"""Persistent conversation memory for JARVIS.

SQLite-backed memory system supporting:
1. Full-text search over past conversation turns (FTS5)
2. Key-value facts ("remember X is Y")
3. Session-based conversation history retrieval
4. Cross-session context injection for LLM prompts

No external dependencies — uses Python stdlib sqlite3.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("jarvis.knowledge.conversation_memory")


class ConversationMemory:
    """Persistent, SQLite-backed conversation memory with FTS5 search.

    Stores three things:
    - conversation_turns: every user/assistant message with session IDs
    - memory_facts: key-value facts ("remember API keys are in .env")
    - session_meta: per-session summaries and activity tracking
    """

    def __init__(self, db_path: str = "./data/conversation_memory.db") -> None:
        self.db_path = str(Path(db_path).resolve())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables and indices on first use."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")

            # Conversation turns
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    ts REAL NOT NULL,
                    uuid TEXT NOT NULL UNIQUE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_turns_session
                ON conversation_turns(session_id, ts)
            """)

            # FTS5 virtual table for full-text search
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS conversation_fts USING fts5(
                    content,
                    content=conversation_turns,
                    content_rowid='id'
                )
            """)

            # FTS5 triggers to keep index in sync
            conn.executescript("""
                CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON conversation_turns BEGIN
                    INSERT INTO conversation_fts(rowid, content) VALUES (new.id, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS turns_ad AFTER DELETE ON conversation_turns BEGIN
                    INSERT INTO conversation_fts(conversation_fts, rowid, content) VALUES('delete', old.id, old.content);
                END;
                CREATE TRIGGER IF NOT EXISTS turns_au AFTER UPDATE ON conversation_turns BEGIN
                    INSERT INTO conversation_fts(conversation_fts, rowid, content) VALUES('delete', old.id, old.content);
                    INSERT INTO conversation_fts(rowid, content) VALUES (new.id, new.content);
                END;
            """)

            # Key-value memory facts
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_facts_category
                ON memory_facts(category)
            """)

            # Session metadata
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_meta (
                    session_id TEXT PRIMARY KEY,
                    last_activity REAL NOT NULL,
                    turn_count INTEGER NOT NULL DEFAULT 0,
                    summary TEXT
                )
            """)

            conn.commit()

    # ── Turn logging ─────────────────────────────────────────────────────────

    def log_turn(self, session_id: str, role: str, content: str) -> int:
        """Record a conversation turn and return its ID."""
        assert role in ("user", "assistant", "system"), f"invalid role: {role}"
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """INSERT INTO conversation_turns (session_id, role, content, ts, uuid)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, role, content, now, str(uuid.uuid4())),
            )
            turn_id = cur.lastrowid

            # Update session meta
            conn.execute(
                """INSERT INTO session_meta (session_id, last_activity, turn_count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(session_id) DO UPDATE SET
                       last_activity=excluded.last_activity,
                       turn_count=turn_count + 1""",
                (session_id, now),
            )
            conn.commit()
        return turn_id

    def get_session_turns(self, session_id: str, limit: int = 50) -> List[dict]:
        """Get all turns for a session, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT id, session_id, role, content, ts, uuid
                   FROM conversation_turns
                   WHERE session_id = ?
                   ORDER BY ts DESC
                   LIMIT ?""",
                (session_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_recent_sessions(self, limit: int = 10) -> List[dict]:
        """Get the most recent sessions with their metadata."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT sm.session_id, sm.last_activity, sm.turn_count, sm.summary,
                          (SELECT content FROM conversation_turns
                           WHERE session_id = sm.session_id AND role = 'user'
                           ORDER BY ts ASC LIMIT 1) AS first_message
                   FROM session_meta sm
                   ORDER BY sm.last_activity DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── FTS5 search ─────────────────────────────────────────────────────────-

    def search_conversations(
        self,
        query: str,
        limit: int = 10,
        session_filter: Optional[str] = None,
    ) -> List[dict]:
        """Full-text search over conversation history using FTS5.

        Args:
            query: FTS5 search terms (supports AND, OR, "phrase", prefix*)
            limit: Max results
            session_filter: Optional session ID to restrict search

        Returns:
            List of matching turns with snippet highlights
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            if session_filter:
                rows = conn.execute(
                    """SELECT ct.id, ct.session_id, ct.role, ct.content, ct.ts,
                              snippet(conversation_fts, 0, '<b>', '</b>', '...', 32) AS highlight
                       FROM conversation_fts
                       JOIN conversation_turns ct ON conversation_fts.rowid = ct.id
                       WHERE conversation_fts MATCH ? AND ct.session_id = ?
                       ORDER BY rank
                       LIMIT ?""",
                    (query, session_filter, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT ct.id, ct.session_id, ct.role, ct.content, ct.ts,
                              snippet(conversation_fts, 0, '<b>', '</b>', '...', 32) AS highlight
                       FROM conversation_fts
                       JOIN conversation_turns ct ON conversation_fts.rowid = ct.id
                       WHERE conversation_fts MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    (query, limit),
                ).fetchall()
            results = [dict(r) for r in rows]
            # Convert ts to readable format
            for r in results:
                r["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"]))
            return results

    # ── Key-value facts ─────────────────────────────────────────────────────

    def save_fact(self, key: str, value: str, category: str = "general") -> None:
        """Save a persistent fact (e.g., 'my API keys are in .env')."""
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO memory_facts (key, value, category, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value=excluded.value,
                       category=excluded.category,
                       updated_at=excluded.updated_at""",
                (key, value, category, now, now),
            )
            conn.commit()

    def get_fact(self, key: str) -> Optional[str]:
        """Retrieve a saved fact by key."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM memory_facts WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else None

    def search_facts(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search memory facts by key or value."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT key, value, category, created_at, updated_at
                   FROM memory_facts
                   WHERE key LIKE ? OR value LIKE ?
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()
            results = [dict(r) for r in rows]
            for r in results:
                r["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["created_at"]))
                r["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["updated_at"]))
            return results

    def list_facts(self, category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List all saved facts, optionally filtered by category."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if category:
                rows = conn.execute(
                    "SELECT key, value, category, created_at, updated_at FROM memory_facts WHERE category = ? ORDER BY updated_at DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key, value, category, created_at, updated_at FROM memory_facts ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            results = [dict(r) for r in rows]
            for r in results:
                r["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["created_at"]))
                r["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["updated_at"]))
            return results

    def delete_fact(self, key: str) -> bool:
        """Delete a specific fact. Returns True if a row was removed."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM memory_facts WHERE key = ?", (key,))
            conn.commit()
            return cur.rowcount > 0

    def clear_all_facts(self) -> int:
        """Delete all memory facts. Returns count of removed facts."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM memory_facts")
            conn.commit()
            return cur.rowcount

    # ── Context injection ────────────────────────────────────────────────────

    def get_context_for_llm(self, session_id: str, max_facts: int = 5, max_history: int = 10) -> str:
        """Build a context string for injection into LLM prompts.

        Includes:
        - Recent conversation history for this session
        - Relevant memory facts
        - Last session summary
        """
        parts: List[str] = []

        # Recent conversation history
        turns = self.get_session_turns(session_id, limit=max_history)
        if turns:
            turns.reverse()
            history_lines = []
            for t in turns:
                prefix = "You" if t["role"] == "assistant" else "User"
                # Truncate long content for context
                content = t["content"][:200]
                history_lines.append(f"{prefix}: {content}")
            if history_lines:
                parts.append("### Recent conversation")
                parts.extend(history_lines)
                parts.append("")

        # Memory facts
        facts = self.list_facts(limit=max_facts)
        if facts:
            parts.append("### Things I remember")
            for f in facts:
                parts.append(f"- {f['key']}: {f['value']}")
            parts.append("")

        if not parts:
            return ""

        return "\n".join(parts)

    # ── Session summary ──────────────────────────────────────────────────────

    def update_session_summary(self, session_id: str, summary: str) -> None:
        """Store a summary for a session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO session_meta (session_id, last_activity, turn_count, summary)
                   VALUES (?, ?, 0, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       summary=excluded.summary,
                       last_activity=excluded.last_activity""",
                (session_id, time.time(), summary),
            )
            conn.commit()

    def get_session_summary(self, session_id: str) -> Optional[str]:
        """Get the summary for a session."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT summary FROM session_meta WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return row[0] if row else None

    # ── Maintenance ──────────────────────────────────────────────────────────

    def prune_old_turns(self, max_age_days: int = 90) -> int:
        """Remove conversation turns older than max_age_days. Returns count removed."""
        cutoff = time.time() - (max_age_days * 86400)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM conversation_turns WHERE ts < ?", (cutoff,)
            )
            conn.execute(
                "DELETE FROM session_meta WHERE last_activity < ?", (cutoff,)
            )
            conn.commit()
            return cur.rowcount

    def stats(self) -> Dict[str, Any]:
        """Return memory statistics."""
        with sqlite3.connect(self.db_path) as conn:
            turn_count = conn.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()[0]
            fact_count = conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
            session_count = conn.execute("SELECT COUNT(*) FROM session_meta").fetchone()[0]
            return {
                "conversation_turns": turn_count,
                "memory_facts": fact_count,
                "sessions": session_count,
                "db_path": self.db_path,
            }