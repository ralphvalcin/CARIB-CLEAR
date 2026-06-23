# governance/agent.py
"""
CARIB-CLEAR Governance Agent

Extracted from trading-system/agents/governance_agent.py
Adapted for multi-jurisdiction FX/MSME compliance decisions.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── Default Thresholds ──────────────────────────────────────────────
_DEFAULT_THRESHOLDS = {
    "compliance": {
        "kyc_threshold": 0.7,
        "aml_risk_threshold": 0.6,
        "sanctions_check_threshold": 0.9,
        "pep_check_threshold": 0.8,
    },
    "fx_settlement": {
        "max_slippage_bps": 50,
        "min_liquidity_usd": 10000,
        "max_settlement_time_min": 30,
    },
    "msme_credit": {
        "min_cashflow_score": 0.6,
        "max_debt_service_ratio": 0.4,
        "min_operating_history_months": 6,
    }
}


def _load_thresholds(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load thresholds from config file, falling back to defaults."""
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "thresholds.json"
        )
    try:
        with open(config_path, "r") as fh:
            data = json.load(fh)
        merged = {}
        for section, defaults in _DEFAULT_THRESHOLDS.items():
            merged[section] = {**defaults, **data.get(section, {})}
        for section in data:
            if section not in merged:
                merged[section] = data[section]
        return merged
    except Exception as e:
        logger.warning(f"[Governance] Could not load thresholds.json ({e}); using defaults.")
        return dict(_DEFAULT_THRESHOLDS)


# ─── KYC/AML Rules per Jurisdiction ─────────────────────────────────
_JURISDICTION_RULES = {
    "JM": {  # Jamaica
        "central_bank": "Bank of Jamaica",
        "kyc_required_docs": ["national_id", "proof_of_address", "tax_compliance_cert"],
        "aml_reporting_threshold_usd": 10000,
        "sanctions_lists": ["OFAC", "UN", "BOJ"],
        "pep_check_required": True,
    },
    "BB": {  # Barbados
        "central_bank": "Central Bank of Barbados",
        "kyc_required_docs": ["national_id", "proof_of_address", "tax_clearance_cert"],
        "aml_reporting_threshold_usd": 10000,
        "sanctions_lists": ["OFAC", "UN", "CBB"],
        "pep_check_required": True,
    },
    "TT": {  # Trinidad & Tobago
        "central_bank": "Central Bank of Trinidad and Tobago",
        "kyc_required_docs": ["national_id", "proof_of_address", "bir_clearance"],
        "aml_reporting_threshold_usd": 10000,
        "sanctions_lists": ["OFAC", "UN", "CBTT"],
        "pep_check_required": True,
    },
    "HT": {  # Haiti
        "central_bank": "Banque de la République d'Haïti",
        "kyc_required_docs": ["national_id", "proof_of_address", "nif_cert"],
        "aml_reporting_threshold_usd": 5000,
        "sanctions_lists": ["OFAC", "UN", "BRH"],
        "pep_check_required": True,
    },
    "XCD": {  # ECCB (Eastern Caribbean)
        "central_bank": "Eastern Caribbean Central Bank",
        "kyc_required_docs": ["national_id", "proof_of_address", "tax_compliance"],
        "aml_reporting_threshold_usd": 10000,
        "sanctions_lists": ["OFAC", "UN", "ECCB"],
        "pep_check_required": True,
    },
}


@dataclass
class ComplianceCheck:
    """Result of a compliance check."""
    check_type: str
    jurisdiction: str
    passed: bool
    score: float
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class GovernanceDecision:
    """Final governance decision for a transaction or credit request."""
    approved: bool
    decision_type: str  # "fx_settlement", "msme_credit", "compliance"
    rationale: str
    confidence: float
    compliance_checks: List[ComplianceCheck] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GovernanceAgent:
    """
    Governance agent for CARIB-CLEAR financial decisions.
    
    Handles:
    - Multi-jurisdiction KYC/AML compliance
    - FX settlement approval
    - MSME credit underwriting decisions
    - Human-in-the-loop escalation
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self._thresholds = _load_thresholds(config_path)
        self.hitl_enabled = self._load_hitl_setting()
        
    def _load_hitl_setting(self) -> bool:
        """Read HITL mode from environment."""
        return os.getenv("CARIB_CLEAR_HITL_MODE", "false").lower() == "true"
    
    def reload_settings(self) -> None:
        """Refresh settings from config/env."""
        self.hitl_enabled = self._load_hitl_setting()

    def get_jurisdiction_rules(self, jurisdiction: str) -> Dict[str, Any]:
        """Get compliance rules for a jurisdiction."""
        return _JURISDICTION_RULES.get(jurisdiction.upper(), _JURISDICTION_RULES["JM"])

    # ─── Compliance Checks ──────────────────────────────────────────
    
    def run_kyc_check(
        self,
        jurisdiction: str,
        customer_data: Dict[str, Any],
        documents: Dict[str, str]
    ) -> ComplianceCheck:
        """Run KYC verification for a jurisdiction."""
        rules = self.get_jurisdiction_rules(jurisdiction)
        required_docs = rules.get("kyc_required_docs", [])
        
        # Check required documents
        missing_docs = [doc for doc in required_docs if doc not in documents]
        doc_score = 1.0 - (len(missing_docs) / max(len(required_docs), 1))
        
        # Validate document quality (simplified)
        quality_score = 1.0 if not missing_docs else 0.5
        
        overall_score = (doc_score * 0.7 + quality_score * 0.3)
        threshold = self._thresholds.get("compliance", {}).get("kyc_threshold", 0.7)
        
        return ComplianceCheck(
            check_type="kyc",
            jurisdiction=jurisdiction,
            passed=overall_score >= threshold,
            score=round(overall_score, 3),
            details={
                "required_docs": required_docs,
                "provided_docs": list(documents.keys()),
                "missing_docs": missing_docs,
                "threshold": threshold,
            }
        )
    
    def run_aml_check(
        self,
        jurisdiction: str,
        transaction_amount_usd: float,
        customer_risk_profile: Dict[str, Any]
    ) -> ComplianceCheck:
        """Run AML screening."""
        rules = self.get_jurisdiction_rules(jurisdiction)
        reporting_threshold = rules.get("aml_reporting_threshold_usd", 10000)
        
        # Simplified risk scoring
        risk_factors = {
            "high_amount": transaction_amount_usd > reporting_threshold,
            "pep_flag": customer_risk_profile.get("is_pep", False),
            "sanctions_match": customer_risk_profile.get("sanctions_match", False),
            "adverse_media": customer_risk_profile.get("adverse_media", False),
            "high_risk_country": customer_risk_profile.get("high_risk_country", False),
        }
        
        risk_score = sum(risk_factors.values()) / len(risk_factors)
        aml_score = 1.0 - risk_score
        threshold = self._thresholds.get("compliance", {}).get("aml_risk_threshold", 0.6)
        
        return ComplianceCheck(
            check_type="aml",
            jurisdiction=jurisdiction,
            passed=aml_score >= threshold,
            score=round(aml_score, 3),
            details={
                "risk_factors": risk_factors,
                "reporting_threshold_usd": reporting_threshold,
                "transaction_amount_usd": transaction_amount_usd,
                "threshold": threshold,
            }
        )
    
    def run_sanctions_check(
        self,
        jurisdiction: str,
        entity_name: str,
        entity_type: str = "individual"
    ) -> ComplianceCheck:
        """Run sanctions screening (stub - integrate with real provider)."""
        rules = self.get_jurisdiction_rules(jurisdiction)
        sanctions_lists = rules.get("sanctions_lists", [])
        
        # Stub: would call Sanctions API (Dow Jones, Refinitiv, etc.)
        # For buildathon: return clean with simulated check
        passed = True
        score = 0.95
        
        return ComplianceCheck(
            check_type="sanctions",
            jurisdiction=jurisdiction,
            passed=passed,
            score=score,
            details={
                "lists_checked": sanctions_lists,
                "entity_name": entity_name,
                "entity_type": entity_type,
            }
        )

    # ─── FX Settlement Approval ─────────────────────────────────────
    
    def approve_fx_settlement(
        self,
        *,
        correlation_id: str,
        from_currency: str,
        to_currency: str,
        amount_usd: float,
        rate: float,
        slippage_bps: float,
        liquidity_usd: float,
        settlement_rail: str,
        counterparty_jurisdiction: str,
    ) -> GovernanceDecision:
        """Approve or reject an FX settlement."""
        self.reload_settings()
        
        fx_t = self._thresholds.get("fx_settlement", _DEFAULT_THRESHOLDS["fx_settlement"])
        reasons = []
        approved = True
        block_reason = ""
        
        # Slippage check
        if slippage_bps > fx_t.get("max_slippage_bps", 50):
            approved = False
            block_reason = f"Slippage {slippage_bps}bps exceeds max {fx_t['max_slippage_bps']}bps"
        
        # Liquidity check
        elif liquidity_usd < fx_t.get("min_liquidity_usd", 10000):
            approved = False
            block_reason = f"Insufficient liquidity: ${liquidity_usd:,.0f} < ${fx_t['min_liquidity_usd']:,}"
        
        # Compliance checks
        compliance_checks = []
        
        # KYC/AML on counterparty
        for jur in [counterparty_jurisdiction, from_currency, to_currency]:
            if jur in _JURISDICTION_RULES:
                rules = self.get_jurisdiction_rules(jur)
                required = {doc: "verified" for doc in rules.get("kyc_required_docs", [])}
                kyc = self.run_kyc_check(jur, {"entity": "counterparty"}, required)
                aml = self.run_aml_check(jur, amount_usd, {})
                sanctions = self.run_sanctions_check(jur, f"counterparty_{jur}")
                compliance_checks.extend([kyc, aml, sanctions])
                
                if not all(c.passed for c in [kyc, aml, sanctions]):
                    approved = False
                    if not block_reason:
                        block_reason = f"Compliance check failed for jurisdiction {jur}"
        
        # Build rationale
        if approved:
            rationale = (
                f"FX settlement approved: {from_currency}→{to_currency} "
                f"${amount_usd:,.0f} @ {rate:.6f} via {settlement_rail}. "
                f"Slippage: {slippage_bps}bps, Liquidity: ${liquidity_usd:,.0f}. "
                + " ".join(reasons)
            )
        else:
            rationale = f"REJECTED: {block_reason}"
        
        # Confidence based on compliance
        passed_checks = sum(1 for c in compliance_checks if c.passed)
        total_checks = len(compliance_checks) if compliance_checks else 1
        confidence = round(0.5 + 0.5 * (passed_checks / total_checks), 3)
        
        # HITL escalation for large amounts
        if self.hitl_enabled and amount_usd > 50000:
            rationale += " | HITL: Requires human approval for amount >$50K"
            approved = False
            block_reason = "Human approval required (HITL enabled, amount >$50K)"
        
        decision = GovernanceDecision(
            approved=approved,
            decision_type="fx_settlement",
            rationale=rationale,
            confidence=confidence,
            compliance_checks=compliance_checks,
        )
        
        logger.info(f"[Governance] FX {correlation_id}: {from_currency}→{to_currency} ${amount_usd:,.0f} → {approved}")
        return decision

    # ─── MSME Credit Approval ───────────────────────────────────────
    
    def approve_msme_credit(
        self,
        *,
        correlation_id: str,
        business_id: str,
        jurisdiction: str,
        cashflow_score: float,
        debt_service_ratio: float,
        operating_history_months: int,
        requested_amount_usd: float,
        collateral_value_usd: float = 0,
        business_data: Optional[Dict[str, Any]] = None,
    ) -> GovernanceDecision:
        """Approve or reject MSME credit based on cash-flow underwriting."""
        self.reload_settings()
        
        credit_t = self._thresholds.get("msme_credit", _DEFAULT_THRESHOLDS["msme_credit"])
        reasons = []
        approved = True
        block_reason = ""
        
        # Cashflow score check
        min_score = credit_t.get("min_cashflow_score", 0.6)
        if cashflow_score < min_score:
            approved = False
            block_reason = f"Cashflow score {cashflow_score:.2f} below minimum {min_score}"
        else:
            reasons.append(f"Strong cashflow score: {cashflow_score:.2f}")
        
        # Debt service ratio
        max_dsr = credit_t.get("max_debt_service_ratio", 0.4)
        if debt_service_ratio > max_dsr:
            approved = False
            block_reason = f"Debt service ratio {debt_service_ratio:.2f} exceeds max {max_dsr}"
        else:
            reasons.append(f"Healthy debt service ratio: {debt_service_ratio:.2f}")
        
        # Operating history
        min_history = credit_t.get("min_operating_history_months", 6)
        if operating_history_months < min_history:
            approved = False
            block_reason = f"Insufficient operating history: {operating_history_months}mo < {min_history}mo"
        else:
            reasons.append(f"Established business: {operating_history_months} months operating")
        
        # Collateral vs no-collateral logic
        if collateral_value_usd >= requested_amount_usd:
            reasons.append("Fully collateralized")
        elif collateral_value_usd > 0:
            reasons.append(f"Partially collateralized (${collateral_value_usd:,.0f})")
        else:
            reasons.append("Unsecured - cash-flow based underwriting")
        
        # Compliance checks
        compliance_checks = []
        for jur in [jurisdiction]:
            rules = self.get_jurisdiction_rules(jur)
            required = {doc: "verified" for doc in rules.get("kyc_required_docs", [])}
            kyc = self.run_kyc_check(jur, {"entity": business_id}, required)
            aml = self.run_aml_check(jur, requested_amount_usd, {})
            sanctions = self.run_sanctions_check(jur, business_id, "business")
            compliance_checks.extend([kyc, aml, sanctions])
            
            if not all(c.passed for c in [kyc, aml, sanctions]):
                approved = False
                if not block_reason:
                    block_reason = f"Compliance check failed for {jur}"
        
        # Build rationale
        if approved:
            rationale = (
                f"MSME credit approved: {business_id} in {jurisdiction} | "
                f"Cashflow: {cashflow_score:.2f} | DSR: {debt_service_ratio:.2f} | "
                f"History: {operating_history_months}mo | "
                f"Amount: ${requested_amount_usd:,.0f} | "
                + " ".join(reasons)
            )
        else:
            rationale = f"REJECTED: {block_reason}"
        
        # Confidence
        base_conf = 0.6
        if approved:
            base_conf += 0.1 * (cashflow_score - min_score) / (1 - min_score)
            base_conf += 0.1 * (1 - debt_service_ratio / max_dsr)
            base_conf += 0.1 * min(1.0, operating_history_months / 24)
        
        passed_checks = sum(1 for c in compliance_checks if c.passed)
        total_checks = len(compliance_checks) if compliance_checks else 1
        base_conf += 0.1 * (passed_checks / total_checks)
        confidence = round(min(0.95, max(0.3, base_conf)), 3)
        
        # HITL for large loans
        if self.hitl_enabled and requested_amount_usd > 25000:
            rationale += " | HITL: Requires human approval for loan >$25K"
            approved = False
            block_reason = "Human approval required (HITL enabled, loan >$25K)"
        
        decision = GovernanceDecision(
            approved=approved,
            decision_type="msme_credit",
            rationale=rationale,
            confidence=confidence,
            compliance_checks=compliance_checks,
        )
        
        logger.info(f"[Governance] Credit {correlation_id}: {business_id} ${requested_amount_usd:,.0f} → {approved}")
        return decision


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = GovernanceAgent()
    
    # Test FX settlement
    print("\n--- TEST: FX Settlement ---")
    fx_decision = agent.approve_fx_settlement(
        correlation_id="test-fx-1",
        from_currency="BBD",
        to_currency="JMD",
        amount_usd=15000,
        rate=76.5,
        slippage_bps=25,
        liquidity_usd=50000,
        settlement_rail="Stellar/USDC",
        counterparty_jurisdiction="JM",
    )
    print(f"Approved: {fx_decision.approved}")
    print(f"Rationale: {fx_decision.rationale}")
    print(f"Confidence: {fx_decision.confidence}")
    
    # Test MSME credit
    print("\n--- TEST: MSME Credit ---")
    credit_decision = agent.approve_msme_credit(
        correlation_id="test-credit-1",
        business_id="haitian_artisan_001",
        jurisdiction="HT",
        cashflow_score=0.75,
        debt_service_ratio=0.3,
        operating_history_months=24,
        requested_amount_usd=10000,
        collateral_value_usd=0,
    )
    print(f"Approved: {credit_decision.approved}")
    print(f"Rationale: {credit_decision.rationale}")
    print(f"Confidence: {credit_decision.confidence}")