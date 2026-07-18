"""Auth/webhook hardening regression probes."""

from __future__ import annotations

import hmac
import os

import pytest
from fastapi.testclient import TestClient

from carib_clear.api import app
from carib_clear.auth import _hash_secret
from carib_clear.db import get_db, reset_db

os.environ.setdefault("CARIB_CLEAR_ENV", "local")


def test_auth_bridge_supports_legacy_env_and_participant_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ENV", "local")
    monkeypatch.setenv("CARIB_CLEAR_API_KEY", "legacy-secret-key")
    db_path = str(tmp_path / "auth_bridge.db")
    monkeypatch.setenv("CARIB_CLEAR_DATABASE_URL", f"sqlite:///{db_path}")
    reset_db(db_path=db_path)

    db = get_db()
    db.create_participant("p_auth", "Auth Participant", "HT", participant_type="msme")
    secret = "participant-secret-" + "x" * 4
    db.create_api_key(
        key_id="key-auth",
        participant_id="p_auth",
        prefix=secret[:12],
        secret_hash=_hash_secret(secret),
        name="Auth Key",
    )

    client = TestClient(app)
    legacy = client.post("/loan/apply", json={"business_name": "Legacy Business", "jurisdiction": "HT", "amount_usd": 100, "sector": "retail", "purpose": "working_capital", "months": 12}, headers={"X-API-Key": "legacy-secret-key"})
    assert legacy.status_code == 200

    participant = client.post("/loan/apply", json={"business_name": "Participant Business", "jurisdiction": "HT", "amount_usd": 100, "sector": "retail", "purpose": "working_capital", "months": 12}, headers={"X-API-Key": secret})
    assert participant.status_code == 200

    missing = client.post("/loan/apply", json={"business_name": "Missing Business", "jurisdiction": "HT", "amount_usd": 100, "sector": "retail", "purpose": "working_capital", "months": 12}, headers={"X-API-Key": "wrong"})
    assert missing.status_code == 401


def test_webhook_register_never_exposes_full_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("CARIB_CLEAR_ENV", "local")
    monkeypatch.setenv("CARIB_CLEAR_API_KEY", "local-api-key")
    db_path = str(tmp_path / "webhook_hygiene.db")
    monkeypatch.setenv("CARIB_CLEAR_DATABASE_URL", f"sqlite:///{db_path}")
    reset_db(db_path=db_path)
    db = get_db()
    db.create_participant("wh_owner", "Webhook Owner", "HT", participant_type="msme")
    secret = "wh-owner-secret-" + "x" * 4
    db.create_api_key(
        key_id="key-wh-owner",
        participant_id="wh_owner",
        prefix=secret[:12],
        secret_hash=_hash_secret(secret),
        name="Webhook Key",
    )

    client = TestClient(app)
    response = client.post(
        "/webhooks/register",
        headers={"X-API-Key": secret, "Content-Type": "application/json"},
        json={"url": "http://127.0.0.2/invalid", "events": ["settlement.completed"], "description": "secret hygiene probe"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "secret" not in payload
    assert payload.get("secret_preview", "").endswith("...")
    assert payload["secret_preview"].startswith(payload["secret_preview"][:6])


def test_admin_routes_fail_closed_with_invalid_token(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "valid-admin-token")
    client = TestClient(app)
    response = client.get("/audit/events", headers={"X-Admin-Token": "bad-token"})
    assert response.status_code == 403
