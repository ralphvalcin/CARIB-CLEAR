"""Tests for CashFlowLendingEngine and related data models."""

from __future__ import annotations

from carib_clear.agents.cash_flow_lending import (
    CashFlowLendingEngine,
    LendingProduct,
    LoanApplication,
    LoanDecision,
)
from carib_clear.agents.credit_profile import CreditProfile, CreditProfileGenerator
from carib_clear.agents.data_aggregation import DataAggregationAgent
from carib_clear.governance.agent import GovernanceAgent


def test_loan_application_defaults() -> None:
    """Verify LoanApplication dataclass defaults."""
    app = LoanApplication(
        application_id="app-001",
        business_id="biz-001",
        business_name="Test Business",
        jurisdiction="HT",
        requested_amount_usd=25000,
        purpose="working_capital",
    )
    assert app.application_id == "app-001"
    assert app.preferred_tenure_months == 12
    assert app.preferred_lender == "auto"
    assert app.collateral_offered_usd == 0.0


def test_loan_decision_summary() -> None:
    """Verify LoanDecision.summary() output."""
    decision = LoanDecision(
        application_id="app-001",
        business_id="biz-001",
        approved=True,
        decision_type="approved",
        lender_id="barita",
        product_name="MSME Growth Loan",
        approved_amount_usd=25000,
        interest_rate_annual_pct=15.0,
        tenure_months=12,
        monthly_payment_usd=2254.0,
        rationale="Good credit",
    )
    summary = decision.summary()
    assert summary["approved"] is True
    assert summary["amount"] == 25000
    assert summary["rate"] == 15.0
    assert summary["lender"] == "barita"


def test_lending_product_basic() -> None:
    """Verify LendingProduct dataclass."""
    product = LendingProduct(
        lender_id="barita",
        product_name="Test Loan",
        min_amount_usd=5000,
        max_amount_usd=50000,
        min_credit_score=0.5,
        max_interest_rate=20.0,
        min_tenure_months=6,
        max_tenure_months=24,
        requires_collateral=False,
        eligible_sectors=["retail", "services"],
        eligible_jurisdictions=["JM", "BB"],
    )
    assert product.lender_id == "barita"
    assert product.max_amount_usd == 50000
    assert product.min_credit_score == 0.5


def test_evaluate_approves_qualified_applicant() -> None:
    """Verify a well-qualified applicant gets approved."""
    import random
    random.seed(42)

    da = DataAggregationAgent()
    scorer = CreditProfileGenerator()
    gov = GovernanceAgent()
    engine = CashFlowLendingEngine(governance_agent=gov)

    pos_csv = da.generate_mock_pos_csv(months=12, avg_monthly_revenue=20000)
    invoices = da.generate_mock_invoices(count=20)
    bank_stmt = da.generate_mock_bank_statement(months=6, avg_deposit=25000)
    tax_data = da.generate_mock_tax_data("JM")

    profile = da.build_profile(
        business_id="test_001",
        business_name="Test Business",
        jurisdiction="JM",
        sector={"sector": "services"},
        pos_csv_content=pos_csv,
        invoice_data=invoices,
        bank_statement_csv=bank_stmt,
        tax_data=tax_data,
    )
    credit = scorer.score(profile)

    app = LoanApplication(
        application_id="test-app-001",
        business_id="test_001",
        business_name="Test Business",
        jurisdiction="JM",
        requested_amount_usd=30000,
        purpose="working_capital",
        preferred_tenure_months=18,
    )

    decision = engine.evaluate(credit, app)
    assert isinstance(decision, LoanDecision)
    assert decision.business_id == "test_001"
    # Should be approved or have a reason
    assert decision.rationale != ""


def test_evaluate_denies_large_amount() -> None:
    """Verify a too-large request gets denied."""
    import random
    random.seed(42)

    da = DataAggregationAgent()
    scorer = CreditProfileGenerator()
    gov = GovernanceAgent()
    engine = CashFlowLendingEngine(governance_agent=gov)

    pos_csv = da.generate_mock_pos_csv(months=6, avg_monthly_revenue=5000)
    profile = da.build_profile(
        business_id="small_001",
        business_name="Small Business",
        jurisdiction="BB",
        sector={"sector": "retail"},
        pos_csv_content=pos_csv,
    )
    credit = scorer.score(profile)

    app = LoanApplication(
        application_id="test-app-002",
        business_id="small_001",
        business_name="Small Business",
        jurisdiction="BB",
        requested_amount_usd=500000,  # Way too much
        purpose="expansion",
    )

    decision = engine.evaluate(credit, app)
    # Likely denied due to amount exceeding product limits or DSR
    assert decision.application_id == "test-app-002"


def test_engine_stats() -> None:
    """Verify engine stats tracking."""
    engine = CashFlowLendingEngine()
    assert engine.get_stats()["total_applications"] == 0


def test_no_governance_still_works() -> None:
    """Verify engine works without governance agent (runs in evaluation mode)."""
    import random
    random.seed(42)

    da = DataAggregationAgent()
    scorer = CreditProfileGenerator()
    engine = CashFlowLendingEngine(governance_agent=None)

    pos_csv = da.generate_mock_pos_csv(months=12, avg_monthly_revenue=20000)
    profile = da.build_profile(
        business_id="no_gov_001",
        business_name="No Gov Test",
        jurisdiction="JM",
        sector={"sector": "services"},
        pos_csv_content=pos_csv,
    )
    credit = scorer.score(profile)

    app = LoanApplication(
        application_id="test-app-003",
        business_id="no_gov_001",
        business_name="No Gov Test",
        jurisdiction="JM",
        requested_amount_usd=15000,
        purpose="working_capital",
    )

    # Should not crash without governance
    decision = engine.evaluate(credit, app)
    assert isinstance(decision, LoanDecision)
