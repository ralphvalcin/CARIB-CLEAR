"""JARVIS Voice — microphone input, transcription, and TTS output.

Security features:
  - Guard file (~/.jarvis_voice_guard): mic permission gate
  - Kill switch (~/.jarvis_voice_kill): emergency stop
  - Context manager cleanup: guaranteed resource release
"""

from jarvis.voice.core import (
    GUARD_FILE_PATH,
    KILL_FILE_PATH,
    AudioCapture,
    JarvisClient,
    TTSEngine,
    Transcriber,
    VoiceConfig,
    VoiceLLMClient,
    activate_guard,
    clear_kill_signal,
    deactivate_guard,
    format_response_for_tts,
    guard_active,
    kill_requested,
)
from jarvis.voice.loop import VoiceLoop, main

__all__ = [
    "AudioCapture",
    "GUARD_FILE_PATH",
    "JarvisClient",
    "KILL_FILE_PATH",
    "TTSEngine",
    "Transcriber",
    "VoiceConfig",
    "VoiceLoop",
    "activate_guard",
    "clear_kill_signal",
    "deactivate_guard",
    "format_response_for_tts",
    "guard_active",
    "kill_requested",
    "main",
]
