"""Tests for voice Tavily search wiring and edge cases."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from jarvis.voice.core import VoiceLLMClient


def test_search_disabled_skips_injection() -> None:
    client = VoiceLLMClient(enable_search=False)
    with patch("jarvis.voice.searcher.search", return_value="Results") as search_mock:
        client._inject_search("what is the latest news")
    search_mock.assert_not_called()


def test_non_search_text_skips_tavily() -> None:
    client = VoiceLLMClient(enable_search=True)
    with patch("jarvis.voice.searcher.needs_search", return_value=False) as needs_mock:
        with patch("jarvis.voice.searcher.search", return_value="Results") as search_mock:
            client._inject_search("hello, how are you?")
    needs_mock.assert_called_once_with("hello, how are you?")
    search_mock.assert_not_called()


def test_search_results_appended_to_messages() -> None:
    client = VoiceLLMClient(enable_search=True)
    client.conversation.add_user("first question")
    with patch("jarvis.voice.searcher.search", return_value="Live results") as search_mock:
        client._inject_search("what is the latest news")

    search_mock.assert_called_once_with("what is the latest news")
    messages = client.conversation.messages
    assert messages[-1] == {"role": "system", "content": "Live results"}


def test_search_no_results_does_not_modify_conversation() -> None:
    client = VoiceLLMClient(enable_search=True)
    client.conversation.add_user("first question")
    with patch("jarvis.voice.searcher.search", return_value=None):
        client._inject_search("what is the latest news")

    messages = client.conversation.messages
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "first question"


def test_inject_search_keeps_user_last_before_llm_response() -> None:
    client = VoiceLLMClient(enable_search=True)
    with patch("jarvis.voice.searcher.search", return_value="context"):
        client.send("what is the latest news")
    msgs = client.conversation.messages
    # The LLM response is appended last.
    assert msgs[-2]["role"] == "user"
    assert msgs[-2]["content"] == "what is the latest news"
    assert msgs[-3]["role"] == "system"
    assert msgs[-3]["content"] == "context"
