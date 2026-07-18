# CARIB-CLEAR Code & Architecture Review Brief

## Context
- Repo: `/Users/ralphucious/CARIB-CLEAR`
- Goal: Production-grade deployment, not buildathon demo.
- Plan files: `SECURITY_REMEDIATION_PLAN.md`, `PRODUCTIZATION_PLAN.md`

## Review Angles
1. **Codebase wiring & correctness** — verify routes/DB/agents are wired end-to-end, no stale/demo-only paths causing runtime failures.
2. **Security posture** — confirm auth is enforced, CORS defaults deny-all, rate limiting active, no leaked secrets, SQL allow-list intact, no md5/eval/insecure hashing.
3. **Architecture review** — evaluate separation of concerns, testability, statefulness, migration strategy, and readiness for Kubernetes/postgres production target.

## Non-Negotiables
- Default-deny CORS and proxy trust.
- All financial writes participant-scoped and auditable.
- No `.env` files tracked; `.env.example` is safe template only.
- Tests must be runnable with: `/Users/ralphucious/.hermes/hermes-agent/venv/bin/python3 -m pytest -q`.

## Deliverables
- Findings grouped by severity (critical / high / medium / low).
- Concrete patch recommendations or skipped findings with rationale.
- Updated `ARCHITECTURE_REVIEW.md` with production readiness score + priority action list.

## Constraints
- Do not modify repo files during review — only report findings.
- Prefer existing patterns in repo; avoid recommending unrelated frameworks.
