"""Piper voice manager — download, list, and select TTS voices.

Voice files are stored in ~/JARVIS/piper_voices/.
Each voice consists of an .onnx model file and a .json config file.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis.voice.voice_manager")

_VOICES_DIR = Path(__file__).resolve().parent.parent.parent / "piper_voices"

# ── Available Piper voices ───────────────────────────────────────────────────
# Format: {voice_id: {name, gender, accent, description, onnx_url, json_url}}
# URL format: https://huggingface.co/rhasspy/piper-voices/resolve/main/...

PIPER_VOICES: Dict[str, Dict[str, str]] = {
    "en_US-lessac-medium": {
        "name": "Lessac (US Female)",
        "gender": "female",
        "accent": "US",
        "description": "Medium-quality female US English voice (default)",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    },
    "en_GB-vctk-medium": {
        "name": "VCTK (British Male)",
        "gender": "male",
        "accent": "British",
        "description": "Medium-quality British male voice from VCTK corpus",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/vctk/medium/en_GB-vctk-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/vctk/medium/en_GB-vctk-medium.onnx.json",
    },
    "en_US-amy-medium": {
        "name": "Amy (US Female)",
        "gender": "female",
        "accent": "US",
        "description": "Medium-quality female US English voice (Amy)",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json",
    },
    "en_GB-southern_english_female-medium": {
        "name": "Southern English Female",
        "gender": "female",
        "accent": "British",
        "description": "Medium-quality Southern British English female voice",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/southern_english_female/medium/en_GB-southern_english_female-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/southern_english_female/medium/en_GB-southern_english_female-medium.onnx.json",
    },
}


@dataclass
class PiperVoiceInfo:
    """Information about a downloaded or available Piper voice."""

    voice_id: str
    name: str
    gender: str
    accent: str
    description: str
    downloaded: bool = False
    size_mb: float = 0.0
    selected: bool = False


class VoiceManager:
    """Manages Piper TTS voices: download, list, select, and switch.

    Stores selected voice ID in a JSON file so it persists across restarts.
    """

    def __init__(self, voices_dir: Optional[Path] = None) -> None:
        self.voices_dir = voices_dir or _VOICES_DIR
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        self._config_path = self.voices_dir / ".voice_config.json"

    # ── Discovery ────────────────────────────────────────────────────────────

    def list_voices(self) -> List[PiperVoiceInfo]:
        """Return all available Piper voices, with download status."""
        results: List[PiperVoiceInfo] = []
        selected = self._get_selected_voice()

        for vid, meta in PIPER_VOICES.items():
            onnx = self.voices_dir / f"{vid}.onnx"
            cfg = self.voices_dir / f"{vid}.onnx.json"
            downloaded = onnx.exists() and cfg.exists()
            size_mb = 0.0
            if onnx.exists():
                size_mb = round(onnx.stat().st_size / (1024 * 1024), 1)

            results.append(PiperVoiceInfo(
                voice_id=vid,
                name=meta["name"],
                gender=meta["gender"],
                accent=meta["accent"],
                description=meta["description"],
                downloaded=downloaded,
                size_mb=size_mb,
                selected=(vid == selected),
            ))

        return results

    def get_voice_paths(self, voice_id: str) -> Optional[Dict[str, str]]:
        """Return {onnx, json} paths for a voice, or None if not downloaded."""
        onnx = self.voices_dir / f"{voice_id}.onnx"
        cfg = self.voices_dir / f"{voice_id}.onnx.json"
        if onnx.exists() and cfg.exists():
            return {"onnx": str(onnx), "json": str(cfg)}
        return None

    # ── Selection ────────────────────────────────────────────────────────────

    def _get_selected_voice(self) -> str:
        """Read the persisted selected voice ID."""
        try:
            if self._config_path.exists():
                data = json.loads(self._config_path.read_text())
                return data.get("selected_voice", "en_US-lessac-medium")
        except Exception:
            pass
        return "en_US-lessac-medium"

    def get_selected_voice(self) -> str:
        """Get the currently selected voice ID."""
        return self._get_selected_voice()

    def select_voice(self, voice_id: str) -> bool:
        """Set the active TTS voice. Returns False if voice isn't downloaded."""
        if voice_id not in PIPER_VOICES:
            logger.warning("Unknown voice: %s", voice_id)
            return False

        paths = self.get_voice_paths(voice_id)
        if not paths:
            logger.warning("Voice '%s' not yet downloaded — download it first", voice_id)
            return False

        try:
            self._config_path.write_text(json.dumps({
                "selected_voice": voice_id,
                "updated_at": time.time(),
            }))
            logger.info("Selected voice: %s", voice_id)
            return True
        except Exception as exc:
            logger.error("Failed to save voice selection: %s", exc)
            return False

    # ── Download ─────────────────────────────────────────────────────────────

    def download_voice(self, voice_id: str) -> bool:
        """Download a Piper voice model and config file.

        Downloads from HuggingFace to the piper_voices directory.
        Returns True if successful (or already downloaded).
        """
        if voice_id not in PIPER_VOICES:
            logger.warning("Unknown voice: %s", voice_id)
            return False

        meta = PIPER_VOICES[voice_id]
        onnx_path = self.voices_dir / f"{voice_id}.onnx"
        json_path = self.voices_dir / f"{voice_id}.onnx.json"

        if onnx_path.exists() and json_path.exists():
            logger.info("Voice '%s' already downloaded", voice_id)
            return True

        try:
            # Download .onnx
            logger.info("Downloading %s (%s)...", voice_id, meta["name"])
            self._download_file(meta["onnx_url"], onnx_path)

            # Download .json
            self._download_file(meta["json_url"], json_path)

            logger.info("Voice '%s' downloaded successfully", voice_id)
            return True
        except Exception as exc:
            logger.error("Failed to download voice '%s': %s", voice_id, exc)
            # Clean up partial files
            onnx_path.unlink(missing_ok=True)
            json_path.unlink(missing_ok=True)
            return False

    def _download_file(self, url: str, dest: Path) -> None:
        """Download a file with progress logging."""
        import urllib.request

        logger.debug("Downloading %s → %s", url, dest.name)
        urllib.request.urlretrieve(url, str(dest))
        mb = round(dest.stat().st_size / (1024 * 1024), 1)
        logger.debug("Downloaded %s (%.1f MB)", dest.name, mb)

    def download_status(self, voice_id: str) -> Optional[float]:
        """Return download progress as percentage, or None if not downloading."""
        # Simple: check if files exist (full async download not implemented yet)
        paths = self.get_voice_paths(voice_id)
        if paths:
            return 100.0
        return None

    # ── Remove ───────────────────────────────────────────────────────────────

    def remove_voice(self, voice_id: str) -> bool:
        """Delete a downloaded voice's model and config files."""
        if voice_id == "en_US-lessac-medium":
            logger.warning("Cannot remove default voice")
            return False

        onnx = self.voices_dir / f"{voice_id}.onnx"
        cfg = self.voices_dir / f"{voice_id}.onnx.json"
        removed = False
        for f in [onnx, cfg]:
            if f.exists():
                f.unlink()
                removed = True

        if removed:
            logger.info("Removed voice '%s'", voice_id)
            selected = self._get_selected_voice()
            if selected == voice_id:
                self.select_voice("en_US-lessac-medium")
            return True
        return False