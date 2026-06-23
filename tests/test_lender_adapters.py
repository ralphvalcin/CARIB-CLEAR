"""Tests for lender adapters (Barita, JMMB, IDB Invest)."""

from __future__ import annotations

from carib_clear.broker.lender_adapters import (
    BaritaLenderAdapter,
    IDBInvestLenderAdapter,
    JMMBLenderAdapter,
)
from carib_clear.broker.lender_base import (
    LenderApplicationRequest,
    get_lender,
    list_lenders,
    register_lender,
)


def _make_request(**kwargs) -> LenderApplicationRequest:
    """Helper to create a standard loan request."""
    defaults = dict(
        business_id="test_001",
        business_name="Test Business",
        jurisdiction="JM",
        sector="retail",
        requested_amount_usd=25000,
        approved_amount_usd=25000,
        interest_rate_annual_pct=15.0,
        tenure_months=18,
        credit_score=0.7,
        credit_rating="BBB",
        dti_ratio=0.25,
        operating_months=24,
        reference_id="app-001",
    )
    defaults.update(kwargs)
    return LenderApplicationRequest(**defaults)


def test_barita_submit_approved() -> None:
    """Verify Barita approves a qualified application."""
    adapter = BaritaLenderAdapter(config={"mock_mode": True})
    request = _make_request(approved_amount_usd=50000)
    result = adapter.submit_application(request)
    assert result.success is True
    assert result.status == "approved"
    assert result.lender_application_id.startswith("BAR")


def test_barita_submit_denied_exceeds_limit() -> None:
    """Verify Barita denies applications over $100K."""
    adapter = BaritaLenderAdapter()
    request = _make_request(approved_amount_usd=150000)
    result = adapter.submit_application(request)
    assert result.success is False
    assert result.status == "denied"


def test_barita_disburse() -> None:
    """Verify Barita disbursement works for approved apps."""
    adapter = BaritaLenderAdapter()
    request = _make_request()
    app = adapter.submit_application(request)
    result = adapter.disburse(app.lender_application_id, 25000)
    assert result.success is True
    assert result.tx_hash.startswith("bar")
    assert result.settlement_rail == "local_ach_jm"


def test_barita_disburse_unapproved() -> None:
    """Verify Barita rejects disbursement for unapproved apps."""
    adapter = BaritaLenderAdapter()
    result = adapter.disburse("NONEXISTENT", 25000)
    assert result.success is False


def test_barita_health() -> None:
    """Verify Barita health check."""
    adapter = BaritaLenderAdapter()
    assert adapter.health() is True


def test_barita_check_status() -> None:
    """Verify Barita status check."""
    adapter = BaritaLenderAdapter()
    request = _make_request()
    app = adapter.submit_application(request)
    status = adapter.check_status(app.lender_application_id)
    assert status.status == "approved"


def test_jmmb_submit_approved() -> None:
    """Verify JMMB approves applications with sufficient collateral."""
    adapter = JMMBLenderAdapter()
    request = _make_request(collateral_offered_usd=25000, approved_amount_usd=30000)
    result = adapter.submit_application(request)
    # 25K collateral / 30K loan = 83% > 75% threshold
    assert result.success is True


def test_jmmb_submit_denied_no_collateral() -> None:
    """Verify JMMB denies applications without sufficient collateral."""
    adapter = JMMBLenderAdapter()
    request = _make_request(collateral_offered_usd=5000, approved_amount_usd=30000)
    result = adapter.submit_application(request)
    assert result.success is False
    assert "collateral" in result.message.lower()


def test_jmmb_submit_denied_over_limit() -> None:
    """Verify JMMB denies applications over $50K."""
    adapter = JMMBLenderAdapter()
    request = _make_request(approved_amount_usd=75000)
    result = adapter.submit_application(request)
    assert result.success is False


def test_idb_submit_approved() -> None:
    """Verify IDB Invest approves a qualified application."""
    adapter = IDBInvestLenderAdapter()
    request = _make_request(sector="agriculture", approved_amount_usd=50000, operating_months=24)
    result = adapter.submit_application(request)
    assert result.success is True
    assert result.status == "under_review"


def test_idb_submit_denied_sector() -> None:
    """Verify IDB Invest denies non-sustainable sectors."""
    adapter = IDBInvestLenderAdapter()
    request = _make_request(sector="manufacturing")
    result = adapter.submit_application(request)
    assert result.success is False


def test_idb_submit_denied_short_history() -> None:
    """Verify IDB Invest requires 12+ months operating history."""
    adapter = IDBInvestLenderAdapter()
    request = _make_request(operating_months=6, sector="agriculture")
    result = adapter.submit_application(request)
    assert result.success is False


def test_idb_disburse() -> None:
    """Verify IDB Invest disbursement via Stellar (must be approved first)."""
    adapter = IDBInvestLenderAdapter()
    request = _make_request(sector="agriculture", operating_months=24)
    app = adapter.submit_application(request)
    # IDB Invest puts applications in "under_review" — disbursement not allowed yet
    assert app.status == "under_review"
    result = adapter.disburse(app.lender_application_id, 50000)
    assert result.success is False  # Must be approved first
    assert "approved" in result.error_message.lower()


def test_lender_registry() -> None:
    """Verify lender registry."""
    lenders = list_lenders()
    assert "barita" in lenders
    assert "jmmb" in lenders
    assert "idb_invest" in lenders


def test_get_lender() -> None:
    """Verify get_lender returns correct adapter."""
    barita = get_lender("barita")
    assert barita is not None
    assert barita.lender_id == "barita"

    jmmb = get_lender("jmmb")
    assert jmmb is not None
    assert jmmb.lender_id == "jmmb"

    idb = get_lender("idb_invest")
    assert idb is not None
    assert idb.lender_id == "idb_invest"

    nonexistent = get_lender("nonexistent")
    assert nonexistent is None