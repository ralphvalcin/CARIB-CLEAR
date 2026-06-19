"""JARVIS macOS Menu Bar App — rumps-powered status indicator and controls.

Requirements:
    pip install rumps

Usage:
    python -m jarvis.menu_bar.app

Features:
    - Status icon (🟢 idle, 🟠 approvals, 🟡 drift, 🔴 down, 🎤 voice active)
    - Start/Stop voice loop
    - Open dashboard in browser
    - Quick drift check
    - View system status
    - Background daemon mode (optional --background)
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
import webbrowser
from typing import Any, Optional

import rumps

from jarvis.menu_bar.status import JarvisStatus, StatusMonitor

logger = logging.getLogger("jarvis.menu_bar.app")

POLL_INTERVAL = 5  # seconds between status refreshes


class JarvisMenuBarApp(rumps.App):
    """macOS menu bar application for JARVIS control."""

    def __init__(self, api_url: str = "http://localhost:8000") -> None:
        super().__init__("JARVIS", title="🟢", quit_button=None)

        self.api_url = api_url
        self.monitor = StatusMonitor(api_url=api_url)
        self._polling = False
        self._poll_thread: Optional[threading.Thread] = None

        # ── Build menu ────────────────────────────────────────────────────
        self.status_item = rumps.MenuItem("🔄 Loading...", callback=None)
        self.menu = [
            self.status_item,
            None,  # separator
            rumps.MenuItem("🎤 Start Voice", callback=self._toggle_voice),
            rumps.MenuItem("⏹ Stop Voice", callback=self._toggle_voice),
            None,
            rumps.MenuItem("📊 Open Dashboard", callback=self._open_dashboard),
            rumps.MenuItem("📋 View Approvals", callback=self._open_approvals),
            None,
            rumps.MenuItem("🔍 Check Drift", callback=self._check_drift),
            rumps.MenuItem("📈 Status Details", callback=self._show_status),
            None,
            rumps.MenuItem("❌ Quit", callback=self._quit),
        ]

        # Start polling thread
        self._start_polling()

    # ── Polling ────────────────────────────────────────────────────────────

    def _start_polling(self) -> None:
        """Start background polling for status updates."""
        self._polling = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="jarvis-menu-poll",
        )
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        """Background loop: refresh status and update UI."""
        while self._polling:
            try:
                status = self.monitor.refresh()
                self._update_ui(status)
            except Exception as exc:
                logger.error("Poll error: %s", exc)
            time.sleep(POLL_INTERVAL)

    def _update_ui(self, status: JarvisStatus) -> None:
        """Update the menu bar icon and status text."""
        self.title = status.icon
        self.status_item.title = status.summary

    # ── Voice control ─────────────────────────────────────────────────────

    def _toggle_voice(self, sender: rumps.MenuItem) -> None:
        """Start or stop the JARVIS voice loop."""
        try:
            current = self.monitor._last_status
            if current.voice_running:
                self._stop_voice()
            else:
                self._start_voice()
        except Exception as exc:
            rumps.notification(
                "JARVIS",
                "Voice Control",
                f"Failed: {exc}",
            )

    def _start_voice(self) -> None:
        """Launch JARVIS voice loop in background."""
        try:
            script_path = str(
                (__import__("pathlib").Path(__file__).resolve().parent.parent.parent)
                / "run_voice.py"
            )
            subprocess.Popen(
                [sys.executable, script_path, "--wake", "--once"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            rumps.notification(
                "JARVIS",
                "Voice Started",
                "Say 'Hey JARVIS' to activate",
            )
            # Force immediate refresh
            self.monitor.refresh(force=True)
        except Exception as exc:
            logger.error("Failed to start voice: %s", exc)
            rumps.notification("JARVIS", "Voice Error", str(exc))

    def _stop_voice(self) -> None:
        """Stop the JARVIS voice loop."""
        try:
            from jarvis.voice.core import KILL_FILE_PATH

            KILL_FILE_PATH.touch()
            rumps.notification("JARVIS", "Voice Stopped", "Voice loop shutting down")
            self.monitor.refresh(force=True)
        except Exception as exc:
            logger.error("Failed to stop voice: %s", exc)
            rumps.notification("JARVIS", "Voice Error", str(exc))

    # ── Dashboard ─────────────────────────────────────────────────────────

    def _open_dashboard(self, _: Any = None) -> None:
        """Open JARVIS dashboard in default browser."""
        webbrowser.open(f"{self.api_url}/dashboard")

    def _open_approvals(self, _: Any = None) -> None:
        """Open approvals section of dashboard."""
        webbrowser.open(f"{self.api_url}/dashboard")

    # ── Drift & Status ────────────────────────────────────────────────────

    def _check_drift(self, _: Any = None) -> None:
        """Run a drift check and notify result."""
        try:
            import urllib.request

            body = b'{"session_id": "menu-bar", "text": "run drift check"}'
            req = urllib.request.Request(
                f"{self.api_url}/control/ingest",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = __import__("json").loads(resp.read().decode())

            report = result.get("drift_report", {})
            missing = report.get("missing", [])
            if missing:
                msg = f"⚠️ {len(missing)} capabilities drifted"
                # Check if auto-repair happened
                repair = result.get("auto_repair")
                if repair and repair.get("success_count", 0) > 0:
                    msg += f" — {repair['success_count']} repaired"
                    recheck = result.get("recheck", {})
                    if recheck and not recheck.get("missing"):
                        msg += " ✅ All fixed!"
                rumps.notification("JARVIS", "Drift Check", msg)
            else:
                rumps.notification("JARVIS", "Drift Check", "✅ All capabilities in sync")
            self.monitor.refresh(force=True)
        except Exception as exc:
            rumps.notification("JARVIS", "Drift Check Error", str(exc))

    def _show_status(self, _: Any = None) -> None:
        """Show detailed status as a notification."""
        status = self.monitor.refresh(force=True)

        lines = [
            f"{status.icon} JARVIS Status",
            f"API: {'✅ Up' if status.api_healthy else '❌ Down'}",
            f"Voice: {'🎤 Running' if status.voice_running else '⏸ Stopped'}",
            f"Approvals: {status.approvals_pending} pending",
            f"Drift: {status.drift_missing} missing",
            f"Capabilities: {status.capability_count}",
        ]
        rumps.notification(
            "JARVIS",
            "System Status",
            "\n".join(lines),
        )

    # ── Quit ──────────────────────────────────────────────────────────────

    def _quit(self, _: Any = None) -> None:
        """Clean shutdown."""
        self._polling = False
        rumps.quit_application()


def main() -> None:
    """Launch the JARVIS menu bar application."""
    import argparse

    parser = argparse.ArgumentParser(description="JARVIS Menu Bar App")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="JARVIS API URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    app = JarvisMenuBarApp(api_url=args.api_url)
    app.run()


if __name__ == "__main__":
    main()