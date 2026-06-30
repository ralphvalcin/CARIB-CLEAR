"""Test live Stellar path payment via adapter."""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from carib_clear.broker.stellar_adapter import StellarAdapter
from carib_clear.broker.base import SettlementOrder

adapter = StellarAdapter({"mock_mode": False})
adapter.initialize()
print("Participants:", len(adapter._participants))

order = SettlementOrder(
    order_id="live-003",
    from_currency="BBD", to_currency="JMD",
    amount_from=100, amount_to=7650, rate=76.5,
    rail="stellar_usdc",
    counterparty_id="JM_SUPPLIER",
    jurisdiction="JM",
    metadata={"source": "BB_HOTEL", "destination": "JM_SUPPLIER"},
)
result = adapter.submit_settlement(order)
print(f"Success: {result.success}")
print(f"Status: {result.status}")
print(f"TX: {result.tx_hash}")
print(f"Time: {result.settlement_time_seconds:.3f}s")
print(f"Fees: ${result.fees_usd:.6f}")
