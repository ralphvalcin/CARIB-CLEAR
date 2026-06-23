"""Kokoro TTS backend — fully open-source, runs locally, tiny model footprint.

Registered as ``kokoro`` in TTSRegistry.

Replaces Piper for voice synthesis. Kokoro is MIT-licensed, downloads models
on first use (~82MB total), and supports multiple voices and languages.
"""

from __future__ import annotations

import io
import logging
from typing import Any, List, Optional

import numpy as np
import soundfile as sf

from jarvis.voice.registry import TTSBackend, TTSRegistry

logger = logging.getLogger("jarvis.voice.kokoro")

# Kokoro voices — fully open-source, no per-voice model files
KOKORO_VOICES: dict[str, dict[str, str]] = {
    "af_heart": {
        "name": "Heart (US Female, warm)",
        "gender": "female",
        "accent": "US",
        "description": "Warm female US English voice (default, Kokoro)",
    },
    "af_bella": {
        "name": "Bella (US Female)",
        "gender": "female",
        "accent": "US",
        "description": "Clear female US English voice",
    },
    "am_adam": {
        "name": "Adam (US Male)",
        "gender": "male",
        "accent": "US",
        "description": "Natural male US English voice",
    },
    "am_michael": {
        "name": "Michael (US Male)",
        "gender": "male",
        "accent": "US",
        "description": "Deep male US English voice",
    },
    # Non-English voices (iso_<lang>_<voice> format)
    "af_sky": {
        "name": "Sky (Multilingual Female)",
        "gender": "female",
        "accent": "Multilingual",
        "description": "Multilingual female voice",
    },
    "am_liam": {
        "name": "Liam (Multilingual Male)",
        "gender": "male",
        "accent": "Multilingual",
        "description": "Multilingual male voice",
    },
    "af_nicole": {
        "name": "Nicole (Multilingual Female)",
        "gender": "female",
        "accent": "Multilingual",
        "description": "Multilingual female voice",
    },
}


@TTSRegistry.register("kokoro")
class KokoroTTSBackend(TTSBackend):
    """Local open-source TTS via Kokoro — no API keys, no cloud calls.

    Model is lazy-loaded on first use. After the first call the pipeline
    stays warm for subsequent utterances.
    """

    backend_id = "kokoro"

    def __init__(self, voice: str = "af_heart", speed: float = 1.0) -> None:
        self._voice = voice
        self._speed = speed
        self._pipeline: Any = None

    def _ensure_pipeline(self) -> Any:
        """Lazy-load the Kokoro pipeline on first use."""
        if self._pipeline is not None:
            return self._pipeline
        try:
            from kokoro import KPipeline

            logger.info("Loading Kokoro TTS pipeline...")
            self._pipeline = KPipeline(lang_code="a")
            logger.info("Kokoro pipeline ready (voice=%s, speed=%.1f)", self._voice, self._speed)
            return self._pipeline
        except ImportError:
            raise RuntimeError("kokoro package not installed. Run: pip install kokoro")

    def synthesize(self, text: str, **kwargs: Any) -> bytes:
        """Synthesize text to WAV audio bytes."""
        if not text.strip():
            return b""

        pipeline = self._ensure_pipeline()
        voice_id = kwargs.get("voice") or self._voice
        speed_val = kwargs.get("speed") or self._speed

        samples: list[np.ndarray] = []
        for gs, ps, audio in pipeline(text, voice=voice_id, speed=speed_val):
            samples.append(audio)

        if not samples:
            logger.warning("Kokoro produced no audio for: %s", text[:60])
            return b""

        combined = np.concatenate(samples)
        buf = io.BytesIO()
        sf.write(buf, combined, 24000, format="WAV")
        buf.seek(0)
        result = buf.getvalue()

        duration = len(combined) / 24000
        logger.debug("Kokoro synthesized %.1fs of audio (%d bytes, voice=%s)", duration, len(result), voice_id)
        return result

    @property
    def voice(self) -> str:
        """Get the current voice ID."""
        return self._voice

    @voice.setter
    def voice(self, voice_id: str) -> None:
        """Set the voice ID. Silently ignores unknown voices."""
        if voice_id in KOKORO_VOICES:
            self._voice = voice_id
            logger.info("Kokoro voice changed to: %s (%s)", voice_id, KOKORO_VOICES[voice_id]["name"])

    def available_voices(self) -> list[dict[str, str]]:
        """Return list of available voices with metadata."""
        return [{"id": vid, **meta} for vid, meta in KOKORO_VOICES.items()]

    def health(self) -> bool:
        """Check if Kokoro is available."""
        try:
            self._ensure_pipeline()
            return True
        except (ImportError, RuntimeError):
            return False

    def cleanup(self) -> None:
        """Release the pipeline and GPU memory (if CUDA)."""
        self._pipeline = None
        logger.debug("Kokoro pipeline released")
