"""Tests for DriftRepairer."""

from jarvis.knowledge.drift_checker import DriftReport
from jarvis.knowledge.drift_repairer import DriftRepairer, RepairResult


def test_repair_empty_report():
    """Empty report should result in zero repair attempts."""
    report = DriftReport(missing=[], stale=[], unexpected=[], checked_at=0.0)
    repairer = DriftRepairer(dry_run=True)
    result = repairer.repair(report)
    assert result.total == 0
    assert result.ok


def test_repair_skips_unknown_skills():
    """Unknown capabilities should be attempted (dry-run won't fail)."""
    report = DriftReport(
        missing=["some_unknown_skill_xyz"],
        stale=[],
        unexpected=[],
        checked_at=0.0,
    )
    repairer = DriftRepairer(dry_run=True)
    result = repairer.repair(report)
    assert result.total == 1
    assert result.skipped_count == 1  # dry-run skips


def test_repair_hermes_skill_dry_run():
    """Dry-run should skip actual skill installation."""
    report = DriftReport(
        missing=["imessage"],
        stale=[],
        unexpected=[],
        checked_at=0.0,
    )
    repairer = DriftRepairer(dry_run=True)
    result = repairer.repair(report)
    assert result.skipped_count == 1
    detail = result.details[0]
    assert detail["status"] == "skipped"
    assert "dry-run" in detail["message"]


def test_can_repair_known_skill():
    repairer = DriftRepairer()
    assert repairer.can_repair("imessage")
    assert repairer.can_repair("github-code-review")


def test_cannot_repair_unknown():
    repairer = DriftRepairer()
    assert not repairer.can_repair("nonexistent_capability_xyz")
    # Built-in Hermes tools are not skills — not repairable via skill install
    assert not repairer.can_repair("web_search")


def test_repair_jarvis_module_dry_run():
    """JARVIS internal modules should be recognized as repairable."""
    repairer = DriftRepairer(dry_run=True)
    result_detail = repairer._repair_one("policy_gating")
    # Even in dry-run, policy_gating could be imported
    assert result_detail["status"] in ("skipped", "success")


def test_repair_result_properties():
    result = RepairResult(success_count=3, failure_count=1)
    assert not result.ok
    assert result.total == 4
    assert result.to_dict()["success_count"] == 3