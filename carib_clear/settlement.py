"""Settlement lifecycle for CARIB-CLEAR.

Provides:
- idempotent submit helper: record+route+persist
- canonical settlement_id generation: '{rail}:{order_id}'
- immutable audit trail via settlement_events
- atomic, forward-only state transitions
"""

from __future__ import annotations

import enum
import json
import logging
from typing import Any, Dict, Optional

from carib_clear.db import get_db

logger = logging.getLogger(__name__)


class SettlementStatus(str, enum.Enum):
    PENDING = "pending"
    FILLED = "filled"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Forward-only transitions for financial correctness.
_TRANSITIONS = {
    SettlementStatus.PENDING: {SettlementStatus.FILLED, SettlementStatus.FAILED, SettlementStatus.CANCELLED},
    SettlementStatus.FILLED: set(),
    SettlementStatus.FAILED: set(),
    SettlementStatus.CANCELLED: set(),
}


def to_settlement_id(rail: str, order_id: str) -> str:
    return f"{rail}:{order_id}"


_recorded: Dict[str, Dict[str, Any]] = {}


def mark_pending(rail: str, order_id: str, data: Optional[Dict[str, Any]] = None) -> str:
    settlement_id = to_settlement_id(rail, order_id)
    _recorded[settlement_id] = {"status": SettlementStatus.PENDING, "data": data or {}}
    return settlement_id


def submit(rail: str, order_id: str, business_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    settlement_id = to_settlement_id(rail, order_id)
    db = get_db()
    existing = db.get_settlement(settlement_id)
    if existing and existing.get("status") in {SettlementStatus.FILLED, SettlementStatus.FAILED, SettlementStatus.CANCELLED}:
        logger.info("[Settlement] idempotent hit for %s -> %s", settlement_id, existing["status"])
        return existing

    scope = _coerce_business_key(business_key)
    created = db.create_settlement(
        settlement_id=settlement_id,
        scope=scope,
        business_key=business_key,
        data={
            "rail": rail,
            "order_id": order_id,
            "status": SettlementStatus.PENDING,
            "amount_usd": payload.get("amount_usd", 0),
            "currency_from": payload.get("currency_from", ""),
            "currency_to": payload.get("currency_to", ""),
            "amount_from": payload.get("amount_from", 0),
            "amount_to": payload.get("amount_to", 0),
            "rate": payload.get("rate", 0),
            "fees_usd": payload.get("fees_usd", 0),
            "raw_response": payload.get("raw_response"),
        },
        participant_id=payload.get("participant_id"),
    )
    if not created:
        logger.debug("[Settlement] create skipped for %s", settlement_id)

    _recorded[settlement_id] = {"status": SettlementStatus.PENDING}
    _append_event(settlement_id, SettlementStatus.PENDING, payload)
    return _load_settlement(settlement_id)


def complete(rail: str, order_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    settlement_id = to_settlement_id(rail, order_id)
    status = SettlementStatus.FILLED if result.get("success") else SettlementStatus.FAILED
    return transition_to(settlement_id, status, result)


def cancel(rail: str, order_id: str, reason: str = "") -> Dict[str, Any]:
    settlement_id = to_settlement_id(rail, order_id)
    return transition_to(settlement_id, SettlementStatus.CANCELLED, {"error_message": reason})


def transition_to(settlement_id: str, target: SettlementStatus, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    db = get_db()
    row = _get_settlement_for_transition(db, settlement_id)
    current = SettlementStatus(row.get("status", SettlementStatus.PENDING))
    if not _is_allowed(current, target):
        raise ValueError(f"Invalid settlement transition: {current.value} -> {target.value}")
    now = datetime_utcnow()
    payload = result or {}
    db.update_settlement_status(
        settlement_id=settlement_id,
        status=target.value,
        tx_hash=payload.get("tx_hash"),
        error_message=payload.get("error_message", ""),
        raw_response=payload.get("raw_response") or {},
    )
    db.execute(
        "UPDATE settlements SET updated_at = ? WHERE settlement_id = ?",
        (now, settlement_id),
    )
    _append_event(settlement_id, target, payload)
    cached = _recorded.get(settlement_id, {})
    cached["status"] = target
    return _load_settlement(settlement_id)


def get_settlement(settlement_id: str) -> Dict[str, Any]:
    cached = _recorded.get(settlement_id)
    if cached:
        if cached.get("status") in {SettlementStatus.FILLED, SettlementStatus.FAILED, SettlementStatus.CANCELLED}:
            data = cached.get("data") or {}
            row = _get_settlement_for_transition(get_db(), settlement_id)
            if row:
                row.pop("raw_response", None)
                return row
            return {
                "settlement_id": settlement_id,
                "status": cached["status"].value if isinstance(cached["status"], SettlementStatus) else cached["status"],
                "rail": data.get("rail"),
                "order_id": data.get("order_id"),
            }
    return _load_settlement(settlement_id)


def get_order_settlement(rail: str, order_id: str) -> Optional[Dict[str, Any]]:
    row = get_db().get_settlement_by_order(rail=rail, order_id=order_id)
    if row:
        row.pop("raw_response", None)
    return row


def _load_settlement(settlement_id: str) -> Dict[str, Any]:
    row = get_db().get_settlement(settlement_id)
    if row:
        row.pop("raw_response", None)
    return row or {}


def _is_allowed(current: SettlementStatus, target: SettlementStatus) -> bool:
    return target in _TRANSITIONS.get(current, set())


def _get_settlement_for_transition(db, settlement_id: str) -> Dict[str, Any]:
    row = db.get_settlement(settlement_id)
    if not row:
        raise ValueError(f"Settlement not found: {settlement_id}")
    return row


def _append_event(settlement_id: str, target: SettlementStatus, payload: Dict[str, Any]) -> None:
    db = get_db()
    event_id = f"{settlement_id}:{target.value}"
    db.insert("settlement_events", {
        "event_id": event_id,
        "settlement_id": settlement_id,
        "event_type": target.value,
        "payload": json.dumps(payload or {}),
        "source": payload.get("source") if isinstance(payload, dict) else None,
        "confirmed_at": datetime_utcnow(),
    })


def _coerce_business_key(business_key: str) -> str:
    if business_key in {"fx", "p2p", "rtp"}:
        return business_key
    return "fx"


def datetime_utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
