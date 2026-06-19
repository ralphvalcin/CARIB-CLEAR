# broker/mobile_money_adapter.py
"""
CARIB-CLEAR Mobile Money Adapter (Mock)

Mock adapter for mobile money systems:
- Haiti: MonCash
- Jamaica: e-cash, QuikPay
- Barbados: mMoney
- Regional: MoMo (MTN), etc.

For buildathon: mock with instant settlement, low fees, KYC tier limits.
"""
from __future__ import annotations

import os
import time
import logging
import random
from typing import Any, Dict, List, Optional

from .base import MultiRailBroker, SettlementOrder, SettlementResult, RailInfo

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
            3: {"max_usd": 10000, "docs": ["national_id", "proof_address", "phone"]},
        },
    },
    "ecash": {  # Jamaica - NCB e-cash
        "name": "e-cash",
        "country": "JM",
        "currencies": ["JMD", "USD"],
        "min_amount_usd": 1.0,
        "max_amount_usd": 5000,
        "fee_bps": 30,
        "settlement_time_seconds": 5,
        "availability": 0.998,
        "kyc_tiers": {
            1: {"max_usd": 500, "docs": ["phone"]},
            2: {"max_usd": 5000, "docs": ["trn", "national_id", "phone"]},
            3: {"max_usd": 25000, "docs": ["trn", "national_id", "proof_address", "phone"]},
        },
    },
    "mmoney": {  # Barbados - mMoney
        "name": "mMoney",
        "country": "BB",
        "currencies": ["BBD", "USD"],
        "min_amount_usd": 1.0,
        "max_amount_usd": 3000,
        "fee_bps": 25,
        "settlement_time_seconds": 10,
        "availability": 0.99,
        "kyc_tiers": {
            1: {"max_usd": 250, "docs": ["phone"]},
            2: {"max_usd": 3000, "docs": ["national_id", "phone"]},
        },
    },
    "quickpay": {  # Jamaica - QuikPay
        "name": "QuikPay",
        "country": "JM",
        "currencies": ["JMD", "USD"],
        "min_amount_usd": 1.0,
        "max_amount_usd": 3000,
        "fee_bps": 40,
        "settlement_time_seconds": 10,
        "availability": 0.99,
        "kyc_tiers": {
            1: {"max_usd": 250, "docs": ["phone"]},
            2: {"max_usd": 3000, "docs": ["trn", "national_id", "phone"]},
        },
    },
}

CURRENCY_TO_PROVIDER = {
    "HTG": "moncash", "USD": "moncash",
    "JMD": "ecash",  # Would also have quickpay
    "BBD": "mmoney",
    "TTD": "quickpay",  # Would have local provider
}

MOCK_MM_RATES = {
    ("HTG", "USD"): 0.0077, ("USD", "HTG"): 130.0,
    ("JMD", "USD"): 0.0065, ("USD", "JMD"): 154.0,
    ("BBD", "USD"): 0.5, ("USD", "BBD"): 2.0,
    ("TTD", "USD"): 0.147, ("USD", "TTD"): 6.8,
    ("XCD", "USD"): 0.37, ("USD", "XCD"): 2.7,
}


class MobileMoneyAdapter(MultiRailBroker):
    """
    Mock Mobile Money Adapter for Caribbean providers.
    
    Features:
    - Instant P2P settlement
    - KYC tier-based limits
    - Phone-number based addressing
    - Agent cash-in/cash-out network
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("mobile_money", config)
        self.provider_id = config.get("provider", "moncash") if config else "moncash"
        self.provider_config = MOBILE_MONEY_CONFIGS.get(self.provider_id, MOBILE_MONEY_CONFIGS["moncash"])
        self.mock_failure_rate = config.get("mock_failure_rate", 0.01) if config else 0.01
        self._initialized = False
    
    @property
    def rail_info(self) -> RailInfo:
        cfg = self.provider_config
        return RailInfo(
            rail_id=f"mm_{self.provider_id}",
            name=cfg["name"],
            supported_currencies=cfg["currencies"],
            min_amount_usd=cfg["min_amount_usd"],
            max_amount_usd=cfg["max_amount_usd"],
            estimated_time_seconds=cfg["settlement_time_seconds"],
            fee_bps=cfg["fee_bps"],
            availability=cfg["availability"],
            jurisdictions=[cfg["country"]],
            metadata={
                "provider": cfg["name"],
                "country": cfg["country"],
                "kyc_tiers": cfg["kyc_tiers"],
                "addressing": "phone_number",
                "cash_in_out": "agent_network",
            }
        )
    
    def initialize(self) -> bool:
        """Initialize mobile money connection (mock)."""
        logger.info(f"[MobileMoney] Mock initialized: {self.provider_config['name']} ({self.provider_config['country']})")
        self._initialized = True
        return True
    
    def health_check(self) -> bool:
        """Check provider health."""
        return self._initialized and random.random() > self.mock_failure_rate
    
    def get_quote(
        self,
        from_currency: str,
        to_currency: str,
        amount: float
    ) -> Optional[Dict[str, Any]]:
        """Get FX quote for mobile money."""
        pair = (from_currency.upper(), to_currency.upper())
        
        # Check currency support
        if (from_currency.upper() not in self.provider_config["currencies"] or
            to_currency.upper() not in self.provider_config["currencies"]):
            return None
        
        # Check KYC tier limits
        if amount > self.provider_config["max_amount_usd"]:
            return {
                "rate": None,
                "error": f"Amount ${amount:,.0f} exceeds KYC tier limit ${self.provider_config['max_amount_usd']:,.0f}",
                "requires_higher_kyc": True,
            }
        
        rate = MOCK_MM_RATES.get(pair)
        if not rate:
            rev_pair = (to_currency.upper(), from_currency.upper())
            rev_rate = MOCK_MM_RATES.get(rev_pair)
            if rev_rate:
                rate = 1.0 / rev_rate
            else:
                return None
        
        return {
            "rate": rate,
            "fees_bps": self.rail_info.fee_bps,
            "estimated_time_seconds": self.rail_info.estimated_time_seconds,
            "valid_until": time.time() + 300,  # 5 min for mobile
            "max_amount_usd": self.provider_config["max_amount_usd"],
            "kyc_tier_required": self._get_required_tier(amount),
        }
    
    def _get_required_tier(self, amount: float) -> int:
        for tier in sorted(self.provider_config["kyc_tiers"].keys()):
            if amount <= self.provider_config["kyc_tiers"][tier]["max_usd"]:
                return tier
        return max(self.provider_config["kyc_tiers"].keys())
    
    def submit_settlement(self, order: SettlementOrder) -> SettlementResult:
        """Submit mobile money P2P transfer."""
        start_time = time.time()
        
        if not self._initialized:
            return SettlementResult(
                order_id=order.order_id,
                success=False,
                error_message="Not initialized",
                status="failed",
            )
        
        # Check amount limits
        if order.amount_from > self.provider_config["max_amount_usd"]:
            return SettlementResult(
                order_id=order.order_id,
                success=False,
                error_message=f"Amount ${order.amount_from:,.0f} exceeds max ${self.provider_config['max_amount_usd']:,.0f} for this KYC tier",
                status="failed",
            )
        
        # Simulate processing
        time.sleep(0.05)  # Mobile is fast
        
        # Random failure
        if random.random() < self.mock_failure_rate:
            return SettlementResult(
                order_id=order.order_id,
                success=False,
                error_message="Mobile money network temporarily busy",
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
            tx_hash=f"MM-{self.provider_id.upper()}-{order.order_id}",
            status="filled",
            raw_response={
                "provider": self.provider_config["name"],
                "country": self.provider_config["country"],
                "sender_phone": order.metadata.get("sender_phone", "+1876XXXXXXX"),
                "recipient_phone": order.metadata.get("recipient_phone", "+1876YYYYYYY"),
                "kyc_tier": self._get_required_tier(order.amount_from),
            },
        )
    
    def get_settlement_status(self, order_id: str) -> SettlementResult:
        """Check mobile money transfer status."""
        return SettlementResult(
            order_id=order_id,
            success=True,
            status="filled",
            tx_hash=f"MM-{self.provider_id.upper()}-{order_id}",
        )
    
    def cancel_settlement(self, order_id: str) -> bool:
        """Cancel mobile money transfer (only if pending)."""
        logger.info(f"[MobileMoney-{self.provider_id}] Cancellation requested: {order_id}")
        return False  # Usually instant, can't cancel


# ─── Multi-Provider Factory ────────────────────────────────────────
class MultiProviderMobileMoney:
    """Manage multiple mobile money providers."""
    
    def __init__(self):
        self.providers = {
            "moncash": MobileMoneyAdapter({"provider": "moncash"}),
            "ecash": MobileMoneyAdapter({"provider": "ecash"}),
            "mmoney": MobileMoneyAdapter({"provider": "mmoney"}),
            "quickpay": MobileMoneyAdapter({"provider": "quickpay"}),
        }
        for p in self.providers.values():
            p.initialize()
    
    def get_provider(self, currency: str) -> Optional[MobileMoneyAdapter]:
        """Get provider for a currency."""
        provider_id = CURRENCY_TO_PROVIDER.get(currency.upper())
        if provider_id:
            return self.providers.get(provider_id)
        return None
    
    def get_best_provider(self, from_currency: str, to_currency: str, amount_usd: float) -> Optional[MobileMoneyAdapter]:
        """Find provider supporting both currencies with sufficient limit."""
        for provider in self.providers.values():
            if (from_currency.upper() in provider.rail_info.supported_currencies and
                to_currency.upper() in provider.rail_info.supported_currencies and
                amount_usd <= provider.provider_config["max_amount_usd"]):
                return provider
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    mm = MultiProviderMobileMoney()
    
    # Test MonCash (Haiti)
    mc = mm.get_provider("HTG")
    print(f"Haiti: {mc.rail_info.name}")
    quote = mc.get_quote("HTG", "USD", 500)
    print(f"  HTG→USD $500: {quote}")
    
    # Test e-cash (Jamaica)
    ec = mm.get_provider("JMD")
    print(f"\nJamaica: {ec.rail_info.name}")
    quote = ec.get_quote("JMD", "USD", 2000)
    print(f"  JMD→USD $2k: {quote}")
    
    # Test settlement
    from .base import SettlementOrder
    order = SettlementOrder(
        from_currency="HTG",
        to_currency="USD",
        amount_from=65000,  # HTG
        amount_to=500,      # USD
        rate=130.0,
        rail="mm_moncash",
        counterparty_id="ht_artisan_001",
        jurisdiction="HT",
        metadata={"recipient_phone": "+509XXXXXXXX"},
    )
    result = mc.submit_settlement(order)
    print(f"\nMonCash Settlement: {result.status}")
    print(f"  TX: {result.tx_hash}")
    print(f"  Time: {result.settlement_time_seconds:.2f}s")
    print(f"  Fees: ${result.fees_usd:.2f}")