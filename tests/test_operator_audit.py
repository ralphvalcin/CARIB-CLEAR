"""Operator audit API tests."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient
import pytest

from carib_clear.api import app
from carib_clear.audit import audit
from carib_clear.db import get_db, reset_db


os.environ.setdefault("CARIB_CLEAR_ENV", "local")


def _make_client() -> TestClient:
    return TestClient(app)


def test_admin_audit_list_returns_events(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")
    client = _make_client()
    response = client.get("/audit/events", headers={"X-Admin-Token": "phase4-admin-token"})
    assert response.status_code == 200
    body = response.json()
    assert "events" in body
    assert "total" in body
    assert body["limit"] == 100
    assert body["offset"] == 0


def test_admin_audit_list_filters_by_event(monkeypatch, tmp_path):
    monkeypatch.setenv("CARIB_CLEAR_ENV", "local")
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")

    db_file = tmp_path / "admin_audit_list_filter.db"
    reset_db(str(db_file))
    get_db().query(
        "INSERT OR REPLACE INTO audit_trail(audit_id,event,actor,action,entity,entity_id,payload,outcome,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "evt-1",
            "loan.apply",
            "api",
            "apply_for_loan",
            "loan_application",
            "loan-1",
            "{}",
            "success",
            "2026-01-01T00:00:00+00:00",
        ),
    )

    client = _make_client()
    response = client.get("/audit/events?event=loan.apply&limit=10", headers={"X-Admin-Token": "phase4-admin-token"})
    assert response.status_code == 200
    events = response.json()["events"]
    assert all(event["event"] == "loan.apply" for event in events)


def test_admin_audit_detail_helper_returns_record_and_masks_secrets(tmp_path):
    db_file = tmp_path / "admin_audit_detail_helper.db"
    reset_db(str(db_file))
    get_db().query(
        "INSERT OR REPLACE INTO audit_trail(audit_id,event,actor,action,entity,entity_id,payload,outcome,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "audit-detail-1",
            "compliance.reload_lists",
            "operator",
            "reload_compliance_lists",
            "compliance_lists",
            "list-1",
            '{"api_key": "secret"}',
            "success",
            "2026-01-01T00:00:00+00:00",
        ),
    )

    from carib_clear.audit import get_audit_by_id
    record = get_audit_by_id("audit-detail-1", db=get_db())
    assert record is not None
    assert record["audit_id"] == "audit-detail-1"
    assert record["payload"] == {"***": "redacted"}


def test_operator_console_page_returns_html(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")
    client = _make_client()
    response = client.get("/operator", headers={"X-Admin-Token": "phase4-admin-token"})
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("text/html")


def test_operator_note_requires_existing_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("CARIB_CLEAR_ENV", "local")
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")

    db_file = tmp_path / "operator_note_404.db"
    reset_db(str(db_file))

    client = _make_client()
    response = client.post(
        "/operator/audit/does-not-exist/note",
        headers={"X-Admin-Token": "phase4-admin-token", "Content-Type": "application/json"},
        json={"note": "test"},
    )
    assert response.status_code == 404


def test_operator_escalate_requires_existing_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("CARIB_CLEAR_ENV", "local")
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")

    db_file = tmp_path / "operator_escalate_404.db"
    reset_db(str(db_file))

    client = _make_client()
    response = client.post(
        "/operator/audit/does-not-exist/escalate",
        headers={"X-Admin-Token": "phase4-admin-token", "Content-Type": "application/json"},
        json={"reason": "test"},
    )
    assert response.status_code == 404
