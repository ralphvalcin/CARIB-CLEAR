# Architecture Review — AML/PEP Ledger Productization

**Scope:** compliance/config flow into API and worker, worker lease-based queue lifecycle, audit trail append-only guarantees, Helm/K8s fit, alignment with prior phases.  
**Artifacts reviewed:** `carib_clear/compliance/{screening.py, providers.py,cache.py}`, `carib_clear/config/{__init__.py, compliance_lists.json}`, `carib_clear/worker/settlement_worker.py`, `carib_clear/governance/approval.py`, `carib_clear/audit.py`, `carib_clear/db.py`, `carib_clear/api.py`, `carib_clear/secrets.py`, `carib_clear/agents/compliance.py`, `carib_clear/config_reloader.py`, `helm/carib-clear/...`, `k8s/...`, targeted tests.

---

## Review Goals — Status

| Goal | Status | Notes |
| --- | --- | --- |
| New modules wired into real flows (not just added) | Partial Yes | Screening is used by `/settlements` and worker, but APIs rebuild engine per-request. |
| Data flow: screening -> worker/API -> audit trail | Yes with gaps | Audit hooks exist on key API writes; worker does not append audit on executed/failed. |
| No demo-only shortcuts in production paths | No | `/market/state`, `/liquidity/state`, and broker/demo adapters still call `generate_mock_*` and mock adapters inside production endpoints. |
| Test coverage reflects actual behavior | Partial Yes | Screening, worker, audit, and idempotency have tests, but no worker->audit trace test. |
| No architectural drift from Vault/KYC/K8s phases | Partial Yes | Vault hook exists; KYC enforcement is present in API but not worker; K8s has gaps. |

---

## Findings

### 1) Compliance/Config Flow Into API and Worker
- **Finding:** Stable config path exists (`CARIB_CLEAR_COMPLIANCE_LISTS` -> `config/__init__.py` -> JSON-backed `ComplianceListConfig` -> registry -> cache). `config_reloader.py` can reload lists, but there is no runtime watcher/auto-reload hook.
- **Finding:** `api.py` instantiates `ComplianceScreeningEngine` inside `/settlements`, `/compliance/screen`, and `/compliance/reload-lists`. This works, but creates duplicated engine instances per request.
- **Finding:** Worker also builds its own engine in `__init__`; no shared singleton or app-level cache across API + worker.
- **Finding:** `agents/compliance.py` still carries parallel mock logic (`_screen_sanctions`, `_screen_pep`, `_detect_anomaly`, jurisdiction defaults) used by onboarding/KYC flows. New provider engine does not replace it yet, creating two compliance surfaces.
- **Follow-up:**
  - P2: Add hot-reload watcher for list file changes.
  - P2: Unify compliance/agent and screening-engine flows or mark legacy path demo-only.

### 2) Worker Queue Lifecycle With Lease-Based Claiming
- **Finding:** `approval.py` supports lease fields (`claimed_by`, `claimed_at`, `lease_until`), stale lease reclamation, and retry-with-fail state transitions.
- **Finding:** Worker uses `claim_for_execution` correctly, but **claims force status to `approved` even if the item was already `denied` or `executed`** (claim condition allows re-claim of approved stale leases). This can resurrect already-decided items.
- **Finding:** `reclaim_stale_claims()` exists but is **not called** by the worker, so worker leases can grow stale without recovery.
- **Finding:** Worker DB path defaults to `data/settlement_approvals.db`, separate from main `carib_clear.db`; no cross-DB transaction or event recording.
- **Finding:** Worker does not append audit events for executions/blocked decisions, leaving a trace gap.
- **Follow-up:**
  - P0: Fix claim condition to include `pending` or stale approved only; exclude `denied/executed/failed`.
  - P0: Worker should call `reclaim_stale_claims` before `run_once`.
  - P1: Worker AML block path should emit `audit(...)`.
  - P2: Align default DB path/model for approvals with main DB or document multi-DB topology.

### 3) Audit Trail Append-Only Guarantees
- **Finding:** `audit.py` only inserts; existing search found no `audit_trail` DELETE path in code.
- **Finding:** DB layer exposes a generic `delete()` method and raw `execute()` on all allow-listed tables. Nothing technically prevents app code from deleting `audit_trail` rows.
- **Finding:** `audit_trail` lacks DB-level append-only enforcement; no `ONLY INSERT` policy/RLS in schema.
- **Follow-up:**
  - P1: Add DB policy/guard to prevent delete/update on `audit_trail`.
  - P2: Add integration test asserting delete API/helper fails.

### 4) Helm Chart Deployment Fit
- **Finding:** `helm/carib-clear/values.yaml` omits `CARIB_CLEAR_COMPLIANCE_LISTS`, so list reload is non-functional in Helm by default.
- **Finding:** `templates/secret.yaml` has invalid rendering syntax around `api-key`: `*** .Values.api.env.apiKey | quote }}`.
- **Finding:** Default tag `latest` is unsuitable for production; README notes this but values keep it default.
- **Finding:** Worker readiness/liveness exec commands reference `carib_clear.worker.health`, which was missing until this review added it; that shouldn't block, but it's a late patch.
- **Finding:** No Postgres PVC/pitrtool/backup manifests; DB is configured via secret URL but not operationalized for K8s durability.
- **Finding:** Official `k8s/api-deployment.yaml` and `k8s/worker-deployment.yaml` duplicate/inline Helm concerns with no rendered output parity; key env wiring differs.
- **Follow-up:**
  - P1: Fix secret template, remove `latest` default in production docs, add `complianceListsPath` value/env.
  - P1: Add optional Postgres provision or PVC manifest, or external DB notes.
  - P2: Add backup job + PITR guidance for financial DB.

### 5) Alignment With Prior Phases
- **Vault:** `secrets.py` already supports `CARIB_CLEAR_SECRET_BACKEND=vault`; Helm templates export optional envs. **Aligned.**
- **KYC:** API settlement route enforces `require_verified_participant`; onboarding sets verified status. **Partially aligned.** Worker has no participant/KYC gate and can execute approval items without identity/compliance checks.
- **K8s:** Chart plus standalone YAML present, but render parity and runtime health checks are inconsistent; no Webhook/queue sidecar for distributed workloads. **Partially aligned.**
- **Follow-up:**
  - P0: Add KYC participant verification into worker execution path.
  - P1: Reconcile standalone K8s YAML with Helm templates or remove standalone.
  - P2: Align ledger/event topology with settlement worker output.

---

## Top Required Follow-Ups

### P0
1. Harden worker claim semantics to avoid re-claiming denied/executed/failed items.
2. Add stale-claim reclamation to worker loop.
3. Add worker compliance block audit event emission.
4. Enforce KYC/participant verified status in worker execution path.
5. Fix Helm secret template syntax and add missing `CARIB_CLEAR_COMPLIANCE_LISTS`.

### P1
6. Prevent `audit_trail` mutations at DB level; add delete-failure regression test.
7. Add operational DB durability guidance/backup artifacts for K8s.
8. Document or implement runtime compliance list reload watcher.
9. Unify or clearly demarcate legacy compliance agent vs new provider engine.

### P2
10. Add worker K8s health probe (`health.py` added; verify rendered manifests).
11. Reconcile reproduction between standalone K8s manifests and Helm output.

---

## Recommended Next Checkpoint
Run a targeted integration scenario: enqueue approval -> worker claim -> AML block -> audit row created -> stale expiry -> re-claim allowed -> verify no double execution, plus Helm template render diff against standalone K8s YAML.
