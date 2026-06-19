# agents/net_settlement.py
"""
CARIB-CLEAR Net Settlement Agent

Aggregates transactions across multiple parties and settles only net obligations.
Replaces gross settlement with efficient netting, reducing capital requirements.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from carib_clear.governance.agent import GovernanceAgent
from carib_clear.broker.base import MultiRailBroker, MultiRailRouter, SettlementOrder, SettlementResult

logger = logging.getLogger(__name__)


@dataclass
class NetPosition:
    """Net position for a participant across all currencies."""
    participant_id: str
    currency: str
    net_amount_usd: float  # positive = receive, negative = pay
    jurisdiction: str
    transactions: List[str] = field(default_factory=list)  # transaction IDs


@dataclass
class NettingCycle:
    """A complete netting cycle result."""
    cycle_id: str
    timestamp: str
    participants: List[str]
    currencies: List[str]
    gross_volume_usd: float
    net_volume_usd: float
    netting_efficiency: float  # 1 - net/gross
    settlement_instructions: List[Dict[str, Any]]
    governance_approvals: Dict[str, Any]


class NetSettlementAgent:
    """
    Net Settlement Agent - The "balance sheet" of the CARICOM FX Swap Network.
    
    Features:
    - Multilateral netting across all participants
    - Reduces gross settlement volume by 80-95%
    - Single payment per participant per currency per cycle
    - Integrates with governance for compliance
    - Supports multiple settlement rails
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
        
        # Transaction pool for current cycle
        self.pending_transactions: List[Dict[str, Any]] = []
        
        # Settlement history
        self.settled_cycles: List[Dict[str, Any]] = []
        
        # Configuration
        self.min_cycle_volume_usd = config.get("min_cycle_volume_usd", 10000)
        self.max_cycle_interval_hours = config.get("max_cycle_interval_hours", 6)
        
        # Supported currencies
        self.currencies = ["USD", "BBD", "JMD", "TTD", "XCD", "HTG"]
    
    def add_transaction(
        self,
        *,
        transaction_id: str,
        from_participant: str,
        to_participant: str,
        from_currency: str,
        to_currency: str,
        amount_usd: float,
        rate: float,
        from_jurisdiction: str,
        to_jurisdiction: str,
        rail: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Add a bilaterally matched transaction to the netting pool."""
        
        tx = {
            "transaction_id": transaction_id,
            "from_participant": from_participant,
            "to_participant": to_participant,
            "from_currency": from_currency,
            "to_currency": to_currency,
            "amount_usd": amount_usd,
            "rate": rate,
            "from_jurisdiction": from_jurisdiction,
            "to_jurisdiction": to_jurisdiction,
            "rail": rail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        
        self.pending_transactions.append(tx)
        logger.info(f"[NetSettlement] Added to netting pool: {transaction_id} "
                    f"{from_participant}→{to_participant} ${amount_usd:,.0f}")
    
    def should_run_cycle(self) -> bool:
        """Check if netting cycle should run."""
        if not self.pending_transactions:
            return False
        
        # Check volume threshold
        total_volume = sum(tx["amount_usd"] for tx in self.pending_transactions)
        if total_volume >= self.min_cycle_volume_usd:
            return True
        
        # Check time threshold (would need cycle start time tracking)
        # Simplified: run every cycle for buildathon
        return True
    
    def run_netting_cycle(self) -> Optional[NettingCycle]:
        """
        Execute a multilateral netting cycle.
        
        Steps:
        1. Calculate net positions per participant per currency
        2. Generate settlement instructions (who pays whom)
        3. Get governance approval for each net settlement
        4. Execute settlements via optimal rails
        5. Record cycle
        """
        if not self.pending_transactions:
            return None
        
        cycle_id = f"net-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        logger.info(f"[NetSettlement] Starting netting cycle {cycle_id} "
                    f"with {len(self.pending_transactions)} transactions")
        
        # Step 1: Calculate net positions
        net_positions = self._calculate_net_positions()
        
        # Step 2: Generate settlement instructions
        instructions = self._generate_settlement_instructions(net_positions)
        
        # Step 3: Governance approval for each instruction
        approved_instructions = []
        gov_approvals = {}
        
        for instr in instructions:
            approval = self.governance.approve_fx_settlement(
                correlation_id=f"net-{cycle_id}-{instr['instruction_id']}",
                from_currency=instr["from_currency"],
                to_currency=instr["to_currency"],
                amount_usd=instr["amount_usd"],
                rate=instr["rate"],
                slippage_bps=5,  # Internal netting = very tight
                liquidity_usd=instr["amount_usd"] * 2,
                settlement_rail=instr["recommended_rail"],
                counterparty_jurisdiction=instr["to_jurisdiction"],
            )
            
            gov_approvals[instr["instruction_id"]] = approval
            
            if approval.approved:
                approved_instructions.append(instr)
            else:
                logger.warning(f"[NetSettlement] Net settlement rejected: {approval.rationale}")
        
        if not approved_instructions:
            logger.warning(f"[NetSettlement] No approved settlements in cycle {cycle_id}")
            return None
        
        # Step 4: Execute approved settlements
        executed = []
        for instr in approved_instructions:
            result = self._execute_net_settlement(instr)
            if result.success:
                executed.append({"instruction": instr, "result": result})
        
        # Step 5: Calculate metrics
        gross_volume = sum(tx["amount_usd"] for tx in self.pending_transactions)
        net_volume = sum(instr["amount_usd"] for instr in approved_instructions)
        efficiency = 1 - (net_volume / gross_volume) if gross_volume > 0 else 0
        
        cycle = NettingCycle(
            cycle_id=cycle_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            participants=list(set(tx["from_participant"] for tx in self.pending_transactions) | 
                            set(tx["to_participant"] for tx in self.pending_transactions)),
            currencies=list(set(tx["from_currency"] for tx in self.pending_transactions) | 
                          set(tx["to_currency"] for tx in self.pending_transactions)),
            gross_volume_usd=gross_volume,
            net_volume_usd=net_volume,
            netting_efficiency=round(efficiency, 3),
            settlement_instructions=executed,
            governance_approvals=gov_approvals,
        )
        
        # Clear pending transactions
        self.pending_transactions.clear()
        
        # Store cycle
        self.settled_cycles.append({
            "cycle_id": cycle_id,
            "cycle": cycle,
            "timestamp": cycle.timestamp,
        })
        
        logger.info(f"[NetSettlement] Cycle {cycle_id} completed: "
                    f"${gross_volume:,.0f} gross → ${net_volume:,.0f} net "
                    f"({efficiency:.1%} reduction)")
        
        return cycle
    
    def _calculate_net_positions(self) -> Dict[str, NetPosition]:
        """
        Calculate net position for each participant in each currency.
        
        Returns dict: "participant_id/currency" -> NetPosition
        """
        # Aggregate all flows
        positions = defaultdict(lambda: defaultdict(float))
        jurisdictions = {}
        
        for tx in self.pending_transactions:
            from_part = tx["from_participant"]
            to_part = tx["to_participant"]
            from_ccy = tx["from_currency"]
            to_ccy = tx["to_currency"]
            amount = tx["amount_usd"]
            
            # Payer: negative net position in from_currency
            positions[from_part][from_ccy] -= amount
            jurisdictions[f"{from_part}/{from_ccy}"] = tx["from_jurisdiction"]
            
            # Receiver: positive net position in to_currency
            positions[to_part][to_ccy] += amount
            jurisdictions[f"{to_part}/{to_ccy}"] = tx["to_jurisdiction"]
        
        # Convert to NetPosition objects
        net_positions = {}
        for participant, currencies in positions.items():
            for currency, net_amount in currencies.items():
                if abs(net_amount) < 0.01:  # Ignore dust
                    continue
                
                key = f"{participant}/{currency}"
                net_positions[key] = NetPosition(
                    participant_id=participant,
                    currency=currency,
                    net_amount_usd=round(net_amount, 2),
                    jurisdiction=jurisdictions.get(key, "UNKNOWN"),
                    transactions=[],  # Would track specific txs in production
                )
        
        return net_positions
    
    def _generate_settlement_instructions(
        self,
        net_positions: Dict[str, NetPosition]
    ) -> List[Dict[str, Any]]:
        """
        Generate settlement instructions from net positions.
        
        For each currency: match payers with receivers.
        """
        instructions = []
        
        # Group by currency
        by_currency = defaultdict(list)
        for key, pos in net_positions.items():
            by_currency[pos.currency].append(pos)
        
        for currency, positions in by_currency.items():
            # Separate payers (negative) and receivers (positive)
            payers = [p for p in positions if p.net_amount_usd < 0]
            receivers = [p for p in positions if p.net_amount_usd > 0]
            
            # Sort payers by amount (largest first)
            payers.sort(key=lambda p: p.net_amount_usd)
            receivers.sort(key=lambda p: -p.net_amount_usd)
            
            # Match payers to receivers
            payer_idx = 0
            receiver_idx = 0
            
            while payer_idx < len(payers) and receiver_idx < len(receivers):
                payer = payers[payer_idx]
                receiver = receivers[receiver_idx]
                
                pay_amount = abs(payer.net_amount_usd)
                recv_amount = receiver.net_amount_usd
                settle_amount = min(pay_amount, recv_amount)
                
                if settle_amount < 1:  # Skip dust
                    if pay_amount <= recv_amount:
                        payer_idx += 1
                    else:
                        receiver_idx += 1
                    continue
                
                instruction = {
                    "instruction_id": f"net-{payer.participant_id}-{receiver.participant_id}-{currency}",
                    "from_participant": payer.participant_id,
                    "to_participant": receiver.participant_id,
                    "from_currency": currency,
                    "to_currency": currency,  # Same currency netting
                    "amount_usd": round(settle_amount, 2),
                    "rate": 1.0,  # Same currency
                    "recommended_rail": self._recommend_rail(payer.jurisdiction, receiver.jurisdiction, currency),
                    "from_jurisdiction": payer.jurisdiction,
                    "to_jurisdiction": receiver.jurisdiction,
                }
                
                instructions.append(instruction)
                
                # Update remaining amounts
                payer.net_amount_usd += settle_amount  # negative + positive = less negative
                receiver.net_amount_usd -= settle_amount
                
                if abs(payer.net_amount_usd) < 1:
                    payer_idx += 1
                if receiver.net_amount_usd < 1:
                    receiver_idx += 1
        
        return instructions
    
    def _recommend_rail(
        self,
        from_jurisdiction: str,
        to_jurisdiction: str,
        currency: str
    ) -> str:
        """Recommend best settlement rail for a net instruction."""
        # Priority: Stellar > Local ACH > Mobile Money
        # For same currency within jurisdiction: Local ACH
        if from_jurisdiction == to_jurisdiction:
            return f"ach_{from_jurisdiction.lower()}"
        
        # Cross-jurisdiction: Stellar for speed/cost
        return "stellar_usdc"
    
    def _execute_net_settlement(self, instruction: Dict[str, Any]) -> SettlementResult:
        """Execute a net settlement instruction."""
        best_rail = self.router.find_best_rail(
            instruction["from_currency"],
            instruction["to_currency"],
            instruction["amount_usd"],
            jurisdiction=instruction["from_jurisdiction"],
            priority="cost"
        )
        
        if not best_rail:
            return SettlementResult(
                order_id=instruction["instruction_id"],
                success=False,
                error_message="No available rail",
                status="failed",
            )
        
        order = SettlementOrder(
            from_currency=instruction["from_currency"],
            to_currency=instruction["to_currency"],
            amount_from=instruction["amount_usd"],
            amount_to=instruction["amount_usd"],  # Same currency
            rate=1.0,
            rail=best_rail.rail_id,
            counterparty_id=instruction["to_participant"],
            jurisdiction=instruction["from_jurisdiction"],
            metadata={"is_netting": True, **instruction},
        )
        
        return best_rail.submit_settlement(order)
    
    def get_pending_volume(self) -> float:
        """Get total pending transaction volume in USD."""
        return sum(tx["amount_usd"] for tx in self.pending_transactions)
    
    def get_pending_by_currency(self) -> Dict[str, float]:
        """Get pending volume grouped by currency."""
        by_ccy = defaultdict(float)
        for tx in self.pending_transactions:
            by_ccy[tx["from_currency"]] += tx["amount_usd"]
            by_ccy[tx["to_currency"]] += tx["amount_usd"]
        return dict(by_ccy)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics."""
        total_gross = sum(c.gross_volume_usd for c in 
                         [nc["cycle"] for nc in self.settled_cycles])
        total_net = sum(c.net_volume_usd for c in 
                       [nc["cycle"] for nc in self.settled_cycles])
        avg_efficiency = sum(c.netting_efficiency for c in 
                           [nc["cycle"] for nc in self.settled_cycles]) / len(self.settled_cycles) if self.settled_cycles else 0
        
        return {
            "pending_transactions": len(self.pending_transactions),
            "pending_volume_usd": self.get_pending_volume(),
            "pending_by_currency": self.get_pending_by_currency(),
            "completed_cycles": len(self.settled_cycles),
            "total_gross_volume_usd": total_gross,
            "total_net_volume_usd": total_net,
            "avg_netting_efficiency": round(avg_efficiency, 3),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    from carib_clear.governance.agent import GovernanceAgent
    from carib_clear.broker.base import MultiRailRouter
    from carib_clear.broker.stellar_adapter import StellarAdapter
    from carib_clear.broker.ach_adapter import LocalACHAdapter
    
    gov = GovernanceAgent()
    router = MultiRailRouter([
        StellarAdapter({"mock_mode": True}),
        LocalACHAdapter({"jurisdiction": "JM"}),
        LocalACHAdapter({"jurisdiction": "BB"}),
    ])
    
    agent = NetSettlementAgent(gov, router)
    
    # Add test transactions
    agent.add_transaction(
        transaction_id="tx-1",
        from_participant="bb_hotel_001",
        to_participant="jm_supplier_001",
        from_currency="BBD", to_currency="JMD",
        amount_usd=50000, rate=76.5,
        from_jurisdiction="BB", to_jurisdiction="JM",
        rail="stellar_usdc",
    )
    
    agent.add_transaction(
        transaction_id="tx-2",
        from_participant="jm_exporter_001",
        to_participant="bb_importer_001",
        from_currency="JMD", to_currency="BBD",
        amount_usd=30000, rate=0.013,
        from_jurisdiction="JM", to_jurisdiction="BB",
        rail="stellar_usdc",
    )
    
    agent.add_transaction(
        transaction_id="tx-3",
        from_participant="tt_energy_001",
        to_participant="bb_hotel_001",
        from_currency="TTD", to_currency="BBD",
        amount_usd=20000, rate=0.294,
        from_jurisdiction="TT", to_jurisdiction="BB",
        rail="stellar_usdc",
    )
    
    print(f"Pending: {agent.get_pending_volume():,.0f} USD")
    print(f"By currency: {agent.get_pending_by_currency()}")
    
    # Run cycle
    cycle = agent.run_netting_cycle()
    if cycle:
        print(f"\nCycle {cycle.cycle_id}:")
        print(f"  Gross: ${cycle.gross_volume_usd:,.0f}")
        print(f"  Net: ${cycle.net_volume_usd:,.0f}")
        print(f"  Efficiency: {cycle.netting_efficiency:.1%}")
        print(f"  Settlements: {len(cycle.settlement_instructions)}")
    
    print(f"\nStats: {agent.get_stats()}")