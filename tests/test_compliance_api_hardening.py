"""Compliance API hardening regression probes."""

from __future__ import annotations

import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from carib_clear.api import app
from carib_clear.auth import _hash_secret
from carib_clear.db import get_db, reset_db

os.environ.setdefault("CARIB_CLEAR_ENV", "local")


def _seed_participant(participant_id="comp-probe", jurisdiction="HT", api_key_value="comp-api-secret-1234"):
    reset_db("/tmp/compliance_probe.db")
    db = get_db()
    db.create_participant(participant_id, "Compliance Probe", jurisdiction, participant_type="msme")
    db.create_api_key(
        key_id="key-" + participant_id,
        participant_id=participant_id,
        prefix=api_key_value[:12],
        secret_hash=_hash_secret(api_key_value),
        name="compliance probe key",
    )
    return participant_id, api_key_value


def test_compliance_lists_hides_local_file_path_and_requires_admin(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "good-admin-token")
    client = TestClient(app)

    assert client.get("/compliance/lists", headers={"X-API-Key": "some-api"}).status_code in {401, 403, 404, 422}
    assert client.get("/compliance/lists").status_code in {401, 403, 404, 422}

    response = client.get("/compliance/lists", headers={"X-Admin-Token": "good-admin-token"})
    assert response.status_code == 200
    payload = response.json()
    assert "file" not in payload


def test_compliance_reload_lists_requires_admin_and_validates_path(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "good-admin-token")
    client = TestClient(app)

    assert client.post("/compliance/reload-lists").status_code in {401, 403, 404, 422}
    bad = client.post("/compliance/reload-lists", headers={"X-Admin-Token": "bad"})
    assert bad.status_code == 403
    bad = client.post("/compliance/reload-lists", headers={"X-Admin-Token": "bad"})
    assert bad.status_code == 403
