from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json
import sqlite3

from jarvis.events.models import Event


class JsonlEventStore:
    def __init__(self, path: str = "./data/events.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: Event) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

    def recent(self, limit: int = 10) -> list[dict]:
        """Read the most recent N events from the JSONL file."""
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        events: list[dict] = []
        for line in lines[-limit:]:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events


class SqliteEventStore:
    def __init__(self, db_path: str = "./data/events.db") -> None:
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    ts REAL NOT NULL,
                    session_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    level TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def append(self, event: Event) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO events (event_id, ts, session_id, type, level, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.ts,
                    event.session_id,
                    event.type,
                    event.level,
                    json.dumps(event.payload, ensure_ascii=False),
                ),
            )
            conn.commit()
