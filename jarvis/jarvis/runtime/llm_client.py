from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Literal, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger("jarvis.runtime.llm")

_DEFAULT_SYSTEM_PROMPT = """You are JARVIS, an intelligent personal assistant running on macOS.
You have access to local tools (read files, run Python, check disk, system info).
You can execute commands through your runtime system.
Be concise, helpful, and precise. Answer in natural language."""

OLLAMA_API_BASE = "http://localhost:11434"

MessageRole = Literal["system", "user", "assistant"]


class ChatMessage:
    """A single message in a chat conversation."""

    def __init__(self, role: MessageRole, content: str) -> None:
        self.role = role
        self.content = content

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


class LLMClient:
    """Lightweight Ollama HTTP API client for local LLM inference.

    Uses Ollama's REST API at http://localhost:11434/api/chat.
    Supports full conversation history and proper system messages.
    Falls back to generating static responses if Ollama is unavailable.
    """

    def __init__(
        self,
        model: str = "llama3.2:3b",
        system_prompt: str = _DEFAULT_SYSTEM_PROMPT,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self.timeout = timeout
        self.max_retries = max_retries
        self._available: Optional[bool] = None  # lazy check
        self.enabled: bool = True  # set False in tests to force fallback mode
        # In-memory conversation buffer per session
        self._histories: Dict[str, List[ChatMessage]] = {}

    # ── Availability check ───────────────────────────────────────────────────

    def check_available(self) -> bool:
        """Check if Ollama is running and the model is available."""
        if self._available is not None:
            return self._available
        try:
            req = Request(
                f"{OLLAMA_API_BASE}/api/tags",
                method="GET",
            )
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            self._available = any(
                tag.get("name") == self.model
                for tag in data.get("models", [])
            )
        except Exception as e:
            logger.warning("Ollama check failed: %s", e)
            self._available = False
        return self._available

    def clear_cache(self) -> None:
        """Reset the availability cache."""
        self._available = None

    # ── Conversation history ─────────────────────────────────────────────────

    def get_history(self, session_id: str) -> List[ChatMessage]:
        """Get conversation history for a session."""
        return self._histories.get(session_id, [])

    def add_to_history(self, session_id: str, role: MessageRole, content: str) -> None:
        """Add a message to the conversation history."""
        if session_id not in self._histories:
            self._histories[session_id] = []
        self._histories[session_id].append(ChatMessage(role, content))
        # Keep last 20 turns to bound memory usage
        if len(self._histories[session_id]) > 40:
            self._histories[session_id] = self._histories[session_id][-40:]

    def clear_history(self, session_id: str) -> None:
        """Clear conversation history for a session."""
        self._histories.pop(session_id, None)

    # ── Core chat ────────────────────────────────────────────────────────────

    def chat(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        context_messages: Optional[List[ChatMessage]] = None,
    ) -> str:
        """Send a message to the LLM and get a response.

        Supports:
        - Optional session_id for persistent conversation history
        - Optional context_messages for injection (e.g., memory facts)
        - Falls back to canned responses if Ollama is unavailable
        """
        if not self.enabled or not self.check_available():
            logger.info("Ollama unavailable — using fallback response")
            return self._fallback_response(user_message)

        # Build message list
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt or self.system_prompt}
        ]

        # Inject context messages (memory, facts, etc.)
        if context_messages:
            for m in context_messages:
                messages.append(m.to_dict())

        # Inject conversation history if session_id provided
        if session_id and session_id in self._histories:
            for m in self._histories[session_id]:
                messages.append(m.to_dict())

        # Add current user message
        messages.append({"role": "user", "content": user_message})

        for attempt in range(self.max_retries + 1):
            try:
                body = json.dumps({
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "num_predict": 2048,
                        "temperature": 0.7,
                    },
                }).encode()

                req = Request(
                    f"{OLLAMA_API_BASE}/api/chat",
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode())

                response_text = (data.get("message", {}) or {}).get("content", "").strip()
                if response_text:
                    # Auto-add to history if session_id provided
                    if session_id:
                        self.add_to_history(session_id, "user", user_message)
                        self.add_to_history(session_id, "assistant", response_text)
                    return response_text

                logger.warning("Ollama returned empty response (attempt %d)", attempt + 1)

            except (HTTPError, URLError, TimeoutError, OSError) as e:
                logger.warning("Ollama API error (attempt %d): %s", attempt + 1, e)
            except json.JSONDecodeError as e:
                logger.warning("Ollama JSON decode error (attempt %d): %s", attempt + 1, e)

            if attempt < self.max_retries:
                time.sleep(1.0)

        return self._fallback_response(user_message)

    def stream_chat(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        context_messages: Optional[List[ChatMessage]] = None,
    ) -> str:
        """Same as chat() but accumulates result from streaming response.

        Useful for long responses; returns fully accumulated text.
        Falls back to non-streaming if streaming fails.
        """
        if not self.enabled or not self.check_available():
            logger.info("Ollama unavailable — using fallback response")
            return self._fallback_response(user_message)

        # Build the same message list as chat()
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt or self.system_prompt}
        ]
        if context_messages:
            for m in context_messages:
                messages.append(m.to_dict())
        if session_id and session_id in self._histories:
            for m in self._histories[session_id]:
                messages.append(m.to_dict())
        messages.append({"role": "user", "content": user_message})

        for attempt in range(1):  # no retry on streaming
            try:
                body = json.dumps({
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                    "options": {"num_predict": 2048, "temperature": 0.7},
                }).encode()

                req = Request(
                    f"{OLLAMA_API_BASE}/api/chat",
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(req, timeout=self.timeout) as resp:
                    full_text = ""
                    buffer = b""
                    while True:
                        chunk = resp.read(4096)
                        if not chunk:
                            break
                        buffer += chunk
                        # Try to parse complete JSON lines
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                                delta = (obj.get("message", {}) or {}).get("content", "")
                                full_text += delta
                            except json.JSONDecodeError:
                                continue

                    response_text = full_text.strip()
                    if response_text:
                        if session_id:
                            self.add_to_history(session_id, "user", user_message)
                            self.add_to_history(session_id, "assistant", response_text)
                        return response_text

            except Exception as e:
                logger.warning("Ollama streaming failed, falling back: %s", e)
                return self.chat(
                    user_message=user_message,
                    system_prompt=system_prompt,
                    session_id=session_id,
                    context_messages=context_messages,
                )

        return self._fallback_response(user_message)

    # ── Fallback ─────────────────────────────────────────────────────────────

    def _fallback_response(self, user_message: str) -> str:
        """Generate a canned response when the LLM is unavailable."""
        msg = user_message.lower().strip()

        if any(k in msg for k in ["hello", "hi ", "hey", "howdy", "sup"]):
            return "Hello! I'm JARVIS. What can I help you with?"
        if "who are you" in msg or "what are you" in msg:
            return "I'm JARVIS, your personal AI assistant. I can help with file operations, system checks, running Python code, and more. Say 'help' to see what I can do."
        if "help" in msg or "what can you" in msg:
            return "I can read files, list directories, run Python code, check disk usage, tell you the time, and report system info. I can also execute commands through Hermes."
        if "thank" in msg:
            return "You're welcome! Let me know if you need anything else."
        if "goodbye" in msg or "bye" in msg or "see you" in msg:
            return "Goodbye! I'll be here when you need me."
        if "time" in msg or "date" in msg:
            from datetime import datetime
            now = datetime.now().strftime("%I:%M %p on %A, %B %d, %Y")
            return f"The current time is {now}."
        if "drift" in msg:
            return "I can run a drift check to see if all my capabilities are available. Just say 'run drift check'."
        if "approval" in msg:
            return "Actions that need approval will show up on the dashboard at /dashboard. You can approve or deny them there."
        if "memory" in msg:
            return "I can remember things you tell me. I'm powered by a Llama 3.2 model running locally on this machine."

        return f"I understand you asked: \"{user_message[:80]}\". I can help with file operations, system checks, and running commands. Try saying something like 'read my pyproject.toml' or 'check disk usage'."

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def list_local_models(self) -> List[str]:
        """Return list of locally available Ollama models."""
        try:
            req = Request(f"{OLLAMA_API_BASE}/api/tags", method="GET")
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            return [tag.get("name", "?") for tag in data.get("models", [])]
        except Exception:
            return []