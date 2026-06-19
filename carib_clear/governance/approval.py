# governance/approval.py
"""
CARIB-CLEAR Approval Queue

Extracted from JARVIS jarvis/runtime/approval_queue.py
Durable SQLite-backed approval queue with lease-based worker claiming,
idempotency, and automatic stale-claim reclamation.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Literal, Optional
import json
import sqlite3
import threading
import time
import uuid

ApprovalStatus = Literal["pending", "approved", "denied", "executed", "failed", "expired"]


@dataclass
class PendingAction:
    approval_id: str
    session_id: str
    action: str
    payload: Dict[str, Any]
    reason: str
    status: ApprovalStatus
    created_at: float
    updated_at: float
    result: Optional[Dict[str, Any]] = None
    claimed_by: Optional[str] = None
    claimed_at: Optional[float] = None
    lease_until: Optional[float] = None
    retry_count: int = 0
    last_error: Optional[str] = None
    priority: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SqliteApprovalQueue:
    """Durable approval queue backed by SQLite with worker leases."""

    def __init__(self, db_path: str = "./data/approvals.db") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_column(self, conn: sqlite3.Connection, name: str, ddl: str) -> None:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(approvals)").fetchall()}
        if name not in cols:
            conn.execute(ddl)

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    claimed_by TEXT,
                    claimed_at REAL,
                    lease_until REAL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    priority INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._ensure_column(conn, "claimed_by", "ALTER TABLE approvals ADD COLUMN claimed_by TEXT")
            self._ensure_column(conn, "claimed_at", "ALTER TABLE approvals ADD COLUMN claimed_at REAL")
            self._ensure_column(conn, "lease_until", "ALTER TABLE approvals ADD COLUMN lease_until REAL")
            self._ensure_column(conn, "retry_count", "ALTER TABLE approvals ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "last_error", "ALTER TABLE approvals ADD COLUMN last_error TEXT")
            self._ensure_column(conn, "priority", "ALTER TABLE approvals ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_approvals_status_created ON approvals(status, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_approvals_status_lease ON approvals(status, lease_until)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_approvals_session ON approvals(session_id)"
            )
            conn.commit()

    def _row_to_item(self, row: sqlite3.Row) -> PendingAction:
        return PendingAction(
            approval_id=row["approval_id"],
            session_id=row["session_id"],
            action=row["action"],
            payload=json.loads(row["payload_json"]),
            reason=row["reason"],
            status=row["status"],  # type: ignore[arg-type]
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            claimed_by=row["claimed_by"],
            claimed_at=row["claimed_at"],
            lease_until=row["lease_until"],
            retry_count=row["retry_count"] or 0,
            last_error=row["last_error"],
            priority=row["priority"] or 0,
        )

    def enqueue(
        self,
        session_id: str,
        action: str,
        payload: Dict[str, Any],
        reason: str,
        priority: int = 0
    ) -> PendingAction:
        now = time.time()
        item = PendingAction(
            approval_id=str(uuid.uuid4()),
            session_id=session_id,
            action=action,
            payload=payload,
            reason=reason,
            status="pending",
            created_at=now,
            updated_at=now,
            priority=priority,
        )
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO approvals (
                        approval_id, session_id, action, payload_json, reason, status, result_json,
                        created_at, updated_at, claimed_by, claimed_at, lease_until, retry_count, last_error, priority
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.approval_id,
                        item.session_id,
                        item.action,
                        json.dumps(item.payload, ensure_ascii=False),
                        item.reason,
                        item.status,
                        None,
                        item.created_at,
                        item.updated_at,
                        None,
                        None,
                        None,
                        0,
                        None,
                        item.priority,
                    ),
                )
                conn.commit()
        return item

    def get(self, approval_id: str) -> Optional[PendingAction]:
        with self._lock:
            with self._conn() as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM approvals WHERE approval_id = ?",
                    (approval_id,),
                ).fetchone()
        if not row:
            return None
        return self._row_to_item(row)

    def list(
        self,
        status: Optional[ApprovalStatus] = None,
        session_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM approvals"
        params: list = []
        conditions = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY priority DESC, created_at DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            with self._conn() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_item(r).to_dict() for r in rows]

    def _set_status(self, approval_id: str, status: ApprovalStatus) -> Optional[PendingAction]:
        now = time.time()
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute(
                    """
                    UPDATE approvals
                    SET status = ?, updated_at = ?, lease_until = NULL
                    WHERE approval_id = ?
                    """,
                    (status, now, approval_id),
                )
                conn.commit()
                if cur.rowcount == 0:
                    return None
        return self.get(approval_id)

    def approve(self, approval_id: str) -> Optional[PendingAction]:
        return self._set_status(approval_id, "approved")

    def claim_for_execution(
        self,
        approval_id: str,
        worker_id: str,
        lease_seconds: float = 30.0,
    ) -> Optional[PendingAction]:
        """Atomically claim an approval for execution with worker lease."""
        now = time.time()
        lease_until = now + lease_seconds
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute(
                    """
                    UPDATE approvals
                    SET
                      status = 'approved',
                      updated_at = ?,
                      claimed_by = ?,
                      claimed_at = ?,
                      lease_until = ?,
                      last_error = NULL
                    WHERE approval_id = ?
                      AND (
                        status = 'pending'
                        OR (status = 'approved' AND lease_until IS NOT NULL AND lease_until <= ?)
                      )
                    """,
                    (now, worker_id, now, lease_until, approval_id, now),
                )
                conn.commit()
                if cur.rowcount == 0:
                    return None
        return self.get(approval_id)

    def reclaim_stale_claims(self, lease_seconds: float = 30.0) -> int:
        """Move stale approved claims back to pending for new workers."""
        now = time.time()
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute(
                    """
                    UPDATE approvals
                    SET
                      status = 'pending',
                      updated_at = ?,
                      claimed_by = NULL,
                      claimed_at = NULL,
                      lease_until = NULL
                    WHERE status = 'approved' AND lease_until IS NOT NULL AND lease_until <= ?
                    """,
                    (now, now),
                )
                conn.commit()
                return cur.rowcount

    def deny(self, approval_id: str) -> Optional[PendingAction]:
        return self._set_status(approval_id, "denied")

    def mark_executed(
        self,
        approval_id: str,
        result: Dict[str, Any],
        worker_id: str
    ) -> Optional[PendingAction]:
        now = time.time()
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute(
                    """
                    UPDATE approvals
                    SET status = ?, result_json = ?, updated_at = ?, lease_until = NULL
                    WHERE approval_id = ? AND status = 'approved' AND claimed_by = ?
                    """,
                    ("executed", json.dumps(result, ensure_ascii=False), now, approval_id, worker_id),
                )
                conn.commit()
                if cur.rowcount == 0:
                    return None
        return self.get(approval_id)

    def mark_failed(
        self,
        approval_id: str,
        worker_id: str,
        error: str,
        max_retries: int = 2
    ) -> Optional[PendingAction]:
        now = time.time()
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT retry_count FROM approvals WHERE approval_id = ? AND status = 'approved' AND claimed_by = ?",
                    (approval_id, worker_id),
                ).fetchone()
                if not row:
                    return None
                retry_count = int(row[0] or 0) + 1
                next_status: ApprovalStatus = "pending" if retry_count <= max_retries else "failed"
                conn.execute(
                    """
                    UPDATE approvals
                    SET status = ?, updated_at = ?, retry_count = ?, last_error = ?,
                        claimed_by = NULL, claimed_at = NULL, lease_until = NULL
                    WHERE approval_id = ?
                    """,
                    (next_status, now, retry_count, error, approval_id),
                )
                conn.commit()
        return self.get(approval_id)

    def expire_old_pending(self, max_age_seconds: float = 86400) -> int:
        """Expire pending approvals older than max_age_seconds."""
        cutoff = time.time() - max_age_seconds
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute(
                    """
                    UPDATE approvals
                    SET status = 'expired', updated_at = ?
                    WHERE status = 'pending' AND created_at < ?
                    """,
                    (time.time(), cutoff),
                )
                conn.commit()
                return cur.rowcount

    def metrics(self) -> Dict[str, int]:
        """Count of approvals per status."""
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS cnt FROM approvals GROUP BY status"
                ).fetchall()
        counts: Dict[str, int] = {}
        for r in rows:
            counts[r[0]] = r[1]
        return {
            "pending": counts.get("pending", 0),
            "approved": counts.get("approved", 0),
            "denied": counts.get("denied", 0),
            "executed": counts.get("executed", 0),
            "failed": counts.get("failed", 0),
            "expired": counts.get("expired", 0),
            "total": sum(counts.values()),
        }


# ─── Action Types for CARIB-CLEAR ──────────────────────────────────
ACTION_TYPES = {
    "fx_settlement": "FX Settlement Approval",
    "msme_credit": "MSME Credit Approval",
    "compliance_review": "Compliance Review",
    "liquidity_provision": "Liquidity Pool Provision",
    "rail_selection": "Settlement Rail Selection",
    "kyc_verification": "KYC Verification",
    "aml_screening": "AML Screening",
    "sanctions_check": "Sanctions Check",
}

if __name__ == "__main__":
    # Demo
    queue = SqliteApprovalQueue("./data/test_approvals.db")
    
    # Enqueue a test approval
    item = queue.enqueue(
        session_id="test-session-1",
        action="fx_settlement",
        payload={"from_ccy": "BBD", "to_ccy": "JMD", "amount_usd": 10000},
        reason="Barbados hotel paying Jamaican supplier",
        priority=10,
    )
    print(f"Enqueued: {item.approval_id}")
    
    # Claim for execution
    claimed = queue.claim_for_execution(item.approval_id, "worker-1", lease_seconds=60)
    print(f"Claimed: {claimed.claimed_by}")
    
    # Mark executed
    executed = queue.mark_executed(item.approval_id, {"tx_hash": "0xabc123"}, "worker-1")
    print(f"Executed: {executed.status}")
    
    # Metrics
    print(f"Metrics: {queue.metrics()}")