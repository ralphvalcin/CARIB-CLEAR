"""VoiceLoanBridge — natural language loan requests → CARIB-CLEAR pipeline.

Takes voice-transcribed text (English or Kreyòl), extracts structured loan intent,
routes through the full CARIB-CLEAR MSME credit pipeline, and formats the
decision as natural language speech response.

Architecture:
  Voice/Text → IntentExtraction → DataAggregation → CreditProfile
    → CashFlowLending → LenderAdapter → ResponseFormatter → TTS
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from carib_clear.agents.cash_flow_lending import CashFlowLendingEngine, LoanApplication
from carib_clear.agents.credit_profile import CreditProfileGenerator
from carib_clear.agents.data_aggregation import DataAggregationAgent
from carib_clear.governance.agent import GovernanceAgent

logger = logging.getLogger(__name__)

# ─── Supported jurisdictions for voice demo ───────────────────────────
JURISDICTION_MAP = {
    "haiti": "HT", "ayiti": "HT", "ht": "HT",
    "jamaica": "JM", "jamaik": "JM", "jm": "JM",
    "barbados": "BB", "babad": "BB", "bb": "BB",
    "trinidad": "TT", "trinite": "TT", "tt": "TT",
    "eastern caribbean": "ECCB", "ec": "ECCB", "eccb": "ECCB",
}

SECTOR_MAP = {
    "retail": "retail", "magazen": "retail", "boutik": "retail",
    "agriculture": "agriculture", "agrikilti": "agriculture", "farming": "agriculture",
    "services": "services", "sèvis": "services",
    "manufacturing": "manufacturing", "fabrikasyon": "manufacturing",
    "tech": "tech", "technology": "tech", "teknoloji": "tech",
    "handicraft": "retail", "atizana": "retail", "artisan": "retail",
    "restaurant": "retail", "restoran": "retail",
    "transport": "services", "transpò": "services",
    "education": "services", "edikasyon": "services",
}

PURPOSE_MAP = {
    "working capital": "working_capital", "kapital": "working_capital",
    "expansion": "expansion", "expand": "expansion", "elaji": "expansion", "grow": "expansion",
    "inventory": "working_capital", "stòk": "working_capital",
    "equipment": "equipment", "ekipman": "equipment",
    "invoice": "invoice_financing", "fakti": "invoice_financing",
    "trade": "trade_finance", "komès": "trade_finance",
}


@dataclass
class LoanIntent:
    """Structured loan intent extracted from natural language."""

    amount_usd: float
    jurisdiction: str  # "HT", "JM", "BB", "TT", "ECCB"
    sector: str  # "retail", "agriculture", "services", "manufacturing", "tech"
    purpose: str = "working_capital"
    business_name: str = ""
    business_id: str = ""
    confidence: float = 1.0
    raw_text: str = ""
    detected_language: str = "en"  # "en" or "ht"


@dataclass
class VoiceLoanResult:
    """Result of a voice-driven loan request, ready for TTS."""

    success: bool
    approved: bool
    amount_usd: float
    response_text: str  # Natural language response for TTS
    response_text_ht: str = ""  # Kreyòl version
    decision: Any = None
    details: Dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────
# Intent Extraction
# ──────────────────────────────────────────────────────────────────────


class KreyolAmountParser:
    """Parse amount mentions from Kreyòl/English text."""

    # Kreyòl number words
    NUMBERS_HT = {
        "en": 1, "yon": 1, "de": 2, "twa": 3, "kat": 4,
        "senk": 5, "sis": 6, "sèt": 7, "uit": 8, "nèf": 9,
        "dis": 10, "onz": 11, "douz": 12, "trèz": 13, "katòz": 14,
        "kenz": 15, "sèz": 16, "dizsèt": 17, "dizuit": 18, "diznèf": 19,
        "ven": 20, "trant": 30, "karant": 40, "senkant": 50,
        "swasant": 60, "swasanndis": 70, "katreven": 80, "katrevendis": 90,
        "san": 100, "mil": 1000, "milyon": 1000000,
        "mille": 1000, "million": 1000000,
    }

    @classmethod
    def parse_amount(cls, text: str) -> Optional[float]:
        """Extract a dollar amount from text. Handles Kreyòl and English patterns."""

        # Pattern 1: $5,000 or 5000 dollars
        patterns = [
            r'\$[\s]*([\d,]+)',                # $5,000 or $ 5000
            r'([\d,]+)\s*(?:dola|dollar|dollars|usd|goud)',  # 5000 dollars
            r'([\d,]+)\s*(?:dola|dollar|dollars|usd)',         # 5000 USD
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1).replace(",", ""))
                except ValueError:
                    pass

        # Pattern 2: "senk mil dola" (Kreyòl: five thousand dollars)
        words = re.sub(r'[^\w\s]', ' ', text.lower()).split()
        amount = 0.0
        current = 0.0
        found = False
        for word in words:
            if word in cls.NUMBERS_HT:
                val = cls.NUMBERS_HT[word]
                if val >= 1000:
                    current = max(current, 1) * val
                    amount += current
                    current = 0.0
                    found = True
                elif val >= 100:
                    current = max(current, 1) * val
                else:
                    current += val
                    found = True
            elif word in ("dola", "dollar", "dollars"):
                amount += current if current > 0 else 0
                amount = max(amount, 1)  # At least $1
                current = 0.0
                found = True
            else:
                if current > 0:
                    amount += current
                    current = 0.0

        if current > 0:
            amount += current

        return amount if found and amount > 0 else None


def detect_language(text: str) -> str:
    """Detect if text is Haitian Creole or English."""
    kreyol_markers = [
        "mwen", "ou", "li", "nou", "yo", "se", "nan", "pou", "ak", "avèk",
        "pa", "gen", "ap", "pral", "fè", "vle", "bezwen", "kapab", "ka",
        "kreyòl", "ayisyen", "ayiti", "bonjou", "bonswa", "mesi", "tanpri",
        "piske", "depi", "kote", "ki", "kisa", "poukisa", "konbyen",
        "mache", "biznis", "lajan", "travay", "mannman", "papa", "pitit",
    ]
    words = set(re.sub(r'[^\w\s]', ' ', text.lower()).split())
    matches = len(words & set(kreyol_markers))
    # Heuristic: if enough Kreyòl markers, it's Kreyòl
    if matches >= 2 or (matches >= 1 and len(words) <= 5):
        return "ht"
    return "en"


def extract_loan_intent(text: str) -> LoanIntent:
    """Extract structured loan intent from natural language text.

    Uses pattern matching + keyword extraction for the buildathon.
    In production, this would call an LLM for more robust extraction.
    """
    raw = text.strip()
    lang = detect_language(raw)

    # Extract amount
    amount = KreyolAmountParser.parse_amount(raw)
    if amount is None:
        amount = 25000.0  # Default fallback for demo

    # Extract jurisdiction
    jurisdiction = "HT"  # Default
    raw_lower = raw.lower()
    for key, code in JURISDICTION_MAP.items():
        if key in raw_lower:
            jurisdiction = code
            break

    # Extract sector
    sector = "retail"  # Default
    for key, sec in SECTOR_MAP.items():
        if key in raw_lower:
            sector = sec
            break

    # Extract purpose
    purpose = "working_capital"
    for key, purp in PURPOSE_MAP.items():
        if key in raw_lower:
            purpose = purp
            break

    # Extract business name
    biz_name = ""
    biz_patterns = [
        r'(?:biznis|business|company|enterprise|societe|sosyete)\s+(?:mwen|my|nan|a|la|)\s*(?:rele|called|)\s*["\']?([A-Za-z\s]+?)["\']?(?:\s|$|\.)',
        r'(?:rele|called|named)\s+["\']?([A-Za-z\s]+?)["\']?(?:\s|$|\.)',
    ]
    for pat in biz_patterns:
        m = re.search(pat, raw, re.IGNORECASE)
        if m:
            biz_name = m.group(1).strip()
            break

    biz_id = f"voice_{jurisdiction.lower()}_{int(time.time())}"
    if not biz_name:
        biz_name = f"Voice Applicant {jurisdiction}"

    return LoanIntent(
        amount_usd=round(amount, 0),
        jurisdiction=jurisdiction,
        sector=sector,
        purpose=purpose,
        business_name=biz_name,
        business_id=biz_id,
        raw_text=raw,
        detected_language=lang,
    )


# ──────────────────────────────────────────────────────────────────────
# Response Formatting
# ──────────────────────────────────────────────────────────────────────

def format_loan_response(
    approved: bool,
    amount_usd: float,
    interest_rate: float = 12.0,
    lender: str = "",
    tenure_months: int = 18,
    rejection_reason: str = "",
    lang: str = "en",
) -> str:
    """Format a CARIB-CLEAR credit decision as natural language speech response."""

    if approved:
        en = (
            f"Congratulations! Your loan for ${amount_usd:,.0f} has been approved "
            f"at {interest_rate:.1f}% APR through {lender}. "
            f"No collateral required — this is a cash-flow based loan. "
            f"The funds will be available within 5 business days. "
            f"Monthly payments will be approximately "
            f"${_estimate_payment(amount_usd, interest_rate, tenure_months):.2f} "
            f"over {tenure_months} months."
        )
        ht = (
            f"Felisitasyon! Prè ou a $ {amount_usd:,.0f} te apwouve. "
            f"To enterè se {interest_rate:.1f}% chak ane atravè {lender}. "
            f"Ou pa bezwen kolateral — se sou baz lajan k ap antre ou ye a. "
            f"Lajan an ap disponib nan 5 jou travay. "
            f"Pèman mansyèl la pral anviwon "
            f"${_estimate_payment(amount_usd, interest_rate, tenure_months):.2f} "
            f"pandan {tenure_months} mwa."
        )
    else:
        en = (
            f"Unfortunately, your loan request for ${amount_usd:,.0f} "
            f"could not be approved at this time. "
            f"{rejection_reason} "
            f"We encourage you to build your credit profile and try again."
        )
        ht = (
            f"Malerezman, demann prè ou a $ {amount_usd:,.0f} pa t ka apwouve "
            f"kounye a. "
            f"{rejection_reason if rejection_reason else 'Nou ankouraje ou konstwi pwofil kredi ou epi eseye ankò.'} "
        )

    return ht if lang == "ht" else en


def _estimate_payment(principal: float, rate_annual: float, months: int) -> float:
    """Estimate monthly payment using amortization formula."""
    monthly_rate = rate_annual / 100 / 12
    if monthly_rate <= 0:
        return principal / months
    payment = principal * (monthly_rate * (1 + monthly_rate) ** months) / ((1 + monthly_rate) ** months - 1)
    return round(payment, 2)


# ──────────────────────────────────────────────────────────────────────
# VoiceLoanBridge
# ──────────────────────────────────────────────────────────────────────


class VoiceLoanBridge:
    """Bridge between voice/text input and the CARIB-CLEAR lending pipeline.

    Usage:
        bridge = VoiceLoanBridge()
        result = bridge.process_request("Mwen bezwen $5,000 pou biznis mwen")
        print(result.response_text)
    """

    def __init__(self):
        self.data_agent = DataAggregationAgent()
        self.credit_generator = CreditProfileGenerator()
        self.gov_agent = GovernanceAgent()
        self.lending_engine = CashFlowLendingEngine()
        self._history: List[Dict[str, Any]] = []

    def process_request(self, text: str) -> VoiceLoanResult:
        """Process a voice loan request end-to-end.

        Args:
            text: Transcribed text from voice input (English or Kreyòl).

        Returns:
            VoiceLoanResult with response text ready for TTS.
        """
        # 1. Extract intent
        intent = extract_loan_intent(text)
        logger.info(
            "[VoiceLoan] Intent: %s in %s | $%.0f | %s | lang=%s",
            intent.business_name, intent.jurisdiction, intent.amount_usd,
            intent.sector, intent.detected_language,
        )

        # 2. Build business profile with mock financial data
        pos_csv = self.data_agent.generate_mock_pos_csv(months=12)
        invoices = self.data_agent.generate_mock_invoices(count=20)
        bank_csv = self.data_agent.generate_mock_bank_statement(months=6)
        tax_data = self.data_agent.generate_mock_tax_data(intent.jurisdiction)

        profile = self.data_agent.build_profile(
            business_id=intent.business_id,
            business_name=intent.business_name,
            jurisdiction=intent.jurisdiction,
            sector={"sector": intent.sector, "sub_sector": "", "description": ""},
            pos_csv_content=pos_csv,
            invoice_data=invoices,
            bank_statement_csv=bank_csv,
            tax_data=tax_data,
        )
        logger.info(
            "[VoiceLoan] Profile built: rev=$%.0f/yr, stability=%.2f",
            profile.estimated_annual_revenue_usd,
            profile.cash_flow_stability_score,
        )

        # 3. Generate credit score
        credit = self.credit_generator.score(profile)
        logger.info(
            "[VoiceLoan] Credit score: %.3f (%s)",
            credit.credit_score, credit.credit_rating,
        )

        # 4. Apply for loan
        application = LoanApplication(
            application_id=intent.business_id,
            business_id=intent.business_id,
            business_name=intent.business_name,
            jurisdiction=intent.jurisdiction,
            requested_amount_usd=intent.amount_usd,
            purpose=intent.purpose,
            preferred_tenure_months=self._suggest_tenure(intent.amount_usd),
        )

        decision = self.lending_engine.evaluate(credit, application)

        # 5. Format response
        if decision.approved:
            response_text = format_loan_response(
                approved=True,
                amount_usd=decision.approved_amount_usd or intent.amount_usd,
                interest_rate=decision.interest_rate_annual_pct,
                lender=decision.lender_id.upper() if decision.lender_id else "IDB Invest",
                tenure_months=decision.tenure_months,
                lang=intent.detected_language,
            )
            response_text_ht = format_loan_response(
                approved=True,
                amount_usd=decision.approved_amount_usd or intent.amount_usd,
                interest_rate=decision.interest_rate_annual_pct,
                lender=decision.lender_id.upper() if decision.lender_id else "IDB Invest",
                tenure_months=decision.tenure_months,
                lang="ht",
            )
        else:
            reasons = decision.rejection_reasons[:2] if decision.rejection_reasons else []
            reason_str = "; ".join(reasons) if reasons else "Your application does not meet current criteria."
            response_text = format_loan_response(
                approved=False,
                amount_usd=intent.amount_usd,
                rejection_reason=reason_str,
                lang=intent.detected_language,
            )
            response_text_ht = format_loan_response(
                approved=False,
                amount_usd=intent.amount_usd,
                rejection_reason=reason_str,
                lang="ht",
            )

        result = VoiceLoanResult(
            success=True,
            approved=decision.approved,
            amount_usd=intent.amount_usd,
            response_text=response_text,
            response_text_ht=response_text_ht,
            decision=decision,
            details={
                "intent": intent.__dict__,
                "credit_score": credit.credit_score,
                "credit_rating": credit.credit_rating,
                "lender": decision.lender_id,
                "interest_rate": decision.interest_rate_annual_pct,
            },
        )

        self._history.append({
            "text": text,
            "intent": intent.__dict__,
            "approved": decision.approved,
            "timestamp": time.time(),
        })

        return result

    def _suggest_tenure(self, amount_usd: float) -> int:
        """Suggest loan tenure based on amount."""
        if amount_usd <= 10000:
            return 12
        elif amount_usd <= 50000:
            return 18
        else:
            return 36

    def get_history(self) -> List[Dict[str, Any]]:
        return self._history


# ──────────────────────────────────────────────────────────────────────
# Demo
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    samples = [
        "Mwen bezwen $5,000 pou biznis atizana m nan Ayiti",
        "I need $25,000 to expand my restaurant in Jamaica",
        "Hello I would like a $10,000 loan for my farming business in Barbados",
        "Mwen vle $50,000 pou elaji biznis mwen nan Trinidad",
        "$100,000 for tech startup in Haiti please",
    ]

    bridge = VoiceLoanBridge()

    print(f"\n{'='*60}")
    print("Kreyol Voice Loan Bridge — Demo")
    print(f"{'='*60}\n")

    for sample in samples:
        print(f"  🎤 Input: \"{sample}\"")
        result = bridge.process_request(sample)
        status_icon = "✅" if result.approved else "❌"
        print(f"  {status_icon} Decision: {result.response_text[:120]}...")
        print()