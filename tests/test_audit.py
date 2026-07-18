"""Audit trail regression tests."""

from __future__ import annotations

import os
import tempfile

from carib_clear.audit import audit, list_audits
from carib_clear.db import reset_db


def _db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name
    return reset_db(path), path


def test_audit_appends_and_lists():
    db, path = _db()
    try:
        audit(
            event="loan.apply",
            actor="api",
            action="apply_for_loan",
            entity="loan_application",
            entity_id="loan-1",
            payload={"approved": True},
            outcome="success",
            db=db,
        )
        audit(
            event="loan.apply",
            actor="api",
            action="apply_for_loan",
            entity="loan_application",
            entity_id="loan-2",
            payload={"approved": False},
            outcome="declined",
            db=db,
        )
        rows = list_audits(db=db, limit=10, event="loan.apply")
        assert len(rows) >= 2
        entities = [row["entity_id"] for row in rows]
        assert "loan-1" in entities
        assert "loan-2" in entities
    finally:
        os.remove(path)


def test_audit_filter_by_event_and_entity():
    db, path = _db()
    try:
        audit(
            event="settlement.submit",
            actor="api",
            action="submit_settlement",
            entity="settlement",
            entity_id="stl-1",
            payload={},
            outcome="success",
            db=db,
        )
        audit(
            event="participant.onboard",
            actor="api",
            action="onboard_participant",
            entity="participant",
            entity_id="pt-1",
            payload={},
            outcome="success",
            db=db,
        )
        settlements = list_audits(db=db, event="settlement.submit")
        participants = list_audits(db=db, entity="participant")
        assert any(row["entity_id"] == "stl-1" for row in settlements)
        assert any(row["entity_id"] == "pt-1" for row in participants)
    finally:
        os.remove(path)


def test_audit_write_failed_is_returned_and_logged(monkeypatch):
    db, path = _db()
    try:
        def _raise_disk_full(**kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(db, "insert_audit_trail", _raise_disk_full)
        attempt = audit(
            event="compliance.reload_lists",
            actor="operator",
            action="reload_compliance_lists",
            entity="compliance_lists",
            entity_id="list-1",
            payload={"path": "/compliance/lists.yml"},
            outcome="success",
            db=db,
        )
        assert attempt.get("audit_status") == "write_failed"
        assert attempt.get("outcome") == "success"
    finally:
        os.remove(path)
