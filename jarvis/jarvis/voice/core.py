"""Voice I/O core: audio capture, transcription, JARVIS integration, and TTS."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
import json
import logging
import os
import subprocess
import sys
import threading
import time

from jarvis.voice.voice_manager import VoiceManager

import numpy as np
import sounddevice as sd

logger = logging.getLogger("jarvis.voice")

# ── Guard File ───────────────────────────────────────────────────────────────
# When present, allows the voice loop to open the microphone.
# Without it, the loop refuses to start unless --force is passed.

GUARD_FILE_PATH = Path.home() / ".jarvis_voice_guard"
KILL_FILE_PATH = Path.home() / ".jarvis_voice_kill"


def guard_active() -> bool:
    """Return True if the guard file exists (mic permission granted)."""
    return GUARD_FILE_PATH.exists()


def activate_guard() -> bool:
    """Create the guard file. Returns True if newly created."""
    if guard_active():
        return False
    GUARD_FILE_PATH.touch(exist_ok=True)
    logger.info("🔓 Voice guard activated (%s)", GUARD_FILE_PATH)
    return True


def deactivate_guard() -> bool:
    """Remove the guard file. Returns True if it existed."""
    if not guard_active():
        return False
    GUARD_FILE_PATH.unlink(missing_ok=True)
    logger.info("🔒 Voice guard deactivated (%s)", GUARD_FILE_PATH)
    return True


def kill_requested() -> bool:
    """Return True if the kill switch file exists (request to stop immediately)."""
    return KILL_FILE_PATH.exists()


def clear_kill_signal() -> None:
    """Consume the kill signal so it doesn't persist."""
    KILL_FILE_PATH.unlink(missing_ok=True)


# ── Config ───────────────────────────────────────────────────────────────────

@dataclass
class VoiceConfig:
    """Configuration for the voice loop."""

    # Audio
    sample_rate: int = 16000
    block_duration: float = 0.5  # seconds per audio block for monitoring
    silence_rms_threshold: float = 0.001  # RMS (normalized float [-1,1]) below this = silence
    voice_rms_threshold: float = 0.004  # RMS (normalized float [-1,1]) above this = voice started
    silence_timeout: float = 0.5  # seconds of silence to end utterance
    max_record_seconds: float = 30.0
    max_listen_seconds: float = 120.0  # max seconds to wait for speech before returning
    input_device: Optional[int] = None  # None = system default

    # Transcription
    whisper_model_size: str = "tiny"  # tiny, base, small, medium, large
    whisper_device: str = "auto"  # auto, cpu, cuda
    whisper_compute_type: str = "int8"  # default, float16, int8

    # JARVIS
    in_process: bool = True  # True = import JarvisApp directly; False = HTTP
    api_url: str = "http://localhost:8000"
    api_key: str = ""

    # TTS
    tts_engine: str = "piper"  # "say", "piper", "none"
    piper_path: str = "/usr/local/bin/piper"
    piper_voice: str = "en_US-lessac-medium"
    piper_rate: float = 1.0

    # Sensitivity — adjusts voice/silence multiplier vs ambient
    sensitivity: str = "medium"  # "low", "medium", "high"

    # Voice activity
    wake_word_enabled: bool = False
    wake_word: str = "jarvis"

    def apply_env_defaults(self) -> None:
        import os as _os
        if _os.getenv("JARVIS_VOICE_MODEL"):
            self.whisper_model_size = _os.getenv("JARVIS_VOICE_MODEL", self.whisper_model_size)
        if _os.getenv("JARVIS_VOICE_TTS"):
            self.tts_engine = _os.getenv("JARVIS_VOICE_TTS", self.tts_engine)
        if _os.getenv("JARVIS_VOICE_SEARCH") is not None:
            self.wake_word_enabled = _os.getenv("JARVIS_VOICE_SEARCH", "").lower() not in {"0", "false", "no", "off"}
            self.wake_word = _os.getenv("JARVIS_VOICE_WORD", self.wake_word)


# ── Audio Capture ───────────────────────────────────────────────────────────

class AudioCapture:
    """Captures microphone audio with energy-based VAD."""

    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self._stop_event = threading.Event()
        self._tts_last_speech: float = 0.0  # shared TTS playback timestamp
        self._tts_interrupt_cb: Any = None  # callable to interrupt TTS

    def __enter__(self) -> AudioCapture:
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()

    def __del__(self) -> None:
        self.stop()

    def stop(self) -> None:
        self._stop_event.set()

    def _auto_calibrate(self) -> tuple[float, float]:
        """Measure ambient noise floor, return (silence_rms, voice_rms) thresholds.

        Records 1.5 seconds of mic input, computes median RMS across blocks,
        and sets thresholds relative to the ambient floor.
        """
        fs = self.config.sample_rate
        block = int(fs * 0.25)  # 250ms blocks for calibration
        blocks_needed = 1  # minimum capture block
        rms_blocks: list[float] = []
        rms_blocks: list[float] = []

        def cal_callback(indata: np.ndarray, _frames: int, _info: Any, _status: Any) -> None:
            rms = float(np.sqrt(np.mean((indata.astype(np.float64) / 32768.0) ** 2)))
            rms_blocks.append(rms)
            if len(rms_blocks) >= blocks_needed:
                raise sd.CallbackStop

        try:
            with sd.InputStream(
                device=self.config.input_device,
                samplerate=fs,
                channels=1,
                blocksize=block,
                callback=cal_callback,
                dtype="int16",
            ):
                while len(rms_blocks) < blocks_needed:
                    sd.sleep(50)
        except sd.CallbackStop:
            pass

        if not rms_blocks:
            ambient_rms = 0.005  # fallback
        else:
            ambient_rms = float(np.median(rms_blocks))

        # Sensitivity presets — trade-off between catching quiet speech vs
        # false triggers from ambient noise
        _SENSITIVITY_MAP = {
            "high":   (1.1, 1.5),   # voice at 1.5x ambient — catches whispers
            "medium": (1.3, 2.5),   # voice at 2.5x ambient — good for normal rooms
            "low":    (1.8, 4.0),   # voice at 4.0x ambient — needs louder speech
        }
        sil_mult, voice_mult = _SENSITIVITY_MAP.get(
            self.config.sensitivity.lower(), (1.3, 2.5)
        )

        silence_rms = max(ambient_rms * sil_mult, 0.0005)
        voice_rms = max(ambient_rms * voice_mult, 0.002)

        if ambient_rms >= 0.03:
            voice_rms = min(voice_rms, 0.02)
            silence_rms = min(silence_rms, 0.008)

        if ambient_rms >= 0.06:
            room_mult = 1.2
            voice_rms = max(voice_rms, ambient_rms * room_mult)
            silence_rms = max(ambient_rms * 0.9, 0.005)

        # Cap thresholds so they never become impossible to cross.
        cap = 0.06
        if voice_rms > cap:
            voice_rms = cap
        if silence_rms > cap * 0.5:
            silence_rms = cap * 0.5
        logger.info(
            "VAD calibrated: ambient=%.5f  silence_thresh=%.5f  voice_thresh=%.5f  (sensitivity=%s)",
            ambient_rms, silence_rms, voice_rms, self.config.sensitivity,
        )
        return silence_rms, voice_rms

    def wait_for_voice(self) -> Optional[np.ndarray]:
        """Monitor mic until voice crosses threshold, then capture utterance.

        Auto-calibrates noise floor at the start of each call.
        Returns recorded audio as int16 numpy array, or None on interrupt.
        """
        silence_thresh, voice_thresh = self._auto_calibrate()
        fs = self.config.sample_rate
        block = int(fs * self.config.block_duration)  # samples per block
        max_samples = int(fs * self.config.max_record_seconds)

        audio_buffer: list[np.ndarray] = []
        silence_blocks = 0
        silence_limit = int(self.config.silence_timeout / self.config.block_duration)
        voice_active = False
        total_samples = 0

        def callback(indata: np.ndarray, frames: int, _time_info: Any, status: Any) -> None:
            nonlocal voice_active, silence_blocks, total_samples
            if status:
                logger.warning("sounddevice status: %s", status)

            rms = np.sqrt(np.mean((indata.astype(np.float64) / 32768.0) ** 2))

            # Echo suppression: if TTS was speaking < 300ms ago, ignore this block
            # BUT: if voice continues past the suppression window, it's the user
            # talking over JARVIS — interrupt TTS immediately
            if time.time() < self._tts_last_speech:
                if not voice_active:
                    return  # Still in quiet phase — ignore echo
                # If voice was already active, continue capture (user may be talking over TTS)

            # Interruption: if TTS is still playing and voice exceeds threshold,
            # kill TTS immediately so JARVIS stops talking
            if (
                rms >= voice_thresh
                and not voice_active
                and self._tts_interrupt_cb is not None
                and time.time() < self._tts_last_speech + 3.0
            ):
                logger.info("🔊 Voice detected during TTS — interrupting")
                self._tts_interrupt_cb()
                # Don't return — let this be treated as the start of a new utterance
                voice_active = True
                audio_buffer.append(indata.copy())
                total_samples += frames
                return

            if rms >= voice_thresh and not voice_active:
                voice_active = True
                logger.debug("Voice started (rms=%.4f)", rms)
                # include the block that triggered voice
                audio_buffer.append(indata.copy())
                total_samples += frames

            elif voice_active:
                if rms < silence_thresh:
                    silence_blocks += 1
                else:
                    silence_blocks = 0
                audio_buffer.append(indata.copy())
                total_samples += frames

                if silence_blocks >= silence_limit or total_samples >= max_samples:
                    raise sd.CallbackStop

        try:
            with sd.InputStream(
                device=self.config.input_device,
                samplerate=fs,
                channels=1,
                blocksize=block,
                callback=callback,
                dtype="int16",
            ):
                start = time.time()
                while not self._stop_event.is_set():
                    elapsed = time.time() - start
                    if elapsed >= self.config.max_listen_seconds:
                        logger.debug("Max listen time reached (%.0fs)", elapsed)
                        break
                    sd.sleep(100)
        except sd.CallbackStop:
            pass  # Expected — utterance ended

        if not audio_buffer:
            return None

        raw = np.concatenate(audio_buffer).ravel()
        return raw

    def record_seconds(self, duration: float) -> Optional[np.ndarray]:
        """Record a fixed-duration clip from the microphone."""
        fs = self.config.sample_rate
        samples = int(fs * duration)
        try:
            recording = sd.rec(
                samples,
                samplerate=fs,
                channels=1,
                device=self.config.input_device,
                dtype="int16",
            )
            sd.wait()
            return recording.ravel()
        except Exception as exc:
            logger.error("Recording failed: %s", exc)
            return None


# ── Transcriber ─────────────────────────────────────────────────────────────

class Transcriber:
    """Speech-to-text via faster-whisper."""

    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self._model = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        logger.info(
            "Loading Whisper model '%s' on device=%s compute=%s",
            self.config.whisper_model_size,
            self.config.whisper_device,
            self.config.whisper_compute_type,
        )
        self._model = WhisperModel(
            self.config.whisper_model_size,
            device=self.config.whisper_device,
            compute_type=self.config.whisper_compute_type,
        )

    def cleanup(self) -> None:
        """Release the Whisper model to free ~1GB RAM."""
        self._model = None
        logger.debug("Whisper model released")

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio (int16) to text."""
        self._load()

        # Convert int16 to float32 (faster-whisper expects float32 in [-1, 1])
        audio_float = audio.astype(np.float32) / 32768.0

        with self._lock:
            segments, info = self._model.transcribe(audio_float, beam_size=5, language="en")
            text = " ".join(seg.text for seg in segments)

        if not text.strip():
            return ""

        # Determine language from first segment metadata
        lang = getattr(info, "language", None) or "en"
        logger.debug("Transcribed (lang=%s): %s", lang, text[:80])
        return text.strip()


# ── TTS Engine ────────────────────────────────────────────────────────────────


class TTSEngine:
    """Text-to-speech output through system speakers."""

    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self._piper_voice = None  # lazy-loaded
        self._voice_manager = VoiceManager()
        self._playback_process: Optional["subprocess.Popen[bytes]"] = None
        self._interrupted: bool = False
        self.last_speech_at: float = 0.0
        self.last_speech_till: float = 0.0

    def cleanup(self) -> None:
        """Release the Piper voice model and kill any active playback."""
        self._stop_playback()
        self._piper_voice = None

    def interrupt(self) -> None:
        """Interrupt TTS playback immediately (user is speaking over it)."""
        self._interrupted = True
        self._stop_playback()

    def _stop_playback(self) -> None:
        """Kill any running afplay playback process."""
        if self._playback_process is not None:
            try:
                self._playback_process.kill()
            except Exception:
                pass
            self._playback_process = None

    def speak(self, text: str) -> None:
        """Speak text through default audio output."""
        if not text.strip():
            return

        engine = self.config.tts_engine
        logger.debug("TTS (%s): %s", engine, text[:60])

        if engine == "say":
            self._speak_say(text)
        elif engine == "piper":
            self._speak_piper(text)
        elif engine == "none":
            logger.info("TTS suppressed: %s", text)
        else:
            logger.warning("Unknown TTS engine: %s", engine)

    def speak_streaming(self, text_generator) -> None:
        """Truly streaming TTS: speak the first sentence as soon as it forms.

        Accumulates tokens from the generator into a buffer. When a sentence
        boundary is reached (ending with . ! or ?), immediately starts
        synthesizing and playing that sentence while continuing to collect
        more tokens for the next one.
        """
        import re as _re
        import tempfile
        import wave

        if not text_generator:
            return

        buffer = ""
        prev_process: Optional["subprocess.Popen[bytes]"] = None
        piper_loaded = False
        self._interrupted = False

        def _synthesize_and_play(sentence: str) -> Optional["subprocess.Popen[bytes]"]:
            """Synthesize a single sentence and play it, returning the process."""
            nonlocal piper_loaded
            try:
                if not piper_loaded:
                    self._ensure_piper_loaded()
                    piper_loaded = True

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    wav_path = tmp.name

                wav_file = wave.open(wav_path, "w")
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(22050)
                self._piper_voice.synthesize_wav(sentence, wav_file)
                wav_file.close()

                proc = subprocess.Popen(["afplay", wav_path])
                proc._wav_path = wav_path  # type: ignore[attr-defined]
                self.last_speech_at = time.time()
                return proc
            except Exception as exc:
                logger.error("Streaming TTS synthesis failed: %s", exc)
                return None

        for token in text_generator:
            if self._interrupted:
                logger.debug("TTS interrupted mid-stream")
                break
            buffer += token

            # Check if buffer contains a complete sentence
            match = _re.search(r"(.*?[.!?])\s*$", buffer)
            if match:
                sentence = match.group(1).strip()
                if sentence:
                    # Wait for previous playback to finish
                    if prev_process is not None:
                        try:
                            prev_process.wait(timeout=30)
                        except Exception:
                            pass
                        try:
                            Path(prev_process._wav_path).unlink(missing_ok=True)  # type: ignore[attr-defined]
                        except Exception:
                            pass

                    # Synthesize this sentence and start playback
                    proc = _synthesize_and_play(sentence)
                    if proc:
                        prev_process = proc
                    buffer = ""

        # Handle any remaining text in buffer (no sentence-ending punctuation)
        buffer = buffer.strip()
        if buffer:
            if prev_process is not None:
                try:
                    prev_process.wait(timeout=30)
                except Exception:
                    pass
                try:
                    Path(prev_process._wav_path).unlink(missing_ok=True)  # type: ignore[attr-defined]
                except Exception:
                    pass
            proc = _synthesize_and_play(buffer)
            if proc:
                prev_process = proc

        # Wait for last playback and set end timestamp
        if prev_process is not None:
            try:
                prev_process.wait(timeout=30)
            except Exception:
                pass
            self.last_speech_till = time.time()
            try:
                Path(prev_process._wav_path).unlink(missing_ok=True)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _ensure_piper_loaded(self) -> None:
        """Load the Piper voice model if not already loaded."""
        if self._piper_voice is not None:
            return
        from piper import PiperVoice
        voice_dir = Path(__file__).resolve().parent.parent.parent / "piper_voices"
        flag = voice_dir / ".voice_changed"
        if flag.exists():
            flag.unlink(missing_ok=True)
        selected_id = self._voice_manager.get_selected_voice()
        paths = self._voice_manager.get_voice_paths(selected_id)
        if not paths:
            self._voice_manager.select_voice("en_US-lessac-medium")
            paths = self._voice_manager.get_voice_paths("en_US-lessac-medium")
            if not paths:
                raise FileNotFoundError("Default voice not available")
        onnx_path = paths["onnx"]
        config_path = paths["json"]
        logger.info("Loading Piper voice '%s' from %s", selected_id, onnx_path)
        self._piper_voice = PiperVoice.load(onnx_path, config_path=config_path)

    def _speak_say(self, text: str) -> None:
        """Use macOS `say` command."""
        cleaned = text.replace('"', "'")
        try:
            subprocess.run(
                ["say", cleaned],
                timeout=120,
                capture_output=True,
            )
            self.last_speech_till = time.time()
        except subprocess.TimeoutExpired:
            logger.warning("TTS timed out")
        except FileNotFoundError:
            logger.error("`say` command not found — TTS unavailable")

    def _speak_piper(self, text: str) -> None:
        """Use Piper TTS for natural-sounding voice output.

        Lazy-loads the Piper voice model and writes a temp WAV for playback.
        Checks the voice change flag before loading to pick up voice switches.
        """
        import tempfile
        import wave

        try:
            if self._piper_voice is None:
                from piper import PiperVoice

                voice_dir = (
                    Path(__file__).resolve().parent.parent.parent / "piper_voices"
                )
                # Check if voice was changed via API
                flag = voice_dir / ".voice_changed"
                if flag.exists():
                    flag.unlink(missing_ok=True)
                selected_id = self._voice_manager.get_selected_voice()
                paths = self._voice_manager.get_voice_paths(selected_id)
                if not paths:
                    logger.error("Voice '%s' not found — falling back to default", selected_id)
                    self._voice_manager.select_voice("en_US-lessac-medium")
                    paths = self._voice_manager.get_voice_paths("en_US-lessac-medium")
                    if not paths:
                        raise FileNotFoundError("Default voice not available")
                onnx_path = paths["onnx"]
                config_path = paths["json"]
                logger.info("Loading Piper voice '%s' from %s", selected_id, onnx_path)
                self._piper_voice = PiperVoice.load(
                    onnx_path, config_path=config_path
                )

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                wav_path = tmp.name

            wav_file = wave.open(wav_path, "w")
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            self._piper_voice.synthesize_wav(text, wav_file)
            wav_file.close()

            self.last_speech_at = time.time()
            # Estimate TTS playback end time for echo suppression
            # Piper at 22050Hz: ~12 chars/sec for English. Add 0.5s buffer.
            est_duration = max(len(text) / 12, 0.5) + 0.3
            self.last_speech_till = time.time() + est_duration
            self._playback_process = subprocess.Popen(
                ["afplay", wav_path],
            )
            # Clean up wav file in a background thread after a delay
            def _cleanup_wav() -> None:
                time.sleep(30.0)
                try:
                    Path(wav_path).unlink(missing_ok=True)
                except Exception:
                    pass

            threading.Thread(target=_cleanup_wav, daemon=True).start()

        except Exception as exc:
            logger.error("Piper TTS failed: %s", exc)
        finally:
            # wav cleanup is handled in a background thread
            pass


# ── Response Formatter ──────────────────────────────────────────────────────

def format_response_for_tts(response: Dict[str, Any]) -> str:
    """Convert a JARVIS handle_text response into a TTS-friendly string."""
    if not isinstance(response, dict):
        return "JARVIS could not process that request."

    if response.get("error"):
        return f"Error: {response['error']}"

    if response.get("requires_approval"):
        action = response.get("action", "something")
        reason = response.get("reason", "")
        return f"I need your approval to {action}. {reason}. Check the dashboard to approve or deny."

    if response.get("denied"):
        reason = response.get("reason", "that action is not allowed")
        return f"That action is denied. {reason}"

    if response.get("path") == "drift_check":
        report = response.get("drift_report", {})
        missing = report.get("missing", [])
        if missing:
            return f"Drift check complete. Missing capabilities: {', '.join(missing)}. Everything else is in sync."
        return "Drift check complete. No capabilities have drifted. All systems are in sync."

    if response.get("path") == "direct_response":
        return response.get("response", "I'm ready. What would you like me to do?")

    if response.get("tool_result"):
        result = response.get("tool_result", {})
        if isinstance(result, dict) and result.get("ok"):
            return "Done. The action completed successfully."
        if isinstance(result, dict) and result.get("error"):
            return f"The action had an issue: {result['error']}"
        return "Done."

    if response.get("path") == "fallback":
        return "I couldn't process that request. Could you rephrase it?"

    return "Request received. Check the dashboard for details."


# ── JARVIS Client ───────────────────────────────────────────────────────────

class JarvisClient:
    """Interface to send text to JARVIS and get a response."""

    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self._jarvis_app: Any = None
        self._session_id: str = f"voice-{int(time.time())}"

        if config.in_process:
            self._init_in_process()

    def _init_in_process(self) -> None:
        """Import and instantiate JarvisApp directly."""
        # Ensure the project root is on sys.path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from jarvis.main import JarvisApp

        self._jarvis_app = JarvisApp()
        logger.info("JARVIS voice client initialized (in-process)")

    def send(self, text: str) -> Dict[str, Any]:
        """Send transcribed text to JARVIS and return the response."""
        if self._jarvis_app:
            return self._jarvis_app.handle_text(session_id=self._session_id, text=text)

        # HTTP mode fallback
        import http.client
        import urllib.parse

        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key

        try:
            import urllib.request

            body = json.dumps({"session_id": self._session_id, "text": text}).encode()
            req = urllib.request.Request(
                f"{self.config.api_url}/control/ingest",
                data=body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            logger.error("HTTP request to JARVIS failed: %s", exc)
            return {"error": str(exc), "path": "error"}


# ── Voice LLM Client (new) ────────────────────────────────────────────────────

class VoiceLLMClient:
    """Conversational LLM client for the voice loop.

    Uses StreamingLLM + Conversation to talk directly to the LLM with
    proper voice-optimized prompts and conversation history, bypassing
    the JarvisApp routing layer. Optional Tavily web search for current
    events queries.
    """

    def __init__(self, enable_search: bool = True) -> None:
        from jarvis.voice.llm_client import Conversation, StreamingLLM

        self.llm = StreamingLLM()
        self.conversation = Conversation()
        self._search_enabled = enable_search
        logger.info("VoiceLLMClient initialized (search=%s)", enable_search)

    def send(self, text: str) -> str:
        """Send user text to LLM and return the full response."""
        self._inject_search(text)
        self.conversation.add_user(text)
        response = self.llm.chat(self.conversation)
        return response

    def stream_send(self, text: str):
        """Send user text to LLM and yield response tokens as they arrive."""
        self._inject_search(text)
        self.conversation.add_user(text)
        yield from self.llm.stream_chat(self.conversation)

    def _inject_search(self, text: str) -> None:
        """Run Tavily search if needed and inject results as conversation context.

        Inserts live search context as a transient system message immediately
        before the current user query. This preserves message order across
        multiple turns and makes the web results the clearest context for
        the LLM.
        """
        if not self._search_enabled:
            return
        try:
            from jarvis.voice.searcher import needs_search, search

            if not needs_search(text):
                return

            logger.info("🌐 Searching web for: %s", text[:60])
            context = search(text)
            if not context:
                return

            self.conversation.messages.append({"role": "system", "content": context})
            logger.info("🌐 Web results injected (message #%d)", len(self.conversation.messages))
        except Exception as exc:
            logger.warning("Web search injection failed: %s", exc)

    def reset(self) -> None:
        """Clear conversation history (keep system prompt)."""
        self.conversation.reset()
        logger.info("VoiceLLMClient conversation reset")