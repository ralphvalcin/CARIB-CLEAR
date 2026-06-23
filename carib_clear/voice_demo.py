"""CARIB-CLEAR Kreyol Voice Demo

Speak a loan request in English or Kreyòl → CARIB-CLEAR processes it → hear the decision.

Requires:
  - A microphone
  - faster-whisper (pip install faster-whisper)
  - sounddevice (pip install sounddevice)
  - Kokoro TTS (pip install kokoro) or macOS `say` fallback

Usage:
    python -m carib_clear.voice_demo            # Single request
    python -m carib_clear.voice_demo --loop      # Continuous mode
    python -m carib_clear.voice_demo --text-only  # Skip audio (text in, text out)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Optional audio dependencies — gracefully degrade
try:
    import sounddevice as sd
    import numpy as np
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

try:
    from kokoro import KPipeline
    import soundfile as sf
    HAS_KOKORO = True
except ImportError:
    HAS_KOKORO = False


# ── Audio Capture ─────────────────────────────────────────────────────

SAMPLE_RATE = 16000
RECORD_SECONDS = 8  # Max recording length


def record_audio(duration: int = RECORD_SECONDS, sample_rate: int = SAMPLE_RATE) -> Optional[bytes]:
    """Record audio from microphone. Returns WAV bytes or None on failure."""
    if not HAS_SOUNDDEVICE:
        logger.error("sounddevice not installed. Install with: pip install sounddevice")
        return None

    print(f"\n🎤 Listening (max {duration}s)... Speak your loan request!")
    print(f"   (Say something like: \"Mwen bezwen $5,000 pou biznis mwen nan Ayiti\")")
    print(f"   Press Ctrl+C when done, or wait for timeout...")

    try:
        recording = sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype=np.int16,
        )
        # Wait for recording to complete or interrupt
        try:
            sd.wait()
        except KeyboardInterrupt:
            # Trim to where user stopped speaking
            sd.stop()
            # Find where user stopped (last non-silent sample)
            data = recording[:int(sd.portaudio.time() * sample_rate)]
            audio_data = data.tobytes()
        else:
            audio_data = recording.tobytes()

        # Convert to WAV in memory
        import io
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data)
        return buf.getvalue()

    except Exception as exc:
        logger.error("Recording failed: %s", exc)
        return None


# ── Speech-to-Text ────────────────────────────────────────────────────

_whisper_model: Optional[WhisperModel] = None


def transcribe(wav_bytes: bytes) -> Optional[str]:
    """Transcribe WAV audio bytes to text using faster-whisper."""
    global _whisper_model

    if not HAS_WHISPER:
        logger.error("faster-whisper not installed. Install with: pip install faster-whisper")
        return None

    if _whisper_model is None:
        logger.info("Loading Whisper model (tiny)...")
        _whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        logger.info("Whisper loaded.")

    try:
        import io
        import tempfile
        # Save to temp file (faster-whisper prefers file paths)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name

        segments, info = _whisper_model.transcribe(
            tmp_path,
            language=None,  # Auto-detect
            beam_size=3,
            vad_filter=True,
        )

        text = " ".join(seg.text for seg in segments).strip()
        Path(tmp_path).unlink(missing_ok=True)

        detected_lang = info.language if info else "en"
        logger.info("Transcribed [%s]: %s", detected_lang, text[:100])
        return text if text else None

    except Exception as exc:
        logger.error("Transcription failed: %s", exc)
        return None


# ── Text-to-Speech ────────────────────────────────────────────────────

_kokoro_pipeline: Optional[KPipeline] = None


def speak(text: str) -> bool:
    """Speak text using Kokoro TTS, falling back to macOS `say`."""
    global _kokoro_pipeline

    if HAS_KOKORO:
        try:
            if _kokoro_pipeline is None:
                logger.info("Loading Kokoro TTS...")
                _kokoro_pipeline = KPipeline(lang_code="a")
                logger.info("Kokoro loaded.")

            print(f"🗣️ {text[:120]}...")

            # Generate audio
            samples = []
            for gs, ps, audio in _kokoro_pipeline(text, voice="af_heart", speed=1.0):
                if audio is not None:
                    samples.append(audio)

            if samples:
                import numpy as np
                audio_data = np.concatenate(samples)

                # Play back
                if HAS_SOUNDDEVICE:
                    sd.play(audio_data, samplerate=24000)
                    sd.wait()
                    return True
                else:
                    logger.warning("sounddevice not available for playback")
                    return False

        except Exception as exc:
            logger.warning("Kokoro TTS failed: %s", exc)

    # Fallback to macOS `say`
    import subprocess
    print(f"🗣️ {text[:120]}...")
    try:
        subprocess.run(["say", text], timeout=30, check=False)
        return True
    except Exception:
        logger.error("Could not speak response")
        return False


# ── Main Demo ─────────────────────────────────────────────────────────


def run_demo_cycle(bridge, text_only: bool = False):
    """Run one voice loan request cycle."""
    from carib_clear.voice_bridge import VoiceLoanBridge

    if bridge is None:
        bridge = VoiceLoanBridge()

    # 1. Get input
    if text_only:
        print("\n📝 Enter your loan request (or 'quit'):")
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return False
        if not text or text.lower() in ("quit", "exit", "q"):
            return False
    else:
        wav_data = record_audio()
        if wav_data is None:
            return False

        print("   Transcribing...")
        text = transcribe(wav_data)
        if not text:
            print("   Could not understand. Try again.")  # noqa: T201
            return True

    # 2. Process through CARIB-CLEAR
    print(f"\n📋 Processing: \"{text}\"")
    result = bridge.process_request(text)

    # 3. Show result
    if result.approved:
        print(f"\n✅ APPROVED — ${result.amount_usd:,.0f}")
    else:
        print(f"\n❌ DECLINED")

    # 4. Speak response
    response = result.response_text
    print(f"\n{response}\n")

    if not text_only:
        speak(response)
        time.sleep(0.5)

    return True


def main():
    parser = argparse.ArgumentParser(description="CARIB-CLEAR Kreyol Voice Demo")
    parser.add_argument("--loop", action="store_true", help="Continuous mode")
    parser.add_argument("--text-only", action="store_true", help="Text input only (no audio)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    from carib_clear.voice_bridge import VoiceLoanBridge
    bridge = VoiceLoanBridge()

    print(f"\n{'='*60}")
    print("  CARIB-CLEAR Kreyol Voice Demo")
    print("  Voice-powered MSME lending for the Caribbean")
    print(f"{'='*60}")

    if args.text_only:
        print("  (Text-only mode — type your loan request)")
    else:
        print("  (Speak into your microphone to request a loan)")
        if not HAS_WHISPER:
            print("  ⚠️  faster-whisper not installed. Install with: pip install faster-whisper")
        if not HAS_KOKORO and sys.platform != "darwin":
            print("  ⚠️  Kokoro TTS not installed. Will use macOS say if available.")
        print()

    if args.loop:
        print("  Continuous mode — press Ctrl+C to exit\n")
        try:
            while run_demo_cycle(bridge, text_only=args.text_only):
                pass
        except KeyboardInterrupt:
            print("\n\nGoodbye!")  # noqa: T201
    else:
        run_demo_cycle(bridge, text_only=args.text_only)


if __name__ == "__main__":
    main()