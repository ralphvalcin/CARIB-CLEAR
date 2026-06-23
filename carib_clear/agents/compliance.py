# agents/compliance.py
"""
CARIB-CLEAR Compliance Agent

Multi-jurisdiction KYC/AML/sanctions compliance for Caribbean financial transactions.
Deterministic rules + AI-assisted monitoring for JM, BB, TT, HT, ECCB.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ComplianceProfile:
    """Compliance profile for a participant."""
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
    """Result of a compliance check."""
    check_id: str
    participant_id: str
    check_type: str  # "kyc", "aml", "sanctions", "pep", "transaction"
    passed: bool
    score: float
    details: Dict[str, Any]
    requires_review: bool = False
    reviewer_notes: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─── Jurisdiction-Specific Rules ─────────────────────────────────
JURISDICTION_RULES = {
    "JM": {  # Jamaica - BOJ
        "regulator": "Bank of Jamaica",
        "kyc_required": ["tax_compliance_certificate", "national_id", "proof_of_address", "trn"],
        "kyc_tier_limits": {1: 50000, 2: 250000, 3: 1000000},  # JMD
        "aml_threshold_jmd": 1000000,  # 1M JMD ~ $6500 USD
        "reporting_currency": "JMD",
        "sanctions_lists": ["OFAC", "UN", "BOJ"],
        "pep_required": True,
        "beneficial_ownership_threshold": 0.10,  # 10%
    },
    "BB": {  # Barbados - CBB
        "regulator": "Central Bank of Barbados",
        "kyc_required": ["tax_clearance_certificate", "national_id", "proof_of_address"],
        "kyc_tier_limits": {1: 100000, 2: 500000, 3: 2000000},  # BBD
        "aml_threshold_bbd": 200000,  # 200k BBD ~ $100k USD
        "reporting_currency": "BBD",
        "sanctions_lists": ["OFAC", "UN", "CBB"],
        "pep_required": True,
        "beneficial_ownership_threshold": 0.10,
    },
    "TT": {  # Trinidad & Tobago - CBTT
        "regulator": "Central Bank of Trinidad and Tobago",
        "kyc_required": ["national_id", "proof_of_address", "bir_clearance_certificate"],
        "kyc_tier_limits": {1: 50000, 2: 250000, 3: 1000000},  # TTD
        "aml_threshold_ttd": 500000,  # 500k TTD ~ $75k USD
        "reporting_currency": "TTD",
        "sanctions_lists": ["OFAC", "UN", "CBTT"],
        "pep_required": True,
        "beneficial_ownership_threshold": 0.10,
    },
    "HT": {  # Haiti - BRH
        "regulator": "Banque de la République d'Haïti",
        "kyc_required": ["national_id", "proof_of_address", "nif_certificate"],
        "kyc_tier_limits": {1: 10000, 2: 50000, 3: 250000},  # HTG
        "aml_threshold_htg": 500000,  # 500k HTG ~ $3800 USD
        "reporting_currency": "HTG",
        "sanctions_lists": ["OFAC", "UN", "BRH"],
        "pep_required": True,
        "beneficial_ownership_threshold": 0.25,  # Lower threshold in Haiti
    },
    "ECCB": {  # Eastern Caribbean Currency Union
        "regulator": "Eastern Caribbean Central Bank",
        "kyc_required": ["national_id", "proof_of_address", "tax_compliance_certificate"],
        "kyc_tier_limits": {1: 50000, 2: 250000, 3: 1000000},  # XCD
        "aml_threshold_xcd": 270000,  # 270k XCD ~ $100k USD
        "reporting_currency": "XCD",
        "sanctions_lists": ["OFAC", "UN", "ECCB"],
        "pep_required": True,
        "beneficial_ownership_threshold": 0.10,
    },
}


class ComplianceAgent:
    """
    Compliance Agent - The "gatekeeper" of the CARICOM FX Swap Network.
    
    Handles:
    - Multi-jurisdiction KYC verification
    - AML screening with jurisdiction-specific thresholds
    - Sanctions screening (OFAC, UN, local lists)
    - PEP (Politically Exposed Person) detection
    - Transaction monitoring with risk scoring
    - Regulatory reporting (CTR, SAR, etc.)
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.profiles: Dict[str, ComplianceProfile] = {}
        self.check_history: List[ComplianceCheckResult] = []
        
        # AI model for anomaly detection (placeholder)
        self.anomaly_threshold = self.config.get("anomaly_threshold", 0.8)
    
    def get_jurisdiction_rules(self, jurisdiction: str) -> Dict[str, Any]:
        """Get compliance rules for a jurisdiction."""
        return JURISDICTION_RULES.get(jurisdiction.upper(), JURISDICTION_RULES["JM"])
    
    # ─── Participant Onboarding ──────────────────────────────────
    
    def onboard_participant(
        self,
        participant_id: str,
        jurisdiction: str,
        kyc_documents: Dict[str, str],
        beneficial_owners: List[Dict[str, Any]] = None,
        kyc_tier: int = 1,
    ) -> ComplianceCheckResult:
        """Onboard a new participant with KYC verification."""
        
        rules = self.get_jurisdiction_rules(jurisdiction)
        required_docs = rules.get("kyc_required", [])
        
        # Check required documents
        missing_docs = [doc for doc in required_docs if doc not in kyc_documents]
        doc_complete = len(missing_docs) == 0
        
        # Determine KYC tier based on documents + self-declared tier
        max_tier = len(rules.get("kyc_tier_limits", {1: 100000}))
        actual_tier = min(kyc_tier, max_tier)
        
        if not doc_complete:
            actual_tier = 1  # Downgrade if missing docs
        
        # Screen beneficial owners for PEP/sanctions
        pep_detected = False
        sanctions_hit = False
        
        if beneficial_owners:
            for owner in beneficial_owners:
                pep_check = self._screen_pep(owner.get("name", ""))
                sanctions_check = self._screen_sanctions(owner.get("name", ""))
                
                if pep_check:
                    pep_detected = True
                if sanctions_check:
                    sanctions_hit = True
        
        # Build profile
        profile = ComplianceProfile(
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
        
        result = ComplianceCheckResult(
            check_id=f"kyc-{participant_id}-{int(time.time())}",
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
    
    def update_kyc(self, participant_id: str, documents: Dict[str, str]) -> ComplianceCheckResult:
        """Update KYC documents for existing participant."""
        profile = self.profiles.get(participant_id)
        if not profile:
            return ComplianceCheckResult(
                check_id=f"kyc-update-{participant_id}-{int(time.time())}",
                participant_id=participant_id,
                check_type="kyc",
                passed=False,
                score=0.0,
                details={"error": "Participant not found"},
                requires_review=True,
            )
        
        # Merge new documents
        profile.kyc_documents.update(documents)
        
        # Re-verify
        return self.onboard_participant(
            participant_id=participant_id,
            jurisdiction=profile.jurisdiction,
            kyc_documents=profile.kyc_documents,
            kyc_tier=profile.kyc_tier,
        )
    
    # ─── Transaction Screening ───────────────────────────────────
    
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
        """Screen a transaction for AML/compliance issues."""
        
        from_profile = self.profiles.get(from_participant)
        to_profile = self.profiles.get(to_participant)
        
        checks = []
        issues = []
        
        # 1. Participant KYC status
        for participant_id, profile, side in [
            (from_participant, from_profile, "from"),
            (to_participant, to_profile, "to"),
        ]:
            if not profile:
                issues.append(f"{side}_participant_not_onboarded")
                checks.append({"check": f"{side}_kyc", "passed": False, "reason": "Not onboarded"})
            elif profile.kyc_status != "verified":
                issues.append(f"{side}_kyc_not_verified")
                checks.append({"check": f"{side}_kyc", "passed": False, "reason": f"KYC status: {profile.kyc_status}"})
            else:
                checks.append({"check": f"{side}_kyc", "passed": True})
            
            # Check KYC tier limits
            if profile:
                rules = self.get_jurisdiction_rules(profile.jurisdiction)
                tier_limits = rules.get("kyc_tier_limits", {})
                limit = tier_limits.get(profile.kyc_tier, tier_limits.get(max(tier_limits.keys()), 100000))
                if amount_usd > limit:
                    issues.append(f"{side}_kyc_tier_exceeded")
                    checks.append({
                        "check": f"{side}_tier_limit", 
                        "passed": False, 
                        "reason": f"Amount ${amount_usd:,.0f} exceeds tier {profile.kyc_tier} limit ${limit:,.0f}"
                    })
        
        # 2. AML threshold check
        from_rules = self.get_jurisdiction_rules(from_jurisdiction)
        to_rules = self.get_jurisdiction_rules(to_jurisdiction)
        
        # Convert amount to local currency for threshold check (simplified)
        # In production would use real-time FX rates
        local_amount = amount_usd * self._get_usd_to_local_rate(currency)
        
        aml_thresholds = {
            "JM": from_rules.get("aml_threshold_jmd", 1000000),
            "BB": from_rules.get("aml_threshold_bbd", 200000),
            "TT": from_rules.get("aml_threshold_ttd", 500000),
            "HT": from_rules.get("aml_threshold_htg", 500000),
        }
        
        threshold = aml_thresholds.get(from_jurisdiction, 1000000)
        if local_amount > threshold:
            issues.append("aml_reporting_threshold_exceeded")
            checks.append({
                "check": "aml_threshold",
                "passed": True,  # Not a block, but requires CTR filing
                "reason": f"Amount ${amount_usd:,.0f} exceeds reporting threshold",
                "requires_ctr": True,
            })
        
        # 3. Sanctions screening
        sanctions_check = self._screen_sanctions(f"{from_participant}:{to_participant}")
        if sanctions_check:
            issues.append("sanctions_match")
            checks.append({"check": "sanctions", "passed": False, "reason": "Sanctions match detected"})
        else:
            checks.append({"check": "sanctions", "passed": True})
        
        # 4. PEP screening
        pep_from = from_profile.pep_status if from_profile else False
        pep_to = to_profile.pep_status if to_profile else False
        if pep_from or pep_to:
            issues.append("pep_involved")
            checks.append({"check": "pep", "passed": True, "reason": "PEP involved - enhanced due diligence required"})
        
        # 5. Behavioral anomaly detection (AI-assisted)
        anomaly_score = self._detect_anomaly(
            from_participant, to_participant, amount_usd, purpose
        )
        if anomaly_score > self.anomaly_threshold:
            issues.append("behavioral_anomaly")
            checks.append({
                "check": "anomaly",
                "passed": False,
                "reason": f"Anomaly score {anomaly_score:.2f} > threshold {self.anomaly_threshold}",
            })
        
        # Final decision
        passed = len([i for i in issues if "blocking" in i or "sanctions" in i]) == 0
        
        result = ComplianceCheckResult(
            check_id=f"txn-{transaction_id}-{int(time.time())}",
            participant_id=f"{from_participant}:{to_participant}",
            check_type="transaction",
            passed=passed,
            score=1.0 - (len(issues) * 0.15),
            details={
                "amount_usd": amount_usd,
                "currency": currency,
                "local_amount": local_amount,
                "issues": issues,
                "checks": checks,
                "requires_ctr": any("threshold" in i for i in issues),
                "requires_edd": "pep_involved" in issues,
            },
            requires_review=len(issues) > 0,
            reviewer_notes=f"{len(issues)} issues found" if issues else "Clean",
        )
        
        self.check_history.append(result)
        return result
    
    # ─── Periodic Screening ──────────────────────────────────────
    
    def run_periodic_sanctions_screening(self) -> List[ComplianceCheckResult]:
        """Run periodic sanctions screening on all participants."""
        results = []
        for participant_id, profile in self.profiles.items():
            if profile.sanctions_cleared:
                # Re-screen
                match = self._screen_sanctions(participant_id)
                if match:
                    profile.sanctions_cleared = False
                    profile.restrictions.append("sanctions_match")
                    
                    result = ComplianceCheckResult(
                        check_id=f"periodic-sanctions-{participant_id}-{int(time.time())}",
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
    
    # ─── Helper Methods ──────────────────────────────────────────
    
    def _screen_sanctions(self, name: str) -> bool:
        """Screen name against sanctions lists (mock - integrate with real provider)."""
        # In production: integrate with Dow Jones, Refinitiv, etc.
        # For buildathon: mock with known test names
        sanctions_keywords = [
            "specially designated national", "blocked person",
            "terrorist", "narcotics trafficking",
        ]
        
        name_lower = name.lower()
        for keyword in sanctions_keywords:
            if keyword in name_lower:
                return True
        return False
    
    def _screen_pep(self, name: str) -> bool:
        """Screen for PEP status (mock - integrate with real provider)."""
        # In production: integrate with PEP database
        # For buildathon: mock
        pep_keywords = ["minister", "president", "governor", "senator", "deputy"]
        
        name_lower = name.lower()
        for keyword in pep_keywords:
            if keyword in name_lower:
                return True
        return False
    
    def _detect_anomaly(
        self,
        from_participant: str,
        to_participant: str,
        amount_usd: float,
        purpose: str
    ) -> float:
        """AI-assisted anomaly detection (mock)."""
        # In production: train ML model on transaction patterns
        # For buildathon: simple heuristic
        anomaly = 0.0
        
        # Unusual amount
        if amount_usd > 100000:
            anomaly += 0.2
        if amount_usd > 500000:
            anomaly += 0.3
        
        # New counterparty
        from_profile = self.profiles.get(from_participant)
        to_profile = self.profiles.get(to_participant)
        
        if from_profile and to_participant not in from_profile.metadata.get("counterparties", []):
            anomaly += 0.15
        
        # Unusual purpose
        if purpose not in ["trade", "remittance", "investment"]:
            anomaly += 0.1
        
        # Velocity check (would check recent txn frequency)
        # anomaly += velocity_score
        
        return min(1.0, anomaly)
    
    def _get_usd_to_local_rate(self, currency: str) -> float:
        """Get USD to local currency rate (mock)."""
        rates = {
            "JMD": 154, "BBD": 2, "TTD": 6.8, 
            "XCD": 2.7, "HTG": 130, "USD": 1.0
        }
        return rates.get(currency, 1.0)
    
    # ─── Reporting ───────────────────────────────────────────────
    
    def generate_ctr_report(self, participant_id: str, period_start: str, period_end: str) -> Dict[str, Any]:
        """Generate Currency Transaction Report for reporting threshold breaches."""
        profile = self.profiles.get(participant_id)
        if not profile:
            return {"error": "Participant not found"}
        
        relevant_checks = [
            c for c in self.check_history
            if c.participant_id == participant_id
            and c.check_type == "transaction"
            and c.details.get("requires_ctr")
        ]
        
        return {
            "report_type": "CTR",
            "participant_id": participant_id,
            "jurisdiction": profile.jurisdiction,
            "period": f"{period_start} to {period_end}",
            "total_transactions": len(relevant_checks),
            "total_amount_usd": sum(
                c.details.get("amount_usd", 0) for c in relevant_checks
            ),
            "transactions": [
                {
                    "amount_usd": c.details.get("amount_usd"),
                    "currency": c.details.get("currency"),
                    "timestamp": c.timestamp,
                }
                for c in relevant_checks
            ],
        }
    
    def generate_sar_report(self, check_id: str) -> Optional[Dict[str, Any]]:
        """Generate Suspicious Activity Report."""
        check = next((c for c in self.check_history if c.check_id == check_id), None)
        if not check:
            return None
        
        return {
            "report_type": "SAR",
            "trigger_check_id": check_id,
            "participant": check.participant_id,
            "reason": check.details.get("issues", []),
            "amount_usd": check.details.get("amount_usd"),
            "timestamp": check.timestamp,
        }
    
    def get_compliance_dashboard(self) -> Dict[str, Any]:
        """Get compliance dashboard metrics."""
        total = len(self.profiles)
        verified = len([p for p in self.profiles.values() if p.kyc_status == "verified"])
        pep_count = len([p for p in self.profiles.values() if p.pep_status])
        sanctions_count = len([p for p in self.profiles.values() if not p.sanctions_cleared])
        
        txn_checks = [c for c in self.check_history if c.check_type == "transaction"]
        txn_passed = len([c for c in txn_checks if c.passed])
        txn_flagged = len([c for c in txn_checks if c.requires_review])
        
        return {
            "participants": {
                "total": total,
                "verified": verified,
                "pending_kyc": total - verified,
                "pep_flagged": pep_count,
                "sanctions_issues": sanctions_count,
            },
            "transactions": {
                "total_screened": len(txn_checks),
                "passed": txn_passed,
                "flagged_for_review": txn_flagged,
                "pass_rate": round(txn_passed / len(txn_checks) * 100, 1) if txn_checks else 100,
            },
            "recent_checks": [
                {
                    "check_id": c.check_id,
                    "type": c.check_type,
                    "passed": c.passed,
                    "score": c.score,
                    "timestamp": c.timestamp,
                }
                for c in self.check_history[-10:]
            ],
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    import time
    agent = ComplianceAgent()
    
    # Onboard participants
    print("--- Onboarding Participants ---")
    
    # Barbados hotel
    result = agent.onboard_participant(
        participant_id="bb_hotel_001",
        jurisdiction="BB",
        kyc_documents={
            "tax_clearance_certificate": "TCC-2024-001234",
            "national_id": "BBD-12345678",
            "proof_of_address": "Utility bill - 123 Bay St, Bridgetown",
        },
        beneficial_owners=[
            {"name": "John Smith", "ownership": 0.60},
            {"name": "Jane Doe", "ownership": 0.40},
        ],
        kyc_tier=3,
    )
    print(f"BB Hotel: {result.passed} (tier {result.details.get('kyc_tier')})")
    
    # Jamaica supplier
    result = agent.onboard_participant(
        participant_id="jm_supplier_001",
        jurisdiction="JM",
        kyc_documents={
            "tax_compliance_certificate": "TCC-JM-2024-567890",
            "national_id": "JMD-87654321",
            "proof_of_address": "Business license - 456 King St, Kingston",
            "trn": "123-456-789",
        },
        beneficial_owners=[
            {"name": "Minister Robert Brown", "ownership": 0.25},  # PEP!
            {"name": "Mary Williams", "ownership": 0.75},
        ],
        kyc_tier=2,
    )
    print(f"JM Supplier: {result.passed} (PEP: {result.details.get('pep_detected')})")
    
    # Screen transaction
    print("\n--- Screening Transaction ---")
    txn_result = agent.screen_transaction(
        transaction_id="txn-001",
        from_participant="bb_hotel_001",
        to_participant="jm_supplier_001",
        amount_usd=50000,
        currency="BBD",
        from_jurisdiction="BB",
        to_jurisdiction="JM",
        purpose="trade",
    )
    print(f"TXN-001: {txn_result.passed} (score: {txn_result.score:.2f})")
    print(f"  Issues: {txn_result.details.get('issues')}")
    print(f"  Requires CTR: {txn_result.details.get('requires_ctr')}")
    print(f"  Requires EDD: {txn_result.details.get('requires_edd')}")
    
    # Dashboard
    print("\n--- Compliance Dashboard ---")
    dash = agent.get_compliance_dashboard()
    print(f"Participants: {dash['participants']}")
    print(f"Transactions: {dash['transactions']}")