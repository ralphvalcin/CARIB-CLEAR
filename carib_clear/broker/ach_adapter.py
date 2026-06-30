# broker/ach_adapter.py
"""
CARIB-CLEAR Local ACH Adapter (Mock)

Mock adapter for local ACH/RTGS systems:
- Jamaica: JAMCLEAR-RTGS
- Barbados: BARBADOS-RTGS  
- Trinidad & Tobago: TT-RTGS
- ECCB: EC-RTGS

For buildathon: mock implementation with configurable latency/fees.
Real implementation would integrate with central bank APIs.
"""
from __future__ import annotations

import os
import time
import logging
import random
from typing import Any, Dict, List, Optional

from carib_clear.broker.base import MultiRailBroker, SettlementOrder, SettlementResult, RailInfo
from carib_clear.plugin import PluginSpec

logger = logging.getLogger(__name__)


# ─── Central Bank ACH Configs ──────────────────────────────────────
ACH_CONFIGS = {
    "JM": {  # Jamaica
        "name": "JAMCLEAR-RTGS",
        "currencies": ["JMD", "USD"],
        "min_amount_usd": 50,
        "max_amount_usd": 5_000_000,
        "fee_bps": 15,  # ~$1.50 per $10k
        "settlement_time_seconds": 3600,  # 1 hour RTGS
        "availability": 0.99,
        "operating_hours": "Mon-Fri 8:30-15:00 JST",
    },
    "BB": {  # Barbados
        "name": "BARBADOS-RTGS",
        "currencies": ["BBD", "USD"],
        "min_amount_usd": 50,
        "max_amount_usd": 3_000_000,
        "fee_bps": 20,
        "settlement_time_seconds": 7200,  # 2 hours
        "availability": 0.98,
        "operating_hours": "Mon-Fri 8:00-14:00 AST",
    },
    "TT": {  # Trinidad & Tobago
        "name": "TT-RTGS",
        "currencies": ["TTD", "USD"],
        "min_amount_usd": 100,
        "max_amount_usd": 10_000_000,
        "fee_bps": 25,
        "settlement_time_seconds": 10800,  # 3 hours
        "availability": 0.97,
        "operating_hours": "Mon-Fri 8:00-14:30 AST",
    },
    "ECCB": {  # Eastern Caribbean Currency Union
        "name": "EC-RTGS",
        "currencies": ["XCD", "USD"],
        "min_amount_usd": 25,
        "max_amount_usd": 2_000_000,
        "fee_bps": 10,
        "settlement_time_seconds": 1800,  # 30 min
        "availability": 0.99,
        "operating_hours": "Mon-Fri 8:00-15:00 AST",
    },
}

CURRENCY_TO_JURISDICTION = {
    "JMD": "JM", "BBD": "BB", "TTD": "TT", "XCD": "ECCB", "USD": "JM",
}

# Mock FX rates (would come from central bank or Reuters/Bloomberg)
MOCK_ACH_RATES = {
    ("BBD", "USD"): 0.5, ("USD", "BBD"): 2.0,
    ("JMD", "USD"): 0.0065, ("USD", "JMD"): 154.0,
    ("TTD", "USD"): 0.147, ("USD", "TTD"): 6.8,
    ("XCD", "USD"): 0.37, ("USD", "XCD"): 2.7,
    ("HTG", "USD"): 0.0077, ("USD", "HTG"): 130.0,
}


@PluginSpec.register("local_ach", {
    "type": "settlement_rail",
    "id": "local_ach",
    "name": "Local ACH",
    "currencies": ["BBD", "JMD", "TTD", "XCD", "USD"],
    "jurisdictions": ["BB", "JM", "TT", "ECCB"],
    "fee_bps": 20,
    "estimated_time_seconds": 7200,
    "min_amount_usd": 50,
    "max_amount_usd": 3000000,
    "description": "Local ACH/RTGS — central bank settlement, 1-3 hours",
})
class LocalACHAdapter(MultiRailBroker):
    """
    Mock Local ACH/RTGS Adapter for Caribbean central banks.
    
    For buildathon demo - simulates:
    - Batch processing windows
    - RTGS settlement times
    - Central bank fee structures
    - Operating hour restrictions
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("local_ach", config)
        self.jurisdiction = config.get("jurisdiction", "JM") if config else "JM"
        self.jurisdiction_config = ACH_CONFIGS.get(self.jurisdiction, ACH_CONFIGS["JM"])
        self.mock_failure_rate = config.get("mock_failure_rate", 0.02) if config else 0.02
        self._initialized = False
    
    @property
    def rail_info(self) -> RailInfo:
        cfg = self.jurisdiction_config
        return RailInfo(
            rail_id=f"ach_{self.jurisdiction.lower()}",
            name=cfg["name"],
            supported_currencies=cfg["currencies"],
            min_amount_usd=cfg["min_amount_usd"],
            max_amount_usd=cfg["max_amount_usd"],
            estimated_time_seconds=cfg["settlement_time_seconds"],
            fee_bps=cfg["fee_bps"],
            availability=cfg["availability"],
            jurisdictions=[self.jurisdiction],
            metadata={
                "operating_hours": cfg["operating_hours"],
                "system_type": "RTGS",
                "central_bank": cfg["name"].replace("-RTGS", ""),
            }
        )
    
    def initialize(self) -> bool:
        """Initialize ACH connection (mock)."""
        logger.info(f"[ACH-{self.jurisdiction}] Mock initialized: {self.jurisdiction_config['name']}")
        self._initialized = True
        return True
    
    def health_check(self) -> bool:
        """Simulate health check."""
        if self.config.get("mock_mode", True):
            return True
        return self._initialized and random.random() > self.mock_failure_rate
    
    def get_quote(
        self,
        from_currency: str,
        to_currency: str,
        amount: float
    ) -> Optional[Dict[str, Any]]:
        """Get FX quote via local ACH."""
        pair = (from_currency.upper(), to_currency.upper())
        
        # Check if both currencies supported
        if from_currency.upper() not in self.jurisdiction_config["currencies"]:
            return None
        if to_currency.upper() not in self.jurisdiction_config["currencies"]:
            return None
        
        rate = MOCK_ACH_RATES.get(pair)
        if not rate:
            rev_pair = (to_currency.upper(), from_currency.upper())
            rev_rate = MOCK_ACH_RATES.get(rev_pair)
            if rev_rate:
                rate = 1.0 / rev_rate
            else:
                return None
        
        return {
            "rate": rate,
            "fees_bps": self.rail_info.fee_bps,
            "estimated_time_seconds": self.rail_info.estimated_time_seconds,
            "valid_until": time.time() + 3600,
            "settlement_type": "RTGS",
            "operating_hours": self.jurisdiction_config["operating_hours"],
        }
    
    def submit_settlement(self, order: SettlementOrder) -> SettlementResult:
        """Submit settlement to local ACH (mock)."""
        start_time = time.time()
        
        if not self._initialized:
            return SettlementResult(
                order_id=order.order_id,
                success=False,
                error_message="Not initialized",
                status="failed",
            )
        
        time.sleep(0.2)
        
        if random.random() < self.mock_failure_rate:
            return SettlementResult(
                order_id=order.order_id,
                success=False,
                error_message="ACH system temporarily unavailable",
                status="failed",
                settlement_time_seconds=time.time() - start_time,
            )
        
        fees_usd = order.amount_from * self.rail_info.fee_bps / 10000
        
        return SettlementResult(
            order_id=order.order_id,
            success=True,
            fill_price=order.rate,
            fill_quantity=order.amount_to,
            fees_usd=fees_usd,
            settlement_time_seconds=time.time() - start_time,
            tx_hash=f"ACH-{self.jurisdiction}-{order.order_id}",
            status="filled",
            raw_response={
                "system": self.jurisdiction_config["name"],
                "jurisdiction": self.jurisdiction,
                "batch_id": f"BATCH-{int(time.time())}",
                "settlement_date": time.strftime("%Y-%m-%d"),
            },
        )
    
    def get_settlement_status(self, order_id: str) -> SettlementResult:
        """Check status (mock - always filled after submission)."""
        return SettlementResult(
            order_id=order_id,
            success=True,
            status="filled",
            tx_hash=f"ACH-{self.jurisdiction}-{order_id}",
        )
    
    def cancel_settlement(self, order_id: str) -> bool:
        """Cancel ACH settlement (possible before batch processing)."""
        logger.info(f"[ACH-{self.jurisdiction}] Cancellation requested for {order_id}")
        return True


# ─── Multi-Jurisdiction Factory ────────────────────────────────────
class MultiJurisdictionACH:
    """Factory for managing multiple jurisdiction ACH adapters."""
    
    def __init__(self):
        self.adapters = {
            "JM": LocalACHAdapter({"jurisdiction": "JM"}),
            "BB": LocalACHAdapter({"jurisdiction": "BB"}),
            "TT": LocalACHAdapter({"jurisdiction": "TT"}),
            "ECCB": LocalACHAdapter({"jurisdiction": "ECCB"}),
        }
        for adapter in self.adapters.values():
            adapter.initialize()
    
    def get_adapter(self, currency: str) -> Optional[LocalACHAdapter]:
        """Get ACH adapter for a currency."""
        jurisdiction = CURRENCY_TO_JURISDICTION.get(currency.upper())
        if jurisdiction:
            return self.adapters.get(jurisdiction)
        return None
    
    def get_adapter_for_pair(self, from_currency: str, to_currency: str) -> Optional[LocalACHAdapter]:
        """Get adapter that supports both currencies."""
        for adapter in self.adapters.values():
            if (from_currency.upper() in adapter.rail_info.supported_currencies and
                to_currency.upper() in adapter.rail_info.supported_currencies):
                return adapter
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ach = MultiJurisdictionACH()
    
    jm = ach.get_adapter("JMD")
    print(f"Jamaica: {jm.rail_info.name}")
    quote = jm.get_quote("JMD", "USD", 10000)
    print(f"  JMD→USD quote: {quote}")
    
    bb = ach.get_adapter("BBD")
    print(f"\nBarbados: {bb.rail_info.name}")
    quote = bb.get_quote("BBD", "USD", 5000)
    print(f"  BBD→USD quote: {quote}")
    
    from .base import SettlementOrder
    order = SettlementOrder(
        from_currency="BBD",
        to_currency="USD",
        amount_from=10000,
        amount_to=5000,
        rate=0.5,
        rail="ach_bb",
        counterparty_id="bb_hotel_001",
        jurisdiction="BB",
    )
    result = bb.submit_settlement(order)
    print(f"\nBBD Settlement: {result.status}")
    print(f"  TX: {result.tx_hash}")
    print(f"  Time: {result.settlement_time_seconds:.1f}s (mock)")
    print(f"  Fees: ${result.fees_usd:.2f}")
