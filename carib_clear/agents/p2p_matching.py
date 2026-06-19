# agents/p2p_matching.py
"""
CARIB-CLEAR P2P Matching Engine

Core matching engine for direct FX settlement without USD bridge.
Matches opposing currency needs and executes atomic settlements.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from carib_clear.governance.agent import GovernanceAgent
from carib_clear.agents.flow_visibility import FlowVisibilityAgent, MatchingOpportunity
from carib_clear.broker.base import MultiRailBroker, MultiRailRouter, SettlementOrder, SettlementResult

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result of a P2P match execution."""
    match_id: str
    opportunity_id: str
    demand_order_id: str
    supply_order_id: str
    settled_amount_usd: float
    settlement_rate: float
    rail_used: str
    settlement_result: SettlementResult
    governance_decision: Any
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class OrderBookEntry:
    """Order in the matching engine book."""
    order_id: str
    currency_from: str
    currency_to: str
    amount_usd: float
    max_rate: Optional[float]  # Max rate willing to pay (for demand)
    min_rate: Optional[float]  # Min rate willing to accept (for supply)
    side: str  # "demand" or "supply"
    participant_id: str
    jurisdiction: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "open"  # open, matched, filled, cancelled


class P2PMatchingEngine:
    """
    P2P Matching Engine - The "heart" of the CARICOM FX Swap Network.
    
    Features:
    - Direct currency matching (no USD bridge required)
    - Price-time priority order book
    - Multi-currency support (BBD, JMD, TTD, XCD, HTG, USD)
    - Integration with governance for compliance
    - Multi-rail settlement routing
    """
    
    def __init__(
        self,
        governance_agent: GovernanceAgent,
        router: MultiRailRouter,
        config: Optional[Dict[str, Any]] = None
    ):
        self.governance = governance_agent
        self.router = router
        self.config = config or {}
        
        # Order books (in-memory for buildathon; would be Redis/DB in production)
        self.demand_book: Dict[str, List[OrderBookEntry]] = {}  # by currency pair
        self.supply_book: Dict[str, List[OrderBookEntry]] = {}
        
        # Match history
        self.match_history: List[MatchResult] = []
        
        # Supported pairs
        self.supported_pairs = [
            ("BBD", "JMD"), ("BBD", "TTD"), ("BBD", "XCD"),
            ("JMD", "TTD"), ("JMD", "XCD"), ("JMD", "HTG"),
            ("TTD", "XCD"), ("TTD", "HTG"),
            ("XCD", "HTG"),
            ("USD", "BBD"), ("USD", "JMD"), ("USD", "TTD"),
            ("USD", "XCD"), ("USD", "HTG"),
        ]
    
    def _get_book_key(self, from_currency: str, to_currency: str) -> str:
        """Get normalized book key for currency pair."""
        # Normalize: always store as stronger currency first
        return f"{from_currency}/{to_currency}"
    
    def submit_demand_order(
        self,
        *,
        currency_from: str,
        currency_to: str,
        amount_usd: float,
        max_rate: float,
        participant_id: str,
        jurisdiction: str
    ) -> OrderBookEntry:
        """Submit a demand order (need to BUY currency_to, SELL currency_from)."""
        key = self._get_book_key(currency_from, currency_to)
        
        order = OrderBookEntry(
            order_id=f"demand-{uuid.uuid4().hex[:12]}",
            currency_from=currency_from,
            currency_to=currency_to,
            amount_usd=amount_usd,
            max_rate=max_rate,
            min_rate=None,
            side="demand",
            participant_id=participant_id,
            jurisdiction=jurisdiction,
        )
        
        if key not in self.demand_book:
            self.demand_book[key] = []
        self.demand_book[key].append(order)
        
        # Sort by price-time priority (best rate first, then time)
        self.demand_book[key].sort(key=lambda o: (-o.max_rate, o.created_at))
        
        logger.info(f"[P2PMatching] Demand order: {order.currency_from}→{order.currency_to} "
                    f"${amount_usd:,.0f} @ max {max_rate:.4f} by {participant_id}")
        
        return order
    
    def submit_supply_order(
        self,
        *,
        currency_from: str,
        currency_to: str,
        amount_usd: float,
        min_rate: float,
        participant_id: str,
        jurisdiction: str
    ) -> OrderBookEntry:
        """Submit a supply order (need to SELL currency_from, BUY currency_to)."""
        key = self._get_book_key(currency_from, currency_to)
        
        order = OrderBookEntry(
            order_id=f"supply-{uuid.uuid4().hex[:12]}",
            currency_from=currency_from,
            currency_to=currency_to,
            amount_usd=amount_usd,
            max_rate=None,
            min_rate=min_rate,
            side="supply",
            participant_id=participant_id,
            jurisdiction=jurisdiction,
        )
        
        if key not in self.supply_book:
            self.supply_book[key] = []
        self.supply_book[key].append(order)
        
        # Sort by price-time priority (best rate first, then time)
        self.supply_book[key].sort(key=lambda o: (o.min_rate, o.created_at))
        
        logger.info(f"[P2PMatching] Supply order: {order.currency_from}→{order.currency_to} "
                    f"${amount_usd:,.0f} @ min {min_rate:.4f} by {participant_id}")
        
        return order
    
    def match_orders(self, currency_from: str, currency_to: str) -> List[MatchResult]:
        """
        Match demand and supply orders for a currency pair.
        
        Uses price-time priority: best price first, then earliest timestamp.
        """
        key = self._get_book_key(currency_from, currency_to)
        
        demand_orders = [o for o in self.demand_book.get(key, []) if o.status == "open"]
        supply_orders = [o for o in self.supply_book.get(key, []) if o.status == "open"]
        
        matches = []
        
        for demand in demand_orders:
            if demand.status != "open":
                continue
                
            for supply in supply_orders:
                if supply.status != "open":
                    continue
                
                # Check if rates cross (demand max >= supply min)
                if demand.max_rate is None or supply.min_rate is None:
                    continue
                if demand.max_rate < supply.min_rate:
                    break  # No more matches possible at this price level
                
                # Determine match amount
                match_amount = min(demand.amount_usd, supply.amount_usd)
                
                # Determine settlement rate (mid-point)
                settlement_rate = (demand.max_rate + supply.min_rate) / 2.0
                
                # Execute match
                match_result = self._execute_match(
                    demand, supply, match_amount, settlement_rate
                )
                
                if match_result:
                    matches.append(match_result)
                    
                    # Update order statuses
                    demand.amount_usd -= match_amount
                    supply.amount_usd -= match_amount
                    
                    if demand.amount_usd <= 0:
                        demand.status = "filled"
                    elif demand.amount_usd < demand.amount_usd:
                        demand.status = "partially_filled"
                    
                    if supply.amount_usd <= 0:
                        supply.status = "filled"
                    elif supply.amount_usd < supply.amount_usd:
                        supply.status = "partially_filled"
                    
                    break  # Move to next demand order
        
        return matches
    
    def _execute_match(
        self,
        demand: OrderBookEntry,
        supply: OrderBookEntry,
        amount_usd: float,
        rate: float
    ) -> Optional[MatchResult]:
        """Execute a matched settlement."""
        match_id = f"match-{uuid.uuid4().hex[:12]}"
        correlation_id = f"corr-{uuid.uuid4().hex[:12]}"
        
        logger.info(f"[P2PMatching] Executing match {match_id}: "
                    f"{demand.currency_from}→{demand.currency_to} ${amount_usd:,.0f} @ {rate:.4f}")
        
        # Governance approval for demand side
        demand_gov = self.governance.approve_fx_settlement(
            correlation_id=f"{correlation_id}-demand",
            from_currency=demand.currency_from,
            to_currency=demand.currency_to,
            amount_usd=amount_usd,
            rate=rate,
            slippage_bps=10,  # Internal match = tight spread
            liquidity_usd=amount_usd * 2,
            settlement_rail="auto",
            counterparty_jurisdiction=supply.jurisdiction,
        )
        
        if not demand_gov.approved:
            logger.warning(f"[P2PMatching] Match rejected by governance (demand): {demand_gov.rationale}")
            return None
        
        # Governance approval for supply side
        supply_gov = self.governance.approve_fx_settlement(
            correlation_id=f"{correlation_id}-supply",
            from_currency=supply.currency_from,
            to_currency=supply.currency_to,
            amount_usd=amount_usd,
            rate=1/rate,  # Inverse rate for supply side
            slippage_bps=10,
            liquidity_usd=amount_usd * 2,
            settlement_rail="auto",
            counterparty_jurisdiction=demand.jurisdiction,
        )
        
        if not supply_gov.approved:
            logger.warning(f"[P2PMatching] Match rejected by governance (supply): {supply_gov.rationale}")
            return None
        
        # Find best rail
        best_rail = self.router.find_best_rail(
            demand.currency_from,
            demand.currency_to,
            amount_usd,
            jurisdiction=demand.jurisdiction,
            priority="cost"
        )
        
        if not best_rail:
            logger.error(f"[P2PMatching] No available rail for {demand.currency_from}→{demand.currency_to}")
            return None
        
        # Submit settlement
        settlement_order = SettlementOrder(
            from_currency=demand.currency_from,
            to_currency=demand.currency_to,
            amount_from=amount_usd,
            amount_to=amount_usd * rate,
            rate=rate,
            rail=best_rail.rail_id,
            counterparty_id=supply.participant_id,
            jurisdiction=demand.jurisdiction,
            metadata={
                "match_id": match_id,
                "demand_participant": demand.participant_id,
                "supply_participant": supply.participant_id,
            }
        )
        
        settlement_result = best_rail.submit_settlement(settlement_order)
        
        if not settlement_result.success:
            logger.error(f"[P2PMatching] Settlement failed: {settlement_result.error_message}")
            return None
        
        # Record match
        match = MatchResult(
            match_id=match_id,
            opportunity_id=f"opp-{match_id}",
            demand_order_id=demand.order_id,
            supply_order_id=supply.order_id,
            settled_amount_usd=amount_usd,
            settlement_rate=rate,
            rail_used=best_rail.rail_id,
            settlement_result=settlement_result,
            governance_decision=demand_gov,
        )
        
        self.match_history.append(match)
        logger.info(f"[P2PMatching] Match {match_id} completed: {settlement_result.tx_hash}")
        
        return match
    
    def run_continuous_matching(self, interval_seconds: int = 30):
        """Run continuous matching loop for supported pairs."""
        logger.info(f"[P2PMatching] Starting continuous matching (interval={interval_seconds}s)")
        
        try:
            while True:
                for from_ccy, to_ccy in self.supported_pairs:
                    matches = self.match_orders(from_ccy, to_ccy)
                    if matches:
                        logger.info(f"[P2PMatching] {from_ccy}/{to_ccy}: {len(matches)} matches executed")
                
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            logger.info("[P2PMatching] Stopped")
    
    def get_order_book_snapshot(self, currency_from: str, currency_to: str) -> Dict[str, Any]:
        """Get current order book snapshot."""
        key = self._get_book_key(currency_from, currency_to)
        return {
            "pair": f"{currency_from}/{currency_to}",
            "demand": [
                {
                    "order_id": o.order_id,
                    "amount_usd": o.amount_usd,
                    "max_rate": o.max_rate,
                    "participant": o.participant_id,
                }
                for o in self.demand_book.get(key, []) if o.status == "open"
            ][:10],
            "supply": [
                {
                    "order_id": o.order_id,
                    "amount_usd": o.amount_usd,
                    "min_rate": o.min_rate,
                    "participant": o.participant_id,
                }
                for o in self.supply_book.get(key, []) if o.status == "open"
            ][:10],
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        total_matches = len(self.match_history)
        total_volume = sum(m.settled_amount_usd for m in self.match_history)
        
        rails_used = {}
        for m in self.match_history:
            rails_used[m.rail_used] = rails_used.get(m.rail_used, 0) + 1
        
        return {
            "total_matches": total_matches,
            "total_volume_usd": total_volume,
            "rails_used": rails_used,
            "open_demand_orders": sum(len([o for o in b if o.status == "open"]) for b in self.demand_book.values()),
            "open_supply_orders": sum(len([o for o in b if o.status == "open"]) for b in self.supply_book.values()),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Setup
    from carib_clear.governance.agent import GovernanceAgent
    from carib_clear.broker.stellar_adapter import StellarAdapter
    from carib_clear.broker.ach_adapter import LocalACHAdapter
    from carib_clear.broker.mobile_money_adapter import MobileMoneyAdapter
    from carib_clear.broker.base import MultiRailRouter
    
    gov = GovernanceAgent()
    router = MultiRailRouter([
        StellarAdapter({"mock_mode": True}),
        LocalACHAdapter({"jurisdiction": "JM"}),
        LocalACHAdapter({"jurisdiction": "BB"}),
        MobileMoneyAdapter({"provider": "moncash"}),
    ])
    
    engine = P2PMatchingEngine(gov, router)
    
    # Submit test orders
    engine.submit_demand_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=50000, max_rate=77.0,
        participant_id="bb_hotel_001", jurisdiction="BB"
    )
    
    engine.submit_supply_order(
        currency_from="JMD", currency_to="BBD",
        amount_usd=50000, min_rate=76.0,
        participant_id="jm_supplier_001", jurisdiction="JM"
    )
    
    # Match
    matches = engine.match_orders("BBD", "JMD")
    print(f"Matches: {len(matches)}")
    for m in matches:
        print(f"  {m.match_id}: ${m.settled_amount_usd:,.0f} @ {m.settlement_rate:.4f} via {m.rail_used}")
        print(f"    TX: {m.settlement_result.tx_hash}")
    
    print(f"\nStats: {engine.get_stats()}")