"""Immutable append-only audit trail for CARIB-CLEAR."""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from carib_clear.db import Database, get_db

logger = logging.getLogger(__name__)


_SECRET_HINT_KEYS = {"api_key", "apikey", "authorization", "bearer", "client_secret", "password", "secret", "token", "x-api-key"}
_SECRET_HINT_SUFFIXES = ("_token", "_secret", "_key")


def _looks_like_secret(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in payload.keys():
        if not isinstance(key, str):
            continue
        lowered = key.lower()
        if lowered in _SECRET_HINT_KEYS or any(lowered.endswith(suffix) for suffix in _SECRET_HINT_SUFFIXES):
            return True
        if "bearer" in lowered or "basic " in lowered:
            return True
    return False


def audit(
    *,
    event: str,
    actor: str,
    action: str,
    entity: Optional[str] = None,
    entity_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    outcome: str = "success",
    reference: Optional[str] = None,
    db: Optional[Database] = None,
) -> Dict[str, Any]:
    """Append an immutable audit record."""
    payload = payload or {}
    if _looks_like_secret(payload):
        payload = {"***": "redacted"}
    reference = reference or str(uuid.uuid4())
    attempt: Dict[str, Any] = {
        "audit_id": reference,
        "event": event,
        "actor": actor,
        "action": action,
        "entity": entity or "",
        "entity_id": entity_id or "",
        "payload": payload,
        "outcome": outcome,
    }
    try:
        target = db or get_db()
        if hasattr(target, "insert_audit_trail"):
            target.insert_audit_trail(
                audit_id=reference,
                event=event,
                actor=actor,
                action=action,
                entity=entity or "",
                entity_id=entity_id or "",
                payload=payload,
                outcome=outcome,
            )
        logger.debug("Audit %s %s %s", action, entity, outcome)
        return attempt
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Audit write failed: %s", exc, exc_info=True)
        attempt["audit_status"] = "write_failed"
        return attempt


def list_audits(db: Optional[Database] = None, limit: int = 100, event: Optional[str] = None, entity: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        target = db or get_db()
        if not hasattr(target, "list_audit_trail"):
            return []
        kwargs: Dict[str, Any] = {"limit": max(limit, 1)}
        if event:
            kwargs["event"] = event
        if entity:
            kwargs["entity"] = entity
        return target.list_audit_trail(**kwargs)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Audit query failed: %s", exc)
        return []


def list_audit_trail_admin(
    db: Optional[Database] = None,
    limit: int = 100,
    offset: int = 0,
    event: Optional[str] = None,
    entity: Optional[str] = None,
    actor: Optional[str] = None,
    outcome: Optional[str] = None,
) -> List[Dict[str, Any]]:
    try:
        target = db or get_db()
        where = ["1=1"]
        params: list = []
        if event:
            where.append("event = ?")
            params.append(event)
        if entity:
            where.append("entity = ?")
            params.append(entity)
        if actor:
            where.append("actor = ?")
            params.append(actor)
        if outcome:
            where.append("outcome = ?")
            params.append(outcome)
        params.extend([max(limit, 1), max(offset, 0)])
        sql = (
            f"SELECT * FROM audit_trail WHERE {' AND '.join(where)}"
            " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        )
        rows = target.query(sql, tuple(params))
        for row in rows:
            row["payload"] = json.loads(row.get("payload") or "{}")
        return rows
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Audit query failed: %s", exc)
        return []


def count_audit_trail_admin(
    db: Optional[Database] = None,
    event: Optional[str] = None,
    entity: Optional[str] = None,
    actor: Optional[str] = None,
    outcome: Optional[str] = None,
) -> int:
    try:
        target = db or get_db()
        where = ["1=1"]
        count_params: list = []
        if event:
            where.append("event = ?")
            count_params.append(event)
        if entity:
            where.append("entity = ?")
            count_params.append(entity)
        if actor:
            where.append("actor = ?")
            count_params.append(actor)
        if outcome:
            where.append("outcome = ?")
            count_params.append(outcome)
        sql = f"SELECT COUNT(*) as total FROM audit_trail WHERE {' AND '.join(where)}"
        row = target.query_one(sql, tuple(count_params))
        return int(row.get("total", 0) if isinstance(row, dict) else (row[0] if row else 0))
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Audit count failed: %s", exc)
        return 0


def get_audit_by_id(audit_id: str, db: Optional[Database] = None) -> Optional[Dict[str, Any]]:
    try:
        target = db or get_db()
        if not hasattr(target, "query_one"):
            return None
        row = target.query_one("SELECT * FROM audit_trail WHERE audit_id = ?", (audit_id,))
        if not row:
            return None
        row = dict(row)
        try:
            payload = json.loads(row.get("payload") or "{}")
        except Exception:
            payload = {"***": "unreadable"}
        if _looks_like_secret(payload):
            payload = {"***": "redacted"}
        row["payload"] = payload
        return row
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Audit detail failed: %s", exc)
        return None
