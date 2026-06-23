"""Concrete lender adapter implementations for Barita, JMMB, and IDB Invest.

Each adapter simulates the lender's API with realistic response shapes,
processing delays, and business rules. For the buildathon, all run in
mock mode. Production deployments replace the mock methods with real
HTTP calls to each lender's API.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from carib_clear.broker.lender_base import (
    DisbursementResult,
    LenderAdapter,
    LenderApplicationRequest,
    LenderApplicationResult,
    register_lender,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Mock helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mock_tx_hash(prefix: str = "tx") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"

def _mock_lender_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Barita Capital Markets — Jamaica's premier investment bank
# ─────────────────────────────────────────────────────────────────────────────


@register_lender
class BaritaLenderAdapter(LenderAdapter):
    """Barita Capital Markets MSME Lending Adapter.

    Features:
      - Unsecured cash-flow loans up to JMD 15M (~$100K USD)
      - 24-hour decision SLA
      - Same-day disbursement for approved applications
      - API base: https://api.barita.com/msme/v1 (mock)
    """

    lender_id = "barita"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.api_base = self.config.get("api_base", "https://api.barita.com/msme/v1")
        self.api_key = self.config.get("api_key") or self.config.get("BARITA_API_KEY", "")
        self._applications: Dict[str, Dict[str, Any]] = {}

    def submit_application(self, request: LenderApplicationRequest) -> LenderApplicationResult:
        logger.info("[Barita] Submitting application for %s ($%.0f)", request.business_name, request.approved_amount_usd)

        lender_id = _mock_lender_id("BAR")

        # Simulate processing delay
        time.sleep(0.2)

        # Barita's internal rules
        issues = []
        if request.approved_amount_usd > 100000:
            issues.append("Amount exceeds Barita's MSME limit")
        if request.credit_rating in ("C", "D"):
            issues.append("Credit rating below Barita's minimum threshold")
        if request.operating_months < 6:
            issues.append("Minimum 6 months operating history required")

        approved = len(issues) == 0

        self._applications[lender_id] = {
            "request": request,
            "status": "approved" if approved else "denied",
            "issues": issues,
            "submitted_at": _now(),
        }

        return LenderApplicationResult(
            success=approved,
            lender_application_id=lender_id,
            status="approved" if approved else "denied",
            message="Application approved" if approved else f"Denied: {'; '.join(issues)}",
            estimated_decision_time_min=0 if approved else 1440,
            conditions=[] if approved else issues,
            raw_response={"barita_reference": lender_id, "reviewed_by": "Barita Credit Team"},
        )

    def check_status(self, lender_application_id: str) -> LenderApplicationResult:
        app = self._applications.get(lender_application_id)
        if not app:
            return LenderApplicationResult(
                success=False, lender_application_id=lender_application_id,
                status="not_found", message="Application not found",
            )
        return LenderApplicationResult(
            success=app["status"] == "approved",
            lender_application_id=lender_application_id,
            status=app["status"],
            message=f"Application is {app['status']}",
        )

    def disburse(self, lender_application_id: str, amount_usd: float) -> DisbursementResult:
        app = self._applications.get(lender_application_id)
        if not app or app["status"] != "approved":
            return DisbursementResult(
                success=False, amount_usd=amount_usd,
                error_message="Application not approved or not found",
            )
        app["status"] = "disbursed"
        app["disbursed_at"] = _now()
        return DisbursementResult(
            success=True,
            amount_usd=amount_usd,
            tx_hash=_mock_tx_hash("bar"),
            settlement_rail="local_ach_jm",
            estimated_arrival_seconds=3600,
            fee_usd=amount_usd * 0.015,  # 1.5% processing fee
            raw_response={"barita_tx_id": _mock_tx_hash("bar-tx")},
        )

    def cancel_application(self, lender_application_id: str, reason: str = "") -> bool:
        app = self._applications.get(lender_application_id)
        if app and app["status"] in ("pending", "approved"):
            app["status"] = "cancelled"
            app["cancel_reason"] = reason
            return True
        return False

    def health(self) -> bool:
        return True  # Mock: always healthy


# ─────────────────────────────────────────────────────────────────────────────
# JMMB Group — Jamaica Money Market Brokers
# ─────────────────────────────────────────────────────────────────────────────


@register_lender
class JMMBLenderAdapter(LenderAdapter):
    """JMMB Group MSME Lending Adapter.

    Features:
      - Secured loans up to JMD 8M (~$50K USD)
      - Collateral required (75%+ of loan value)
      - 48-hour decision SLA
      - Business mentoring program included
      - API base: https://api.jmmb.com/msme/v2 (mock)
    """

    lender_id = "jmmb"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.api_base = self.config.get("api_base", "https://api.jmmb.com/msme/v2")
        self.api_key = self.config.get("api_key") or self.config.get("JMMB_API_KEY", "")
        self._applications: Dict[str, Dict[str, Any]] = {}

    def submit_application(self, request: LenderApplicationRequest) -> LenderApplicationResult:
        logger.info("[JMMB] Submitting application for %s ($%.0f)", request.business_name, request.approved_amount_usd)

        lender_id = _mock_lender_id("JMMB")
        time.sleep(0.2)

        # JMMB requires collateral
        issues = []
        conditions = []
        if request.collateral_offered_usd < request.approved_amount_usd * 0.75:
            issues.append("Collateral must cover at least 75% of loan amount")
        if request.credit_rating == "D":
            issues.append("Credit rating D not eligible for JMMB MSME products")
        if request.approved_amount_usd > 50000:
            issues.append("JMMB MSME maximum is $50,000")

        if not issues:
            conditions.extend([
                "Collateral documentation required",
                "Business mentoring program enrollment mandatory",
                "Monthly performance reports required",
                "Personal guarantee from business owner",
            ])

        approved = len(issues) == 0

        self._applications[lender_id] = {
            "request": request,
            "status": "approved" if approved else "denied",
            "issues": issues,
            "conditions": conditions,
            "submitted_at": _now(),
        }

        return LenderApplicationResult(
            success=approved,
            lender_application_id=lender_id,
            status="approved" if approved else "denied",
            message="Application approved with conditions" if approved else f"Denied: {'; '.join(issues)}",
            estimated_decision_time_min=1440 if approved else 0,
            conditions=conditions,
            raw_response={"jmmb_reference": lender_id, "underwriter": "JMMB Credit Committee"},
        )

    def check_status(self, lender_application_id: str) -> LenderApplicationResult:
        app = self._applications.get(lender_application_id)
        if not app:
            return LenderApplicationResult(
                success=False, lender_application_id=lender_application_id,
                status="not_found", message="Application not found",
            )
        return LenderApplicationResult(
            success=app["status"] == "approved",
            lender_application_id=lender_application_id,
            status=app["status"],
            message=f"Application is {app['status']}",
        )

    def disburse(self, lender_application_id: str, amount_usd: float) -> DisbursementResult:
        app = self._applications.get(lender_application_id)
        if not app or app["status"] != "approved":
            return DisbursementResult(
                success=False, amount_usd=amount_usd,
                error_message="Application not approved or not found",
            )
        app["status"] = "disbursed"
        app["disbursed_at"] = _now()
        return DisbursementResult(
            success=True,
            amount_usd=amount_usd,
            tx_hash=_mock_tx_hash("jmmb"),
            settlement_rail="local_ach_jm",
            estimated_arrival_seconds=7200,
            fee_usd=amount_usd * 0.02,  # 2% processing fee
            raw_response={"jmmb_tx_id": _mock_tx_hash("jmmb-tx")},
        )

    def cancel_application(self, lender_application_id: str, reason: str = "") -> bool:
        app = self._applications.get(lender_application_id)
        if app and app["status"] in ("pending", "approved"):
            app["status"] = "cancelled"
            return True
        return False

    def health(self) -> bool:
        return True


# ─────────────────────────────────────────────────────────────────────────────
# IDB Invest — Inter-American Development Bank's private sector arm
# ─────────────────────────────────────────────────────────────────────────────


@register_lender
class IDBInvestLenderAdapter(LenderAdapter):
    """IDB Invest Caribbean MSME Lending Adapter.

    Features:
      - Concessional financing for sustainable/green businesses
      - Up to $200K USD, no collateral required
      - Extended tenure up to 60 months
      - Technical assistance included
      - Lower rates (8-14% APR)
      - 5-day decision SLA (more thorough due diligence)
      - API base: https://api.idbinvest.org/msme/caribbean (mock)
    """

    lender_id = "idb_invest"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.api_base = self.config.get("api_base", "https://api.idbinvest.org/msme/caribbean")
        self.api_key = self.config.get("api_key") or self.config.get("IDB_API_KEY", "")
        self._applications: Dict[str, Dict[str, Any]] = {}

    def submit_application(self, request: LenderApplicationRequest) -> LenderApplicationResult:
        logger.info("[IDB Invest] Submitting application for %s ($%.0f)", request.business_name, request.approved_amount_usd)

        lender_id = _mock_lender_id("IDB")
        time.sleep(0.3)  # IDB is slower — more thorough

        # IDB Invest: sustainable/green business criteria
        issues = []
        conditions = []

        # Green/sustainability criteria
        sustainable_sectors = ["agriculture", "services", "tech", "renewable_energy", "eco_tourism"]
        if request.sector not in sustainable_sectors:
            issues.append("Sector must be sustainability/green-aligned for IDB concessional rates")

        if request.credit_rating in ("C", "D"):
            if request.credit_score < 0.45:
                issues.append("Credit score below IDB Invest minimum threshold")

        if request.approved_amount_usd > 200000:
            issues.append("IDB Invest Caribbean MSME maximum is $200,000")

        if request.operating_months < 12:
            issues.append("Minimum 12 months operating history required")

        if not issues:
            conditions.extend([
                "Environmental and social impact report required within 90 days",
                "Quarterly business performance reviews",
                "Funds must align with sustainable development goals",
            ])

        approved = len(issues) == 0

        self._applications[lender_id] = {
            "request": request,
            "status": "under_review" if approved else "denied",
            "issues": issues,
            "conditions": conditions,
            "submitted_at": _now(),
        }

        return LenderApplicationResult(
            success=approved,
            lender_application_id=lender_id,
            status="under_review" if approved else "denied",
            message="Application under review by IDB Invest credit committee" if approved else f"Denied: {'; '.join(issues)}",
            estimated_decision_time_min=7200 if approved else 0,  # 5 days for IDB
            conditions=conditions,
            raw_response={
                "idb_reference": lender_id,
                "review_team": "IDB Invest Caribbean Desk",
                "due_diligence_period_days": 5,
            },
        )

    def check_status(self, lender_application_id: str) -> LenderApplicationResult:
        app = self._applications.get(lender_application_id)
        if not app:
            return LenderApplicationResult(
                success=False, lender_application_id=lender_application_id,
                status="not_found", message="Application not found",
            )
        return LenderApplicationResult(
            success=app["status"] in ("approved", "disbursed"),
            lender_application_id=lender_application_id,
            status=app["status"],
            message=f"Application is {app['status']}",
        )

    def disburse(self, lender_application_id: str, amount_usd: float) -> DisbursementResult:
        app = self._applications.get(lender_application_id)
        if not app or app["status"] not in ("approved",):
            return DisbursementResult(
                success=False, amount_usd=amount_usd,
                error_message="Application must be approved first",
            )
        app["status"] = "disbursed"
        app["disbursed_at"] = _now()
        return DisbursementResult(
            success=True,
            amount_usd=amount_usd,
            tx_hash=_mock_tx_hash("idb"),
            settlement_rail="stellar_usdc",
            estimated_arrival_seconds=300,  # 5 min via Stellar
            fee_usd=amount_usd * 0.005,  # 0.5% (concessional)
            raw_response={"idb_tx_id": _mock_tx_hash("idb-tx"), "settlement_currency": "USDC"},
        )

    def cancel_application(self, lender_application_id: str, reason: str = "") -> bool:
        app = self._applications.get(lender_application_id)
        if app and app["status"] in ("pending", "under_review"):
            app["status"] = "cancelled"
            return True
        return False

    def health(self) -> bool:
        return True
