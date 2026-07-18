"""Tests for CARIB-CLEAR settlement idempotency and persistence."""

from __future__ import annotations

import pytest

from carib_clear.broker.stellar_adapter import StellarAdapter
from carib_clear.broker.base import SettlementOrder
from carib_clear.db import reset_db
from carib_clear import settlement as settlement_lifecycle


def test_mock_settlement_is_idempotent():
    adapter = StellarAdapter({"mock_mode": True})
    adapter.initialize()
    order = SettlementOrder(
        order_id="mock-idempotency-1",
        from_currency="BBD",
        to_currency="JMD",
        amount_from=1000,
        amount_to=1538,
        rate=1.538,
        rail="stellar_usdc",
        counterparty_id="jm_counterpart",
        jurisdiction="JM",
    )

    first = adapter.submit_settlement(order)
    second = adapter.submit_settlement(order)
    assert first.status == second.status == "filled"
    assert first.tx_hash == second.tx_hash == "0xmock-idempotency-1stellar"


def test_live_settlement_records_status_flow():
    reset_db(db_path=":memory:")
    adapter = StellarAdapter({"mock_mode": True})
    adapter.initialize()
    order = SettlementOrder(
        order_id="mock-flow-1",
        from_currency="USD",
        to_currency="JMD",
        amount_from=100,
        amount_to=15400,
        rate=154,
        rail="stellar_usdc",
        counterparty_id="jm_counterpart",
        jurisdiction="JM",
    )

    first = adapter.submit_settlement(order)
    second = adapter.submit_settlement(order)
    assert first.status == "filled"
    assert second.status == "filled"
    assert first.tx_hash == second.tx_hash == "0xmock-flow-1stellar"


def test_settlement_idempotent_record_creates_row_once():
    reset_db(db_path=":memory:")
    payload = {
        "amount_usd": 500,
        "currency_from": "BBD",
        "currency_to": "JMD",
        "amount_from": 250,
        "amount_to": 385,
        "rate": 1.54,
        "fees_usd": 0.05,
        "rail": "stellar_usdc",
        "order_id": "record-1",
        "raw_response": {"mock": True},
    }
    first = settlement_lifecycle.submit("stellar_usdc", "record-1", "fx", payload)
    second = settlement_lifecycle.submit("stellar_usdc", "record-1", "fx", payload)
    assert first["settlement_id"] == second["settlement_id"] == "stellar_usdc:record-1"
    assert first["status"] == second["status"] == "pending"


def test_settlement_complete_transitions_to_filled():
    reset_db(db_path=":memory:")
    settlement_lifecycle.submit(
        "stellar_usdc",
        "record-2",
        "fx",
        {
            "amount_usd": 500,
            "currency_from": "BBD",
            "currency_to": "JMD",
            "amount_from": 250,
            "amount_to": 385,
            "rate": 1.54,
            "fees_usd": 0.05,
            "rail": "stellar_usdc",
        },
    )
    finalized = settlement_lifecycle.complete(
        "stellar_usdc",
        "record-2",
        {
            "success": True,
            "tx_hash": "tx-abc",
            "raw_response": {"successful": True},
        },
    )
    assert finalized["status"] == "filled"
    claim = settlement_lifecycle.get_settlement("stellar_usdc:record-2")
    assert claim is not None
    assert claim["status"] == "filled"


def test_settlement_forward_only_transitions():
    reset_db(db_path=":memory:")
    settlement_lifecycle.submit(
        "stellar_usdc",
        "transition-1",
        "fx",
        {
            "amount_usd": 500,
            "currency_from": "BBD",
            "currency_to": "JMD",
            "amount_from": 250,
            "amount_to": 385,
            "rate": 1.54,
            "fees_usd": 0.05,
            "rail": "stellar_usdc",
        },
    )
    filled = settlement_lifecycle.transition_to(
        "stellar_usdc:transition-1",
        settlement_lifecycle.SettlementStatus.FILLED,
        {"success": True, "tx_hash": "tx-fill"},
    )
    assert filled["status"] == "filled"
    with pytest.raises(ValueError):
        settlement_lifecycle.transition_to(
            "stellar_usdc:transition-1",
            settlement_lifecycle.SettlementStatus.CANCELLED,
        )
