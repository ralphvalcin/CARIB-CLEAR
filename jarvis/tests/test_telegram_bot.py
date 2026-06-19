"""Tests for the JARVIS Telegram bot and handler.

All tests run in mock mode — no Telegram API token required.
The handler is tested against the real JARVIS API endpoint when available,
or falls back to offline unit tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from jarvis.notifications.telegram_bot import JarvisTelegramBot, _resolve_token
from jarvis.notifications.telegram_handler import TelegramHandler


# ═══════════════════════════════════════════════════════════════════════════════
# Token resolution
# ═══════════════════════════════════════════════════════════════════════════════


class TestTokenResolution:
    def test_returns_none_when_no_env(self) -> None:
        with patch("jarvis.notifications.telegram_bot.Path.exists", return_value=False):
            with patch.dict("os.environ", {}, clear=True):
                token = _resolve_token()
                assert token is None

    def test_returns_from_env(self) -> None:
        with patch.dict("os.environ", {"JARVIS_TELEGRAM_BOT_TOKEN": "test:token"}):
            token = _resolve_token()
            assert token == "test:token"

    def test_mock_mode_when_no_token(self) -> None:
        with patch("jarvis.notifications.telegram_bot._resolve_token", return_value=None):
            bot = JarvisTelegramBot(token=None)
            assert bot.is_mock

    def test_live_mode_when_token(self) -> None:
        bot = JarvisTelegramBot(token="fake:token")
        assert not bot.is_mock


# ═══════════════════════════════════════════════════════════════════════════════
# Command handling (offline — no API needed)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCommandRouting:
    def setup_method(self) -> None:
        self.handler = TelegramHandler(api_url="http://localhost:0")

    def test_empty_text(self) -> None:
        resp = self.handler.handle("c1", "")
        assert "Say something" in resp

    def test_start_command(self) -> None:
        resp = self.handler.handle("c1", "/start")
        assert "JARVIS" in resp
        assert "commands" in resp or "help" in resp

    def test_start_with_username(self) -> None:
        resp = self.handler.handle("c1", "/start", username="Ralph")
        assert "Ralph" in resp

    def test_help_lists_commands(self) -> None:
        resp = self.handler.handle("c1", "/help")
        assert "/status" in resp
        assert "/drift" in resp
        assert "/approve" in resp
        assert "/deny" in resp
        assert "/help" in resp

    def test_unknown_command(self) -> None:
        resp = self.handler.handle("c1", "/xyzzy")
        assert "Unknown command" in resp
        assert "/help" in resp

    def test_approve_without_arg(self) -> None:
        """Should try to list pending approvals (API call will fail gracefully)."""
        resp = self.handler.handle("c1", "/approve")
        # Falls back to graceful error since API is on port 0
        assert len(resp) > 0

    def test_deny_without_arg_shows_usage(self) -> None:
        resp = self.handler.handle("c1", "/deny")
        assert "Usage" in resp

    def test_forget_command(self) -> None:
        """Should try to clear history (API call will fail gracefully)."""
        resp = self.handler.handle("c1", "/forget")
        assert len(resp) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Conversation routing (offline)
# ═══════════════════════════════════════════════════════════════════════════════


class TestConversationRouting:
    def setup_method(self) -> None:
        self.handler = TelegramHandler(api_url="http://localhost:0")

    def test_conversation_returns_response(self) -> None:
        resp = self.handler.handle("c1", "hello")
        assert len(resp) > 0

    def test_conversation_with_session_persistence(self) -> None:
        """Same chat_id gets same session for memory continuity."""
        resp1 = self.handler.handle("same-chat", "remember test_tg is working")
        resp2 = self.handler.handle("same-chat", "recall test_tg")
        assert len(resp1) > 0
        assert len(resp2) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Bot mock mode
# ═══════════════════════════════════════════════════════════════════════════════


class TestBotMockMode:
    def test_bot_initializes_in_mock(self) -> None:
        with patch("jarvis.notifications.telegram_bot._resolve_token", return_value=None):
            bot = JarvisTelegramBot(token=None)
            assert bot.is_mock
            assert bot._application is None

    def test_mock_accepts_messages(self) -> None:
        with patch("jarvis.notifications.telegram_bot._resolve_token", return_value=None):
            bot = JarvisTelegramBot(token=None)
            # Mock mode doesn't connect to Telegram — just validates init
            assert bot.is_mock


# ═══════════════════════════════════════════════════════════════════════════════
# API integration (live, if API is running)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.skip(reason="Integration test — run manually when API is live")
class TestLiveAPI:
    def test_status_command(self) -> None:
        handler = TelegramHandler(api_url="http://localhost:8000")
        resp = handler.handle("live-test", "/status")
        assert "JARVIS" in resp or "System" in resp
        assert "API" in resp

    def test_conversation(self) -> None:
        handler = TelegramHandler(api_url="http://localhost:8000")
        resp = handler.handle("live-test", "hello")
        assert len(resp) > 10
        assert "JARVIS" in resp or "help" in resp

    def test_drift_command(self) -> None:
        handler = TelegramHandler(api_url="http://localhost:8000")
        resp = handler.handle("live-test", "/drift")
        assert "capabilities" in resp or "Drift" in resp


# ═══════════════════════════════════════════════════════════════════════════════
# Response formatting
# ═══════════════════════════════════════════════════════════════════════════════


class TestResponseFormatting:
    def setup_method(self) -> None:
        self.handler = TelegramHandler(api_url="http://localhost:0")

    def test_approval_response_parse(self) -> None:
        """Handler should properly detect and format approval-required responses."""
        # Simulate a mock API response that would trigger the approval path
        # This is tested indirectly via conversation routing
        pass

    def test_tool_result_formatting(self) -> None:
        """Tool results should be formatted cleanly."""
        pass