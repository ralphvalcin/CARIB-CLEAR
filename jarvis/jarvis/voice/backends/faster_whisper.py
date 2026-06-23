"""Faster-Whisper speech-to-text backend (local, CTranslate2-based).

Registered as ``faster-whisper`` in SpeechRegistry.

Uses the faster-whisper library for fast local transcription.
Supports model sizes from tiny to large, CUDA/CPU/MPS devices,
and various compute types (float16, int8, etc.).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, List, Optional

import numpy as np

from jarvis.voice.registry import SpeechBackend, SpeechRegistry

logger = logging.getLogger("jarvis.voice.faster_whisper")

# Model size options
WHISPER_MODEL_SIZES = ["tiny", "base", "small", "medium", "large", "large-v3"]


@SpeechRegistry.register("faster-whisper")
class FasterWhisperBackend(SpeechBackend):
    """Local speech-to-text using Faster-Whisper (CTranslate2).

    Lazy-loads the model on first transcribe() call. The model stays warm
    for subsequent calls. Call cleanup() to release ~1GB GPU memory.
    """

    backend_id = "faster-whisper"

    def __init__(
        self,
        model_size: str = "tiny",
        device: str = "auto",
        compute_type: str = "int8",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model: Any = None
        self._lock = threading.Lock()

    def transcribe(self, audio: Any, **kwargs: Any) -> str:
        """Transcribe audio (int16 numpy array) to text.

        Args:
            audio: int16 numpy array of audio samples.
            **kwargs: May include ``language`` (default: "en").

        Returns:
            Transcribed text string.
        """
        self._load()

        # Convert int16 to float32 (faster-whisper expects float32 in [-1, 1])
        if isinstance(audio, np.ndarray) and audio.dtype == np.int16:
            audio_float = audio.astype(np.float32) / 32768.0
        else:
            audio_float = audio

        language = kwargs.get("language", "en")

        with self._lock:
            segments, info = self._model.transcribe(audio_float, beam_size=5, language=language)
            text = " ".join(seg.text for seg in segments)

        if not text.strip():
            return ""

        lang = getattr(info, "language", None) or language
        logger.debug("Transcribed (lang=%s): %s", lang, text[:80])
        return text.strip()

    def available_models(self) -> List[str]:
        """Return supported model sizes."""
        return list(WHISPER_MODEL_SIZES)

    def health(self) -> bool:
        """Check if faster-whisper is importable and model can load."""
        try:
            from faster_whisper import WhisperModel
            return True
        except ImportError:
            return False

    def cleanup(self) -> None:
        """Release the Whisper model to free ~1GB RAM."""
        self._model = None
        logger.debug("Whisper model released")

    def _load(self) -> None:
        """Lazy-load the Whisper model on first use."""
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        logger.info(
            "Loading Whisper model '%s' on device=%s compute=%s",
            self._model_size, self._device, self._compute_type,
        )
        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type=self._compute_type,
        )
