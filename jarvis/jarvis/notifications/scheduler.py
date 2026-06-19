"""Scheduled notifications and event-driven triggers for JARVIS.

Features:
- Periodic health reports (every N hours)
- Event-driven triggers (approval pending, drift detected)
- Configurable channel routing
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from jarvis.notifications.channels import (
    ConsoleChannel,
    MacOSNotificationChannel,
    NotificationChannel,
    TelegramChannel,
)
from jarvis.notifications.events import (
    EventType,
    NotificationEvent,
    RulesEngine,
)

logger = logging.getLogger("jarvis.notifications.scheduler")


class NotificationService:
    """Central notification service — schedule reports, fire events, manage channels.

    Usage:
        svc = NotificationService()
        svc.add_channel(MacOSNotificationChannel())
        svc.add_channel(TelegramChannel())
        svc.fire("approval_pending", "Approval Needed", "3 actions pending")
        svc.start_health_reports(jarvis_app, interval_hours=24)
    """

    def __init__(self, rules_engine: Optional[RulesEngine] = None) -> None:
        self.channels: Dict[str, NotificationChannel] = {}
        self.rules = rules_engine or RulesEngine()
        self._health_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Register default channels
        self._add_default_channels()

    def _add_default_channels(self) -> None:
        """Register built-in channels."""
        self.register_channel(ConsoleChannel())
        self.register_channel(MacOSNotificationChannel())

    def register_channel(self, channel: NotificationChannel) -> None:
        """Add a notification channel by name."""
        self.channels[channel.name] = channel

    def add_channel(self, channel: NotificationChannel) -> None:
        """Alias for register_channel."""
        self.register_channel(channel)

    def fire(
        self,
        event_type: str,
        title: str,
        message: str,
        severity: str = "info",
        payload: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Create an event and dispatch to matching channels.

        Returns count of successful deliveries.
        """
        try:
            etype = EventType(event_type)
        except ValueError:
            logger.warning("Unknown event type: %s", event_type)
            return 0

        event = NotificationEvent(
            type=etype,
            title=title,
            message=message,
            severity=severity,
            payload=payload or {},
        )

        channel_names = self.rules.evaluate(event)
        if not channel_names:
            logger.debug("No channel matched for event %s", event_type)
            return 0

        success_count = 0
        for name in channel_names:
            ch = self.channels.get(name)
            if ch is None:
                logger.warning("Channel '%s' not registered", name)
                continue
            if ch.send(event):
                success_count += 1

        return success_count

    def fire_event(self, event: NotificationEvent) -> int:
        """Fire a pre-built event object through the rules engine."""
        channel_names = self.rules.evaluate(event)
        if not channel_names:
            return 0

        success_count = 0
        for name in channel_names:
            ch = self.channels.get(name)
            if ch and ch.send(event):
                success_count += 1
        return success_count

    # ── Health reports ────────────────────────────────────────────────────────

    def start_health_reports(
        self,
        get_status: Callable[[], Dict[str, Any]],
        interval_hours: float = 24,
    ) -> None:
        """Start a background thread that sends periodic health reports."""
        if self._health_thread and self._health_thread.is_alive():
            logger.warning("Health report thread already running")
            return

        self._stop_event.clear()
        self._health_thread = threading.Thread(
            target=self._health_loop,
            args=(get_status, interval_hours),
            daemon=True,
            name="jarvis-health-reporter",
        )
        self._health_thread.start()
        logger.info(
            "Health reports started (every %.1f hours)", interval_hours
        )

    def stop_health_reports(self) -> None:
        """Stop the periodic health report thread."""
        self._stop_event.set()
        logger.info("Health reports stopped")

    def _health_loop(
        self,
        get_status: Callable[[], Dict[str, Any]],
        interval_hours: float,
    ) -> None:
        """Background loop: fetch status and send health report."""
        interval_seconds = interval_hours * 3600
        # First report after 30 seconds (don't fire immediately on startup)
        if not self._stop_event.wait(30):
            self._send_health_report(get_status())

        while not self._stop_event.wait(interval_seconds):
            try:
                status = get_status()
                self._send_health_report(status)
            except Exception as exc:
                logger.error("Health report failed: %s", exc)

    def send_immediate_health_report(
        self, status: Dict[str, Any]
    ) -> int:
        """Send a health report right now. Returns delivery count."""
        return self._send_health_report(status)

    def _send_health_report(self, status: Dict[str, Any]) -> int:
        """Format and fire a health report event."""
        ap = status.get("approvals_pending", 0)
        drift_count = len(status.get("drift_missing", []))

        parts = [
            f"🟢 API: {status.get('api', 'unknown')}",
            f"📋 Pending approvals: {ap}",
        ]

        if drift_count > 0:
            parts.append(f"⚠️ Drift: {drift_count} capabilities drifted")
        else:
            parts.append("✅ Drift: in sync")

        caps = status.get("capability_count", 0)
        parts.append(f"🧠 Capabilities: {caps}")

        voice = status.get("voice_running", False)
        parts.append(f"🎤 Voice: {'ON' if voice else 'OFF'}")

        message = " · ".join(parts)

        event = NotificationEvent(
            type=EventType.HEALTH_REPORT,
            title="JARVIS Health Report",
            message=message,
            severity="info",
            payload=status,
        )
        return self.fire_event(event)