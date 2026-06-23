"""Tests for ComplianceAgent — multi-jurisdiction KYC/AML/sanctions checks."""

from __future__ import annotations

from carib_clear.agents.compliance import (
    ComplianceAgent,
    ComplianceCheckResult,
    ComplianceProfile,
    JURISDICTION_RULES,
)


def test_jurisdiction_rules_all_defined() -> None:
    """Verify all 5 CARICOM jurisdictions have rules defined."""
    for jur in ["JM", "BB", "TT", "HT", "ECCB"]:
        assert jur in JURISDICTION_RULES
        assert "regulator" in JURISDICTION_RULES[jur]
        assert "kyc_required" in JURISDICTION_RULES[jur]
        assert "kyc_tier_limits" in JURISDICTION_RULES[jur]


def test_get_jurisdiction_rules_known() -> None:
    """Verify known jurisdiction returns correct rules."""
    agent = ComplianceAgent()
    rules = agent.get_jurisdiction_rules("JM")
    assert rules["regulator"] == "Bank of Jamaica"
    assert "national_id" in rules["kyc_required"]


def test_get_jurisdiction_rules_unknown() -> None:
    """Verify unknown jurisdiction falls back to JM defaults."""
    agent = ComplianceAgent()
    rules = agent.get_jurisdiction_rules("XYZ")
    assert rules["regulator"] == "Bank of Jamaica"


def test_get_jurisdiction_rules_case_insensitive() -> None:
    """Verify jurisdiction lookup is case-insensitive."""
    agent = ComplianceAgent()
    rules = agent.get_jurisdiction_rules("jm")
    assert rules["regulator"] == "Bank of Jamaica"


def test_compliance_profile_defaults() -> None:
    """Verify ComplianceProfile dataclass defaults."""
    profile = ComplianceProfile(
        participant_id="test_001",
        jurisdiction="BB",
        kyc_status="verified",
        kyc_tier=2,
    )
    assert profile.aml_risk_score == 0.0
    assert profile.sanctions_cleared is True
    assert profile.pep_status is False
    assert profile.restrictions == []


def test_compliance_check_result() -> None:
    """Verify ComplianceCheckResult dataclass."""
    result = ComplianceCheckResult(
        check_id="test-check-001",
        participant_id="test_001",
        check_type="kyc",
        passed=True,
        score=0.95,
        details={"documents_verified": 3},
    )
    assert result.passed is True
    assert result.score == 0.95
    assert result.requires_review is False


def test_onboard_participant_success_jm() -> None:
    """Verify successful KYC onboarding for Jamaica."""
    agent = ComplianceAgent()
    result = agent.onboard_participant(
        participant_id="jm_business_001",
        jurisdiction="JM",
        kyc_documents={
            "tax_compliance_certificate": "filed",
            "national_id": "verified",
            "proof_of_address": "verified",
            "trn": "verified",
        },
    )
    assert result.passed is True
    assert result.check_type == "kyc"
    assert result.score >= 0.7
    assert result.requires_review is False


def test_onboard_participant_success_ht() -> None:
    """Verify successful KYC onboarding for Haiti (different doc requirements)."""
    agent = ComplianceAgent()
    result = agent.onboard_participant(
        participant_id="ht_artisan_001",
        jurisdiction="HT",
        kyc_documents={
            "national_id": "verified",
            "proof_of_address": "verified",
            "nif_certificate": "verified",
        },
    )
    assert result.passed is True
    assert agent.profiles["ht_artisan_001"].kyc_status == "verified"


def test_onboard_participant_missing_docs_jm() -> None:
    """Verify KYC fails when Jamaica-required documents are missing."""
    agent = ComplianceAgent()
    result = agent.onboard_participant(
        participant_id="incomplete_jm",
        jurisdiction="JM",
        kyc_documents={
            "national_id": "verified",
            # Missing: tax_compliance_certificate, proof_of_address, trn
        },
    )
    assert result.passed is False
    missing = result.details.get("missing_documents", [])
    assert len(missing) > 0
    assert "tax_compliance_certificate" in missing


def test_onboard_participant_all_jurisdictions() -> None:
    """Verify onboarding succeeds for all 5 CARICOM jurisdictions."""
    agent = ComplianceAgent()
    doc_sets = {
        "JM": {"tax_compliance_certificate": "f", "national_id": "f", "proof_of_address": "f", "trn": "f"},
        "BB": {"tax_clearance_certificate": "f", "national_id": "f", "proof_of_address": "f"},
        "TT": {"national_id": "f", "proof_of_address": "f", "bir_clearance_certificate": "f"},
        "HT": {"national_id": "f", "proof_of_address": "f", "nif_certificate": "f"},
        "ECCB": {"national_id": "f", "proof_of_address": "f", "tax_compliance_certificate": "f"},
    }
    for jur, docs in doc_sets.items():
        result = agent.onboard_participant(f"test_{jur}", jur, docs)
        assert result.passed is True, f"Onboarding failed for {jur}: {result.details}"


def test_update_kyc_adds_documents() -> None:
    """Verify updating KYC adds new documents and re-verifies."""
    agent = ComplianceAgent()
    agent.onboard_participant(
        "test_update", "JM",
        {"national_id": "verified"},
        kyc_tier=1,
    )
    result = agent.update_kyc("test_update", {
        "tax_compliance_certificate": "filed",
        "proof_of_address": "verified",
        "trn": "verified",
    })
    assert result.passed is True
    assert result.check_type == "kyc"


def test_update_kyc_unknown_participant() -> None:
    """Verify updating KYC for unknown participant returns failure."""
    agent = ComplianceAgent()
    result = agent.update_kyc("unknown", {"national_id": "verified"})
    assert result.passed is False


def test_screen_transaction_clean() -> None:
    """Verify a clean transaction passes all checks."""
    agent = ComplianceAgent()
    # Pre-onboard both participants
    agent.onboard_participant(
        "sender_clean", "BB",
        {"tax_clearance_certificate": "v", "national_id": "v", "proof_of_address": "v"},
    )
    agent.onboard_participant(
        "receiver_clean", "JM",
        {"tax_compliance_certificate": "v", "national_id": "v", "proof_of_address": "v", "trn": "v"},
    )

    result = agent.screen_transaction(
        transaction_id="tx-clean-001",
        from_participant="sender_clean",
        to_participant="receiver_clean",
        amount_usd=5000,
        currency="BBD",
        from_jurisdiction="BB",
        to_jurisdiction="JM",
        purpose="trade",
    )
    assert result.passed is True
    assert result.score >= 0.5


def test_screen_transaction_unonboarded() -> None:
    """Verify transaction with unonboarded participant is flagged for review."""
    agent = ComplianceAgent()
    result = agent.screen_transaction(
        transaction_id="tx-unreg-001",
        from_participant="unknown_sender",
        to_participant="unknown_receiver",
        amount_usd=5000,
        currency="BBD",
        from_jurisdiction="BB",
        to_jurisdiction="JM",
        purpose="trade",
    )
    assert result.requires_review is True  # Flagged, not auto-blocked
    issues = result.details.get("issues", [])
    assert "from_participant_not_onboarded" in issues


def test_screen_transaction_exceeds_tier() -> None:
    """Verify transaction exceeding KYC tier limit is flagged."""
    agent = ComplianceAgent()
    agent.onboard_participant(
        "low_tier_user", "JM",
        {"tax_compliance_certificate": "v", "national_id": "v", "proof_of_address": "v", "trn": "v"},
        kyc_tier=1,  # Tier 1 limit: 50,000 JMD
    )
    agent.onboard_participant(
        "high_tier_receiver", "JM",
        {"tax_compliance_certificate": "v", "national_id": "v", "proof_of_address": "v", "trn": "v"},
        kyc_tier=3,
    )
    result = agent.screen_transaction(
        transaction_id="tx-tier-exceed",
        from_participant="low_tier_user",
        to_participant="high_tier_receiver",
        amount_usd=100000,  # Way over tier 1 limit
        currency="JMD",
        from_jurisdiction="JM",
        to_jurisdiction="JM",
        purpose="trade",
    )
    # Might still pass (it's only a flag, not a block) but should flag tier issue
    tier_issues = [i for i in result.details.get("issues", []) if "tier" in i]
    assert len(tier_issues) > 0 or result.requires_review is True


def test_sanctions_screening_detects_blocked() -> None:
    """Verify sanctions keywords are detected."""
    agent = ComplianceAgent()
    assert agent._screen_sanctions("specially designated national entity") is True
    assert agent._screen_sanctions("blocked person") is True
    assert agent._screen_sanctions("terrorist organization") is True


def test_sanctions_screening_clean() -> None:
    """Verify clean names pass sanctions screening."""
    agent = ComplianceAgent()
    assert agent._screen_sanctions("Bob's Bakery") is False
    assert agent._screen_sanctions("Port-au-Prince Trading Co") is False
    assert agent._screen_sanctions("Kingston Wholesale Ltd") is False


def test_pep_screening_detects() -> None:
    """Verify PEP keywords are detected."""
    agent = ComplianceAgent()
    assert agent._screen_pep("Minister of Finance") is True
    assert agent._screen_pep("President of the Senate") is True
    assert agent._screen_pep("Deputy Governor") is True


def test_pep_screening_clean() -> None:
    """Verify non-PEP names pass screening."""
    agent = ComplianceAgent()
    assert agent._screen_pep("Jane's Art Shop") is False
    assert agent._screen_pep("Carlos Auto Repair") is False


def test_anomaly_detection_high_amount() -> None:
    """Verify very high amounts increase anomaly score."""
    agent = ComplianceAgent()
    score = agent._detect_anomaly("sender", "receiver", 1500000, "trade")
    assert score >= 0.5  # Should be significant


def test_anomaly_detection_low_amount() -> None:
    """Verify normal amounts have low anomaly score."""
    agent = ComplianceAgent()
    score = agent._detect_anomaly("sender", "receiver", 500, "trade")
    assert score < 0.3


def test_anomaly_detection_unusual_purpose() -> None:
    """Verify unusual transaction purposes increase anomaly score."""
    agent = ComplianceAgent()
    score = agent._detect_anomaly("sender", "receiver", 10000, "charity_donation")
    trade_score = agent._detect_anomaly("sender", "receiver", 10000, "trade")
    assert score > trade_score


def test_periodic_sanctions_screening() -> None:
    """Verify periodic screening runs without crashing."""
    agent = ComplianceAgent()
    agent.onboard_participant(
        "test_periodic", "BB",
        {"tax_clearance_certificate": "v", "national_id": "v", "proof_of_address": "v"},
    )
    results = agent.run_periodic_sanctions_screening()
    assert isinstance(results, list)


def test_ctr_report() -> None:
    """Verify Currency Transaction Report generation."""
    agent = ComplianceAgent()
    agent.onboard_participant(
        "ctr_test", "JM",
        {"tax_compliance_certificate": "v", "national_id": "v", "proof_of_address": "v", "trn": "v"},
    )
    report = agent.generate_ctr_report("ctr_test", "2026-01-01", "2026-06-01")
    assert "report_type" in report
    assert report["participant_id"] == "ctr_test"


def test_ctr_report_unknown_participant() -> None:
    """Verify CTR report for unknown participant returns error."""
    agent = ComplianceAgent()
    report = agent.generate_ctr_report("unknown", "2026-01-01", "2026-06-01")
    assert "error" in report


def test_sar_report() -> None:
    """Verify Suspicious Activity Report generation."""
    agent = ComplianceAgent()
    agent.onboard_participant(
        "sar_test", "BB",
        {"tax_clearance_certificate": "v", "national_id": "v", "proof_of_address": "v"},
    )
    result = agent.screen_transaction(
        transaction_id="tx-sar-001",
        from_participant="sar_test",
        to_participant="sar_test",
        amount_usd=50000,
        currency="BBD",
        from_jurisdiction="BB",
        to_jurisdiction="BB",
        purpose="trade",
    )
    report = agent.generate_sar_report(result.check_id)
    assert report is not None
    assert report["report_type"] == "SAR"


def test_sar_report_unknown_check() -> None:
    """Verify SAR report for unknown check returns None."""
    agent = ComplianceAgent()
    report = agent.generate_sar_report("nonexistent-check-id")
    assert report is None


def test_usd_to_local_rate() -> None:
    """Verify currency conversion rates."""
    agent = ComplianceAgent()
    assert agent._get_usd_to_local_rate("JMD") == 154
    assert agent._get_usd_to_local_rate("BBD") == 2
    assert agent._get_usd_to_local_rate("USD") == 1.0
    assert agent._get_usd_to_local_rate("EUR") == 1.0  # Unknown currency


def test_profile_stored_after_onboarding() -> None:
    """Verify profile is stored and accessible after onboarding."""
    agent = ComplianceAgent()
    agent.onboard_participant(
        "stored_test", "TT",
        {"national_id": "v", "proof_of_address": "v", "bir_clearance_certificate": "v"},
    )
    assert "stored_test" in agent.profiles
    assert agent.profiles["stored_test"].jurisdiction == "TT"
    assert agent.profiles["stored_test"].kyc_status == "verified"


def test_sanctions_in_transaction_screening() -> None:
    """Verify sanctions names are caught in transaction screening."""
    agent = ComplianceAgent()
    agent.onboard_participant(
        "sanctioned_sender", "BB",
        {"tax_clearance_certificate": "v", "national_id": "v", "proof_of_address": "v"},
    )
    result = agent.screen_transaction(
        transaction_id="tx-sanctioned",
        from_participant="sanctioned_sender",
        to_participant="specially designated national",  # Triggers sanctions
        amount_usd=1000,
        currency="BBD",
        from_jurisdiction="BB",
        to_jurisdiction="BB",
        purpose="trade",
    )
    # Should flag sanctions
    issues = result.details.get("issues", [])
    assert "sanctions" in str(issues).lower() or result.requires_review is True