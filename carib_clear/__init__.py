"""CARIB-CLEAR - CARICOM FX Swap Network + MSME Credit Layer

Agentic financial infrastructure for the Caribbean.
"""

__version__ = "0.1.0-buildathon"

from .agents import (
    CashFlowLendingEngine,
    ComplianceAgent,
    CreditProfileGenerator,
    DataAggregationAgent,
    FlowVisibilityAgent,
    NetSettlementAgent,
    P2PMatchingEngine,
)
from .broker import (
    BaritaLenderAdapter,
    IDBInvestLenderAdapter,
    JMMBLenderAdapter,
    LocalACHAdapter,
    MobileMoneyAdapter,
    MultiRailBroker,
    MultiRailRouter,
    StellarAdapter,
)
from .governance import GovernanceAgent, SqliteApprovalQueue

__all__ = [
    "BaritaLenderAdapter",
    "JMMBLenderAdapter",
    "IDBInvestLenderAdapter",
    "CashFlowLendingEngine",
    "CreditProfileGenerator",
    "DataAggregationAgent",
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