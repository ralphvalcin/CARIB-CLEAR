"""Piper TTS backend — legacy, uses external Piper CLI/onnx model.

Registered as ``piper`` in TTSRegistry.

Piper runs as a subprocess to Piper's CLI. Voice models are downloaded
separately via VoiceManager. Keep this backend only if you need Piper-specific
voices; Kokoro is the recommended default.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

from jarvis.voice.registry import TTSBackend, TTSRegistry
from jarvis.voice.voice_manager import VoiceManager

logger = logging.getLogger("jarvis.voice.piper")

# Known Piper voices metadata (mirrors VoiceManager's PIPER_VOICES)
PIPER_VOICES: dict[str, dict[str, str]] = {
    "en_US-lessac-medium": {
        "name": "Lessac (US Female)",
        "gender": "female",
        "accent": "US",
        "description": "Medium-quality female US English voice (default)",
    },
    "en_GB-vctk-medium": {
        "name": "VCTK (British Male)",
        "gender": "male",
        "accent": "British",
        "description": "Medium-quality British male voice from VCTK corpus",
    },
    "en_US-amy-medium": {
        "name": "Amy (US Female)",
        "gender": "female",
        "accent": "US",
        "description": "Medium-quality female US English voice (Amy)",
    },
    "en_GB-southern_english_female-medium": {
        "name": "Southern English Female",
        "gender": "female",
        "accent": "British",
        "description": "Medium-quality Southern British English female voice",
    },
}


@TTSRegistry.register("piper")
class PiperTTSBackend(TTSBackend):
    """Piper TTS via subprocess to Piper CLI.

    Lazy-loads the Piper voice model on first use. Keeps it warm for
    subsequent calls. Uses afplay on macOS for playback.
    """

    backend_id = "piper"

    def __init__(self, voice: str = "en_US-lessac-medium") -> None:
        self._voice = voice
        self._piper_model: Any = None  # PiperVoice instance
        self._voice_manager = VoiceManager()
        self._playback_process: Optional["subprocess.Popen[bytes]"] = None

    def synthesize(self, text: str, **kwargs: Any) -> bytes:
        """Synthesize text to WAV audio bytes via Piper.

        Returns the WAV bytes directly so the caller can play them however
        they want (afplay, sounddevice, etc.).
        """
        if not text.strip():
            return b""

        voice_id = kwargs.get("voice") or self._voice
        model = self._ensure_model(voice_id)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        try:
            wav_file = wave.open(wav_path, "w")
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            model.synthesize_wav(text, wav_file)
            wav_file.close()

            with open(wav_path, "rb") as f:
                audio_bytes = f.read()
            return audio_bytes
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def available_voices(self) -> List[Dict[str, str]]:
        """Return list of available Piper voices with download status."""
        results: list[dict[str, str]] = []
        for vid, meta in PIPER_VOICES.items():
            paths = self._voice_manager.get_voice_paths(vid)
            status = "downloaded" if paths else "not_downloaded"
            results.append({
                "id": vid,
                "name": meta["name"],
                "gender": meta["gender"],
                "accent": meta["accent"],
                "description": meta["description"],
                "status": status,
            })
        return results

    def health(self) -> bool:
        """Check if the default Piper voice is available."""
        try:
            paths = self._voice_manager.get_voice_paths(self._voice)
            return paths is not None
        except Exception:
            return False

    def cleanup(self) -> None:
        """Release the Piper voice model."""
        self._piper_model = None
        logger.debug("Piper model released")

    def _ensure_model(self, voice_id: str) -> Any:
        """Lazy-load the Piper voice model."""
        from piper import PiperVoice

        if self._piper_model is not None:
            return self._piper_model

        paths = self._voice_manager.get_voice_paths(voice_id)
        if not paths:
            # Try default
            self._voice_manager.select_voice("en_US-lessac-medium")
            paths = self._voice_manager.get_voice_paths("en_US-lessac-medium")
            if not paths:
                raise FileNotFoundError(f"Piper voice '{voice_id}' not available. Download it first.")

        logger.info("Loading Piper voice '%s' from %s", voice_id, paths["onnx"])
        self._piper_model = PiperVoice.load(paths["onnx"], config_path=paths["json"])
        return self._piper_model
