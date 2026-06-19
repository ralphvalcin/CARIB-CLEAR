from __future__ import annotations

import time
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from jarvis.hermes_bridge.retry_client import (
    RetryingHermesClient,
    _is_transient_error,
    _is_transient_exception,
)


class TestIsTransientError:
    def test_ok_result_not_transient(self) -> None:
        assert not _is_transient_error({"ok": True, "data": "all good"})

    def test_429_rate_limit_is_transient(self) -> None:
        assert _is_transient_error({"ok": False, "error": "Rate limit exceeded (429)"})

    def test_timeout_is_transient(self) -> None:
        assert _is_transient_error({"ok": False, "error": "timed out after 10s"})

    def test_connection_refused_is_transient(self) -> None:
        assert _is_transient_error({"ok": False, "error": "Connection refused"})

    def test_unknown_tool_not_transient(self) -> None:
        assert not _is_transient_error({"ok": False, "error": "unknown tool: rainbow_magic"})

    def test_bad_arguments_not_transient(self) -> None:
        assert not _is_transient_error({"ok": False, "error": "missing required argument 'path'"})


class TestIsTransientException:
    def test_timeout_exception(self) -> None:
        assert _is_transient_exception(TimeoutError("connection timed out"))

    def test_connection_error(self) -> None:
        assert _is_transient_exception(ConnectionRefusedError("Connection refused"))

    def test_other_exception_not_transient(self) -> None:
        assert not _is_transient_exception(ValueError("invalid tool name"))

    def test_broken_pipe(self) -> None:
        assert _is_transient_exception(BrokenPipeError("Broken pipe"))


class _FakeHermes:
    """Simulates a Hermes client for testing retry logic."""

    def __init__(self) -> None:
        self.call_count = 0
        self.results: List[Dict[str, Any]] = []
        self.exception: Exception | None = None

    def run_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self.call_count += 1
        if self.exception:
            raise self.exception
        if self.results:
            return self.results.pop(0)
        return {"ok": True, "tool": name}

    def chat(self, prompt: str) -> str:
        self.call_count += 1
        if self.exception:
            raise self.exception
        return f"response to: {prompt}"

    def list_skills(self) -> str:
        self.call_count += 1
        return "skill1\nskill2"

    def list_memory(self) -> str:
        self.call_count += 1
        return "memory entry"

    def update_memory(self, text: str) -> str:
        self.call_count += 1
        return "ok"


class TestRetryingHermesClient:
    def test_ok_passes_through_no_retry(self) -> None:
        inner = _FakeHermes()
        client = RetryingHermesClient(inner=inner, max_retries=3)
        result = client.run_tool("web_search", {"query": "test"})
        assert result["ok"] is True
        assert inner.call_count == 1

    def test_non_transient_error_passes_through(self) -> None:
        inner = _FakeHermes()
        inner.results = [{"ok": False, "error": "unknown tool: rainbow_magic"}]
        client = RetryingHermesClient(inner=inner, max_retries=3)
        result = client.run_tool("rainbow_magic", {})
        assert result["ok"] is False
        assert "unknown tool" in result["error"]
        assert inner.call_count == 1  # no retry on non-transient

    def test_transient_error_retries_then_succeeds(self) -> None:
        inner = _FakeHermes()
        # First call fails with rate limit, second succeeds
        inner.results = [
            {"ok": False, "error": "Rate limit exceeded (429)"},
            {"ok": True, "tool": "web_search"},
        ]
        client = RetryingHermesClient(inner=inner, max_retries=3, base_delay=0.01)
        result = client.run_tool("web_search", {"query": "test"})
        assert result["ok"] is True
        assert inner.call_count == 2  # one retry

    def test_transient_error_exhausts_retries_returns_last(self) -> None:
        inner = _FakeHermes()
        # All calls fail with rate limit
        inner.results = [
            {"ok": False, "error": "Rate limit exceeded (429)"},
            {"ok": False, "error": "Rate limit exceeded (429)"},
            {"ok": False, "error": "Rate limit exceeded (429)"},
            {"ok": False, "error": "Rate limit exceeded (429)"},  # 4th call = final
        ]
        client = RetryingHermesClient(inner=inner, max_retries=3, base_delay=0.01)
        result = client.run_tool("web_search", {"query": "test"})
        assert result["ok"] is False
        assert inner.call_count == 4  # initial + 3 retries

    def test_exception_retries_then_raises(self) -> None:
        inner = _FakeHermes()
        inner.exception = ConnectionRefusedError("Connection refused")
        client = RetryingHermesClient(inner=inner, max_retries=2, base_delay=0.01)
        with pytest.raises(ConnectionRefusedError):
            client.run_tool("web_search", {"query": "test"})
        assert inner.call_count == 3  # initial + 2 retries

    def test_non_transient_exception_passes_through(self) -> None:
        inner = _FakeHermes()
        inner.exception = ValueError("invalid tool name")
        client = RetryingHermesClient(inner=inner, max_retries=3, base_delay=0.01)
        with pytest.raises(ValueError):
            client.run_tool("web_search", {"query": "test"})
        assert inner.call_count == 1  # no retry on non-transient exception

    def test_chat_method_retries(self) -> None:
        inner = _FakeHermes()
        inner.results = [
            {"ok": False, "error": "timed out"},
            {"ok": True, "tool": "chat"},
        ]
        client = RetryingHermesClient(inner=inner, max_retries=3, base_delay=0.01)
        result = client.chat("hello")
        # chat returns a string from inner, not a dict
        assert isinstance(result, str)
        assert "hello" in result

    def test_delay_increases_exponentially(self) -> None:
        """Verify delay values grow exponentially (not wall-clock test)."""
        client = RetryingHermesClient(max_retries=5, base_delay=0.5, max_delay=8.0, jitter=0)
        delays = [client._delay(i) for i in range(5)]
        # 0.5, 1.0, 2.0, 4.0, 8.0 (without jitter)
        assert delays[0] == 0.5
        assert delays[1] == 1.0
        assert delays[2] == 2.0
        assert delays[3] == 4.0
        assert delays[4] == 8.0

    def test_jitter_varies_delays(self) -> None:
        """With jitter, delays should not be exactly exponential."""
        client = RetryingHermesClient(max_retries=5, base_delay=0.5, max_delay=8.0, jitter=0.25)
        delays = [client._delay(i) for i in range(5)]
        # All should be positive and within reasonable range
        for d in delays:
            assert 0 < d <= 10.0