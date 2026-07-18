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


def test_admin_audit_detail_returns_record_and_masks_secret_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("CARIB_CLEAR_ENV", "local")
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")

    db_file = tmp_path / "admin_audit_detail.db"
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

    client = _make_client()
    response = client.get("/audit/events?audit_id=audit-detail-1", headers={"X-Admin-Token": "phase4-admin-token"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["audit_id"] == "audit-detail-1"
    assert body["payload"] == {"***": "redacted"}


def test_admin_audit_detail_missing_returns_404(monkeypatch, tmp_path):
    monkeypatch.setenv("CARIB_CLEAR_ENV", "local")
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")

    db_file = tmp_path / "admin_audit_missing.db"
    reset_db(str(db_file))

    client = _make_client()
    response = client.get("/audit/events?audit_id=does-not-exist", headers={"X-Admin-Token": "phase4-admin-token"})
    assert response.status_code == 404


def test_audit_list_filter_returns_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("CARIB_CLEAR_ENV", "local")
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")

    db_file = tmp_path / "admin_audit_list.db"
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
    body = response.json()
    assert "events" in body
    assert all(row["event"] == "loan.apply" for row in body["events"])


def test_operator_note_appends_audit_record(monkeypatch, tmp_path):
    monkeypatch.setenv("CARIB_CLEAR_ENV", "local")
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")

    db_file = tmp_path / "operator_note.db"
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
            "{}",
            "success",
            "2026-01-01T00:00:00+00:00",
        ),
    )

    client = _make_client()
    response = client.post(
        "/operator/audit/audit-detail-1/note",
        headers={"X-Admin-Token": "phase4-admin-token"},
        json={"note": "Reviewed by operator"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "accepted"
    assert body["audit"]["event"] == "operator.note:compliance.reload_lists"
    assert body["audit"]["action"] == "note"
    assert body["audit"]["payload"] == {"audit_id": "audit-detail-1", "note": "Reviewed by operator"}

    events = client.get("/audit/events", headers={"X-Admin-Token": "phase4-admin-token"}).json()["events"]
    assert any(evt["audit_id"] == body["audit"]["audit_id"] for evt in events)


def test_operator_escalate_appends_audit_record(monkeypatch, tmp_path):
    monkeypatch.setenv("CARIB_CLEAR_ENV", "local")
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")

    db_file = tmp_path / "operator_escalate.db"
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
            "{}",
            "success",
            "2026-01-01T00:00:00+00:00",
        ),
    )

    client = _make_client()
    response = client.post(
        "/operator/audit/audit-detail-1/escalate",
        headers={"X-Admin-Token": "phase4-admin-token"},
        json={"reason": "Needs manual review"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "accepted"
    assert body["audit"]["event"] == "operator.escalate:compliance.reload_lists"
    assert body["audit"]["action"] == "escalate"
    assert body["audit"]["payload"] == {"audit_id": "audit-detail-1", "reason": "Needs manual review"}


def test_operator_actions_404_for_missing_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("CARIB_CLEAR_ENV", "local")
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")

    db_file = tmp_path / "operator_missing.db"
    reset_db(str(db_file))

    client = _make_client()
    response = client.post(
        "/operator/audit/does-not-exist/note",
        headers={"X-Admin-Token": "phase4-admin-token"},
        json={"note": "test"},
    )
    assert response.status_code == 404
    response = client.post(
        "/operator/audit/does-not-exist/escalate",
        headers={"X-Admin-Token": "phase4-admin-token"},
        json={"reason": "test"},
    )
    assert response.status_code == 404
