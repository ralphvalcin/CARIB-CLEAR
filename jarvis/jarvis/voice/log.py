from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import sqlite3
import time


@dataclass
class VoiceLogEntry:
    """A single voice interaction log entry."""

    utterance_id: str
    timestamp: float
    duration: float  # seconds of recorded audio
    transcription: str
    response_text: str
    response_path: str  # route path from handle_text
    wake_word: bool  # was this triggered by wake word?


class VoiceLogger:
    """SQLite-backed logger for voice interactions.

    Stores each utterance + JARVIS response for review and debugging.
    """

    def __init__(self, db_path: str = "./data/voice_log.db") -> None:
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_log (
                    utterance_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    duration REAL NOT NULL,
                    transcription TEXT NOT NULL,
                    response_text TEXT NOT NULL,
                    response_path TEXT NOT NULL DEFAULT '',
                    wake_word INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_voice_log_ts ON voice_log(timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_voice_log_transcription ON voice_log(transcription)"
            )
            conn.commit()

    def append(self, entry: VoiceLogEntry) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO voice_log
                    (utterance_id, timestamp, duration, transcription, response_text, response_path, wake_word)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.utterance_id,
                    entry.timestamp,
                    entry.duration,
                    entry.transcription,
                    entry.response_text,
                    entry.response_path,
                    1 if entry.wake_word else 0,
                ),
            )
            conn.commit()

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the most recent voice log entries."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM voice_log ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search voice log entries by transcription text."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM voice_log WHERE transcription LIKE ? ORDER BY timestamp DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def count(self) -> int:
        """Total number of logged utterances."""
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM voice_log").fetchone()[0]