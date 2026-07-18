## 3. TECHNICAL ARCHITECTURE

### 3.1 Agent Swarm (LangGraph on H200)

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: CARICOM FX SWAP NETWORK                           │
├─────────────────────────────────────────────────────────────┤
│  FlowVisibilityAgent  →  P2PMatchingEngine  →  NetSettlementAgent  │
│       (AI)                    (Core)                (Core)       │
│                                                             │
│  LiquidityPoolSim  +  SmartRoutingAgent  +  ComplianceAgent     │
│       (Market)           (AI)              (Deterministic+AI)    │
│                                                             │
│  MultiRailBroker: StellarAdapter • ACHAdapter • MobileMoneyAdapter │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2: MSME CREDIT LAYER                                 │
├─────────────────────────────────────────────────────────────┤
│  DataAggregationAgent  →  CreditProfileGenerator  →  CashFlowLendingEngine │
│       (ETL)                    (AI)                     (Rules+AI)         │
│                                                             │
│  TradeFinanceModule  •  InvoiceFactoring  •  LenderAdapters      │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Codebase Integration

| Component | Source | Integration |
|-----------|--------|-------------|
| Governance/HITL/Approval Queue | trading-system | Direct import as `governance/` package |
| Multi-rail Broker Abstraction | trading-system (Alpaca) | Extended to `MultiRailBroker` base |
| Agent Orchestration | JARVIS | LangGraph swap, same patterns |
| Voice Pipeline (Whisper/Ollama/Piper) | JARVIS | `kreyol:3b` model added |
| Kreyol LLM (QLoRA Llama 3.2 3B) | Haiti AI Lab | Merged to Ollama, served via JARVIS |