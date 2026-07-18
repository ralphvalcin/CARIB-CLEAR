# AML/PEP + Worker + Ledger Review Brief

## Scope
Review the latest CARIB-CLEAR productization work:
- AML/PEP screening engine + configurable watchlists + cache
- Settlement worker with compliance gating
- Ledger/audit trail wiring in API + DB schema
- Existing K8s/Helm packaging

## Review Goals
1. Verify all new modules are wired into real flows (not just added)
2. Check data flow integrity: screening → worker/API → audit trail
3. Ensure no demo-only shortcuts remain in production paths
4. Validate test coverage reflects actual behavior
5. Flag any architectural drift from previous phases

## Non-Negotiables
- Default-deny security posture
- No raw SQL string interpolation
- KYC gate must remain enforced on settlements
- Audit trail must be append-only with no delete path
- Worker screening must hard-block sanctions matches

## Artifacts to Review
- carib_clear/compliance/{screening.py,providers.py,cache.py}
- carib_clear/config/compliance_lists.json
- carib_clear/worker/settlement_worker.py
- carib_clear/audit.py
- carib_clear/db.py schema additions
- carib_clear/api.py audit hooks
- tests/test_compliance_screening.py
- tests/test_settlement_worker.py
- tests/test_audit.py
- helm/carib-clear/ Chart + templates

## Deliverables
- Top issues by severity (P0/P1/P2)
- Confirmation of correct wiring or required patches
- Updated plan for remaining productization phases
