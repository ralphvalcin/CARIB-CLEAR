# CARIB-CLEAR Architecture Review — Production Readiness Assessment

**Evaluated target**: Kubernetes + PostgreSQL deployment  
**Reviewed docs**: `REVIEW_BRIEF.md`, `SECURITY_REMEDIATION_PLAN.md`, `PRODUCTIZATION_PLAN.md`  
**Verified with**: local pytest run (`32 passed`) + static review of API/auth/DB/webhooks/SEP-31/ISO20022/plugin/settlement/compliance/K8s/container files

---

## Production Readiness Score

**Score: 46/100 — Demo-adjacent; major architectural upgrades required before prod service**

Rating scale:
- **0–49**: Not production-ready; risky to run customer-facing or financial flows
- **50–69**: Prototype; partially usable with significant guardrails
- **70–89**: Production-capable with known mitigation work
- **90–100**: Production-grade, resilient, and auditable

Breakdown by dimension:
| Dimension | Score | Summary |
|---|---|---|
| Separation of concerns | 6/10 | Good layer boundaries, but demo + production shares single FastAPI app/module; heavy in-process coupling |
| Security posture | 5/10 | Mixed: api-key auth and CORS improves, but legacy exposure remains; secrets leak risk still active |
| Testability | 7/10 | Pytest suite present and passing; insertion of `reset_db` allows tests. Still thin on component-level contracts + integration tests. |
| State management | 4/10 | SQLite-local default, global singleton state (`_loan_history`, `_db`, `_recorded`), process-scoped `WebhookRegistry`
 singleton — not horizontally safe on Kubernetes yet |
| Database + migrations | 6/10 | SQL-first schema with “keeps both modes”; no Delphi-style alembic; environment-driven but not migration tooling-hardened |
| Kubernetes fit | 5/10 | YAML exists but relies on `/readyz`/`/livez`, no prod image hardening/tags/storageClass/backup/sidecar plan |
| Financial correctness / audit | 6/10 | Schema + events + transitions help; missing immutable ledger, atomicity-shards, compensation, non-local tx guarantees |
| Operational readiness | 4/10 | Basic metrics + readiness endpoints, but no PITR/backup, no DLQ worker, CPU-bound mock adapters, in-memory bottleneck candidates |

---

## Scope of Review

I reviewed:
- `carib_clear/api.py`, `auth.py`, `api_hardening.py`, `db.py`, `errors.py`, `settlement.py`, `sep31/__init__.py`, `iso20022/api.py`, `webhooks/__init__.py`, `plugin/registry.py`
- domain modules: `compliance.py`, `broker/base.py`, `engine/demo_runner.py`
- persistence/migrations: `db.py`, `migrations/apply.py`, `V1..V4`
- deployment/container: `Dockerfile`, `docker-compose.yml`, `k8s/api-deployment.yaml`
- tests: `tests/test_api.py`, `test_settlement_idempotency.py`, `test_session_e2e_wiring.py`, `test_phase5_settlement_api.py`, `test_data_layer.py`, `tests/test_compliance.py`

Operational constraint: **read-only review** — no files modified, no secrets touched. Created `ARCHITECTURE_REVIEW.md` if requested elsewhere.

---

## Severity Grouped Findings

### Critical
- secrets-leakage-standalone-html
  - Security audit still cites `carib_clear/static/CARIB-CLEAR Dashboard (standalone).html` containing `AKIACTAW0FiAL0FKAugD`. Current repo search only lands on docs/remediation plan, suggesting the source file/path lineage and/or embedded references remain present. On Kubernetes with any volume mounts or presence containers scanning, this remains high-risk.
  - Recommendation: quarantine/remove standalone bundle, add path metadata checksum to CI, rotate/hash any real key.
- auth-default-deny-not-forced
  - Authentication is opt-in via env var and disabled by default, but not enforced at platform level. Even with `CARIB_CLEAR_API_KEY`, several informational routes are still public (`/metrics`, `/livez`, `/readyz`, `/docs`, `/openapi.json`).
- global-singleton-state-not-k8s-safe
  - App module globals: `_loan_history`, `_demo_cache`, `_start_time`, plus module globals inside database/webhook/SEP-31 systems are not pod-safe under multiple workers/replicas. Current K8s manifest requests 2 replicas without sticky session state; in-memory caches are unreachable cross-pod.
- missing-backed-by-db transparency
  - Loan/application state exists in DB lineage but default system path shows SQLite-first descent with local file paths. For Kubernetes, volume mounts and shared storage caveats apply. There is no automated failover strategy.

### High
- db-abstraction-leakage-through-raw-helpers
  - `db.delete/count/execute/query/query_one` expose raw SQL composition plus table-name allowlist only; Postgres != sqlite path uses `psycopg.connect` directly but doctests/migrations assume SQLite idioms. Stress/exotic UTF-8 under SQLite is unverified.
- no-transaction-boundaries-at-application-level
  - Financial writes between `loan/apply` and `settlements` are best-effort individually committed. No DB-level transaction wrappers for multi-step financial actions; if a later step fails, earlier data remains in DB, posing partial-state risk.
- webhook-delivery-in-process-blocking
  - `WebhookDispatcher._deliver` is synchronous within API request path and can block worker threads while retrying with 2**n backoff. Kubernetes Horizontal Pod Autoscaler sees inflated request latency. Recommendation: event bus/queue + worker Deployment.
- cross-module-active-mocking-in-production
  - `/liquidity/state`, `/market/state`, `/demo/trade_finance`, and adapters in `/rails/status` inject mock providers/flows inside real endpoints. Under K8s, “prod mode” is undefined.
- pod-liveness/readiness-accuracy
  - `/readyz` references `get_db()._conn.execute("SELECT 1")` which is private, causing direct DB coupling and not sufficient for multiple-dependency readiness.
- postgres-migrations-not-postgres-aware
  - `SCHEMA_SQL` has `IF NOT EXISTS` and order-resilient DDL, but foreign keys + indexes wording are SQLite-friendly. Missing explicit `USING` for sequences, enum types, and JSON schema patterns for Postgres.

### Medium
- rate-limiter-memory-state
  - `RateLimiter` uses in-process dict without distributed backend; Kubernetes replica method invalidates cross-pod rate limit behavior.
- compliance-mock-screening
  - Sanctions/PEP/anomaly engines are string-keyword heuristics. Required for roadmap/high-level readiness but not audit-ready: integrate real provider adapters.
- psycopg-import-path-undetected
  - DB `_connection_from_url` imports psycopg lazily. If package is missing, runtime error only happens on actual request.
- k8s-manifest-missing-storage-and-backup
  - No `PersistentVolumeClaim`, no Postgres sidecar/external DB instance configuration, no backup job, no secret management for API keys beyond `secretKeyRef`.

### Low
- dockerfile-cache-busting
  - Source copy occurs after dependency install; source changes invalidate cache. Minor and acceptable for demos.
- no-ready-jsonlogger
  - Structured logging exists as module names but format is not uniform JSON; not critical but makes log aggregation in K8s noisier.

---

## Architecture Evaluation

### Separation of Concerns
- **Layers exist cleanly**: API → agents → broker → DB. Broker ABC + router, compliance agent, settlement lifecycle, webhook registry, plugin system.
- **Issues**: `api.py` reaches into domain modules directly; demo execution, test scaffolding, and production wiring share the same module and globals. The SEP-31/ISO20022 routers are mounted in-process instead of as separate services/workers.

### API Design
- Strong points:
  - Pydantic request/response models, typed error envelope: good API contract.
  - Identity-aware scoping appears on loans/settlements.
- Weak points:
  - Public demo endpoints alongside sensitive endpoints; no versioning scheme.
  - Info endpoints emit in-memory state not normalized through API schema.
  - Response body includes raw_response for settlements among other serialization oddities.

### State Management
- Duplicated state: SQLite file + in-memory process dict + global singletons.
- Safe in single-process demo, but redundant on K8s with multiple replicas. Cross-request consistency relies on thread-local connections, not pod-safe.

### Migration Strategy
- Existing text-based migration runner is good for schema-first bootstrapping.
- Issue: no formal version tracking on Postgres, no idempotency checks, no status table; no roll-forward/rollback definitions.

### Production Fit (Kubernetes + Postgres)
Target discussion:
- **Network**: API should be fronted by ingress/edge WAF; currently no TLS/automatic cert management artifacts.
- **Storage**: No PVC or managed DB guidance; append-only financial requirements demand WAL + PITR.
- **Observability**: `/metrics` is hand-rolled; not OpenTelemetry; missing distributed traces.
- **Workers**: Synchronous webhook retries block CPU and fail on pod restart.
- **Secrets**: No Vault/SealedSecrets workflow; `.env.example`> guidance is minimal.

---

## Prioritized Action List

### P0 — Blocking; before any customer/settlement traffic
1. **Rotate and purge the leaked key/standalone bundle.**
2. **Enforce auth as the platform default.**
   - Add platform control: if env var missing or empty, **reject** all state-changing requests, not disable auth.
   - Avoids drift where a missing env silently grants anonymous access.
3. **Eliminate module-global state in favor of request-scoped abstractions or external cache.**
   - Relocate `_loan_history`, `_demo_cache`, webhook registry, settlement caches to Postgres or Redis.
4. **Implement transactional boundaries for financial writes.**
   - Wrap loan+ledger, settlement+events in single DB transactions.
5. **Add automatic DB migrations with version table and production-tested DDL.**
   - Migrate `SCHEMA_SQL` + `V*__*.sql` to managed migrations with up/down hooks.

### P1 — Hardening before production launch
6. **Offload webhook dispatch to a worker queue with DLQ and persistent job state.**
7. **Segregate demo/production endpoints.**
   - `/demo/*` should be gated behind feature flag or removed from `main`-style behavior.
   - Replace `generate_mock_*` calls with real data sources or conditional `mock_mode` config.
8. **Add backup/restore and PITR for Postgres.**
9. **Formalize secrets management workflow.**
   - `CARIB_CLEAR_API_KEY` rotation, ledger/audit log for issued keys, webhook secrets retrieval.
10. **Harden `/readyz` to validate DB, cache, queue, rail, and schema/version health.**

### P2 — Near-term reliability and scale
11. **Distributed rate limiting and tracing.**
12. **Replace in-process auth/routing cache with Redis Hash/consistent cache.**
13. **Introduce real sanctions/PEP/adapter providers.**
14. **CI/CD pipeline:**
    - Reproducible prod builds with image digests.
    - SAST/secret scan, pytest gate per PR.
    - Admission policy for K8s secrets.
15. **Policy-engineize compliance rules:**
   - Exportable policy/tests for `JURISDICTION_RULES` and enumeration coverage as reviewed in `tests/test_compliance.py`.

---

## Scoring Summary Rationale
Scores are depressed primarily by still-present credential-exposure artifact paths, process-local coupled state, in-process webhook dispatch, auth opt-out default, mock-through-production routing, and missing Kubernetes-level persistence/secret/observability scaffolds. The codebase has advanced structural pieces (typed models, event ledger, broker ABC, plugin registry), but deployment semantics do not match Kubernetes-managed Postgres production target yet.
