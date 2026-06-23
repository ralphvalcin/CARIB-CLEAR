"""Tests for P2PMatchingEngine — order book, matching logic, partial fills."""

from __future__ import annotations

from carib_clear.agents.p2p_matching import (
    OrderBookEntry,
    P2PMatchingEngine,
)
from carib_clear.governance.agent import GovernanceAgent
from carib_clear.broker.base import MultiRailRouter
from carib_clear.broker.stellar_adapter import StellarAdapter


def _make_engine() -> P2PMatchingEngine:
    """Create a test matching engine with mock governance and router."""
    gov = GovernanceAgent()
    router = MultiRailRouter([
        StellarAdapter({"mock_mode": True}),
    ])
    return P2PMatchingEngine(gov, router)


def test_order_book_entry_defaults() -> None:
    """Verify OrderBookEntry dataclass defaults."""
    entry = OrderBookEntry(
        order_id="test-001",
        currency_from="BBD",
        currency_to="JMD",
        amount_usd=50000,
        max_rate=77.0,
        min_rate=None,
        side="demand",
        participant_id="test_participant",
        jurisdiction="BB",
    )
    assert entry.status == "open"
    assert entry.order_id == "test-001"
    assert entry.side == "demand"


def test_submit_demand_order() -> None:
    """Verify demand order submission and book placement."""
    engine = _make_engine()
    order = engine.submit_demand_order(
        currency_from="BBD",
        currency_to="JMD",
        amount_usd=50000,
        max_rate=77.0,
        participant_id="bb_hotel_001",
        jurisdiction="BB",
    )
    assert order.side == "demand"
    assert order.amount_usd == 50000
    assert order.max_rate == 77.0
    assert order.status == "open"
    assert order.order_id.startswith("demand-")


def test_submit_supply_order() -> None:
    """Verify supply order submission and book placement."""
    engine = _make_engine()
    order = engine.submit_supply_order(
        currency_from="BBD",
        currency_to="JMD",
        amount_usd=50000,
        min_rate=76.0,
        participant_id="jm_supplier_001",
        jurisdiction="JM",
    )
    assert order.side == "supply"
    assert order.amount_usd == 50000
    assert order.min_rate == 76.0
    assert order.status == "open"
    assert order.order_id.startswith("supply-")


def test_matching_crossing_rates() -> None:
    """Verify matching works when demand max >= supply min."""
    engine = _make_engine()
    engine.submit_demand_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, max_rate=77.0,
        participant_id="bb_hotel_001", jurisdiction="BB",
    )
    engine.submit_supply_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, min_rate=76.0,
        participant_id="jm_supplier_001", jurisdiction="JM",
    )
    matches = engine.match_orders("BBD", "JMD")
    assert len(matches) == 1
    m = matches[0]
    assert m.settled_amount_usd == 50000
    # Settlement rate should be midpoint: (77 + 76) / 2
    assert m.settlement_rate == 76.5
    assert m.rail_used is not None


def test_matching_no_match_when_rates_dont_cross() -> None:
    """Verify no match when demand max < supply min."""
    engine = _make_engine()
    engine.submit_demand_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, max_rate=75.0,  # Low max
        participant_id="bb_hotel_001", jurisdiction="BB",
    )
    engine.submit_supply_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, min_rate=78.0,  # High min
        participant_id="jm_supplier_001", jurisdiction="JM",
    )
    matches = engine.match_orders("BBD", "JMD")
    assert len(matches) == 0


def test_partial_fill_demand() -> None:
    """Verify demand order gets partially_filled status when only partly matched."""
    engine = _make_engine()
    engine.submit_demand_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=100000, max_rate=77.0,
        participant_id="bb_hotel_001", jurisdiction="BB",
    )
    engine.submit_supply_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=60000, min_rate=76.0,
        participant_id="jm_supplier_001", jurisdiction="JM",
    )
    matches = engine.match_orders("BBD", "JMD")
    assert len(matches) == 1
    m = matches[0]
    assert m.settled_amount_usd == 60000  # Only supply amount matched

    # Demand should be partially_filled, supply filled
    demand_book = engine.demand_book.get("BBD/JMD", [])
    supply_book = engine.supply_book.get("BBD/JMD", [])
    assert any(o.status == "partially_filled" for o in demand_book)
    assert any(o.status == "filled" for o in supply_book)


def test_partial_fill_supply() -> None:
    """Verify supply order gets partially_filled when only partly matched."""
    engine = _make_engine()
    engine.submit_demand_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=30000, max_rate=77.0,
        participant_id="bb_hotel_001", jurisdiction="BB",
    )
    engine.submit_supply_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=100000, min_rate=76.0,
        participant_id="jm_supplier_001", jurisdiction="JM",
    )
    matches = engine.match_orders("BBD", "JMD")
    assert len(matches) == 1
    assert matches[0].settled_amount_usd == 30000

    demand_book = engine.demand_book.get("BBD/JMD", [])
    supply_book = engine.supply_book.get("BBD/JMD", [])
    assert any(o.status == "filled" for o in demand_book)
    assert any(o.status == "partially_filled" for o in supply_book)


def test_multi_currency_matching() -> None:
    """Verify matching across different currency pairs."""
    engine = _make_engine()
    # BBD→JMD
    engine.submit_demand_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, max_rate=77.0,
        participant_id="bb_hotel_001", jurisdiction="BB",
    )
    engine.submit_supply_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, min_rate=76.0,
        participant_id="jm_supplier_001", jurisdiction="JM",
    )
    # TTD→USD
    engine.submit_demand_order(
        currency_from="TTD", currency_to="USD",
        amount_usd=25000, max_rate=0.148,
        participant_id="tt_energy_001", jurisdiction="TT",
    )
    engine.submit_supply_order(
        currency_from="TTD", currency_to="USD",
        amount_usd=25000, min_rate=0.146,
        participant_id="us_investor_001", jurisdiction="US",
    )

    bbd_matches = engine.match_orders("BBD", "JMD")
    ttd_matches = engine.match_orders("TTD", "USD")
    assert len(bbd_matches) == 1
    assert len(ttd_matches) == 1


def test_order_book_snapshot() -> None:
    """Verify order book snapshot includes open orders."""
    engine = _make_engine()
    engine.submit_demand_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, max_rate=77.0,
        participant_id="bb_hotel_001", jurisdiction="BB",
    )
    engine.submit_supply_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, min_rate=76.0,
        participant_id="jm_supplier_001", jurisdiction="JM",
    )
    snapshot = engine.get_order_book_snapshot("BBD", "JMD")
    assert snapshot["pair"] == "BBD/JMD"
    assert len(snapshot["demand"]) == 1
    assert len(snapshot["supply"]) == 1


def test_get_stats() -> None:
    """Verify engine stats tracking."""
    engine = _make_engine()
    stats = engine.get_stats()
    assert stats["total_matches"] == 0
    assert stats["total_volume_usd"] == 0

    engine.submit_demand_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, max_rate=77.0,
        participant_id="bb_hotel_001", jurisdiction="BB",
    )
    engine.submit_supply_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, min_rate=76.0,
        participant_id="jm_supplier_001", jurisdiction="JM",
    )
    engine.match_orders("BBD", "JMD")
    stats = engine.get_stats()
    assert stats["total_matches"] == 1
    assert stats["total_volume_usd"] == 50000


def test_price_time_priority() -> None:
    """Verify best-priced order matches first."""
    engine = _make_engine()
    # One demand at good rate
    engine.submit_demand_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, max_rate=77.0,
        participant_id="buyer_a", jurisdiction="BB",
    )
    # Two supplies: one at better rate, one at worse
    engine.submit_supply_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, min_rate=75.0,  # Better rate (lower = better for buyer)
        participant_id="seller_a", jurisdiction="JM",
    )
    engine.submit_supply_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, min_rate=76.5,  # Worse rate
        participant_id="seller_b", jurisdiction="JM",
    )

    matches = engine.match_orders("BBD", "JMD")
    assert len(matches) == 1
    m = matches[0]
    # Should match with the better-priced supply (seller_a at 75.0)
    assert m.supply_order_id.startswith("supply-")
    supply_book = engine.supply_book.get("BBD/JMD", [])
    matched_supply = next(o for o in supply_book if o.order_id == m.supply_order_id)
    assert matched_supply.min_rate == 75.0


def test_supported_pairs() -> None:
    """Verify supported pairs list is populated."""
    engine = _make_engine()
    assert ("BBD", "JMD") in engine.supported_pairs
    assert ("JMD", "TTD") in engine.supported_pairs
    assert ("USD", "HTG") in engine.supported_pairs
    assert len(engine.supported_pairs) > 5