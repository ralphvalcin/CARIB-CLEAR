"""Structured demo runner — runs CARIB-CLEAR pipeline and returns JSON data.

Replaces the StringIO stdout-capture hack with real structured results
that the API can return as JSON. The CLI output still works for terminal
demos; this module collects the same data but in machine-readable form.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class StepResult:
    """Result of a single demo step."""
    step_number: int
    step_name: str
    status: str  # "running", "complete", "skipped", "failed"
    details: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DemoResult:
    """Structured result from running a CARIB-CLEAR demo."""
    status: str  # "complete", "error"
    layers: List[str]
    steps: List[StepResult]
    metrics: Dict[str, Any]
    duration_seconds: float
    cost_comparison: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "status": self.status,
            "layers": self.layers,
            "steps": [asdict(s) for s in self.steps],
            "metrics": self.metrics,
            "duration_seconds": self.duration_seconds,
            "cost_comparison": self.cost_comparison,
            "errors": self.errors,
        }


@dataclass
class MatchInfo:
    """Info about a matched FX swap."""
    pair: str
    amount_usd: float
    rate: float
    rail: str
    tx_hash: Optional[str] = None
    savings_vs_traditional_pct: float = 0.0
    fee_usd: float = 0.0


@dataclass
class LoanInfo:
    """Info about a loan application result."""
    business_name: str
    amount_usd: float
    approved: bool
    lender: str
    interest_rate_pct: float
    collateral_required: bool
    rejection_reasons: List[str] = field(default_factory=list)


class DemoRunner:
    """Runs CARIB-CLEAR demo steps and collects structured results."""

    def __init__(self, live: bool = False):
        self.live = live
        self.steps: List[StepResult] = []
        self.matches: List[MatchInfo] = []
        self.loans: List[LoanInfo] = []
        self.errors: List[str] = []

    def add_step(self, number: int, name: str) -> StepResult:
        """Start tracking a demo step."""
        step = StepResult(
            step_number=number,
            step_name=name,
            status="running",
        )
        self.steps.append(step)
        return step

    def complete_step(self, step: StepResult, status: str = "complete",
                       details: Optional[List[str]] = None,
                       metrics: Optional[Dict[str, Any]] = None) -> None:
        """Mark a step as complete."""
        step.status = status
        if details:
            step.details = details
        if metrics:
            step.metrics = metrics

    def add_match(self, pair: str, amount: float, rate: float, rail: str,
                   tx_hash: Optional[str] = None,
                   savings_pct: float = 0.0, fee: float = 0.0) -> None:
        """Record an FX match."""
        self.matches.append(MatchInfo(
            pair=pair, amount_usd=amount, rate=rate, rail=rail,
            tx_hash=tx_hash, savings_vs_traditional_pct=savings_pct,
            fee_usd=fee,
        ))

    def add_loan(self, name: str, amount: float, approved: bool, lender: str,
                  rate: float, collateral: bool,
                  reasons: Optional[List[str]] = None) -> None:
        """Record a loan application result."""
        self.loans.append(LoanInfo(
            business_name=name, amount_usd=amount, approved=approved,
            lender=lender, interest_rate_pct=rate, collateral_required=collateral,
            rejection_reasons=reasons or [],
        ))

    def build_result(self, duration: float) -> DemoResult:
        """Build the final structured result."""
        match_count = len(self.matches)
        loan_count = len(self.loans)
        loan_approved = sum(1 for l in self.loans if l.approved)

        # Cost comparison
        cost_comp = None
        if self.matches:
            first = self.matches[0]
            trad_fee = first.amount_usd * 0.08  # 8% traditional
            cost_comp = {
                "traditional_fee_usd": round(trad_fee, 2),
                "carib_clear_fee_usd": round(first.fee_usd, 2),
                "savings_percent": round(first.savings_vs_traditional_pct, 2),
                "time_saved_days": 3,
            }

        return DemoResult(
            status="complete" if not self.errors else "error",
            layers=["fx_swap", "msme_credit"],
            steps=self.steps,
            metrics={
                "matches": str(match_count),
                "volume_fx": f"${sum(m.amount_usd for m in self.matches):,.0f}",
                "volume_credit": f"${sum(l.amount_usd for l in self.loans):,.0f}",
                "approved_loans": str(loan_approved),
                "total_applications": str(loan_count),
                "jurisdictions": "5",
                "currencies": "6",
            },
            duration_seconds=round(duration, 2),
            cost_comparison=cost_comp,
            errors=self.errors,
        )
