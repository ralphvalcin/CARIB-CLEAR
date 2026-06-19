# CARIB-CLEAR API Reference

> **Agent, broker, and governance interfaces for contributors**

---

## 🤖 Agent Interfaces

### FlowVisibilityAgent

```python
from carib_clear.agents import FlowVisibilityAgent, CurrencyFlow

agent = FlowVisibilityAgent()

# Ingest a currency flow signal
flow = CurrencyFlow(
    currency="BBD",
    jurisdiction="BB",
    direction="demand",        # "demand" or "supply"
    amount_usd=50000,
    urgency=0.8,
    source="merchant",         # merchant, remittance, treasury, importer
    metadata={"corridor": "BBD/JMD"}
)
agent.ingest_flow(flow)

# Scan for matching opportunities
matches = agent.scan_for_matches()
# Returns List[MatchingOpportunity]
```

### P2PMatchingEngine

```python
from carib_clear.agents import P2PMatchingEngine, MatchResult
from carib_clear.governance import GovernanceAgent
from carib_clear.broker import MultiRailRouter

gov = GovernanceAgent()
router = MultiRailRouter([...])
engine = P2PMatchingEngine(gov, router)

# Submit demand order (need to BUY to_ccy, SELL from_ccy)
demand = engine.submit_demand_order(
    currency_from="BBD",
    currency_to="JMD",
    amount_usd=50000,
    max_rate=77.0,
    participant_id="bb_hotel_001",
    jurisdiction="BB"
)

# Submit supply order (need to SELL from_ccy, BUY to_ccy)
supply = engine.submit_supply_order(
    currency_from="JMD",
    currency_to="BBD",
    amount_usd=50000,
    min_rate=76.0,
    participant_id="jm_supplier_001",
    jurisdiction="JM"
)

# Execute matches
matches = engine.match_orders("BBD", "JMD")
# Returns List[MatchResult]
```

### NetSettlementAgent

```python
from carib_clear.agents import NetSettlementAgent, NettingCycle

net = NetSettlementAgent(gov, router)

# Add matched transactions to netting pool
net.add_transaction(
    transaction_id="tx-001",
    from_participant="bb_hotel_001",
    to_participant="jm_supplier_001",
    from_currency="BBD",
    to_currency="JMD",
    amount_usd=50000,
    rate=76.5,
    from_jurisdiction="BB",
    to_jurisdiction="JM",
    rail="stellar_usdc"
)

# Run netting cycle
cycle = net.run_netting_cycle()
# Returns NettingCycle with settlement instructions
```

### ComplianceAgent

```python
from carib_clear.agents import ComplianceAgent, ComplianceCheckResult

comp = ComplianceAgent()

# Onboard participant
result = comp.onboard_participant(
    participant_id="bb_hotel_001",
    jurisdiction="BB",
    kyc_documents={
        "tax_clearance_certificate": "TCC-2024-001234",
        "national_id": "BBD-12345678",
        "proof_of_address": "Utility bill - 123 Bay St, Bridgetown"
    },
    beneficial_owners=[
        {"name": "John Smith", "ownership": 0.60},
        {"name": "Jane Doe", "ownership": 0.40}
    ],
    kyc_tier=3
)

# Screen transaction
txn_result = comp.screen_transaction(
    transaction_id="txn-001",
    from_participant="bb_hotel_001",
    to_participant="jm_supplier_001",
    amount_usd=50000,
    currency="BBD",
    from_jurisdiction="BB",
    to_jurisdiction="JM",
    purpose="trade"
)

# Get dashboard
dashboard = comp.get_compliance_dashboard()
```

---

## 🏦 Broker Interfaces

### MultiRailBroker (Abstract Base)

```python
from carib_clear.broker import MultiRailBroker, SettlementOrder, SettlementResult, RailInfo

class MyCustomRail(MultiRailBroker):
    @property
    def rail_info(self) -> RailInfo:
        return RailInfo(...)
    
    def initialize(self) -> bool: ...
    def health_check(self) -> bool: ...
    def get_quote(self, from_ccy: str, to_ccy: str, amount: float) -> Optional[Dict]: ...
    def submit_settlement(self, order: SettlementOrder) -> SettlementResult: ...
    def get_settlement_status(self, order_id: str) -> SettlementResult: ...
    def cancel_settlement(self, order_id: str) -> bool: ...
```

### StellarAdapter

```python
from carib_clear.broker import StellarAdapter, SettlementOrder

stellar = StellarAdapter({"mock_mode": True})
stellar.initialize()

quote = stellar.get_quote("BBD", "JMD", 10000)
# {"rate": 38.25, "fees_bps": 0.1, "estimated_time_seconds": 5, ...}

order = SettlementOrder(
    from_currency="BBD",
    to_currency="JMD",
    amount_from=20000,
    amount_to=765000,
    rate=38.25,
    rail="stellar_usdc",
    counterparty_id="jam_supplier_001",
    jurisdiction="JM"
)
result = stellar.submit_settlement(order)
```

### LocalACHAdapter

```python
from carib_clear.broker import LocalACHAdapter, MultiJurisdictionACH

# Single jurisdiction
jm_ach = LocalACHAdapter({"jurisdiction": "JM"})
jm_ach.initialize()

# Or multi-jurisdiction factory
ach = MultiJurisdictionACH()
jm_ach = ach.get_adapter("JMD")  # Returns JM adapter
```

### MobileMoneyAdapter

```python
from carib_clear.broker import MobileMoneyAdapter, MultiProviderMobileMoney

moncash = MobileMoneyAdapter({"provider": "moncash"})
moncash.initialize()

# Check KYC tier limits
quote = moncash.get_quote("HTG", "USD", 500)
# {"rate": 130.0, "max_amount_usd": 2500, "kyc_tier_required": 2, ...}
```

### MultiRailRouter

```python
from carib_clear.broker import MultiRailRouter

router = MultiRailRouter([stellar, jm_ach, moncash])

# Find best rail
best = router.find_best_rail(
    from_currency="BBD",
    to_currency="JMD",
    amount_usd=10000,
    jurisdiction="BB",
    priority="cost"  # or "speed", "reliability"
)

# Get all quotes
quotes = router.get_all_quotes("BBD", "JMD", 10000)
```

---

## ⚖️ Governance Interfaces

### GovernanceAgent

```python
from carib_clear.governance import GovernanceAgent, GovernanceDecision, ComplianceCheck

gov = GovernanceAgent()

# FX Settlement approval
fx_decision = gov.approve_fx_settlement(
    correlation_id="fx-001",
    from_currency="BBD",
    to_currency="JMD",
    amount_usd=50000,
    rate=76.5,
    slippage_bps=25,
    liquidity_usd=100000,
    settlement_rail="stellar_usdc",
    counterparty_jurisdiction="JM"
)

# MSME Credit approval
credit_decision = gov.approve_msme_credit(
    correlation_id="credit-001",
    business_id="haitian_artisan_001",
    jurisdiction="HT",
    cashflow_score=0.75,
    debt_service_ratio=0.3,
    operating_history_months=24,
    requested_amount_usd=10000,
    collateral_value_usd=0
)
```

### SqliteApprovalQueue

```python
from carib_clear.governance import SqliteApprovalQueue, PendingAction, ACTION_TYPES

queue = SqliteApprovalQueue("./data/approvals.db")

# Enqueue approval request
item = queue.enqueue(
    session_id="session-001",
    action="fx_settlement",
    payload={"from_ccy": "BBD", "to_ccy": "JMD", "amount_usd": 50000},
    reason="Barbados hotel paying Jamaican supplier",
    priority=10
)

# Claim for execution (worker lease)
claimed = queue.claim_for_execution(item.approval_id, "worker-1", lease_seconds=60)

# Mark executed
executed = queue.mark_executed(item.approval_id, {"tx_hash": "0xabc123"}, "worker-1")

# Get metrics
metrics = queue.metrics()
# {"pending": 5, "approved": 10, "executed": 8, "failed": 1, "total": 24}
```

---

## 📝 Data Structures

### SettlementOrder
```python
@dataclass
class SettlementOrder:
    order_id: str                    # Auto-generated
    from_currency: str               # "BBD"
    to_currency: str                 # "JMD"
    amount_from: float               # Amount in from_currency
    amount_to: float                 # Amount in to_currency
    rate: float                      # FX rate
    rail: str                        # "stellar_usdc", "ach_jm", "mm_moncash"
    counterparty_id: str             # Participant ID
    jurisdiction: str                # "JM", "BB", etc.
    metadata: Dict = {}
    created_at: str                  # ISO timestamp
```

### SettlementResult
```python
@dataclass
class SettlementResult:
    order_id: str
    success: bool
    fill_price: Optional[float]
    fill_quantity: Optional[float]
    fees_usd: float
    settlement_time_seconds: float
    tx_hash: Optional[str]
    status: str                      # "pending", "filled", "partial", "failed", "cancelled"
    error_message: Optional[str]
    raw_response: Dict = {}
```

### ComplianceCheckResult
```python
@dataclass
class ComplianceCheckResult:
    check_id: str
    participant_id: str
    check_type: str                  # "kyc", "aml", "sanctions", "pep", "transaction"
    passed: bool
    score: float
    details: Dict
    requires_review: bool
    reviewer_notes: str
    timestamp: str
```

### GovernanceDecision
```python
@dataclass
class GovernanceDecision:
    approved: bool
    decision_type: str               # "fx_settlement", "msme_credit", "compliance"
    rationale: str
    confidence: float
    compliance_checks: List[ComplianceCheck]
    conditions: List[str] = []
    timestamp: str
```

---

## 🔧 Configuration

### thresholds.json
```json
{
  "governance": {
    "ml_high_threshold": 0.7,
    "ml_low_threshold": 0.3,
    "rl_consensus_threshold": 0.6,
    "sentiment_shock_threshold": -0.6,
    "ml_consensus_threshold": 0.65
  },
  "compliance": {
    "kyc_threshold": 0.7,
    "aml_risk_threshold": 0.6,
    "sanctions_check_threshold": 0.9,
    "pep_check_threshold": 0.8
  },
  "fx_settlement": {
    "max_slippage_bps": 50,
    "min_liquidity_usd": 10000,
    "max_settlement_time_min": 30
  },
  "msme_credit": {
    "min_cashflow_score": 0.6,
    "max_debt_service_ratio": 0.4,
    "min_operating_history_months": 6
  }
}
```

### jurisdiction_rules.json (Auto-loaded)
```json
{
  "JM": {"regulator": "BOJ", "aml_threshold_jmd": 1000000, "kyc_required": ["tax_compliance_certificate", "national_id", "proof_of_address", "trn"]},
  "BB": {"regulator": "CBB", "aml_threshold_bbd": 200000, "kyc_required": ["tax_clearance_certificate", "national_id", "proof_of_address"]},
  "TT": {"regulator": "CBTT", "aml_threshold_ttd": 500000, "kyc_required": ["national_id", "proof_of_address", "bir_clearance_certificate"]},
  "HT": {"regulator": "BRH", "aml_threshold_htg": 500000, "kyc_required": ["national_id", "proof_of_address", "nif_certificate"]},
  "ECCB": {"regulator": "ECCB", "aml_threshold_xcd": 270000, "kyc_required": ["national_id", "proof_of_address", "tax_compliance_certificate"]}
}
```

---

*Generated for Future Caribbean Buildathon — auto-updated with code changes*