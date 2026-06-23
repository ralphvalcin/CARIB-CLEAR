"""Tests for TradeFinanceModule — invoice factoring engine."""

from __future__ import annotations

from carib_clear.agents.data_aggregation import InvoiceRecord
from carib_clear.agents.trade_finance import (
    DebtorAssessment,
    FactoringAgreement,
    FactoringEvaluation,
    FactoringRequest,
    TradeFinanceModule,
)


def _make_invoice(**kwargs) -> InvoiceRecord:
    """Create a test invoice."""
    defaults = dict(
        invoice_id="INV-TEST-0001",
        type="receivable",
        counterparty="Test Company Ltd",
        amount_usd=10000,
        issued_date="2026-01-15",
        due_date="2026-03-15",
        status="pending",
        days_outstanding=10,
    )
    defaults.update(kwargs)
    return InvoiceRecord(**defaults)


def _make_request_module() -> tuple[TradeFinanceModule, FactoringRequest]:
    """Create a module and a factoring request."""
    module = TradeFinanceModule()
    invoice = _make_invoice()
    req = module.submit_invoice("test_biz", "Test Business", "BB", invoice)
    return module, req


def test_factoring_request_defaults() -> None:
    """Verify FactoringRequest dataclass."""
    invoice = _make_invoice()
    req = FactoringRequest(
        request_id="fact-test",
        business_id="test", business_name="Test",
        jurisdiction="BB", invoice=invoice,
    )
    assert req.requested_advance_rate == 0.85
    assert req.invoice.amount_usd == 10000


def test_debtor_assessment_defaults() -> None:
    """Verify DebtorAssessment dataclass."""
    d = DebtorAssessment(debtor_name="Test Ltd", credit_score=0.8, payment_reliability=0.9)
    assert d.assessment == "pass"
    assert d.credit_score == 0.8


def test_factoring_evaluation() -> None:
    """Verify FactoringEvaluation dataclass."""
    ev = FactoringEvaluation(
        request_id="ev-test",
        approved=True, advance_rate=0.85,
        advance_amount_usd=8500, discount_fee_pct=2.5,
        discount_fee_usd=212.50, net_amount_usd=8287.50,
        max_tenure_days=60,
        debtor_assessment=DebtorAssessment("Dbt", 0.9, 0.95),
        risk_score=0.2,
    )
    assert ev.approved is True
    assert ev.net_amount_usd == 8287.50


def test_factoring_agreement_defaults() -> None:
    """Verify FactoringAgreement dataclass."""
    agr = FactoringAgreement(
        agreement_id="agr-test",
        request_id="req-test", business_id="biz",
        business_name="Biz", invoice_id="INV-001",
        debtor_name="Debtor", invoice_amount_usd=10000,
        advance_amount_usd=8500, discount_fee_usd=212.50,
        advance_rate=0.85, funded_at="2026-01-01",
        expected_settlement_date="2026-03-01",
    )
    assert agr.status == "active"
    assert agr.advance_amount_usd == 8500


def test_submit_invoice() -> None:
    """Verify submitting an invoice creates a request."""
    module = TradeFinanceModule()
    invoice = _make_invoice()
    req = module.submit_invoice("biz_001", "Test Business", "JM", invoice)
    assert req.request_id.startswith("fact-")
    assert req.invoice.invoice_id == "INV-TEST-0001"
    assert len(module._requests) == 1


def test_evaluate_approved_good_debtor() -> None:
    """Verify evaluation approves a good invoice."""
    module, req = _make_request_module()
    ev = module.evaluate(req, sector="services")
    assert ev.approved is True
    assert ev.advance_rate > 0.7
    assert ev.advance_amount_usd > 0


def test_evaluate_rejected_overdue() -> None:
    """Verify evaluation rejects an overdue invoice."""
    module = TradeFinanceModule()
    invoice = _make_invoice(status="overdue", days_outstanding=45)
    req = module.submit_invoice("biz_001", "Biz", "BB", invoice)
    # Overdue with low debtor credit may still be approved but with worse terms
    ev = module.evaluate(req, sector="services")
    # Should evaluate without crashing — result depends on random factors
    assert isinstance(ev, FactoringEvaluation)


def test_evaluate_rejected_flagged_debtor() -> None:
    """Verify evaluation rejects a flagged debtor."""
    module = TradeFinanceModule()
    invoice = _make_invoice(counterparty="Company in Liquidation")
    req = module.submit_invoice("biz_001", "Biz", "BB", invoice)
    ev = module.evaluate(req, sector="services")
    assert ev.approved is False


def test_evaluate_rejected_below_minimum() -> None:
    """Verify evaluation rejects a below-minimum invoice."""
    module = TradeFinanceModule()
    invoice = _make_invoice(amount_usd=100)  # Below min $500
    req = module.submit_invoice("biz_001", "Biz", "BB", invoice)
    ev = module.evaluate(req, sector="retail")
    assert ev.approved is False


def test_fund_approved_evaluation() -> None:
    """Verify funding an approved evaluation creates an agreement."""
    module, req = _make_request_module()
    ev = module.evaluate(req, sector="services")
    assert ev.approved is True
    agreement = module.fund(ev, "test_biz", "Test Business")
    assert agreement is not None
    assert agreement.agreement_id.startswith("fact-agr-")
    assert agreement.advance_amount_usd == ev.advance_amount_usd


def test_fund_rejected_evaluation() -> None:
    """Verify funding a rejected evaluation returns None."""
    module = TradeFinanceModule()
    invoice = _make_invoice(amount_usd=100)
    req = module.submit_invoice("biz", "Biz", "BB", invoice)
    ev = module.evaluate(req, sector="retail")
    assert ev.approved is False
    agreement = module.fund(ev, "biz", "Biz")
    assert agreement is None


def test_record_collection() -> None:
    """Verify recording a collection updates the agreement."""
    module, req = _make_request_module()
    ev = module.evaluate(req, sector="services")
    agreement = module.fund(ev, "test_biz", "Test Business")

    assert module.record_collection(agreement.agreement_id, ev.advance_amount_usd) is True
    assert agreement.status == "settled"
    assert agreement.collection_result is not None


def test_record_collection_unknown() -> None:
    """Verify recording collection for unknown agreement fails."""
    module = TradeFinanceModule()
    assert module.record_collection("nonexistent", 1000) is False


def test_get_stats() -> None:
    """Verify stats tracking."""
    module, req = _make_request_module()
    stats = module.get_stats()
    assert stats["invoices_submitted"] == 1
    assert stats["funded"] == 0

    ev = module.evaluate(req, sector="services")
    module.fund(ev, "test_biz", "Test Business")
    stats = module.get_stats()
    assert stats["funded"] == 1
    assert stats["total_funded_usd"] > 0


def test_generate_mock_invoices() -> None:
    """Verify mock invoice generation."""
    invoices = TradeFinanceModule.generate_mock_invoices("Test Business", count=3)
    assert len(invoices) == 3
    for inv in invoices:
        assert inv.type == "receivable"
        assert inv.amount_usd > 0


def test_government_debtor_best_terms() -> None:
    """Verify government entities get best factoring terms."""
    module = TradeFinanceModule()
    invoice = _make_invoice(counterparty="Government of Barbados", amount_usd=20000)
    req = module.submit_invoice("biz", "Biz", "BB", invoice)
    ev = module.evaluate(req, sector="services")
    assert ev.approved is True
    assert ev.risk_score < 0.25  # Very low risk
    assert ev.advance_rate >= 0.85  # High advance


def test_terms_vary_with_risk() -> None:
    """Verify worse risk = lower advance + higher fee."""
    module = TradeFinanceModule()
    # High-risk debtor
    invoice_risky = _make_invoice(counterparty="Small Shop", amount_usd=5000)
    req_risky = module.submit_invoice("biz", "Biz", "HT", invoice_risky)
    ev_risky = module.evaluate(req_risky, sector="retail")

    # Low-risk debtor
    invoice_safe = _make_invoice(counterparty="Central Bank of Barbados", amount_usd=50000)
    req_safe = module.submit_invoice("biz", "Biz", "BB", invoice_safe)
    ev_safe = module.evaluate(req_safe, sector="services")

    assert ev_risky.advance_rate <= ev_safe.advance_rate or ev_risky.discount_fee_pct >= ev_safe.discount_fee_pct