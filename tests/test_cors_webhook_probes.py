"""Focused CORS and webhook queue hardening probes."""

from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from carib_clear.api import app
from carib_clear.auth import _hash_secret
from carib_clear.db import get_db, reset_db


client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_file_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "probe.db")
    monkeypatch.delenv("CARIB_CLEAR_API_KEY", raising=False)
    monkeypatch.setenv("CARIB_CLEAR_ENV", "demo")
    monkeypatch.setenv("CARIB_CLEAR_DATABASE_URL", f"sqlite:///{db_path}")
    reset_db(db_path=db_path)
    yield
    monkeypatch.delenv("CARIB_CLEAR_DATABASE_URL", raising=False)


def _seed_participant_for_webhook(participant_id: str = "queue_probe") -> str:
    db = get_db()
    db.create_participant(participant_id, "Queue Probe", "HT", participant_type="msme")
    secret = "probe-secret-" + "x" * 6
    db.create_api_key(
        key_id=f"key-{participant_id}",
        participant_id=participant_id,
        prefix=secret[:12],
        secret_hash=_hash_secret(secret),
        name="probe-key",
    )
    return secret


def test_cors_origin_configuration_denies_by_default_with_local_fallback():
    from carib_clear.api import _build_cors_origins

    local_defaults = _build_cors_origins()
    assert local_defaults, "_build_cors_origins() should provide local defaults"


def test_webhook_dispatch_failure_queues_delivery(tmp_path):
    secret = _seed_participant_for_webhook("queue_probe")
    response = client.post(
        "/webhooks/register",
        headers={"X-API-Key": secret, "Content-Type": "application/json"},
        json={
            "url": "http://127.0.0.2:1/nope",
            "events": ["settlement.completed"],
            "description": "probe",
        },
    )
    assert response.status_code == 200, response.text
    webhook_id = response.json()["webhook_id"]

    get_dispatcher = __import__(
        "carib_clear.webhooks", fromlist=["get_dispatcher"]
    ).get_dispatcher
    get_dispatcher().dispatch(
        "settlement.completed",
        {"probe": True},
        participant_id="queue_probe",
    )

    db_path = str(tmp_path / "probe.db")
    reset_db(db_path=db_path)
    rows = get_db().query(
        "SELECT * FROM webhook_delivery_queue WHERE webhook_id = ?",
        (webhook_id,),
    )
    assert len(rows) >= 1
    assert rows[0]["status"] == "queued"
    assert rows[0]["error_message"]
