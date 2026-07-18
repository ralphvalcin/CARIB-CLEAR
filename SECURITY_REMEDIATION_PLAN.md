# Security Remediation Plan

## Goal
Raise CARIB-CLEAR from `44/100` Poor to `80+` Good by fixing the audit findings. Execute in order so each step builds on the last.

---

## Phase 1 — Secrets & Leakage (Critical)
**Target**: Remove exposed credentials and prevent future leakage.

1. **Rotate/revoke exposed AWS-style key**: Treat `AKIACTAW0FiAL0FKAugD` as compromised; deactivate it immediately.
2. **Strip checked-in secret from history**: Purge the dashboard bundle file from git history after confirming it contains only that bundled data.
3. **Add `.env` entries to `.gitignore`**: Insert `.env`, `.env.*`, `.env.local`, `.env.production`.
4. **Un-track stray `.env*` files**: Use `git rm --cached` on anything tracked that should be ignored.

**Acceptance**: `git ls-files '*.env*'` returns nothing sensitive; `grep -R` for the key returns no repo matches.

---

## Phase 2 — API Security & Access Control (Critical)
**Target**: Every state-changing endpoint requires authentication.

1. **Audit endpoints needing auth**: Cross-reference `carib_clear/api.py`, `carib_clear/sep31/__init__.py`, and `carib_clear/iso20022/api.py`.
2. **Add auth to missing endpoints**: Loan, compliance, market, settlement, webhook management, and sensitive reads.
3. **Enforce auth-origin in production**: Ensure `require_api_key` is the default behavior when `CARIB_CLEAR_API_KEY` exists.

**Acceptance**: No route mutating data is reachable without `X-API-Key` when the env var is set.

---

## Phase 3 — Injection Resistance (Critical)
**Target**: Remove raw SQL interpolation and harden query paths.

1. **Restrict `table` and `where` args in `carib_clear/db.py`**: Replace f-string `DELETE FROM {table} WHERE {where}` with an allow-list + parameterized queries.
2. **Do the same for `trading-system/dashboard/app.py` and `trading-system/scripts/health_check.py`**: Replace f-string SQL.
3. **Add helper for allowed tables**: Map whitelisted table names to query methods.

**Acceptance**: No `execute(f"...{table}...")` or `cursor.execute(... + ...)` remains.

---

## Phase 4 — CORS Hardening (High)
**Target**: Stop wildcard + credentials combo.

1. **Default to empty allowlist**: If `CARIB_CLEAR_ALLOWED_ORIGINS` is missing, use `[]` instead of `["*"]`.
2. **Drop `allow_credentials=True` unless whitelist is set**: Tie credentials flag to validated env presence.
3. **Add startup log showing active origins**: Helps operators verify config without reading code.

**Acceptance**: Missing env var => browser CORS preflight rejects unknown origins.

---

## Phase 5 — Rate Limiting Resilience (Medium)
**Target**: Prevent easy IP bypass.

1. **Trust `X-Forwarded-For` only behind known proxy config**: Read a new env var like `CARIB_CLEAR_TRUSTED_PROXY=1` before using headers.
2. **Log 429 events**: Add minimal log line on rate-limit rejection.
3. **Add `/health` and `/metrics` to skip list**: Already mostly there, verify.

**Acceptance**: Rate limiter uses proxy header only when explicitly enabled.

---

## Phase 6 — Webhook & Response Hygiene (Medium)
**Target**: Leak less sensitive state.

1. **Do not return webhook secret on list/register**: Return it only once on creation, or require owner-only retrieval.
2. **Verify existing webhook signature checks on inbound delivery**: Confirm `verifyWebhookSignature` logic exists for received payloads.

**Acceptance**: Listing webhooks no longer exposes `secret`.

---

## Phase 7 — Legacy Crypto & Debug Noise (Low)
**Target**: Future-proof and reduce debug leakage.

1. **Replace `hashlib.md5` in non-core scripts**: Move `kreyol-ai/scripts/...` to SHA-256 or UUID-based checksums.
2. **Redact token prints in `jarvis/jarvis/voice/engine.py` and `jarvis/jarvis/notifications/telegram_bot.py`**: Remove or guard sensitive prints; add logger.sensitive fallback.

**Acceptance**: No `eval(` and no `console.log(token...)` in repo.

---

## Execution Order
```
Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 -> Phase 6 -> Phase 7
```

Each phase is independent enough to verify before moving on. I will:
- run targeted tests/pytest after each phase,
- update `SECURITY_AUDIT.md` with the new score when complete.
