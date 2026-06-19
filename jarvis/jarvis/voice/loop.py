"""Main voice loop — listen, transcribe, send to JARVIS, speak back."""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from typing import Any, Optional

import uuid

from jarvis.voice.core import (
    AudioCapture,
    GUARD_FILE_PATH,
    KILL_FILE_PATH,
    TTSEngine,
    Transcriber,
    VoiceConfig,
    VoiceLLMClient,
    activate_guard,
    clear_kill_signal,
    deactivate_guard,
    guard_active,
    kill_requested,
)
from jarvis.voice.log import VoiceLogger, VoiceLogEntry

logger = logging.getLogger("jarvis.voice.loop")


class VoiceLoop:
    """Continuous voice interaction loop.

    Listens for speech, transcribes it, sends to JARVIS, and speaks the response.
    Optionally supports wake-word activation (e.g. "Hey JARVIS").
    """

    def __init__(self, config: Optional[VoiceConfig] = None) -> None:
        self.config = config or VoiceConfig()
        self._running = False
        self._loop_thread: Optional[threading.Thread] = None

        self.capture = AudioCapture(self.config)
        self.transcriber = Transcriber(self.config)
        self.client = VoiceLLMClient()
        self.tts = TTSEngine(self.config)
        # Wire TTS interrupt so VAD can cut off JARVIS mid-speech
        self.capture._tts_interrupt_cb = self.tts.interrupt
        self.voice_log = VoiceLogger()

        # Warm up Whisper model on start
        self._warm_up()

    def __enter__(self) -> VoiceLoop:
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()
        self.cleanup()

    def cleanup(self) -> None:
        """Release loaded models and resources."""
        self.transcriber.cleanup()
        self.tts.cleanup()
        logger.debug("VoiceLoop resources released")

    def _warm_up(self) -> None:
        """Pre-load the Whisper model so first utterance isn't slow."""
        logger.info("Warming up Whisper model...")
        import numpy as np
        warmup = np.zeros(int(self.config.sample_rate * 0.5), dtype=np.int16)
        try:
            self.transcriber.transcribe(warmup)
            logger.info("Whisper model ready")
        except Exception as exc:
            logger.warning("Whisper warm-up failed (will retry on first use): %s", exc)

    def _play_confirmation_tone(self) -> None:
        """Play a short rising tone to confirm JARVIS is listening."""
        try:
            import numpy as np
            import sounddevice as sd
            fs = self.config.sample_rate
            t = np.linspace(0, 0.15, int(fs * 0.15), endpoint=False)
            # Rising tone: 440 Hz → 880 Hz
            tone = (np.sin(2 * np.pi * 440 * t + np.pi * 440 * t**2 / 0.15) * 0.3).astype(np.float32)
            sd.play(tone, samplerate=fs)
            sd.wait()
        except Exception as exc:
            logger.warning("Confirmation tone failed: %s", exc)

    def _wake_word_detect(self) -> Optional[Any]:
        """Listen for a wake word in speech segments.

        Captures up to `wake_listen_seconds` of audio, transcribes it,
        and checks if the configured wake word appears in the text.
        Returns the full audio segment if wake word is detected, else None.
        """
        import re as _re
        import numpy as np

        wake_word = self.config.wake_word.lower().strip()
        listen_duration = 2.0
        max_attempts = int(self.config.max_listen_seconds / listen_duration)

        logger.info("Waiting for wake word '%s'...", wake_word)

        for attempt in range(max_attempts):
            if not self._running:
                return None

            audio = self.capture.record_seconds(listen_duration)
            if audio is None or len(audio) < int(self.config.sample_rate * 0.5):
                continue

            text = self.transcriber.transcribe(audio)
            if not text:
                continue

            logger.debug("Wake word check (%d/%d): '%s'", attempt + 1, max_attempts, text[:60])
            if _re.search(_re.escape(wake_word), text.lower()):
                logger.info("Wake word detected: '%s' in '%s'", wake_word, text[:80])
                return audio

        logger.info("Wake word not detected after %.0fs", max_attempts * listen_duration)
        return None

    def _process_utterance(self, mute_cooldown: float = 0.0) -> bool:
        """Listen, transcribe, send, speak — returns True if utterance was handled.

        If wake_word_enabled, first waits for the wake word, then
        proceeds to full utterance capture for the actual command.
        After speaking, pauses for *mute_cooldown* seconds to prevent echo
        feedback (mic hearing its own speaker output).
        """
        logger.debug("Listening for voice...")

        # ── Wake word phase ────────────────────────────────────
        if self.config.wake_word_enabled:
            wake_audio = self._wake_word_detect()
            if wake_audio is None:
                return False  # Wake word not detected
            logger.debug("Wake word confirmed. Now listening for command...")
            # Play a brief confirmation tone to indicate JARVIS is listening
            self._play_confirmation_tone()

        # ── Full utterance capture ─────────────────────────────
        audio = self.capture.wait_for_voice()
        if audio is None or len(audio) < int(self.config.sample_rate * 1.0):
            return False  # Too short, likely noise

        duration = len(audio) / self.config.sample_rate
        logger.info("Captured %.1f seconds of audio", duration)

        text = self.transcriber.transcribe(audio)
        if not text:
            logger.info("No speech detected in %.1fs of audio", duration)
            return True  # Noise but we consumed the buffer

        logger.info("You said: %s", text)

        # Stream response through pipelined TTS — tokens arrive from Ollama,
        # go directly to Piper synthesis and playback
        token_gen = self.client.stream_send(text)
        collected: list[str] = []

        # Wrap generator to log tokens as they arrive
        def _logging_gen() -> Any:  # noqa: ANN401
            for token in token_gen:
                collected.append(token)
                yield token

        self.tts.speak_streaming(_logging_gen())
        tts_text = "".join(collected).strip()
        logger.info("JARVIS says: %s", tts_text)

        # Log the interaction
        try:
            self.voice_log.append(VoiceLogEntry(
                utterance_id=str(uuid.uuid4()),
                timestamp=time.time(),
                duration=duration,
                transcription=text,
                response_text=tts_text,
                response_path="conversation",
                wake_word=self.config.wake_word_enabled,
            ))
        except Exception as exc:
            logger.warning("Failed to log voice interaction: %s", exc)

        # Set echo suppression window with 1.5s grace period after playback ends
        # to prevent mic hearing the last sentence's speaker output as new speech
        self.capture._tts_last_speech = time.time() + 1.5
        # Mute cooldown — let Piper's audio from the speakers fade out before
        # the next VAD cycle starts, preventing echo feedback loops.
        if mute_cooldown > 0 and self._running:
            logger.debug("Mute cooldown %.1fs (preventing echo)", mute_cooldown)
            time.sleep(mute_cooldown)

    def run_forever(self, interval_between_utterances: float = 0.3, mute_cooldown: float = 0.0) -> None:
        """Run the voice loop continuously until stopped."""
        self._running = True
        logger.info("Voice loop started. Speak to JARVIS!")
        self.tts.speak("JARVIS is listening.")

        try:
            while self._running:
                try:
                    self._process_utterance(mute_cooldown=mute_cooldown)
                    # Kill switch check — touch ~/.jarvis_voice_kill to
                    # stop the loop on the next cycle without Ctrl+C
                    if kill_requested():
                        logger.info("Kill switch triggered")
                        clear_kill_signal()
                        break
                    # Brief pause between utterances
                    if self._running:
                        time.sleep(interval_between_utterances)
                except KeyboardInterrupt:
                    break
                except Exception as exc:
                    logger.error("Voice loop error: %s", exc, exc_info=True)
                    time.sleep(1.0)
        finally:
            self._running = False
            logger.info("Voice loop stopped")

    def run_once(self, mute_cooldown: float = 0.0) -> None:
        """Listen for one utterance, process it, and return."""
        self._running = True
        try:
            self._process_utterance(mute_cooldown=mute_cooldown)
        finally:
            self._running = False

    def stop(self) -> None:
        """Signal the voice loop to stop."""
        self._running = False
        self.capture.stop()


def main() -> None:
    """CLI entry point for the JARVIS voice assistant."""
    import argparse
    import atexit
    import os

    parser = argparse.ArgumentParser(description="JARVIS Voice Assistant")
    parser.add_argument(
        "--model",
        default="tiny",
        choices=["tiny", "base", "small", "medium"],
        help="Whisper model size (default: tiny — fastest, good for clean speech)",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Input device index (default: system default)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one utterance and exit",
    )
    parser.add_argument(
        "--tts",
        default="piper",
        choices=["say", "piper", "none"],
        help="TTS engine (default: piper)",
    )
    parser.add_argument(
        "--sensitivity",
        default="medium",
        choices=["low", "medium", "high"],
        help="VAD sensitivity — 'low' needs louder speech, 'high' catches whispers (default: medium)",
    )
    parser.add_argument(
        "--mute-cooldown",
        type=float,
        default=0.0,
        help="Seconds to mute mic after TTS to prevent echo feedback (default: 0.0 — no cooldown)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Use HTTP to connect to running JARVIS API instead of in-process",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="JARVIS API URL (used with --http)",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="JARVIS API key (used with --http)",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available audio devices and exit",
    )
    parser.add_argument(
        "--wake",
        action="store_true",
        default=False,
        help="Enable wake word activation ('Hey JARVIS') — mic listens all the time",
    )
    parser.add_argument(
        "--wake-word",
        default="jarvis",
        help="Wake word to listen for (default: jarvis)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Bypass the voice guard file check and start anyway",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        default=False,
        help="Create the voice guard file (grants mic permission)",
    )
    parser.add_argument(
        "--deactivate",
        action="store_true",
        default=False,
        help="Remove the voice guard file (revokes mic permission)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        default=False,
        help="Show whether the voice guard is active and exit",
    )
    parser.add_argument(
        "--kill",
        action="store_true",
        default=False,
        help="Send a kill signal to a running voice loop (touch ~/.jarvis_voice_kill)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Check guard, print what would happen, and exit without starting",
    )

    args = parser.parse_args()

    if args.list_devices:
        import sounddevice as sd
        print("Available audio devices:")
        print(sd.query_devices())
        return

    # ── Guard file management ────────────────────────────────
    if args.status:
        if guard_active():
            print(f"🔓 Voice guard ACTIVE — mic permission granted")
            print(f"   File: {GUARD_FILE_PATH}")
        else:
            print(f"🔒 Voice guard INACTIVE — microphone blocked")
            print(f"   Create: python -m jarvis.voice.loop --activate")
        return

    if args.kill:
        KILL_FILE_PATH.touch()
        print(f"⚠️  Kill signal sent to running voice loop")
        print(f"   File: {KILL_FILE_PATH}")
        return

    if args.activate:
        if activate_guard():
            print(f"✅ Voice guard created — mic permission granted now")
        else:
            print(f"ℹ️  Voice guard already active")
        return

    if args.deactivate:
        if deactivate_guard():
            print(f"✅ Voice guard removed — microphone locked down")
        else:
            print(f"ℹ️  Voice guard was not active")
        return

    # ── Guard check ──────────────────────────────────────────
    if not guard_active() and not args.force:
        print("🔒 Microphone BLOCKED by voice guard")
        print(f"   Run with --activate to grant permission")
        print(f"   Or run with --force to bypass (not recommended)")
        print(f"   Check: python -m jarvis.voice.loop --status")
        return

    # ── Dry run ──────────────────────────────────────────────
    if args.dry_run:
        print("✅ Dry run — all checks passed, would start voice loop")
        print(f"   Guard: {'ACTIVE' if guard_active() else 'bypassed (--force)'}")
        print(f"   Model: {args.model}")
        print(f"   TTS: {args.tts}")
        print(f"   Sensitivity: {args.sensitivity}")
        print(f"   Mode: {'HTTP' if args.http else 'In-process'}")
        print(f"   Wake word: {'ON' if args.wake else 'OFF'}")
        print("   (no microphone opened — use without --dry-run to start)")
        return

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    config = VoiceConfig(
        whisper_model_size=args.model,
        input_device=args.device,
        tts_engine=args.tts,
        sensitivity=args.sensitivity,
        in_process=not args.http,
        api_url=args.api_url,
        api_key=args.api_key,
        wake_word_enabled=args.wake,
        wake_word=args.wake_word,
    )

    loop = VoiceLoop(config)
    _loop_ref = loop  # keep ref for atexit

    def _handle_signal(signum: int, _frame: Any) -> None:
        logger.info("Signal %d received, shutting down...", signum)
        loop.stop()

    @atexit.register
    def _cleanup_on_exit() -> None:
        """Guarantee cleanup on normal exit, signals, and crashes."""
        _loop_ref.stop()
        _loop_ref.cleanup()
        deactivate_guard()
        logger.info("🔒 Voice resources and guard released")

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        if args.once:
            loop.run_once(mute_cooldown=args.mute_cooldown)
        else:
            print("")
            print("┌─────────────────────────────────────────────┐")
            print("│  🎤 JARVIS MICROPHONE IS NOW ACTIVE         │")
            print("│  Speak clearly — everything you say is      │")
            print("│  transcribed and sent to the JARVIS runtime. │")
            print("└─────────────────────────────────────────────┘")
            print("")
            print(f"   Model: {args.model}  |  TTS: {args.tts}  |  Sensitivity: {args.sensitivity}")
            print(f"   Mute cooldown: {args.mute_cooldown}s  |  Mode: {'HTTP' if args.http else 'In-process'}")
            print(f"   PID: {os.getpid()}  |  Guard: {GUARD_FILE_PATH}")
            print("")
            print("   ❖ Press Ctrl+C to stop the loop")
            print(f"   ❖ Kill switch: python -m jarvis.voice.loop --kill")
            print("")
            loop.run_forever(mute_cooldown=args.mute_cooldown)
    finally:
        loop.cleanup()
    print("🔒 Microphone released — all resources cleaned up")


if __name__ == "__main__":
    main()