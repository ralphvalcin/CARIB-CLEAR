"""Notification event types and rules engine for JARVIS.

Defines:
- NotificationEvent — typed events (approval_pending, drift_detected, health_report, etc.)
- NotificationRule — when an event triggers which channels
- RulesEngine — evaluates events against rules and dispatch
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis.notifications.events")


class EventType(str, Enum):
    """Types of events that can trigger notifications."""

    APPROVAL_PENDING = "approval_pending"
    DRIFT_DETECTED = "drift_detected"
    DRIFT_FIXED = "drift_fixed"
    HEALTH_REPORT = "health_report"
    VOICE_ERROR = "voice_error"
    SYSTEM_STARTUP = "system_startup"
    SYSTEM_SHUTDOWN = "system_shutdown"
    RUNTIME_ERROR = "runtime_error"


SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2, "debug": 3}


@dataclass
class NotificationEvent:
    """A notification-worthy event."""

    type: EventType
    title: str
    message: str
    severity: str = "info"  # critical, warning, info, debug
    payload: Dict[str, Any] = field(default_factory=dict)
    source: str = "jarvis"

    def formatted(self) -> str:
        """Human-readable one-liner."""
        return f"[{self.type.value}] {self.title}: {self.message}"


@dataclass
class NotificationRule:
    """When an event matches, dispatch to named channels.

    A rule can filter by event type, minimum severity, or custom check.
    """

    event_types: List[EventType]
    channels: List[str]  # channel names: "console", "notification_center", "telegram"
    min_severity: str = "info"
    enabled: bool = True

    def matches(self, event: NotificationEvent) -> bool:
        """Check if this rule applies to the given event."""
        if not self.enabled:
            return False
        if event.type not in self.event_types:
            return False
        event_sev = SEVERITY_ORDER.get(event.severity, 2)
        rule_sev = SEVERITY_ORDER.get(self.min_severity, 2)
        return event_sev <= rule_sev  # lower number = more severe


# ── Default rules ─────────────────────────────────────────────────────────────

_DEFAULT_RULES = [
    NotificationRule(
        event_types=[EventType.APPROVAL_PENDING],
        channels=["notification_center"],
        min_severity="info",
    ),
    NotificationRule(
        event_types=[EventType.DRIFT_DETECTED, EventType.RUNTIME_ERROR],
        channels=["notification_center"],
        min_severity="warning",
    ),
    NotificationRule(
        event_types=[EventType.HEALTH_REPORT],
        channels=["notification_center"],
        min_severity="info",
    ),
    NotificationRule(
        event_types=[EventType.VOICE_ERROR],
        channels=["notification_center"],
        min_severity="warning",
    ),
]


class RulesEngine:
    """Evaluates events against rules and dispatches to channels."""

    def __init__(self, rules: Optional[List[NotificationRule]] = None) -> None:
        self.rules = rules or list(_DEFAULT_RULES)

    def evaluate(self, event: NotificationEvent) -> List[str]:
        """Return list of channel names to dispatch to."""
        return [ch for rule in self.rules for ch in rule.channels if rule.matches(event)]