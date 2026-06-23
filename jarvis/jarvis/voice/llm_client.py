"""Legacy compatibility shim — imports from the new registry.

The Conversation class and Ollama backend have moved to:
  - ``jarvis.voice.registry`` → ``Conversation``
  - ``jarvis.voice.backends.ollama`` → ``OllamaBackend``

Use the new ``LLMEngine`` factory instead of ``StreamingLLM`` directly."""

from __future__ import annotations

import logging

from jarvis.voice.engine import LLMEngine, VOICE_SYSTEM_PROMPT as VOICE_SYSTEM_PROMPT
from jarvis.voice.registry import Conversation

logger = logging.getLogger("jarvis.voice.llm_client")

# Re-export for backward compatibility
__all__ = ["Conversation", "LLMEngine"]

# Backward-compatible alias
def StreamingLLM(*args, **kwargs):
    """Deprecated: use LLMEngine instead. Returns an LLMEngine instance."""
    logger.warning("StreamingLLM is deprecated — use LLMEngine instead")
    return LLMEngine()

__all__ += ["StreamingLLM"]