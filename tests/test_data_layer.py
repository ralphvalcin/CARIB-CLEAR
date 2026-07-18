"""Phase 7 production data layer prep."""
from __future__ import annotations

import os

import pytest
from carib_clear.db import get_db, reset_db


def test_default_sqlite_path_is_project_db():
    reset_db(db_path=":memory:")
    db = get_db()
    assert db.db_path == ":memory:"


def test_database_url_env_override(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_DATABASE_URL", "sqlite:///override.db")
    db = reset_db(db_path="")
    assert db.database_url == "sqlite:///override.db"
    assert db.db_path == "override.db"


def test_database_url_env_override_does_not_leak(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_DATABASE_URL", "sqlite:///override.db")
    reset_db(db_path="")
    try:
        db = get_db()
        assert db.database_url == "sqlite:///override.db"
    finally:
        monkeypatch.delenv("CARIB_CLEAR_DATABASE_URL", raising=False)
        reset_db(db_path=":memory:")


def test_sqlite_url_prefix_is_accepted(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_DATABASE_URL", "sqlite:///custom.db")
    db = reset_db(db_path="")
    assert db.db_path == "custom.db"
    assert db.database_url == "sqlite:///custom.db"
    monkeypatch.delenv("CARIB_CLEAR_DATABASE_URL", raising=False)
    reset_db(db_path=":memory:")
