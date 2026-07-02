"""NovisPay client crate entries for Transport API."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import time
from typing import Any, Dict, Optional

from carib_clear.broker.base import MultiRailBroker, RailInfo, SettlementOrder, SettlementResult
from carib_clear.plugin import PluginSpec

DEFAULT_NOVISPAY_WEBHOOK_URL = "https://xymnqhneieuyafdlmznw.supabase.co/functions/v1/caribclear-webhook"
DEFAULT_NOVISPAY_PARTICIPANT_ID = "novispay_001"


@PluginSpec.register("novispay", {
    "type": "settlement_rail",
    "id": "novispay",
    "name": "NovisPay",
    "currencies": ["XCD", "USD"],
    "jurisdictions": ["ECCB"],
    "fee_bps": 0,
    "estimated_time_seconds": 5,
    "min_amount_usd": 10,
    "max_amount_usd": 100000,
    "description": "NovisPay webhook delivery rail for settlement events.",
})
class NovisPayAdapter(MultiRailBroker):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("novispay", config)
        config = config or {}
        self.webhook_url = config.get("webhook_url", DEFAULT_NOVISPAY_WEBHOOK_URL)
        self.participant_id = config.get("participant_id", DEFAULT_NOVISPAY_PARTICIPANT_ID)
        self.shared_secret = config.get("shared_secret") or config.get("webhook_secret") or os.getenv("NOVISPAY_WEBHOOK_SECRET", "")
        self.mock_mode = bool(config.get("mock_mode", True))
        self.mock_failure_rate = float(config.get("mock_failure_rate", 0.0))
        self._initialized = False
        self._envelope_keys: Dict[tuple[str, str], str] = {}

    @property
    def rail_info(self) -> RailInfo:
        return RailInfo(
            rail_id="novispay",
            name="NovisPay",
            supported_currencies=["XCD", "USD"],
            min_amount_usd=10,
            max_amount_usd=100000,
            estimated_time_seconds=5,
            fee_bps=0,
            availability=0.99,
            jurisdictions=["ECCB"],
            metadata={
                "participant_id": self.participant_id,
                "webhook_url": self.webhook_url,
                "mock_mode": self.mock_mode,
            },
        )

    def initialize(self) -> bool:
        self._initialized = True
        return True

    def health_check(self) -> bool:
        return self._initialized

    def get_quote(self, from_currency: str, to_currency: str, amount: float) -> Optional[Dict[str, Any]]:
        return None

    def submit_settlement(self, order: SettlementOrder) -> SettlementResult:
        started = time.time()
        if not self._initialized:
            return SettlementResult(order_id=order.order_id, success=False, status="failed", error_message="not initialized")

        if self.mock_mode and random.random() < self.mock_failure_rate:
            return SettlementResult(
                order_id=order.order_id,
                success=False,
                status="failed",
                error_message="Mock settlement failed (test error)",
                raw_response={
                    "provider": "NovisPay",
                    "reference": f"{self.participant_id}-{order.order_id}",
                    "mode": "mock",
                    "error_message": "Mock settlement failed (test error)",
                    "reason": "mock_failure_rate_triggered",
                },
            )

        tx_ref = f"{self.participant_id}-{order.order_id}"
        return SettlementResult(
            order_id=order.order_id,
            success=True,
            fill_price=order.rate,
            fill_quantity=order.amount_to,
            fees_usd=0.0,
            settlement_time_seconds=round(time.time() - started, 3),
            tx_hash=tx_ref,
            status="filled",
            raw_response={"provider": "NovisPay", "reference": tx_ref, "mode": "mock" if self.mock_mode else "live"},
        )

    def get_settlement_status(self, order_id: str) -> SettlementResult:
        return SettlementResult(order_id=order_id, success=True, status="filled", tx_hash=f"{self.participant_id}-{order_id}")

    def cancel_settlement(self, order_id: str) -> bool:
        return False

    def build_webhook_envelope(self, event_type: str, settlement_payload: Dict[str, Any]) -> Dict[str, Any]:
        if event_type not in {"settlement.completed", "settlement.failed", "settlement.updated"}:
            raise ValueError(f"unsupported event_type: {event_type}")

        settlement_id = settlement_payload.get("settlement_id", "")
        raw_id = f"{settlement_id}:{event_type}".encode()
        stable_event_id = f"evt-{hashlib.sha256(raw_id).hexdigest()[:16]}"
        payload = {
            "event_id": stable_event_id,
            "event_type": event_type,
            "participant_id": self.participant_id,
            "timestamp": time.time(),
            "settlement_id": settlement_payload.get("settlement_id", ""),
            "event": settlement_payload,
            "meta": {"source": "carib-clear", "schema_version": 1},
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {"content-type": "application/json"}
        if self.shared_secret:
            headers["x-caribclear-signature"] = hmac.new(self.shared_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return {"url": self.webhook_url, "headers": headers, "body": body, "payload": payload}
