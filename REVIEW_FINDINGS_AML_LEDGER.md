# CARIB-CLEAR Code Review — AML / Ledger Scope
Severity-ranked findings for the requested files, focused on wiring correctness, production readiness, scope adherence, raw SQL, demo-only paths, audit_trail deletion isolation, worker compliance gating, Helm wiring/secrets, and DB allowlist alignment.

## CRITICAL
### C-1 `audit_trail` is technically mutable through DB layer
**Files:**
- `carib_clear/db.py:403-417`, `carib_clear/db.py:375-401`, `carib_clear/db.py:365-373`

`audit_trail` is allow-listed in `_TABLES` and `delete()`/`execute()` accept any table. Nothing currently in the reviewed APIs deletes audit rows, but the primitive exists and any future path/bug can silently mutate/erase the audit ledger.

**Patch:**
- Remove `audit_trail` from `_TABLES`.
- Add a dedicated append-only helper, or guard `delete()`/`execute()` with a deny-list for `audit_trail`.

---

## HIGH
### H-1 Hardcoded jurisdictions on `/settlements` and `/compliance/screen`
**Files:**
- `carib_clear/api.py:804-836`, `carib_clear/api.py:1070-1071`

`/settlements` ignores request-provided inputs and computes jurisdictions from `from_currency`/`to_currency` via hardcoded mapping. `/compliance/screen` hardcodes `from_jurisdiction="BB"`, `to_jurisdiction="JM"`. AML screening must run on true transaction data.

**Patch:**
- Require `from_jurisdiction`/`to_jurisdiction` in requests or derive them from participant profile/identity KYC data.
- Never fall back to hardcoded `"BB"` / `"JM"`.

### H-2 Demo/mock paths in production endpoints
**Files:**
- `carib_clear/api.py:976-983`, `carib_clear/api.py:1157-1163`, `carib_clear/api.py:360-458`
- `carib_clear/worker/settlement_worker.py:71-88`

- `/liquidity/state`, `/market/state`, and settlement rails status call mock generators (`generate_mock_providers`) and `mock_mode` adapters. Under K8s these “prod mode” assumptions are undefined.
- `/demo/*` endpoints are live in the FastAPI app with no feature flag/env-gate.

**Patch:**
- Gate `/demo/*` behind `CARIB_CLEAR_ENV != production` or a feature flag.
- Ensure `/liquidity/state`, `/market/state`, and broker health endpoints raise 503/degraded when no live backing exists rather than returning fabricated data.
- In settlement screening, log and block instead of falling back to demo defaults.

### H-3 Helm worker deployment command may not resolve correctly
**Files:**
- `helm/carib-clear/templates/worker-deployment.yaml:24`
- `carib_clear/worker/__init__.py:14` (reads as having `if __name__ == "__main__"`)

Command is `python -m carib_clear.worker`. Package module resolution depends on what `__init__.py` actually does; the review target file showed only a single `__main__` line in that package. If `carib_clear/worker/__init__.py` is not an executable console script, this pod fails to start.

**Patch:**
- Verify `carib_clear/worker/__init__.py` sets up the worker loop/CLI, or replace command with `python -m carib_clear.worker.settlement_worker` and confirm CLI exists.

---

## MEDIUM-HIGH
### MH-1 Helm worker missing `CARIB_CLEAR_COMPLIANCE_LISTS`
**Files:**
- `helm/carib-clear/templates/worker-deployment.yaml:25-32`
- `helm/carib-clear/values.yaml:85-86`
- `carib_clear/worker/settlement_worker.py:34`

Worker defaults to the bundled JSON when `CARIB_CLEAR_COMPLIANCE_LISTS` is unset. In production this should be explicit ConfigMap/Secret-driven.

**Patch:**
- Add `worker.env.complianceLists` in `values.yaml` and mount it as `CARIB_CLEAR_COMPLIANCE_LISTS`, or include the list content via ConfigMap.

### MH-2 Helm secret template syntax error
**Files:**
- `helm/carib-clear/templates/secret.yaml:10-11`

Line 11 reads:
```
  api-key: *** .Values.api.env.apiKey | quote }}
```

This is missing an opening `{{` and is invalid YAML/Helm. Deployment will fail template rendering.

**Patch:**
```yaml
  {{- if .Values.api.env.apiKey }}
  api-key: {{ .Values.api.env.apiKey | quote }}
  {{- end }}
```

### MH-3 Global image uses mutable `latest` tag
**Files:**
- `helm/carib-clear/values.yaml:8`

`latest` causes non-reproducible deployments and lost traceability.

**Patch:**
- Replace `tag: latest` with a pinned build/revision tag promoted via CI/CD.

### MH-4 Registry cache lookup is source-global but store is source-specific
**Files:**
- `carib_clear/compliance/providers.py:114-130`

`CachedProviderMixin._cache_lookup`/`_cache_store` use `source_id`. Registry shortcut on line 115 reads cache from only the first provider but returns its boolean as a global result. If there are multiple sources, cache state is inconsistent: cache read can return a stale aggregate from whichever provider sorts first.

**Patch:**
- Remove the global shortcut cache read, or include `source_id` in caller-visible behavior so cache lookup semantics stay per-source.

### MH-5 DB allowlist includes tables that do not exist in schema
**Files:**
- `carib_clear/db.py:375-401`

Allow-listed tables include `compliance_profiles`, `webhook_deliveries`, `sep31_transactions`, `sep31_customers`, `iso20022_messages`, `cashflow_schedules`, `market_snapshots`, `app_state`, `ohlcv`, `trades`, `signals`, `accounts`, `equity_snapshots` — none present in `SCHEMA_SQL`. `webhook_deliveries` partial matches `delivery_attempts`+`webhook_delivery_queue`. Permit lists that don’t match schema widen attack surface for typos and future accidental schema divergence.

**Patch:**
- Remove undeclared tables or keep the allowlist in sync with the schema block.

---

## MEDIUM
### M-1 Worker compliance block is not ledgered in DB
**Files:**
- `carib_clear/worker/settlement_worker.py:72-102`

On sanctions/AML failure, worker marks approval `failed` in its local SQLite approval queue only; it does not insert `compliance_checks`, `aml_pep_hits`, or `audit_trail` records.

**Patch:**
- Insert a compliance check + AML/PEP hit + audit record on any `failed` compliance decision, mirroring `api.py` `/compliance/screen`.

### M-2 `/settlements` ignores `to_participant` identity
**Files:**
- `carib_clear/api.py:830-831`

`from_participant` and `to_participant` are both set to `identity.participant_id`. This doubles the sender as the beneficiary and breaks AML “from vs to” sanctions/PEP screening.

**Patch:**
- Accept `to_participant` in the request or derive it from counterparty metadata; do not coerce both sides to the authenticated identity.

### M-3 Reload compliance lists endpoint lacks validation/audit/access hardening
**Files:**
- `carib_clear/api.py:1130-1135`

`/compliance/reload-lists` reloads lists from env path without writing audit trail, validating schema, or ensuring API-key scope/role restriction.

**Patch:**
- Add validation, emit an `audit` event, and require elevated role.

### M-4 Silent swallowing of audit/DB exceptions masks outages
**Files:**
- `carib_clear/audit.py:40-57`, `carib_clear/audit.py:60-73`

Both `audit()` and `list_audits()` catch broad exceptions and return partial data. If DB is down, important audit writes are lost without alerting.

**Patch:**
- Re-raise or emit error metrics; at minimum ensure non-blocking audit still surfaces failures to monitoring.

### M-5 API doc version says buildathon
**Files:**
- `carib_clear/api.py:36`, `carib_clear/api.py:279-280`

Exposing buildathon metadata in production responses is out of scope for AML/ledger productization.

**Patch:**
- Make version configurable via env variable or package metadata.

---

## LOW / INFORMATIONAL
### L-1 Demo endpoints are exposed without feature-gate
Same as H-2; noted here because they do not affect correctness of AML/ledger paths, but production presentation should remove or feature-flag them.

### L-2 Audit trail schema/indexes are aligned
**Files:**
- `carib_clear/db.py:215-228`, `carib_clear/db.py:718-731`

`audit_trail` table + `insert_audit_trail`/`list_audit_trail` are present and indexed on `(event, created_at DESC)` and `(entity, entity_id)`. Wiring is correct.

### L-3 Worker health probe is import-based
**Files:**
- `carib_clear/worker/health.py:8-14`

`carib_clear.worker.health` verifies importability of `SettlementWorker`; useful for basic liveness/readiness. No deeper dependency checks.

---

## CORRECT / NO CHANGE REQUIRED
- `carib_clear/compliance/screening.py` and `carib_clear/compliance/providers.py` correctly wire `ComplianceListConfig` → registry → cache.
- `carib_clear/config/compliance_lists.json` is present and loaded with active default keywords source.
- `tests/test_settlement_worker.py`, `tests/test_audit.py`, `tests/test_compliance_screening.py` validate basic success/failure branches.
- Auth-gated production flows (`/settlements`, `/compliance/onboard`, `/loan/apply`, `/webhooks/*`, `/compliance/screen`, `/compliance/reload-lists`) exist and use `require_api_key` or `require_verified_participant`.
