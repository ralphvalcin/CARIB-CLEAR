"""Persistence layer for CARIB-CLEAR.

Defaults to SQLite for local/test runs. In production, set ``CARIB_CLEAR_DATABASE_URL``
to a PostgreSQL connection string and the app will use Postgres-backed storage
instead of the bundled SQLite file.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default DB path when running locally with SQLite.
DEFAULT_SQLITE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "carib_clear.db")
TEST_DB_OVERRIDE: Optional[str] = None


def _resolve_database_url() -> str:
    env_url = os.getenv("CARIB_CLEAR_DATABASE_URL")
    if env_url:
        return env_url
    if TEST_DB_OVERRIDE is not None:
        return TEST_DB_OVERRIDE
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


def _production_db_url() -> Optional[str]:
    candidate = os.getenv("CARIB_CLEAR_DATABASE_URL", "").strip()
    if not candidate:
        return None
    return candidate


def _connection_from_url(database_url: str):
    if database_url.startswith("sqlite:///"):
        db_path = database_url[len("sqlite:///"):]
        if os.getenv("CARIB_CLEAR_ENV", "local").lower() not in {"local", "demo", "test"}:
            raise RuntimeError(
                "SQLite is not allowed with CARIB_CLEAR_ENV=production; set CARIB_CLEAR_DATABASE_URL to PostgreSQL"
            )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn, db_path

    if database_url.startswith("postgresql://") or database_url.startswith("postgres://"):
        try:
            import psycopg  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "CARIB_CLEAR_DATABASE_URL requires psycopg/psycopg2 for PostgreSQL"
            ) from exc

        conn = psycopg.connect(database_url)
        conn.autocommit = False
        return conn, database_url

    raise ValueError(f"Unsupported CARIB_CLEAR_DATABASE_URL scheme: {database_url}")

# Schema SQL
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS participants (
    participant_id TEXT PRIMARY KEY,
    type TEXT NOT NULL DEFAULT 'msme',
    name TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS participant_api_keys (
    key_id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    prefix TEXT NOT NULL,
    secret_hash TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT,
    FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
);
CREATE INDEX IF NOT EXISTS idx_participant_api_keys_participant ON participant_api_keys(participant_id);
CREATE INDEX IF NOT EXISTS idx_participant_api_keys_prefix ON participant_api_keys(prefix);

CREATE TABLE IF NOT EXISTS webhooks (
    webhook_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    events TEXT NOT NULL,  -- JSON array
    participant_id TEXT NOT NULL,
    secret TEXT NOT NULL,
    description TEXT DEFAULT '',
    retry_count INTEGER DEFAULT 3,
    timeout_seconds INTEGER DEFAULT 10,
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
);
CREATE INDEX IF NOT EXISTS idx_webhooks_participant ON webhooks(participant_id);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    delivery_id TEXT PRIMARY KEY,
    webhook_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,  -- success, failed, pending
    status_code INTEGER DEFAULT 0,
    error_message TEXT DEFAULT '',
    attempt_number INTEGER DEFAULT 1,
    duration_ms REAL DEFAULT 0.0,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (webhook_id) REFERENCES webhooks(webhook_id)
);
CREATE INDEX IF NOT EXISTS idx_deliveries_webhook ON delivery_attempts(webhook_id);

CREATE TABLE IF NOT EXISTS webhook_delivery_queue (
    delivery_id TEXT PRIMARY KEY,
    webhook_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    attempt_number INTEGER DEFAULT 1,
    error_message TEXT DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('queued','processing','done','failed')),
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_webhook_queue_webhook ON webhook_delivery_queue(webhook_id);

CREATE TABLE IF NOT EXISTS loan_applications (
    application_id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    business_name TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    jurisdiction TEXT NOT NULL,
    approved INTEGER DEFAULT 0,
    lender TEXT,
    interest_rate_pct REAL,
    sector TEXT,
    purpose TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
);
CREATE INDEX IF NOT EXISTS idx_loans_participant ON loan_applications(participant_id);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settlements (
    settlement_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    business_key TEXT NOT NULL,
    participant_id TEXT NOT NULL DEFAULT '',
    rail TEXT NOT NULL,
    order_id TEXT NOT NULL,
    status TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    currency_from TEXT NOT NULL,
    currency_to TEXT NOT NULL,
    amount_from REAL NOT NULL,
    amount_to REAL NOT NULL,
    rate REAL NOT NULL,
    fees_usd REAL NOT NULL DEFAULT 0,
    tx_hash TEXT,
    error_message TEXT DEFAULT '',
    raw_response TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_settlements_scope_business ON settlements(scope, business_key);
CREATE INDEX IF NOT EXISTS idx_settlements_order ON settlements(order_id);
CREATE INDEX IF NOT EXISTS idx_settlements_status ON settlements(status);

CREATE TABLE IF NOT EXISTS settlement_events (
    event_id TEXT PRIMARY KEY,
    settlement_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    source TEXT,
    confirmed_at TEXT NOT NULL,
    FOREIGN KEY (settlement_id) REFERENCES settlements(settlement_id)
);
CREATE INDEX IF NOT EXISTS idx_settlement_events_settlement ON settlement_events(settlement_id);

CREATE TABLE IF NOT EXISTS compliance_checks (
    check_id TEXT PRIMARY KEY,
    participant_id TEXT,
    check_type TEXT NOT NULL,
    passed INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0,
    details TEXT NOT NULL DEFAULT '{}',
    requires_review INTEGER NOT NULL DEFAULT 0,
    reviewer_notes TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aml_pep_hits (
    hit_id TEXT PRIMARY KEY,
    participant_id TEXT,
    check_id TEXT NOT NULL,
    issue TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_queues (
    queue_id TEXT PRIMARY KEY,
    check_id TEXT NOT NULL,
    participant_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer_id TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_trail (
    audit_id TEXT PRIMARY KEY,
    event TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    outcome TEXT NOT NULL DEFAULT 'success',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_trail_event_created ON audit_trail(event, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_trail_entity ON audit_trail(entity, entity_id);
"""


class Database:
    """SQLite database with thread-safe access.

    Usage:
        db = Database()
        db.init_schema()
        db.insert("webhooks", {"webhook_id": "wh_001", ...})
        rows = db.query("SELECT * FROM webhooks WHERE participant_id = ?", ("bb_hotel",))
    """

    def __init__(self, db_path: str = DEFAULT_SQLITE_PATH):
        self._local = threading.local()
        self.database_url = self._coerce_db_url(db_path)
        self.db_path = self._sqlite_path_for(self.database_url)
        url = self.database_url
        if url.startswith("postgres://") or url.startswith("postgresql://"):
            url = "postgres://<redacted>"
        logger.info("[DB] database_url=%s", url)

    @staticmethod
    def _coerce_db_url(db_path: str) -> str:
        override = os.getenv("CARIB_CLEAR_DATABASE_URL")
        if override:
            return override
        if not db_path or db_path == ":memory:":
            return "sqlite://"
        if db_path.startswith("sqlite:///"):
            return db_path
        return f"sqlite:///{db_path}"

    @staticmethod
    def _sqlite_path_for(database_url: str) -> str:
        if database_url == "sqlite://":
            return ":memory:"
        if database_url.startswith("sqlite:///"):
            return database_url[len("sqlite:///"):]
        return ""

    @property
    def _conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if self.database_url.startswith("sqlite://") and os.getenv("CARIB_CLEAR_ENV", "local").lower() not in {"local", "demo", "test"}:
            raise RuntimeError(
                "SQLite is not allowed with CARIB_CLEAR_ENV=production; set CARIB_CLEAR_DATABASE_URL to PostgreSQL"
            )
        if not hasattr(self._local, "conn") or self._local.conn is None:
            db_path = self.db_path or DEFAULT_SQLITE_PATH
            self._local.conn = sqlite3.connect(db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def init_schema(self) -> None:
        """Create tables if they don't exist, then apply bundled migrations."""
        try:
            self._conn.executescript(SCHEMA_SQL)
        except Exception as exc:
            logger.debug("[DB] Schema bootstrap note: %s", exc)
        try:
            self._migrate_add_column("settlements", "participant_id")
        except Exception as exc:
            logger.debug("[DB] Migration note: %s", exc)
        try:
            self._conn.executescript("PRAGMA user_version=1;")
        except Exception:
            pass
        try:
            self._conn.commit()
        except Exception as exc:
            logger.debug("[DB] Schema commit note: %s", exc)
        logger.info("[DB] Schema initialized")

    def _migrate_add_column(self, table: str, column: str) -> None:
        try:
            rows = self._conn.execute(
                f"PRAGMA table_info({self._quote_identifier(table)})"
            ).fetchall()
            cols = {row["name"] for row in rows}
            if column not in cols:
                sql = (
                    f"ALTER TABLE {self._quote_identifier(table)} "
                    f"ADD COLUMN {self._quote_identifier(column)} TEXT NOT NULL DEFAULT ''"
                )
                self._conn.execute(sql)
                logger.info("[DB] Added missing column %s on %s", column, table)
        except Exception:
            logger.debug("[DB] Migration skipped for %s.%s", table, column)

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        if not identifier or identifier.strip() != identifier or "'" in identifier:
            raise ValueError("Invalid SQL identifier")
        return '"' + identifier.replace('"', '""') + '"'

    def _build_param_sql(self, table: str, columns: Dict[str, Any]) -> tuple[str, tuple]:
        if table not in self._TABLES or not columns:
            raise ValueError("Invalid target/columns for insert")
        sql_columns = ", ".join(self._quote_identifier(name) for name in columns)
        placeholders = ", ".join("?" for _ in columns)
        return sql_columns, tuple(columns.values())

    def insert(self, table: str, data: Dict[str, Any]) -> bool:
        """Insert a row into a table.

        Args:
            table: Table name.
            data: Dict of column_name -> value.

        Returns:
            True on success.
        """
        if not data:
            return False
        if table not in self._TABLES:
            return False
        cols, values = self._build_param_sql(table, data)
        placeholders = ", ".join("?" for _ in data)
        sql = f"INSERT OR REPLACE INTO {self._quote_identifier(table)} ({cols}) VALUES ({placeholders})"
        try:
            self._conn.execute(sql, list(values))
            self._conn.commit()
            return True
        except Exception as e:
            logger.error("[DB] Insert failed: %s", e)
            return False

    def query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return rows as dicts."""
        try:
            cursor = self._conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("[DB] Query failed: %s — %s", sql, e)
            return []

    def query_one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Execute a SELECT query and return the first row (or None)."""
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple = ()) -> bool:
        """Execute a write query (INSERT, UPDATE, DELETE)."""
        if "audit_trail" in sql.lower() and not sql.strip().lower().startswith("insert"):
            raise ValueError("audit_trail is append-only and cannot be mutated")
        try:
            self._conn.execute(sql, params)
            self._conn.commit()
            return True
        except Exception as e:
            logger.error("[DB] Execute failed: %s — %s", sql, e)
            return False

    _TABLES = {
        "participants",
        "participant_api_keys",
        "config",
        "loan_applications",
        "compliance_checks",
        "aml_pep_hits",
        "review_queues",
        "audit_trail",
        "webhooks",
        "delivery_attempts",
        "webhook_delivery_queue",
        "settlements",
        "settlement_events",
    }

    def delete(self, table: str, where: Iterable[str], params: tuple = ()) -> bool:
        """Delete rows from an allow-listed, quoted table.

        Args:
            table: Table name.
            where: Raw WHERE fragments without parameter placeholders.
            params: Bind parameters for those fragments in declaration order.

        Returns:
            True on success.
        """
        if table == "audit_trail":
            raise ValueError("audit_trail is append-only and cannot be mutated")
        if table not in self._TABLES:
            raise ValueError(f"Table not allowed: {table}")
        query = f"DELETE FROM {self._quote_identifier(table)} WHERE {' AND '.join(where)}"
        return self.execute(query, tuple(params))

    def count(self, table: str, where: Iterable[str] = ("1=1",), params: tuple = ()) -> int:
        """Count rows in an allow-listed, quoted table."""
        if table not in self._TABLES:
            raise ValueError(f"Table not allowed: {table}")
        query = f"SELECT COUNT(*) as cnt FROM {self._quote_identifier(table)} WHERE {' AND '.join(where)}"
        row = self.query_one(query, params)
        return row["cnt"] if row else 0

    def close(self) -> None:
        """Close the connection for this thread."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # ── Config key-value store ──────────────────────────────────────────

    def get_config(self, key: str, default: Any = None) -> Optional[str]:
        """Get a config value by key."""
        row = self.query_one("SELECT value FROM config WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_config(self, key: str, value: str) -> bool:
        """Set a config value."""
        from datetime import datetime, timezone
        return self.insert("config", {
            "key": key,
            "value": value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    # ── Participant identity ─────────────────────────────────────────

    def create_participant(self, participant_id: str, name: str, jurisdiction: str,
                           participant_type: str = "msme", metadata: Optional[dict] = None) -> bool:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        return self.insert("participants", {
            "participant_id": participant_id,
            "type": participant_type,
            "name": name,
            "jurisdiction": jurisdiction,
            "status": "pending",
            "metadata": json.dumps(metadata or {}),
            "created_at": now,
            "updated_at": now,
        })

    def update_participant_status(self, participant_id: str, status: str) -> bool:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        return self.execute(
            "UPDATE participants SET status = ?, updated_at = ? WHERE participant_id = ?",
            (status, now, participant_id),
        )

    def get_participant(self, participant_id: str) -> Optional[Dict[str, Any]]:
        row = self.query_one("SELECT * FROM participants WHERE participant_id = ?", (participant_id,))
        if not row:
            return None
        row["metadata"] = json.loads(row.get("metadata") or "{}")
        return row

    def list_participants(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self.query("SELECT * FROM participants ORDER BY created_at DESC LIMIT ?", (limit,))
        for row in rows:
            row["metadata"] = json.loads(row.get("metadata") or "{}")
        return rows

    def create_api_key(self, key_id: str, participant_id: str, prefix: str,
                       secret_hash: str, name: str = "") -> bool:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        return self.insert("participant_api_keys", {
            "key_id": key_id,
            "participant_id": participant_id,
            "prefix": prefix,
            "secret_hash": secret_hash,
            "name": name,
            "active": 1,
            "created_at": now,
        })

    def get_active_api_key_by_prefix(self, prefix: str) -> Optional[Dict[str, Any]]:
        return self.query_one(
            "SELECT * FROM participant_api_keys WHERE prefix = ? AND active = 1 AND revoked_at IS NULL",
            (prefix,),
        )

    # ── Settlement ledger ──────────────────────────────────────────

    def create_settlement(self, settlement_id: str, scope: str, business_key: str, data: Dict[str, Any], participant_id: Optional[str] = None) -> bool:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        return self.insert("settlements", {
            "settlement_id": settlement_id,
            "scope": scope,
            "business_key": business_key,
            "rail": data["rail"],
            "order_id": data["order_id"],
            "status": data.get("status", "pending"),
            "amount_usd": float(data.get("amount_usd", 0) or 0),
            "currency_from": data.get("currency_from", ""),
            "currency_to": data.get("currency_to", ""),
            "amount_from": float(data.get("amount_from", 0) or 0),
            "amount_to": float(data.get("amount_to", 0) or 0),
            "rate": float(data.get("rate", 0) or 0),
            "fees_usd": float(data.get("fees_usd", 0) or 0),
            "tx_hash": data.get("tx_hash"),
            "error_message": data.get("error_message", ""),
            "raw_response": json.dumps(data.get("raw_response") or {}),
            "participant_id": participant_id,
            "created_at": now,
            "updated_at": now,
        })

    def get_settlement(self, settlement_id: str) -> Optional[Dict[str, Any]]:
        row = self.query_one("SELECT * FROM settlements WHERE settlement_id = ?", (settlement_id,))
        if row:
            row["raw_response"] = json.loads(row.get("raw_response") or "{}")
        return row

    def get_settlement_by_order(self, rail: str, order_id: str, status: Optional[str] = None) -> Optional[Dict[str, Any]]:
        where = ["rail = ?", "order_id = ?"]
        params: list = [rail, order_id]
        if status:
            where.append("status = ?")
            params.append(status)
        sql = f"SELECT * FROM settlements WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT 1"
        row = self.query_one(sql, tuple(params))
        if row:
            row["raw_response"] = json.loads(row.get("raw_response") or "{}")
        return row

    def update_settlement_status(self, settlement_id: str, status: str, tx_hash: Optional[str] = None, error_message: str = "", raw_response: Optional[Dict[str, Any]] = None) -> bool:
        from datetime import datetime, timezone
        sets = ["status = ?", "updated_at = ?"]
        params: list = [status, datetime.now(timezone.utc).isoformat()]
        if tx_hash:
            sets.append("tx_hash = ?")
            params.append(tx_hash)
        if error_message:
            sets.append("error_message = ?")
            params.append(error_message)
        if raw_response is not None:
            sets.append("raw_response = ?")
            params.append(json.dumps(raw_response))
        params.append(settlement_id)
        sql = f"UPDATE settlements SET {', '.join(sets)} WHERE settlement_id = ?"
        return self.execute(sql, tuple(params))

    def list_settlements(self, participant_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        where = ["1=1"]
        params: list = []
        if participant_id:
            where.append("participant_id = ?")
            params.append(participant_id)
        if status:
            where.append("status = ?")
            params.append(status)
        params.append(max(limit, 1))
        sql = f"SELECT * FROM settlements WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?"
        rows = self.query(sql, tuple(params))
        for row in rows:
            row["raw_response"] = json.loads(row.get("raw_response") or "{}")
        return rows

    def add_settlement_event(self, event_id: str, settlement_id: str, event_type: str, payload: Dict[str, Any], source: Optional[str], confirmed_at: str) -> bool:
        return self.insert("settlement_events", {
            "event_id": event_id,
            "settlement_id": settlement_id,
            "event_type": event_type,
            "payload": json.dumps(payload or {}),
            "source": source,
            "confirmed_at": confirmed_at,
        })

    def get_settlement_events(self, settlement_id: str) -> List[Dict[str, Any]]:
        rows = self.query("SELECT * FROM settlement_events WHERE settlement_id = ? ORDER BY confirmed_at ASC", (settlement_id,))
        for row in rows:
            row["payload"] = json.loads(row.get("payload") or "{}")
        return rows

    # ── Compliance ledger ──────────────────────────────────────────

    def insert_compliance_check(self, check_id: str, participant_id: Optional[str], check_type: str, passed: bool, score: float, details: Dict[str, Any], requires_review: bool = False, reviewer_notes: str = "") -> bool:
        from datetime import datetime, timezone
        return self.insert("compliance_checks", {
            "check_id": check_id,
            "participant_id": participant_id,
            "check_type": check_type,
            "passed": 1 if passed else 0,
            "score": float(score),
            "details": json.dumps(details or {}),
            "requires_review": 1 if requires_review else 0,
            "reviewer_notes": reviewer_notes,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_compliance_check(self, check_id: str) -> Optional[Dict[str, Any]]:
        row = self.query_one("SELECT * FROM compliance_checks WHERE check_id = ?", (check_id,))
        if row:
            row["details"] = json.loads(row.get("details") or "{}")
        return row

    def list_compliance_checks(self, participant_id: Optional[str] = None, check_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        where = ["1=1"]
        params: list = []
        if participant_id:
            where.append("participant_id = ?")
            params.append(participant_id)
        if check_type:
            where.append("check_type = ?")
            params.append(check_type)
        params.append(max(limit, 1))
        rows = self.query(f"SELECT * FROM compliance_checks WHERE {' AND '.join(where)} ORDER BY timestamp DESC LIMIT ?", tuple(params))
        for row in rows:
            row["details"] = json.loads(row.get("details") or "{}")
        return rows

    def insert_aml_pep_hit(self, hit_id: str, participant_id: Optional[str], check_id: str, issue: str, payload: Dict[str, Any]) -> bool:
        from datetime import datetime, timezone
        return self.insert("aml_pep_hits", {
            "hit_id": hit_id,
            "participant_id": participant_id,
            "check_id": check_id,
            "issue": issue,
            "payload": json.dumps(payload or {}),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    def get_aml_pep_hits(self, participant_id: Optional[str] = None, check_id: Optional[str] = None) -> List[Dict[str, Any]]:
        where = ["1=1"]
        params: list = []
        if participant_id:
            where.append("participant_id = ?")
            params.append(participant_id)
        if check_id:
            where.append("check_id = ?")
            params.append(check_id)
        sql = f"SELECT * FROM aml_pep_hits WHERE {' AND '.join(where)} ORDER BY created_at DESC"
        rows = self.query(sql, tuple(params))
        for row in rows:
            row["payload"] = json.loads(row.get("payload") or "{}")
        return rows

    def insert_review_queue_item(self, queue_id: str, check_id: str, participant_id: Optional[str], status: str = "pending", reviewer_id: Optional[str] = None, reason: Optional[str] = None) -> bool:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        return self.insert("review_queues", {
            "queue_id": queue_id,
            "check_id": check_id,
            "participant_id": participant_id,
            "status": status,
            "reviewer_id": reviewer_id,
            "reason": reason,
            "created_at": now,
            "updated_at": now,
        })

    def update_review_queue_item(self, queue_id: str, status: str, reviewer_id: Optional[str] = None, reason: Optional[str] = None) -> bool:
        from datetime import datetime, timezone
        sets = ["status = ?", "updated_at = ?"]
        params: list = [status, datetime.now(timezone.utc).isoformat()]
        if reviewer_id is not None:
            sets.append("reviewer_id = ?")
            params.append(reviewer_id)
        if reason is not None:
            sets.append("reason = ?")
            params.append(reason)
        params.append(queue_id)
        sql = f"UPDATE review_queues SET {', '.join(sets)} WHERE queue_id = ?"
        return self.execute(sql, tuple(params))

    def get_review_queue_items(self, status: Optional[str] = None, participant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        where = ["1=1"]
        params: list = []
        if status:
            where.append("status = ?")
            params.append(status)
        if participant_id:
            where.append("participant_id = ?")
            params.append(participant_id)
        sql = f"SELECT * FROM review_queues WHERE {' AND '.join(where)} ORDER BY created_at DESC"
        return self.query(sql, tuple(params))

    def insert_audit_trail(self, audit_id: str, event: str, actor: str, action: str, entity: str, entity_id: str, payload: Dict[str, Any], outcome: str = "success") -> bool:
        from datetime import datetime, timezone
        return self.insert("audit_trail", {
            "audit_id": audit_id,
            "event": event,
            "actor": actor,
            "action": action,
            "entity": entity,
            "entity_id": entity_id,
            "payload": json.dumps(payload or {}),
            "outcome": outcome,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    def list_audit_trail(self, limit: int = 100, event: Optional[str] = None, entity: Optional[str] = None) -> List[Dict[str, Any]]:
        where = ["1=1"]
        params: list = []
        if event:
            where.append("event = ?")
            params.append(event)
        if entity:
            where.append("entity = ?")
            params.append(entity)
        params.append(max(limit, 1))
        rows = self.query(f"SELECT * FROM audit_trail WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?", tuple(params))
        for row in rows:
            row["payload"] = json.loads(row.get("payload") or "{}")
        return rows


# ── Global singleton ─────────────────────────────────────────────────

_db: Optional[Database] = None
_db_lock = threading.Lock()


def get_db() -> Database:
    """Get or create the global Database singleton."""
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                _db = Database()
                _db.init_schema()
    return _db


def reset_db(db_path: str = ":memory:") -> Database:
    """Reset the database (for testing). Creates a new in-memory instance."""
    global _db
    with _db_lock:
        if _db is not None:
            _db.close()
        _db = Database(db_path)
        _db.init_schema()
    return _db
