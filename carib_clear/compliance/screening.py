"""AML/PEP screening engine — provider-based, config-backed, cacheable."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from carib_clear.compliance.providers import (
    BaseProvider,
    CachedProviderMixin,
    ComplianceProviderRegistry,
    ProviderResult,
)
from carib_clear.config import load_compliance_lists
from carib_clear.compliance.cache import ScreeningCache
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List

logger = logging.getLogger(__name__)


# Shared deterministic fallbacks for legacy compliance agent bridging.
SANCTIONS_KEYWORDS: List[str] = [
    "specially designated national",
    "blocked person",
    "terrorist",
    "narcotics trafficking",
]
PEP_KEYWORDS: List[str] = [
    "minister",
    "president",
    "governor",
    "senator",
    "deputy",
]
USD_TO_LOCAL_RATES: Dict[str, float] = {
    "JMD": 154,
    "BBD": 2,
    "TTD": 6.8,
    "XCD": 2.7,
    "HTG": 130,
    "USD": 1.0,
}


def _sanctions_keywords() -> List[str]:
    return list(SANCTIONS_KEYWORDS)


def _pep_keywords() -> List[str]:
    return list(PEP_KEYWORDS)


def _usd_to_local_rate(currency: str) -> float:
    currency = (currency or "USD").upper()
    return float(USD_TO_LOCAL_RATES.get(currency, 1.0))

# Legacy jurisdiction rules are kept in the agent module, but importing
# there can be expensive during tests. Copy the rules locally here so the
# screening engine can support legacy-bridged endpoints without depending
# on the demo/legacy agent module.
JURISDICTION_RULES: Dict[str, Dict[str, Any]] = {
    "JM": {
        "regulator": "Bank of Jamaica",
        "kyc_required": ["tax_compliance_certificate", "national_id", "proof_of_address", "trn"],
        "kyc_tier_limits": {1: 50000, 2: 250000, 3: 1000000},
        "aml_threshold_jmd": 1000000,
        "reporting_currency": "JMD",
        "sanctions_lists": ["OFAC", "UN", "BOJ"],
        "pep_required": True,
        "beneficial_ownership_threshold": 0.10,
    },
    "BB": {
        "regulator": "Central Bank of Barbados",
        "kyc_required": ["tax_clearance_certificate", "national_id", "proof_of_address"],
        "kyc_tier_limits": {1: 100000, 2: 500000, 3: 2000000},
        "aml_threshold_bbd": 200000,
        "reporting_currency": "BBD",
        "sanctions_lists": ["OFAC", "UN", "CBB"],
        "pep_required": True,
        "beneficial_ownership_threshold": 0.10,
    },
    "TT": {
        "regulator": "Central Bank of Trinidad and Tobago",
        "kyc_required": ["national_id", "proof_of_address", "bir_clearance_certificate"],
        "kyc_tier_limits": {1: 50000, 2: 250000, 3: 1000000},
        "aml_threshold_ttd": 500000,
        "reporting_currency": "TTD",
        "sanctions_lists": ["OFAC", "UN", "CBTT"],
        "pep_required": True,
        "beneficial_ownership_threshold": 0.10,
    },
    "HT": {
        "regulator": "Banque de la République d'Haïti",
        "kyc_required": ["national_id", "proof_of_address", "nif_certificate"],
        "kyc_tier_limits": {1: 10000, 2: 50000, 3: 250000},
        "aml_threshold_htg": 500000,
        "reporting_currency": "HTG",
        "sanctions_lists": ["OFAC", "UN", "BRH"],
        "pep_required": True,
        "beneficial_ownership_threshold": 0.25,
    },
    "ECCB": {
        "regulator": "Eastern Caribbean Central Bank",
        "kyc_required": ["national_id", "proof_of_address", "tax_compliance_certificate"],
        "kyc_tier_limits": {1: 50000, 2: 250000, 3: 1000000},
        "aml_threshold_xcd": 270000,
        "reporting_currency": "XCD",
        "sanctions_lists": ["OFAC", "UN", "ECCB"],
        "pep_required": True,
        "beneficial_ownership_threshold": 0.10,
    },
}


@dataclass
class _BridgeComplianceProfile:
    participant_id: str
    jurisdiction: str
    kyc_status: str
    kyc_tier: int
    kyc_documents: Dict[str, str] = field(default_factory=dict)
    aml_risk_score: float = 0.0
    sanctions_cleared: bool = True
    pep_status: bool = False
    last_screening: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    restrictions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _BridgeComplianceCheckResult:
    check_id: str
    participant_id: str
    check_type: str
    passed: bool
    score: float
    details: Dict[str, Any]
    requires_review: bool = False
    reviewer_notes: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


NON_BLOCKING_ISSUES = {"behavioral_anomaly", "aml_reporting_threshold_exceeded", "pep_involved"}


class ComplianceScreeningEngine:
    def __init__(self, lists_path: Optional[str] = None, cache_max_size: int = 2048, cache_ttl: float = 600.0):
        self.profiles: Dict[str, _BridgeComplianceProfile] = {}
        self.check_history: List[_BridgeComplianceCheckResult] = []
        self.lists = load_compliance_lists(path=lists_path)
        cache_cfg = self.lists.cache or {}
        self.cache = ScreeningCache(
            max_size=int(cache_cfg.get("max_size", cache_max_size)),
            default_ttl=float(cache_cfg.get("ttl_seconds", cache_ttl)),
        )
        self.registry = ComplianceProviderRegistry(lists=self.lists, cache=self.cache)
        self.providers: Dict[str, BaseProvider] = {}

    def initialize(self) -> None:
        self.registry.load()
        self.providers = dict(self.registry.providers)

    def get_jurisdiction_rules(self, jurisdiction: str) -> Dict[str, Any]:
        return JURISDICTION_RULES.get(jurisdiction.upper(), JURISDICTION_RULES["JM"])

    def screen_entity(self, name: str, kind: str = "sanctions", context: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[Dict[str, Any]]]:
        context = context or {"kind": kind}
        results = self.registry.screen(term=name, kind=kind, context=context)
        matches = []
        value = False
        for result in results:
            value = value or result.value
            if result.value:
                matches.append({
                    "provider": result.provider_id,
                    "kind": kind,
                    "term": name,
                    "matches": getattr(result, "meta", {}).get("matches", []),
                    "cached": getattr(result, "meta", {}).get("cached", False),
                })
        return value, matches

    def screen_sanctions(self, name: str) -> bool:
        hit, _ = self.screen_entity(name, kind="sanctions", context={"kind": "sanctions"})
        return hit

    def screen_pep(self, name: str) -> bool:
        hit, _ = self.screen_entity(name, kind="pep", context={"kind": "pep"})
        return hit

    def screen_transaction(self, *, transaction_id: str, from_participant: str, to_participant: str,
                           amount_usd: float, currency: str, from_jurisdiction: str, to_jurisdiction: str,
                           purpose: str = "trade", context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        sanctions_from, matches_from = self.screen_entity(from_participant, kind="sanctions")
        sanctions_to, matches_to = self.screen_entity(to_participant, kind="sanctions")
        pep_from, pep_matches_from = self.screen_entity(from_participant, kind="pep")
        pep_to, pep_matches_to = self.screen_entity(to_participant, kind="pep")

        issues = []
        if sanctions_from:
            issues.append("sanctions_match")
        if sanctions_to:
            issues.append("sanctions_match")
        if pep_from:
            issues.append("pep_involved")
        if pep_to:
            issues.append("pep_involved")

        passed = len([i for i in issues if i not in {"pep_involved"}]) == 0
        review = decide_review(passed=passed, issues=issues, amount_usd=amount_usd, sanctions_hit=bool(sanctions_from or sanctions_to), pep_flagged=bool(pep_from or pep_to))
        return {
            "transaction_id": transaction_id,
            "passed": passed,
            "requires_review": review,
            "issues": issues,
            "sanctions": {"from": matches_from, "to": matches_to, "hit_count": len(matches_from) + len(matches_to)},
            "pep": {"from": pep_matches_from, "to": pep_matches_to},
        }


    def onboard_participant(
        self,
        participant_id: str,
        jurisdiction: str,
        kyc_documents: Dict[str, str],
        beneficial_owners: Optional[List[Dict[str, Any]]] = None,
        kyc_tier: int = 1,
    ) -> _BridgeComplianceCheckResult:
        rules = JURISDICTION_RULES.get(jurisdiction.upper(), JURISDICTION_RULES["JM"])
        required_docs = rules.get("kyc_required", [])
        missing_docs = [doc for doc in required_docs if doc not in kyc_documents]
        doc_complete = not missing_docs
        max_tier = len(rules.get("kyc_tier_limits", {1: 100000}))
        actual_tier = min(kyc_tier, max_tier)
        if not doc_complete:
            actual_tier = 1

        pep_detected = False
        sanctions_hit = False
        if beneficial_owners:
            for owner in beneficial_owners:
                pep_detected = pep_detected or bool(self.screen_pep(owner.get("name", "")))
                sanctions_hit = sanctions_hit or bool(self.screen_sanctions(owner.get("name", "")))

        profile = _BridgeComplianceProfile(
            participant_id=participant_id,
            jurisdiction=jurisdiction,
            kyc_status="verified" if doc_complete else "failed",
            kyc_tier=actual_tier,
            kyc_documents=kyc_documents,
            aml_risk_score=0.1 if doc_complete else 0.8,
            sanctions_cleared=not sanctions_hit,
            pep_status=pep_detected,
            restrictions=[] if doc_complete and not sanctions_hit else ["kyc_incomplete"],
        )
        self.profiles[participant_id] = profile

        check_id = f"kyc-{participant_id}-{int(datetime.now(timezone.utc).timestamp())}"
        result = _BridgeComplianceCheckResult(
            check_id=check_id,
            participant_id=participant_id,
            check_type="kyc",
            passed=doc_complete and not sanctions_hit,
            score=1.0 if doc_complete and not sanctions_hit else 0.3,
            details={
                "missing_documents": missing_docs,
                "kyc_tier": actual_tier,
                "pep_detected": pep_detected,
                "sanctions_hit": sanctions_hit,
                "beneficial_owners_screened": len(beneficial_owners) if beneficial_owners else 0,
            },
            requires_review=pep_detected or sanctions_hit or not doc_complete,
        )
        self.check_history.append(result)
        return result

    def update_kyc(self, participant_id: str, documents: Dict[str, str]) -> _BridgeComplianceCheckResult:
        if participant_id not in self.profiles:
            return _BridgeComplianceCheckResult(
                check_id=f"kyc-update-{participant_id}-{int(datetime.now(timezone.utc).timestamp())}",
                participant_id=participant_id,
                check_type="kyc",
                passed=False,
                score=0.0,
                details={"error": "Participant not found"},
                requires_review=True,
            )
        profile = self.profiles[participant_id]
        merged = dict(profile.kyc_documents)
        merged.update(documents)
        return self.onboard_participant(
            participant_id=participant_id,
            jurisdiction=profile.jurisdiction,
            kyc_documents=merged,
            kyc_tier=profile.kyc_tier,
        )

    def _detect_anomaly(self, from_participant: str, to_participant: str, amount_usd: float, purpose: str) -> float:
        anomaly = 0.0
        if amount_usd > 100000:
            anomaly += 0.2
        if amount_usd > 500000:
            anomaly += 0.3
        from_profile = self.profiles.get(from_participant)
        to_profile = self.profiles.get(to_participant)
        if from_profile and to_participant not in (from_profile.metadata or {}).get("counterparties", []):
            anomaly += 0.15
        if purpose not in ["trade", "remittance", "investment"]:
            anomaly += 0.1
        return min(1.0, anomaly)

    def run_periodic_sanctions_screening(self) -> List[_BridgeComplianceCheckResult]:
        results: List[_BridgeComplianceCheckResult] = []
        for participant_id, profile in list(self.profiles.items()):
            if profile.sanctions_cleared:
                match = self.screen_sanctions(participant_id)
                if match:
                    profile.sanctions_cleared = False
                    profile.restrictions.append("sanctions_match")
                    result = _BridgeComplianceCheckResult(
                        check_id=f"periodic-sanctions-{participant_id}-{int(datetime.now(timezone.utc).timestamp())}",
                        participant_id=participant_id,
                        check_type="sanctions",
                        passed=False,
                        score=0.0,
                        details={"reason": "Periodic screening detected sanctions match"},
                        requires_review=True,
                    )
                    results.append(result)
                    self.check_history.append(result)
        return results

    def get_profile(self, participant_id: str) -> Optional[_BridgeComplianceProfile]:
        return self.profiles.get(participant_id)

    def get_jurisdiction_entries(self) -> Dict[str, Dict[str, Any]]:
        """Return legacy jurisdiction rules from the new engine."""
        return dict(JURISDICTION_RULES)


def decide_sanctions_block(hit_count: int, value: bool) -> bool:
    return value and hit_count > 0


def is_ed_only(pep_flagged: bool, sanctions_hit: bool, aml_only: bool) -> bool:
    return pep_flagged and not sanctions_hit and not aml_only


def decide_review(*, passed: bool, issues: List[str], amount_usd: float, sanctions_hit: bool, pep_flagged: bool) -> bool:
    if not passed:
        return True
    if sanctions_hit:
        return True
    if pep_flagged:
        return True
    if amount_usd > 250000:
        return True
    return False
