# CARIB-CLEAR Review Findings
Date: 2026-07-17
Scope: wiring/correctness, security non-negotiables, end-to-end route/db/agent auth.

## Summary
- Tests: 258 passed, 1 skipped.
- CORS current behavior: deny-all when `CARIB_CLEAR_ALLOWED_ORIGINS` is unset; credentials only when origin list is non-empty.
- Auth coverage: all state-changing `carib_clear` API routes declare `require_api_key`; auth falls back to disabled only when no env key is set and logs one-time warning.
- Secrets scan in `carib_clear/dashboard` area: no live secret values found in checked code paths.
- Critical open gap: multiple SQL paths still build queries with f-string interpolation for table/where/order/set clauses, which bypasses parameterization and depends on manual allow-listing.

## Critical / High Findings

1) SQL dynamic-string paths still use f-string interpolation instead of fully parameterized queries
- Files/lines:
  - `carib_clear/db.py:269` — `ALTER TABLE {table} ADD COLUMN ...`
  - `carib_clear/db.py:286` — `INSERT OR REPLACE INTO {table} ({cols}) ...`
  - `carib_clear/db.py:349` — `DELETE FROM {table} WHERE {where}`
  - `carib_clear/db.py:355` — `SELECT COUNT(*) ... FROM {table} WHERE {where}`
  - `carib_clear/db.py:468` — `SELECT * FROM settlements WHERE {where}`
  - `carib_clear/db.py:487` — `UPDATE settlements SET {', '.join(sets)} WHERE ...`
  - `carib_clear/db.py:502/555/580/610/621` — similar SELECT/UPDATE/query builders using `f"..."` with joined clauses
  - `carib_clear/api.py:700-723` — `loan_applications` listing joins user-derived `where`
- Why critical: table/where fragments are trusted by convention rather than enforced by the driver; a future allow-list miss or accidental caller-influenced column/where string can introduce injection.
- Fix: remove SQL string interpolation completely. Use explicit helper methods or a tiny query builder that only emits parameterized SQL with `?` placeholders and an explicit table allow-list mapping to supported columns.

2) Settlement `/settlements` list filters by `business_key` instead of `participant_id`
- Files/lines:
  - `carib_clear/api.py:818-824`
  - `carib_clear/settlement.py:178-183`
- Why high: `business_key` is not the authenticated identity. `submit_settlement` stores identity in `participant_id`, but `list_settlements` ignores it and scopes by `business_key`, so identity-scoped visibility is incorrect.
- Fix: in `list_settlements`, use `participant_id` from `identity.participant_id` to scope: `WHERE participant_id = ?` instead of `business_key`; keep `business_key` only as an optional extra filter.

3) `/settlements/{id}` returns `raw_response` when present in DB after event loads
- Files/lines:
  - `carib_clear/db.py:459-460, 469-470, 504, 519-520, 542-543, 556-558, 579-583`
  - `carib_clear/api.py:831-836`
- Why high: JSON blob fields like `raw_response`, `payload`, `details` are deserialized and returned to API consumers. If backend adapters later inject sensitive adapter state, those fields become information-leak vectors.
- Fix: default-strip sensitive blobs from read paths; return only schema-approved summaries unless an explicit admin audit endpoint requests full payloads.

4) Dashboard trading-system routes expose raw Telegram token logging and unauthenticated mutation endpoints
- Files/lines:
  - `trading-system/dashboard/app.py:632-647` — builds Telegram send using `TELEGRAM_BOT_TOKEN`; warning path logs `exc` only, which is okay, but absence of token value logging is only by accident.
  - `trading-system/dashboard/app.py:397-421, 650-679` — `PATCH /api/adaptation/*` and `POST /api/settings` accept mutation; only `settings` enforces `_require_settings_auth`.
  - `trading-system/dashboard/app.py:512-554` — `PATCH /api/schedules/*` toggles task status/cron without auth.
- Why high: unauthenticated mutation of strategy adaptation, system settings, and scheduled jobs is a direct operational risk; token/env usage should never be trusted by convention.
- Fix: require `_require_settings_auth` on every mutation endpoint; remove any debugging that might print secrets; validate all cron/status values server-side.

## Medium Findings

5) CORS allow-credentials coupling is acceptable today, but should be explicitly reject-all when no whitelist is set
- Current: `carib_clear/api.py:41-46` — `allow_credentials=bool(origin_list)`; missing origins currently returns `[]`, so deny-all holds.
- Gap: default behavior is implicit; a future env misread could flip to wildcard.
- Fix: add an explicit guard: if `CARIB_CLEAR_ALLOWED_ORIGINS` is missing, set `allow_origins=[]`, `allow_credentials=False`, `allow_methods=[]`, and log restricted mode once at startup.

6) Raw SQL usage in trading-system dashboard and health scripts mirrors repo-level risk
- Files/lines:
  - `trading-system/dashboard/app.py:109-161, 253-269, 559-578` — mostly static parameterized queries, but `app.py:297` embeds raw `{where}` in a query string.
  - `trading-system/scripts/health_check.py` referenced in SECURITY_REMEDIATION_PLAN.md: likely f-string SQL path as well.
- Fix: audit `trading-system/scripts/*` for any f-string SQL and convert to parameterized SQL with allow-listed tables.

7) AWS-style key remains referenced in docs and markdown presence must be purged from git history
- Files/lines:
  - `SECURITY_AUDIT.md:28`
  - `SECURITY_REMEDIATION_PLAN.md:11`
- Note: code paths checked do not contain the literal key string outside those plan/docs references; still, markdown mentions must be scrubbed and history rewritten if the key ever lived in tracked content.
- Fix: purge bundle/file with the key from git history, add clean rewrite commit, and remove references from plan/audit markdown after rotation/revocation.

8) Mixed auth modes enable bypass during local/demo runs
- Files/lines:
  - `carib_clear/auth.py:50-72` — when `CARIB_CLEAR_API_KEY` is unset, auth returns disabled identity.
- Why medium: acceptable for local demo, but dangerous in any environment resembling production accidentally.
- Fix: gate demo mode on explicit `CARIB_CLEAR_ENV=local|demo`; refuse startup if env says prod and API key is missing.

## Low Findings

9) Demo endpoints not protected by auth even when key is configured
- Files/lines:
  - `carib_clear/api.py:323-421` — `/demo/*` routes have no `require_api_key` dependency.
- Why low: they are compute-heavy and expose business logic/performance characteristics.
- Fix: add `Depends(require_api_key)` or a demo-only token requirement.

10) MD5/eval presence is outside core `carib_clear`
- Files: `kreyol-ai/scripts/kreyolbench-v1.py`, `kreyol-ai/scripts/kreyol-chat.py`, `trading-system/ml/lstm_inference.py`, `trading-system/ml/training/lstm_trainer.py`
- Why low: these are model training/eval loops, not security/hashing usage, but the scan pattern matches.
- Fix: rename variables/methods to avoid `eval` false positives, or add allowlist documentation; ensure no shell/command eval flows exist near model inference code.

11) Legacy print/debug noise in agents
- Files/lines:
  - `carib_clear/governance/approval.py:399-410`
  - `carib_clear/agents/cash_flow_lending.py:730-755`
  - `carib_clear/demo.py:56-345`
- Fix: replace with structured logger calls; ensure no secrets or PII are included.

## Prioritized Fixes
1. Parameterize all SQL in `carib_clear/db.py` and remove f-string table/where clauses.
2. Correct settlement list scoping to `participant_id`.
3. Harden dashboard mutation endpoints with auth, especially `/api/adaptation/*` and `/api/schedules/*`.
4. Make CORS deny-all explicit when no whitelist env is present.
5. Strip blob fields from read responses unless explicitly requested for audit.

## Concrete Patch Recommendations

- `carib_clear/db.py`: Replace `insert/query/execute/delete/count` dynamic parts with methods that map allow-listed tables, columns, and operators to static parameterized SQL templates. Example: a `SUPPORTED_TABLES` dict with canonical column lists, and a small `where_clause(conditions)` builder that outputs `(? placeholders)` plus params.
- `carib_clear/api.py` settlement list: change `list_settlements` to use `participant_id` where filter rather than `business_key`.
- `trading-system/dashboard/app.py`: add `Depends(_require_settings_auth)` to `/api/adaptation/*` and `/api/schedules/*`; consider moving dashboard into an `APIRouter` with `dependencies=[Depends(_require_settings_auth)]` for all write paths.
- `carib_clear/api.py` CORS block: change startup default to explicit deny-all mode with log line; only enable credentials when origin whitelist is present.

## Readiness Assessment
- Functional tests: passing.
- End-to-end route/db/agent wiring: structurally present for core flows (loan, settlement, webhooks, compliance), with noted scoping bug in settlement listing.
- Security hardening: auth and rate limiting are present; CORS is functionally safe but should be more explicit; SQL allow-list intent exists but implementation still relies on f-string assembly and requires full parameterization.
- Production blocks: SQL parameterization, identity-scoped listing, dashboard mutation auth, explicit CORS deny-by-default, blob sanitization.
