# CARIB-CLEAR — Judge Demo Script

> Track 3: Finance, Payments & MSME Capital · Future Caribbean Global AI Buildathon

---

## 🎯 Elevator Pitch (30 seconds)

> "Every Caribbean cross-border payment routes through a USD bank in Miami. That's 7-9% fees and 3 days of settlement.
>
> CARIB-CLEAR replaces that pipe. Six Caribbean currencies — direct, peer-to-peer, 5 seconds, 10 basis points. 
> We also lend to MSMEs using cash flow data instead of real estate collateral.
>
> Built on Stellar. Powered by AI agents. 250 tests. Docker compose up — it works."

---

## 🖥️ Full Demo Script (5 minutes)

### Phase 1 — The Dashboard (1 minute)

**What you say:**
> "This is CARIB-CLEAR's live dashboard. Let me show you what's happening under the hood."

**What you click/point to:**
- **API status dot** (green pulsing) — "Our API is live right now on port 8000"
- **Architecture flow diagram** — "Two layers. Layer 1 is the FX Swap Network — 6 steps from flow visibility to settlement. Layer 2 is the MSME Credit engine."
- **Settlement rails row** — "Four settlement rails. Stellar at 0.1 basis points. TerraPay at 35. Local ACH. Mobile Money. The router picks the cheapest automatically."
- **Cost comparison banner** — "$4,000 vs $50. That's 98.75% cheaper. One swap saves $3,950."

### Phase 2 — Run the Demo (2 minutes)

**What you say:**
> "Let me run the full pipeline. One click."

**Action:** Click **▶ Run Full Demo**

**What happens (point to each):**
- Output box fills with Layer 1 pipeline: **Flow Visibility → P2P Matching → Settlement → Compliance**
- Key line to point out: `✓ MATCH BBD↔JMD $50,000 @ rate 76.50 via stellar_usdc`
- Then Layer 2: **Data Aggregation → Credit Scoring → Lending Engine → Loan Decision**
- Cost comparison updates: shows real savings
- Speed metric shows actual execution time

**Killer stat to say while it runs:**
> "3 days bank wire → 2.3 seconds. 8% fees → 0.1%. That one swap just saved $3,950."

### Phase 3 — Deep Dive: The Infrastructure (1 minute)

**What you say:**
> "This isn't a prototype. Let me show you the infrastructure that makes this real."

**Action:** Click **Swagger API** (opens `/docs`)

**Point to:**
- **30+ endpoints** — "Everything you just saw is REST API-first."
- **`/iso20022/fx`** — "Banks can submit ISO 20022 FX confirmations. Standard SWIFT format. Any bank can integrate."
- **`/sep31/info`** — "SEP-31 compliance. Any Stellar anchor can route through CARIB-CLEAR automatically."
- **`/webhooks/register`** — "Settlement notifications for bank partners. HMAC-signed. Auto-retry."
- **`/metrics`** — "Prometheus endpoint for monitoring. Production-ready."

### Phase 4 — The Numbers (30 seconds)

**What you say:**
> "Let me give you the numbers that matter."

| Metric | Traditional | CARIB-CLEAR |
|--------|-------------|-------------|
| FX fee on $50K | $4,000 | $50 |
| Settlement time | 3 days | 5 seconds |
| Currencies supported | 2 (USD pairs) | 6 (any-to-any) |
| MSME loan collateral | Required | Cash-flow based |
| Lenders integrated | 0 | 3 (Barita, JMMB, IDB) |

### Phase 5 — Close (30 seconds)

**What you say:**
> "We're solving a $10+ billion problem. Caribbean businesses lose 1.4 billion dollars a year to FX intermediaries. 80% of MSMEs can't access credit. We replace both bottlenecks with infrastructure that works today.
>
> 250 tests. Live Stellar testnet settlement. Docker compose up. One click to run the full pipeline. We're ready."

---

## 🗣️ Q&A — Anticipated Questions

| Question | Answer |
|----------|--------|
| "Why Stellar and not Ethereum/Solana?" | "Stellar was purpose-built for payments — path payments, 5-second finality, native USDC. Ethereum costs $5 per transaction and takes 15 minutes. Stellar costs $0.00001." |
| "Is this real money?" | "Testnet today. But the path payment executes the exact same code as mainnet. The jump is one line change — swap the Horizon URL." |
| "How do you handle compliance?" | "SEP-12 for KYC, SEP-31 for cross-border, ISO 20022 for bank messaging. Plus a GovernanceAgent that checks every settlement against 4 compliance rules before execution." |
| "What's the business model?" | "10 basis points per transaction. At $20B Caribbean remittance volume, that's a $20M/year opportunity from FX alone. Plus credit scoring fees from lenders." |
| "Who are your competitors?" | "Western Union charges 13.78% on the Haiti corridor. TerraPay just entered T&T and Jamaica — we built a TerraPay connector that routes through them, not against them. We're the infrastructure layer." |
| "You built this solo?" | "Yes. 6 weeks. 250+ tests. 30+ API endpoints. Four settlement rails. ISO 20022 and SEP-31 compliance. Live on Stellar testnet." |
| "What's next?" | "TerraPay mainnet integration for live T&T-Jamaica corridors. IDB Pay partnership for central bank settlement. And SEP-31 mainnet for Stellar anchor compatibility." |

---

## 🔧 Demo Checklist (Before Judging)

- [ ] API server running: `python -m carib_clear.api` → health check green
- [ ] Dashboard loads: `http://localhost:8000/dashboard` → architecture flow visible
- [ ] Full demo works: Click "Run Full Demo" → output within 10 seconds
- [ ] Swagger loads: Click "Swagger API" → all endpoints listed
- [ ] Metrics endpoint works: `http://localhost:8000/metrics` → Prometheus format
- [ ] Cost comparison updates after demo
- [ ] Charts render (liquidity by currency bar chart)

### Fallback Plan (if API drops)
```bash
# CLI demo always works
python -m carib_clear.demo full      # mock
python -m carib_clear.demo fx_swap --live  # Stellar testnet
```

### Fallback Plan (if no internet)
The mock demo runs entirely offline. No external connections needed. Just `python -m carib_clear.demo full`.

---

## 📊 Numbers to Internalize

| Metric | Value | Why judges care |
|--------|-------|-----------------|
| Traditional FX fee | 7-9% ($4K on $50K) | Shows the pain |
| CARIB-CLEAR fee | 0.1% ($50 on $50K) | Shows the solution |
| Time saved | 3 days → 5 seconds | Wow factor |
| MSME credit gap | $10B+ | Market size |
| Haiti corridor fee | 9.24% (highest globally) | Emotional hook |
| Stellar tx cost | $0.00001 | Near-zero overhead |
| Active currencies | 6 (BBD, JMD, TTD, XCD, HTG, USD) | Coverage |
| Settlement rails | 4 | Redundancy |
| API endpoints | 30+ | Production readiness |
| Tests | 250+ | Engineering quality |
| Build time | 6 weeks pure code | Solo + speed |

---

## 🎬 Demo Recording Script (for submission video)

### 0:00–0:30 — Problem
*Show dashboard header with mission statement*
> "The Caribbean has 15 currencies. Every cross-border payment goes through a USD bank in Miami. That means 7% fees and multi-day settlement. And 80% of businesses — the MSMEs — can't get loans."

### 0:30–2:00 — The FX Swap
*Click "Run Full Demo" — point to Layer 1 steps*
> "Here's a Barbadian hotel needing to pay a Jamaican supplier. BBD directly to JMD through our P2P matching engine. Stellar path payment executes on-chain. 0.1% fee. 5 seconds. The bank would have charged $4,000."

### 2:00–3:30 — The Credit Layer
*Point to Layer 2 steps*
> "Same hotel applies for a loan. Our engine aggregates 12 months of point-of-sale data, bank statements, and tax records. Generates a 5 C's credit profile. Matches them to the right lender. No collateral needed."

### 3:30–4:30 — The Infrastructure
*Open Swagger docs*
> "Everything you saw is REST API-first. ISO 20022 for bank integration. SEP-31 for Stellar compliance. Webhooks for settlement notifications. Prometheus for monitoring. 30+ endpoints documented. Docker compose up."

### 4:30–5:00 — Close
*Show cost comparison banner*
> "250 tests. Live on Stellar testnet. One click. We're ready to fix Caribbean payments."
