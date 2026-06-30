# broker/mobile_money_adapter.py
"""
CARIB-CLEAR Mobile Money Adapter (Mock)

Mock adapter for Caribbean mobile money platforms:
- Haiti: MonCash (Digicel)
- Jamaica: JMMB Money, NCB Mobile
- Trinidad: TSTT bMobile

For buildathon: mock implementation with configurable latency/fees.
"""
from __future__ import annotations

import os
import time
import logging
import random
from typing import Any, Dict, Optional

from carib_clear.broker.base import MultiRailBroker, SettlementOrder, SettlementResult, RailInfo
from carib_clear.plugin import PluginSpec

logger = logging.getLogger(__name__)


# ─── Mobile Money Provider Configs ─────────────────────────────────
MOBILE_MONEY_CONFIGS = {
    "moncash": {  # Haiti - Digicel MonCash
        "name": "MonCash",
        "country": "HT",
        "currencies": ["HTG", "USD"],
        "min_amount_usd": 0.50,
        "max_amount_usd": 2500,  # Tier 2 KYC limit
        "fee_bps": 50,  # 0.5% for P2P
        "settlement_time_seconds": 10,  # Instant
        "availability": 0.995,
        "kyc_tiers": {
            1: {"max_usd": 100, "docs": ["phone"]},
            2: {"max_usd": 2500, "docs": ["national_id", "phone"]},
        },
    },
    "jmmb_money": {  # Jamaica
        "name": "JMMB Money",
        "country": "JM",
        "currencies": ["JMD", "USD"],
        "min_amount_usd": 1,
        "max_amount_usd": 5000,
        "fee_bps": 35,
        "settlement_time_seconds": 5,
        "availability": 0.99,
        "kyc_tiers": {
            1: {"max_usd": 500, "docs": ["phone", "name"]},
            2: {"max_usd": 5000, "docs": ["national_id", "phone", "address"]},
        },
    },
    "bmobile": {  # Trinidad
        "name": "bMobile",
        "country": "TT",
        "currencies": ["TTD", "USD"],
        "min_amount_usd": 0.50,
        "max_amount_usd": 3000,
        "fee_bps": 40,
        "settlement_time_seconds": 8,
        "availability": 0.985,
        "kyc_tiers": {
            1: {"max_usd": 300, "docs": ["phone"]},
            2: {"max_usd": 3000, "docs": ["national_id", "phone"]},
        },
    },
}


@PluginSpec.register("mobile_money", {
    "type": "settlement_rail",
    "id": "mobile_money",
    "name": "Mobile Money",
    "currencies": ["HTG", "USD"],
    "jurisdictions": ["HT"],
    "fee_bps": 50,
    "estimated_time_seconds": 10,
    "min_amount_usd": 0.50,
    "max_amount_usd": 2500,
    "description": "Mobile money — MonCash (Haiti), JMMB Money (Jamaica), bMobile (Trinidad)",
})
class MobileMoneyAdapter(MultiRailBroker):
    """
    Mock Mobile Money Adapter for Caribbean mobile wallets.
    
    Supports multiple mobile money providers:
    - MonCash (Haiti) - Digicel's mobile money platform
    - JMMB Money (Jamaica) - JMMB's mobile wallet
    - bMobile (Trinidad) - TSTT mobile wallet
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("mobile_money", config)
        self.provider_name = config.get("provider", "moncash") if config else "moncash"
        self.provider_config = MOBILE_MONEY_CONFIGS.get(self.provider_name, MOBILE_MONEY_CONFIGS["moncash"])
        self.mock_failure_rate = config.get("mock_failure_rate", 0.02) if config else 0.02
        self._initialized = False
    
    @property
    def rail_info(self) -> RailInfo:
        cfg = self.provider_config
        return RailInfo(
            rail_id=f"mm_{self.provider_name}",
            name=cfg["name"],
            supported_currencies=cfg["currencies"],
            min_amount_usd=cfg["min_amount_usd"],
            max_amount_usd=cfg["max_amount_usd"],
            estimated_time_seconds=cfg["settlement_time_seconds"],
            fee_bps=cfg["fee_bps"],
            availability=cfg["availability"],
            jurisdictions=[cfg["country"]],
            metadata={
                "provider": self.provider_name,
                "kyc_tiers": cfg["kyc_tiers"],
            }
        )
    
    def initialize(self) -> bool:
        """Initialize mobile money connection (mock)."""
        logger.info(f"[MobileMoney-{self.provider_name}] Mock initialized: {self.provider_config['name']}")
        self._initialized = True
        return True
    
    def health_check(self) -> bool:
        """Check provider health."""
        if self.config.get("mock_mode", True):
            return True
        return self._initialized and random.random() > self.mock_failure_rate
    
    def get_quote(
        self,
        from_currency: str,
        to_currency: str,
        amount: float
    ) -> Optional[Dict[str, Any]]:
        """Get FX quote for mobile money."""
        pair = (from_currency.upper(), to_currency.upper())
        
        if from_currency.upper() not in self.provider_config["currencies"]:
            return None
        if to_currency.upper() not in self.provider_config["currencies"]:
            return None
        
        # Mobile money uses provider's FX rate
        from carib_clear.broker.ach_adapter import MOCK_ACH_RATES
        rate = MOCK_ACH_RATES.get(pair)
        if not rate:
            rev_pair = (to_currency.upper(), from_currency.upper())
            rev_rate = MOCK_ACH_RATES.get(rev_pair)
            if rev_rate:
                rate = 1.0 / rev_rate
            else:
                return None
        
        # Add mobile money markup
        rate *= (1 - self.rail_info.fee_bps / 10000)
        
        return {
            "rate": rate,
            "fees_bps": self.rail_info.fee_bps,
            "estimated_time_seconds": self.rail_info.estimated_time_seconds,
            "valid_until": time.time() + 300,
            "provider": self.provider_name,
            "kyc_tier": 1 if amount < 100 else 2,
        }
    
    def submit_settlement(self, order: SettlementOrder) -> SettlementResult:
        """Submit mobile money settlement (mock)."""
        start_time = time.time()
        
        if not self._initialized:
            return SettlementResult(
                order_id=order.order_id,
                success=False,
                error_message="Not initialized",
                status="failed",
            )
        
        time.sleep(0.1)
        
        if random.random() < self.mock_failure_rate:
            return SettlementResult(
                order_id=order.order_id,
                success=False,
                error_message=f"{self.provider_config['name']} service temporarily unavailable",
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
            tx_hash=f"MM-{self.provider_name}-{order.order_id}",
            status="filled",
            raw_response={
                "provider": self.provider_config["name"],
                "reference": f"MM-{int(time.time())}",
                "settlement_method": "mobile_wallet",
                "fee": fees_usd,
            },
        )
    
    def get_settlement_status(self, order_id: str) -> SettlementResult:
        """Check mobile money settlement status (mock)."""
        return SettlementResult(
            order_id=order_id,
            success=True,
            status="filled",
            tx_hash=f"MM-{self.provider_name}-{order_id}",
        )
    
    def cancel_settlement(self, order_id: str) -> bool:
        """Cancel mobile money settlement (usually possible within 30s)."""
        logger.info(f"[MobileMoney-{self.provider_name}] Cancellation requested for {order_id}")
        return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    for provider in ["moncash", "jmmb_money", "bmobile"]:
        mm = MobileMoneyAdapter({"provider": provider})
        mm.initialize()
        print(f"\n{mm.rail_info.name}:")
        print(f"  Currencies: {mm.rail_info.supported_currencies}")
        print(f"  Fee: {mm.rail_info.fee_bps} bps")
        print(f"  Max: ${mm.rail_info.max_amount_usd:,}")
        
        quote = mm.get_quote("USD", "HTG", 100)
        if quote:
            print(f"  USD→HTG rate: {quote['rate']:.4f}")
