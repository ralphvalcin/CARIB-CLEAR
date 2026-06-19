# carib_clear/__init__.py
"""
CARIB-CLEAR - CARICOM FX Swap Network + MSME Credit Layer

Agentic financial infrastructure for the Caribbean.
"""

__version__ = "0.1.0-buildathon"

from .agents import (
    FlowVisibilityAgent,
    P2PMatchingEngine,
    NetSettlementAgent,
    ComplianceAgent,
)
from .broker import (
    MultiRailBroker,
    MultiRailRouter,
    StellarAdapter,
    LocalACHAdapter,
    MobileMoneyAdapter,
)
from .governance import GovernanceAgent, SqliteApprovalQueue

__all__ = [
    "FlowVisibilityAgent",
    "P2PMatchingEngine",
    "NetSettlementAgent",
    "ComplianceAgent",
    "MultiRailBroker",
    "MultiRailRouter",
    "StellarAdapter",
    "LocalACHAdapter",
    "MobileMoneyAdapter",
    "GovernanceAgent",
    "SqliteApprovalQueue",
]