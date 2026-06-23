"""macOS ``say`` TTS backend — uses the built-in macOS speech synthesizer.

Registered as ``say`` in TTSRegistry.

No dependencies, no models to download — uses the system ``say`` command.
Limited to the voices installed on the system. Good for quick testing or
when no other TTS engine is available.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Dict, List

from jarvis.voice.registry import TTSBackend, TTSRegistry

logger = logging.getLogger("jarvis.voice.say")


@TTSRegistry.register("say")
class SayTTSBackend(TTSBackend):
    """macOS built-in TTS via the ``say`` command.

    Fast, zero-dependency, but limited voice quality compared to Kokoro.
    """

    backend_id = "say"

    def __init__(self, voice: str = "") -> None:
        self._voice = voice

    def synthesize(self, text: str, **kwargs: Any) -> bytes:
        """Synthesize text to AIFF audio bytes via ``say``.

        Returns AIFF audio data captured from the say command's stdout.
        """
        if not text.strip():
            return b""

        cleaned = text.replace('"', "'")
        cmd = ["say", cleaned, "--data-format=AIFF"]

        voice = kwargs.get("voice") or self._voice
        if voice:
            cmd.extend(["--voice", voice])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=120,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
            logger.warning("say command returned no audio for: %s", text[:40])
            return b""
        except subprocess.TimeoutExpired:
            logger.error("say TTS timed out")
            return b""
        except FileNotFoundError:
            logger.error("`say` command not found — not running macOS?")
            return b""

    def available_voices(self) -> List[Dict[str, str]]:
        """Return system voices from the ``say`` command."""
        try:
            result = subprocess.run(
                ["say", "--voice", "?"],
                capture_output=True, text=True, timeout=10,
            )
            voices: list[dict[str, str]] = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split(maxsplit=1)
                if parts:
                    voices.append({
                        "id": parts[0],
                        "name": parts[1] if len(parts) > 1 else "",
                        "gender": "",
                        "accent": "",
                        "description": f"macOS system voice: {parts[0]}",
                    })
            return voices
        except Exception as exc:
            logger.warning("Failed to list say voices: %s", exc)
            return []

    def health(self) -> bool:
        """Check if the ``say`` command is available."""
        try:
            subprocess.run(["which", "say"], capture_output=True, timeout=5)
            return True
        except Exception:
            return False
