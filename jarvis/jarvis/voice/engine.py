"""LLM Engine — factory that resolves the configured LLM backend.

Handles backend resolution from config, auto-discovery, and fallback
if the primary backend is unavailable. Designed to be the single point
of entry for all LLM interactions from the voice loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional

from jarvis.voice.registry import Conversation, LLMBackend, LLMRegistry

logger = logging.getLogger("jarvis.voice.engine")


@dataclass
class LLMConfig:
    """Configuration for the LLM engine.

    Set these values from VoiceConfig or directly.
    """

    engine: str = "ollama"
    """Primary LLM backend ID (ollama, openai, etc.)"""

    model: str = "llama3.2:3b"
    """Model name for the backend."""

    fallback_engine: str = ""
    """Backup engine if primary is unavailable (empty = no fallback)."""

    fallback_model: str = "gpt-4o-mini"
    """Model name for the fallback backend."""

    temperature: float = 0.7
    max_tokens: int = 256
    timeout: float = 30.0

    # Backend-specific settings
    ollama_base_url: str = "http://localhost:11434"
    openai_base_url: str = ""
    """Base URL for OpenAI-compatible API. Empty = default (api.openai.com)."""

    openai_api_key: str = ""
    """API key for OpenAI. Empty = reads from OPENAI_API_KEY env var."""


# Voice-optimized system prompt — keeps responses short and conversational
VOICE_SYSTEM_PROMPT = (
    "You are JARVIS, a conversational voice assistant. "
    "You speak in short, natural sentences — never more than 2-3 sentences at a time. "
    "Be helpful, conversational, and direct. Never ramble or list things. "
    "If you don't know something, say so briefly. "
    "Always respond as if speaking aloud in a conversation."
)


class LLMEngine:
    """LLM inference engine with backend resolution and fallback.

    Usage:
        engine = LLMEngine(config)
        conv = Conversation(system_prompt=VOICE_SYSTEM_PROMPT)
        conv.add_user("What's the weather?")
        for token in engine.stream_chat(conv):
            print(token, end="")
    """

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
    ) -> None:
        self.config = config or LLMConfig()
        self._primary_backend: Optional[LLMBackend] = None
        self._fallback_backend: Optional[LLMBackend] = None
        self._resolved: bool = False
        self._using_fallback: bool = False

    # ── Public API ──────────────────────────────────────────────────────────

    def stream_chat(self, conversation: Conversation) -> Generator[str, None, None]:
        """Send conversation to LLM and yield response tokens.

        Uses the primary backend first. If it fails or is unavailable,
        falls back to the configured fallback.
        """
        self._ensure_resolved()

        backend = self._fallback_backend if self._using_fallback else self._primary_backend
        if backend is None:
            yield "I don't have any available language model configured."
            return

        try:
            yield from backend.stream_chat(conversation)
        except Exception as exc:
            logger.error("Primary backend failed: %s", exc)
            if self._fallback_backend is not None and not self._using_fallback:
                logger.info("Falling back to %s...", self.config.fallback_engine)
                self._using_fallback = True
                yield from self._fallback_backend.stream_chat(conversation)
            else:
                yield "I'm having trouble processing that. Please try again."

    def chat(self, conversation: Conversation) -> str:
        """Send conversation and return full response (non-streaming)."""
        return "".join(self.stream_chat(conversation))

    def health(self) -> Dict[str, Any]:
        """Return health status of all backends."""
        self._ensure_resolved()
        return {
            "primary": self.config.engine if self._primary_backend else "unavailable",
            "fallback": self.config.fallback_engine if self._fallback_backend else "none",
            "using_fallback": self._using_fallback,
            "primary_healthy": self._primary_backend.health() if self._primary_backend else False,
            "fallback_healthy": self._fallback_backend.health() if self._fallback_backend else None,
        }

    def reset_fallback(self) -> None:
        """Reset to using the primary backend on the next call."""
        self._using_fallback = False

    def cleanup(self) -> None:
        """Release all backend resources."""
        if self._primary_backend:
            self._primary_backend.cleanup()
        if self._fallback_backend:
            self._fallback_backend.cleanup()
        self._primary_backend = None
        self._fallback_backend = None
        self._resolved = False

    # ── Backend resolution ────────────────────────────────────────────────

    def _ensure_resolved(self) -> None:
        """Discover and instantiate backends if not already done."""
        if self._resolved:
            return

        # Auto-discover LLM backends
        LLMRegistry.auto_discover("jarvis.voice.backends.ollama")
        LLMRegistry.auto_discover("jarvis.voice.backends.openai")

        self._primary_backend = self._create_backend(
            self.config.engine,
            self.config.model,
            is_primary=True,
        )

        if self.config.fallback_engine and self.config.fallback_engine != self.config.engine:
            self._fallback_backend = self._create_backend(
                self.config.fallback_engine,
                self.config.fallback_model,
                is_primary=False,
            )
            if self._fallback_backend:
                logger.info("Fallback LLM backend configured: %s/%s", self.config.fallback_engine, self.config.fallback_model)

        self._resolved = True

        # If primary is unhealthy and fallback exists, switch immediately
        if self._primary_backend and not self._primary_backend.health() and self._fallback_backend:
            logger.warning("Primary LLM backend '%s' unreachable — using fallback '%s'", self.config.engine, self.config.fallback_engine)
            self._using_fallback = True

    def _create_backend(self, engine: str, model: str, is_primary: bool = True) -> Optional[LLMBackend]:
        """Create a backend instance from the registry."""
        if not LLMRegistry.contains(engine):
            logger.warning("Unknown LLM engine '%s'. Available: %s", engine, LLMRegistry.available())
            return None

        backend_cls = LLMRegistry.get(engine)

        if engine == "ollama":
            return backend_cls(
                model=model,
                base_url=self.config.ollama_base_url,
                timeout=self.config.timeout,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
        elif engine == "openai":
            return backend_cls(
                model=model,
                base_url=self.config.openai_base_url or None,
                api_key=self.config.openai_api_key or None,
                timeout=self.config.timeout,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
        else:
            return backend_cls()
