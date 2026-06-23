# CARIB-CLEAR

> **CARICOM FX Swap Network + MSME Credit Layer**
>
> Direct multi-currency settlement (BBD↔JMD↔TTD↔XCD↔HTG) without USD bridge — <1% fees, <5 min finality. Cash-flow MSME lending (no collateral) on Layer 1 rails.

[![Buildathon](https://img.shields.io/badge/Future%20Caribbean-Buildathon%20Track%203-blue)](https://futurecaribbean.com)
[![Python](https://img.shields.io/badge/Python-3.10+-blue)](pyproject.toml)
[![Tests](https://img.shields.io/badge/Tests-47%20passing-green)](tests/)

---

## Quick Start

```bash
# Install
pip install -e .

# Full demo (Layer 1 + Layer 2)
python -m carib_clear.demo full

# Layer 1 — FX Swap Network only
python -m carib_clear.demo fx_swap

# Layer 2 — MSME Credit only
python -m carib_clear.demo msme_credit
```

The full demo completes in ~4 seconds and shows:
- BBD↔JMD $50K P2P FX match settled via Stellar/USDC
- MSME credit scoring and $125K in approved loans via IDB Invest
- Multi-jurisdiction KYC/AML compliance (BB, JM, TT, HT)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1 — CARICOM FX SWAP NETWORK                          │
├─────────────────────────────────────────────────────────────┤
│  FlowVisibility → P2PMatching → NetSettlement → Compliance │
│  SmartRouting → MultiRailBroker (Stellar, ACH, Mobile)      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2 — MSME CREDIT LAYER                                │
├─────────────────────────────────────────────────────────────┤
│  DataAggregation → CreditProfile → CashFlowLendingEngine    │
│  LenderAdapters (Barita, JMMB, IDB Invest)                  │
└─────────────────────────────────────────────────────────────┘
```

## 6 Buildathon Steps

| # | Step | Type | Status |
|---|------|------|--------|
| 1 | Flow Visibility | AI LAYER | ✅ |
| 2 | P2P FX Matching Engine | CORE | ✅ |
| 3 | Net Settlement Layer | CORE | ✅ |
| 4 | Liquidity Pools | CORE + MARKET DESIGN | 🔄 In progress |
| 5 | Smart Routing | AI-ASSISTED | ✅ |
| 6 | Compliance + Controls | DETERMINISTIC + AI SUPPORT | ✅ |

## Project Structure

```
carib_clear/
├── demo.py                     # CLI demo (4 commands)
├── agents/
│   ├── flow_visibility.py      # Currency demand/supply detection
│   ├── p2p_matching.py         # P2P FX order book + matching
│   ├── net_settlement.py       # Multilateral netting
│   ├── compliance.py           # Multi-jurisdiction KYC/AML
│   ├── data_aggregation.py     # POS/Invoice/Bank/Tax ETL
│   ├── credit_profile.py       # 5 C's AI cash-flow scoring
│   └── cash_flow_lending.py    # Loan decision + lender submission
├── broker/
│   ├── base.py                 # MultiRailBroker ABC
│   ├── stellar_adapter.py      # Stellar/USDC settlement
│   ├── ach_adapter.py          # Local ACH settlement
│   ├── mobile_money_adapter.py # Mobile money settlement
│   ├── lender_base.py          # LenderAdapter ABC
│   └── lender_adapters.py      # Barita, JMMB, IDB Invest
├── governance/
│   ├── agent.py                # FX + MSME credit approval
│   └── approval.py             # SQLite approval queue
└── config/
    └── thresholds.json          # Governance thresholds
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_lender_adapters.py -v
```

## API Server

```bash
# Start the REST API
python -m carib_clear.api

# Open http://localhost:8000/docs for Swagger UI

# Key endpoints:
#   GET  /health                 — Health check
#   GET  /demo/full              — Run full pipeline demo
#   GET  /demo/fx_swap           — Run Layer 1 demo
#   GET  /demo/msme_credit       — Run Layer 2 demo
#   POST /loan/apply             — Submit a loan application
#   GET  /loan/applications      — List recent applications
#   GET  /liquidity/state        — Liquidity pool status
#   POST /compliance/onboard     — Onboard a participant
#   POST /compliance/screen      — Screen a transaction
```

## Docker

```bash
docker build -t carib-clear .
docker run -p 8000:8000 carib-clear
```

## Buildathon Context

Built for the **Future Caribbean Global AI Buildathon** (Track 3: Finance, Payments & MSME Capital). 40 teams, 10 tracks, 3 winners per track. Winners pitch at the **NYSE in September 2026**.

**Key targets:**
- ✅ Direct BBD↔JMD↔TTD↔XCD↔HTG settlement (no USD bridge)
- ✅ <1% FX cost vs 7–9% traditional
- ✅ <5 min settlement vs 2–3 days
- ✅ Cash-flow loan approved (no collateral)
- ✅ Multi-jurisdiction compliance (JM, BB, TT, HT, ECCB)
- ✅ 3 lender integrations (Barita, JMMB, IDB Invest)
