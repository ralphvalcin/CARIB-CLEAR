# CARIB-CLEAR Repo Cleanup Plan
_Plan-only. No execution until confirmed._

## Goal
Remove genuinely stale files and references, keep any code/tests/docs that are still wired into production paths or live documentation, and leave the repo in a state that passes the same focused test surface we already rely on.

## Current Verified Baseline
- Main branch: `cc04bc6`
- Live Render: `https://carib-clear.onrender.com` (service `srv-d9dn8g77f7vs7391nvl0`)
- `/health` verified returning `200`
- `/operator`, `/audit/events`, `/compliance/lists`, `/compliance/reload-lists` verified endpoint behavior
- Focused tests verified:
  - `test_operator_date_range.py`
  - `test_legacy_compliance_compat.py`
  - `test_data_layer_durability.py`
  - `test_compliance_api_hardening.py`, `test_admin_audit.py`, `test_operator_audit.py`

---

## Inventory Findings
- Stale references found from search: none that break entrypoints; cleanups are confined to docs, assets, tracked junk, and genuinely unused static files.
- Productization plan still lists Phases 1–6; those deliverables are already present in code/fixtures.
- README still shows old module docs referencing `demo.py` and older agent paths.

---

## Proposed Cleanup — Phase A: Remove Unused Assets
Remove only files that have zero problem-space usage.

1. `carib_clear/static/CARIB-CLEAR Dashboard (standalone).html`
   - Why: zero references in `carib_clear`, `tests`, `README.md`, `API.md`
   - Risk: none
   - Verification: grep static paths; remove file

2. `carib_clear/static/carib-clear-workflow.png`
   - Why: zero references in `carib_clear`, `tests`, `README.md`, `API.md`
   - Risk: none
   - Verification: grep image paths; remove file

3. `tests/.DS_Store`
   - Why: tracked OS metadata
   - Risk: none
   - Verification: `git rm --cached`

4. `carib_clear/.DS_Store`
   - Why: tracked OS metadata
   - Risk: none
   - Verification: `git rm --cached`

---

## Proposed Cleanup — Phase B: Deprecation / Trim References
Trim docs/README so stale module publicity is removed, but keep modules/tests that are still used.

1. Update `README.md` module tree section:
   - Remove `demo.py` leaf line.
   - Remove or condense legacy broker/adapter leaves that are not mentioned elsewhere in README body.
   - Add note: “Legacy demo CLI is no longer listed; active routes remain `/operator`, `/audit/events`, `/compliance/*`.”

2. Update `PRODUCTIZATION_PLAN.md`:
   - Mark Phases 1–6 complete with commit references: `df435b9`, `345ee24`, `bd47338`, `cc04bc6`, `b643718`, `a938189`
   - Add a new minimal `Phase 7: Repo hygiene` checklist that maps to Phases 1–6 terminal cleanup.
   - Define next focus: optional `Phase 8: Operator/K8s hardening` only if requested.

3. Optional软的确定性检查:
   - Confirm whether `carib_clear/iso20022/adapter.py` should be deprecated or removed; hold it for now because it has no references, which makes it a deletion candidate rather than live routing.
   - Confirm whether `demo.py` and `engine/demo_runner.py` are still used by operator data generation at runtime. Preliminary data shows they are imported for `/demo/*` flows; retain unless user requests demo-path removal.

---

## Proposed Verification — Phase C: Focused Green Check
After cleanup, rerun only the focused file set, not full suite:

```bash
PY=/Users/ralphucious/.hermes/hermes-agent/venv/bin/python3
$PY -m pytest -q \
  tests/test_operator_date_range.py \
  tests/test_legacy_compliance_compat.py \
  tests/test_data_layer_durability.py \
  tests/test_compliance_api_hardening.py \
  tests/test_admin_audit.py \
  tests/test_operator_audit.py
```

Acceptance:
- Same pass count as current baseline for the inspected focused modules.
- No new missing-file or import errors during collection.
- Live `/health` still `200` if a manual smoke check is desired.

---

## Execution Sequence
1. Remove stale static assets and tracked `.DS_Store` files.
2. Patch `README.md` module tree.
3. Patch `PRODUCTIZATION_PLAN.md`.
4. Run focused pytest set above.
5. If any focused test fails, stop and report the exact failure rather than rerunning blind.
6. Commit as `chore: repo hygiene — remove unused static assets, update docs/plan`.

## Out of Scope
- No broad test-suite rerun unless a focused failure forces secondary checks.
- No deletion of modules that are imported by production routes or pytest modules.
- No changes to Helm manifests or Render deployment config.

## User Decision Point
Please confirm:
- Approve Phase A+ B+C?
- Keep or remove `carib_clear/iso20022/adapter.py`?
- Keep or remove `demo.py`/`engine/demo_runner.py`?
- Any additional directories to preserve or remove?
