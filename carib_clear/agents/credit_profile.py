"""CreditProfileGenerator — AI cash-flow scoring for MSME lending.

Takes a BusinessProfile from DataAggregationAgent and produces a CreditProfile
with a score, risk factors, recommended loan terms, and explanation.

Uses a transparent rules-based scoring model for the buildathon (5 C's of
credit: Capacity, Character, Collateral, Conditions, Capital). The model
can be swapped for an ML-based scorer (XGBoost/LightGBM) in production.

Each factor is scored 0.0-1.0 and the final score is a weighted combination.
All intermediate scores are recorded so the decision is fully explainable:
"Your capacity score is 0.75 because your average monthly revenue is $X
with a growing trend and stable cash flow."
"""

from __future__ import annotations

import json
import logging
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RiskFactor:
    """A single risk factor that affects the credit score."""

    name: str  # e.g., "low_revenue", "high_overdue_ratio"
    category: str  # "capacity", "character", "collateral", "conditions", "capital"
    impact: float  # -1.0 (negative) to +1.0 (positive)
    weight: float  # 0.0-1.0 contribution to this category
    description: str  # Human-readable explanation
    detail: str = ""  # Specific numbers
    severity: str = "info"  # "positive", "info", "warning", "critical"


@dataclass
class CreditScoreCategory:
    """Score for one of the 5 C's of credit."""

    name: str
    score: float  # 0.0-1.0
    weight: float  # Contribution to final score
    factors: List[RiskFactor] = field(default_factory=list)

    def weighted_contribution(self) -> float:
        return self.score * self.weight


@dataclass
class LoanRecommendation:
    """Recommended loan terms based on credit score."""

    recommended: bool  # True = approve, False = deny
    max_amount_usd: float
    suggested_amount_usd: float
    interest_rate_annual_pct: float
    tenure_months: int
    collateral_required: bool
    rationale: str
    conditions: List[str] = field(default_factory=list)


@dataclass
class CreditProfile:
    """Complete credit profile for an MSME — output of CreditProfileGenerator.

    This is the input to CashFlowLendingEngine for final decisions.
    """

    business_id: str
    business_name: str
    jurisdiction: str

    # Overall score
    credit_score: float  # 0.0-1.0 (poor to excellent)
    credit_score_norm: int = 0  # 0-850 normalized (like FICO)
    credit_rating: str = ""  # "AAA", "AA", "A", "BBB", "BB", "B", "C", "D"

    # Financial snapshot (passed through from BusinessProfile for lending engine)
    estimated_annual_revenue_usd: float = 0.0
    avg_monthly_revenue_usd: float = 0.0
    operating_months: int = 0
    cash_flow_stability_score: float = 0.5
    sector_name: str = "retail"

    # Breakdown
    categories: Dict[str, CreditScoreCategory] = field(default_factory=dict)
    all_risk_factors: List[RiskFactor] = field(default_factory=list)
    positive_factors: List[str] = field(default_factory=list)
    negative_factors: List[str] = field(default_factory=list)
    warning_factors: List[str] = field(default_factory=list)

    # Recommendation
    recommendation: Optional[LoanRecommendation] = None

    # Metadata
    model_version: str = "v1-rules-based"
    data_completeness: float = 0.0
    confidence: float = 0.0
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def summary(self) -> Dict[str, Any]:
        """Return a concise summary dict for API/display."""
        return {
            "business_id": self.business_id,
            "credit_score": self.credit_score,
            "credit_rating": self.credit_rating,
            "recommended": self.recommendation.recommended if self.recommendation else False,
            "max_amount_usd": self.recommendation.max_amount_usd if self.recommendation else 0,
            "suggested_amount_usd": self.recommendation.suggested_amount_usd if self.recommendation else 0,
            "interest_rate": self.recommendation.interest_rate_annual_pct if self.recommendation else 0,
            "positive_factors": len(self.positive_factors),
            "negative_factors": len(self.negative_factors),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Scoring Weights — The 5 C's of Credit
# ─────────────────────────────────────────────────────────────────────────────

# Weights for each category (total = 1.0)
CATEGORY_WEIGHTS = {
    "capacity": 0.40,  # Ability to repay (revenue, cash flow)
    "character": 0.25,  # Willingness to repay (history, compliance)
    "collateral": 0.15,  # Assets and buffers
    "conditions": 0.10,  # External factors (sector, jurisdiction)
    "capital": 0.10,  # Net worth, equity
}

# Sector risk multipliers (1.0 = neutral, <1.0 = higher risk)
SECTOR_RISK = {
    "retail": 0.9,
    "agriculture": 0.7,
    "services": 1.0,
    "manufacturing": 0.85,
    "tech": 1.1,
}

# Jurisdiction stability scores (0.0-1.0)
JURISDICTION_STABILITY = {
    "BB": 0.85,  # Barbados — stable
    "JM": 0.80,  # Jamaica — moderate
    "TT": 0.80,  # Trinidad & Tobago — moderate
    "XCD": 0.75,  # ECCB — stable
    "HT": 0.50,  # Haiti — challenging
}

# Interest rate bands by credit rating
INTEREST_RATES = {
    "AAA": (5.0, 8.0),
    "AA": (8.0, 11.0),
    "A": (11.0, 14.0),
    "BBB": (14.0, 18.0),
    "BB": (18.0, 22.0),
    "B": (22.0, 28.0),
    "C": (28.0, 35.0),
    "D": (35.0, 50.0),
}


# ─────────────────────────────────────────────────────────────────────────────
# CreditProfileGenerator
# ─────────────────────────────────────────────────────────────────────────────


class CreditProfileGenerator:
    """AI cash-flow credit scoring for MSME lending.

    Transforms a BusinessProfile into a CreditProfile with:
    - 5 C's scoring (Capacity, Character, Collateral, Conditions, Capital)
    - Risk factor analysis with explanations
    - Loan amount and interest rate recommendation
    - Credit rating (AAA through D)

    Designed to be replaced by an ML model (XGBoost/LightGBM) in production.
    The `call_ml_model()` method is the swap point.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.use_ml = self.config.get("use_ml", False)
        self.model_path = self.config.get("model_path", "")

    def score(self, profile: Any) -> CreditProfile:
        """Score a business profile and return a CreditProfile.

        Args:
            profile: A BusinessProfile (from DataAggregationAgent).

        Returns:
            CreditProfile with score, risk factors, and recommendation.
        """
        from carib_clear.agents.data_aggregation import BusinessProfile

        if not isinstance(profile, BusinessProfile):
            raise TypeError(f"Expected BusinessProfile, got {type(profile).__name__}")

        logger.info("[CreditProfile] Scoring %s (%s)", profile.business_name, profile.jurisdiction)

        # Score each of the 5 C's
        capacity = self._score_capacity(profile)
        character = self._score_character(profile)
        collateral = self._score_collateral(profile)
        conditions = self._score_conditions(profile)
        capital = self._score_capital(profile)

        categories = {
            "capacity": capacity,
            "character": character,
            "collateral": collateral,
            "conditions": conditions,
            "capital": capital,
        }

        # Calculate weighted final score
        final_score = sum(cat.score * cat.weight for cat in categories.values())
        final_score = round(max(0.0, min(1.0, final_score)), 4)

        # Normalize to 0-850 (FICO-like)
        fico_score = int(round(final_score * 850))

        # Credit rating
        rating = self._get_rating(final_score)

        # Financial pass-through for lending engine
        annual_rev = profile.estimated_annual_revenue_usd
        avg_monthly = profile.avg_monthly_revenue_usd
        op_months = profile.operating_months
        stability = profile.cash_flow_stability_score
        sector_name = profile.sector.sector if hasattr(profile.sector, 'sector') else "retail"

        # Collect all risk factors
        all_factors: List[RiskFactor] = []
        for cat in categories.values():
            all_factors.extend(cat.factors)

        # Separate positive and negative factors
        positive = [f"{f.name}: {f.description}" for f in all_factors if f.impact > 0]
        negative = [f"{f.name}: {f.description}" for f in all_factors if f.impact < 0]
        warnings = [f"{f.name}: {f.description}" for f in all_factors if f.severity in ("warning", "critical")]

        # Data completeness affects confidence
        completeness = profile.data_completeness
        confidence = round(final_score * 0.3 + completeness * 0.7, 3)

        # Generate loan recommendation
        recommendation = self._generate_recommendation(final_score, rating, profile, all_factors)

        credit_profile = CreditProfile(
            business_id=profile.business_id,
            business_name=profile.business_name,
            jurisdiction=profile.jurisdiction,
            credit_score=final_score,
            credit_score_norm=fico_score,
            credit_rating=rating,
            estimated_annual_revenue_usd=annual_rev,
            avg_monthly_revenue_usd=avg_monthly,
            operating_months=op_months,
            cash_flow_stability_score=stability,
            sector_name=sector_name,
            categories=categories,
            all_risk_factors=all_factors,
            positive_factors=positive,
            negative_factors=negative,
            warning_factors=warnings,
            recommendation=recommendation,
            data_completeness=completeness,
            confidence=confidence,
        )

        logger.info(
            "[CreditProfile] %s: score=%.3f (%s), rating=%s, max_loan=$%.0f",
            profile.business_name, final_score, confidence, rating,
            recommendation.max_amount_usd if recommendation else 0,
        )
        return credit_profile

    # ─── 5 C's Scoring ─────────────────────────────────────────────────

    def _score_capacity(self, profile: Any) -> CreditScoreCategory:
        """Score Capacity — ability to repay from revenue and cash flow.

        Factors: revenue level, revenue trend, cash flow stability, invoice health
        """
        factors: List[RiskFactor] = []
        base_score = 0.5

        # 1. Revenue level (higher = better capacity)
        annual = profile.estimated_annual_revenue_usd
        if annual >= 200000:
            rev_score = 0.9
            rev_detail = f"Strong annual revenue: ${annual:,.0f}"
            rev_severity = "positive"
        elif annual >= 100000:
            rev_score = 0.7
            rev_detail = f"Moderate annual revenue: ${annual:,.0f}"
            rev_severity = "info"
        elif annual >= 50000:
            rev_score = 0.5
            rev_detail = f"Low annual revenue: ${annual:,.0f}"
            rev_severity = "info"
        else:
            rev_score = 0.3
            rev_detail = f"Very low annual revenue: ${annual:,.0f}"
            rev_severity = "warning"

        factors.append(RiskFactor(
            name="annual_revenue",
            category="capacity",
            impact=rev_score * 2 - 1,  # Normalize -1 to 1
            weight=0.30,
            description=rev_detail,
            severity=rev_severity,
        ))
        base_score += (rev_score - 0.5) * 0.30

        # 2. Revenue trend
        trend = profile.revenue_trend
        if trend == "growing":
            trend_score = 1.0
            trend_desc = "Revenue is growing month over month"
            trend_severity = "positive"
        elif trend == "stable":
            trend_score = 0.7
            trend_desc = "Revenue is stable"
            trend_severity = "info"
        elif trend == "seasonal":
            trend_score = 0.5
            trend_desc = "Revenue is seasonal (consider flexible repayment)"
            trend_severity = "info"
        else:
            trend_score = 0.3
            trend_desc = "Revenue is declining — higher risk"
            trend_severity = "warning"

        factors.append(RiskFactor(
            name="revenue_trend",
            category="capacity",
            impact=trend_score * 2 - 1,
            weight=0.20,
            description=trend_desc,
            severity=trend_severity,
        ))
        base_score += (trend_score - 0.5) * 0.20

        # 3. Cash flow stability
        stability = profile.cash_flow_stability_score
        if stability >= 0.8:
            stab_severity = "positive"
            stab_desc = f"Excellent cash flow stability: {stability:.2f}"
        elif stability >= 0.5:
            stab_severity = "info"
            stab_desc = f"Adequate cash flow stability: {stability:.2f}"
        else:
            stab_severity = "warning"
            stab_desc = f"Unstable cash flow: {stability:.2f} — erratic revenue pattern"

        factors.append(RiskFactor(
            name="cash_flow_stability",
            category="capacity",
            impact=stability * 2 - 1,
            weight=0.25,
            description=stab_desc,
            severity=stab_severity,
        ))
        base_score += (stability - 0.5) * 0.25

        # 4. Invoice health (overdue ratio)
        inv = profile.invoice_summary
        if inv:
            overdue = inv.overdue_ratio
            if overdue <= 0.1:
                inv_score = 0.9
                inv_desc = f"Excellent payment discipline: only {overdue:.0%} overdue"
                inv_severity = "positive"
            elif overdue <= 0.3:
                inv_score = 0.6
                inv_desc = f"Moderate overdue ratio: {overdue:.0%}"
                inv_severity = "info"
            elif overdue <= 0.5:
                inv_score = 0.4
                inv_desc = f"High overdue ratio: {overdue:.0%} — payment collection issues"
                inv_severity = "warning"
            else:
                inv_score = 0.2
                inv_desc = f"Critical overdue ratio: {overdue:.0%} — likely defaults ahead"
                inv_severity = "critical"

            factors.append(RiskFactor(
                name="invoice_overdue_ratio",
                category="capacity",
                impact=inv_score * 2 - 1,
                weight=0.15,
                description=inv_desc,
                severity=inv_severity,
            ))
            base_score += (inv_score - 0.5) * 0.15

            # Collection period
            collection = inv.avg_collection_period_days
            if collection <= 30:
                coll_desc = f"Fast collection: {collection:.0f} days"
                coll_severity = "positive"
            elif collection <= 60:
                coll_desc = f"Normal collection: {collection:.0f} days"
                coll_severity = "info"
            elif collection <= 90:
                coll_desc = f"Slow collection: {collection:.0f} days — cash tied up"
                coll_severity = "warning"
            else:
                coll_desc = f"Critical collection: {collection:.0f} days — severe cash conversion issues"
                coll_severity = "critical"

            factors.append(RiskFactor(
                name="collection_period",
                category="capacity",
                impact=1.0 - (collection / 120),  # Normalize: >120 days = 0
                weight=0.10,
                description=coll_desc,
                severity=coll_severity,
            ))

        # If no invoice data, apply a penalty for missing data
        if not inv:
            factors.append(RiskFactor(
                name="missing_invoice_data",
                category="capacity",
                impact=-0.2,
                weight=0.25,
                description="No invoice data provided — cannot assess payment discipline",
                severity="warning",
            ))
            base_score -= 0.05

        # Clamp and return
        final = max(0.0, min(1.0, base_score))
        return CreditScoreCategory(
            name="capacity",
            score=round(final, 4),
            weight=CATEGORY_WEIGHTS["capacity"],
            factors=factors,
        )

    def _score_character(self, profile: Any) -> CreditScoreCategory:
        """Score Character — willingness to repay based on history.

        Factors: tax compliance, operating history, data transparency
        """
        factors: List[RiskFactor] = []
        base_score = 0.5

        # 1. Tax compliance
        tax = profile.tax_status
        if tax:
            if tax.tax_filing_status == "compliant":
                tax_score = 0.9
                tax_desc = f"Tax compliant in {tax.jurisdiction} — {tax.years_filed} years filed"
                tax_severity = "positive"
            elif tax.tax_filing_status == "non_filing":
                tax_score = 0.3
                tax_desc = "Tax non-compliant — higher risk of default"
                tax_severity = "critical"
            else:
                tax_score = 0.5
                tax_desc = f"Tax status: {tax.tax_filing_status}"
                tax_severity = "warning"

            factors.append(RiskFactor(
                name="tax_compliance",
                category="character",
                impact=tax_score * 2 - 1,
                weight=0.35,
                description=tax_desc,
                severity=tax_severity,
            ))
            base_score += (tax_score - 0.5) * 0.35

            # Years filed (longer = more established)
            years = tax.years_filed
            if years >= 3:
                yr_severity = "positive"
                yr_desc = f"Well-established: {years} years of tax filings"
            elif years >= 1:
                yr_severity = "info"
                yr_desc = f"New filer: {years} years of tax filings"
            else:
                yr_severity = "warning"
                yr_desc = "No tax filing history"

            factors.append(RiskFactor(
                name="tax_history_years",
                category="character",
                impact=min(1.0, years / 5),
                weight=0.15,
                description=yr_desc,
                severity=yr_severity,
            ))

            if tax.has_penalties:
                factors.append(RiskFactor(
                    name="tax_penalties",
                    category="character",
                    impact=-0.5,
                    weight=0.15,
                    description="Has tax penalties — compliance concern",
                    severity="critical",
                ))
                base_score -= 0.07

        # 2. Operating history
        months = profile.operating_months
        if months >= 36:
            op_score = 0.9
            op_desc = f"Established business: {months} months operating"
            op_severity = "positive"
        elif months >= 12:
            op_score = 0.6
            op_desc = f"Operating {months} months — proving stability"
            op_severity = "info"
        elif months >= 6:
            op_score = 0.4
            op_desc = f"New business: {months} months — higher risk"
            op_severity = "warning"
        else:
            op_score = 0.2
            op_desc = f"Very new: {months} months — limited track record"
            op_severity = "warning"

        factors.append(RiskFactor(
            name="operating_history",
            category="character",
            impact=op_score * 2 - 1,
            weight=0.25,
            description=op_desc,
            severity=op_severity,
        ))
        base_score += (op_score - 0.5) * 0.25

        # 3. Data transparency (willingness to provide information)
        completeness = profile.data_completeness
        if completeness >= 0.75:
            data_score = 0.9
            data_desc = f"High data transparency: {completeness:.0%} of requested data provided"
            data_severity = "positive"
        elif completeness >= 0.5:
            data_score = 0.6
            data_desc = f"Partial data: {completeness:.0%} — more data improves score"
            data_severity = "info"
        elif completeness >= 0.25:
            data_score = 0.4
            data_desc = f"Limited data: {completeness:.0%} — score has lower confidence"
            data_severity = "warning"
        else:
            data_score = 0.2
            data_desc = f"Minimal data: {completeness:.0%} — cannot properly assess"
            data_severity = "critical"

        factors.append(RiskFactor(
            name="data_transparency",
            category="character",
            impact=data_score * 2 - 1,
            weight=0.25,
            description=data_desc,
            severity=data_severity,
        ))
        base_score += (data_score - 0.5) * 0.25

        if not tax:
            factors.append(RiskFactor(
                name="missing_tax_data",
                category="character",
                impact=-0.3,
                weight=0.35,
                description="No tax data provided — cannot verify compliance",
                severity="warning",
            ))
            base_score -= 0.05

        final = max(0.0, min(1.0, base_score))
        return CreditScoreCategory(
            name="character",
            score=round(final, 4),
            weight=CATEGORY_WEIGHTS["character"],
            factors=factors,
        )

    def _score_collateral(self, profile: Any) -> CreditScoreCategory:
        """Score Collateral — financial buffers and assets.

        Factors: bank balances, net receivables, deposit coverage
        """
        factors: List[RiskFactor] = []
        base_score = 0.5

        # 1. Bank balance health
        bank = profile.bank_metrics
        if bank:
            # Minimum balance relative to monthly revenue
            annual = profile.estimated_annual_revenue_usd or 1
            monthly_rev = annual / 12
            balance_coverage = bank.min_balance_3mo_usd / monthly_rev if monthly_rev > 0 else 0

            if balance_coverage >= 3:  # 3+ months of expenses in bank
                bal_score = 0.9
                bal_desc = f"Strong cash reserves: ${bank.min_balance_3mo_usd:,.0f} min balance"
                bal_severity = "positive"
            elif balance_coverage >= 1:
                bal_score = 0.6
                bal_desc = f"Adequate cash reserves: ${bank.min_balance_3mo_usd:,.0f} min balance"
                bal_severity = "info"
            elif balance_coverage >= 0.5:
                bal_score = 0.4
                bal_desc = f"Tight cash reserves: ${bank.min_balance_3mo_usd:,.0f} min balance"
                bal_severity = "warning"
            else:
                bal_score = 0.2
                bal_desc = f"Critical: only ${bank.min_balance_3mo_usd:,.0f} minimum balance"
                bal_severity = "critical"

            factors.append(RiskFactor(
                name="bank_min_balance",
                category="collateral",
                impact=bal_score * 2 - 1,
                weight=0.35,
                description=bal_desc,
                severity=bal_severity,
            ))
            base_score += (bal_score - 0.5) * 0.35

            # NSF history
            if bank.nsf_count > 0:
                nsf_severity = "critical" if bank.nsf_count >= 3 else "warning"
                factors.append(RiskFactor(
                    name="nsf_history",
                    category="collateral",
                    impact=max(-1.0, -bank.nsf_count * 0.15),
                    weight=0.20,
                    description=f"{bank.nsf_count} bounced checks/transactions",
                    severity=nsf_severity,
                ))
                base_score -= min(0.15, bank.nsf_count * 0.03)

            # Deposit trend
            avg_deposit = bank.avg_monthly_deposits_usd
            deposit_ratio = avg_deposit / monthly_rev if monthly_rev > 0 else 0
            if deposit_ratio >= 1.0:
                factors.append(RiskFactor(
                    name="deposit_coverage",
                    category="collateral",
                    impact=0.3,
                    weight=0.15,
                    description=f"Deposits (${avg_deposit:,.0f}/mo) cover monthly revenue",
                    severity="positive",
                ))
                base_score += 0.03
            elif deposit_ratio < 0.5:
                factors.append(RiskFactor(
                    name="deposit_coverage",
                    category="collateral",
                    impact=-0.2,
                    weight=0.15,
                    description=f"Deposits (${avg_deposit:,.0f}/mo) are low vs revenue",
                    severity="warning",
                ))
                base_score -= 0.03

        else:
            factors.append(RiskFactor(
                name="missing_bank_data",
                category="collateral",
                impact=-0.2,
                weight=0.35,
                description="No bank statement data — cannot assess financial buffers",
                severity="warning",
            ))
            base_score -= 0.03

        # 2. Net receivables (if invoices provided)
        inv = profile.invoice_summary
        if inv:
            net_rec = inv.net_receivables_usd
            if net_rec > 0:
                factors.append(RiskFactor(
                    name="net_receivables",
                    category="collateral",
                    impact=min(0.5, net_rec / 50000),
                    weight=0.30,
                    description=f"Positive net receivables: ${net_rec:,.0f}",
                    severity="positive",
                ))
                base_score += min(0.1, net_rec / 100000 * 0.1)
            else:
                factors.append(RiskFactor(
                    name="net_receivables",
                    category="collateral",
                    impact=-0.2,
                    weight=0.30,
                    description=f"Negative net receivables: ${net_rec:,.0f} — owes more than owed",
                    severity="warning",
                ))
                base_score -= 0.03

        final = max(0.0, min(1.0, base_score))
        return CreditScoreCategory(
            name="collateral",
            score=round(final, 4),
            weight=CATEGORY_WEIGHTS["collateral"],
            factors=factors,
        )

    def _score_conditions(self, profile: Any) -> CreditScoreCategory:
        """Score Conditions — external factors affecting the business.

        Factors: sector risk, jurisdiction stability, macro conditions
        """
        factors: List[RiskFactor] = []
        base_score = 0.6

        # 1. Sector risk
        sector = profile.sector.sector if hasattr(profile, 'sector') else "retail"
        sector_mult = SECTOR_RISK.get(sector, 1.0)
        if sector_mult >= 1.0:
            sec_detail = f"Low-risk sector: {sector}"
            sec_severity = "positive"
        elif sector_mult >= 0.8:
            sec_detail = f"Moderate-risk sector: {sector}"
            sec_severity = "info"
        else:
            sec_detail = f"Higher-risk sector: {sector} (exposed to weather/commodity cycles)"
            sec_severity = "warning"

        factors.append(RiskFactor(
            name="sector_risk",
            category="conditions",
            impact=sector_mult - 0.5,
            weight=0.40,
            description=sec_detail,
            severity=sec_severity,
        ))
        base_score += (sector_mult - 0.5) * 0.40

        # 2. Jurisdiction stability
        jur = profile.jurisdiction
        jur_score = JURISDICTION_STABILITY.get(jur, 0.6)
        if jur_score >= 0.8:
            jur_detail = f"Stable jurisdiction: {jur}"
            jur_severity = "positive"
        elif jur_score >= 0.6:
            jur_detail = f"Moderate jurisdiction stability: {jur}"
            jur_severity = "info"
        else:
            jur_detail = f"Challenging jurisdiction: {jur} — higher country risk"
            jur_severity = "warning"

        factors.append(RiskFactor(
            name="jurisdiction_stability",
            category="conditions",
            impact=jur_score * 2 - 1,
            weight=0.35,
            description=jur_detail,
            severity=jur_severity,
        ))
        base_score += (jur_score - 0.5) * 0.35

        # 3. Operating months as a proxy for business maturity
        months = profile.operating_months
        maturity = min(1.0, months / 60)  # 60 months = 5 years = full maturity

        if maturity >= 0.5:
            mat_detail = f"Mature business: {months} months operating"
            mat_severity = "positive"
        else:
            mat_detail = f"Developing business: {months} months operating"
            mat_severity = "info"

        factors.append(RiskFactor(
            name="business_maturity",
            category="conditions",
            impact=maturity * 2 - 1,
            weight=0.25,
            description=mat_detail,
            severity=mat_severity,
        ))
        base_score += (maturity - 0.5) * 0.25

        final = max(0.0, min(1.0, base_score))
        return CreditScoreCategory(
            name="conditions",
            score=round(final, 4),
            weight=CATEGORY_WEIGHTS["conditions"],
            factors=factors,
        )

    def _score_capital(self, profile: Any) -> CreditScoreCategory:
        """Score Capital — net position and equity indicators.

        Factors: net receivables position, revenue-to-debt, bank balance
        """
        factors: List[RiskFactor] = []
        base_score = 0.5

        # 1. Net position (from invoices)
        inv = profile.invoice_summary
        if inv:
            net = inv.net_receivables_usd
            annual = profile.estimated_annual_revenue_usd or 1
            net_to_revenue = net / annual if annual > 0 else 0

            if net_to_revenue > 0.05:  # Net positive >5% of revenue
                cap_detail = f"Healthy capital position: ${net:,.0f} net receivables"
                cap_severity = "positive"
                cap_score = 0.8
            elif net_to_revenue > -0.05:  # Near break-even
                cap_detail = f"Break-even capital position: ${net:,.0f}"
                cap_severity = "info"
                cap_score = 0.5
            else:
                cap_detail = f"Negative capital position: ${net:,.0f} — more owed than owed to"
                cap_severity = "warning"
                cap_score = 0.3

            factors.append(RiskFactor(
                name="net_capital_position",
                category="capital",
                impact=cap_score * 2 - 1,
                weight=0.40,
                description=cap_detail,
                severity=cap_severity,
            ))
            base_score += (cap_score - 0.5) * 0.40

        # 2. Revenue scale (proxy for capital base)
        annual = profile.estimated_annual_revenue_usd
        if annual >= 250000:
            rev_cap = 0.9
            rev_detail = f"Strong revenue base: ${annual:,.0f}"
            rev_severity = "positive"
        elif annual >= 100000:
            rev_cap = 0.6
            rev_detail = f"Moderate revenue base: ${annual:,.0f}"
            rev_severity = "info"
        elif annual >= 50000:
            rev_cap = 0.4
            rev_detail = f"Small revenue base: ${annual:,.0f}"
            rev_severity = "info"
        else:
            rev_cap = 0.2
            rev_detail = f"Micro revenue base: ${annual:,.0f}"
            rev_severity = "warning"

        factors.append(RiskFactor(
            name="revenue_capital_base",
            category="capital",
            impact=rev_cap * 2 - 1,
            weight=0.35,
            description=rev_detail,
            severity=rev_severity,
        ))
        base_score += (rev_cap - 0.5) * 0.35

        # 3. Bank balance as capital buffer
        bank = profile.bank_metrics
        if bank:
            avg_bal = bank.avg_balance_3mo_usd
            monthly_rev = annual / 12 if annual > 0 else 1
            bal_months = avg_bal / monthly_rev if monthly_rev > 0 else 0

            if bal_months >= 2:
                bal_detail = f"Strong capital buffer: {bal_months:.1f} months of revenue in bank"
                bal_severity = "positive"
            elif bal_months >= 1:
                bal_detail = f"Adequate capital buffer: {bal_months:.1f} months in bank"
                bal_severity = "info"
            else:
                bal_detail = f"Thin capital buffer: {bal_months:.1f} months in bank"
                bal_severity = "warning"

            factors.append(RiskFactor(
                name="bank_capital_buffer",
                category="capital",
                impact=min(0.5, bal_months * 0.2),
                weight=0.25,
                description=bal_detail,
                severity=bal_severity,
            ))

        final = max(0.0, min(1.0, base_score))
        return CreditScoreCategory(
            name="capital",
            score=round(final, 4),
            weight=CATEGORY_WEIGHTS["capital"],
            factors=factors,
        )

    # ─── Rating & Recommendation ───────────────────────────────────────

    @staticmethod
    def _get_rating(score: float) -> str:
        """Convert a 0.0-1.0 score to a credit rating."""
        if score >= 0.90:
            return "AAA"
        elif score >= 0.80:
            return "AA"
        elif score >= 0.70:
            return "A"
        elif score >= 0.60:
            return "BBB"
        elif score >= 0.50:
            return "BB"
        elif score >= 0.40:
            return "B"
        elif score >= 0.25:
            return "C"
        else:
            return "D"

    def _generate_recommendation(
        self,
        score: float,
        rating: str,
        profile: Any,
        factors: List[RiskFactor],
    ) -> LoanRecommendation:
        """Generate loan recommendation based on credit score.

        Loan amounts are based on a percentage of annual revenue.
        Interest rates are based on credit rating.
        """
        annual = profile.estimated_annual_revenue_usd

        # Calculate max loan as % of annual revenue
        if rating in ("AAA", "AA"):
            max_loan_pct = 0.50  # 50% of annual revenue
            suggested_pct = 0.35
        elif rating in ("A", "BBB"):
            max_loan_pct = 0.35
            suggested_pct = 0.25
        elif rating in ("BB", "B"):
            max_loan_pct = 0.20
            suggested_pct = 0.15
        else:
            max_loan_pct = 0.10
            suggested_pct = 0.05

        max_amount = round(annual * max_loan_pct, -2)  # Round to nearest 100
        suggested_amount = round(annual * suggested_pct, -2)

        # Interest rate from rating bands
        rate_range = INTEREST_RATES.get(rating, (15.0, 25.0))
        # Use score within rating to pick rate
        rating_score = score % 0.10 / 0.10  # 0.0-1.0 within rating band
        interest_rate = round(rate_range[0] + (rate_range[1] - rate_range[0]) * (1 - rating_score), 1)

        # Tenure based on risk
        if rating in ("AAA", "AA", "A"):
            tenure = 24  # 24 months
            collateral = False
        elif rating in ("BBB", "BB"):
            tenure = 18
            collateral = score < 0.65
        elif rating == "B":
            tenure = 12
            collateral = True
        else:
            tenure = 6
            collateral = True

        # Check for critical risk factors that should block approval
        critical_factors = [f for f in factors if f.severity == "critical"]
        approve = rating not in ("C", "D") and len(critical_factors) <= 1

        # Build conditions
        conditions = []
        if collateral:
            conditions.append("Collateral required (personal guarantee or asset pledge)")
        if rating in ("BB", "B"):
            conditions.append("Monthly repayment schedule")
        if rating == "B":
            conditions.append("Business mentoring program enrollment required")
        if any(f.name == "tax_compliance" for f in factors if f.impact < 0):
            conditions.append("Tax compliance must be resolved within 90 days")
        if any(f.name == "nsf_history" for f in factors):
            conditions.append("Separate business bank account required")

        # Build rationale
        if approve:
            rationale = (
                f"Credit score {score:.3f} ({rating}) — recommended for "
                f"${suggested_amount:,.0f} at {interest_rate}% APR over {tenure} months."
            )
        else:
            top_warnings = [f.description for f in factors if f.severity in ("warning", "critical")][:3]
            rationale = (
                f"Credit score {score:.3f} ({rating}) — not recommended. "
                f"Key concerns: {'; '.join(top_warnings)}"
            )

        return LoanRecommendation(
            recommended=approve,
            max_amount_usd=max_amount,
            suggested_amount_usd=suggested_amount,
            interest_rate_annual_pct=interest_rate,
            tenure_months=tenure,
            collateral_required=collateral,
            rationale=rationale,
            conditions=conditions,
        )

    # ─── ML Model Interface (for future use) ──────────────────────────

    def call_ml_model(self, profile: Any) -> float:
        """Call an ML model for scoring (future).

        In production, replace this with:
        - XGBoost/LightGBM model loaded from model_path
        - Feature vector built from BusinessProfile
        - Returns a score 0.0-1.0

        For the buildathon, falls back to rules-based scoring.
        """
        logger.info("[CreditProfile] ML model not enabled — using rules-based scoring")
        return self.score(profile).credit_score

    def prepare_ml_features(self, profile: Any) -> Dict[str, float]:
        """Prepare feature vector for ML model.

        Returns a flat dict of numeric features that an ML model can consume.
        """
        features = {
            "avg_monthly_revenue_usd": profile.avg_monthly_revenue_usd,
            "estimated_annual_revenue_usd": profile.estimated_annual_revenue_usd,
            "operating_months": profile.operating_months,
            "cash_flow_stability": profile.cash_flow_stability_score,
            "data_completeness": profile.data_completeness,
            "revenue_trend_growing": 1.0 if profile.revenue_trend == "growing" else 0.0,
            "revenue_trend_declining": 1.0 if profile.revenue_trend == "declining" else 0.0,
        }

        if profile.invoice_summary:
            inv = profile.invoice_summary
            features.update({
                "overdue_ratio": inv.overdue_ratio,
                "avg_collection_days": inv.avg_collection_period_days,
                "net_receivables_usd": inv.net_receivables_usd,
                "invoice_count": inv.invoice_count,
            })

        if profile.bank_metrics:
            bank = profile.bank_metrics
            features.update({
                "avg_deposits_usd": bank.avg_monthly_deposits_usd,
                "avg_withdrawals_usd": bank.avg_monthly_withdrawals_usd,
                "min_balance_usd": bank.min_balance_3mo_usd,
                "avg_balance_usd": bank.avg_balance_3mo_usd,
                "deposit_volatility": bank.deposit_volatility,
                "nsf_count": bank.nsf_count,
                "cf_pattern_stable": 1.0 if bank.cash_flow_pattern == "stable" else 0.0,
                "cf_pattern_erratic": 1.0 if bank.cash_flow_pattern == "erratic" else 0.0,
            })

        if profile.tax_status:
            features.update({
                "tax_years_filed": profile.tax_status.years_filed,
                "tax_compliant": 1.0 if profile.tax_status.tax_filing_status == "compliant" else 0.0,
                "has_penalties": 1.0 if profile.tax_status.has_penalties else 0.0,
            })

        return features


# ─────────────────────────────────────────────────────────────────────────────
# Quick test / demo
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    from carib_clear.agents.data_aggregation import DataAggregationAgent

    # Generate mock data and build profile
    da = DataAggregationAgent()
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

    # Score it
    scorer = CreditProfileGenerator()
    credit = scorer.score(profile)

    print(f"\n{'='*60}")
    print(f"Credit Profile: {credit.business_name}")
    print(f"{'='*60}")
    print(f"  Score: {credit.credit_score:.4f} (FICO: {credit.credit_score_norm})")
    print(f"  Rating: {credit.credit_rating}")
    print(f"  Confidence: {credit.confidence:.2%}")
    print()
    print(f"  5 C's Breakdown:")
    for name, cat in sorted(credit.categories.items()):
        bar = "█" * int(cat.score * 20) + "░" * (20 - int(cat.score * 20))
        print(f"    {name:12s}: [{bar}] {cat.score:.3f} (weight: {cat.weight:.0%})")

    if credit.recommendation:
        r = credit.recommendation
        print(f"\n  Recommendation:")
        print(f"    {'✅ APPROVED' if r.recommended else '❌ DENIED'}")
        print(f"    Suggested Loan: ${r.suggested_amount_usd:,.0f}")
        print(f"    Max Loan: ${r.max_amount_usd:,.0f}")
        print(f"    Interest Rate: {r.interest_rate_annual_pct:.1f}% APR")
        print(f"    Tenure: {r.tenure_months} months")
        print(f"    Collateral: {'Required' if r.collateral_required else 'Not required'}")
        print(f"    Rationale: {r.rationale}")

    print(f"\n  Positive Factors ({len(credit.positive_factors)}):")
    for f in credit.positive_factors[:5]:
        print(f"    ✅ {f[:80]}")
    print(f"\n  Negative Factors ({len(credit.negative_factors)}):")
    for f in credit.negative_factors[:5]:
        print(f"    ⚠️  {f[:80]}")

    if credit.warning_factors:
        print(f"\n  ⚠️  Warnings ({len(credit.warning_factors)}):")
        for f in credit.warning_factors:
            print(f"    🔴 {f}")
