"""Tests for broker adapters (Stellar, ACH, MobileMoney) and MultiRailRouter."""

from __future__ import annotations

from carib_clear.broker.base import MultiRailRouter, SettlementOrder
from carib_clear.broker.stellar_adapter import StellarAdapter
from carib_clear.broker.ach_adapter import LocalACHAdapter
from carib_clear.broker.mobile_money_adapter import MobileMoneyAdapter


def _order(
    oid="test-001", fc="BBD", tc="JMD",
    af=50000, at=50000, rate=76.5,
) -> SettlementOrder:
    return SettlementOrder(
        order_id=oid, from_currency=fc, to_currency=tc,
        amount_from=af, amount_to=at, rate=rate,
        rail="mock", counterparty_id="cp", jurisdiction="BB",
    )


def test_stellar_init() -> None:
    a = StellarAdapter({"mock_mode": True})
    assert a.rail_id == "stellar_usdc"


def test_stellar_health() -> None:
    assert StellarAdapter({"mock_mode": True}).health_check() is True


def test_stellar_quote_has_rate() -> None:
    q = StellarAdapter({"mock_mode": True}).get_quote("BBD", "JMD", 50000)
    assert q is not None and q.get("rate", 0) > 0


def test_stellar_submit() -> None:
    r = StellarAdapter({"mock_mode": True}).submit_settlement(_order())
    assert r.success is True
    assert r.tx_hash is not None


def test_stellar_rail_info() -> None:
    info = StellarAdapter({"mock_mode": True}).rail_info
    assert info.rail_id == "stellar_usdc"
    assert info.estimated_time_seconds < 60


def test_ach_init_and_submit() -> None:
    a = LocalACHAdapter({"mock_mode": True})
    a.initialize()
    assert a.rail_id == "local_ach"
    assert a.health_check() is True
    r = a.submit_settlement(_order(
        oid="ach-01", fc="BBD", tc="BBD", af=25000, at=25000, rate=1.0))
    assert r.success is True


def test_mm_init_and_submit() -> None:
    a = MobileMoneyAdapter({"mock_mode": True})
    a.initialize()
    assert a.rail_id == "mobile_money"
    assert a.health_check() is True
    r = a.submit_settlement(_order(
        oid="mm-01", fc="HTG", tc="HTG", af=500, at=500, rate=1.0))
    assert r.success is True


def test_router_init() -> None:
    router = MultiRailRouter([StellarAdapter({"mock_mode": True})])
    assert len(router.brokers) == 1


def test_router_multi_broker() -> None:
    router = MultiRailRouter([
        LocalACHAdapter({"mock_mode": True}),
        StellarAdapter({"mock_mode": True}),
    ])
    assert len(router.brokers) == 2


def test_stellar_faster_than_ach() -> None:
    ach = LocalACHAdapter({"mock_mode": True})
    stellar = StellarAdapter({"mock_mode": True})
    assert stellar.rail_info.estimated_time_seconds < ach.rail_info.estimated_time_seconds