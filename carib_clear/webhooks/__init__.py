"""Webhook system for CARIB-CLEAR — event notifications for integrators.

Banks, fintechs, and settlement partners register webhook URLs to receive
real-time notifications when events occur (settlement completed, loan
approved, etc.). The system delivers POST requests with signed JSON payloads.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── Events ─────────────────────────────────────────────────────────────

# Standard event types
EVENT_SETTLEMENT_COMPLETED = "settlement.completed"
EVENT_SETTLEMENT_FAILED = "settlement.failed"
EVENT_LOAN_APPROVED = "loan.approved"
EVENT_LOAN_DECLINED = "loan.declined"
EVENT_COMPLIANCE_FLAG = "compliance.flagged"


# ─── Data Models ────────────────────────────────────────────────────────


@dataclass
class WebhookRegistration:
    """A registered webhook endpoint."""
    webhook_id: str
    url: str
    events: List[str]  # Which events to receive (or ["*"] for all)
    participant_id: str  # Which participant owns this webhook
    secret: str = ""  # HMAC signing secret (auto-generated if empty)
    description: str = ""
    retry_count: int = 3  # Number of retries on failure
    timeout_seconds: int = 10
    created_at: str = ""
    active: bool = True

    def __post_init__(self):
        if not self.webhook_id:
            self.webhook_id = f"wh_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.secret:
            self.secret = uuid.uuid4().hex

    def matches_event(self, event_type: str) -> bool:
        """Check if this webhook should receive the given event."""
        return self.active and ("*" in self.events or event_type in self.events)

    def sign_payload(self, payload: bytes) -> str:
        """HMAC-SHA256 sign a payload with the webhook secret."""
        return hmac.new(
            self.secret.encode(), payload, hashlib.sha256
        ).hexdigest()


@dataclass
class DeliveryAttempt:
    """Record of a webhook delivery attempt."""
    webhook_id: str
    event_type: str
    payload: Dict[str, Any]
    status: str  # "success", "failed", "pending"
    delivery_id: str = ""
    status_code: int = 0
    error_message: str = ""
    attempt_number: int = 1
    duration_ms: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.delivery_id:
            self.delivery_id = f"del_{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ─── Webhook Registry ──────────────────────────────────────────────────


class WebhookRegistry:
    """Registry of webhook endpoints with SQLite persistence.

    Webhook registrations and delivery logs are stored in SQLite so they
    survive server restarts.
    """

    def __init__(self, db: Any = None):
        self._webhooks: Dict[str, WebhookRegistration] = {}
        self._deliveries: List[DeliveryAttempt] = []
        if db is None:
            from carib_clear.db import get_db
            db = get_db()
        self.db = db
        self._load_from_db()

    def _load_from_db(self) -> None:
        """Load webhooks and recent deliveries from SQLite."""
        rows = self.db.query("SELECT * FROM webhooks WHERE active = 1")
        for row in rows:
            self._webhooks[row["webhook_id"]] = WebhookRegistration(
                webhook_id=row["webhook_id"],
                url=row["url"],
                events=json.loads(row["events"]),
                participant_id=row["participant_id"],
                secret=row["secret"],
                description=row.get("description", ""),
                retry_count=row.get("retry_count", 3),
                timeout_seconds=row.get("timeout_seconds", 10),
                created_at=row["created_at"],
                active=bool(row["active"]),
            )
        # Load last 100 deliveries
        del_rows = self.db.query(
            "SELECT * FROM delivery_attempts ORDER BY timestamp DESC LIMIT 100"
        )
        for row in reversed(del_rows):
            self._deliveries.append(DeliveryAttempt(
                delivery_id=row["delivery_id"],
                webhook_id=row["webhook_id"],
                event_type=row["event_type"],
                payload={},
                status=row["status"],
                status_code=row.get("status_code", 0),
                error_message=row.get("error_message", ""),
                attempt_number=row.get("attempt_number", 1),
                duration_ms=row.get("duration_ms", 0.0),
                timestamp=row["timestamp"],
            ))
        if self._webhooks:
            logger.info("[Webhooks] Loaded %d webhooks, %d deliveries from DB",
                         len(self._webhooks), len(self._deliveries))

    def register(
        self,
        url: str,
        events: List[str],
        participant_id: str,
        description: str = "",
        retry_count: int = 3,
        timeout_seconds: int = 10,
    ) -> WebhookRegistration:
        """Register a new webhook endpoint.

        Args:
            url: The URL to POST events to.
            events: List of event types (or ["*"] for all).
            participant_id: The participant who owns this webhook.
            description: Human-readable description.
            retry_count: Number of retries on failure.
            timeout_seconds: HTTP request timeout.

        Returns:
            The registered WebhookRegistration.
        """
        wh = WebhookRegistration(
            webhook_id=f"wh_{uuid.uuid4().hex[:12]}",
            url=url,
            events=events,
            participant_id=participant_id,
            description=description,
            retry_count=retry_count,
            timeout_seconds=timeout_seconds,
        )
        self._webhooks[wh.webhook_id] = wh
        self.db.insert("webhooks", {
            "webhook_id": wh.webhook_id,
            "url": wh.url,
            "events": json.dumps(wh.events),
            "participant_id": wh.participant_id,
            "secret": wh.secret,
            "description": wh.description,
            "retry_count": wh.retry_count,
            "timeout_seconds": wh.timeout_seconds,
            "active": 1,
            "created_at": wh.created_at,
        })
        logger.info("[Webhooks] Registered %s for %s (%s)", wh.webhook_id, participant_id, url)
        return wh

    def unregister(self, webhook_id: str) -> bool:
        """Remove a webhook registration."""
        if webhook_id in self._webhooks:
            del self._webhooks[webhook_id]
            self.db.execute("DELETE FROM webhooks WHERE webhook_id = ?", (webhook_id,))
            logger.info("[Webhooks] Unregistered %s", webhook_id)
            return True
        return False

    def get(self, webhook_id: str) -> Optional[WebhookRegistration]:
        """Get a webhook by ID."""
        return self._webhooks.get(webhook_id)

    def list(self, participant_id: Optional[str] = None) -> List[WebhookRegistration]:
        """List webhooks, optionally filtered by participant."""
        if participant_id:
            return [w for w in self._webhooks.values() if w.participant_id == participant_id]
        return list(self._webhooks.values())

    def get_subscribers(self, event_type: str, participant_id: Optional[str] = None) -> List[WebhookRegistration]:
        """Get webhooks subscribed to a specific event."""
        subscribers = [
            w for w in self._webhooks.values()
            if w.matches_event(event_type)
        ]
        if participant_id:
            subscribers = [w for w in subscribers if w.participant_id == participant_id]
        return subscribers

    def record_delivery(self, attempt: DeliveryAttempt) -> None:
        """Record a delivery attempt."""
        self._deliveries.append(attempt)
        self.db.insert("delivery_attempts", {
            "delivery_id": attempt.delivery_id,
            "webhook_id": attempt.webhook_id,
            "event_type": attempt.event_type,
            "status": attempt.status,
            "status_code": attempt.status_code,
            "error_message": attempt.error_message,
            "attempt_number": attempt.attempt_number,
            "duration_ms": attempt.duration_ms,
            "timestamp": attempt.timestamp,
        })
        if len(self._deliveries) > 1000:
            self._deliveries = self._deliveries[-1000:]

    def get_deliveries(self, webhook_id: Optional[str] = None, limit: int = 50) -> List[DeliveryAttempt]:
        """Get delivery history."""
        deliveries = self._deliveries
        if webhook_id:
            deliveries = [d for d in deliveries if d.webhook_id == webhook_id]
        return deliveries[-limit:]


# ─── Webhook Dispatcher ────────────────────────────────────────────────


class WebhookDispatcher:
    """Dispatches events to registered webhooks with retry logic."""

    def __init__(self, registry: WebhookRegistry):
        self.registry = registry
        self._http = None  # Lazy-import httpx for async delivery

    def _get_http(self):
        if self._http is None:
            import httpx
            self._http = httpx
        return self._http

    def dispatch(self, event_type: str, payload: Dict[str, Any],
                 participant_id: Optional[str] = None) -> List[DeliveryAttempt]:
        """Dispatch an event to all matching webhooks.

        Args:
            event_type: The event type (e.g. "settlement.completed").
            payload: The event payload (JSON-serializable dict).
            participant_id: Optional — if set, only deliver to this participant's webhooks.

        Returns:
            List of delivery attempts (one per webhook).
        """
        import httpx

        subscribers = self.registry.get_subscribers(event_type, participant_id)
        if not subscribers:
            logger.debug("[Webhooks] No subscribers for %s", event_type)
            return []

        payload_bytes = json.dumps(payload).encode()
        results: List[DeliveryAttempt] = []

        for wh in subscribers:
            attempt = self._deliver(wh, event_type, payload, payload_bytes)
            self.registry.record_delivery(attempt)
            results.append(attempt)

        success_count = sum(1 for r in results if r.status == "success")
        logger.info("[Webhooks] Dispatched %s: %d/%d delivered",
                     event_type, success_count, len(results))
        return results

    def _deliver(self, wh: WebhookRegistration, event_type: str,
                 payload: Dict[str, Any], payload_bytes: bytes) -> DeliveryAttempt:
        """Deliver a single webhook with retry logic."""
        import httpx

        signature = wh.sign_payload(payload_bytes)
        headers = {
            "Content-Type": "application/json",
            "X-CARIB-CLEAR-Event": event_type,
            "X-CARIB-CLEAR-Signature": signature,
            "X-CARIB-CLEAR-Delivery": uuid.uuid4().hex,
            "User-Agent": "CARIB-CLEAR-Webhook/1.0",
        }

        t0 = time.time()

        for attempt_num in range(1, wh.retry_count + 1):
            try:
                with httpx.Client(timeout=wh.timeout_seconds) as client:
                    resp = client.post(wh.url, content=payload_bytes, headers=headers)

                duration_ms = (time.time() - t0) * 1000
                attempt = DeliveryAttempt(
                    webhook_id=wh.webhook_id,
                    event_type=event_type,
                    payload=payload,
                    status="success" if resp.is_success else "failed",
                    status_code=resp.status_code,
                    attempt_number=attempt_num,
                    duration_ms=round(duration_ms, 1),
                    error_message="" if resp.is_success else f"HTTP {resp.status_code}",
                )
                if resp.is_success:
                    return attempt

                logger.warning("[Webhooks] %s attempt %d/%d: HTTP %d",
                               wh.webhook_id[:12], attempt_num, wh.retry_count, resp.status_code)

            except Exception as exc:
                duration_ms = (time.time() - t0) * 1000
                error_msg = str(exc)[:200]
                attempt = DeliveryAttempt(
                    webhook_id=wh.webhook_id,
                    event_type=event_type,
                    payload=payload,
                    status="failed",
                    error_message=error_msg,
                    attempt_number=attempt_num,
                    duration_ms=round(duration_ms, 1),
                )
                logger.warning("[Webhooks] %s attempt %d/%d: %s",
                               wh.webhook_id[:12], attempt_num, wh.retry_count, error_msg)

            if attempt_num < wh.retry_count:
                time.sleep(2 ** attempt_num)  # Exponential backoff

        return attempt  # Last failed attempt


# ─── Global singleton ─────────────────────────────────────────────────

_registry = WebhookRegistry()
_dispatcher = WebhookDispatcher(_registry)


def get_registry() -> WebhookRegistry:
    return _registry


def get_dispatcher() -> WebhookDispatcher:
    return _dispatcher


def dispatch_event(event_type: str, payload: Dict[str, Any],
                   participant_id: Optional[str] = None) -> List[DeliveryAttempt]:
    """Convenience function to dispatch an event."""
    return _dispatcher.dispatch(event_type, payload, participant_id)
