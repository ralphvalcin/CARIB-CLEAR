"""Persistent conversation memory for JARVIS.

SQLite-backed store providing:
1. Conversation turn logging with FTS5 full-text search
2. Key-value fact persistence ("remember X is Y")
3. Session-aware context retrieval for LLM injection
4. Cross-session recall ("what did we talk about yesterday?")

No external dependencies — uses stdlib sqlite3 with FTS5.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis.knowledge.memory")

_MAX_FACTS_PER_QUERY = 20
_MAX_TURNS_PER_SESSION = 50
_MAX_SEARCH_RESULTS = 10
_FTS_MAX_TOKENS = 128


@dataclass
class ConversationTurn:
    """A single turn in a conversation."""
    id: int = 0
    session_id: str = ""
    role: str = ""  # 'user', 'assistant', 'system'
    content: str = ""
    ts: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content[:200],  # truncated for display
            "ts": self.ts,
        }


@dataclass
class MemoryFact:
    """A persistent key-value fact."""
    key: str = ""
    value: str = ""
    category: str = "general"
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value[:200],
            "category": self.category,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class MemorySearchResult:
    """Result of a conversation memory search."""
    query: str = ""
    turns: List[ConversationTurn] = field(default_factory=list)
    facts: List[MemoryFact] = field(default_factory=list)
    sessions_found: int = 0

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "turns": [t.to_dict() for t in self.turns],
            "facts": [f.to_dict() for f in self.facts],
            "sessions_found": self.sessions_found,
        }


class ConversationMemoryStore:
    """SQLite-backed persistent conversation memory.

    Schema:
    - conversation_turns: all user/assistant turns with timestamps
    - conversation_fts: FTS5 virtual table for full-text search
    - memory_facts: key-value persistence for remembered facts
    - session_meta: per-session metadata and summaries
    """

    def __init__(self, db_path: str = "./data/conversation_memory.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    ts REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns(session_id, ts);
                CREATE INDEX IF NOT EXISTS idx_turns_ts ON conversation_turns(ts);

                CREATE VIRTUAL TABLE IF NOT EXISTS conversation_fts USING fts5(
                    content,
                    content=conversation_turns,
                    content_rowid='id',
                    tokenize='porter unicode61'
                );

                -- Auto-sync triggers for FTS
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

                CREATE TABLE IF NOT EXISTS memory_facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_facts_category ON memory_facts(category);

                CREATE TABLE IF NOT EXISTS session_meta (
                    session_id TEXT PRIMARY KEY,
                    last_activity REAL NOT NULL,
                    turn_count INTEGER DEFAULT 0,
                    summary TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_session_activity ON session_meta(last_activity);
            """)
            conn.commit()

    # ── Conversation turn logging ────────────────────────────────────────────

    def log_turn(self, session_id: str, role: str, content: str) -> int:
        """Record a conversation turn. Returns the turn ID."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO conversation_turns (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
                (session_id, role, content, time.time()),
            )
            turn_id = cursor.lastrowid or 0

            # Update session metadata
            conn.execute("""
                INSERT INTO session_meta (session_id, last_activity, turn_count)
                VALUES (?, ?, 1)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_activity = excluded.last_activity,
                    turn_count = turn_count + 1
            """, (session_id, time.time()))

            conn.commit()
            return turn_id

    def get_session_turns(
        self,
        session_id: str,
        limit: int = _MAX_TURNS_PER_SESSION,
        offset: int = 0,
    ) -> List[ConversationTurn]:
        """Get recent conversation turns for a session, newest first."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, session_id, role, content, ts FROM conversation_turns "
                "WHERE session_id = ? ORDER BY ts DESC LIMIT ? OFFSET ?",
                (session_id, limit, offset),
            ).fetchall()
        return [ConversationTurn(**dict(r)) for r in reversed(rows)]  # chronological

    def get_recent_turns(
        self, limit: int = 20, since: Optional[float] = None
    ) -> List[ConversationTurn]:
        """Get most recent turns across all sessions."""
        with self._get_conn() as conn:
            if since:
                rows = conn.execute(
                    "SELECT id, session_id, role, content, ts FROM conversation_turns "
                    "WHERE ts > ? ORDER BY ts DESC LIMIT ?",
                    (since, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, session_id, role, content, ts FROM conversation_turns "
                    "ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [ConversationTurn(**dict(r)) for r in reversed(rows)]

    def get_session_summary(self, session_id: str) -> str:
        """Get a brief summary of what happened in a session."""
        turns = self.get_session_turns(session_id, limit=10)
        if not turns:
            return "No conversation history for this session."

        # Build a compact summary
        summary_parts: List[str] = []
        for t in turns[-6:]:  # last 6 turns
            prefix = "You" if t.role == "user" else "JARVIS"
            content = t.content[:120]
            summary_parts.append(f"{prefix}: {content}")

        return "\n".join(summary_parts)

    # ── Full-text search ─────────────────────────────────────────────────────

    def search_conversations(
        self, query: str, limit: int = _MAX_SEARCH_RESULTS
    ) -> List[ConversationTurn]:
        """Full-text search over all conversation history."""
        if not query.strip():
            return []

        with self._get_conn() as conn:
            try:
                # Sanitize query for FTS5
                safe_query = self._sanitize_fts_query(query)
                rows = conn.execute(
                    "SELECT t.id, t.session_id, t.role, t.content, t.ts "
                    "FROM conversation_fts f "
                    "JOIN conversation_turns t ON f.rowid = t.id "
                    "WHERE conversation_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (safe_query, limit),
                ).fetchall()
            except sqlite3.OperationalError as e:
                logger.warning("FTS5 query failed ('%s'): %s", query, e)
                # Fallback to LIKE search
                like_pattern = f"%{query}%"
                rows = conn.execute(
                    "SELECT id, session_id, role, content, ts FROM conversation_turns "
                    "WHERE content LIKE ? ORDER BY ts DESC LIMIT ?",
                    (like_pattern, limit),
                ).fetchall()

        return [ConversationTurn(**dict(r)) for r in rows]

    def _sanitize_fts_query(self, query: str) -> str:
        """Clean up a user query for safe FTS5 matching."""
        # Remove special FTS5 characters but keep words
        cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in query)
        # Limit tokens
        tokens = cleaned.strip().split()[:8]
        if not tokens:
            return query  # fallback
        # Default FTS5 mode is AND — multi-word searches need all terms
        return " AND ".join(tokens)

    # ── Key-value facts ─────────────────────────────────────────────────────

    def save_fact(self, key: str, value: str, category: str = "general") -> None:
        """Remember a fact (persistent key-value pair)."""
        now = time.time()
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO memory_facts (key, value, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    updated_at = excluded.updated_at
            """, (key.lower().strip(), value, category, now, now))
            conn.commit()
        logger.info("Saved fact: '%s' = '%s' (category=%s)", key, value, category)

    def get_fact(self, key: str) -> Optional[MemoryFact]:
        """Retrieve a remembered fact by key."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT key, value, category, created_at, updated_at FROM memory_facts WHERE key = ?",
                (key.lower().strip(),),
            ).fetchone()
        if row:
            return MemoryFact(**dict(row))
        return None

    def search_facts(
        self, query: str, limit: int = _MAX_FACTS_PER_QUERY
    ) -> List[MemoryFact]:
        """Search facts by key or value content."""
        like = f"%{query}%"
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT key, value, category, created_at, updated_at FROM memory_facts "
                "WHERE key LIKE ? OR value LIKE ? OR category LIKE ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (like, like, like, limit),
            ).fetchall()
        return [MemoryFact(**dict(r)) for r in rows]

    def all_facts(self, limit: int = 50) -> List[MemoryFact]:
        """Get all remembered facts."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT key, value, category, created_at, updated_at FROM memory_facts "
                "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [MemoryFact(**dict(r)) for r in rows]

    def delete_fact(self, key: str) -> bool:
        """Delete a remembered fact. Returns True if existed."""
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM memory_facts WHERE key = ?", (key.lower().strip(),))
            conn.commit()
            return cursor.rowcount > 0

    def delete_facts_by_category(self, category: str) -> int:
        """Delete all facts in a category. Returns count deleted."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM memory_facts WHERE category = ?", (category,)
            )
            conn.commit()
            return cursor.rowcount

    # ── Composite operations ─────────────────────────────────────────────────

    def search_memory(
        self, query: str, limit: int = _MAX_SEARCH_RESULTS
    ) -> MemorySearchResult:
        """Search both conversation history AND facts with one query."""
        result = MemorySearchResult(query=query)

        # Search conversations
        result.turns = self.search_conversations(query, limit=limit)

        # Search facts
        result.facts = self.search_facts(query, limit=limit)

        # Count unique sessions found
        session_ids = set(t.session_id for t in result.turns)
        result.sessions_found = len(session_ids)

        return result

    def build_context_prompt(self, session_id: str, max_turns: int = 6) -> str:
        """Build a context string for LLM injection with recent history + relevant facts."""
        parts: List[str] = []

        # Recent conversation history
        turns = self.get_session_turns(session_id, limit=max_turns)
        if turns:
            history_lines: List[str] = ["Recent conversation:"]
            for t in turns:
                prefix = "User" if t.role == "user" else "JARVIS"
                history_lines.append(f"  {prefix}: {t.content[:200]}")
            parts.append("\n".join(history_lines))

        # Relevant facts
        facts = self.all_facts(limit=5)
        if facts:
            fact_lines: List[str] = ["Things I remember:"]
            for f in facts:
                fact_lines.append(f"  {f.key}: {f.value}")
            parts.append("\n".join(fact_lines))

        return "\n\n".join(parts)

    def parse_remember_command(self, text: str) -> Optional[Dict[str, str]]:
        """Parse a 'remember X is Y' style command into a key-value pair.

        Supports patterns:
        - "remember X is Y"
        - "remember that X is Y"
        - "remember X = Y"
        - "don't forget X is Y"
        - "remember my X is Y"
        - "remember: X is Y"
        """
        t = text.strip().lower()

        # Remove prefix
        for prefix in ["remember that ", "remember my ", "remember: ", "remember ", "don't forget that ", "don't forget ", "dont forget "]:
            if t.startswith(prefix):
                t = t[len(prefix):]
                break
        else:
            return None

        # Try "X is Y" pattern
        if " is " in t:
            parts = t.split(" is ", 1)
            key = parts[0].strip()
            value = parts[1].strip()
            if key and value:
                return {"key": key, "value": value}

        # Try "X = Y" pattern
        if " = " in t:
            parts = t.split(" = ", 1)
            key = parts[0].strip()
            value = parts[1].strip()
            if key and value:
                return {"key": key, "value": value}

        return None

    def parse_recall_command(self, text: str) -> Optional[str]:
        """Extract the search query from a recall/what-did-we-talk-about command.

        Patterns:
        - "what did we talk about X" → X
        - "what was I working on with X" → X
        - "recall X" → X
        - "search for X in our conversations" → X
        - bare "what did we talk about" → None (return recent summary)
        """
        t = text.strip().lower()
        prefixes = [
            "what did we talk about ",
            "what did i ask about ",
            "what was i working on ",
            "search for ",
            "search ",
            "recall ",
            "find ",
        ]

        # Check if there's a specific topic
        for prefix in prefixes:
            if t.startswith(prefix):
                rest = t[len(prefix):].strip()
                if rest and rest not in ("", ".", "?"):
                    return rest

        # No specific topic found, return None for general recall
        return None


class InMemoryConversationStore(ConversationMemoryStore):
    """In-memory version for testing — uses :memory: SQLite."""

    def __init__(self) -> None:
        # Override db_path to use :memory:
        self.db_path = Path(":memory:")
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        return self._conn