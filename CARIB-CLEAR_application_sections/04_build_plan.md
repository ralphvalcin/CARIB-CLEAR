## 4. 21-DAY BUILD PLAN

### Week 1 (Jul 7-13): Layer 1 Core Agents
- **Day 1-2:** `FlowVisibilityAgent` — ingest multi-currency demand/supply signals
- **Day 3-4:** `P2PMatchingEngine` — direct BBD↔JMD↔TTD matching, order book from trading-system
- **Day 5:** `NetSettlementAgent` — net obligations across N participants, governance approvals
- **Day 6-7:** `ComplianceAgent` — per-jurisdiction KYC/AML rules (JM, BB, TT, HT), deterministic + AI-assisted
- **Weekend:** Integration test — CLI demo: `barbados_importer pay jamaican_supplier 50000 BBD→JMD`

### Week 2 (Jul 14-20): Layer 1 Polish + Layer 2 Start
- **Day 1-2:** `LiquidityPoolSim` + `SmartRoutingAgent` — dynamic spreads, AI path selection
- **Day 3-4:** `MultiRailBroker` adapters — Stellar testnet, ACH mock, MobileMoney mock
- **Day 5:** Voice UI integration — JARVIS pipeline + `kreyol:3b` for Haitian merchant flow
- **Day 6-7:** **Layer 2 start** — `DataAggregationAgent` (POS CSV, invoice PDF, bank statement parsers)
- **Weekend:** `CreditProfileGenerator` — cash-flow features → risk score (no collateral)

### Week 3 (Jul 21-27): Integration + Submission
- **Day 1-2:** `CashFlowLendingEngine` + `TradeFinanceModule` + `LenderAdapters` (Barita, JMMB mocks)
- **Day 3:** End-to-end flow: FX swap → net settle → credit decision → loan disburse
- **Day 4:** Benchmarks + Grafana dashboards (cost vs SWIFT, settlement time, success rate, approval rate)
- **Day 5:** Pitch deck + 3-min demo video
- **Day 6-7:** Submission package: code (GitHub), video, architecture doc, partner LOIs

### Submission Target: August 8 (build phase ends Aug 7)