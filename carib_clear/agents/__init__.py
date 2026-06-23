"""CARIB-CLEAR Agents Package

Core agents for the CARICOM FX Swap Network + MSME Credit Layer.
"""

from .cash_flow_lending import (
    CashFlowLendingEngine,
    LendingProduct,
    LoanApplication,
    LoanDecision,
)
from .compliance import ComplianceAgent, ComplianceCheckResult, ComplianceProfile
from .credit_profile import (
    CreditProfile,
    CreditProfileGenerator,
    CreditScoreCategory,
    LoanRecommendation,
    RiskFactor,
)
from .data_aggregation import (
    BankStatementMetrics,
    BusinessProfile,
    BusinessSpecies,
    DataAggregationAgent,
    InvoiceRecord,
    InvoiceSummary,
    MonthlyRevenue,
    POSCSVParser,
    TaxComplianceStatus,
)
from .flow_visibility import CurrencyFlow, FlowVisibilityAgent, MatchingOpportunity
from .net_settlement import NetPosition, NetSettlementAgent, NettingCycle
from .p2p_matching import MatchResult, OrderBookEntry, P2PMatchingEngine

from .liquidity_pools import (
    CurrencyPool,
    LiquidityPoolManager,
    LiquidityProvider,
    PoolQuote,
)
from .trade_finance import (
    DebtorAssessment,
    FactoringAgreement,
    FactoringEvaluation,
    FactoringRequest,
    TradeFinanceModule,
)

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
    "DataAggregationAgent",
    "BusinessProfile",
    "BusinessSpecies",
    "MonthlyRevenue",
    "InvoiceRecord",
    "InvoiceSummary",
    "BankStatementMetrics",
    "TaxComplianceStatus",
    "POSCSVParser",
    "CreditProfileGenerator",
    "CreditProfile",
    "CreditScoreCategory",
    "LoanRecommendation",
    "RiskFactor",
    "CashFlowLendingEngine",
    "LoanApplication",
    "LoanDecision",
    "LendingProduct",
    "LiquidityPoolManager",
    "LiquidityProvider",
    "CurrencyPool",
    "PoolQuote",
    "TradeFinanceModule",
    "FactoringRequest",
    "FactoringEvaluation",
    "FactoringAgreement",
    "DebtorAssessment",
]
