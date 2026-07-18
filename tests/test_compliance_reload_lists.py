"""Compliance reload / lists API hardening tests."""

from __future__ import annotations

import json

import pytest

from carib_clear.config_reloader import reload_compliance_lists


def test_reload_lists_helper_rejects_missing_path():
    result = reload_compliance_lists(path="/nonexistent", actor="test")
    assert result["status"] == "failed"
    assert result["reason"] == "missing or unreadable lists path"
    assert result["source_count"] == 0
    assert result["keyword_groups"] == []
    assert result["content_sha256"] == ""


def test_reload_lists_helper_rejects_empty_file(tmp_path):
    path = tmp_path / "compliance_lists.json"
    path.write_text("")
    result = reload_compliance_lists(path=str(path), actor="test")

    assert result["status"] == "failed"
    assert result["reason"] == "empty compliance lists file"
    assert result["source_count"] == 0
    assert result["keyword_groups"] == []
    assert "content_sha256" in result
    assert result["content_sha256"] == ""


def test_reload_lists_helper_returns_shape_fields(tmp_path):
    path = tmp_path / "compliance_lists.json"
    path.write_text(json.dumps({"keywords": {"sanctions": ["x"]}, "sources": {}}))
    result = reload_compliance_lists(path=str(path), actor="test")

    assert result["status"] in {"success", "failed"}
    assert "file" in result
    assert "source_count" in result
    assert "keyword_groups" in result
    assert "content_sha256" in result
    assert "cache_max_size" in result


def test_compliance_lists_reload_response_shape_alignment(tmp_path):
    path = tmp_path / "compliance_lists.json"
    path.write_text(json.dumps({"keywords": {"sanctions": ["x"]}, "sources": {}}))
    result = reload_compliance_lists(path=str(path), actor="test")

    expected_fields = {"file", "source_count", "keyword_groups"}
    assert expected_fields.issubset(result.keys())

    if result.get("status") == "success":
        assert result["source_count"] >= 1
        assert "content_sha256" in result


def test_compliance_lists_empty_file_rejects_before_reload(tmp_path):
    path = tmp_path / "compliance_lists.json"
    path.write_text("")
    result = reload_compliance_lists(path=str(path), actor="test")

    assert result["status"] == "failed"
    assert result["reason"] == "empty compliance lists file"
    assert "content_sha256" in result
