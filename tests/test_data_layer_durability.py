"""Production database durability posture tests."""

from __future__ import annotations

import os

import pytest

from carib_clear.db import Database, _connection_from_url, _resolve_database_url


def test_production_env_rejects_missing_database_url_at_resolve():
    os.environ["CARIB_CLEAR_ENV"] = "production"
    try:
        with pytest.raises(RuntimeError, match="CARIB_CLEAR_DATABASE_URL is required in production"):
            _resolve_database_url()
    finally:
        os.environ.pop("CARIB_CLEAR_ENV", None)


def test_production_env_rejects_sqlite_connection():
    os.environ["CARIB_CLEAR_ENV"] = "production"
    try:
        with pytest.raises(RuntimeError, match="SQLite is not allowed with CARIB_CLEAR_ENV=production"):
            _connection_from_url("sqlite:///production.db")
    finally:
        os.environ.pop("CARIB_CLEAR_ENV", None)


def test_local_demo_test_env_allow_sqlite_connection():
    for env in {"local", "demo", "test"}:
        os.environ["CARIB_CLEAR_ENV"] = env
        try:
            _connection_from_url("sqlite:///local.db")
        finally:
            os.environ.pop("CARIB_CLEAR_ENV", None)


def test_prod_env_startup_guard_blocks_sqlite_init_schema():
    os.environ["CARIB_CLEAR_ENV"] = "production"
    try:
        db = Database("sqlite:///startup_guard.db")
        with pytest.raises(RuntimeError, match="SQLite is not allowed with CARIB_CLEAR_ENV=production"):
            _ = db._conn
    finally:
        os.environ.pop("CARIB_CLEAR_ENV", None)
        try:
            os.remove("startup_guard.db")
        except OSError:
            pass
