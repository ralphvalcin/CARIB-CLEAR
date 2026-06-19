# agents/__init__.py
"""
CARIB-CLEAR Agents Package

Core agents for the CARICOM FX Swap Network + MSME Credit Layer.
"""

from .flow_visibility import FlowVisibilityAgent, CurrencyFlow, MatchingOpportunity
from .p2p_matching import P2PMatchingEngine, MatchResult, OrderBookEntry
from .net_settlement import NetSettlementAgent, NetPosition, NettingCycle
from .compliance import ComplianceAgent, ComplianceProfile, ComplianceCheckResult

__all__ = [
    "FlowVisibilityAgent",
    "CurrencyFlow", 
    "MatchingOpportunity",
    "P2PMatchingEngine",
    "MatchResult",
    "OrderBookEntry",
    "NetSettlementAgent",
    "NetPosition",
    "NettingCycle",
    "ComplianceAgent",
    "ComplianceProfile",
    "ComplianceCheckResult",
]