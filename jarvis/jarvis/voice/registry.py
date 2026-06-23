"""Plugin registry for TTS and STT backends.

Backends register themselves via decorator at import time, making them
auto-discoverable from config. Adding a new backend is a single file
with a decorator — no changes to the core loop.

Usage:
    @TTSRegistry.register("my_engine")
    class MyTTSBackend(TTSBackend):
        backend_id = "my_engine"

    @SpeechRegistry.register("my_stt")
    class MySTTBackend(SpeechBackend):
        backend_id = "my_stt"
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type


# ── Abstract Base Classes ─────────────────────────────────────────────────


class TTSBackend(ABC):
    """Abstract base for all text-to-speech backends."""

    backend_id: str = ""

    @abstractmethod
    def synthesize(self, text: str, **kwargs: Any) -> bytes:
        """Synthesize text to WAV audio bytes.

        Args:
            text: Text to speak.
            **kwargs: Backend-specific options (voice, speed, etc.).

        Returns:
            WAV audio bytes.
        """

    @abstractmethod
    def available_voices(self) -> List[Dict[str, str]]:
        """Return list of available voices with metadata."""

    def health(self) -> bool:
        """Check if the backend is operational. Override for custom checks."""
        return True

    def cleanup(self) -> None:
        """Release any loaded models or resources."""


class SpeechBackend(ABC):
    """Abstract base for all speech-to-text backends."""

    backend_id: str = ""

    @abstractmethod
    def transcribe(self, audio: Any, **kwargs: Any) -> str:
        """Transcribe audio to text.

        Args:
            audio: Audio data (numpy array of int16).
            **kwargs: Backend-specific options.

        Returns:
            Transcribed text string.
        """

    def health(self) -> bool:
        """Check if the backend is operational."""
        return True

    def cleanup(self) -> None:
        """Release any loaded models or resources."""


# ── Registries ──────────────────────────────────────────────────────────────


class _Registry:
    """Generic backend registry with auto-discovery."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._backends: Dict[str, Type] = {}

    def register(self, backend_id: Optional[str] = None):
        """Decorator to register a backend class.

        If backend_id is omitted, uses the class's ``backend_id`` attribute.

        Usage:
            @registry.register("my_engine")
            class MyBackend(TTSBackend):
                backend_id = "my_engine"

            # or with auto-detection:
            @registry.register()
            class MyBackend(TTSBackend):
                backend_id = "my_engine"
        """
        import functools

        def decorator(cls: Type) -> Type:
            nonlocal backend_id
            if backend_id is None:
                backend_id = getattr(cls, "backend_id", cls.__name__.lower())
            key = backend_id.lower()
            if key in self._backends:
                import logging

                logging.getLogger("jarvis.voice.registry").warning(
                    "Overwriting registered backend '%s' (was %s, now %s)",
                    key, self._backends[key].__name__, cls.__name__,
                )
            self._backends[key] = cls
            return cls

        return decorator

    def get(self, backend_id: str) -> Optional[Type]:
        """Get a backend class by ID. Returns None if not found."""
        return self._backends.get(backend_id.lower())

    def contains(self, backend_id: str) -> bool:
        """Check if a backend is registered."""
        return backend_id.lower() in self._backends

    def list_backends(self) -> Dict[str, Type]:
        """Return all registered backends (copy)."""
        return dict(self._backends)

    def available(self) -> List[str]:
        """Return sorted list of registered backend IDs."""
        return sorted(self._backends.keys())

    def auto_discover(self, module_path: str) -> None:
        """Import a module to trigger its decorators and discover backends.

        Usage:
            registry.auto_discover("jarvis.voice.kokoro_tts")
        """
        import importlib

        try:
            importlib.import_module(module_path)
        except ImportError as exc:
            import logging

            logging.getLogger("jarvis.voice.registry").debug(
                "Auto-discover skipped %s: %s", module_path, exc,
            )


# Singleton registries
TTSRegistry = _Registry("tts")
SpeechRegistry = _Registry("speech")
LLMRegistry = _Registry("llm")


# ── LLM Backend ────────────────────────────────────────────────────────────────


class Conversation:
    """A single conversation session with sliding window history.

    Shared data structure used by all LLM backends and the VoiceLLMClient.
    """

    def __init__(
        self,
        system_prompt: str = "",
        max_history: int = 10,
    ) -> None:
        self.messages: List[Dict[str, str]] = []
        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})
        self.max_history = max_history

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})
        self._trim()

    def add_assistant(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})
        self._trim()

    def _trim(self) -> None:
        system = [m for m in self.messages if m["role"] == "system"]
        turns = [m for m in self.messages if m["role"] != "system"]
        if len(turns) > self.max_history * 2:
            turns = turns[-(self.max_history * 2):]
        self.messages = system + turns

    def reset(self) -> None:
        system = [m for m in self.messages if m["role"] == "system"]
        self.messages = system[:1] if system else []


class LLMBackend(ABC):
    """Abstract base for all LLM inference backends.

    Supports both streaming (yielding tokens) and non-streaming (full text)
    chat interfaces. Backends should lazy-load models on first use.
    """

    backend_id: str = ""

    @abstractmethod
    def stream_chat(self, conversation: Conversation) -> Any:
        """Send conversation to LLM and yield response tokens as they arrive.

        Args:
            conversation: Conversation with message history.

        Yields:
            Response tokens (strings) as the model generates them.
        """

    def chat(self, conversation: Conversation) -> str:
        """Send conversation to LLM and return the full response.

        Default implementation collects tokens from ``stream_chat()``.
        Override for non-streaming backends.
        """
        return "".join(self.stream_chat(conversation))

    def health(self) -> bool:
        """Check if the backend is operational."""
        return True

    def cleanup(self) -> None:
        """Release any loaded models or resources."""


# ── Built-in backends ──────────────────────────────────────────────────────────
# These auto-discover when the module is imported. The register decorators
# live in each backend's module file.
