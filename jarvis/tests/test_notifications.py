"""Tests for the JARVIS notification system and menu bar status monitor."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from jarvis.notifications.channels import (
    ConsoleChannel,
    MacOSNotificationChannel,
    NotificationChannel,
    TelegramChannel,
)
from jarvis.notifications.events import (
    EventType,
    NotificationEvent,
    NotificationRule,
    RulesEngine,
)
from jarvis.notifications.scheduler import NotificationService


# ═══════════════════════════════════════════════════════════════════════════════
# Events
# ═══════════════════════════════════════════════════════════════════════════════


class TestNotificationEvent:
    def test_creates_from_type(self) -> None:
        evt = NotificationEvent(
            type=EventType.APPROVAL_PENDING,
            title="Test",
            message="Something needs approval",
        )
        assert evt.type == EventType.APPROVAL_PENDING
        assert "Something needs approval" in evt.formatted()

    def test_all_event_types_render(self) -> None:
        for etype in EventType:
            evt = NotificationEvent(type=etype, title="T", message="M")
            assert len(evt.formatted()) > 0

    def test_default_severity_is_info(self) -> None:
        evt = NotificationEvent(type=EventType.DRIFT_DETECTED, title="T", message="M")
        assert evt.severity == "info"

    def test_severity_ordering(self) -> None:
        evt_info = NotificationEvent(type=EventType.HEALTH_REPORT, title="T", message="M", severity="info")
        evt_warn = NotificationEvent(type=EventType.DRIFT_DETECTED, title="T", message="M", severity="warning")
        evt_crit = NotificationEvent(type=EventType.RUNTIME_ERROR, title="T", message="M", severity="critical")
        assert evt_crit.severity != evt_info.severity


class TestNotificationRule:
    def test_matches_event_type(self) -> None:
        rule = NotificationRule(
            event_types=[EventType.APPROVAL_PENDING],
            channels=["notification_center"],
        )
        evt = NotificationEvent(type=EventType.APPROVAL_PENDING, title="T", message="M")
        assert rule.matches(evt)

    def test_does_not_match_different_type(self) -> None:
        rule = NotificationRule(
            event_types=[EventType.APPROVAL_PENDING],
            channels=["notification_center"],
        )
        evt = NotificationEvent(type=EventType.DRIFT_DETECTED, title="T", message="M")
        assert not rule.matches(evt)

    def test_disabled_rule_never_matches(self) -> None:
        rule = NotificationRule(
            event_types=[EventType.APPROVAL_PENDING],
            channels=["notification_center"],
            enabled=False,
        )
        evt = NotificationEvent(type=EventType.APPROVAL_PENDING, title="T", message="M")
        assert not rule.matches(evt)

    def test_severity_filter(self) -> None:
        # Rule accepts warning+ but event is info
        rule = NotificationRule(
            event_types=[EventType.APPROVAL_PENDING],
            channels=["notification_center"],
            min_severity="warning",
        )
        evt = NotificationEvent(type=EventType.APPROVAL_PENDING, title="T", message="M", severity="info")
        assert not rule.matches(evt)

    def test_severity_filter_passes_critical(self) -> None:
        rule = NotificationRule(
            event_types=[EventType.RUNTIME_ERROR],
            channels=["notification_center"],
            min_severity="warning",
        )
        evt = NotificationEvent(type=EventType.RUNTIME_ERROR, title="T", message="M", severity="critical")
        assert rule.matches(evt)


class TestRulesEngine:
    def test_returns_channel_names(self) -> None:
        rule = NotificationRule(
            event_types=[EventType.APPROVAL_PENDING],
            channels=["telegram", "notification_center"],
        )
        engine = RulesEngine(rules=[rule])
        evt = NotificationEvent(type=EventType.APPROVAL_PENDING, title="T", message="M")
        channels = engine.evaluate(evt)
        assert "telegram" in channels
        assert "notification_center" in channels

    def test_empty_when_no_match(self) -> None:
        rule = NotificationRule(
            event_types=[EventType.DRIFT_DETECTED],
            channels=["console"],
        )
        engine = RulesEngine(rules=[rule])
        evt = NotificationEvent(type=EventType.APPROVAL_PENDING, title="T", message="M")
        assert engine.evaluate(evt) == []


# ═══════════════════════════════════════════════════════════════════════════════
# Channels
# ═══════════════════════════════════════════════════════════════════════════════


class TestConsoleChannel:
    def test_send_returns_true(self) -> None:
        ch = ConsoleChannel()
        evt = NotificationEvent(type=EventType.HEALTH_REPORT, title="T", message="M")
        assert ch.send(evt) is True


class TestMacOSNotificationChannel:
    def test_send_returns_true_on_success(self) -> None:
        ch = MacOSNotificationChannel()
        evt = NotificationEvent(type=EventType.HEALTH_REPORT, title="Test Title", message="Test message")
        with patch("subprocess.run") as mock_run:
            mock = MagicMock()
            mock.returncode = 0
            mock_run.return_value = mock
            assert ch.send(evt) is True
            # Verify osascript was called
            args = mock_run.call_args[0][0]
            assert args[0] == "osascript"
            assert "display notification" in args[2]

    def test_send_returns_false_on_failure(self) -> None:
        ch = MacOSNotificationChannel()
        evt = NotificationEvent(type=EventType.HEALTH_REPORT, title="T", message="M")
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = RuntimeError("osascript failed")
            assert ch.send(evt) is False


class TestTelegramChannel:
    def test_send_returns_true(self) -> None:
        ch = TelegramChannel(hermes_binary="echo")
        evt = NotificationEvent(type=EventType.APPROVAL_PENDING, title="T", message="Test")
        with patch("subprocess.run") as mock_run:
            mock = MagicMock()
            mock.returncode = 0
            mock_run.return_value = mock
            assert ch.send(evt) is True

    def test_send_fallback_on_missing_binary(self) -> None:
        ch = TelegramChannel(hermes_binary="nonexistent_binary_xyz")
        evt = NotificationEvent(type=EventType.APPROVAL_PENDING, title="T", message="M")
        assert ch.send(evt) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Notification Service
# ═══════════════════════════════════════════════════════════════════════════════


class TestNotificationService:
    def test_fire_returns_count(self) -> None:
        svc = NotificationService()
        # Console channel should always succeed
        count = svc.fire(
            "approval_pending",
            "Approval Needed",
            "3 actions pending",
        )
        assert count >= 1  # console always delivers

    def test_fire_unknown_event_type_returns_zero(self) -> None:
        svc = NotificationService()
        count = svc.fire("imaginary_event", "T", "M")
        assert count == 0

    def test_fire_event_object(self) -> None:
        svc = NotificationService()
        evt = NotificationEvent(type=EventType.HEALTH_REPORT, title="T", message="M")
        count = svc.fire_event(evt)
        assert count >= 1  # console always delivers

    def test_register_custom_channel(self) -> None:
        svc = NotificationService()

        class FakeChannel(NotificationChannel):
            name = "fake"
            def __init__(self):
                self.sent = []
            def send(self, event):
                self.sent.append(event)
                return True

        fake = FakeChannel()
        svc.register_channel(fake)

        # Add rule that routes health_report to "fake"
        from jarvis.notifications.events import NotificationRule, EventType
        svc.rules.rules.append(
            NotificationRule(
                event_types=[EventType.HEALTH_REPORT],
                channels=["fake"],
                min_severity="info",
            )
        )

        count = svc.fire("health_report", "T", "M")
        assert count >= 1  # at least fake delivered
        assert len(fake.sent) == 1

    def test_custom_rules(self) -> None:
        rule = NotificationRule(
            event_types=[EventType.HEALTH_REPORT],
            channels=["console"],
            min_severity="info",
        )
        svc = NotificationService(rules_engine=RulesEngine(rules=[rule]))
        count = svc.fire("health_report", "T", "M")
        assert count >= 1

    def test_health_report_format(self) -> None:
        svc = NotificationService()
        status = {
            "api": "healthy",
            "approvals_pending": 2,
            "drift_missing": [],
            "capability_count": 235,
            "voice_running": True,
        }
        count = svc.send_immediate_health_report(status)
        assert count >= 1

    def test_health_report_shows_drift(self) -> None:
        svc = NotificationService()
        status = {
            "api": "healthy",
            "approvals_pending": 0,
            "drift_missing": ["voice_output"],
            "capability_count": 234,
            "voice_running": False,
        }
        count = svc.send_immediate_health_report(status)
        assert count >= 1

    def test_start_stop_health_reports(self) -> None:
        svc = NotificationService()
        svc.start_health_reports(get_status=lambda: {"api": "healthy"}, interval_hours=999)
        assert svc._health_thread is not None
        assert svc._health_thread.is_alive()
        svc.stop_health_reports()


# ═══════════════════════════════════════════════════════════════════════════════
# Status Monitor (menu bar)
# ═══════════════════════════════════════════════════════════════════════════════


class TestJarvisStatus:
    def test_icon_shows_green_when_healthy(self) -> None:
        from jarvis.menu_bar.status import JarvisStatus
        s = JarvisStatus(api_healthy=True)
        assert s.icon == "🟢"

    def test_icon_shows_red_when_down(self) -> None:
        from jarvis.menu_bar.status import JarvisStatus
        s = JarvisStatus(api_healthy=False)
        assert s.icon == "🔴"

    def test_icon_shows_microphone_when_voice_on(self) -> None:
        from jarvis.menu_bar.status import JarvisStatus
        s = JarvisStatus(api_healthy=True, voice_running=True)
        assert s.icon == "🎤"

    def test_icon_shows_yellow_when_drift(self) -> None:
        from jarvis.menu_bar.status import JarvisStatus
        s = JarvisStatus(api_healthy=True, drift_missing=3)
        assert s.icon == "🟡"

    def test_icon_shows_orange_when_approvals_pending(self) -> None:
        from jarvis.menu_bar.status import JarvisStatus
        s = JarvisStatus(api_healthy=True, approvals_pending=2, drift_missing=0)
        assert s.icon == "🟠"

    def test_summary_includes_voice(self) -> None:
        from jarvis.menu_bar.status import JarvisStatus
        s = JarvisStatus(api_healthy=True, voice_running=True)
        assert "Voice" in s.summary

    def test_summary_includes_approvals(self) -> None:
        from jarvis.menu_bar.status import JarvisStatus
        s = JarvisStatus(api_healthy=True, approvals_pending=3)
        assert "3" in s.summary

    def test_summary_includes_drift(self) -> None:
        from jarvis.menu_bar.status import JarvisStatus
        s = JarvisStatus(api_healthy=True, drift_missing=2)
        assert "2" in s.summary


class TestStatusMonitor:
    def test_initial_state(self) -> None:
        from jarvis.menu_bar.status import StatusMonitor
        m = StatusMonitor(api_url="http://localhost:0")
        s = m.refresh()
        assert s.api_healthy is False  # port 0 won't respond

    def test_caches_within_interval(self) -> None:
        from jarvis.menu_bar.status import StatusMonitor, JarvisStatus
        m = StatusMonitor(api_url="http://localhost:0")
        # First call fails (no server) → cached
        s1 = m.refresh()
        s2 = m.refresh()  # should use cache, not re-request
        assert s2.api_healthy == s1.api_healthy
        assert s2.last_checked == s1.last_checked