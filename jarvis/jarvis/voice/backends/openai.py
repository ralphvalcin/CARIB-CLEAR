"""OpenAI-compatible LLM backend — works with OpenAI, Anthropic, and any
OpenAI-compatible API.

Registered as ``openai`` in LLMRegistry.

Supports any OpenAI-compatible API endpoint. Set the base URL and API key
in config or environment variables. Supports streaming token-by-token.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Generator, List, Optional

from jarvis.voice.registry import Conversation, LLMBackend, LLMRegistry

logger = logging.getLogger("jarvis.voice.openai")


@LLMRegistry.register("openai")
class OpenAIBackend(LLMBackend):
    """LLM inference via any OpenAI-compatible API.

    Supports OpenAI, Anthropic (via proxy), Together AI, Groq, and any
    other provider with an OpenAI-compatible chat completions endpoint.

    Reads API key from ``api_key`` param, ``OPENAI_API_KEY`` env var,
    or ``ANTHROPIC_API_KEY`` env var as fallback.
    """

    backend_id = "openai"

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client: Any = None
        logger.info(
            "OpenAI backend initialized (model=%s, base_url=%s)",
            self.model, self.base_url or "default",
        )

    def _ensure_client(self) -> Any:
        """Lazy-load the OpenAI client."""
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI

            kwargs: dict[str, Any] = {
                "api_key": self._api_key,
                "timeout": self.timeout,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url

            self._client = OpenAI(**kwargs)
            logger.debug("OpenAI client initialized")
            return self._client
        except ImportError:
            raise RuntimeError("openai package not installed. Run: pip install openai")

    def _build_messages(self, conversation: Conversation) -> list[dict]:
        """Convert Conversation to OpenAI message format."""
        return list(conversation.messages)

    def stream_chat(self, conversation: Conversation) -> Generator[str, None, None]:
        """Stream chat via OpenAI-compatible chat completions endpoint."""
        client = self._ensure_client()
        messages = self._build_messages(conversation)

        collected: list[str] = []

        try:
            stream = client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta:
                    content = chunk.choices[0].delta.content
                    if content:
                        collected.append(content)
                        yield content

        except Exception as exc:
            logger.error("OpenAI streaming error: %s", exc)
            yield "I'm having trouble reaching the API. Please check my connection."

        full_text = "".join(collected).strip()
        if full_text:
            conversation.add_assistant(full_text)

    def health(self) -> bool:
        """Check if the API key is configured and the client can be created."""
        if not self._api_key:
            return False
        try:
            self._ensure_client()
            return True
        except Exception:
            return False

    def cleanup(self) -> None:
        """Release the client."""
        self._client = None
        logger.debug("OpenAI backend cleaned up")
