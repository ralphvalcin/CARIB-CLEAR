"""Tests for CreditProfileGenerator and related data models."""

from __future__ import annotations

from carib_clear.agents.credit_profile import (
    CreditProfile,
    CreditProfileGenerator,
    CreditScoreCategory,
    LoanRecommendation,
    RiskFactor,
)
from carib_clear.agents.data_aggregation import DataAggregationAgent


def test_risk_factor_defaults() -> None:
    """Verify RiskFactor dataclass defaults."""
    f = RiskFactor(name="test", category="capacity", impact=0.5, weight=0.3, description="Test factor")
    assert f.name == "test"
    assert f.category == "capacity"
    assert f.impact == 0.5
    assert f.severity == "info"


def test_credit_score_category_weighted() -> None:
    """Verify weighted contribution calculation."""
    cat = CreditScoreCategory(name="capacity", score=0.75, weight=0.40)
    assert cat.weighted_contribution() == 0.75 * 0.40


def test_loan_recommendation_defaults() -> None:
    """Verify LoanRecommendation dataclass."""
    r = LoanRecommendation(
        recommended=True,
        max_amount_usd=50000,
        suggested_amount_usd=25000,
        interest_rate_annual_pct=15.0,
        tenure_months=12,
        collateral_required=False,
        rationale="Good credit score",
    )
    assert r.recommended is True
    assert r.max_amount_usd == 50000
    assert r.interest_rate_annual_pct == 15.0


def test_credit_profile_summary() -> None:
    """Verify CreditProfile.summary() output."""
    profile = CreditProfile(
        business_id="test_001",
        business_name="Test Business",
        jurisdiction="HT",
        credit_score=0.75,
        credit_rating="A",
    )
    summary = profile.summary()
    assert summary["business_id"] == "test_001"
    assert summary["credit_score"] == 0.75
    assert summary["credit_rating"] == "A"
    assert summary["recommended"] is False  # No recommendation


def test_credit_rating_aaa() -> None:
    """Verify rating boundaries."""
    assert CreditProfileGenerator._get_rating(0.95) == "AAA"
    assert CreditProfileGenerator._get_rating(0.85) == "AA"
    assert CreditProfileGenerator._get_rating(0.75) == "A"
    assert CreditProfileGenerator._get_rating(0.65) == "BBB"
    assert CreditProfileGenerator._get_rating(0.55) == "BB"
    assert CreditProfileGenerator._get_rating(0.45) == "B"
    assert CreditProfileGenerator._get_rating(0.30) == "C"
    assert CreditProfileGenerator._get_rating(0.10) == "D"


def test_scorer_accepts_business_profile() -> None:
    """Verify scorer accepts BusinessProfile and returns CreditProfile."""
    agent = DataAggregationAgent()
    scorer = CreditProfileGenerator()

    pos_csv = agent.generate_mock_pos_csv(months=6, avg_monthly_revenue=12000)
    invoices = agent.generate_mock_invoices(count=10)
    bank_stmt = agent.generate_mock_bank_statement(months=6, avg_deposit=15000)
    tax_data = agent.generate_mock_tax_data("HT")

    profile = agent.build_profile(
        business_id="test_001",
        business_name="Test Business",
        jurisdiction="HT",
        sector={"sector": "retail"},
        pos_csv_content=pos_csv,
        invoice_data=invoices,
        bank_statement_csv=bank_stmt,
        tax_data=tax_data,
    )

    credit = scorer.score(profile)

    assert isinstance(credit, CreditProfile)
    assert credit.business_id == "test_001"
    assert credit.business_name == "Test Business"
    assert credit.jurisdiction == "HT"
    assert 0.0 <= credit.credit_score <= 1.0
    assert credit.credit_rating in ("AAA", "AA", "A", "BBB", "BB", "B", "C", "D")
    assert len(credit.categories) == 5  # All 5 C's
    assert "capacity" in credit.categories
    assert "character" in credit.categories
    assert "collateral" in credit.categories
    assert "conditions" in credit.categories
    assert "capital" in credit.categories


def test_scorer_high_revenue_low_risk() -> None:
    """Verify a high-revenue, stable business gets a good score."""
    agent = DataAggregationAgent()
    scorer = CreditProfileGenerator()

    pos_csv = agent.generate_mock_pos_csv(months=24, avg_monthly_revenue=50000)
    bank_stmt = agent.generate_mock_bank_statement(months=12, avg_deposit=60000)

    profile = agent.build_profile(
        business_id="strong_001",
        business_name="Strong Business",
        jurisdiction="BB",
        sector={"sector": "services"},
        pos_csv_content=pos_csv,
        bank_statement_csv=bank_stmt,
    )

    credit = scorer.score(profile)
    assert credit.credit_score >= 0.5  # Should be decent
    assert credit.recommendation is not None


def test_scorer_minimal_data_still_works() -> None:
    """Verify scorer handles minimal data gracefully."""
    agent = DataAggregationAgent()
    scorer = CreditProfileGenerator()

    pos_csv = agent.generate_mock_pos_csv(months=3, avg_monthly_revenue=3000)

    profile = agent.build_profile(
        business_id="minimal_001",
        business_name="Minimal Business",
        jurisdiction="HT",
        pos_csv_content=pos_csv,
    )

    credit = scorer.score(profile)
    assert credit.credit_score >= 0  # Should always produce a score
    assert len(credit.positive_factors) + len(credit.negative_factors) > 0


def test_ml_feature_preparation() -> None:
    """Verify ML feature preparation returns flat dict."""
    agent = DataAggregationAgent()
    scorer = CreditProfileGenerator()

    pos_csv = agent.generate_mock_pos_csv(months=6, avg_monthly_revenue=10000)
    profile = agent.build_profile(
        business_id="feat_001",
        business_name="Feature Test",
        jurisdiction="JM",
        pos_csv_content=pos_csv,
    )

    features = scorer.prepare_ml_features(profile)
    assert isinstance(features, dict)
    assert "avg_monthly_revenue_usd" in features
    assert "estimated_annual_revenue_usd" in features
    assert "operating_months" in features
    assert "cash_flow_stability" in features
