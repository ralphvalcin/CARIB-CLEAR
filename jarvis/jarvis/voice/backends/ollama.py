"""Ollama LLM backend — local inference via Ollama's HTTP API.

Registered as ``ollama`` in LLMRegistry.

Connects to a local Ollama instance at localhost:11434 by default.
Supports token-by-token streaming for sub-2s first-audio latency.
No API keys, no rate limits, no credits needed.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Generator, List

import httpx

from jarvis.voice.registry import Conversation, LLMBackend, LLMRegistry

logger = logging.getLogger("jarvis.voice.ollama")

# Ollama's default local endpoint
OLLAMA_BASE = "http://localhost:11434"


@LLMRegistry.register("ollama")
class OllamaBackend(LLMBackend):
    """Local LLM inference via Ollama — streaming, no credits, no rate limits.

    Lazy-validates that Ollama is reachable on first use.
    Supports any model served by Ollama (llama3.2, gemma, qwen, etc.).
    """

    backend_id = "ollama"

    def __init__(
        self,
        model: str = "llama3.2:3b",
        base_url: str = OLLAMA_BASE,
        timeout: float = 30.0,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._chat_url = f"{self.base_url}/api/chat"
        self._healthy: bool = False
        logger.info("Ollama backend initialized (model=%s, url=%s)", self.model, self._chat_url)

    def stream_chat(self, conversation: Conversation) -> Generator[str, None, None]:
        """Stream chat via Ollama's /api/chat endpoint."""
        body = {
            "model": self.model,
            "messages": conversation.messages,
            "stream": True,
            "options": {
                "num_predict": self.max_tokens,
                "temperature": self.temperature,
            },
        }

        collected: list[str] = []

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream("POST", self._chat_url, json=body) as resp:
                    if resp.status_code != 200:
                        error_body = resp.text[:300]
                        logger.error("Ollama API error %d: %s", resp.status_code, error_body)
                        yield "I'm having trouble reaching my local model."
                        return

                    for line in resp.iter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            content = chunk.get("message", {}).get("content", "")
                            if content:
                                collected.append(content)
                                yield content
                            if chunk.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue

        except httpx.TimeoutException:
            logger.error("Ollama timed out after %ss", self.timeout)
            yield "Sorry, that took too long. Can you tell me again?"
        except httpx.ConnectError:
            logger.error("Ollama not running at %s", self.base_url)
            yield "My local model isn't running. Check that Ollama is active."
        except Exception as exc:
            logger.error("Ollama streaming error: %s", exc)
            yield "I hit an error processing that. Try again?"

        full_text = "".join(collected).strip()
        if full_text:
            conversation.add_assistant(full_text)
            self._healthy = True

    def health(self) -> bool:
        """Check if Ollama is reachable on the configured URL."""
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def cleanup(self) -> None:
        """No persistent resources to free for Ollama (stateless HTTP)."""
        logger.debug("Ollama backend cleaned up")
