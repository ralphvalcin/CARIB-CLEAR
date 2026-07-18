"""Tests for settlement worker AML/PEP screening hook."""

from __future__ import annotations

import os
import tempfile
import uuid

from carib_clear.worker.settlement_worker import SettlementWorker


def test_worker_runs_once_and_reports_metrics():
    with tempfile.TemporaryDirectory() as dir_name:
        db_path = os.path.join(dir_name, "approvals.db")
        worker = _worker(db_path=db_path)
        metrics = worker.run_once()
        assert metrics["worker_id"] == worker.worker_id
        assert metrics["claimed"] is None or isinstance(metrics["claimed"], str)


def test_worker_executes_approved_screening_payload():
    with tempfile.TemporaryDirectory() as dir_name:
        db_path = os.path.join(dir_name, "approvals.db")
        worker = _worker(db_path=db_path)
        approval_id = worker.queue.enqueue(
            session_id=f"session-{uuid.uuid4().hex[:8]}",
            action="fx_settlement",
            payload={
                "from_participant": "clean sender",
                "to_participant": "clean receiver",
                "amount_usd": 1000,
                "currency": "BBD",
                "from_jurisdiction": "BB",
                "to_jurisdiction": "JM",
                "purpose": "trade",
            },
            reason="Clean settlement",
            priority=1,
        ).approval_id

        metrics = worker.run_once(approval_id=approval_id)

        assert metrics["claimed"] == approval_id
        assert metrics["decision"] == "executed"
        assert metrics["screened"]["passed"] is True
        approval = worker.queue.get(approval_id)
        assert approval is not None and approval.status == "executed"


def test_worker_blocks_hard_compliance_failure():
    with tempfile.TemporaryDirectory() as dir_name:
        db_path = os.path.join(dir_name, "approvals.db")
        worker = _worker(db_path=db_path)
        approval_id = worker.queue.enqueue(
            session_id=f"session-{uuid.uuid4().hex[:8]}",
            action="fx_settlement",
            payload={
                "from_participant": "specially designated national entity",
                "to_participant": "clean receiver",
                "amount_usd": 1000,
                "currency": "BBD",
                "from_jurisdiction": "BB",
                "to_jurisdiction": "JM",
                "purpose": "trade",
            },
            reason="Sanctions screening",
            priority=2,
        ).approval_id

        metrics = worker.run_once(approval_id=approval_id)

        assert metrics["claimed"] == approval_id
        assert metrics["decision"] in {"failed", "pending"}
        assert metrics["screened"]["passed"] is False
        assert "sanctions_match" in metrics["screened"]["issues"]
        approval = worker.queue.get(approval_id)
        assert approval is not None and approval.status in {"pending", "failed"}


def _worker(db_path: str) -> SettlementWorker:
    return SettlementWorker(db_path=db_path, lease_seconds=60, max_retries=2)
