"""Status monitor for JARVIS — polls the API for consolidated status."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("jarvis.menu_bar.status")


@dataclass
class JarvisStatus:
    """Current state of the JARVIS system."""

    api_healthy: bool = False
    voice_running: bool = False
    approvals_pending: int = 0
    drift_missing: int = 0
    capability_count: int = 0
    last_checked: float = 0.0

    @property
    def icon(self) -> str:
        """Return an emoji representing the overall status."""
        if not self.api_healthy:
            return "🔴"
        if self.drift_missing > 0:
            return "🟡"
        if self.approvals_pending > 0:
            return "🟠"
        if self.voice_running:
            return "🎤"
        return "🟢"

    @property
    def summary(self) -> str:
        """Short one-line status description."""
        if not self.api_healthy:
            return "🔴 API Unreachable"
        parts = []
        if self.voice_running:
            parts.append("🎤 Voice ON")
        if self.approvals_pending:
            parts.append(f"📋 {self.approvals_pending} pending")
        if self.drift_missing:
            parts.append(f"⚠️ {self.drift_missing} drifted")
        if not parts:
            parts.append(f"✅ {self.capability_count} caps")
        return " · ".join(parts)


class StatusMonitor:
    """Polls the JARVIS API for consolidated system status.

    Caches results for a configurable interval to avoid hammering the API.
    """

    def __init__(self, api_url: str = "http://localhost:8000", poll_interval: float = 5.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.poll_interval = poll_interval
        self._last_status: JarvisStatus = JarvisStatus()
        self._last_poll: float = 0.0

    def _request(self, path: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
        """Make a GET request to the API. Returns parsed JSON or None."""
        try:
            req = Request(f"{self.api_url}{path}", method="GET")
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            logger.debug("API request to %s failed: %s", path, exc)
            return None

    def refresh(self, force: bool = False) -> JarvisStatus:
        """Poll the API and return current status.

        Uses cached value if within poll_interval (unless force=True).
        """
        now = time.time()
        if not force and (now - self._last_poll) < self.poll_interval:
            return self._last_status

        self._last_poll = now

        # Health check
        health = self._request("/health")
        if health is None:
            self._last_status = JarvisStatus(api_healthy=False, last_checked=now)
            return self._last_status

        # Approval metrics
        metrics = self._request("/control/metrics")
        approvals_pending = 0
        if metrics and metrics.get("ok"):
            approvals_pending = metrics["metrics"].get("pending", 0)

        # Drift status
        knowledge = self._request("/knowledge/self")
        drift_missing = 0
        capability_count = 0
        if knowledge:
            drift = knowledge.get("drift", {})
            drift_missing = len(drift.get("missing", []))
            capability_count = knowledge.get("capability_count", 0)

        # Voice status (check via PID file or voice log endpoint availability)
        voice_running = self._check_voice_running()

        self._last_status = JarvisStatus(
            api_healthy=True,
            voice_running=voice_running,
            approvals_pending=approvals_pending,
            drift_missing=drift_missing,
            capability_count=capability_count,
            last_checked=now,
        )
        return self._last_status

    def _check_voice_running(self) -> bool:
        """Check if the JARVIS voice loop is running.

        Uses the kill-switch file as an indicator: if the guard is active
        but kill file doesn't exist, the voice loop is likely running.
        """
        from pathlib import Path
        guard = Path.home() / ".jarvis_voice_guard"
        kill = Path.home() / ".jarvis_voice_kill"
        if guard.exists() and not kill.exists():
            return True
        return False