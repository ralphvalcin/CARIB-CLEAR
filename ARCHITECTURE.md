# CARIB-CLEAR Architecture

> **CARICOM FX Swap Network + MSME Credit Layer**
>
> Two-layer agentic financial infrastructure for the Caribbean.

## Two-Layer Design

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: CARICOM FX SWAP NETWORK                           │
├─────────────────────────────────────────────────────────────┤
│  FlowVisibility → P2PMatching → NetSettlement → Compliance │
│                                                                     │
│  LiquidityPools → SmartRouting → MultiRailBroker                   │
│                     (Stellar, ACH, MobileMoney)                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ (Unified Settlement Rails)
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2: MSME CREDIT LAYER                                 │
├─────────────────────────────────────────────────────────────┤
│  DataAggregation → CreditProfile → CashFlowLendingEngine   │
│                                                             │
│  TradeFinance • InvoiceFactoring • LenderAdapters          │
│                      (Barita, JMMB, IDB Invest)             │
└─────────────────────────────────────────────────────────────┘
```

## 6 Buildathon Steps

| # | Step | Type | File | Status |
|---|------|------|------|--------|
| 1 | **Flow Visibility** | AI LAYER | `agents/flow_visibility.py` | ✅ |
| 2 | **P2P FX Matching** | CORE | `agents/p2p_matching.py` | ✅ |
| 3 | **Net Settlement** | CORE | `agents/net_settlement.py` | ✅ |
| 4 | **Liquidity Pools** | CORE + MARKET | `agents/liquidity_pools.py` | ✅ |
| 5 | **Smart Routing** | AI-ASSISTED | `broker/base.py` → `MultiRailRouter` | ✅ |
| 6 | **Compliance + Controls** | DETERMINISTIC + AI | `agents/compliance.py` + `governance/agent.py` | ✅ |

## Extended Features

| Feature | File | Status |
|---------|------|--------|
| Data Aggregation (POS/Invoice/Bank/Tax ETL) | `agents/data_aggregation.py` | ✅ |
| 5 C's Credit Scoring | `agents/credit_profile.py` | ✅ |
| Cash-Flow Lending Engine | `agents/cash_flow_lending.py` | ✅ |
| Lender Adapters (Barita, JMMB, IDB Invest) | `broker/lender_adapters.py` | ✅ |
| Governance + HITL | `governance/agent.py` + `approval.py` | ✅ |
| Trade Finance / Invoice Factoring | `agents/trade_finance.py` | ✅ |
| Kreyol Voice Bridge | `voice_bridge.py` | ✅ |
| Voice Demo (mic → STT → TTS) | `voice_demo.py` | ✅ |
| REST API (15 endpoints) | `api.py` | ✅ |
| Web Dashboard (Chart.js) | `static/dashboard.html` | ✅ |
| Docker Deployment | `Dockerfile` | ✅ |

## Settlement Rails

| Rail | Description | Speed | Fee |
|------|-------------|-------|-----|
| **Stellar/USDC** | Blockchain settlement | <5s | 0.1 bps |
| **Local ACH (JM/BB/TT)** | Central bank RTGS | 1-3h | 10-25 bps |
| **Mobile Money (MonCash)** | Mobile wallet | 10s | 30-50 bps |

## Compliance Jurisdictions

| Code | Regulator | Key Documents |
|------|-----------|---------------|
| **JM** | Bank of Jamaica | tax_compliance_cert, national_id, proof_of_address, trn |
| **BB** | Central Bank of Barbados | tax_clearance_cert, national_id, proof_of_address |
| **TT** | Central Bank of Trinidad | national_id, proof_of_address, bir_clearance |
| **HT** | Banque de la République d'Haïti | national_id, proof_of_address, nif_cert |
| **ECCB** | Eastern Caribbean Central Bank | national_id, proof_of_address, tax_compliance |

## File Map

```
carib_clear/
├── demo.py                     # CLI demo (4 commands)
├── voice_bridge.py             # Kreyol/EN voice-to-loan bridge
├── voice_demo.py               # Mic capture → STT → TTS demo
├── api.py                      # FastAPI REST server
├── static/dashboard.html       # Web dashboard (Chart.js)
├── agents/
│   ├── flow_visibility.py      # Currency demand/supply detection
│   ├── p2p_matching.py         # P2P FX order book + matching
│   ├── net_settlement.py       # Multilateral netting
│   ├── compliance.py           # Multi-jurisdiction KYC/AML
│   ├── liquidity_pools.py      # Market depth + dynamic spreads
│   ├── data_aggregation.py     # POS/Invoice/Bank/Tax ETL
│   ├── credit_profile.py       # 5 C's AI cash-flow scoring
│   ├── cash_flow_lending.py    # Loan decision + lender submit
│   └── trade_finance.py        # Invoice factoring
├── broker/
│   ├── base.py                 # MultiRailBroker ABC + Router
│   ├── stellar_adapter.py      # Stellar/USDC settlement
│   ├── ach_adapter.py          # Local ACH settlement
│   ├── mobile_money_adapter.py # Mobile money settlement
│   ├── lender_base.py          # LenderAdapter ABC
│   └── lender_adapters.py      # Barita, JMMB, IDB Invest
├── governance/
│   ├── agent.py                # FX + MSME credit approval
│   └── approval.py             # SQLite approval queue with HITL
└── config/
    └── thresholds.json         # Governance thresholds
```
