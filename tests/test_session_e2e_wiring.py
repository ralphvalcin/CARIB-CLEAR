"""Focused session-wiring tests for security, auth, and settlement correctness."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from carib_clear.api import app
from carib_clear.auth import _hash_secret, require_api_key
from carib_clear.db import get_db, reset_db
from carib_clear.errors import CARIBClearException

client = TestClient(app)


def test_legacy_api_key_when_configured():
    reset_db(db_path=":memory:")
    with pytest.raises(CARIBClearException) as exc:
        require_api_key(x_api_key="wrong")
    assert exc.value.status_code == 401


def test_api_key_disabled_by_default():
    reset_db(db_path=":memory:")
    try:
        from carib_clear.api_hardening import limiter
        limiter._windows.clear()
    except Exception:
        pass
    res = client.post("/loan/apply", json={
        "business_name": "A",
        "jurisdiction": "BB",
        "amount_usd": 10,
    })
    assert res.status_code == 200


def test_settlement_events_endpoint_wiring():
    reset_db(db_path=":memory:")
    row = get_db().query_one("SELECT name FROM sqlite_master WHERE type='table' AND name='settlement_events'")
    assert row is not None
    events = get_db().get_settlement_events("stellar_usdc:missing")
    assert events == []
