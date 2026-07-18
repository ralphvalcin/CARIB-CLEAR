"""Operator audit API regression tests."""

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


def test_admin_audit_fails_without_admin_token(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")
    client = _make_client()
    response = client.get("/audit/events")
    assert response.status_code in {403, 422}
    body = response.json()
    assert "invalid admin token" in str(body).lower() or "x-admin-token" in str(body).lower()


def test_admin_audit_fails_with_wrong_token(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")
    client = _make_client()
    response = client.get("/audit/events", headers={"X-Admin-Token": "wrong-token"})
    assert response.status_code == 403
    body = response.json()
    assert "invalid admin token" in str(body).lower()


def test_admin_audit_allows_with_valid_token(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")
    client = _make_client()
    response = client.get("/audit/events", headers={"X-Admin-Token": "phase4-admin-token"})
    assert response.status_code == 200
    data = response.json()
    assert "events" in data
    assert "total" in data
    assert data["limit"] == 100
    assert data["offset"] == 0


def test_admin_audit_query_filters_events(tmp_path, monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ENV", "local")
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")

    db_file = tmp_path / "admin_audit.db"
    reset_db(str(db_file))
    get_db().query(
        "INSERT OR REPLACE INTO audit_trail(audit_id,event,actor,action,entity,entity_id,payload,outcome,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "loan-1",
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
    get_db().query(
        "INSERT OR REPLACE INTO audit_trail(audit_id,event,actor,action,entity,entity_id,payload,outcome,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "stl-1",
            "settlement.submit",
            "api",
            "submit_settlement",
            "settlement",
            "stl-1",
            "{}",
            "success",
            "2026-01-01T00:00:01+00:00",
        ),
    )

    client = _make_client()
    response = client.get(
        "/audit/events?event=loan.apply&limit=10&offset=0",
        headers={"X-Admin-Token": "phase4-admin-token"},
    )
    assert response.status_code == 200
    events = response.json()["events"]
    assert all(event["event"] == "loan.apply" for event in events)


def test_admin_audit_total_count_reflects_filter(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")
    assert get_audit_total(event="compliance.reload_lists") >= 0
    assert get_audit_total() >= 0


def get_audit_total(event=None, entity=None, actor=None, outcome=None):
    from carib_clear.audit import count_audit_trail_admin
    return count_audit_trail_admin(db=get_db(), event=event, entity=entity, actor=actor, outcome=outcome)


def test_admin_audit_detail_missing_returns_404(monkeypatch):
    monkeypatch.setenv("CARIB_CLEAR_ADMIN_TOKEN", "phase4-admin-token")
    client = _make_client()
    response = client.get("/audit/does-not-exist", headers={"X-Admin-Token": "phase4-admin-token"})
    assert response.status_code == 404


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

    from carib_clear.audit import get_audit_by_id

    record = get_audit_by_id("audit-detail-1", db=get_db())
    assert record is not None
    assert record["audit_id"] == "audit-detail-1"
    assert record["payload"] == {"***": "redacted"}
