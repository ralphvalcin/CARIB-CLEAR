"""Tests for GovernanceAgent — FX settlement approval, MSME credit, HITL."""

from __future__ import annotations

import os

from carib_clear.governance.agent import (
    ComplianceCheck,
    GovernanceAgent,
    GovernanceDecision,
    _DEFAULT_THRESHOLDS,
    _JURISDICTION_RULES,
)


# ─── Data Models ──────────────────────────────────────────────────────────

def test_compliance_check_defaults() -> None:
    """Verify ComplianceCheck dataclass."""
    c = ComplianceCheck(
        check_type="kyc", jurisdiction="JM", passed=True, score=0.95,
        details={"doc": "verified"},
    )
    assert c.passed is True
    assert c.score == 0.95


def test_governance_decision_defaults() -> None:
    """Verify GovernanceDecision dataclass."""
    d = GovernanceDecision(
        approved=True, decision_type="fx_settlement",
        rationale="All checks passed", confidence=0.85,
    )
    assert d.approved is True
    assert d.decision_type == "fx_settlement"


# ─── Jurisdiction ─────────────────────────────────────────────────────────

def test_jurisdiction_rules_all_defined() -> None:
    """Verify all 5 jurisdictions have rules."""
    for jur in ["JM", "BB", "TT", "HT", "XCD"]:
        assert jur in _JURISDICTION_RULES
        assert "kyc_required_docs" in _JURISDICTION_RULES[jur]


def test_get_jurisdiction_rules_known() -> None:
    """Verify known jurisdiction returns correct rules."""
    agent = GovernanceAgent()
    rules = agent.get_jurisdiction_rules("BB")
    assert rules["central_bank"] == "Central Bank of Barbados"


def test_get_jurisdiction_rules_fallback() -> None:
    """Verify unknown jurisdiction falls back to JM."""
    agent = GovernanceAgent()
    rules = agent.get_jurisdiction_rules("ZZ")
    assert rules["central_bank"] == "Bank of Jamaica"



# ─── Thresholds ──────────────────────────────────────────────────────────

def test_default_thresholds_exist() -> None:
    """Verify all threshold sections exist."""
    for section in ["compliance", "fx_settlement", "msme_credit"]:
        assert section in _DEFAULT_THRESHOLDS


def test_agent_loads_defaults() -> None:
    """Verify agent initializes with default thresholds."""
    agent = GovernanceAgent()
    assert agent._thresholds is not None
    assert "fx_settlement" in agent._thresholds
    assert "msme_credit" in agent._thresholds
    assert agent._thresholds["fx_settlement"]["max_slippage_bps"] == 50


def test_hitl_disabled_by_default() -> None:
    """Verify HITL is disabled unless env var is set."""
    agent = GovernanceAgent()
    assert agent.hitl_enabled is False


# ─── KYC Check ───────────────────────────────────────────────────────────

def test_run_kyc_check_passes() -> None:
    """Verify KYC check passes with all required docs."""
    agent = GovernanceAgent()
    result = agent.run_kyc_check("HT", {"entity": "test"},
        {"national_id": "verified", "proof_of_address": "verified", "nif_cert": "verified"})
    assert result.passed is True
    assert result.check_type == "kyc"


def test_run_kyc_check_fails_missing_docs() -> None:
    """Verify KYC check fails with missing required docs."""
    agent = GovernanceAgent()
    result = agent.run_kyc_check("HT", {"entity": "test"}, {"national_id": "verified"})
    assert result.passed is False
    assert "nif_cert" in result.details.get("missing_docs", [])


# ─── AML Check ────────────────────────────────────────────────────────────

def test_run_aml_check_low_amount() -> None:
    """Verify AML check passes for small transactions."""
    agent = GovernanceAgent()
    result = agent.run_aml_check("JM", 500, {})
    assert result.passed is True
    assert result.score > 0.5


def test_run_aml_check_high_risk() -> None:
    """Verify AML check fails for high-risk profiles."""
    agent = GovernanceAgent()
    result = agent.run_aml_check("JM", 50000, {
        "is_pep": True, "sanctions_match": True, "adverse_media": True,
    })
    assert result.passed is False


# ─── Sanctions Check ─────────────────────────────────────────────────────

def test_run_sanctions_check() -> None:
    """Verify sanctions check returns clean."""
    agent = GovernanceAgent()
    result = agent.run_sanctions_check("HT", "haitian_artisan_001", "business")
    assert result.passed is True
    assert "OFAC" in result.details.get("lists_checked", [])


# ─── FX Settlement ─────────────────────────────────────────────────────

def test_fx_settlement_approves_good_params() -> None:
    """Verify FX settlement is approved with good parameters."""
    agent = GovernanceAgent()
    decision = agent.approve_fx_settlement(
        correlation_id="test-fx-1",
        from_currency="BBD", to_currency="JMD",
        amount_usd=15000, rate=76.5,
        slippage_bps=25, liquidity_usd=50000,
        settlement_rail="stellar_usdc", counterparty_jurisdiction="BB",
    )
    assert decision.decision_type == "fx_settlement"
    assert decision.approved is True


def test_fx_settlement_rejects_high_slippage() -> None:
    """Verify FX settlement is rejected when slippage exceeds max."""
    agent = GovernanceAgent()
    decision = agent.approve_fx_settlement(
        correlation_id="test-fx-slip",
        from_currency="BBD", to_currency="JMD",
        amount_usd=15000, rate=76.5,
        slippage_bps=100, liquidity_usd=50000,  # Slippage too high
        settlement_rail="stellar_usdc", counterparty_jurisdiction="BB",
    )
    assert decision.approved is False
    assert "slippage" in decision.rationale.lower()


def test_fx_settlement_rejects_low_liquidity() -> None:
    """Verify FX settlement is rejected when liquidity is insufficient."""
    agent = GovernanceAgent()
    decision = agent.approve_fx_settlement(
        correlation_id="test-fx-liq",
        from_currency="BBD", to_currency="JMD",
        amount_usd=15000, rate=76.5,
        slippage_bps=10, liquidity_usd=100,  # Liquidity too low
        settlement_rail="stellar_usdc", counterparty_jurisdiction="BB",
    )
    assert decision.approved is False
    assert "liquidity" in decision.rationale.lower()


def test_fx_settlement_confidence_calculation() -> None:
    """Verify confidence is calculated correctly."""
    agent = GovernanceAgent()
    decision = agent.approve_fx_settlement(
        correlation_id="test-fx-conf",
        from_currency="BBD", to_currency="JMD",
        amount_usd=15000, rate=76.5,
        slippage_bps=10, liquidity_usd=50000,
        settlement_rail="stellar_usdc", counterparty_jurisdiction="BB",
    )
    assert 0.0 <= decision.confidence <= 1.0
    assert decision.confidence > 0.5  # Good params = high confidence


def test_fx_settlement_includes_compliance_checks() -> None:
    """Verify FX settlement runs compliance checks."""
    agent = GovernanceAgent()
    decision = agent.approve_fx_settlement(
        correlation_id="test-fx-comp",
        from_currency="BBD", to_currency="JMD",
        amount_usd=15000, rate=76.5,
        slippage_bps=10, liquidity_usd=50000,
        settlement_rail="stellar_usdc", counterparty_jurisdiction="BB",
    )
    assert len(decision.compliance_checks) > 0
    check_types = {c.check_type for c in decision.compliance_checks}
    assert "kyc" in check_types
    assert "aml" in check_types


# ─── MSME Credit ────────────────────────────────────────────────────────

def test_msme_credit_approves_strong_application() -> None:
    """Verify MSME credit approves a strong application."""
    agent = GovernanceAgent()
    decision = agent.approve_msme_credit(
        correlation_id="test-credit-1",
        business_id="strong_biz_001", jurisdiction="BB",
        cashflow_score=0.85, debt_service_ratio=0.2,
        operating_history_months=36, requested_amount_usd=15000,
    )
    assert decision.decision_type == "msme_credit"
    assert decision.approved is True


def test_msme_credit_rejects_low_cashflow() -> None:
    """Verify MSME credit rejects low cashflow score."""
    agent = GovernanceAgent()
    decision = agent.approve_msme_credit(
        correlation_id="test-credit-low-cf",
        business_id="weak_biz", jurisdiction="HT",
        cashflow_score=0.3, debt_service_ratio=0.2,
        operating_history_months=12, requested_amount_usd=5000,
    )
    assert decision.approved is False
    assert "cashflow" in decision.rationale.lower()


def test_msme_credit_rejects_high_dsr() -> None:
    """Verify MSME credit rejects high debt service ratio."""
    agent = GovernanceAgent()
    decision = agent.approve_msme_credit(
        correlation_id="test-credit-high-dsr",
        business_id="biz", jurisdiction="HT",
        cashflow_score=0.8, debt_service_ratio=0.7,
        operating_history_months=12, requested_amount_usd=5000,
    )
    assert decision.approved is False
    assert "debt service" in decision.rationale.lower()


def test_msme_credit_rejects_short_history() -> None:
    """Verify MSME credit rejects short operating history."""
    agent = GovernanceAgent()
    decision = agent.approve_msme_credit(
        correlation_id="test-credit-short",
        business_id="new_biz", jurisdiction="HT",
        cashflow_score=0.8, debt_service_ratio=0.2,
        operating_history_months=2, requested_amount_usd=5000,
    )
    assert decision.approved is False
    assert "operating history" in decision.rationale.lower()


def test_msme_credit_collateral_tracked() -> None:
    """Verify collateral info appears in rationale."""
    agent = GovernanceAgent()
    decision = agent.approve_msme_credit(
        correlation_id="test-credit-coll",
        business_id="biz_with_collateral", jurisdiction="BB",
        cashflow_score=0.85, debt_service_ratio=0.2,
        operating_history_months=24, requested_amount_usd=50000,
        collateral_value_usd=100000,
    )
    assert decision.approved is True
    assert "collateralized" in decision.rationale.lower()


def test_msme_credit_no_collateral_label() -> None:
    """Verify no-collateral loans are labeled."""
    agent = GovernanceAgent()
    decision = agent.approve_msme_credit(
        correlation_id="test-credit-no-coll",
        business_id="no_coll_biz", jurisdiction="BB",
        cashflow_score=0.85, debt_service_ratio=0.2,
        operating_history_months=24, requested_amount_usd=25000,
        collateral_value_usd=0,
    )
    assert decision.approved is True
    assert "unsecured" in decision.rationale.lower()


def test_msme_credit_confidence_good() -> None:
    """Verify good applications get high confidence."""
    agent = GovernanceAgent()
    decision = agent.approve_msme_credit(
        correlation_id="test-credit-conf",
        business_id="good_biz", jurisdiction="BB",
        cashflow_score=0.9, debt_service_ratio=0.15,
        operating_history_months=48, requested_amount_usd=10000,
    )
    assert decision.approved is True
    assert decision.confidence >= 0.7


def test_msme_credit_confidence_low() -> None:
    """Verify borderline applications get lower confidence."""
    agent = GovernanceAgent()
    decision = agent.approve_msme_credit(
        correlation_id="test-credit-low-conf",
        business_id="borderline_biz", jurisdiction="HT",
        cashflow_score=0.65, debt_service_ratio=0.35,
        operating_history_months=7, requested_amount_usd=5000,
    )
    assert decision.approved is True  # Just barely approved
    assert decision.confidence < 0.85


# ─── HITL (Human-in-the-Loop) ────────────────────────────────────────────

def test_hitl_enabled_triggers_for_large_fx() -> None:
    """Verify HITL blocks large FX settlements when enabled."""
    os.environ["CARIB_CLEAR_HITL_MODE"] = "true"
    try:
        agent = GovernanceAgent()
        decision = agent.approve_fx_settlement(
            correlation_id="test-hitl-fx",
            from_currency="BBD", to_currency="JMD",
            amount_usd=100000, rate=76.5,
            slippage_bps=10, liquidity_usd=500000,
            settlement_rail="stellar_usdc", counterparty_jurisdiction="BB",
        )
        assert decision.approved is False
        assert "HITL" in decision.rationale or "human" in decision.rationale.lower()
    finally:
        os.environ.pop("CARIB_CLEAR_HITL_MODE", None)


def test_hitl_ignores_small_fx() -> None:
    """Verify HITL doesn't block small FX settlements."""
    os.environ["CARIB_CLEAR_HITL_MODE"] = "true"
    try:
        agent = GovernanceAgent()
        decision = agent.approve_fx_settlement(
            correlation_id="test-hitl-small-fx",
            from_currency="BBD", to_currency="JMD",
            amount_usd=10000, rate=76.5,
            slippage_bps=10, liquidity_usd=50000,
            settlement_rail="stellar_usdc", counterparty_jurisdiction="BB",
        )
        assert decision.approved is True  # Small enough to skip HITL
    finally:
        os.environ.pop("CARIB_CLEAR_HITL_MODE", None)


def test_hitl_triggers_for_large_loan() -> None:
    """Verify HITL blocks large MSME loans when enabled."""
    os.environ["CARIB_CLEAR_HITL_MODE"] = "true"
    try:
        agent = GovernanceAgent()
        decision = agent.approve_msme_credit(
            correlation_id="test-hitl-loan",
            business_id="big_loan_biz", jurisdiction="BB",
            cashflow_score=0.85, debt_service_ratio=0.2,
            operating_history_months=36, requested_amount_usd=50000,
        )
        assert decision.approved is False
        assert "HITL" in decision.rationale or "human" in decision.rationale.lower()
    finally:
        os.environ.pop("CARIB_CLEAR_HITL_MODE", None)


def test_hitl_ignores_small_loan() -> None:
    """Verify HITL doesn't block small MSME loans."""
    os.environ["CARIB_CLEAR_HITL_MODE"] = "true"
    try:
        agent = GovernanceAgent()
        decision = agent.approve_msme_credit(
            correlation_id="test-hitl-small-loan",
            business_id="small_biz", jurisdiction="BB",
            cashflow_score=0.85, debt_service_ratio=0.2,
            operating_history_months=36, requested_amount_usd=10000,
        )
        assert decision.approved is True  # Small enough
    finally:
        os.environ.pop("CARIB_CLEAR_HITL_MODE", None)


# ─── Reload Settings ─────────────────────────────────────────────────────

def test_reload_settings() -> None:
    """Verify reload_settings refreshes HITL state."""
    agent = GovernanceAgent()
    assert agent.hitl_enabled is False

    os.environ["CARIB_CLEAR_HITL_MODE"] = "true"
    try:
        agent.reload_settings()
        assert agent.hitl_enabled is True
    finally:
        os.environ.pop("CARIB_CLEAR_HITL_MODE", None)


# ─── Edge Cases ─────────────────────────────────────────────────────────

def test_fx_settlement_zero_amount() -> None:
    """Verify FX settlement handles zero amount gracefully."""
    agent = GovernanceAgent()
    decision = agent.approve_fx_settlement(
        correlation_id="test-zero",
        from_currency="BBD", to_currency="JMD",
        amount_usd=0, rate=76.5,
        slippage_bps=0, liquidity_usd=0,
        settlement_rail="stellar_usdc", counterparty_jurisdiction="BB",
    )
    # Should not crash — result depends on other params
    assert isinstance(decision, GovernanceDecision)


def test_msme_credit_edge_scores() -> None:
    """Verify MSME credit handles boundary values."""
    agent = GovernanceAgent()
    decision = agent.approve_msme_credit(
        correlation_id="test-edge",
        business_id="edge_biz", jurisdiction="HT",
        cashflow_score=0.6, debt_service_ratio=0.4,
        operating_history_months=6, requested_amount_usd=1000,
    )
    # Exactly at threshold — check it doesn't crash
    assert isinstance(decision, GovernanceDecision)
    assert decision.confidence > 0