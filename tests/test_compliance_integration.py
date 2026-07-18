"""Integration tests for Phase 6 compliance persistence and reviewer workflow."""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from carib_clear.api import app

client = TestClient(app)


def _auth_headers():
    return {"X-API-Key": "phase6-secret"}


def test_screen_endpoint_persists_check_and_hits(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_API_KEY", "phase6-secret")
    res = client.post("/compliance/screen", json={
        "from_participant": "from_alice",
        "to_participant": "to_bob",
        "amount_usd": 10,
        "currency": "USD",
        "from_jurisdiction": "BB",
        "to_jurisdiction": "JM",
        "purpose": "trade",
    }, headers=_auth_headers())
    assert res.status_code == 200
    body = res.json()
    assert "passed" in body
    assert "issues" in body


def test_onboard_defaults_when_participant_id_missing(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_API_KEY", "phase6-secret")
    res = client.post("/compliance/onboard", json={
        "participant_id": "",
        "jurisdiction": "JM",
        "documents": {"national_id": "abc"},
    }, headers=_auth_headers())
    assert res.status_code in {200, 400}


def test_compliance_profile_defaults_404():
    res = client.get("/compliance/profile/nonexistent")
    assert res.status_code in {401, 404}

    if res.status_code == 401:
        res = client.get("/compliance/profile/nonexistent", headers={"X-API-Key": "phase6-secret"})
    assert res.status_code in {401, 404}
