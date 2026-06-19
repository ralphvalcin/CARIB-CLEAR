"""Tests for JARVIS voice module."""

from __future__ import annotations

from typing import Any, Dict
import json

from jarvis.voice.core import format_response_for_tts, VoiceConfig


def test_format_direct_response() -> None:
    resp = {"path": "direct_response", "response": "Aye, I can help with that."}
    tts = format_response_for_tts(resp)
    assert "I can help" in tts


def test_format_approval_required() -> None:
    resp = {
        "requires_approval": True,
        "action": "terminal",
        "reason": "shell commands need approval",
    }
    tts = format_response_for_tts(resp)
    assert "approval" in tts.lower()
    assert "terminal" in tts


def test_format_denied() -> None:
    resp = {"denied": True, "reason": "that action is not allowed"}
    tts = format_response_for_tts(resp)
    assert "denied" in tts.lower()


def test_format_drift_report() -> None:
    resp = {
        "path": "drift_check",
        "drift_report": {"missing": ["memory_add"], "stale": [], "unexpected": ["terminal"], "checked_at": 1000},
    }
    tts = format_response_for_tts(resp)
    assert "memory_add" in tts
    assert "missing" in tts.lower()


def test_format_drift_no_missing() -> None:
    resp = {
        "path": "drift_check",
        "drift_report": {"missing": [], "stale": [], "unexpected": [], "checked_at": 1000},
    }
    tts = format_response_for_tts(resp)
    assert "in sync" in tts or "complete" in tts.lower()


def test_format_tool_executed() -> None:
    resp = {"path": "tool_action", "tool_result": {"ok": True, "tool": "web_search"}}
    tts = format_response_for_tts(resp)
    assert "successfully" in tts


def test_format_fallback() -> None:
    resp = {"path": "fallback", "response": "I could not classify that."}
    tts = format_response_for_tts(resp)
    assert "rephrase" in tts.lower()


def test_format_error() -> None:
    resp = {"error": "something broke"}
    tts = format_response_for_tts(resp)
    assert "error" in tts.lower()


def test_format_tool_executed_with_error() -> None:
    resp = {"path": "tool_action", "tool_result": {"ok": False, "error": "timeout"}}
    tts = format_response_for_tts(resp)
    assert "issue" in tts.lower() or "timeout" in tts


def test_format_empty_dict() -> None:
    tts = format_response_for_tts({})
    assert "could not" in tts.lower() or "request" in tts.lower()


def test_format_none() -> None:
    tts = format_response_for_tts({"path": "direct_response"})
    assert tts  # should not crash


def test_voice_config_defaults() -> None:
    config = VoiceConfig()
    assert config.sample_rate == 16000
    assert config.whisper_model_size == "tiny"
    assert config.tts_engine == "piper"
    assert config.in_process is True
