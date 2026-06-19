# CARIB-CLEAR

> **Agentic CARICOM FX Swap Network + MSME Credit Layer**
> 
> Direct multi-currency settlement (BBD↔JMD↔TTD↔XCD↔HTG) without USD bridge — <1% fees, <5 min finality. Cash-flow MSME lending (no collateral) on Layer 1 rails.

[![Buildathon](https://img.shields.io/badge/Future%20Caribbean-Buildathon%20Track%203-blue)](https://futurecaribbean.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](pyproject.toml)

---

## 🎯 Overview

**CARIB-CLEAR** is a two-layer agentic financial infrastructure for the Caribbean:

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1 — CARICOM FX SWAP NETWORK                          │
├─────────────────────────────────────────────────────────────┤
│  FlowVisibilityAgent → P2PMatchingEngine → NetSettlement   │
│       (AI)               (Core)               (Core)        │
│                                                             │
│  LiquidityPool + SmartRouting + Compliance (JM/BB/TT/HT)   │
│                                                             │
│  MultiRailBroker: Stellar/USDC • Local ACH • Mobile Money  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2 — MSME CREDIT LAYER (built on Layer 1 rails)       │
├─────────────────────────────────────────────────────────────┤
│  DataAggregation → CreditProfile → CashFlowLendingEngine   │
│       (ETL)           (AI)              (Rules+AI)         │
│                                                             │
│  TradeFinance • InvoiceFactoring • LenderAdapters           │
└─────────────────────────────────────────────────────────────┘
```

**Targets (21-day buildathon):**
- ✅ BBD↔JMD↔TTD direct swap
- ✅ <1% FX cost vs 7–9% traditional
- ✅ <5 min settlement vs 2–3 days
- ✅ 3+ currencies live
- ✅ Cash-flow loan approved (no collateral)
- ✅ Voice demo (Kreyol/English)

---

## 🏗️ Architecture

| Layer | Agents | Brokers | Governance |
|-------|--------|---------|------------|
| **1. FX Swap** | FlowVisibility, P2PMatching, NetSettlement, Compliance | StellarAdapter, LocalACHAdapter, MobileMoneyAdapter | GovernanceAgent + SqliteApprovalQueue |
| **2. MSME Credit** | DataAggregation, CreditProfile, CashFlowLendingEngine | Reuses Layer 1 rails | Same governance layer |

**Key Design Principles:**
- **Agentic coordination** — LangGraph multi-agent swarms on H200
- **Multi-rail settlement** — Best path selection (cost/speed/reliability)
- **Jurisdiction-aware compliance** — KYC/AML per JM/BB/TT/HT/ECCB
- **Human-in-the-loop** — Telegram approval for large transactions
- **Proven primitives** — Extracted from trading system, JARVIS, Kreyol-AI

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- NVIDIA H200 (buildathon) or CUDA/MPS for local dev
- Ollama for local LLMs

### Install
```bash
git clone https://github.com/ralphucious/CARIB-CLEAR
cd CARIB-CLEAR
pip install -r requirements.txt
```

### Run Demo (Buildathon)
```bash
# On H200 during buildathon (Jul 17–Aug 7)
python scripts/quick_train_kreyol.py --stage both --skip-h200-check
python scripts/merge_kreyol_to_ollama.py --output-model kreyol:3b

# CLI demo: BBD→JMD swap
python -m carib_clear.demo fx_swap \
    --from BBD --to JMD --amount 50000 \
    --participant bb_hotel_001 --counterparty jm_supplier_001
```

### Run Tests
```bash
pytest tests/ -v
```

---

## 📚 Documentation

| Doc | Description |
|-----|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, agent interactions, data flows |
| [WHITEPAPER.md](WHITEPAPER.md) | Problem, solution, market, technical approach |
| [API.md](API.md) | Agent/broker interfaces for contributors |
| [DEPLOYMENT.md](DEPLOYMENT.md) | H200 setup, production deployment |

---

## 🤝 Contributing

**Buildathon (Jul 17–Aug 7):** All hands on core agents.

**Roles needed:**
1. **Payments/Compliance Engineer** — KYC/AML JM/BB/TT/HT
2. **Voice/LLM Engineer** — Whisper/Ollama/Piper, multilingual

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## 📄 License

MIT License — see [LICENSE](LICENSE)

---

## 🔗 Links

- **Buildathon:** https://futurecaribbean.com
- **Application:** https://futurecaribbean.com/apply
- **Discord:** https://discord.gg/futurecaribbean
- **Lead:** Ralph Valcin (Haitian native, AI healthcare SDET)

---

*Built for the Future Caribbean Global AI Buildathon — Track 3: Finance, Payments & MSME Capital*