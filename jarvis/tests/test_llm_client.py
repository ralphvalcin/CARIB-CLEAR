"""Tests for LLMClient with Ollama HTTP API."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from jarvis.runtime.llm_client import LLMClient


class TestLLMClientInit:
    def test_default_model(self) -> None:
        client = LLMClient()
        assert client.model == "llama3.2:3b"
        assert client.timeout == 30.0

    def test_custom_model(self) -> None:
        client = LLMClient(model="qwen2.5:3b")
        assert client.model == "qwen2.5:3b"

    def test_enabled_by_default(self) -> None:
        client = LLMClient()
        assert client.enabled is True

    def test_disabled_fallback(self) -> None:
        """When enabled=False, chat should return fallback without calling Ollama."""
        client = LLMClient()
        client.enabled = False
        resp = client.chat("hello")
        assert len(resp) > 0
        assert "JARVIS" in resp


class TestLLMFallback:
    def test_greeting(self) -> None:
        client = LLMClient()
        client.enabled = False
        resp = client.chat("hello there")
        assert len(resp) > 0
        assert "JARVIS" in resp

    def test_who_are_you(self) -> None:
        client = LLMClient()
        client.enabled = False
        resp = client.chat("who are you?")
        assert "JARVIS" in resp or "assistant" in resp

    def test_help_request(self) -> None:
        client = LLMClient()
        client.enabled = False
        resp = client.chat("what can you do?")
        assert "read files" in resp or "file" in resp

    def test_thanks(self) -> None:
        client = LLMClient()
        client.enabled = False
        resp = client.chat("thank you")
        assert "welcome" in resp.lower()

    def test_time_query(self) -> None:
        client = LLMClient()
        client.enabled = False
        resp = client.chat("what time is it")
        assert ":" in resp or "time" in resp.lower()

    def test_generic_fallback(self) -> None:
        client = LLMClient()
        client.enabled = False
        resp = client.chat("tell me a joke")
        assert len(resp) > 0
        assert "file operations" in resp  # generic fallback mentions capabilities


class TestLLMCheckAvailable:
    def test_returns_false_when_ollama_not_running(self) -> None:
        client = LLMClient()
        with patch("jarvis.runtime.llm_client.urlopen") as mock_urlopen:
            from urllib.error import URLError
            mock_urlopen.side_effect = URLError("connection refused")
            assert client.check_available() is False

    def test_returns_false_when_model_not_in_list(self) -> None:
        client = LLMClient()
        fake_response = MagicMock()
        fake_response.read.return_value = json.dumps({"models": [{"name": "gemma4:latest"}]}).encode()
        fake_response.__enter__.return_value = fake_response
        with patch("jarvis.runtime.llm_client.urlopen", return_value=fake_response):
            assert client.check_available() is False

    def test_returns_true_when_model_available(self) -> None:
        client = LLMClient()
        fake_response = MagicMock()
        fake_response.read.return_value = json.dumps({"models": [{"name": "llama3.2:3b"}]}).encode()
        fake_response.__enter__.return_value = fake_response
        with patch("jarvis.runtime.llm_client.urlopen", return_value=fake_response):
            assert client.check_available() is True

    def test_results_are_cached(self) -> None:
        client = LLMClient()
        fake_response = MagicMock()
        fake_response.read.return_value = json.dumps({"models": [{"name": "llama3.2:3b"}]}).encode()
        fake_response.__enter__.return_value = fake_response
        with patch("jarvis.runtime.llm_client.urlopen", return_value=fake_response) as mock_urlopen:
            assert client.check_available() is True
            assert client.check_available() is True
            assert mock_urlopen.call_count == 1


class TestLLMChatWithMock:
    def test_successful_chat(self) -> None:
        client = LLMClient()
        client._available = True  # bypass check
        fake_response = MagicMock()
        fake_response.read.return_value = json.dumps({
            "message": {"content": "I am fine, thank you."},
            "done": True,
        }).encode()
        fake_response.__enter__.return_value = fake_response
        with patch("jarvis.runtime.llm_client.urlopen", return_value=fake_response):
            resp = client.chat("how are you?")
            assert "fine" in resp

    def test_empty_response_uses_fallback(self) -> None:
        client = LLMClient()
        client._available = True
        fake_response = MagicMock()
        fake_response.read.return_value = json.dumps({
            "message": {"content": ""},
            "done": True,
        }).encode()
        fake_response.__enter__.return_value = fake_response
        with patch("jarvis.runtime.llm_client.urlopen", return_value=fake_response):
            resp = client.chat("hello")
            assert len(resp) > 0
            # Should fall back since empty response
            assert "JARVIS" in resp or "help" in resp

    def test_timeout_uses_fallback(self) -> None:
        client = LLMClient(max_retries=1, timeout=0.1)
        client._available = True
        with patch("jarvis.runtime.llm_client.urlopen") as mock_urlopen:
            from urllib.error import URLError
            mock_urlopen.side_effect = URLError("timeout")
            resp = client.chat("hello")
            assert len(resp) > 0
            assert "JARVIS" in resp or "help" in resp

    def test_chat_adds_to_history(self) -> None:
        client = LLMClient()
        client._available = True
        fake_response = MagicMock()
        fake_response.read.return_value = json.dumps({
            "message": {"content": "I remember!"},
            "done": True,
        }).encode()
        fake_response.__enter__.return_value = fake_response
        with patch("jarvis.runtime.llm_client.urlopen", return_value=fake_response):
            resp = client.chat("remember this", session_id="test_sid")
            assert "remember" in resp.lower() or "I remember" in resp
            assert len(client._histories.get("test_sid", [])) == 2  # user + assistant

    def test_context_messages_injected(self) -> None:
        from jarvis.runtime.llm_client import ChatMessage
        client = LLMClient()
        client._available = True
        fake_response = MagicMock()
        fake_response.read.return_value = json.dumps({
            "message": {"content": "Got it!"},
            "done": True,
        }).encode()
        fake_response.__enter__.return_value = fake_response

        ctx_messages = [ChatMessage("system", "Context: user's name is Ralph")]
        with patch("jarvis.runtime.llm_client.urlopen", return_value=fake_response) as mock_urlopen:
            resp = client.chat("say my name", context_messages=ctx_messages)
            assert len(resp) > 0

            # Verify the request body included the context message
            call_args = mock_urlopen.call_args
            if call_args and call_args[0]:
                req = call_args[0][0]
                if hasattr(req, 'data') and req.data:
                    body = req.data.decode('utf-8')
                    assert "Ralph" in body or "Context:" in body or "context" in body.lower()


class TestListModels:
    def test_returns_models(self) -> None:
        client = LLMClient()
        fake_response = MagicMock()
        fake_response.read.return_value = json.dumps({
            "models": [{"name": "llama3.2:3b"}, {"name": "gemma4:latest"}]
        }).encode()
        fake_response.__enter__.return_value = fake_response
        with patch("jarvis.runtime.llm_client.urlopen", return_value=fake_response):
            models = client.list_local_models()
            assert "llama3.2:3b" in models
            assert "gemma4:latest" in models

    def test_returns_empty_on_failure(self) -> None:
        client = LLMClient()
        with patch("jarvis.runtime.llm_client.urlopen") as mock_urlopen:
            from urllib.error import URLError
            mock_urlopen.side_effect = URLError("connection refused")
            models = client.list_local_models()
            assert models == []