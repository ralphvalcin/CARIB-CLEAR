"""TradeFinanceModule — invoice factoring and trade finance for MSMEs.

Invoice factoring allows MSMEs to sell their accounts receivable at a discount
for immediate cash, rather than waiting 30-90 days for customers to pay.

Workflow:
  1. MSME submits unpaid invoices for factoring
  2. Module evaluates invoice quality, debtor credit, and risk
  3. If approved, an advance (70-90% of invoice value) is funded
  4. When the debtor pays, the remaining balance (minus fees) is returned
     to the MSME

This module integrates with the existing DataAggregationAgent's InvoiceRecord
data model and the CashFlowLendingEngine for funding decisions.
"""

from __future__ import annotations

import json
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from carib_clear.agents.data_aggregation import InvoiceRecord

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────────────────────


@dataclass
class FactoringRequest:
    """An invoice submitted for factoring by an MSME."""

    request_id: str
    business_id: str
    business_name: str
    jurisdiction: str
    invoice: InvoiceRecord
    requested_advance_rate: float = 0.85  # 85% default
    submitted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DebtorAssessment:
    """Assessment of the debtor's ability to pay the invoice."""

    debtor_name: str
    credit_score: float  # 0.0-1.0
    payment_reliability: float  # 0.0-1.0 (historical on-time payment rate)
    known_issues: List[str] = field(default_factory=list)
    assessment: str = "pass"  # "pass", "caution", "fail"


@dataclass
class FactoringEvaluation:
    """Evaluation of a factoring request."""

    request_id: str
    approved: bool
    advance_rate: float  # 0.0-1.0 (e.g., 0.85 = 85%)
    advance_amount_usd: float
    discount_fee_pct: float  # Fee percentage (e.g., 3.0 = 3%)
    discount_fee_usd: float
    net_amount_usd: float  # Advance minus fee
    max_tenure_days: int  # Days until repayment expected
    debtor_assessment: DebtorAssessment
    risk_score: float  # 0.0-1.0 (lower = safer)
    rationale: str = ""
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class FactoringAgreement:
    """A funded factoring agreement."""

    agreement_id: str
    request_id: str
    business_id: str
    business_name: str
    invoice_id: str
    debtor_name: str
    invoice_amount_usd: float
    advance_amount_usd: float
    discount_fee_usd: float
    advance_rate: float
    funded_at: str
    expected_settlement_date: str
    status: str = "active"  # "active", "collected", "settled", "defaulted"
    collection_result: Optional[Dict[str, Any]] = None


# ──────────────────────────────────────────────────────────────────────
# TradeFinanceModule
# ──────────────────────────────────────────────────────────────────────


class TradeFinanceModule:
    """Invoice factoring and trade finance engine.

    Evaluates invoices, proposes factoring terms, and manages the
    full lifecycle from submission to settlement.

    Typical advance rates:
      - Excellent debtor (govt, large corp): 90% @ 1-2% fee
      - Good debtor (established MSME): 85% @ 2-3% fee
      - Fair debtor (small business): 75% @ 3-5% fee
      - Risky debtor (startup, thin file): 60-70% @ 5-8% fee
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._requests: List[FactoringRequest] = []
        self._evaluations: Dict[str, FactoringEvaluation] = {}
        self._agreements: Dict[str, FactoringAgreement] = {}
        self._total_funded_usd = 0.0

        # Default parameters
        self.base_advance_rate = self.config.get("base_advance_rate", 0.85)
        self.max_tenure_days = self.config.get("max_tenure_days", 90)
        self.min_invoice_usd = self.config.get("min_invoice_usd", 500)
        self.max_invoice_usd = self.config.get("max_invoice_usd", 200000)

        # Industry risk weights (by sector)
        self.sector_risk: Dict[str, float] = {
            "retail": 0.15,
            "agriculture": 0.20,
            "services": 0.12,
            "manufacturing": 0.18,
            "tech": 0.10,
            "construction": 0.25,
            "energy": 0.15,
            "transport": 0.15,
        }

        # Jurisdiction risk weights
        self.jurisdiction_risk: Dict[str, float] = {
            "BB": 0.08, "JM": 0.10, "TT": 0.10,
            "HT": 0.25, "ECCB": 0.12, "US": 0.05,
        }

    # ─── Invoice Submission ─────────────────────────────────────────

    def submit_invoice(self, business_id: str, business_name: str,
                       jurisdiction: str, invoice: InvoiceRecord) -> FactoringRequest:
        """Submit an invoice for factoring."""
        request = FactoringRequest(
            request_id=f"fact-{uuid.uuid4().hex[:8].upper()}",
            business_id=business_id,
            business_name=business_name,
            jurisdiction=jurisdiction,
            invoice=invoice,
        )
        self._requests.append(request)
        logger.info(
            "[TradeFinance] Invoice submitted: %s | $%.0f from %s | due %s",
            request.request_id, invoice.amount_usd, invoice.counterparty, invoice.due_date,
        )
        return request

    # ─── Evaluation ─────────────────────────────────────────────────

    def evaluate(self, request: FactoringRequest, sector: str = "retail") -> FactoringEvaluation:
        """Evaluate a factoring request and propose terms.

        Factors considered:
          1. Invoice status and aging (overdue = higher risk)
          2. Debtor assessment (credit quality + payment history)
          3. Sector risk (agriculture/construction riskier than tech/services)
          4. Jurisdiction risk (HT > ECCB > JM/TT > BB > US)
          5. Invoice amount (relative to limits)
        """
        invoice = request.invoice

        # 1. Basic validation
        issues = []
        if invoice.status != "pending":
            issues.append(f"Invoice status is '{invoice.status}', not 'pending'")
        if invoice.amount_usd < self.min_invoice_usd:
            issues.append(f"Invoice amount ${invoice.amount_usd:,.0f} below minimum ${self.min_invoice_usd:,.0f}")
        if invoice.amount_usd > self.max_invoice_usd:
            issues.append(f"Invoice amount ${invoice.amount_usd:,.0f} exceeds maximum ${self.max_invoice_usd:,.0f}")

        if issues:
            return FactoringEvaluation(
                request_id=request.request_id,
                approved=False,
                advance_rate=0.0,
                advance_amount_usd=0.0,
                discount_fee_pct=0.0,
                discount_fee_usd=0.0,
                net_amount_usd=0.0,
                max_tenure_days=0,
                debtor_assessment=DebtorAssessment(
                    debtor_name=invoice.counterparty,
                    credit_score=0.0,
                    payment_reliability=0.0,
                    known_issues=issues,
                    assessment="fail",
                ),
                risk_score=1.0,
                rationale="; ".join(issues),
            )

        # 2. Assess the debtor
        debtor = self._assess_debtor(invoice.counterparty, invoice.amount_usd, sector)
        if debtor.assessment == "fail":
            return FactoringEvaluation(
                request_id=request.request_id,
                approved=False,
                advance_rate=0.0,
                advance_amount_usd=0.0,
                discount_fee_pct=0.0,
                discount_fee_usd=0.0,
                net_amount_usd=0.0,
                max_tenure_days=0,
                debtor_assessment=debtor,
                risk_score=1.0,
                rationale=f"Debtor assessment failed: {debtor.known_issues[0] if debtor.known_issues else 'High risk'}",
            )

        # 3. Calculate risk score (0.0 = safe, 1.0 = risky)
        risk_score = self._calculate_risk(invoice, sector, request.jurisdiction, debtor)

        # 4. Determine terms based on risk
        advance_rate, fee_pct, max_days = self._calculate_terms(risk_score, invoice.amount_usd)

        advance_amount = invoice.amount_usd * advance_rate
        discount_fee = advance_amount * (fee_pct / 100)
        net_amount = advance_amount - discount_fee

        evaluation = FactoringEvaluation(
            request_id=request.request_id,
            approved=True,
            advance_rate=advance_rate,
            advance_amount_usd=round(advance_amount, 2),
            discount_fee_pct=fee_pct,
            discount_fee_usd=round(discount_fee, 2),
            net_amount_usd=round(net_amount, 2),
            max_tenure_days=max_days,
            debtor_assessment=debtor,
            risk_score=round(risk_score, 3),
            rationale=(
                f"Advanced ${advance_amount:,.0f} ({(advance_rate*100):.0f}%) of "
                f"${invoice.amount_usd:,.0f} invoice from {invoice.counterparty}. "
                f"Fee: {fee_pct:.1f}% (${discount_fee:.2f}). "
                f"Risk score: {risk_score:.2f}."
            ),
        )
        self._evaluations[request.request_id] = evaluation

        logger.info(
            "[TradeFinance] Evaluation %s: %s | advance=%.0f%% fee=%.1f%% risk=%.2f",
            request.request_id,
            "APPROVED" if evaluation.approved else "DENIED",
            advance_rate * 100, fee_pct, risk_score,
        )
        return evaluation

    def _assess_debtor(self, debtor_name: str, amount_usd: float,
                       sector: str = "retail") -> DebtorAssessment:
        """Assess a debtor's creditworthiness for factoring.

        In production, this would query credit bureaus, trade references,
        and payment history databases. For the buildathon, uses keyword
        heuristics on the debtor name.
        """
        name_lower = debtor_name.lower()
        known_issues = []

        # Check for government entities (lowest risk)
        govt_keywords = ["govt", "government", "ministry", "central bank",
                         "national", "public", "authority", "municipal"]
        is_govt = any(kw in name_lower for kw in govt_keywords)

        # Check for large corporates (low risk)
        large_corp_keywords = ["bank", "limited", "ltd", "inc", "corporation",
                               "corp", "international", "group", "holdings"]
        is_large_corp = any(kw in name_lower for kw in large_corp_keywords)

        # Check for flagged entities
        flagged_keywords = ["disputed", "delinquent", "default", "bankrupt",
                            "liquidation", "receivership"]
        is_flagged = any(kw in name_lower for kw in flagged_keywords)

        if is_flagged:
            return DebtorAssessment(
                debtor_name=debtor_name,
                credit_score=0.2,
                payment_reliability=0.1,
                known_issues=["Debtor flagged: in default/liquidation"],
                assessment="fail",
            )

        # Score based on entity type
        if is_govt:
            credit_score = random.uniform(0.85, 0.98)
            reliability = random.uniform(0.90, 0.99)
        elif is_large_corp:
            credit_score = random.uniform(0.75, 0.92)
            reliability = random.uniform(0.80, 0.95)
        else:
            credit_score = random.uniform(0.50, 0.80)
            reliability = random.uniform(0.50, 0.85)

        assessment = "pass"
        if credit_score < 0.6:
            assessment = "caution"
            known_issues.append("Low credit score")
        if reliability < 0.6:
            assessment = "caution"
            known_issues.append("Low payment reliability")

        return DebtorAssessment(
            debtor_name=debtor_name,
            credit_score=round(credit_score, 3),
            payment_reliability=round(reliability, 3),
            known_issues=known_issues,
            assessment=assessment,
        )

    def _calculate_risk(self, invoice: InvoiceRecord, sector: str,
                        jurisdiction: str, debtor: DebtorAssessment) -> float:
        """Calculate overall risk score for a factoring deal.

        Factors (weighted):
          - Invoice aging: 25% (overdue = higher risk)
          - Debtor credit: 30%
          - Sector risk: 20%
          - Jurisdiction risk: 15%
          - Invoice amount relative to max: 10%
        """
        # Aging factor
        aging_days = invoice.days_outstanding
        aging_factor = min(1.0, aging_days / self.max_tenure_days)

        # If overdue, significantly higher aging factor
        if invoice.status == "overdue":
            aging_factor = min(1.0, aging_factor * 1.5)

        # Debtor credit factor (invert: higher credit score = lower risk)
        debtor_factor = 1.0 - debtor.credit_score

        # Sector risk
        sector_factor = self.sector_risk.get(sector, 0.15)

        # Jurisdiction risk
        jur_factor = self.jurisdiction_risk.get(jurisdiction, 0.15)

        # Amount factor
        amount_factor = min(1.0, invoice.amount_usd / self.max_invoice_usd)

        risk = (
            0.25 * aging_factor +
            0.30 * debtor_factor +
            0.20 * sector_factor +
            0.15 * jur_factor +
            0.10 * amount_factor
        )

        return min(1.0, max(0.0, risk))

    def _calculate_terms(self, risk_score: float, amount_usd: float) -> Tuple[float, float, int]:
        """Calculate factoring terms based on risk score.

        Returns:
            Tuple of (advance_rate, fee_pct, max_tenure_days)
        """
        if risk_score < 0.15:
            advance = 0.92
            fee = 1.5
            days = 60
        elif risk_score < 0.25:
            advance = 0.88
            fee = 2.0
            days = 60
        elif risk_score < 0.35:
            advance = 0.85
            fee = 2.5
            days = 45
        elif risk_score < 0.50:
            advance = 0.80
            fee = 3.5
            days = 45
        elif risk_score < 0.65:
            advance = 0.75
            fee = 5.0
            days = 30
        else:
            advance = 0.65
            fee = 7.0
            days = 30

        # Adjust for larger invoices (better terms)
        if amount_usd >= 50000:
            advance = min(0.95, advance + 0.02)
            fee = max(1.0, fee - 0.5)

        return round(advance, 2), round(fee, 1), days

    # ─── Funding ───────────────────────────────────────────────────

    def fund(self, evaluation: FactoringEvaluation, business_id: str,
             business_name: str) -> Optional[FactoringAgreement]:
        """Fund an approved factoring evaluation."""
        if not evaluation.approved:
            logger.warning("[TradeFinance] Cannot fund rejected evaluation %s", evaluation.request_id)
            return None

        request = next((r for r in self._requests if r.request_id == evaluation.request_id), None)
        if not request:
            logger.warning("[TradeFinance] Request not found for evaluation %s", evaluation.request_id)
            return None

        # Calculate expected settlement date
        from datetime import timedelta
        expected_date = (datetime.now(timezone.utc) + timedelta(days=evaluation.max_tenure_days)).isoformat()

        agreement = FactoringAgreement(
            agreement_id=f"fact-agr-{uuid.uuid4().hex[:8].upper()}",
            request_id=evaluation.request_id,
            business_id=business_id,
            business_name=business_name,
            invoice_id=request.invoice.invoice_id,
            debtor_name=request.invoice.counterparty,
            invoice_amount_usd=request.invoice.amount_usd,
            advance_amount_usd=evaluation.advance_amount_usd,
            discount_fee_usd=evaluation.discount_fee_usd,
            advance_rate=evaluation.advance_rate,
            funded_at=datetime.now(timezone.utc).isoformat(),
            expected_settlement_date=expected_date,
        )
        self._agreements[agreement.agreement_id] = agreement
        self._total_funded_usd += evaluation.advance_amount_usd

        logger.info(
            "[TradeFinance] Funded %s: $%.0f advanced (fee: $%.0f) | due %s",
            agreement.agreement_id, agreement.advance_amount_usd,
            agreement.discount_fee_usd, agreement.expected_settlement_date[:10],
        )
        return agreement

    # ─── Collection ─────────────────────────────────────────────────

    def record_collection(self, agreement_id: str, collected_amount_usd: float,
                          settled: bool = True) -> bool:
        """Record that an invoice has been collected (debtor paid)."""
        agreement = self._agreements.get(agreement_id)
        if not agreement:
            logger.warning("[TradeFinance] Agreement not found: %s", agreement_id)
            return False

        agreement.status = "settled" if settled else "defaulted"
        agreement.collection_result = {
            "collected_amount_usd": collected_amount_usd,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "settled": settled,
        }
        logger.info(
            "[TradeFinance] Collection recorded for %s: collected $%.0f | settled=%s",
            agreement_id, collected_amount_usd, settled,
        )
        return True

    # ─── Statistics ─────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get trade finance engine statistics."""
        active = [a for a in self._agreements.values() if a.status == "active"]
        settled = [a for a in self._agreements.values() if a.status == "settled"]
        defaulted = [a for a in self._agreements.values() if a.status == "defaulted"]

        return {
            "invoices_submitted": len(self._requests),
            "evaluations_completed": len(self._evaluations),
            "approved": sum(1 for e in self._evaluations.values() if e.approved),
            "funded": len(self._agreements),
            "total_funded_usd": self._total_funded_usd,
            "active_agreements": len(active),
            "settled": len(settled),
            "defaulted": len(defaulted),
            "avg_advance_rate": round(
                sum(a.advance_rate for a in self._agreements.values()) / max(len(self._agreements), 1), 3
            ),
            "default_rate": round(
                len(defaulted) / max(len(self._agreements), 1), 3
            ),
        }

    # ─── Mock Data ─────────────────────────────────────────────────

    @staticmethod
    def generate_mock_invoices(business_name: str, count: int = 5) -> List[InvoiceRecord]:
        """Generate mock invoices for the buildathon demo."""
        debtors = [
            ("Jamaica Hotel Association", "JM", 15000, "services"),
            ("Barbados Tourism Authority", "BB", 25000, "services"),
            ("Trinidad Energy Corp", "TT", 50000, "energy"),
            ("Haiti Ministry of Education", "HT", 12000, "services"),
            ("ECCB Treasury Division", "ECCB", 35000, "services"),
            ("Caribbean Airlines Ltd", "TT", 18000, "transport"),
            ("Digicel Jamaica Ltd", "JM", 22000, "tech"),
            ("FirstCaribbean Bank", "BB", 30000, "services"),
            ("National Flour Mills TT", "TT", 14000, "manufacturing"),
            ("Teleco Haiti S.A.", "HT", 8000, "tech"),
        ]

        invoices = []
        for i in range(min(count, len(debtors))):
            name = business_name
            debtor_name, jur, amt, sector = debtors[i]
            idx = i + 1
            invoice = InvoiceRecord(
                invoice_id=f"INV-{name[:4].upper()}-{str(idx).zfill(4)}",
                type="receivable",
                counterparty=debtor_name,
                amount_usd=amt + random.uniform(-1000, 1000),
                issued_date=f"2026-0{random.randint(1, 6):02d}-{random.randint(1, 28):02d}",
                due_date=f"2026-0{random.randint(4, 8):02d}-{random.randint(1, 28):02d}",
                status=random.choices(["pending", "pending", "pending", "overdue"], weights=[60, 20, 15, 5])[0],
                days_outstanding=random.randint(5, 60),
            )
            invoices.append(invoice)
        return invoices


# ──────────────────────────────────────────────────────────────────────
# Demo
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    module = TradeFinanceModule()

    print(f"\n{'='*60}")
    print("Trade Finance Module — Invoice Factoring Demo")
    print(f"{'='*60}")

    # Generate mock invoices for an MSME
    invoices = TradeFinanceModule.generate_mock_invoices("Atelier Kreyol", count=5)

    print(f"\n📄 Invoices submitted: {len(invoices)}")
    print(f"{'Invoice':20s} {'Debtor':30s} {'Amount':>10s} {'Due':>12s} {'Status':>10s}")
    print(f"{'─' * 82}")
    for inv in invoices:
        print(f"{inv.invoice_id:20s} {inv.counterparty:30s} ${inv.amount_usd:>7,.0f} {inv.due_date:>12s} {inv.status:>10s}")

    for inv in invoices:
        print(f"\n{'─' * 60}")
        request_id = ""
        sector = ""

        # Determine sector from debtor
        if "Tourism" in inv.counterparty or "Hotel" in inv.counterparty:
            sector = "services"
        elif "Energy" in inv.counterparty:
            sector = "energy"
        elif "Education" in inv.counterparty:
            sector = "services"
        elif "Treasury" in inv.counterparty:
            sector = "services"
        elif "Airlines" in inv.counterparty:
            sector = "transport"
        elif "Flour" in inv.counterparty:
            sector = "manufacturing"
        elif "Digicel" in inv.counterparty or "Teleco" in inv.counterparty:
            sector = "tech"
        elif "Bank" in inv.counterparty:
            sector = "services"
        else:
            sector = "retail"

        # Extract jurisdiction from debtor name
        jur = "HT"
        if "Jamaica" in inv.counterparty or "Digicel" in inv.counterparty:
            jur = "JM"
        elif "Barbados" in inv.counterparty or "FirstCaribbean" in inv.counterparty:
            jur = "BB"
        elif "Trinidad" in inv.counterparty or "Caribbean Airlines" in inv.counterparty or "National Flour" in inv.counterparty:
            jur = "TT"
        elif "ECCB" in inv.counterparty:
            jur = "ECCB"

        req = module.submit_invoice(
            business_id="voice_atelier_kreyol",
            business_name="Atelier Kreyol Artisans",
            jurisdiction=jur,
            invoice=inv,
        )
        request_id = req.request_id

        evaluation = module.evaluate(req, sector=sector)
        status = "✅ APPROVED" if evaluation.approved else "❌ DENIED"

        print(f"  {status}  |  Invoice: ${inv.amount_usd:,.0f}")
        if evaluation.approved:
            print(f"         Advance: ${evaluation.advance_amount_usd:,.0f} ({(evaluation.advance_rate*100):.0f}%)")
            print(f"         Fee:     ${evaluation.discount_fee_usd:.2f} ({evaluation.discount_fee_pct:.1f}%)")
            print(f"         Net:     ${evaluation.net_amount_usd:,.0f}")
            print(f"         Risk:    {evaluation.risk_score:.2f}")
            print(f"         Debtor:  {evaluation.debtor_assessment.debtor_name} "
                  f"(credit={evaluation.debtor_assessment.credit_score:.2f}, "
                  f"reliab={evaluation.debtor_assessment.payment_reliability:.2f})")

            # Fund
            agreement = module.fund(evaluation, "voice_atelier_kreyol", "Atelier Kreyol Artisans")
            if agreement:
                print(f"         💰 Funded: {agreement.agreement_id} | "
                      f"Due: {agreement.expected_settlement_date[:10]}")

    print(f"\n{'='*60}")
    print("Trade Finance Summary")
    print(f"{'='*60}")
    stats = module.get_stats()
    print(f"  Invoices submitted: {stats['invoices_submitted']}")
    print(f"  Approved:           {stats['approved']}/{stats['evaluations_completed']}")
    print(f"  Funded:             {stats['funded']} agreements")
    print(f"  Total funded:       ${stats['total_funded_usd']:,.0f}")
    print(f"  Active:             {stats['active_agreements']}")
    print(f"  Default rate:       {(stats['default_rate']*100):.1f}%")
