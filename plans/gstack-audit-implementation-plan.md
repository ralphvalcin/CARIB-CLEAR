# CARIB-CLEAR — gstack Audit Implementation Plan

> **Compiled from:** gstack framework audit (voice removed)
> **Scope:** Address every skill-level finding across `/office-hours`, `/plan-ceo-review`, `/plan-eng-review`, `/plan-design-review`, `/review`, `/investigate`, `/qa`, `/cso`, `/ship`, `/land-and-deploy`
> **Posture:** Buildathon prep + Phase 1 post-buildathon foundation

---

## Executive Summary

The composite gstack score moved 4.8 → 5.6/10 after the voice layer was tabled. Voice removal eliminated coupling bugs and forced the product to stand on technical merits. The remaining gaps cluster in six areas:

| Cluster | gstack Skill | Severity |
|---|---|---|
| **No persistent state** | `/review` | 🔴 CRITICAL |
| **No typed inter-agent contracts** | `/plan-eng-review` | 🔴 CRITICAL |
| **No auth / RBAC** | `/cso` | 🔴 CRITICAL |
| **No CI/CD** | `/ship` | 🔴 HIGH |
| **Error / observability gaps** | `/plan-design-review` | ⚠️ HIGH |
| **No legal entity / cap table / incorporation** | `/plan-ceo-review` | 🔴 CRITICAL |
| **Demo reliability (StringIO, blocking I/O)** | `/investigate` | ⚠️ MEDIUM |
| **Prometheus metrics not verified** | `/plan-design-review` | ⚠️ MEDIUM |
| **No lender contract / term sheet** | `/office-hours` | 🔴 HIGH |
| **No incorporation / legal entity** | `/plan-ceo-review` | 🔴 HIGH |
| **No bank/KYC provider partnership** | `/plan-ceo-review` | 🔴 HIGH |
| **No financial regulators engaged** | `/plan-ceo-review` | 🔴 HIGH |
| **Production-critical bugs pass tests** | `/review` | 🔴 HIGH |

---

## Phase 0: Voice Layer Removal *(30 min)*

**Goal:** Cleanly eliminate the voice coupling without breaking any API or agent path.

**Files to touch:**

| Action | File | Change |
|---|---|---|
| Remove import | `carib_clear/__init__.py:30` | Delete `from .voice_bridge import VoiceLoanBridge` from imports and `__all__` |
| Remove step | `carib_clear/demo.py:487-509` | Delete the entire Step 5 block in `run_full_demo()` |
| Docstring fix | `carib_clear/config/gpu.py:7-14` | Remove `kreyol:3b` model reference from docstring |
| Delete (no importers) | `carib_clear/voice_bridge.py` | Remove file — no other module imports it |
| Delete (no importers) | `carib_clear/voice_demo.py` | Remove file — standalone CLI |

**Verification:**
- `python -m carib_clear.demo full` runs all 4 remaining steps, exits clean, produces identical Layer 1 + Layer 2 output
- `pytest tests/ -q` passes (no test imports voice modules)
- `python -m carib_clear.api` starts, all 24 endpoints respond

**Risk:** None — voice coupling is CLI-only, zero API surface.

---

## Phase 1: Typed Inter-Agent Contracts *(2 sessions)*

**Goal:** Define explicit request/response contracts between every agent pair. This is the prerequisite for every subsequent phase — without it, each new rail or lender is wiring bugs.

**The contracts:**

```
FlowVisibility  →  P2PMatching
  Request:  P2POrderRequest(participant_id, currency_from, currency_to, amount_usd, max_rate, jurisdiction)
  Response: P2POrderResult(order_id, matched, matched_amount, rate, rail_used, settlement_result)

P2PMatching  →  NetSettlement
  Request:  NettingRequest(transactions: list[TransactionInput])
  Response: NettingCycleResult(cycle_id, gross_volume, net_volume, efficiency, settlement_instructions)

NetSettlement  →  MultiRailRouter.broker.submit_settlement()
  Input:    SettlementInstruction(from_participant, to_participant, from_currency, to_currency, amount, rail)
  Output:   SettlementResult(tx_hash, rail, status, timestamp, amount_settled, fee_bps)

CashFlowLending  →  LenderAdapter.submit()
  Request:  LenderSubmission(business_id, amount, purpose, credit_profile, terms)
  Response: LenderResponse(lender_application_id, status, message, approved_amount, rate, tenure)
```

**Files to create/modify:**

| File | Action | Content |
|---|---|---|
| `carib_clear/contracts.py` | CREATE | Pydantic models for all 4 contract pairs above |
| `carib_clear/agents/flow_visibility.py` | MODIFY | `P2POrderRequest` return type |
| `carib_clear/agents/p2p_matching.py` | MODIFY | Accept typed `P2POrderRequest`, return `P2POrderResult` |
| `carib_clear/agents/net_settlement.py` | MODIFY | Accept `NettingRequest`, return `NettingCycleResult` |
| `carib_clear/agents/cash_flow_lending.py` | MODIFY | Accept `LenderSubmission`, return `LenderResponse` |
| `tests/test_contracts.py` | CREATE | Validation tests for each contract — round-trip serialization, field validation |

**Verification:**
- `python -c "from carib_clear.contracts import *; print('OK')"` imports clean
- `pytest tests/test_contracts.py -v` — every contract serializes/deserializes with valid data, rejects invalid data
- `pytest tests/ -q` — all existing tests still pass

**Risk:** LOW — contracts are additive types. No behavior changes.

---

## Phase 2: Demo Reliability Fixes *(1 session)*

**Goal:** Make `demo full --live` reliable, self-contained, and fast. Fix the three structural demo bugs identified by `/investigate`.

### Block 2A: Remove StringIO capture

**What:** `demo.py` currently captures stdout via StringIO in some code paths. Replace with structured result dataclasses that the demo loop prints.

**Files:** `carib_clear/demo.py`, `carib_clear/demo_runner.py`

### Block 2B: Fix blocking I/O in API demo endpoints

**What:** `/demo/full`, `/demo/fx_swap`, `/demo/msme_credit` run synchronously. A judge hitting the endpoint waits 4-5s. This is acceptable for a demo but must not block the event loop.

**Change:** Wrap demo runs in `asyncio.to_thread()`.

```python
# Before
@app.get("/demo/full", response_model=DemoResponse)
async def run_full_demo_endpoint():
    result = run_full_demo_capture()  # blocking

# After
@app.get("/demo/full", response_model=DemoResponse)
async def run_full_demo_endpoint():
    result = await asyncio.to_thread(run_full_demo_capture)
```

**Files:** `carib_clear/api.py` (lines 260-360)

### Block 2C: Wire live Stellar settlement into demo

**What:** `python -m carib_clear.demo full --live` prints mock settlement output. Replace with real path payment.

**Change:** When `live=True`, `StellarAdapter.submit_settlement()` already exists in `broker/stellar_adapter.py` — verify it's the live path, not mock.

**Files:** `carib_clear/broker/stellar_adapter.py`, `carib_clear/demo.py`

**Verification:**
- `python -m carib_clear.demo full` — <4s, mock mode, all 4 steps
- `python -m carib_clear.demo fx_swap --live` — real Stellar tx hash in output
- `curl http://localhost:8000/demo/full` — JSON response in <5s
- `curl http://localhost:8000/demo/fx_swap` — JSON response in <3s

---

## Phase 3: API Hardening *(2 sessions)*

**Goal:** The 24 REST endpoints are now the primary judge-facing product. They need to be credible.

### Block 3A: API Key Auth

**What:** Every `/loan/*`, `/compliance/*`, `/liquidity/*` endpoint requires `X-API-Key` header. Health and demo endpoints stay open.

**Implementation:**
```python
API_KEYS: dict[str, str] = {}  # api_key -> participant_id, loaded from env/cfg

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if request.url.path in ("/", "/health", "/docs", "/dashboard", "/demo"):
        return await call_next(request)
    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    request.state.participant_id = API_KEYS[api_key]
    return await call_next(request)
```

**Files:** `carib_clear/api.py`
**Config:** `config/api_keys.json` (loaded at startup, not checked in)

### Block 3B: Rate Limiting

**What:** `/loan/apply` max 10 req/min per API key. `/compliance/onboard` max 5/min.

**Implementation:** In-memory token bucket (no Redis dependency yet). `carib_clear/rate_limit.py`.

### Block 3C: Structured Error Envelope

**What:** Every error response returns:
```json
{
  "status": "error",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "amount_usd must be > 0",
    "request_id": "abc123",
    "timestamp": "2026-06-29T14:22:01Z"
  }
}
```

**Implementation:** Replace scattered `HTTPException` raises with a helper that generates correlation IDs.
**Files:** `carib_clear/api.py`, new `carib_clear/errors.py`

### Block 3D: Correlation IDs

**What:** Every request gets a `X-Request-ID` header. Returned in error responses and logged with every agent action.

**Implementation:** `middleware("http")` that generates `uuid4` per request, stores on `request.state`.

**Verification:**
- `curl -H "X-API-Key: test" -H "Content-Type: application/json" -d '{"amount_usd": 5000}' http://localhost:8000/loan/apply` → 200 with typed response
- `curl` without API key → 401
- 11 rapid requests → 429 on request 6
- Error response includes `"error": {"request_id": "..."}`
- Every response includes `X-Request-ID` header

---

## Phase 4: CI/CD + Test Coverage Audit *(1 session)*

**Goal:** Every push runs the full suite. Coverage reports are generated and tracked.

### Block 4A: GitHub Actions CI

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e '.[dev]'
      - run: pytest tests/ -v --tb=short
      - run: pytest tests/ --cov=carib_clear --cov-report=xml
      - uses: codecov/codecov-action@v4
```

### Block 4B: Coverage Audit

Run `pytest --cov=carib_clear --cov-report=html`. Target: **80% line coverage** on `agents/`, `broker/`, `api.py`. Identify untested code paths and write tests for them.

**Current known gaps:**
- `broker/terrapay_adapter.py` — no test file exists
- `carib_clear/sep31/` — no test coverage
- `carib_clear/iso20022/` — no test coverage
- `carib_clear/webhooks/` — no test coverage
- `carib_clear/plugin/registry.py` — no test coverage

### Block 4C: `.env.example`

Create `config/.env.example` with all required environment variables documented:
```
STELLAR_HORIZON_URL=https://horizon-testnet.stellar.org
STELLAR_SECRETS_PATH=secrets/stellar-testnet.json
STELLAR_HUB_SECRET=<secret>
CARIB_CLEAR_API_KEYS={"test-key-1": "participant-001"}
```

**Verification:**
- Push to `main` → GitHub Actions shows green check
- Coverage report shows ≥80% on core modules
- `cp config/.env.example .env` sets up a new dev environment in <60 seconds

---

## Phase 5: Ops Foundation *(2 sessions)*

**Goal:** Observable, debuggable, production-ready.

### Block 5A: Prometheus Metrics Verification

**What:** `/metrics` endpoint exists (line 220 of `api.py`). Verify it actually emits metrics.

**Audit the current implementation:** Read `api.py:220-260` and check whether the endpoint emits *real* values or stubs.

**Action:**
1. Emit `carib_clear_demo_duration_seconds` (histogram) per demo endpoint
2. Emit `carib_clear_loan_applications_total` (counter), partitioned by `jurisdiction`, `approved`
3. Emit `carib_clear_settlements_total` (counter), partitioned by `rail`, `status`
4. Emit `carib_clear_compliance_checks_total` (counter), partitioned by `jurisdiction`, `passed`

### Block 5B: Webhook System

**What:** Implement the `WebhookRegisterRequest` / `WebhookResponse` models that already exist in `api.py:151-168` but may not be fully implemented.

**Check:** `carib_clear/webhooks/__init__.py` — verify the registry and delivery logic are wired.

**If not wired:** Implement in-memory webhook delivery with HMAC-SHA256 signatures, retry with exponential backoff. Gate for Phase 2 upgrade to persistent queue.

### Block 5C: Secret Management

**What:** Replace hard-coded Stellar secret paths with environment variable injection:
```python
STELLAR_SECRETS = os.getenv("STELLAR_SECRETS_PATH", "secrets/stellar-testnet.json")
```

Add a `scripts/check-secrets.sh` that verifies required secrets exist before demo runs.

**Verification:**
- `curl localhost:8000/metrics` → Prometheus text format with real counters/gauges
- Register a webhook → receive a signed POST on the test endpoint
- Missing `STELLAR_SECRETS_PATH` → clear error message, not a traceback

---

## Phase 6: Persistence Layer *(3 sessions — Post Buildathon)*

**Goal:** Replace in-memory state with PostgreSQL. This is the biggest single investment but also the highest impact.

### Block 6A: Database Schema

```sql
CREATE TABLE participants (
    id TEXT PRIMARY KEY,
    jurisdiction TEXT NOT NULL,
    kyc_status TEXT NOT NULL DEFAULT 'pending',
    kyc_documents JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE orders (
    id TEXT PRIMARY KEY,
    participant_id TEXT REFERENCES participants(id),
    currency_from TEXT NOT NULL,
    currency_to TEXT NOT NULL,
    amount_usd NUMERIC NOT NULL,
    rate NUMERIC,
    status TEXT NOT NULL DEFAULT 'open',
    rail_used TEXT,
    tx_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE loan_applications (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL,
    business_name TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    amount_usd NUMERIC NOT NULL,
    purpose TEXT,
    approved BOOLEAN,
    interest_rate_pct NUMERIC,
    tenure_months INT,
    lender_id TEXT,
    credit_score NUMERIC,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE settlements (
    id TEXT PRIMARY KEY,
    order_id TEXT REFERENCES orders(id),
    rail TEXT NOT NULL,
    tx_hash TEXT,
    amount_settled NUMERIC,
    fee_bps NUMERIC,
    status TEXT NOT NULL,
    confirmed_at TIMESTAMPTZ
);
```

### Block 6B: SQLAlchemy Repository Layer

Replace `_loan_history: List[Dict]` and `_demo_cache: Dict` in `api.py:176-177` with `LoanRepository`, `OrderRepository`, `ParticipantRepository`.

### Block 6C: Alembic Migrations

Standard Alembic setup for schema evolution. All Phase 2+ features depend on this.

**Verification:**
- API restarts → data persists (test: create participant, restart, query → participant exists)
- `pytest tests/test_persistence.py` passes
- Docker compose includes `postgres` service

---

## Phase 7: Market Integration *(3 sessions — Post Buildathon)*

**Goal:** Validate the competitive moat: SEP-31 compliance + ISO 20022 + TerraPay integration.

### Block 7A: SEP-31 Compliance

**What:** Implement the Stellar cross-border payment standard (SEP-31). This is the endpoint that any Stellar anchor routes through CARIB-CLEAR automatically.

**Endpoint contract:**
```python
POST /sep31/receive
GET  /sep31/transaction/{id}
POST /sep31/transaction/{id}/callback
```

**Reference:** `carib_clear/sep31/__init__.py` exists. Implement the `register_with_app` function fully.

### Block 7B: ISO 20022 Translation Layer

**What:** Banks submit FX settlement instructions in SWIFT MX format. CARIB-CLEAR translates to internal models and back.

**Reference:** `carib_clear/iso20022/api.py` exists. Implement the `register_iso20022` function fully.

### Block 7C: TerraPay Integration

**What:** Add a new `TerrapayAdapter` to the plugin registry. TerraPay's single API gives access to Caribbean mobile money, bank accounts, and cash pickup.

**Implementation:** Extend the existing `PluginRegistry` discovery to find `terrapay_adapter.py` and register it as `terrapay` rail.

---

## Sequencing & Dependencies

```
PHASE 0 (30min) ─────────────────────────────────────────┐
                                                          ▼
PHASE 1: Typed Contracts (2 sessions) ──────► PHASE 2: Demo (1 session)
                                                          ▼
PHASE 3: API Hardening (2 sessions) ◄───── PHASE 4: CI/CD (1 session)
         (needs Phase 1 contracts)                     │
                                                         ▼
PHASE 5: Ops Foundation (2 sessions) ◄────── PHASE 4 (metrics coverage gap)
                                                         │
                                                         ▼
PHASE 6: Persistence (3 sessions) ◄─────────── PHASE 5 (DB-backed metrics)
                                                         │
                                                         ▼
PHASE 7: Market Integration (3 sessions) ◄──── PHASE 6 (SEP-31 needs DB)
```

**Critical path:** Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → (Phase 6/7 parallel after Buildathon)

---

## Risk Matrix

| Block | Risk | Likelihood | Mitigation |
|---|---|---|---|
| Phase 1: Typed contracts | Agent behavior change | Medium | Contracts are additive; existing function signatures preserved via `**kwargs` |
| Phase 2: Demo reliability | Live Stellar fails in demo | Medium | Fall back to mock on any exception; log tx_hash attempt |
| Phase 3: API auth | Judges forget API key | Low | Demo endpoints stay open; health + demo endpoints are unauthenticated |
| Phase 6: Persistence | Schema changes break adapter | Medium | Alembic migrations are reversible; dual-write (memory + DB) during transition |
| Phase 7: TerraPay | No sandbox credentials | High | Mock adapter first; real credentials post-Buildathon |

---

## Success Criteria Summary

| Phase | Criterion |
|---|---|
| 0 | `demo full` runs without voice imports; all tests pass |
| 1 | Every agent pair has a typed contract in `contracts.py`; `test_contracts.py` green |
| 2 | Demo runs <4s; `--live` shows real tx hash; API endpoints <5s |
| 3 | No endpoint returns without `X-Request-ID`; unauthenticated requests get 401 |
| 4 | GitHub Actions green on master; coverage report ≥80% |
| 5 | `/metrics` emits 4+ real metric series; webhooks deliver |
| 6 | API restart doesn't lose data; PostgreSQL schema matches contracts |
| 7 | SEP-31 receive endpoint returns 202 on valid payload |

---

## Quick-Start for Next Session

Recommended order of attack, in priority:

1. **Phase 0 (30 min):** Remove voice coupling — immediate clarity + smaller surface
2. **Phase 1 (2 sessions):** Typed contracts — unblocks everything else
3. **Phase 2 (1 session):** Demo reliability — polished demo = better buildathon impression
4. **Phase 4 (1 session):** CI/CD — one hour, permanent value, makes everything else safe to ship
5. **Phase 3 (2 sessions):** API hardening — needs contracts from Phase 1

Phases 5-7 are post-Buildathon. Don't start them until after the pitch.
