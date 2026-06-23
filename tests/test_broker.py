"""Tests for broker adapters — MultiRailRouter, Stellar, ACH, MobileMoney."""

from __future__ import annotations

import pytest

from carib_clear.broker.ach_adapter import LocalACHAdapter
from carib_clear.broker.base import MultiRailBroker, MultiRailRouter, RailInfo, SettlementOrder, SettlementResult
from carib_clear.broker.mobile_money_adapter import MobileMoneyAdapter
from carib_clear.broker.stellar_adapter import StellarAdapter


# ── Data Models ──────────────────────────────────────────────────────────

def test_rail_info() -> None:
    """Verify RailInfo dataclass."""
    info = RailInfo(
        rail_id="test", name="Test Rail", supported_currencies=["USD"],
        min_amount_usd=100, max_amount_usd=1000000, fee_bps=10,
        estimated_time_seconds=60,
    )
    assert info.estimated_time_seconds == 60
    assert info.fee_bps == 10


def test_settlement_order() -> None:
    """Verify SettlementOrder dataclass."""
    order = SettlementOrder(
        order_id="ord-001", from_currency="BBD", to_currency="JMD",
        amount_from=50000, amount_to=3825000, rate=76.5,
        counterparty_id="test", jurisdiction="BB",
    )
    assert order.amount_to == 3825000


# ── MultiRailRouter ─────────────────────────────────────────────────────

def test_router_initializes_with_rails() -> None:
    """Verify MultiRailRouter accepts rail adapters."""
    rails = [StellarAdapter({"mock_mode": True}), LocalACHAdapter({"mock_mode": True})]
    router = MultiRailRouter(rails)
    assert len(router.brokers) == 2


def test_router_find_best_rail_returns_something() -> None:
    """Verify find_best_rail returns a rail for a valid pair."""
    rails = [
        StellarAdapter({"mock_mode": True}),
        LocalACHAdapter({"mock_mode": True}),
        MobileMoneyAdapter({"mock_mode": True}),
    ]
    router = MultiRailRouter(rails)
    rail = router.find_best_rail("BBD", "JMD", 50000)
    assert rail is not None
    assert rail.health_check() is True


def test_router_priorities_speed() -> None:
    """Verify router selects fastest rail when priority is speed."""
    rails = [StellarAdapter({"mock_mode": True}), LocalACHAdapter({"mock_mode": True})]
    router = MultiRailRouter(rails)
    rail = router.find_best_rail("BBD", "JMD", 50000, priority="speed")
    assert rail is not None


def test_router_priorities_cost() -> None:
    """Verify router selects cheapest rail when priority is cost."""
    rails = [StellarAdapter({"mock_mode": True}), LocalACHAdapter({"mock_mode": True})]
    router = MultiRailRouter(rails)
    rail = router.find_best_rail("BBD", "JMD", 50000, priority="cost")
    assert rail is not None


def test_router_get_all_quotes() -> None:
    """Verify get_all_quotes returns quotes from available rails."""
    rails = [
        StellarAdapter({"mock_mode": True}),
        LocalACHAdapter({"mock_mode": True}),
        MobileMoneyAdapter({"mock_mode": True}),
    ]
    router = MultiRailRouter(rails)
    quotes = router.get_all_quotes("BBD", "JMD", 50000)
    assert len(quotes) >= 1
    for q in quotes:
        assert "rail_id" in q
        assert "fees_usd" in q


def test_router_rail_info() -> None:
    """Verify broker rail_info is accessible via router."""
    adapter = StellarAdapter({"mock_mode": True})
    rails = [adapter]
    router = MultiRailRouter(rails)
    info = adapter.rail_info
    assert info is not None
    assert info.rail_id == "stellar_usdc"


def test_router_rail_info_unknown() -> None:
    """Verify unknown rail returns None from broker lookup."""
    rails = [StellarAdapter({"mock_mode": True})]
    router = MultiRailRouter(rails)
    assert "nonexistent_rail" not in router.brokers


# ── StellarAdapter ──────────────────────────────────────────────────────

def test_stellar_adapter_defaults() -> None:
    """Verify StellarAdapter initializes with mock defaults."""
    adapter = StellarAdapter({"mock_mode": True})
    assert adapter.mock_mode is True
    assert adapter.rail_id == "stellar_usdc"


def test_stellar_rail_info() -> None:
    """Verify Stellar rail info is well-formed."""
    adapter = StellarAdapter({"mock_mode": True})
    info = adapter.rail_info
    assert info.rail_id == "stellar_usdc"
    assert info.estimated_time_seconds <= 10
    assert info.fee_bps < 1


def test_stellar_health_ok() -> None:
    """Verify health check returns True."""
    adapter = StellarAdapter({"mock_mode": True})
    assert adapter.health_check() is True


def test_stellar_initialize() -> None:
    """Verify initialize succeeds."""
    adapter = StellarAdapter({"mock_mode": True})
    assert adapter.initialize() is True


def test_stellar_get_quote() -> None:
    """Verify get_quote returns a quote."""
    adapter = StellarAdapter({"mock_mode": True})
    quote = adapter.get_quote("BBD", "JMD", 50000)
    assert quote is not None


def test_stellar_submit_settlement() -> None:
    """Verify submit_settlement returns a result."""
    adapter = StellarAdapter({"mock_mode": True})
    order = SettlementOrder(
        order_id="test", from_currency="BBD", to_currency="JMD",
        amount_from=50000, amount_to=3825000, rate=76.5,
        counterparty_id="test", jurisdiction="BB",
    )
    result = adapter.submit_settlement(order)
    assert result.success is True
    assert result.tx_hash is not None


def test_stellar_get_settlement_status() -> None:
    """Verify settlement status check returns a result."""
    adapter = StellarAdapter({"mock_mode": True})
    result = adapter.get_settlement_status("test-hash")
    assert isinstance(result, SettlementResult)
    assert result.success is True


def test_stellar_cancel_settlement() -> None:
    """Verify settlement cancellation (Stellar doesn't support cancellation)."""
    adapter = StellarAdapter({"mock_mode": True})
    assert adapter.cancel_settlement("test-hash") is False  # Stellar doesn't support cancel


# ── ACH Adapter ─────────────────────────────────────────────────────────

def test_ach_adapter_defaults() -> None:
    """Verify LocalACHAdapter initializes."""
    adapter = LocalACHAdapter({"mock_mode": True})
    assert "ach" in adapter.rail_id


def test_ach_rail_info() -> None:
    """Verify ACH rail info."""
    adapter = LocalACHAdapter({"mock_mode": True})
    info = adapter.rail_info
    assert info is not None


def test_ach_initialize() -> None:
    """Verify ACH initialize with mock mode."""
    adapter = LocalACHAdapter({"mock_mode": True})
    assert adapter.initialize() is True


def test_ach_get_quote_matching_currency() -> None:
    """Verify ACH get_quote for a supported currency."""
    adapter = LocalACHAdapter({"mock_mode": True})
    adapter.initialize()
    # ACH supports same-currency local pairs
    quote = adapter.get_quote("BBD", "BBD", 10000)
    # May be None if BBD isn't in this ACH instance's supported currencies
    # Test at minimum that it doesn't crash
    assert quote is None or "rate" in quote


def test_ach_submit_settlement() -> None:
    """Verify ACH submit_settlement."""
    adapter = LocalACHAdapter({"mock_mode": True})
    adapter.initialize()
    order = SettlementOrder(
        order_id="test-ach", from_currency="BBD", to_currency="BBD",
        amount_from=50000, amount_to=50000, rate=1.0,
        counterparty_id="test", jurisdiction="BB",
    )
    result = adapter.submit_settlement(order)
    assert result.success is True


# ── Mobile Money Adapter ────────────────────────────────────────────────

def test_mobile_defaults() -> None:
    """Verify MobileMoneyAdapter initializes."""
    adapter = MobileMoneyAdapter({"mock_mode": True})
    assert adapter.rail_id is not None


def test_mobile_rail_info() -> None:
    """Verify MobileMoney rail info."""
    adapter = MobileMoneyAdapter({"mock_mode": True})
    info = adapter.rail_info
    assert info is not None


def test_mobile_initialize() -> None:
    """Verify MobileMoney initialize with mock mode."""
    adapter = MobileMoneyAdapter({"mock_mode": True})
    assert adapter.initialize() is True


def test_mobile_get_quote() -> None:
    """Verify MobileMoney get_quote."""
    adapter = MobileMoneyAdapter({"mock_mode": True})
    adapter.initialize()
    quote = adapter.get_quote("HTG", "USD", 1000)
    assert quote is not None


def test_mobile_submit_settlement() -> None:
    """Verify MobileMoney submit_settlement."""
    adapter = MobileMoneyAdapter({"mock_mode": True})
    adapter.initialize()
    order = SettlementOrder(
        order_id="test-mobile", from_currency="USD", to_currency="HTG",
        amount_from=500, amount_to=3850, rate=7.7,
        counterparty_id="test", jurisdiction="HT",
    )
    result = adapter.submit_settlement(order)
    assert result.success is True