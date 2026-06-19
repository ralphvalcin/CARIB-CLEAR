"""Notification channels for JARVIS: Telegram, macOS Notification Center, console."""

from __future__ import annotations

import abc
import logging
import shlex
import subprocess
from typing import Optional

from jarvis.notifications.events import NotificationEvent

logger = logging.getLogger("jarvis.notifications.channels")


class NotificationChannel(abc.ABC):
    """Base class for a notification delivery channel."""

    name: str = "base"

    @abc.abstractmethod
    def send(self, event: NotificationEvent) -> bool:
        """Deliver a notification. Return True if sent successfully."""
        ...


# ── Console ──────────────────────────────────────────────────────────────────


class ConsoleChannel(NotificationChannel):
    """Log notification to console/stdout. Useful for testing."""

    name = "console"

    def send(self, event: NotificationEvent) -> bool:
        line = event.formatted()
        logger.info("NOTIFY [console] %s", line)
        return True


# ── macOS Notification Center ────────────────────────────────────────────────


class MacOSNotificationChannel(NotificationChannel):
    """Deliver notifications via macOS Notification Center using osascript."""

    name = "notification_center"

    def __init__(self, subtitle: Optional[str] = None) -> None:
        self.subtitle = subtitle or "JARVIS"

    def send(self, event: NotificationEvent) -> bool:
        try:
            # Escape for AppleScript string literals
            safe_title = event.title.replace('"', '\\"').replace("\n", " ")
            safe_msg = event.message.replace('"', '\\"').replace("\n", " ")
            safe_sub = self.subtitle.replace('"', '\\"')

            script = (
                f'display notification "{safe_msg}" '
                f'with title "{safe_title}" '
                f'subtitle "{safe_sub}"'
            )
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5,
            )
            logger.debug("MacOS notification sent: %s", event.title)
            return True
        except Exception as exc:
            logger.warning("Failed to send macOS notification: %s", exc)
            return False


# ── Telegram ─────────────────────────────────────────────────────────────────


class TelegramChannel(NotificationChannel):
    """Send notifications via Hermes CLI (which routes through Telegram).

    Falls back gracefully if `hermes` binary is not available.
    """

    name = "telegram"

    def __init__(self, hermes_binary: str = "hermes") -> None:
        self.hermes_binary = hermes_binary

    def send(self, event: NotificationEvent) -> bool:
        try:
            msg = shlex.quote(event.formatted())
            result = subprocess.run(
                [self.hermes_binary, "send", msg],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.info("Telegram notification sent: %s", event.title)
                return True
            logger.warning(
                "Telegram notification failed (exit %d): %s",
                result.returncode,
                result.stderr[:200],
            )
            return False
        except FileNotFoundError:
            logger.warning("Hermes CLI not found — Telegram channel unavailable")
            return False
        except Exception as exc:
            logger.warning("Telegram notification error: %s", exc)
            return False