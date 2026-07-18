# CARIB-CLEAR Productization Plan
_Sequential, checkpoint-verified, no blind delegation._

## Goal
Move CARIB-CLEAR from demo to production-ready financial infrastructure by closing the remaining review items in priority order, with explicit checkpoints after each phase.

## Completed Phases
- Phase 1: Helm Packaging Health — Helm values, docs, and secret wiring audited; production override guidance added.
- Phase 2: Compliance API Hardening — jurisdiction derivation, admin-only reload, list route hardened.
- Phase 3: Legacy Compliance Demarcation / Unification — legacy `agents/compliance.py` retained as compatibility wrapper with regression coverage.
- Phase 4: Operator Audit API — `/audit/events` filters, admin enforcement, operator console notes/escalate.
- Phase 5: DB Durability / K8s Operations — production `CARIB_CLEAR_DATABASE_URL` enforcement; SQLite fail-fast; Helm docs updated.
- Phase 6: Operator Console UX Hardening — date-range filters added with backend `start`/`end` query support; focused regression tests added.
- Cleanup Phase: Repo Hygiene — removed unused static assets and tracked `.DS_Store` files; README/doc alignment.

## Remaining Focus
- Optional: additional K8s manifest hardening
- Optional: operator/runtime inspector cleanup
- Optional: deprecated-path removal if demo/legacy routes are no longer desired

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
