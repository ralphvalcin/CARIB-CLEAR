"""Legacy compliance agent bridge.

This module preserves the historical ``ComplianceAgent`` API while
delegating watchlist/KYC/sanctions logic to ``ComplianceScreeningEngine``.
Production endpoints now flow through ``compliance/screening.py``, so this
module only adapts legacy responses or tests that still import it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from carib_clear.compliance.screening import ComplianceScreeningEngine as _ScreeningEngine
from carib_clear.compliance.screening import _BridgeComplianceProfile, _BridgeComplianceCheckResult


@dataclass
class ComplianceProfile:
    participant_id: str
    jurisdiction: str
    kyc_status: str  # "pending", "verified", "failed", "expired"
    kyc_tier: int  # 1, 2, 3
    kyc_documents: Dict[str, str] = field(default_factory=dict)
    aml_risk_score: float = 0.0  # 0.0-1.0
    sanctions_cleared: bool = True
    pep_status: bool = False
    last_screening: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    restrictions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComplianceCheckResult:
    check_id: str
    participant_id: str
    check_type: str  # "kyc", "aml", "sanctions", "pep", "transaction"
    passed: bool
    score: float
    details: Dict[str, Any]
    requires_review: bool = False
    reviewer_notes: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ComplianceAgent:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.engine = _ScreeningEngine()
        self.engine.initialize()
        self.config = config or {}

    def get_jurisdiction_rules(self, jurisdiction: str) -> Dict[str, Any]:
        return self.engine.get_jurisdiction_rules(jurisdiction)

    def onboard_participant(
        self,
        participant_id: str,
        jurisdiction: str,
        kyc_documents: Dict[str, str],
        beneficial_owners: List[Dict[str, Any]] = None,
        kyc_tier: int = 1,
    ) -> ComplianceCheckResult:
        result = self.engine.onboard_participant(
            participant_id=participant_id,
            jurisdiction=jurisdiction,
            kyc_documents=kyc_documents,
            beneficial_owners=beneficial_owners,
            kyc_tier=kyc_tier,
        )
        profile = self.engine.profiles.get(participant_id)
        return ComplianceCheckResult(
            check_id=result.check_id,
            participant_id=result.participant_id,
            check_type=result.check_type,
            passed=result.passed,
            score=result.score,
            details=result.details,
            requires_review=result.requires_review,
            reviewer_notes=result.reviewer_notes,
            timestamp=result.timestamp,
        )

    def update_kyc(self, participant_id: str, documents: Dict[str, str]) -> ComplianceCheckResult:
        result = self.engine.update_kyc(participant_id, documents)
        profile = self.engine.get_profile(participant_id)
        return ComplianceCheckResult(
            check_id=result.check_id,
            participant_id=result.participant_id,
            check_type=result.check_type,
            passed=result.passed,
            score=result.score,
            details=result.details,
            requires_review=result.requires_review,
            reviewer_notes=result.reviewer_notes,
            timestamp=result.timestamp,
        )

    def screen_transaction(
        self,
        *,
        transaction_id: str,
        from_participant: str,
        to_participant: str,
        amount_usd: float,
        currency: str,
        from_jurisdiction: str,
        to_jurisdiction: str,
        purpose: str = "trade",
    ) -> ComplianceCheckResult:
        from carib_clear.compliance.screening import NON_BLOCKING_ISSUES
        from carib_clear.compliance.screening import _usd_to_local_rate

        from_profile = self.engine.get_profile(from_participant)
        to_profile = self.engine.get_profile(to_participant)
        screen = self.engine.screen_transaction(
            transaction_id=transaction_id,
            from_participant=from_participant,
            to_participant=to_participant,
            amount_usd=amount_usd,
            currency=currency,
            from_jurisdiction=from_jurisdiction,
            to_jurisdiction=to_jurisdiction,
            purpose=purpose,
        )
        issues = list(screen.get("issues", []) or [])

        # 1. Participant onboarding / KYC status checks
        for participant_id, profile, side in [
            (from_participant, from_profile, "from"),
            (to_participant, to_profile, "to"),
        ]:
            if not profile:
                issues.append(f"{side}_participant_not_onboarded")
            elif profile.kyc_status != "verified":
                issues.append(f"{side}_kyc_not_verified")
            else:
                rules = self.engine.get_jurisdiction_rules(profile.jurisdiction)
                tier_limits = rules.get("kyc_tier_limits", {})
                limit = tier_limits.get(profile.kyc_tier, tier_limits.get(max(tier_limits.keys()), 100000))
                if amount_usd > limit:
                    issues.append(f"{side}_kyc_tier_exceeded")

        # 2. AML threshold check
        from_rules = self.engine.get_jurisdiction_rules(from_jurisdiction)
        to_rules = self.engine.get_jurisdiction_rules(to_jurisdiction)
        local_amount = amount_usd * _usd_to_local_rate(currency)
        aml_thresholds = {
            "JM": from_rules.get("aml_threshold_jmd", 1000000),
            "BB": from_rules.get("aml_threshold_bbd", 200000),
            "TT": from_rules.get("aml_threshold_ttd", 500000),
            "HT": from_rules.get("aml_threshold_htg", 500000),
        }
        threshold = aml_thresholds.get(from_jurisdiction, 1000000)
        if local_amount > threshold:
            issues.append("aml_reporting_threshold_exceeded")

        blocked_issues = [i for i in issues if i not in NON_BLOCKING_ISSUES]
        passed = len(blocked_issues) == 0
        requires_review = len(issues) > 0
        score = 1.0 - (len(issues) * 0.15) if issues else 1.0
        result = ComplianceCheckResult(
            check_id=f"txn-{transaction_id}-{int(datetime.now(timezone.utc).timestamp())}",
            participant_id=f"{from_participant}:{to_participant}",
            check_type="transaction",
            passed=passed,
            score=score,
            details={
                "amount_usd": amount_usd,
                "currency": currency,
                "local_amount": local_amount,
                "issues": issues,
                "checks": [],
                "requires_ctr": any("threshold" in i for i in issues),
                "requires_edd": "pep_involved" in issues,
            },
            requires_review=requires_review,
            reviewer_notes=f"{len(issues)} issues found" if issues else "Clean",
        )
        return result

    def run_periodic_sanctions_screening(self) -> List[ComplianceCheckResult]:
        results = self.engine.run_periodic_sanctions_screening()
        return [
            ComplianceCheckResult(
                check_id=r.check_id,
                participant_id=r.participant_id,
                check_type=r.check_type,
                passed=r.passed,
                score=r.score,
                details=r.details,
                requires_review=r.requires_review,
                reviewer_notes=r.reviewer_notes,
                timestamp=r.timestamp,
            )
            for r in results
        ]

    def _screen_sanctions(self, name: str) -> bool:
        return self.engine.screen_sanctions(name)

    def _screen_pep(self, name: str) -> bool:
        return self.engine.screen_pep(name)

    def _detect_anomaly(self, from_participant: str, to_participant: str, amount_usd: float, purpose: str) -> float:
        return self.engine._detect_anomaly(from_participant, to_participant, amount_usd, purpose)

    def _get_usd_to_local_rate(self, currency: str) -> float:
        from carib_clear.compliance.screening import _usd_to_local_rate
        return _usd_to_local_rate(currency)
