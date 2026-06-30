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
    LiquidityPoolManager,
    NetSettlementAgent,
    P2PMatchingEngine,
    TradeFinanceModule,
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
from .plugin import PluginRegistry, PluginSpec, plugin_registry

__all__ = [
    "BaritaLenderAdapter",
    "JMMBLenderAdapter",
    "IDBInvestLenderAdapter",
    "CashFlowLendingEngine",
    "ComplianceAgent",
    "CreditProfileGenerator",
    "DataAggregationAgent",
    "FlowVisibilityAgent",
    "GovernanceAgent",
    "LiquidityPoolManager",
    "LocalACHAdapter",
    "MobileMoneyAdapter",
    "MultiRailBroker",
    "MultiRailRouter",
    "NetSettlementAgent",
    "P2PMatchingEngine",
    "SqliteApprovalQueue",
    "StellarAdapter",
    "TradeFinanceModule",
]