"""Settlement worker — claims queued approval items and screens before execution."""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

from carib_clear.audit import audit as _worker_audit
from carib_clear.compliance.screening import ComplianceScreeningEngine
from carib_clear.governance.approval import SqliteApprovalQueue, PendingAction

logger = logging.getLogger(__name__)

_DEFAULT_QUEUE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "settlement_approvals.db"
)


class SettlementWorker:
    """Lease-based worker for settlement approvals with AML/PEP gating."""

    def __init__(
        self,
        worker_id: Optional[str] = None,
        db_path: str = _DEFAULT_QUEUE_PATH,
        compliance_lists: Optional[str] = None,
        lease_seconds: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.queue = SqliteApprovalQueue(db_path=db_path)
        self.lists_path = compliance_lists or os.getenv("CARIB_CLEAR_COMPLIANCE_LISTS")
        self.lease_seconds = lease_seconds
        self.max_retries = max_retries
        self.engine = ComplianceScreeningEngine(lists_path=self.lists_path)
        self.engine.initialize()

    def _validate_participant_state(self, payload: Dict[str, Any]) -> Optional[str]:
        """Verify participant identity/KYC via Database helper.

        Returns None when valid, or an error message string if blocked.
        """
        try:
            from carib_clear.db import Database, get_db
        except Exception:
            return None

        identifiers = [
            str(payload.get("from_participant") or ""),
            str(payload.get("to_participant") or ""),
        ]
        db = get_db() if hasattr(get_db, "__call__") else (Database() if callable(get_db) else None)
        try:
            db = get_db()
        except Exception:
            return None

        bad_statuses = {"denied", "blocked", "suspended", "failed"}
        for participant_id in identifiers:
            if not participant_id:
                continue
            row = db.query_one(
                "SELECT status FROM participants WHERE participant_id = ?",
                (participant_id,),
            )
            status = (row.get("status") if row else None) or ""
            if status.lower() in bad_statuses:
                return (
                    f"Participant '{participant_id}' state '{status}' blocks settlement execution"
                )
        return None

    def _emit_audit(self, *, event: str, approval_id: str, outcome: str, detail: Dict[str, Any]) -> None:
        try:
            _worker_audit(
                event=event,
                actor=self.worker_id,
                action="worker_approval_event",
                entity="approval",
                entity_id=approval_id,
                payload=detail,
                outcome=outcome,
            )
        except Exception as audit_exc:
            logger.debug("Worker audit emission failed: %s", audit_exc)

    def run_once(self, approval_id: Optional[str] = None) -> Dict[str, Any]:
        """Run a single worker cycle and return execution metrics."""
        metrics: Dict[str, Any] = {
            "worker_id": self.worker_id,
            "claimed": None,
            "screened": None,
            "decision": None,
            "error": None,
        }

        self.queue.reclaim_stale_claims(lease_seconds=self.lease_seconds)

        if approval_id:
            approval = self.queue.get(approval_id)
            if approval and approval.status in {"pending", "approved"}:
                claimed = self.queue.claim_for_execution(approval_id, self.worker_id, lease_seconds=self.lease_seconds)
            else:
                claimed = None
        else:
            pending = self.queue.list(status="pending", limit=1)
            if not pending:
                return metrics
            item = pending[0]
            claimed = self.queue.claim_for_execution(
                item["approval_id"], self.worker_id, lease_seconds=self.lease_seconds
            )

        if not claimed:
            return metrics

        metrics["claimed"] = claimed.approval_id
        payload = claimed.payload or {}

        try:
            screen = self.engine.screen_transaction(
                transaction_id=f"worker-{uuid.uuid4().hex[:10]}",
                from_participant=str(payload.get("from_participant") or ""),
                to_participant=str(payload.get("to_participant") or ""),
                amount_usd=float(payload.get("amount_usd") or 0),
                currency=str(payload.get("currency") or "USD"),
                from_jurisdiction=str(payload.get("from_jurisdiction") or ""),
                to_jurisdiction=str(payload.get("to_jurisdiction") or ""),
                purpose=str(payload.get("purpose") or "trade"),
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Screening failed for %s", claimed.approval_id)
            failed = self.queue.mark_failed(claimed.approval_id, self.worker_id, str(exc), max_retries=self.max_retries)
            metrics["screened"] = False
            metrics["decision"] = failed.status if failed else "failed"
            metrics["error"] = str(exc)
            return metrics

        issues = screen.get("issues", []) or []
        metrics["screened"] = {
            "passed": bool(screen.get("passed")),
            "requires_review": bool(screen.get("requires_review")),
            "issues": issues,
        }

        if any(issue not in {"pep_involved", "aml_reporting_threshold_exceeded"} for issue in issues):
            error_msg = f"Compliance screening failed: {', '.join(sorted(set(issues)))}"
            failed = self.queue.mark_failed(claimed.approval_id, self.worker_id, error_msg, max_retries=self.max_retries)
            metrics["decision"] = failed.status if failed else "failed"
            metrics["error"] = error_msg
            self._emit_audit(
                event="worker.aml.blocked",
                approval_id=claimed.approval_id,
                outcome="blocked",
                detail={"issues": issues, "error": error_msg},
            )
            return metrics

        kyc_blocker = self._validate_participant_state(payload)
        if kyc_blocker:
            error_msg = f"KYC guard blocked execution: {kyc_blocker}"
            failed = self.queue.mark_failed(claimed.approval_id, self.worker_id, error_msg, max_retries=self.max_retries)
            metrics["decision"] = failed.status if failed else "failed"
            metrics["error"] = error_msg
            self._emit_audit(
                event="worker.kyc.blocked",
                approval_id=claimed.approval_id,
                outcome="blocked",
                detail={"reason": kyc_blocker},
            )
            return metrics

        executed = self.queue.mark_executed(
            approval_id=claimed.approval_id,
            result={
                "status": "executed",
                "input": payload,
                "compliance": metrics["screened"],
            },
            worker_id=self.worker_id,
        )
        metrics["decision"] = executed.status if executed else "executed"
        return metrics

    def drain(self, cycles: int = 5, sleep_seconds: float = 0.1) -> Dict[str, Any]:
        """Run multiple cycles and return aggregate metrics."""
        summary: Dict[str, Any] = {"cycles": 0, "executed": 0, "blocked": 0, "errors": []}
        for _ in range(max(1, cycles)):
            result = self.run_once()
            summary["cycles"] += 1
            decision = result.get("decision")
            if decision == "executed":
                summary["executed"] += 1
            elif decision in {"pending", "failed", "denied"}:
                summary["blocked"] += 1
            if result.get("error"):
                summary["errors"].append(result["error"])
            time.sleep(max(0.0, sleep_seconds))
        return summary
