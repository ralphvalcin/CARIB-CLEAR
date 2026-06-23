"""Liquidity Pool Manager — Step 4 of the CARICOM FX Swap Network.

Banks, fintechs, and institutions provide liquidity into currency-specific pools.
Dynamic spreads are calculated based on real supply/demand, depth, and concentration.
The SmartRouter queries pools for the best quote before routing to external rails.

Each pool:
  - Holds deposits from multiple liquidity providers
  - Tracks available depth per currency pair
  - Calculates dynamic spreads (wider when thin, tighter when deep)
  - Provides real-time quotes to the matching engine and router
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class LiquidityProvider:
    """A bank, fintech, or institution providing liquidity to the network."""

    provider_id: str
    name: str
    jurisdiction: str
    provider_type: str = "bank"  # "bank", "fintech", "remittance", "central_bank"
    tier: int = 1  # 1 = premier, 2 = standard, 3 = participant
    deposits: Dict[str, float] = field(default_factory=dict)
    """Currency -> amount deposited in USD equivalent."""
    total_deposited_usd: float = 0.0
    fee_discount_bps: float = 0.0  # Discount on spread for premier providers
    active: bool = True
    joined_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def currencies(self) -> List[str]:
        return list(self.deposits.keys())


@dataclass
class CurrencyPool:
    """A pool for a specific currency, aggregating all provider deposits."""

    currency: str
    total_liquidity_usd: float = 0.0
    provider_count: int = 0
    providers: Dict[str, float] = field(default_factory=dict)
    """provider_id -> amount deposited in USD."""
    utilization_rate: float = 0.0
    """0.0-1.0 — how much of available liquidity is currently committed."""

    @property
    def available_liquidity_usd(self) -> float:
        return self.total_liquidity_usd * (1.0 - self.utilization_rate)


@dataclass
class OrderBookDepth:
    """Order book depth for a currency pair at a point in time."""

    pair: Tuple[str, str]
    bid_depth_usd: float  # Total buy-side liquidity
    ask_depth_usd: float  # Total sell-side liquidity
    bid_providers: int
    ask_providers: int
    spread_bps: float
    mid_market_rate: float
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PoolQuote:
    """A quote from a liquidity pool for a specific FX conversion."""

    pair: Tuple[str, str]
    amount_usd: float
    rate: float
    spread_bps: float
    provider_count: int
    available_liquidity_usd: float
    estimated_fee_usd: float
    valid_until: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Mid-Market Rates (for buildathon — in production, from oracle/DEX)
# ─────────────────────────────────────────────────────────────────────────────

# Base mid-market rates for direct pairs
MID_MARKET_RATES: Dict[Tuple[str, str], float] = {
    ("BBD", "JMD"): 76.5, ("JMD", "BBD"): 0.0131,
    ("BBD", "TTD"): 3.4, ("TTD", "BBD"): 0.294,
    ("BBD", "XCD"): 1.35, ("XCD", "BBD"): 0.74,
    ("BBD", "USD"): 0.5, ("USD", "BBD"): 2.0,
    ("JMD", "TTD"): 0.045, ("TTD", "JMD"): 22.2,
    ("JMD", "XCD"): 0.0177, ("XCD", "JMD"): 56.5,
    ("JMD", "HTG"): 0.0084, ("HTG", "JMD"): 119.0,
    ("JMD", "USD"): 0.0065, ("USD", "JMD"): 154.0,
    ("TTD", "XCD"): 0.54, ("XCD", "TTD"): 1.85,
    ("TTD", "HTG"): 0.19, ("HTG", "TTD"): 5.26,
    ("TTD", "USD"): 0.147, ("USD", "TTD"): 6.8,
    ("XCD", "HTG"): 0.35, ("HTG", "XCD"): 2.86,
    ("XCD", "USD"): 0.37, ("USD", "XCD"): 2.7,
    ("HTG", "USD"): 0.0077, ("USD", "HTG"): 130.0,
    # Same-currency
    ("USD", "USD"): 1.0, ("BBD", "BBD"): 1.0,
    ("JMD", "JMD"): 1.0, ("TTD", "TTD"): 1.0,
    ("XCD", "XCD"): 1.0, ("HTG", "HTG"): 1.0,
}


# ─────────────────────────────────────────────────────────────────────────────
# LiquidityPoolManager
# ─────────────────────────────────────────────────────────────────────────────


class LiquidityPoolManager:
    """Manages liquidity pools for the CARICOM FX Swap Network.

    Handles:
      - Provider onboarding and deposits
      - Pool state tracking per currency
      - Dynamic spread calculation based on depth, concentration, volatility
      - Quote generation for the SmartRouter

    Acts as the internal FX market — if a pool has enough depth, the trade
    settles internally without touching external rails (Stellar/ACH/Mobile).
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._providers: Dict[str, LiquidityProvider] = {}
        self._pools: Dict[str, CurrencyPool] = {}  # currency -> pool

        # Supported currencies
        self.currencies = ["BBD", "JMD", "TTD", "XCD", "HTG", "USD"]

        # Initialize empty pools
        for ccy in self.currencies:
            self._pools[ccy] = CurrencyPool(currency=ccy)

        # Base spread (tightest possible)
        self.base_spread_bps = self.config.get("base_spread_bps", 5.0)

        # Spread formula parameters
        self.min_liquidity_usd = self.config.get("min_liquidity_usd", 10000)
        self.optimal_liquidity_usd = self.config.get("optimal_liquidity_usd", 500000)
        self.min_providers = self.config.get("min_providers", 2)

        # Track committed liquidity (amount locked in active matches)
        self._committed: Dict[str, float] = defaultdict(float)

    # ─── Provider Management ────────────────────────────────────────────

    def register_provider(
        self,
        provider_id: str,
        name: str,
        jurisdiction: str,
        provider_type: str = "bank",
        tier: int = 1,
    ) -> LiquidityProvider:
        """Register a new liquidity provider."""
        provider = LiquidityProvider(
            provider_id=provider_id,
            name=name,
            jurisdiction=jurisdiction,
            provider_type=provider_type,
            tier=tier,
        )
        self._providers[provider_id] = provider
        logger.info("[LiquidityPool] Provider registered: %s (%s, tier %d)", name, jurisdiction, tier)
        return provider

    def deposit(self, provider_id: str, currency: str, amount_usd: float) -> bool:
        """Provider deposits liquidity into a currency pool.

        Args:
            provider_id: The liquidity provider.
            currency: Currency to deposit (e.g., "BBD", "USD").
            amount_usd: Amount in USD equivalent.

        Returns:
            True if successful.
        """
        provider = self._providers.get(provider_id)
        if not provider:
            logger.warning("[LiquidityPool] Unknown provider: %s", provider_id)
            return False

        if currency not in self.currencies:
            logger.warning("[LiquidityPool] Unsupported currency: %s", currency)
            return False

        # Update provider deposit
        provider.deposits[currency] = provider.deposits.get(currency, 0) + amount_usd
        provider.total_deposited_usd += amount_usd

        # Update pool
        pool = self._pools[currency]
        pool.total_liquidity_usd += amount_usd
        pool.providers[provider_id] = pool.providers.get(provider_id, 0) + amount_usd
        pool.provider_count = len(pool.providers)

        logger.info(
            "[LiquidityPool] Deposit: %s deposited $%.0f into %s pool "
            "(total pool: $%.0f, providers: %d)",
            provider.name, amount_usd, currency,
            pool.total_liquidity_usd, pool.provider_count,
        )
        return True

    def withdraw(self, provider_id: str, currency: str, amount_usd: float) -> bool:
        """Provider withdraws liquidity from a currency pool."""
        provider = self._providers.get(provider_id)
        if not provider:
            return False

        current = provider.deposits.get(currency, 0)
        if current < amount_usd:
            logger.warning("[LiquidityPool] Insufficient deposit for withdrawal")
            return False

        pool = self._pools[currency]
        available = pool.total_liquidity_usd - self._committed[currency]
        if amount_usd > available:
            logger.warning("[LiquidityPool] Cannot withdraw — %s liquidity committed", currency)
            return False

        provider.deposits[currency] -= amount_usd
        provider.total_deposited_usd -= amount_usd
        pool.total_liquidity_usd -= amount_usd
        pool.providers[provider_id] = pool.providers.get(provider_id, 0) - amount_usd

        if pool.providers[provider_id] <= 0:
            del pool.providers[provider_id]
            pool.provider_count = len(pool.providers)

        logger.info("[LiquidityPool] Withdrawal: %s withdrew $%.0f from %s pool", provider.name, amount_usd, currency)
        return True

    # ─── Liquidity Commitment ───────────────────────────────────────────

    def commit_liquidity(self, currency: str, amount_usd: float) -> bool:
        """Lock liquidity for an active settlement. Returns False if insufficient."""
        pool = self._pools.get(currency)
        if not pool:
            return False

        available = pool.available_liquidity_usd
        if amount_usd > available:
            logger.warning("[LiquidityPool] Insufficient %s liquidity: need $%.0f, have $%.0f", currency, amount_usd, available)
            return False

        self._committed[currency] += amount_usd
        pool.utilization_rate = self._committed[currency] / pool.total_liquidity_usd if pool.total_liquidity_usd > 0 else 0
        return True

    def release_liquidity(self, currency: str, amount_usd: float) -> None:
        """Release committed liquidity after settlement completes."""
        self._committed[currency] = max(0, self._committed[currency] - amount_usd)
        pool = self._pools.get(currency)
        if pool and pool.total_liquidity_usd > 0:
            pool.utilization_rate = self._committed[currency] / pool.total_liquidity_usd

    # ─── Dynamic Spread Calculation ────────────────────────────────────

    def calculate_spread(
        self,
        from_currency: str,
        to_currency: str,
        amount_usd: float = 0,
    ) -> float:
        """Calculate dynamic spread in basis points for a currency pair.

        Spread widens when:
          - Low total liquidity in either pool
          - Few providers (concentration risk)
          - Large trade relative to available depth
          - High utilization (pool is busy)

        Spread tightens when:
          - Deep pools with many providers
          - Small trade relative to depth
          - Premier tier providers involved

        Returns:
            Spread in basis points (e.g., 5.0 = 0.05%).
        """
        from_pool = self._pools.get(from_currency)
        to_pool = self._pools.get(to_currency)

        if not from_pool or not to_pool:
            return 50.0  # Max spread for unknown pairs

        spread = self.base_spread_bps

        # 1. Liquidity depth factor (wider when shallow)
        min_liquidity = min(from_pool.available_liquidity_usd, to_pool.available_liquidity_usd)
        if min_liquidity < self.min_liquidity_usd:
            spread += 20.0  # Critical: pool too thin
        elif min_liquidity < self.optimal_liquidity_usd:
            # Interpolate: 0 at optimal, 15 at minimum
            depth_ratio = (min_liquidity - self.min_liquidity_usd) / (self.optimal_liquidity_usd - self.min_liquidity_usd)
            spread += 15.0 * (1.0 - depth_ratio)

        # 2. Provider concentration risk
        min_providers = min(from_pool.provider_count, to_pool.provider_count)
        if min_providers < self.min_providers:
            spread += 10.0  # Single-provider risk
        elif min_providers < 5:
            spread += 5.0 * (1.0 - (min_providers - self.min_providers) / 3)

        # 3. Trade size relative to depth (larger trade = wider spread)
        if amount_usd > 0 and min_liquidity > 0:
            trade_ratio = amount_usd / min_liquidity
            if trade_ratio > 0.5:
                spread += 15.0  # Very large relative to pool
            elif trade_ratio > 0.2:
                spread += 8.0
            elif trade_ratio > 0.1:
                spread += 3.0

        # 4. Utilization rate (busy pools = wider spread)
        avg_utilization = (from_pool.utilization_rate + to_pool.utilization_rate) / 2
        if avg_utilization > 0.7:
            spread += 5.0

        return round(min(spread, 50.0), 1)  # Cap at 50bps

    # ─── Quote Generation ──────────────────────────────────────────────

    def get_quote(
        self,
        from_currency: str,
        to_currency: str,
        amount_usd: float,
    ) -> Optional[PoolQuote]:
        """Get a quote for converting from_currency to to_currency.

        Returns None if the pair isn't supported or liquidity is insufficient.
        """
        pair = (from_currency, to_currency)

        # Check if pair is supported
        if pair not in MID_MARKET_RATES and (to_currency, from_currency) not in MID_MARKET_RATES:
            return None

        # Get mid-market rate
        mid_rate = MID_MARKET_RATES.get(pair)
        if mid_rate is None:
            # Invert the rate
            inverse_pair = (to_currency, from_currency)
            inverse_rate = MID_MARKET_RATES.get(inverse_pair)
            if inverse_rate:
                mid_rate = 1.0 / inverse_rate
            else:
                return None

        # Calculate spread
        spread = self.calculate_spread(from_currency, to_currency, amount_usd)

        # Build rate with spread
        # For demand (buying to_currency): rate = mid * (1 + spread/10000)
        # For supply (selling from_currency): rate = mid * (1 - spread/10000)
        rate = mid_rate * (1 + spread / 10000)

        # Check available liquidity
        from_pool = self._pools.get(from_currency)
        to_pool = self._pools.get(to_currency)
        available = min(from_pool.available_liquidity_usd if from_pool else 0,
                        to_pool.available_liquidity_usd if to_pool else 0)

        fee = amount_usd * (spread / 10000)

        return PoolQuote(
            pair=pair,
            amount_usd=amount_usd,
            rate=round(rate, 6),
            spread_bps=spread,
            provider_count=min(from_pool.provider_count if from_pool else 0,
                               to_pool.provider_count if to_pool else 0),
            available_liquidity_usd=available,
            estimated_fee_usd=round(fee, 2),
        )

    def get_order_book_depth(self, from_currency: str, to_currency: str) -> Optional[OrderBookDepth]:
        """Get order book depth for a currency pair."""
        from_pool = self._pools.get(from_currency)
        to_pool = self._pools.get(to_currency)
        if not from_pool or not to_pool:
            return None

        pair = (from_currency, to_currency)
        mid_rate = MID_MARKET_RATES.get(pair)
        if mid_rate is None:
            inverse = MID_MARKET_RATES.get((to_currency, from_currency))
            if inverse:
                mid_rate = 1.0 / inverse
            else:
                return None

        spread = self.calculate_spread(from_currency, to_currency)

        return OrderBookDepth(
            pair=pair,
            bid_depth_usd=to_pool.available_liquidity_usd,
            ask_depth_usd=from_pool.available_liquidity_usd,
            bid_providers=to_pool.provider_count,
            ask_providers=from_pool.provider_count,
            spread_bps=spread,
            mid_market_rate=mid_rate,
        )

    # ─── Statistics ─────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive pool statistics."""
        total_liquidity = sum(p.total_liquidity_usd for p in self._pools.values())
        total_available = sum(p.available_liquidity_usd for p in self._pools.values())
        total_committed = sum(self._committed.values())
        total_providers = len(self._providers)

        pool_details = {}
        for ccy, pool in sorted(self._pools.items()):
            if pool.total_liquidity_usd > 0:
                pool_details[ccy] = {
                    "total_usd": pool.total_liquidity_usd,
                    "available_usd": pool.available_liquidity_usd,
                    "providers": pool.provider_count,
                    "utilization": round(pool.utilization_rate, 3),
                }

        return {
            "total_liquidity_usd": total_liquidity,
            "total_available_usd": total_available,
            "total_committed_usd": total_committed,
            "total_providers": total_providers,
            "utilization_rate": round(total_committed / total_liquidity, 3) if total_liquidity > 0 else 0,
            "pools": pool_details,
            "currency_count": len([c for c in self._pools if self._pools[c].total_liquidity_usd > 0]),
        }

    def get_provider_summary(self) -> List[Dict[str, Any]]:
        """Get summary of all registered providers."""
        return [
            {
                "provider_id": p.provider_id,
                "name": p.name,
                "jurisdiction": p.jurisdiction,
                "type": p.provider_type,
                "tier": p.tier,
                "currencies": list(p.deposits.keys()),
                "total_deposited_usd": p.total_deposited_usd,
                "active": p.active,
            }
            for p in self._providers.values()
        ]

    # ─── Mock Data Generation ──────────────────────────────────────────

    def generate_mock_providers(self) -> List[str]:
        """Generate mock liquidity providers for the buildathon demo."""
        providers_data = [
            ("cbb_bank", "Central Bank of Barbados", "BB", "central_bank", 1),
            ("boj_bank", "Bank of Jamaica", "JM", "central_bank", 1),
            ("cbtt_bank", "Central Bank of Trinidad", "TT", "central_bank", 1),
            ("brh_bank", "Banque de la République d'Haïti", "HT", "central_bank", 1),
            ("barita_lp", "Barita Capital Markets", "JM", "bank", 1),
            ("jmmb_lp", "JMMB Group", "JM", "bank", 2),
            ("firstcaribbean_lp", "FirstCaribbean International", "BB", "bank", 1),
            ("republic_lp", "Republic Bank", "TT", "bank", 2),
            ("digicel_lp", "Digicel Remittance", "JM", "remittance", 3),
            ("western_union_lp", "Western Union Caribbean", "US", "remittance", 3),
        ]

        provider_ids = []
        for pid, name, jur, ptype, tier in providers_data:
            self.register_provider(pid, name, jur, ptype, tier)
            provider_ids.append(pid)

        # Distribute deposits across currencies
        deposits = [
            ("cbb_bank", "BBD", 2000000), ("cbb_bank", "USD", 1000000),
            ("boj_bank", "JMD", 3000000), ("boj_bank", "USD", 2000000),
            ("cbtt_bank", "TTD", 1500000), ("cbtt_bank", "USD", 1000000),
            ("brh_bank", "HTG", 500000), ("brh_bank", "USD", 300000),
            ("barita_lp", "JMD", 1000000), ("barita_lp", "USD", 500000),
            ("jmmb_lp", "JMD", 500000), ("jmmb_lp", "USD", 250000),
            ("firstcaribbean_lp", "BBD", 750000), ("firstcaribbean_lp", "USD", 500000),
            ("republic_lp", "TTD", 500000), ("republic_lp", "USD", 250000),
            ("digicel_lp", "USD", 200000), ("digicel_lp", "HTG", 200000),
            ("western_union_lp", "USD", 500000),
        ]

        for pid, ccy, amt in deposits:
            self.deposit(pid, ccy, amt)

        return provider_ids


# ─────────────────────────────────────────────────────────────────────────────
# Quick test / demo
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    mgr = LiquidityPoolManager()
    mgr.generate_mock_providers()

    print(f"\n{'='*60}")
    print("Liquidity Pool Manager — Step 4 Demo")
    print(f"{'='*60}")

    stats = mgr.get_stats()
    print(f"\nPools: {stats['currency_count']} currencies active")
    print(f"Providers: {stats['total_providers']}")
    print(f"Total Liquidity: ${stats['total_liquidity_usd']:,.0f}")
    print(f"Available: ${stats['total_available_usd']:,.0f}")

    print(f"\nPool Details:")
    for ccy, detail in sorted(stats['pools'].items()):
        bar = "█" * int(min(detail['available_usd'] / 500000, 1) * 20)
        print(f"  {ccy:4s}  ${detail['total_usd']:>9,.0f}  avail=${detail['available_usd']:>9,.0f}  "
              f"providers={detail['providers']}  util={detail['utilization']:.0%}")

    print(f"\nQuotes (BBD→JMD, $50K):")
    quote = mgr.get_quote("BBD", "JMD", 50000)
    if quote:
        print(f"  Rate: {quote.rate:.4f}")
        print(f"  Spread: {quote.spread_bps:.1f} bps")
        print(f"  Fee: ${quote.estimated_fee_usd:.2f}")
        print(f"  Available: ${quote.available_liquidity_usd:,.0f}")

    print(f"\nQuotes (HTG→USD, $5K):")
    quote = mgr.get_quote("HTG", "USD", 5000)
    if quote:
        print(f"  Rate: {quote.rate:.4f}")
        print(f"  Spread: {quote.spread_bps:.1f} bps")
        print(f"  Fee: ${quote.estimated_fee_usd:.2f}")
        print(f"  Available: ${quote.available_liquidity_usd:,.0f}")

    # Show depth
    depth = mgr.get_order_book_depth("BBD", "JMD")
    if depth:
        print(f"\nOrder Book Depth (BBD→JMD):")
        print(f"  Bid Depth: ${depth.bid_depth_usd:,.0f} ({depth.bid_providers} providers)")
        print(f"  Ask Depth: ${depth.ask_depth_usd:,.0f} ({depth.ask_providers} providers)")
        print(f"  Mid Rate: {depth.mid_market_rate:.4f}")
        print(f"  Spread: {depth.spread_bps:.1f} bps")
