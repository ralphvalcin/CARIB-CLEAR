"""Tests for policy engine and drift checker."""

from jarvis.runtime.policy import DefaultPolicyEngine
from jarvis.knowledge.drift_checker import DriftChecker, HermesCapabilitySource


def test_policy_allow_and_approval():
    p = DefaultPolicyEngine()
    assert p.evaluate("web_search", {}).decision == "allow"
    assert p.evaluate("write_file", {}).decision == "require_approval"


def test_drift_checker_reports_zero_drift():
    """With the real Hermes capability source, all expected caps should be present."""
    checker = DriftChecker(HermesCapabilitySource())
    report = checker.run()
    assert len(report.missing) == 0, f"Missing capabilities: {report.missing}"
    assert len(report.unexpected) == 0, f"Unexpected capabilities: {report.unexpected}"