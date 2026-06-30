"""LenderAdapter base class — standard interface for MSME lender integrations.

Each lender (Barita, JMMB, IDB Invest) implements this ABC to provide
a uniform interface for loan application, status checking, and disbursement.

For the buildathon, adapters run in mock mode with realistic response shapes.
Production deployment would swap mock methods for real API calls.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class LenderApplicationRequest:
    """Payload sent to a lender when submitting a loan application."""

    business_id: str
    business_name: str
    jurisdiction: str
    sector: str
    requested_amount_usd: float
    approved_amount_usd: float
    interest_rate_annual_pct: float
    tenure_months: int
    credit_score: float
    credit_rating: str
    dti_ratio: float  # Debt-to-income
    operating_months: int
    collateral_offered_usd: float = 0.0
    purpose: str = "working_capital"
    reference_id: str = ""  # CARIB-CLEAR's internal reference
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LenderApplicationResult:
    """Response from a lender after submitting an application."""

    success: bool
    lender_application_id: str  # Lender's internal ID
    status: str  # "pending", "approved", "denied", "under_review", "disbursed"
    message: str = ""
    estimated_decision_time_min: int = 30
    conditions: List[str] = field(default_factory=list)
    raw_response: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DisbursementResult:
    """Result of a loan disbursement."""

    success: bool
    amount_usd: float
    tx_hash: str = ""
    settlement_rail: str = ""
    estimated_arrival_seconds: int = 0
    fee_usd: float = 0.0
    error_message: str = ""
    raw_response: Dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Base Adapter
# ─────────────────────────────────────────────────────────────────────────────


class LenderAdapter(ABC):
    """Abstract base for all lender integrations.

    Each lender implements:
      - submit_application  — push an approved loan to the lender
      - check_status         — poll application status
      - disburse             — trigger fund release
      - cancel_application   — withdraw an application
      - health               — is the lender API reachable?
    """

    lender_id: str = ""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.mock_mode = self.config.get("mock_mode", True)
        self._submissions: Dict[str, Any] = {}

    @abstractmethod
    def submit_application(self, request: LenderApplicationRequest) -> LenderApplicationResult:
        """Submit a loan application to the lender."""

    @abstractmethod
    def check_status(self, lender_application_id: str) -> LenderApplicationResult:
        """Check the status of a submitted application."""

    @abstractmethod
    def disburse(self, lender_application_id: str, amount_usd: float) -> DisbursementResult:
        """Trigger fund disbursement for an approved application."""

    @abstractmethod
    def cancel_application(self, lender_application_id: str, reason: str = "") -> bool:
        """Cancel/withdraw a pending application."""

    @abstractmethod
    def health(self) -> bool:
        """Check if the lender API is operational."""

    def name(self) -> str:
        """Human-readable lender name."""
        return self.lender_id.replace("_", " ").title()


# ─────────────────────────────────────────────────────────────────────────────
# Lender Adapter Registry
# ─────────────────────────────────────────────────────────────────────────────

# Singleton registry of all lender adapters
_lender_registry: Dict[str, type] = {}

logger = logging.getLogger(__name__)


def register_lender(cls: type) -> type:
    """Decorator to register a lender adapter class (legacy + plugin system)."""
    if hasattr(cls, "lender_id") and cls.lender_id:
        _lender_registry[cls.lender_id] = cls
        # Also register with the new plugin system (lazy import to avoid cycles)
        try:
            from carib_clear.plugin import PluginSpec

            PluginSpec.register(cls.lender_id, {
                "type": "lender",
                "id": cls.lender_id,
                "name": getattr(cls, "lender_name", cls.lender_id),
                "jurisdictions": getattr(cls, "jurisdictions", []),
                "currencies": getattr(cls, "currencies", []),
                "max_loan_usd": getattr(cls, "max_loan_usd", 500000),
                "requires_collateral": getattr(cls, "requires_collateral", False),
                "description": getattr(cls, "lender_description", f"{cls.lender_id} lender adapter"),
            })(cls)
        except ImportError:
            pass
    return cls


def get_lender(lender_id: str, config: Optional[Dict[str, Any]] = None) -> Optional[LenderAdapter]:
    """Get an instance of a registered lender adapter."""
    cls = _lender_registry.get(lender_id)
    if cls:
        return cls(config=config)
    return None


def list_lenders() -> Dict[str, type]:
    """List all registered lender adapters."""
    return dict(_lender_registry)
