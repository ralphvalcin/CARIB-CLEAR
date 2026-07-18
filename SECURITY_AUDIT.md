# Security Audit Report

## Detected Tech Stack
- **Project type**: Python/FastAPI monorepo
- **Framework**: FastAPI + Uvicorn (`pyproject.toml:14-17`)
- **Database**: SQLite via custom connection helper in `carib_clear/db.py`
- **Auth**: Custom lightweight API-key dependency in `carib_clear/auth.py`
- **Deployment**: Dockerfile present (`Dockerfile`)
- **Other**: HTML dashboard static bundle in `carib_clear/static/`

## Summary
This is a buildathon/demo financial-infrastructure repo with API-key auth and rate limiting, but several security assumptions are still demo-level. I found a hardcoded AWS-style key embedded in a checked-in dashboard bundle, broad CORS with cookie support, broad API key auth exposure, raw SQL with f-string tables/where clauses, MD5 usage outside `carib_clear`, multiple `eval(...)` usages, mixed read-only auth coverage, and `.gitignore` missing `.env` wildcards.

**Project Score**: 44/100 — Poor — significant risk
**Checks Run**: 30/30
**Issues Found**: 12

## Quick Wins (fixable in under 10 minutes)
| # | Issue | Severity | Fix Time | Fix |
|---|-------|----------|----------|-----|
| 1 | `.env*` entries not ignored | 8/10 | 1 min | Add `.env`, `.env.*`, `.env.local`, `.env.production` to `.gitignore` |
| 2 | Non-API endpoints missing auth | 9/10 | 2 min | Add `dependencies=[Depends(require_api_key)]` to write/state-changing routes and sensitive GETs |
| 3 | CORS `allow_credentials=True` with wildcard origins | 8/10 | 2 min | Default to `[]` when env var is missing; drop `allow_credentials=True` unless an explicit whitelist is set |

## Critical Issues (Severity 8-10)
- **1. Secrets Exposure — hardcoded AWS-style key in repo** (Severity: 10/10)
  - File: `carib_clear/static/CARIB-CLEAR Dashboard (standalone).html:290`
  - Pattern matched: `AKIACTAW0FiAL0FKAugD`
  - Fix: Treat this key as compromised, rotate/revoke it immediately, then remove the bundled file from source control.

- **2. Custom Auth — broad API key is required but not consistently used** (Severity: 9/10)
  - File: `carib_clear/api.py:93`, `carib_clear/api.py:219`, `carib_clear/api.py:247`, `carib_clear/api.py:287`, `carib_clear/api.py:323`, `carib_clear/api.py:355`, `carib_clear/api.py:417`, `carib_clear/api.py:441`, `carib_clear/api.py:453`, `carib_clear/api.py:477`, `carib_clear/api.py:493`, `carib_clear/api.py:541`, `carib_clear/api.py:647`, `carib_clear/api.py:653`, `carib_clear/api.py:662`, `carib_clear/api.py:687`, `carib_clear/api.py:696`, `carib_clear/api.py:718`, `pxarib_clear/api.py:742`, `carib_clear/api.py:765`, `carib_clear/api.py:816`, `carib_clear/api.py:855`, `carib_clear/api.py:886`
  - Fix: Apply `require_api_key` to all non-public endpoints, especially loan, compliance, market, settlement, and webhook-sensitive endpoints.

- **3. Injection / Unsanitized Input — raw SQL with interpolated table/where** (Severity: 10/10)
  - File: `carib_clear/db.py:156`, `carib_clear/db.py:158`, `trading-system/dashboard/app.py:295`, `trading-system/scripts/health_check.py:102`
  - Pattern matched: `execute(f"DELETE FROM {table} WHERE {where}"...)`
  - Fix: Replace free-form `table`/`where` interpolation with an allow-list or query builder; never pass unsanitized strings into SQL.

- **4. Gitignore Coverage — missing `.env` coverage** (Severity: 8/10)
  - File: `.gitignore:1-41`
  - Pattern: missing `.env`, `.env.*`, `.env.local`, `.env.production`
  - Fix: Add those entries at the top of `.gitignore`.

- **5. CORS Misconfiguration — wildcard origins + credentials** (Severity: 8/10)
  - File: `carib_clear/api.py:37-46`
  - Pattern matched: `origin_list = [...] else ["*"]` with `allow_credentials=True`
  - Fix: Default to an empty allowlist and require explicit origin whitelisting via env.

## High Priority (Severity 6-7)
- **6. Outdated/Fragile Dependencies — MD5 in non-core scripts** (Severity: 7/10)
  - Files: `kreyol-ai/scripts/corpus-quality-check.py:131`, `kreyol-ai/scripts/kreyol-corpus-pipeline.py:108`
  - Pattern matched: `hashlib.md5`
  - Fix: Replace with SHA-256 or content-addressed identifiers, or quarantine these scripts from production paths.

- **7. Debug Statements — token/password output possible** (Severity: 6/10)
  - Files: `jarvis/jarvis/notifications/telegram_bot.py:240`, `jarvis/jarvis/voice/engine.py:69`
  - Pattern matched: `print(token...)`
  - Fix: Replace with structured logging with redaction, and ensure token env vars never leave process memory into logs/outbound channels.

## Medium Priority (Severity 4-5)
- **8. Rate Limiting — client IP trust bypasses** (Severity: 5/10)
  - File: `carib_clear/api_hardening.py:49-61`
  - Pattern matched: `client_ip = request.client.host...`
  - Fix: Honor `X-Forwarded-For` only when behind a known proxy/LoadBalancer config; otherwise `request.client.host` can be spoofed.

- **9. Webhook Response Exposure — webhook secret returned on registration** (Severity: 6/10)
  - File: `carib_clear/api.py:393-414`
  - Pattern matched: response model returns `secret=wh.secret`
  - Fix: Return the secret only on creation if absolutely required, otherwise require a separate retrieval endpoint protected by owner auth.

## Low Priority (Severity 1-3)
- **10. Informational — Python 3.14 warning from system pip install paths** (Severity: 1/10)
  - File: `pyproject.toml`
  - Note: Builds/runtime should use the dedicated Hermes venv noted for this repo rather than system Python paths during audit/dev.

## Not Applicable
- **Ghost Packages**: No suspicious/unregistered packages detected in `pyproject.toml` on PyPI.
- **Storage Bucket Permissions**: No cloud storage SDKs detected.
- **Password Reset / GDPR Deletion**: No user-account system detected yet.
- **Backup Strategy**: Appears to use SQLite file; DB backup not audited as infrastructure-owned.
- **DDoS/CDN WAF**: Deployment settings not enforced in repo; relies on upstream host/proxy.
