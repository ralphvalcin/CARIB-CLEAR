# CARIB-CLEAR Architecture

> **System design, agent interactions, data flows, and deployment architecture**

---

## 🏗️ System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CARIB-CLEAR SYSTEM                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────────────────┐   ┌──────────────────────────────┐   │
│  │        EXTERNAL PARTICIPANTS      │   │       SETTLEMENT RAILS       │   │
│  │  ┌────────┐ ┌────────┐ ┌───────┐  │   │  ┌──────────┐ ┌───────────┐  │   │
│  │  │BB Hotel│ │JM Supp │ │HT Art │──┼───┼──│ Stellar  │ │ Local ACH │  │   │
│  │  └────────┘ └────────┘ └───────┘  │   │  │ /USDC    │ │ JM/BB/TT  │  │   │
│  │        ▲           ▲      ▲       │   │  └──────────┘ └───────────┘  │   │
│  │        │           │      │       │   │  ┌──────────┐ ┌───────────┐  │   │
│  │  Voice UI ◄──── JARVIS ◄──────┘   │   │  │ Mobile   │ │  Future   │  │   │
│  │  (Kreyol)   Orchestrator          │   │  │ Money    │ │  Rails    │  │   │
│  └──────────────────────────────────┘   │  └──────────┘ └───────────┘  │   │
│                           │              └──────────────────────────────┘   │
│                           ▼                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        AGENT SWARM (LangGraph on H200)              │   │
│  ├──────────────────┬──────────────────┬──────────────────┬───────────┤   │
│  │ FlowVisibility   │ P2PMatching      │ NetSettlement    │ Compliance │   │
│  │ (AI)             │ (Core)           │ (Core)           │ (Rules+AI) │   │
│  ├──────────────────┼──────────────────┼──────────────────┼───────────┤   │
│  │ LiquidityPool    │ SmartRouting     │ DataAggregation  │ CreditProf │   │
│  │ (Market)         │ (AI)             │ (ETL)            │ (AI)       │   │
│  ├──────────────────┼──────────────────┼──────────────────┼───────────┤   │
│  │ CashFlowLending  │ TradeFinance     │ LenderAdapters   │ Governance │   │
│  │ (Rules+AI)       │ (Rules)          │ (Barita/JMMB)    │ (HITL)     │   │
│  └──────────────────┴──────────────────┴──────────────────┴───────────┘   │
│                                    │                                       │
│                           ┌────────┴────────┐                              │
│                           │ SqliteApprovalQueue │                           │
│                           │ (Leases/Idempotency)│                           │
│                           └──────────────────┘                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Core Data Flows

### 1. FX Swap Flow (Layer 1)

```
Participant A (BB)                    Participant B (JM)
     │                                    │
     │ 1. Submit demand: BUY JMD, SELL BBD │
     │ 2. FlowVisibilityAgent ingests      │
     ▼                                    │
┌─────────────────────────────────────────────────────────┐
│ P2PMatchingEngine:                                       │
│   - Price-time priority order book                        │
│   - Direct BBD↔JMD match (no USD)                        │
│   - Settlement rate = mid(market)                        │
└─────────────────────────────────────────────────────────┘
     │                                    │
     │ 3. NetSettlementAgent aggregates   │
     ▼                                    │
┌─────────────────────────────────────────────────────────┐
│ ComplianceAgent:                                         │
│   - KYC/AML per jurisdiction (BB + JM)                   │
│   - Sanctions + PEP screening                            │
│   - HITL if amount > $50K                                │
└─────────────────────────────────────────────────────────┘
     │                                    │
     │ 4. MultiRailRouter selects best    │
     ▼                                    │
┌─────────────────────────────────────────────────────────┐
│ Settlement Execution:                                     │
│   - Stellar/USDC (5s, <0.1% fee)      OR                │
│   - Local ACH JM/BB (1-3h, 15-20 bps)  OR              │
│   - Mobile Money (10s, 30-50 bps)                       │
└─────────────────────────────────────────────────────────┘
     │                                    │
     ▼                                    ▼
   Settlement confirmed              Settlement confirmed
```

### 2. MSME Credit Flow (Layer 2)

```
MSME (HT Artisan)                         Lender (Barita)
     │                                        │
     │ 1. Voice request (Kreyol):             │
     │    "Mwen bezwen $5,000 pou biznis mwen" │
     ▼                                        │
┌─────────────────────────────────────────────────────────┐
│ JARVIS Voice Pipeline:                                  │
│   Whisper STT → kreyol:3b LLM → Piper TTS              │
└─────────────────────────────────────────────────────────┘
     │                                        │
     │ 2. DataAggregationAgent ingests:        │
     │    - POS CSV, invoices, bank statements │
     │    - Tax compliance, NIF certificate    │
     ▼                                        │
┌─────────────────────────────────────────────────────────┐
│ CreditProfileGenerator (AI):                            │
│   - Cash-flow scoring (no collateral)                  │
│   - Debt service ratio, operating history              │
│   - Sector-specific risk (retail, agriculture, services)│
└─────────────────────────────────────────────────────────┘
     │                                        │
     │ 3. CashFlowLendingEngine decides:       │
     ▼                                        │
┌─────────────────────────────────────────────────────────┐
│ GovernanceAgent review:                                 │
│   - Approve/deny with rationale                        │
│   - HITL if loan > $25K                                │
└─────────────────────────────────────────────────────────┘
     │                                        │
     │ 4. LenderAdapter (Barita API):          │
     ▼                                        │
┌─────────────────────────────────────────────────────────┐
│ Disbursement on Layer 1 rails:                          │
│   - USD → HTG via Stellar/MonCash                      │
│   - Repayment auto-deducted from POS                   │
└─────────────────────────────────────────────────────────┘
```

---

## 🤖 Agent Specifications

| Agent | Type | Inputs | Outputs | Dependencies |
|-------|------|--------|---------|--------------|
| **FlowVisibilityAgent** | AI | Merchant FX requests, remittance data, treasury feeds | CurrencyFlow signals (demand/supply per currency) | Market data APIs |
| **P2PMatchingEngine** | Core | CurrencyFlow signals | MatchResult (matched pairs, rate, amount) | Order book, governance |
| **NetSettlementAgent** | Core | MatchResults | NetPosition per participant/currency | Netting cycle config |
| **ComplianceAgent** | Rules+AI | Participant KYC, transaction details | ComplianceCheckResult (pass/fail/score) | Jurisdiction rules, sanctions API |
| **LiquidityPoolSim** | Market | LP deposits, market rates | Quote (rate, depth, spread) | DEX/CEX feeds |
| **SmartRoutingAgent** | AI | Settlement request, rail status | Best rail + quote | MultiRailRouter |
| **DataAggregationAgent** | ETL | POS CSV, invoices, bank stmt, tax docs | Unified business profile | File parsers, OCR |
| **CreditProfileGenerator** | AI | Business profile | CreditScore + risk factors | ML model (XGBoost/LightGBM) |
| **CashFlowLendingEngine** | Rules+AI | Credit profile + lender policy | Approve/deny + terms | Governance, lender config |
| **TradeFinanceModule** | Rules | Invoices, POs, delivery proofs | Factoring advance + terms | Invoice verification |
| **GovernanceAgent** | Rules+AI | Transaction + compliance results | GovernanceDecision (Approve/Deny) | HITL queue, thresholds |
| **LenderAdapters** | Integration | Lender API specs | Standardized loan origination | Barita, JMMB, IDB Invest APIs |

---

## 🔐 Governance & Security

### Approval Queue (SqliteApprovalQueue)
- **Lease-based worker claiming** — 30s default, auto-reclaim stale
- **Idempotency** — approval_id deduplication
- **Retry logic** — max 2 retries, then mark failed
- **Priority queue** — high-value/urgent first

### HITL Triggers
| Condition | Channel | Timeout |
|-----------|---------|---------|
| FX settlement > $50K | Telegram | 5 min |
| MSME loan > $25K | Telegram | 10 min |
| New jurisdiction onboarding | Dashboard | Manual |
| Sanctions match | Alert + Telegram | Immediate |

### Jurisdiction Rules Engine
```python
JURISDICTION_RULES = {
    "JM": {"regulator": "BOJ", "aml_threshold": 1_000_000, "kyc_tiers": 3},
    "BB": {"regulator": "CBB", "aml_threshold": 200_000, "kyc_tiers": 3},
    "TT": {"regulator": "CBTT","aml_threshold": 500_000, "kyc_tiers": 3},
    "HT": {"regulator": "BRH", "aml_threshold": 500_000, "kyc_tiers": 3},
    "ECCB": {"regulator": "ECCB","aml_threshold": 270_000, "kyc_tiers": 3},
}
```

---

## 🌐 Multi-Rail Settlement

| Rail | Currencies | Speed | Fee | Availability | Jurisdictions |
|------|------------|-------|-----|--------------|---------------|
| **Stellar/USDC** | All (USD bridge) | 5s | 0.1 bps | 99.9% | Global |
| **Local ACH (JM)** | JMD, USD | 1h | 15 bps | 99% | JM |
| **Local ACH (BB)** | BBD, USD | 2h | 20 bps | 98% | BB |
| **Local ACH (TT)** | TTD, USD | 3h | 25 bps | 97% | TT |
| **Local ACH (ECCB)** | XCD, USD | 30m | 10 bps | 99% | ECCU |
| **MonCash (HT)** | HTG, USD | 10s | 50 bps | 99.5% | HT |
| **e-cash (JM)** | JMD, USD | 5s | 30 bps | 99.8% | JM |

**Routing Logic:**
```python
def find_best_rail(from_ccy, to_ccy, amount_usd, jurisdiction, priority="cost"):
    candidates = [r for r in rails if r.supports(from_ccy, to_ccy, jurisdiction)]
    if priority == "cost":    return min(candidates, key=lambda r: r.estimate_cost(amount_usd))
    if priority == "speed":   return min(candidates, key=lambda r: r.estimated_time)
    if priority == "reliability": return max(candidates, key=lambda r: r.availability)
```

---

## ☁️ Deployment Architecture

### Buildathon (Jul 17–Aug 7)
```
┌────────────────────────────────────────────────────┐
│              HIGHRise H200 CLUSTER                 │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌───────┐  │
│  │ GPU 0   │  │ GPU 1   │  │ GPU 2   │  │ GPU 3 │  │
│  │Training │  │Inference│  │Agents   │  │Agents │  │
│  │kreyol:3b│  │kreyol:3b│  │Swarm    │  │Swarm  │  │
│  └─────────┘  └─────────┘  └─────────┘  └───────┘  │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌───────┐  │
│  │ GPU 4   │  │ GPU 5   │  │ GPU 6   │  │ GPU 7 │  │
│  │JARVIS   │  │Voice    │  │Monitoring│ │Backup │  │
│  │Voice    │  │Pipeline │  │(Grafana) │       │  │
│  └─────────┘  └─────────┘  └─────────┘  └───────┘  │
└────────────────────────────────────────────────────┘
```

### Production (Post-Buildathon)
```
┌─────────────────────────────────────────────────────────────┐
│                     KUBERNETES CLUSTER                       │
├─────────────────────────────────────────────────────────────┤
│  Namespace: carib-clear-prod                                 │
│  ├── Deployment: agent-swarm (HPA: CPU>70%)                 │
│  ├── Deployment: voice-pipeline (GPU node pool)             │
│  ├── Deployment: governance-api (3 replicas)                │
│  ├── StatefulSet: approval-queue (SQLite → PostgreSQL)     │
│  ├── ConfigMap: jurisdiction-rules, thresholds              │
│  ├── Secret: API keys, HF_TOKEN, TG_BOT_TOKEN               │
│  └── ServiceMonitor: Prometheus + Grafana                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 Monitoring & Observability

| Metric | Target | Alert |
|--------|--------|-------|
| FX settlement success rate | >99.5% | <99% |
| Settlement latency (Stellar) | <10s p95 | >30s |
| Settlement latency (ACH) | <2h p95 | >4h |
| Compliance check latency | <500ms p99 | >2s |
| Voice pipeline latency (STT+LLM+TTS) | <2s | >5s |
| Approval queue processing | <1s | >5s |
| H200 GPU utilization | >80% | <50% |

**Dashboards:**
- **Grafana:** Real-time agent swarm, settlement flows, compliance
- **Prometheus:** Metrics + alerting
- **Jaeger:** Distributed tracing (LangGraph spans)
- **Custom:** Caribbean corridor heatmap, volume by currency

---

## 🔧 Configuration

### thresholds.json
```json
{
  "governance": { "ml_high_threshold": 0.7, "rl_consensus_threshold": 0.6 },
  "compliance": { "kyc_threshold": 0.7, "aml_risk_threshold": 0.6 },
  "fx_settlement": { "max_slippage_bps": 50, "min_liquidity_usd": 10000 },
  "msme_credit": { "min_cashflow_score": 0.6, "max_debt_service_ratio": 0.4 }
}
```

### Environment Variables
```bash
# Required
HUGGINGFACE_TOKEN=hf_xxx
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
STELLAR_SECRET_KEY=Sxxx

# Optional
HF_SPACE_URL=https://huggingface.co/spaces/...
PROMETHEUS_URL=http://prometheus:9090
GRAFANA_URL=http://grafana:3000
```

---

## 📦 Dependencies

### Core
- Python 3.11+
- LangGraph 0.2+ (agent orchestration)
- FastAPI + Uvicorn (API)
- SQLAlchemy + SQLite/PostgreSQL
- Pydantic v2 (validation)

### ML/AI
- PyTorch 2.3+ (CUDA 12.1)
- Transformers 4.40+ (LLM)
- PEFT 0.11+ (LoRA)
- BitsAndBytes 0.43+ (4-bit quantization)
- TRL 0.9+ (SFTTrainer)

### Voice
- faster-whisper (STT)
- Ollama (local LLM serving)
- Piper (TTS)
- WebRTC VAD

### Blockchain/Finance
- stellar-sdk (Stellar/USDC)
- requests (ACH/Mobile Money APIs)
- python-decimal (financial math)

---

## 🧪 Testing Strategy

| Layer | Tool | Coverage Target |
|-------|------|-----------------|
| Unit | pytest + pytest-asyncio | >90% agent logic |
| Integration | TestContainers (PostgreSQL, Redis) | >80% data flows |
| Contract | Pact (broker APIs) | 100% rail interfaces |
| E2E | Playwright (voice UI) | Critical paths |
| Chaos | Chaos Mesh (K8s) | Failover scenarios |

---

*Generated for Future Caribbean Buildathon — updated as system evolves*