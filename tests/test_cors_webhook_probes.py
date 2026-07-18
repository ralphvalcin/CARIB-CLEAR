"""Focused CORS and webhook queue hardening probes."""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from carib_clear.api import app
from carib_clear.auth import _hash_secret
from carib_clear.db import get_db, reset_db

os.environ.setdefault("CARIB_CLEAR_ENV", "local")


def test_cors_origin_configuration_denies_by_default_with_local_fallback():
    from carib_clear.api import _build_cors_origins

    defaults = _build_cors_origins()
    assert defaults == ["http://localhost:5173"]


def test_cors_explicit_allowed_origin_is_returned_by_config(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ALLOWED_ORIGINS", "https://app.example.com")
    from carib_clear.api import _build_cors_origins

    allowed = _build_cors_origins()
    assert allowed == ["https://app.example.com"]

    monkeypatch.delenv("CARIB_CLEAR_ALLOWED_ORIGINS", raising=False)


def test_cors_local_fallback_is_applied_when_no_env_origin():
    from carib_clear.api import _build_cors_origins

    fallback_defaults = _build_cors_origins()
    assert fallback_defaults == ["http://localhost:5173"]


def _seed_webhook_participant():
    db = get_db()
    db.create_participant("queue_probe", "Queue Probe", "HT", participant_type="msme")
    secret = "probe-secret-" + "x" * 6
    db.create_api_key(
        key_id="key-queue_probe",
        participant_id="queue_probe",
        prefix=secret[:12],
        secret_hash=_hash_secret(secret),
        name="probe-key",
    )
    return secret


def test_webhook_dispatch_failure_queues_delivery(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ENV", "local")
    monkeypatch.setenv("CARIB_CLEAR_API_KEY", "local-api-key")
    try:
        from carib_clear.api_hardening import limiter
        limiter._windows.clear()
    except Exception:
        pass

    reset_db("/tmp/queue_probe_same.db")
    secret = _seed_webhook_participant()
    client = TestClient(app)
    response = client.post(
        "/webhooks/register",
        headers={"X-API-Key": secret, "Content-Type": "application/json"},
        json={
            "url": "http://127.0.0.2:1/nope",
            "events": ["settlement.completed"],
            "description": "queue probe",
        },
    )
    assert response.status_code == 200, response.text
    webhook_id = response.json()["webhook_id"]

    get_dispatcher = __import__("carib_clear.webhooks", fromlist=["get_dispatcher"]).get_dispatcher
    get_dispatcher().dispatch(
        "settlement.completed",
        {"probe": True},
        participant_id="queue_probe",
    )

    db = get_db()
    rows = db.query(
        "SELECT * FROM webhook_delivery_queue WHERE webhook_id = ?",
        (webhook_id,),
    )
    assert len(rows) >= 1, "queue should contain a failed delivery"
    assert rows[0]["status"] == "queued"
    assert rows[0]["error_message"]
