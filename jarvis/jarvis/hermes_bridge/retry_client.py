from __future__ import annotations

import time
import random
from typing import Any, Callable, Dict, List, Optional, TypeVar

from jarvis.hermes_bridge.client import CLIHermesClient

T = TypeVar("T")


def _is_transient_error(result: Dict[str, Any]) -> bool:
    """Check if a Hermes client result indicates a transient/retryable error."""
    if result.get("ok", False):
        return False

    error = str(result.get("error", "")).lower()
    # Transient patterns: rate limits, timeouts, connection issues, server errors
    transient_patterns = [
        "rate limit",
        "rate_limit",
        "429",
        "too many requests",
        "timeout",
        "timed out",
        "connection",
        "refused",
        "5xx",
        "503",
        "502",
        "unavailable",
        "service unavailable",
        "internal server error",
        "server error",
        "temporarily",
        "try again",
    ]
    return any(p in error for p in transient_patterns)


def _is_transient_exception(exc: Exception) -> bool:
    """Check if an exception is transient (connection/timeout related)."""
    msg = str(exc).lower()
    transient_patterns = [
        "timeout",
        "timed out",
        "connection",
        "econnrefused",
        "econnreset",
        "broken pipe",
        "name or service not known",
    ]
    return any(p in msg for p in transient_patterns)


class RetryingHermesClient:
    """Wraps CLIHermesClient with exponential backoff retry logic.

    Retries only on transient errors (rate limits, timeouts, connection issues).
    Non-transient errors (tool not found, bad arguments) pass through immediately.

    Default: 5 retries, base delay 0.5s, max delay 8.0s, jitter ±25%.
    """

    def __init__(
        self,
        inner: Optional[CLIHermesClient] = None,
        max_retries: int = 5,
        base_delay: float = 0.5,
        max_delay: float = 8.0,
        jitter: float = 0.25,
    ) -> None:
        self._inner = inner or CLIHermesClient()
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._jitter = jitter

    def _delay(self, attempt: int) -> float:
        """Calculate delay for this attempt with exponential backoff + jitter."""
        delay = min(self._base_delay * (2 ** attempt), self._max_delay)
        jitter_amount = delay * self._jitter
        return delay + random.uniform(-jitter_amount, jitter_amount)

    def _retry_call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute a callable with retry on transient errors."""
        last_result: Optional[T] = None
        last_exception: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):
            try:
                result = fn(*args, **kwargs)

                # If it's a dict result, check for transient errors
                if isinstance(result, dict) and not result.get("ok", True):
                    if attempt < self._max_retries and _is_transient_error(result):
                        delay = self._delay(attempt)
                        time.sleep(delay)
                        last_result = result
                        continue
                    return result

                return result

            except Exception as e:
                last_exception = e
                if attempt < self._max_retries and _is_transient_exception(e):
                    delay = self._delay(attempt)
                    time.sleep(delay)
                    continue
                raise

        # All retries exhausted — return the last result or raise the last exception
        if last_exception:
            raise last_exception
        if last_result is not None:
            return last_result

        # Shouldn't reach here, but defensive
        return fn(*args, **kwargs)  # type: ignore[return-value]

    # ── Hermes client interface ───────────────────────────────────────

    def run_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self._retry_call(self._inner.run_tool, name, arguments)  # type: ignore[return-value]

    def chat(self, prompt: str) -> str:
        return self._retry_call(self._inner.chat, prompt)

    def list_skills(self) -> str:
        return self._retry_call(self._inner.list_skills)

    def list_memory(self) -> str:
        return self._retry_call(self._inner.list_memory)

    def update_memory(self, text: str) -> str:
        return self._retry_call(self._inner.update_memory, text)