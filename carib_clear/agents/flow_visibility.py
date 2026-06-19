# agents/flow_visibility.py
"""
CARIB-CLEAR FlowVisibility Agent

Monitors and surfaces real-time currency demand/supply across the network.
Identifies matching opportunities for P2P FX settlement.
"""
from __future__ import annotations

import logging
import time
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CurrencyFlow:
    """Represents a currency flow signal."""
    currency: str
    jurisdiction: str
    direction: str  # "demand" (need to buy) or "supply" (need to sell)
    amount_usd: float
    urgency: float  # 0.0-1.0
    source: str  # "merchant", "importer", "remittance", "treasury"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchingOpportunity:
    """Identified matching opportunity between demand and supply."""
    opportunity_id: str
    demand_flow: CurrencyFlow
    supply_flow: CurrencyFlow
    match_amount_usd: float
    implied_rate: float
    confidence: float
    estimated_savings_bps: float


class FlowVisibilityAgent:
    """
    FlowVisibility Agent - The "eyes" of the CARICOM FX Swap Network.
    
    Continuously ingests currency demand/supply signals from:
    - Merchant payment requests
    - Importer/supplier FX needs
    - Remittance corridors
    - Central bank reserves
    - Liquidity provider inventories
    
    Surfaces matching opportunities for the P2PMatchingEngine.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.demand_flows: List[CurrencyFlow] = []
        self.supply_flows: List[CurrencyFlow] = []
        self._running = False
        
        # Caribbean currency corridors
        self.corridors = [
            ("BBD", "JMD"), ("BBD", "TTD"), ("BBD", "XCD"),
            ("JMD", "TTD"), ("JMD", "XCD"), ("JMD", "HTG"),
            ("TTD", "XCD"), ("TTD", "HTG"),
            ("XCD", "HTG"),
            # USD pairs
            ("USD", "BBD"), ("USD", "JMD"), ("USD", "TTD"),
            ("USD", "XCD"), ("USD", "HTG"),
        ]
        
        # Mock data sources for buildathon
        self.mock_sources = [
            "barbados_hotels", "jamaica_importers", "trinidad_energy",
            "haiti_remittances", "eccb_reserves", "diaspora_flows"
        ]
    
    def start(self):
        """Start the flow monitoring loop."""
        self._running = True
        logger.info("[FlowVisibility] Started monitoring currency flows")
    
    def stop(self):
        """Stop the flow monitoring loop."""
        self._running = False
        logger.info("[FlowVisibility] Stopped monitoring")
    
    def ingest_flow(self, flow: CurrencyFlow) -> None:
        """Ingest a currency flow signal."""
        if flow.direction == "demand":
            self.demand_flows.append(flow)
        elif flow.direction == "supply":
            self.supply_flows.append(flow)
        else:
            logger.warning(f"[FlowVisibility] Unknown flow direction: {flow.direction}")
        
        # Keep only recent flows (last 1000)
        self.demand_flows = self.demand_flows[-1000:]
        self.supply_flows = self.supply_flows[-1000:]
    
    def scan_for_matches(self) -> List[MatchingOpportunity]:
        """
        Scan demand and supply flows for matching opportunities.
        
        Returns list of MatchingOpportunity sorted by confidence/savings.
        """
        matches = []
        
        for demand in self.demand_flows:
            for supply in self.supply_flows:
                # Check if currencies form a valid pair
                if not self._is_valid_pair(demand.currency, supply.currency):
                    continue
                
                # Check if jurisdictions are compatible (same or corridor)
                if not self._compatible_jurisdictions(demand.jurisdiction, supply.jurisdiction):
                    continue
                
                # Calculate match amount (min of demand/supply)
                match_amount = min(demand.amount_usd, supply.amount_usd)
                if match_amount < 100:  # Minimum viable match
                    continue
                
                # Calculate implied rate
                implied_rate = self._calculate_implied_rate(demand, supply)
                
                # Calculate savings vs traditional bank route
                savings_bps = self._estimate_savings(demand.currency, supply.currency)
                
                # Confidence based on urgency match, amount, corridor
                confidence = self._calculate_confidence(demand, supply, match_amount)
                
                if confidence > 0.5:
                    opp = MatchingOpportunity(
                        opportunity_id=f"opp-{demand.currency}{supply.currency}-{int(time.time())}",
                        demand_flow=demand,
                        supply_flow=supply,
                        match_amount_usd=match_amount,
                        implied_rate=implied_rate,
                        confidence=round(confidence, 3),
                        estimated_savings_bps=savings_bps,
                    )
                    matches.append(opp)
        
        # Sort by confidence * savings
        matches.sort(key=lambda m: m.confidence * m.estimated_savings_bps, reverse=True)
        return matches
    
    def _is_valid_pair(self, ccy1: str, ccy2: str) -> bool:
        """Check if currency pair is supported in corridors."""
        pair = (ccy1, ccy2)
        rev_pair = (ccy2, ccy1)
        return pair in self.corridors or rev_pair in self.corridors
    
    def _compatible_jurisdictions(self, jur1: str, jur2: str) -> bool:
        """Check if jurisdictions can settle directly."""
        # Same jurisdiction always compatible
        if jur1 == jur2:
            return True
        
        # Check if in same corridor
        corridor_map = {
            "BB": ["JM", "TT", "ECCB"],
            "JM": ["BB", "TT", "HT", "ECCB"],
            "TT": ["BB", "JM", "ECCB"],
            "HT": ["JM", "ECCB"],
            "ECCB": ["BB", "JM", "TT", "HT"],
        }
        return jur2 in corridor_map.get(jur1, [])
    
    def _calculate_implied_rate(
        self,
        demand: CurrencyFlow,
        supply: CurrencyFlow
    ) -> float:
        """Calculate implied FX rate from matching flows."""
        # Simplified: would use order book in production
        # For now, return mid-market rate for the pair
        mid_rates = {
            ("BBD", "JMD"): 76.5, ("JMD", "BBD"): 0.0131,
            ("BBD", "TTD"): 3.4, ("TTD", "BBD"): 0.294,
            ("BBD", "XCD"): 1.35, ("XCD", "BBD"): 0.74,
            ("JMD", "TTD"): 0.045, ("TTD", "JMD"): 22.2,
            ("JMD", "XCD"): 0.0177, ("XCD", "JMD"): 56.5,
            ("JMD", "HTG"): 0.0084, ("HTG", "JMD"): 119.0,
            ("TTD", "XCD"): 0.54, ("XCD", "TTD"): 1.85,
            ("TTD", "HTG"): 0.19, ("HTG", "TTD"): 5.26,
            ("XCD", "HTG"): 0.35, ("HTG", "XCD"): 2.86,
        }
        return mid_rates.get((demand.currency, supply.currency), 1.0)
    
    def _estimate_savings(self, ccy1: str, ccy2: str) -> float:
        """Estimate savings in basis points vs traditional bank route."""
        # Traditional bank: 7-9% = 700-900 bps
        # Our target: <1% = <100 bps
        # Savings: ~600-800 bps
        savings_map = {
            ("BBD", "JMD"): 750, ("JMD", "BBD"): 750,
            ("BBD", "TTD"): 600, ("TTD", "BBD"): 600,
            ("BBD", "XCD"): 650, ("XCD", "BBD"): 650,
            ("JMD", "TTD"): 700, ("TTD", "JMD"): 700,
            ("JMD", "HTG"): 800, ("HTG", "JMD"): 800,
        }
        return savings_map.get((ccy1, ccy2), 600)
    
    def _calculate_confidence(
        self,
        demand: CurrencyFlow,
        supply: CurrencyFlow,
        match_amount: float
    ) -> float:
        """Calculate confidence score for a match."""
        base = 0.5
        
        # Urgency alignment
        urgency_diff = abs(demand.urgency - supply.urgency)
        base += (1 - urgency_diff) * 0.2
        
        # Amount size (larger = more confident)
        if match_amount > 50000:
            base += 0.15
        elif match_amount > 10000:
            base += 0.1
        elif match_amount > 1000:
            base += 0.05
        
        # Same source type
        if demand.source == supply.source:
            base += 0.1
        
        return min(0.95, base)
    
    # ─── Mock Data Generation (Buildathon) ──────────────────────────
    
    def generate_mock_flows(self, count: int = 50) -> None:
        """Generate mock flow data for buildathon demo."""
        sources = [
            ("barbados_hotels", "BB", "BBD", "JMD", "demand"),
            ("jamaica_importers", "JM", "JMD", "BBD", "demand"),
            ("trinidad_energy", "TT", "TTD", "USD", "demand"),
            ("haiti_remittances", "HT", "USD", "HTG", "demand"),
            ("eccb_reserves", "ECCB", "XCD", "USD", "supply"),
            ("diaspora_flows", "US", "USD", "JMD", "supply"),
            ("usd_correspondent", "US", "USD", "BBD", "supply"),
        ]
        
        for _ in range(count):
            src, jur, from_ccy, to_ccy, direction = random.choice(sources)
            flow = CurrencyFlow(
                currency=from_ccy,
                jurisdiction=jur,
                direction=direction,
                amount_usd=random.uniform(1000, 100000),
                urgency=random.uniform(0.3, 0.9),
                source=src,
                metadata={"corridor": f"{from_ccy}/{to_ccy}"}
            )
            self.ingest_flow(flow)
        
        logger.info(f"[FlowVisibility] Generated {count} mock flows")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics."""
        return {
            "demand_flows": len(self.demand_flows),
            "supply_flows": len(self.supply_flows),
            "total_volume_usd": sum(f.amount_usd for f in self.demand_flows + self.supply_flows),
            "currencies_covered": len(set(f.currency for f in self.demand_flows + self.supply_flows)),
            "jurisdictions_covered": len(set(f.jurisdiction for f in self.demand_flows + self.supply_flows)),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    agent = FlowVisibilityAgent()
    agent.start()
    
    # Generate mock flows
    agent.generate_mock_flows(100)
    
    # Scan for matches
    matches = agent.scan_for_matches()
    
    print(f"\n[FlowVisibility] Found {len(matches)} matching opportunities")
    for i, match in enumerate(matches[:10]):
        d = match.demand_flow
        s = match.supply_flow
        print(f"  {i+1}. {d.currency}/{s.currency} ${match.match_amount_usd:,.0f} "
              f"@ {match.implied_rate:.4f} | conf={match.confidence:.2f} "
              f"| savings={match.estimated_savings_bps}bps")
    
    print(f"\nStats: {agent.get_stats()}")