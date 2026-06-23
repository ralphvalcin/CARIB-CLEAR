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
from jarvis.voice.engine import LLMConfig, LLMEngine
from jarvis.voice.kokoro_tts import KOKORO_VOICES, KokoroTTSBackend
from jarvis.voice.loop import VoiceLoop, main
from jarvis.voice.mcp_client import MCPManager, MCPServerConfig, MCPTool
from jarvis.voice.registry import (
    Conversation,
    LLMBackend,
    LLMRegistry,
    SpeechBackend,
    SpeechRegistry,
    TTSBackend,
    TTSRegistry,
)

__all__ = [
    "AudioCapture",
    "Conversation",
    "GUARD_FILE_PATH",
    "JarvisClient",
    "KILL_FILE_PATH",
    "KOKORO_VOICES",
    "KokoroTTSBackend",
    "LLMBackend",
    "LLMConfig",
    "LLMEngine",
    "LLMRegistry",
    "MCPManager",
    "MCPServerConfig",
    "MCPTool",
    "SpeechBackend",
    "SpeechRegistry",
    "TTSBackend",
    "TTSRegistry",
    "TTSEngine",
    "Transcriber",
    "VoiceConfig",
    "VoiceLLMClient",
    "VoiceLoop",
    "activate_guard",
    "clear_kill_signal",
    "deactivate_guard",
    "format_response_for_tts",
    "guard_active",
    "kill_requested",
    "main",
]
