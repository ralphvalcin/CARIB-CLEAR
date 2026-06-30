"""CashFlowLendingEngine — final credit decision engine for MSME lending.

Takes a CreditProfile from CreditProfileGenerator and produces the final
LoanDecision after applying lender-specific policies and governance rules.

Pipeline:
  CreditProfileGenerator → CashFlowLendingEngine → GovernanceAgent → LenderAdapters

Supports multiple lender backends (Barita, JMMB, IDB Invest) each with
their own risk appetite, rate cards, and product types.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class LendingProduct:
    """A lending product offered by a specific lender."""

    lender_id: str
    product_name: str
    min_amount_usd: float
    max_amount_usd: float
    min_credit_score: float  # 0.0-1.0
    max_interest_rate: float  # APR
    min_tenure_months: int
    max_tenure_months: int
    requires_collateral: bool
    eligible_sectors: List[str]
    eligible_jurisdictions: List[str]
    description: str = ""
    processing_fee_bps: float = 0.0  # Basis points


@dataclass
class LoanApplication:
    """A loan application from an MSME."""

    application_id: str
    business_id: str
    business_name: str
    jurisdiction: str
    requested_amount_usd: float
    purpose: str  # "working_capital", "equipment", "expansion", "invoice_financing"
    preferred_tenure_months: int = 12
    preferred_lender: str = "auto"  # "barita", "jmmb", "idb_invest", "auto"
    collateral_offered_usd: float = 0.0
    additional_notes: str = ""

    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class LoanDecision:
    """Final lending decision from CashFlowLendingEngine."""

    application_id: str
    business_id: str
    approved: bool
    decision_type: str  # "approved", "denied", "review", "referred"

    # Terms (when approved)
    lender_id: str = ""
    product_name: str = ""
    approved_amount_usd: float = 0.0
    interest_rate_annual_pct: float = 0.0
    tenure_months: int = 0
    collateral_required: bool = False
    processing_fee_usd: float = 0.0
    monthly_payment_usd: float = 0.0

    # Conditions
    conditions: List[str] = field(default_factory=list)
    conditions_met: List[str] = field(default_factory=list)

    # Rationale
    rationale: str = ""
    matched_product: str = ""
    rejection_reasons: List[str] = field(default_factory=list)

    # Audit
    credit_score_at_decision: float = 0.0
    governance_decision: Optional[Dict[str, Any]] = None
    lender_response: Optional[Dict[str, Any]] = None

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = ""

    def summary(self) -> Dict[str, Any]:
        """Return a concise summary for API/display."""
        return {
            "application_id": self.application_id,
            "business_id": self.business_id,
            "approved": self.approved,
            "status": self.decision_type,
            "lender": self.lender_id,
            "amount": self.approved_amount_usd,
            "rate": self.interest_rate_annual_pct,
            "tenure": self.tenure_months,
            "monthly": self.monthly_payment_usd,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Lender Product Catalog — Bank-specific policies
# ─────────────────────────────────────────────────────────────────────────────

LENDER_PRODUCTS: Dict[str, List[LendingProduct]] = {
    "barita": [
        LendingProduct(
            lender_id="barita",
            product_name="Barita MSME Growth Loan",
            min_amount_usd=5000,
            max_amount_usd=100000,
            min_credit_score=0.50,
            max_interest_rate=22.0,
            min_tenure_months=6,
            max_tenure_months=36,
            requires_collateral=False,
            eligible_sectors=["retail", "services", "manufacturing", "tech", "agriculture"],
            eligible_jurisdictions=["JM", "BB", "TT"],
            description="Unsecured cash-flow based lending for Caribbean MSMEs",
            processing_fee_bps=100,  # 1%
        ),
        LendingProduct(
            lender_id="barita",
            product_name="Barita Invoice Financing",
            min_amount_usd=10000,
            max_amount_usd=50000,
            min_credit_score=0.45,
            max_interest_rate=18.0,
            min_tenure_months=1,
            max_tenure_months=3,
            requires_collateral=False,
            eligible_sectors=["retail", "services", "manufacturing", "tech"],
            eligible_jurisdictions=["JM", "BB"],
            description="Short-term financing against outstanding invoices",
            processing_fee_bps=150,
        ),
    ],
    "jmmb": [
        LendingProduct(
            lender_id="jmmb",
            product_name="JMMB MSME Empowerment Loan",
            min_amount_usd=2000,
            max_amount_usd=50000,
            min_credit_score=0.45,
            max_interest_rate=25.0,
            min_tenure_months=6,
            max_tenure_months=24,
            requires_collateral=True,
            eligible_sectors=["retail", "services", "agriculture"],
            eligible_jurisdictions=["JM"],
            description="JMMB's flagship MSME product with mentoring",
            processing_fee_bps=200,
        ),
    ],
    "idb_invest": [
        LendingProduct(
            lender_id="idb_invest",
            product_name="IDB Invest Caribbean Green MSME",
            min_amount_usd=25000,
            max_amount_usd=200000,
            min_credit_score=0.60,
            max_interest_rate=12.0,
            min_tenure_months=12,
            max_tenure_months=60,
            requires_collateral=False,
            eligible_sectors=["agriculture", "services", "tech", "retail"],
            eligible_jurisdictions=["JM", "BB", "TT", "HT"],
            description="Concessional green/sustainable business financing",
            processing_fee_bps=50,
        ),
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# CashFlowLendingEngine
# ─────────────────────────────────────────────────────────────────────────────


class CashFlowLendingEngine:
    """Final credit decision engine for MSME lending.

    Orchestrates the end-to-end lending decision:
    1. Receive CreditProfile + LoanApplication
    2. Match to lender products based on credit quality and eligibility
    3. Calculate pricing (interest rate, fees, monthly payment)
    4. Submit to GovernanceAgent for compliance and HITL
    5. Return final LoanDecision
    """

    def __init__(
        self,
        governance_agent: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.governance = governance_agent
        self.config = config or {}

        # Lender product catalog (can be overridden via config)
        self.products: Dict[str, List[LendingProduct]] = dict(LENDER_PRODUCTS)

        # Decision history
        self.decisions: List[LoanDecision] = []

    # ─── Public API ──────────────────────────────────────────────────────

    def evaluate(
        self,
        credit_profile: Any,
        application: LoanApplication,
    ) -> LoanDecision:
        """Evaluate a loan application against a credit profile.

        This is the main entry point. It:
        1. Matches the best lender product
        2. Calculates pricing
        3. Submits to governance
        4. Returns the final decision
        """
        logger.info(
            "[LendingEngine] Evaluating %s for %s: $%.0f over %dmo",
            application.application_id, application.business_name,
            application.requested_amount_usd, application.preferred_tenure_months,
        )

        # Step 1: Match lender product
        product = self._match_product(credit_profile, application)
        if not product:
            decision = self._deny_no_product(application, credit_profile)
            self.decisions.append(decision)
            return decision

        # Step 2: Calculate pricing
        pricing = self._calculate_pricing(product, credit_profile, application)
        if not pricing["viable"]:
            decision = self._deny_pricing(application, credit_profile, pricing)
            self.decisions.append(decision)
            return decision

        # Step 3: Governance approval
        gov_ok = True
        gov_decision = None
        if self.governance:
            try:
                gov_result = self.governance.approve_msme_credit(
                    correlation_id=application.application_id,
                    business_id=application.business_id,
                    jurisdiction=application.jurisdiction,
                    cashflow_score=credit_profile.credit_score,
                    debt_service_ratio=self._estimate_dsr(pricing["monthly_payment"], credit_profile),
                    operating_history_months=getattr(credit_profile, "operating_months", 12),
                    requested_amount_usd=pricing["approved_amount"],
                    collateral_value_usd=application.collateral_offered_usd,
                    business_data={"credit_rating": credit_profile.credit_rating},
                )
                gov_decision = {
                    "approved": gov_result.approved,
                    "rationale": gov_result.rationale,
                    "confidence": gov_result.confidence,
                    "checks": [c.check_type for c in gov_result.compliance_checks],
                }

                if not gov_result.approved:
                    gov_ok = False
                    logger.warning(
                        "[LendingEngine] Governance rejected %s: %s",
                        application.application_id, gov_result.rationale,
                    )
            except Exception as exc:
                logger.error("[LendingEngine] Governance call failed: %s", exc)
                gov_ok = False

        # Step 4: Build decision with lender submission
        if gov_ok:
            decision = self._approve(
                application, credit_profile, product, pricing, gov_decision,
            )

            # Step 5: Submit to lender adapter
            lender_result = self._submit_to_lender(decision, credit_profile, application)
            if lender_result:
                decision.lender_response = {
                    "submitted": True,
                    "lender_application_id": lender_result.lender_application_id,
                    "lender_status": lender_result.status,
                    "lender_message": lender_result.message,
                }
                # Update decision with lender's reference
                decision.matched_product = f"{decision.lender_id}/{lender_result.lender_application_id}"
                logger.info(
                    "[LendingEngine] Submitted to %s: app=%s status=%s",
                    decision.lender_id, lender_result.lender_application_id, lender_result.status,
                )
        else:
            decision = self._deny_governance(
                application, credit_profile, gov_decision,
            )

        from carib_clear.webhooks import dispatch_event
        event_type = "loan.approved" if decision.approved else "loan.declined"
        dispatch_event(event_type, {
            "application_id": application.application_id,
            "business_name": application.business_name,
            "jurisdiction": application.jurisdiction,
            "requested_amount_usd": application.requested_amount_usd,
            "approved_amount_usd": decision.approved_amount_usd,
            "interest_rate_apr_pct": decision.interest_rate_annual_pct,
            "tenure_months": decision.tenure_months,
            "lender_id": decision.lender_id,
            "decision_type": decision.decision_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        self.decisions.append(decision)
        return decision

    # ─── Product Matching ────────────────────────────────────────────────

    def _match_product(
        self,
        credit_profile: Any,
        application: LoanApplication,
    ) -> Optional[LendingProduct]:
        """Match the best lending product for this application.

        Considers: credit score, amount, jurisdiction, sector, collateral.
        Returns the best product or None if no match.
        """
        score = credit_profile.credit_score
        jurisdiction = credit_profile.jurisdiction
        sector_name = credit_profile.sector_name
        amount = application.requested_amount_usd
        preferred = application.preferred_lender

        candidates: List[tuple[LendingProduct, float]] = []

        for lender_id, products in self.products.items():
            if preferred != "auto" and lender_id != preferred:
                continue

            for product in products:
                match_score = 0.0

                # Credit score check (hard gate)
                if score < product.min_credit_score:
                    continue

                # Amount range (hard gate)
                if amount < product.min_amount_usd or amount > product.max_amount_usd:
                    continue

                # Jurisdiction (hard gate)
                if jurisdiction not in product.eligible_jurisdictions:
                    continue

                # Sector (hard gate)
                if sector_name not in product.eligible_sectors:
                    continue

                # Collateral check
                if product.requires_collateral and application.collateral_offered_usd < amount * 0.5:
                    continue

                # Score the match (higher = better)
                # Prefer higher credit score fit
                score_fit = (score - product.min_credit_score) / (1.0 - product.min_credit_score)
                match_score += score_fit * 0.4

                # Prefer lower interest rates
                rate_fit = 1.0 - (product.max_interest_rate / 30.0)
                match_score += rate_fit * 0.3

                # Prefer longer tenure (more flexibility)
                tenure_fit = product.max_tenure_months / 60.0
                match_score += tenure_fit * 0.15

                # Prefer no collateral
                if not product.requires_collateral:
                    match_score += 0.15

                candidates.append((product, match_score))

        if not candidates:
            return None

        # Return highest-scoring product
        candidates.sort(key=lambda x: x[1], reverse=True)
        matched = candidates[0][0]
        logger.info("[LendingEngine] Matched %s → %s/%s (score=%.2f)", application.application_id, matched.lender_id, matched.product_name, candidates[0][1])
        return matched

    # ─── Pricing ─────────────────────────────────────────────────────────

    def _calculate_pricing(
        self,
        product: LendingProduct,
        credit_profile: Any,
        application: LoanApplication,
    ) -> Dict[str, Any]:
        """Calculate loan pricing based on product and credit quality.

        Returns dict with pricing details and viability flag.
        """
        score = credit_profile.credit_score

        # Interest rate: interpolate within product's max rate based on score
        # Better score = lower rate
        score_quality = max(0.0, min(1.0, (score - product.min_credit_score) / (1.0 - product.min_credit_score)))
        min_rate = product.max_interest_rate * 0.5  # Floor at 50% of max
        rate = product.max_interest_rate - (product.max_interest_rate - min_rate) * score_quality

        # Adjust for risk factors
        if hasattr(credit_profile, 'negative_factors'):
            risk_penalty = len(credit_profile.negative_factors) * 0.5
            rate += risk_penalty

        # Jurisdiction risk premium
        risk_premia = {"HT": 3.0, "JM": 1.0, "TT": 1.0, "BB": 0.0, "XCD": 0.5}
        rate += risk_premia.get(application.jurisdiction, 1.0)

        # Cap at product max
        rate = min(rate, product.max_interest_rate)

        # Loan amount (cap at requested or product max)
        approved_amount = min(application.requested_amount_usd, product.max_amount_usd)

        # Tenure (use requested or product max, whichever is lower)
        tenure = min(application.preferred_tenure_months, product.max_tenure_months)
        tenure = max(tenure, product.min_tenure_months)

        # Processing fee
        fee = approved_amount * (product.processing_fee_bps / 10000)

        # Monthly payment (simple interest amortization)
        monthly_rate = (rate / 100) / 12
        if monthly_rate > 0 and tenure > 0:
            monthly_payment = approved_amount * (monthly_rate * (1 + monthly_rate) ** tenure) / ((1 + monthly_rate) ** tenure - 1)
        else:
            monthly_payment = approved_amount / tenure

        # Viability: monthly payment should not exceed 40% of monthly revenue
        annual_rev = credit_profile.estimated_annual_revenue_usd or 1
        monthly_rev = annual_rev / 12
        dsr = monthly_payment / monthly_rev if monthly_rev > 0 else 99

        viable = dsr <= 0.40 or monthly_payment <= monthly_rev * 0.40

        return {
            "approved_amount": approved_amount,
            "interest_rate": round(rate, 1),
            "tenure_months": tenure,
            "monthly_payment": round(monthly_payment, 2),
            "processing_fee": round(fee, 2),
            "total_repayment": round(monthly_payment * tenure, 2),
            "debt_service_ratio": round(dsr, 3),
            "viable": viable,
        }

    def _estimate_dsr(self, monthly_payment: float, credit_profile: Any) -> float:
        """Estimate debt service ratio from monthly payment and revenue."""
        annual = credit_profile.estimated_annual_revenue_usd or 1
        monthly = annual / 12
        return monthly_payment / monthly if monthly > 0 else 99

    # ─── Decision Builders ───────────────────────────────────────────────

    def _approve(
        self,
        application: LoanApplication,
        credit_profile: Any,
        product: LendingProduct,
        pricing: Dict[str, Any],
        gov_decision: Optional[Dict[str, Any]] = None,
    ) -> LoanDecision:
        """Build an approval decision."""
        from datetime import timedelta

        conditions = []
        if product.requires_collateral:
            conditions.append("Collateral agreement required before disbursement")
        if pricing["debt_service_ratio"] > 0.30:
            conditions.append("Monthly payment monitoring required for first 6 months")
        if hasattr(credit_profile, 'negative_factors') and any("tax" in f.lower() for f in (credit_profile.negative_factors or [])):
            conditions.append("Tax compliance to be resolved within 90 days")

        rationale = (
            f"Approved: ${pricing['approved_amount']:,.0f} at {pricing['interest_rate']:.1f}% APR "
            f"over {pricing['tenure_months']} months via {product.lender_id.upper()}/{product.product_name}. "
            f"Monthly payment: ${pricing['monthly_payment']:.2f}. "
            f"Credit score at decision: {credit_profile.credit_score:.3f}"
        )

        expires = datetime.now(timezone.utc) + timedelta(days=30)

        return LoanDecision(
            application_id=application.application_id,
            business_id=application.business_id,
            approved=True,
            decision_type="approved",
            lender_id=product.lender_id,
            product_name=product.product_name,
            approved_amount_usd=pricing["approved_amount"],
            interest_rate_annual_pct=pricing["interest_rate"],
            tenure_months=pricing["tenure_months"],
            collateral_required=product.requires_collateral,
            processing_fee_usd=pricing["processing_fee"],
            monthly_payment_usd=pricing["monthly_payment"],
            conditions=conditions,
            rationale=rationale,
            matched_product=product.product_name,
            credit_score_at_decision=credit_profile.credit_score,
            governance_decision=gov_decision,
            expires_at=expires.isoformat(),
        )

    def _deny_no_product(
        self,
        application: LoanApplication,
        credit_profile: Any,
    ) -> LoanDecision:
        """Build a denial when no product matches."""
        reasons = ["No eligible lending product found for this application"]
        if hasattr(credit_profile, 'negative_factors'):
            reasons.extend(credit_profile.negative_factors[:3])

        return LoanDecision(
            application_id=application.application_id,
            business_id=application.business_id,
            approved=False,
            decision_type="denied",
            rationale="No matching lender product available for the current credit profile and application parameters.",
            rejection_reasons=reasons,
            credit_score_at_decision=credit_profile.credit_score,
        )

    def _deny_pricing(
        self,
        application: LoanApplication,
        credit_profile: Any,
        pricing: Dict[str, Any],
    ) -> LoanDecision:
        """Build a denial when pricing is not viable."""
        reasons = [
            f"Debt service ratio {pricing['debt_service_ratio']:.1%} exceeds maximum 40%",
            f"Monthly payment ${pricing['monthly_payment']:.2f} would exceed 40% of monthly revenue",
        ]
        return LoanDecision(
            application_id=application.application_id,
            business_id=application.business_id,
            approved=False,
            decision_type="denied",
            rationale="Pricing not viable — the monthly payment would exceed the business's capacity to pay.",
            rejection_reasons=reasons,
            credit_score_at_decision=credit_profile.credit_score,
        )

    def _deny_governance(
        self,
        application: LoanApplication,
        credit_profile: Any,
        gov_decision: Optional[Dict[str, Any]] = None,
    ) -> LoanDecision:
        """Build a denial based on governance rejection."""
        rationale = "Governance/compliance checks did not pass."
        if gov_decision:
            rationale = gov_decision.get("rationale", rationale)

        return LoanDecision(
            application_id=application.application_id,
            business_id=application.business_id,
            approved=False,
            decision_type="denied",
            rationale=rationale,
            rejection_reasons=[rationale],
            credit_score_at_decision=credit_profile.credit_score,
            governance_decision=gov_decision,
        )

    # ─── Utilities ───────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get lending engine statistics."""
        total = len(self.decisions)
        approved = sum(1 for d in self.decisions if d.approved)
        total_volume = sum(d.approved_amount_usd for d in self.decisions if d.approved)
        submitted = sum(1 for d in self.decisions if d.lender_response is not None)

        by_lender: Dict[str, int] = {}
        for d in self.decisions:
            if d.lender_id:
                by_lender[d.lender_id] = by_lender.get(d.lender_id, 0) + 1

        return {
            "total_applications": total,
            "approved": approved,
            "denied": total - approved,
            "submitted_to_lender": submitted,
            "approval_rate": round(approved / total, 3) if total > 0 else 0,
            "total_volume_usd": total_volume,
            "by_lender": by_lender,
        }

    # ─── Lender Submission ──────────────────────────────────────────────

    def _submit_to_lender(
        self,
        decision: LoanDecision,
        credit_profile: Any,
        application: LoanApplication,
    ) -> Optional[Any]:
        """Submit an approved decision to the matched lender's API adapter.

        Returns the LenderApplicationResult or None if adapter not found.
        """
        try:
            from carib_clear.broker.lender_base import get_lender
            from carib_clear.broker.lender_base import LenderApplicationRequest

            adapter = get_lender(decision.lender_id, config={"mock_mode": True})
            if adapter is None:
                logger.warning("[LendingEngine] No adapter found for lender '%s'", decision.lender_id)
                return None

            request = LenderApplicationRequest(
                business_id=application.business_id,
                business_name=application.business_name,
                jurisdiction=application.jurisdiction,
                sector=credit_profile.sector_name if hasattr(credit_profile, 'sector_name') else "retail",
                requested_amount_usd=application.requested_amount_usd,
                approved_amount_usd=decision.approved_amount_usd,
                interest_rate_annual_pct=decision.interest_rate_annual_pct,
                tenure_months=decision.tenure_months,
                credit_score=credit_profile.credit_score,
                credit_rating=credit_profile.credit_rating,
                dti_ratio=decision.monthly_payment_usd / max(credit_profile.estimated_annual_revenue_usd / 12, 1),
                operating_months=credit_profile.operating_months,
                collateral_offered_usd=application.collateral_offered_usd,
                purpose=application.purpose,
                reference_id=application.application_id,
            )

            result = adapter.submit_application(request)
            return result

        except Exception as exc:
            logger.error("[LendingEngine] Lender submission failed: %s", exc)
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Quick test / demo
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import random
    random.seed(42)

    logging.basicConfig(level=logging.INFO)

    from carib_clear.agents.data_aggregation import DataAggregationAgent
    from carib_clear.agents.credit_profile import CreditProfileGenerator
    from carib_clear.governance.agent import GovernanceAgent

    # Build the full pipeline
    da = DataAggregationAgent()
    scorer = CreditProfileGenerator()
    governance = GovernanceAgent()
    engine = CashFlowLendingEngine(governance_agent=governance)

    # Generate data and score
    pos_csv = da.generate_mock_pos_csv(months=12, avg_monthly_revenue=15000)
    invoices = da.generate_mock_invoices(count=20)
    bank_stmt = da.generate_mock_bank_statement(months=6, avg_deposit=18000)
    tax_data = da.generate_mock_tax_data("HT")

    profile = da.build_profile(
        business_id="ht_artisan_001",
        business_name="Atelier Kreyol Artisans",
        jurisdiction="HT",
        sector={"sector": "retail", "sub_sector": "handicrafts"},
        pos_csv_content=pos_csv,
        invoice_data=invoices,
        bank_statement_csv=bank_stmt,
        tax_data=tax_data,
    )

    credit = scorer.score(profile)

    # Submit loan applications
    applications = [
        LoanApplication(
            application_id="app-001",
            business_id="ht_artisan_001",
            business_name="Atelier Kreyol Artisans",
            jurisdiction="HT",
            requested_amount_usd=25000,
            purpose="working_capital",
            preferred_tenure_months=18,
        ),
        LoanApplication(
            application_id="app-002",
            business_id="ht_artisan_001",
            business_name="Atelier Kreyol Artisans",
            jurisdiction="HT",
            requested_amount_usd=100000,
            purpose="expansion",
            preferred_tenure_months=36,
        ),
    ]

    print(f"\n{'='*60}")
    for app in applications:
        print(f"\n--- Application: {app.application_id} ---")
        print(f"  Business: {app.business_name}")
        print(f"  Requested: ${app.requested_amount_usd:,.0f} for {app.purpose}")
        print(f"  Tenure: {app.preferred_tenure_months} months")

        decision = engine.evaluate(credit, app)

        status_icon = "✅" if decision.approved else "❌"
        print(f"\n  {status_icon} Decision: {decision.decision_type.upper()}")
        print(f"  Lender: {decision.lender_id or 'N/A'}")
        print(f"  Product: {decision.product_name or 'N/A'}")
        print(f"  Amount: ${decision.approved_amount_usd:,.0f}")
        print(f"  Rate: {decision.interest_rate_annual_pct:.1f}% APR")
        print(f"  Monthly: ${decision.monthly_payment_usd:.2f}")
        print(f"  Collateral: {'Required' if decision.collateral_required else 'Not required'}")
        if decision.rejection_reasons:
            for r in decision.rejection_reasons:
                print(f"  ⚠️  {r[:80]}")
        print(f"  Rationale: {decision.rationale[:120]}")

    print(f"\n{'='*60}")
    print(f"Engine Stats:")
    for k, v in engine.get_stats().items():
        print(f"  {k}: {v}")
