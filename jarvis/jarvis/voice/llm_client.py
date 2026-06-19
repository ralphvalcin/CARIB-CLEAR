"""Streaming LLM client — calls local Ollama for fast, free, private inference.

Transport: Direct HTTP streaming via Ollama's local API at localhost:11434.
No API keys, no rate limits, no credits needed. True token-by-token streaming
for sub-2s first-audio latency.

Supports both llama3.2:3b (fast, ~2s) and gemma4 (smarter, ~5s).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Generator, List, Optional

import httpx

logger = logging.getLogger("jarvis.voice.llm")

OLLAMA_BASE = "http://localhost:11434"

# Voice-optimized system prompt — keeps responses short and conversational
VOICE_SYSTEM_PROMPT = (
    "You are JARVIS, a conversational voice assistant. "
    "You speak in short, natural sentences — never more than 2-3 sentences at a time. "
    "Be helpful, conversational, and direct. Never ramble or list things. "
    "If you don't know something, say so briefly. "
    "Always respond as if speaking aloud in a conversation."
)

# Known current date context for the LLM
CURRENT_DATE = time.strftime("%A, %B %d, %Y", time.localtime())


class Conversation:
    """A single conversation session with sliding window history."""

    def __init__(
        self,
        system_prompt: str = VOICE_SYSTEM_PROMPT,
        max_history: int = 10,
    ) -> None:
        # Inject current date into system prompt so LLM knows today's date
        dated_prompt = (
            f"{system_prompt}\n\n"
            f"Today is {CURRENT_DATE}. "
            f"You live in the present — use your current knowledge."
        )
        self.messages: List[Dict[str, str]] = [
            {"role": "system", "content": dated_prompt},
        ]
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
        self.messages = self.messages[:1]


class StreamingLLM:
    """Local LLM via Ollama — streaming, no credits, no rate limits."""

    def __init__(
        self,
        model: str = "llama3.2:3b",
        base_url: str = OLLAMA_BASE,
        timeout: float = 30.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._chat_url = f"{self.base_url}/api/chat"
        logger.info(
            "Local LLM initialized (model=%s, url=%s)",
            self.model, self._chat_url,
        )

    def stream_chat(self, conversation: Conversation) -> Generator[str, None, None]:
        """Send conversation to local LLM and yield response tokens as they arrive.

        Uses Ollama's streaming /api/chat endpoint. Each token is yielded
        immediately as it's generated — true streaming, no waiting.
        The full response is saved to conversation history.
        """
        body = {
            "model": self.model,
            "messages": conversation.messages,
            "stream": True,
            "options": {
                "num_predict": 256,
                "temperature": 0.7,
            },
        }

        collected: List[str] = []

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream("POST", self._chat_url, json=body) as resp:
                    if resp.status_code != 200:
                        error_body = resp.text[:300]
                        logger.error(
                            "Ollama API error %d: %s",
                            resp.status_code, error_body,
                        )
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

        # Save full response to conversation history
        full_text = "".join(collected).strip()
        if full_text:
            conversation.add_assistant(full_text)

    def chat(self, conversation: Conversation) -> str:
        """Non-streaming convenience: returns full response."""
        return "".join(self.stream_chat(conversation))


# ── Quick test ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    llm = StreamingLLM()
    conv = Conversation()
    conv.add_user("Say hello in one short sentence.")
    print(f"Model: {llm.model}")
    print()
    print("Response:", end=" ", flush=True)
    t0 = time.time()
    first = True
    for token in llm.stream_chat(conv):
        if first:
            print(f"\n  [first token in {time.time()-t0:.1f}s]", flush=True)
            first = False
        print(token, end="", flush=True)
    print(f"\n  [total: {time.time()-t0:.1f}s]")
    print()
    print("Conversation history:", len(conv.messages), "messages")