# CARIB-CLEAR Productization Plan
_Sequential, checkpoint-verified, no blind delegation._

## Goal
Move CARIB-CLEAR from demo to production-ready financial infrastructure by closing the remaining review items in priority order, with explicit checkpoints after each phase.

## Current Verified Baseline
- 291 passed, 1 skipped, 2 warnings
- Worker/KYC/ledger hardening complete
- Reviews finalized:
  - `REVIEW_FINDINGS_AML_LEDGER.md`
  - `ARCHITECTURE_REVIEW_AML_LEDGER.md`

## Planned Phases

### Phase 1: Helm Packaging Health
Objective: make chart deployment-ready and worker/env-complete.
- Repair `helm/carib-clear/templates/secret.yaml` with valid YAML and include `api-key` + `secret-backend` fields.
- Verify `CARIB_CLEAR_COMPLIANCE_LISTS` is wired in worker deployment from `.Values.worker.env.complianceLists`.
- Remove unsafe `latest` default in docs/values and add `image.tag` enforcement check.
- Checkpoint: `helm lint`, `helm template`, and review rendered worker env block.

### Phase 2: Compliance API Hardening
Objective: remove hardcoded jurisdictions and tighten reload endpoint.
- Make `/compliance/screen` derive `from_jurisdiction` / `to_jurisdiction` from request or participant metadata; reject empty/unknown instead of BB/JM fallback.
- Make `/compliance/reload-lists` emit `audit(...)`, validate path exists/non-empty, and require admin scope/role.
- Add `/compliance/lists` read endpoint returning active sources + loaded keyword counts.
- Checkpoint: targeted tests green; review docs/examples.

### Phase 3: Legacy Compliance Demarcation / Unification
Objective: one compliance surface for production.
- Decide: keep legacy `agents/compliance.py` as demo-only or bridge it to new provider engine.
- Preferred: bridge onboarding/KYC flows to `ComplianceScreeningEngine` so watchlist/sanctions logic is single-sourced.
- Checkpoint: no duplicate watchlist paths; doc-only “legacy path” label removed if bridging succeeds.

### Phase 4: Operator Audit API
Objective: read-side visibility for ledger.
- Add `GET /audit` with filters `event`, `entity`, `entity_id`, `limit`, plus `GET /audit/{audit_id}`.
- Enforce admin/operator scope; do not expose `payload` if it contains secrets.
- Checkpoint: tests pass; doc schema example updated.

### Phase 5: DB Durability / K8s Operations
Objective: production data posture.
- Add optional Postgres PVC/external DB notes; specify backup/PITR guidance.
- Add `CARIB_CLEAR_DATABASE_URL` validation that fails fast on SQLite in production profiles.
- Checkpoint: doc + manifest reviewed; no SQLite default in production values.

## Execution Rules
- Plan mode first; no execution until user confirms phase start.
- Each phase is single-pass: implement, test, checkpoint.
- Full test suite after any schema/API change.
- No broad delegation without exact scope and acceptance criteria.

## Anti-patterns To Avoid
- Hardcoded fallbacks in compliance paths
- Demo-only logic inside production routes
- Unconditional broad exception swallowing around ledger/audit writes
- Silent retries without metrics or failure surfaces

## Next Immediate Step
Proceed with Phase 1 only after your confirmation.
