"""SQLite persistence layer for CARIB-CLEAR.

Replaces in-memory storage with SQLite for durable state across restarts.
Webhook registrations, delivery logs, loan applications, and config key-value
store all persist in a single `carib_clear.db` file.

No external database needed — Python's built-in sqlite3 handles everything.
For production, swap to PostgreSQL by replacing this module.
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
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default DB path (relative to project root)
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "carib_clear.db")

# Schema SQL
SCHEMA_SQL = """
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
    created_at TEXT NOT NULL
);

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

CREATE TABLE IF NOT EXISTS loan_applications (
    application_id TEXT PRIMARY KEY,
    business_name TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    jurisdiction TEXT NOT NULL,
    approved INTEGER DEFAULT 0,
    lender TEXT,
    interest_rate_pct REAL,
    sector TEXT,
    purpose TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class Database:
    """SQLite database with thread-safe access.

    Usage:
        db = Database()
        db.init_schema()
        db.insert("webhooks", {"webhook_id": "wh_001", ...})
        rows = db.query("SELECT * FROM webhooks WHERE participant_id = ?", ("bb_hotel",))
    """

    def __init__(self, db_path: str = ""):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._local = threading.local()
        logger.info("[DB] Path: %s", self.db_path)

    @property
    def _conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def init_schema(self) -> None:
        """Create tables if they don't exist."""
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()
        logger.info("[DB] Schema initialized")

    def insert(self, table: str, data: Dict[str, Any]) -> bool:
        """Insert a row into a table.

        Args:
            table: Table name.
            data: Dict of column_name -> value.

        Returns:
            True on success.
        """
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        sql = f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})"
        try:
            self._conn.execute(sql, list(data.values()))
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
        try:
            self._conn.execute(sql, params)
            self._conn.commit()
            return True
        except Exception as e:
            logger.error("[DB] Execute failed: %s — %s", sql, e)
            return False

    def delete(self, table: str, where: str, params: tuple = ()) -> bool:
        """Delete rows from a table."""
        return self.execute(f"DELETE FROM {table} WHERE {where}", params)

    def count(self, table: str, where: str = "1=1", params: tuple = ()) -> int:
        """Count rows in a table."""
        row = self.query_one(f"SELECT COUNT(*) as cnt FROM {table} WHERE {where}", params)
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


# ── Global singleton ─────────────────────────────────────────────────

_db: Optional[Database] = None


def get_db() -> Database:
    """Get or create the global Database singleton."""
    global _db
    if _db is None:
        _db = Database()
        _db.init_schema()
    return _db


def reset_db(db_path: str = ":memory:") -> Database:
    """Reset the database (for testing). Creates a new in-memory instance."""
    global _db
    _db = Database(db_path)
    _db.init_schema()
    return _db
