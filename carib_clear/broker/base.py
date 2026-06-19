# broker/base.py
"""
CARIB-CLEAR Multi-Rail Broker Abstraction

Extracted from trading-system/data/alpaca_connector.py and agents/execution.py
Abstract base class for multi-rail settlement (Stellar, ACH, Mobile Money, etc.)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class SettlementOrder:
    """Order to be executed on a settlement rail."""
    order_id: str = field(default_factory=lambda: f"carib-{uuid4().hex[:12]}")
    from_currency: str = ""
    to_currency: str = ""
    amount_from: float = 0.0
    amount_to: float = 0.0
    rate: float = 0.0
    rail: str = ""
    counterparty_id: str = ""
    jurisdiction: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "amount_from": self.amount_from,
            "amount_to": self.amount_to,
            "rate": self.rate,
            "rail": self.rail,
            "counterparty_id": self.counterparty_id,
            "jurisdiction": self.jurisdiction,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class SettlementResult:
    """Result of a settlement execution."""
    order_id: str
    success: bool
    fill_price: Optional[float] = None
    fill_quantity: Optional[float] = None
    fees_usd: float = 0.0
    settlement_time_seconds: float = 0.0
    tx_hash: Optional[str] = None
    status: str = "pending"  # pending, filled, partial, failed, cancelled
    error_message: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)
    completed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "success": self.success,
            "fill_price": self.fill_price,
            "fill_quantity": self.fill_quantity,
            "fees_usd": self.fees_usd,
            "settlement_time_seconds": self.settlement_time_seconds,
            "tx_hash": self.tx_hash,
            "status": self.status,
            "error_message": self.error_message,
            "raw_response": self.raw_response,
            "completed_at": self.completed_at,
        }


@dataclass
class RailInfo:
    """Information about a settlement rail."""
    rail_id: str
    name: str
    supported_currencies: List[str]
    min_amount_usd: float
    max_amount_usd: Optional[float]
    estimated_time_seconds: int
    fee_bps: float
    availability: float = 1.0  # 0.0-1.0
    jurisdictions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class MultiRailBroker(ABC):
    """
    Abstract base class for multi-rail settlement brokers.
    
    Subclasses implement specific rails:
    - Stellar/USDC
    - Local ACH (Jamaica, Barbados, Trinidad, ECCB)
    - Mobile Money (MonCash, e-cash, etc.)
    - RTGS/Central Bank
    """
    
    def __init__(self, rail_id: str, config: Optional[Dict[str, Any]] = None):
        self.rail_id = rail_id
        self.config = config or {}
        self._initialized = False
    
    @property
    @abstractmethod
    def rail_info(self) -> RailInfo:
        """Return rail metadata."""
        pass
    
    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the rail connection. Returns True on success."""
        pass
    
    @abstractmethod
    def health_check(self) -> bool:
        """Check if rail is operational."""
        pass
    
    @abstractmethod
    def get_quote(
        self,
        from_currency: str,
        to_currency: str,
        amount: float
    ) -> Optional[Dict[str, Any]]:
        """
        Get a quote for FX conversion.
        
        Returns dict with: rate, fees_bps, estimated_time_seconds, valid_until
        Returns None if pair not supported.
        """
        pass
    
    @abstractmethod
    def submit_settlement(self, order: SettlementOrder) -> SettlementResult:
        """Submit a settlement order. Blocks until completion or timeout."""
        pass
    
    @abstractmethod
    def get_settlement_status(self, order_id: str) -> SettlementResult:
        """Get status of a settlement order."""
        pass
    
    @abstractmethod
    def cancel_settlement(self, order_id: str) -> bool:
        """Cancel a pending settlement. Returns True if cancelled."""
        pass
    
    def estimate_cost(
        self,
        from_currency: str,
        to_currency: str,
        amount_usd: float
    ) -> Optional[Dict[str, float]]:
        """Estimate total cost including fees."""
        quote = self.get_quote(from_currency, to_currency, amount_usd)
        if not quote:
            return None
        
        rate = quote.get("rate", 0)
        fees_bps = quote.get("fees_bps", 0)
        fees_usd = amount_usd * fees_bps / 10000
        
        return {
            "rate": rate,
            "fees_usd": fees_usd,
            "fees_bps": fees_bps,
            "total_usd": amount_usd + fees_usd,
            "estimated_time_seconds": quote.get("estimated_time_seconds", 300),
        }
    
    def is_available(self, currency: str) -> bool:
        """Check if rail supports a currency."""
        return currency in self.rail_info.supported_currencies
    
    def supports_pair(self, from_currency: str, to_currency: str) -> bool:
        """Check if rail supports the currency pair."""
        # Most rails support any pair within their currencies
        # but some may have restrictions
        return (self.is_available(from_currency) and 
                self.is_available(to_currency))


class MultiRailRouter:
    """
    Smart router that selects the best rail for a settlement.
    
    Factors: cost, speed, availability, jurisdiction compliance
    """
    
    def __init__(self, brokers: List[MultiRailBroker]):
        self.brokers = {b.rail_id: b for b in brokers}
    
    def find_best_rail(
        self,
        from_currency: str,
        to_currency: str,
        amount_usd: float,
        jurisdiction: str = "",
        priority: str = "cost"  # cost, speed, reliability
    ) -> Optional[MultiRailBroker]:
        """Find the best rail for a settlement."""
        candidates = []
        
        for broker in self.brokers.values():
            if not broker.supports_pair(from_currency, to_currency):
                continue
            
            # Check jurisdiction support
            if jurisdiction and jurisdiction not in broker.rail_info.jurisdictions:
                continue
            
            cost = broker.estimate_cost(from_currency, to_currency, amount_usd)
            if not cost:
                continue
            
            health = broker.health_check()
            if not health:
                continue
            
            candidates.append((broker, cost))
        
        if not candidates:
            return None
        
        # Score based on priority
        if priority == "cost":
            # Lowest total cost (amount + fees)
            candidates.sort(key=lambda x: x[1]["total_usd"])
        elif priority == "speed":
            # Fastest settlement
            candidates.sort(key=lambda x: x[1]["estimated_time_seconds"])
        elif priority == "reliability":
            # Highest availability * health
            candidates.sort(key=lambda x: -x[0].rail_info.availability)
        else:
            # Balanced: cost * time
            candidates.sort(key=lambda x: x[1]["total_usd"] * x[1]["estimated_time_seconds"])
        
        return candidates[0][0]
    
    def get_all_quotes(
        self,
        from_currency: str,
        to_currency: str,
        amount_usd: float
    ) -> List[Dict[str, Any]]:
        """Get quotes from all available rails."""
        results = []
        for broker in self.brokers.values():
            if not broker.supports_pair(from_currency, to_currency):
                continue
            cost = broker.estimate_cost(from_currency, to_currency, amount_usd)
            if cost:
                results.append({
                    "rail_id": broker.rail_id,
                    "rail_name": broker.rail_info.name,
                    **cost,
                    "availability": broker.rail_info.availability,
                })
        return results


if __name__ == "__main__":
    # Demo
    print("MultiRailBroker base class ready")
    print("Implement concrete adapters:")
    print("  - StellarAdapter")
    print("  - LocalACHAdapter (JM, BB, TT, ECCB)")
    print("  - MobileMoneyAdapter (MonCash, e-cash, etc.)")