"""Operator console date-range regression probes."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from carib_clear.api import app
from carib_clear.db import get_db, reset_db

os.environ.setdefault("CARIB_CLEAR_ENV", "local")


def test_operator_console_includes_start_end_fields(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")
    client = TestClient(app)
    response = client.get("/operator", headers={"X-Admin-Token": "phase4-admin-token"})
    assert response.status_code == 200
    html = response.text
    assert 'id="start"' in html
    assert 'id="end"' in html
    assert 'datetime-local' in html


def test_audit_events_filters_by_start_timestamp(tmp_path, monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")
    db_file = tmp_path / "op_date.db"
    reset_db(str(db_file))
    base = "2026-01-01T00:00:00+00:00"
    end = "2026-12-31T23:59:59+00:00"
    get_db().query(
        "INSERT OR REPLACE INTO audit_trail(audit_id,event,actor,action,entity,entity_id,payload,outcome,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("evt-1", "operator.note", "operator:admin", "note", "settlement", "stl-1", "{}", "success", "2026-06-01T00:00:00+00:00"),
    )
    client = TestClient(app)
    before = client.get("/audit/events", params={"start": base, "end": end}, headers={"X-Admin-Token": "phase4-admin-token"})
    assert before.status_code == 200
    data = before.json()
    assert "events" in data
    assert all(base <= evt.get("created_at", "") <= end for evt in data["events"])
