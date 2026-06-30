# CARIB-CLEAR — Buildathon Pitch & Demo Script

## 🎯 Elevator Pitch (30 seconds)

> "Caribbean businesses lose $1.4B annually in FX fees because every cross-border payment routes through USD. CARIB-CLEAR is agentic infrastructure that connects Caribbean currencies directly — BBD to JMD in 5 seconds for 10 basis points — and lends to MSMEs using cash flow data instead of collateral. Built on Stellar, powered by AI agents."

---

## 📋 Demo Flow (5 minutes for judges)

### 0:00 — The Problem (30s)
**Say:** "The Caribbean is fragmented — 15 currencies, no unified payment system. MSMEs (80-90% of businesses) can't get loans without real estate collateral."

**Show:** Dashboard header with mission statement + Architecture flow diagram.

### 0:30 — Layer 1: FX Swap (90s)
**Say:** "CARIB-CLEAR connects 6 currencies directly. Click 'Run Full Demo'."

**Action:** Click **▶ Run Full Demo**

**Point to:**
- Flow diagram highlights Layer 1
- Cost comparison updates: "$4,000 → $50" = **98.75% cheaper**
- Metrics row shows $16.4M liquidity
- Architecture: Flow Visibility → P2P Matching → Liquidity Pools → Compliance

**Killer stat:** "3 days via bank wire → 5 seconds via Stellar. 8% fees → 0.1%."

### 2:00 — Layer 2: MSME Credit (90s)
**Say:** "Cash-flow based lending. No collateral needed."

**Action:** Type business name "Atelier Kreyol", select Haiti "🇭🇹", amount $25,000 → Click Apply

**Point to:**
- Flow diagram highlights Layer 2
- Loan table shows approved with 12% APR
- "No collateral required — uses POS data, invoices, bank statements"

**Killer stat:** "$10B MSME credit gap in the Caribbean. We open that."

### 3:30 — Kreyol Voice Demo (60s)
**Say:** "Haiti is the largest remittance corridor — $3.8B/year. Our voice bridge works in Kreyòl."

**Show (or describe):** "Mwen bezwen $5,000 pou biznis mwen" → CARIB-CLEAR processes → Kreyòl response via TTS

**Killer stat:** "Voice-first for the 40% of Haitian adults without formal banking."

### 4:30 — Close (30s)
**Say:** "Built on Stellar testnet — live path payments verified. 250 tests passing. Docker compose up runs the whole thing. We're solving a $10B+ problem with 5 seconds and 10 basis points."

---

## 🗣️ Talking Points by Topic

### The Problem
- $700B Caribbean economy, 15+ currencies
- $20B annual remittances at 7-9% fees = $1.4B lost to intermediaries
- 80-90% of businesses are MSMEs — no collateral = no loans
- $10B+ MSME credit gap (IDB Invest)

### Why Agentic AI?
- Rails are heterogeneous (Stellar, ACH, Mobile Money, RTGS)
- Regulations are jurisdiction-specific (5+ regulators)
- Liquidity is fragmented (no central order book)
- Agents discover, match, settle, and adapt in real-time

### Why Stellar?
- Path payments = atomic multi-hop FX swaps (BBD→USDC→JMD in one tx)
- AMM liquidity pools for 6 currency pairs
- 5 second finality vs 2-3 days correspondent banking
- USDC bridge (Circle-regulated) for immediate liquidity
- Upgrade path to self-issued CARICOM tokens

### Buildathon Differentiators
- **3 production codebases merged** — not a prototype (trading system + JARVIS voice + Kreyol-AI)
- **Voice-first in Kreyòl** — nobody else does this
- **Multi-rail** — not locked to one blockchain (Stellar, ACH, Mobile Money)
- **Live Stellar testnet** — real on-chain transactions, verified
- **250+ tests** — engineering quality
- **Docker compose up** — judges can run it immediately

### Numbers to Know
| Metric | Value |
|--------|-------|
| Traditional FX fee | 7-9% ($4K on $50K) |
| CARIB-CLEAR FX fee | 0.1% ($50 on $50K) |
| Time saved | 3 days → 5 seconds |
| MSME credit gap | $10B+ |
| Haiti remittances | $3.8B/yr (25% of GDP) |
| Total liquidity | $16.45M (demo) |
| AMM pools | 5 (BBD, JMD, TTD, XCD, HTG) |
| Stellar settlement | 4.3 seconds, $0.001 fee |
| Tests passing | 250+ |
| Build time | 6 weeks (solo) |

---

## 🖥️ Live Demo Script (what to click)

### Option 1: CLI (no GUI needed)
```bash
# Mock demo — works anywhere
python -m carib_clear.demo full

# Live demo — Stellar testnet
python -m carib_clear.demo fx_swap --live
```

### Option 2: Docker (judges, no Python needed)
```bash
docker compose up
```

### Option 3: Dashboard (best for presentation)
```bash
pip install -e .[stellar]
python -m carib_clear.api
# Open http://localhost:8000/dashboard
```

---

## 📊 Dashboard Walkthrough

1. **Header** — Mission statement + 5 key metrics
2. **Architecture Flow** — Two-layer design with all 6 buildathon steps
3. **Cost Comparison** — "98.75% cheaper" banner (updates after demo)
4. **Charts** — Cost comparison bar chart + Liquidity by currency
5. **▶ Run Full Demo** — Execute full pipeline, see results update live
6. **Loan form** — Apply for a loan, see approval in table
