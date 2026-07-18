"""Run text migrations from carib_clear/migrations in order."""

from __future__ import annotations

import os
from pathlib import Path

from carib_clear.db import Database

_MIGRATIONS_DIR = Path(__file__).with_suffix("") if __name__ == "__main__" else None
if _MIGRATIONS_DIR is None:
    _MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def run() -> None:
    files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        return
    db = Database()
    for path in files:
        sql = path.read_text(encoding="utf-8")
        try:
            db._conn.executescript(sql)
        except Exception as exc:
            raise RuntimeError(f"Migration failed: {path} :: {exc}") from exc
    try:
        db._conn.commit()
    except Exception:
        pass
    print(f"[migrations] Applied {len(files)} migration(s) from {_MIGRATIONS_DIR}")


if __name__ == "__main__":
    run()
