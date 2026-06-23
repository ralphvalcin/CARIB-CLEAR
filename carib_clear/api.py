"""CARIB-CLEAR REST API — FastAPI server for the buildathon demo.

Launches a web server exposing all CARIB-CLEAR functionality as REST endpoints.
Auto-generates Swagger docs at /docs.

Usage:
    python -m carib_clear.api
    # or
    uvicorn carib_clear.api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import random
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

app = FastAPI(
    title="CARIB-CLEAR API",
    description="CARICOM FX Swap Network + MSME Credit Layer — Agentic financial infrastructure for the Caribbean",
    version="0.1.0-buildathon",
)

# Allow CORS for browser-based demos
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static dashboard
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/dashboard", response_class=HTMLResponse, tags=["UI"])
async def dashboard():
    """Serve the CARIB-CLEAR web dashboard."""
    html_path = static_dir / "dashboard.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(), status_code=200)
    return HTMLResponse("<h1>Dashboard not found</h1><p>Run from the carib_clear directory.</p>", status_code=404)


# ──────────────────────────────────────────────────────────────────────
# Request/Response Models
# ──────────────────────────────────────────────────────────────────────


class LoanRequest(BaseModel):
    """Loan application submitted via API."""
    business_name: str = Field(..., description="Business name", json_schema_extra={"example": "Atelier Kreyol Artisans"})
    jurisdiction: str = Field(..., description="ISO jurisdiction code", json_schema_extra={"example": "HT"})
    amount_usd: float = Field(..., gt=0, description="Requested amount in USD", json_schema_extra={"example": 25000})
    sector: str = Field("retail", description="Business sector", json_schema_extra={"example": "retail"})
    purpose: str = Field("working_capital", description="Loan purpose", json_schema_extra={"example": "working_capital"})
    months: int = Field(18, ge=1, le=60, description="Preferred tenure in months")


class LoanResponse(BaseModel):
    """Loan decision response."""
    application_id: str
    approved: bool
    amount_usd: float
    interest_rate_pct: float
    lender: str
    tenure_months: int
    message: str
    credit_score: float
    credit_rating: str


class DemoResponse(BaseModel):
    """Demo execution response."""
    status: str
    layers: List[str]
    metrics: Dict[str, Any]
    duration_seconds: float
    html_output: str  # Pre-formatted for display


class ComplianceOnboardRequest(BaseModel):
    """Participant onboarding request."""
    participant_id: str
    jurisdiction: str
    documents: Dict[str, str]


class TransactionScreenRequest(BaseModel):
    """Transaction screening request."""
    from_participant: str
    to_participant: str
    amount_usd: float
    currency: str = "USD"
    purpose: str = "trade"


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    uptime_seconds: float
    agents_ready: bool


# ──────────────────────────────────────────────────────────────────────
# State
# ──────────────────────────────────────────────────────────────────────

_start_time = time.time()
_loan_history: List[Dict[str, Any]] = []
_demo_cache: Dict[str, str] = {}


def _get_demo_class() -> Any:
    """Lazy-import the demo module to avoid circular imports at module level."""
    import importlib
    mod = importlib.import_module("carib_clear.demo")
    return mod


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@app.get("/", tags=["Info"])
@app.get("/health", response_model=HealthResponse, tags=["Info"])
async def health():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version="0.1.0-buildathon",
        uptime_seconds=round(time.time() - _start_time, 2),
        agents_ready=True,
    )


@app.get("/demo/fx_swap", response_model=DemoResponse, tags=["Demo"])
async def demo_fx_swap():
    """Run the Layer 1 FX Swap Network demo."""
    from io import StringIO
    import sys

    demo = _get_demo_class()
    old_stdout = sys.stdout
    sys.stdout = buf = StringIO()

    try:
        t0 = time.time()
        demo.run_fx_swap_demo()
        duration = time.time() - t0
        output = buf.getvalue()
    finally:
        sys.stdout = old_stdout

    return DemoResponse(
        status="complete",
        layers=["fx_swap"],
        metrics={"matches": "1", "volume": "$50,000", "participants": "4"},
        duration_seconds=round(duration, 2),
        html_output=f"<pre>{output[:5000]}</pre>",
    )


@app.get("/demo/msme_credit", response_model=DemoResponse, tags=["Demo"])
async def demo_msme_credit():
    """Run the Layer 2 MSME Credit demo."""
    from io import StringIO
    import sys

    demo = _get_demo_class()
    old_stdout = sys.stdout
    sys.stdout = buf = StringIO()

    try:
        t0 = time.time()
        demo.run_msme_credit_demo()
        duration = time.time() - t0
        output = buf.getvalue()
    finally:
        sys.stdout = old_stdout

    return DemoResponse(
        status="complete",
        layers=["msme_credit"],
        metrics={"applications": "2", "approved": "2", "volume": "$125,000"},
        duration_seconds=round(duration, 2),
        html_output=f"<pre>{output[:5000]}</pre>",
    )


@app.get("/demo/full", response_model=DemoResponse, tags=["Demo"])
async def demo_full():
    """Run the full pipeline (Layer 1 + Layer 2)."""
    from io import StringIO
    import sys

    demo = _get_demo_class()
    old_stdout = sys.stdout
    sys.stdout = buf = StringIO()

    try:
        t0 = time.time()
        demo.run_full_demo()
        duration = time.time() - t0
        output = buf.getvalue()
    finally:
        sys.stdout = old_stdout

    return DemoResponse(
        status="complete",
        layers=["fx_swap", "msme_credit"],
        metrics={
            "matches": "1",
            "volume_fx": "$50,000",
            "volume_credit": "$125,000",
            "total": "$175,000",
        },
        duration_seconds=round(duration, 2),
        html_output=f"<pre>{output[:8000]}</pre>",
    )


@app.post("/loan/apply", response_model=LoanResponse, tags=["Lending"])
async def apply_for_loan(request: LoanRequest):
    """Submit a loan application through the full CARIB-CLEAR credit pipeline."""
    from carib_clear.agents.data_aggregation import DataAggregationAgent
    from carib_clear.agents.credit_profile import CreditProfileGenerator
    from carib_clear.agents.cash_flow_lending import CashFlowLendingEngine, LoanApplication
    from carib_clear.governance.agent import GovernanceAgent

    app_id = f"api-{uuid.uuid4().hex[:8].upper()}"

    try:
        # 1. Build profile from mock data
        data_agent = DataAggregationAgent()
        pos_csv = data_agent.generate_mock_pos_csv(months=12)
        invoices = data_agent.generate_mock_invoices(count=20)
        bank_csv = data_agent.generate_mock_bank_statement(months=6)
        tax_data = data_agent.generate_mock_tax_data(request.jurisdiction)

        profile = data_agent.build_profile(
            business_id=app_id,
            business_name=request.business_name,
            jurisdiction=request.jurisdiction,
            sector={"sector": request.sector, "sub_sector": "", "description": ""},
            pos_csv_content=pos_csv,
            invoice_data=invoices,
            bank_statement_csv=bank_csv,
            tax_data=tax_data,
        )

        # 2. Score
        scorer = CreditProfileGenerator()
        credit = scorer.score(profile)

        # 3. Evaluate
        gov = GovernanceAgent()
        engine = CashFlowLendingEngine()
        application = LoanApplication(
            application_id=app_id,
            business_id=app_id,
            business_name=request.business_name,
            jurisdiction=request.jurisdiction,
            requested_amount_usd=request.amount_usd,
            purpose=request.purpose,
            preferred_tenure_months=request.months,
        )
        decision = engine.evaluate(credit, application)

        # 4. Record
        record = {
            "application_id": app_id,
            "business_name": request.business_name,
            "amount_usd": request.amount_usd,
            "approved": decision.approved,
            "lender": decision.lender_id or "none",
            "interest_rate": decision.interest_rate_annual_pct,
            "credit_score": credit.credit_score,
            "credit_rating": credit.credit_rating,
            "timestamp": time.time(),
        }
        _loan_history.append(record)

        if decision.approved:
            message = (
                f"Approved! ${decision.approved_amount_usd:,.0f} at "
                f"{decision.interest_rate_annual_pct:.1f}% APR through "
                f"{decision.lender_id.upper()}. "
                f"{'No collateral required.' if not decision.collateral_required else 'Collateral required.'}"
            )
        else:
            message = f"Declined: No eligible lending product found"

        return LoanResponse(
            application_id=app_id,
            approved=decision.approved,
            amount_usd=decision.approved_amount_usd or request.amount_usd,
            interest_rate_pct=decision.interest_rate_annual_pct,
            lender=decision.lender_id.upper() if decision.lender_id else "N/A",
            tenure_months=decision.tenure_months,
            message=message,
            credit_score=credit.credit_score,
            credit_rating=credit.credit_rating,
        )

    except Exception as exc:
        logger.exception("Loan application failed")
        raise HTTPException(status_code=500, detail=f"Processing error: {exc}")


@app.get("/loan/applications", tags=["Lending"])
async def list_applications(limit: int = 10):
    """List recent loan applications."""
    return {"applications": _loan_history[-limit:]}


@app.get("/loan/status/{application_id}", tags=["Lending"])
async def get_loan_status(application_id: str):
    """Get status of a specific loan application."""
    for app in _loan_history:
        if app["application_id"] == application_id:
            return app
    raise HTTPException(status_code=404, detail="Application not found")


@app.get("/liquidity/state", tags=["Market"])
async def get_liquidity_state():
    """Get current liquidity pool state."""
    from carib_clear.agents.liquidity_pools import LiquidityPoolManager

    lp = LiquidityPoolManager()
    lp.generate_mock_providers()
    return lp.get_stats()


@app.get("/compliance/jurisdictions", tags=["Compliance"])
async def list_jurisdictions():
    """List supported jurisdictions and their regulators."""
    from carib_clear.agents.compliance import JURISDICTION_RULES

    return {
        jur: {
            "regulator": rules["regulator"],
            "required_docs": rules["kyc_required"],
            "sanctions_lists": rules["sanctions_lists"],
        }
        for jur, rules in JURISDICTION_RULES.items()
    }


@app.get("/compliance/profile/{participant_id}", tags=["Compliance"])
async def get_compliance_profile(participant_id: str):
    """Get compliance profile for a participant."""
    from carib_clear.agents.compliance import ComplianceAgent

    agent = ComplianceAgent()
    profile = agent.profiles.get(participant_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Participant not found")
    return profile


@app.post("/compliance/onboard", tags=["Compliance"])
async def onboard_participant(request: ComplianceOnboardRequest):
    """Onboard a new participant with KYC documents."""
    from carib_clear.agents.compliance import ComplianceAgent

    agent = ComplianceAgent()
    result = agent.onboard_participant(
        participant_id=request.participant_id,
        jurisdiction=request.jurisdiction,
        kyc_documents=request.documents,
    )
    return {
        "participant_id": request.participant_id,
        "passed": result.passed,
        "score": result.score,
        "details": result.details,
    }


@app.post("/compliance/screen", tags=["Compliance"])
async def screen_transaction(request: TransactionScreenRequest):
    """Screen a transaction for compliance."""
    from carib_clear.agents.compliance import ComplianceAgent

    agent = ComplianceAgent()
    result = agent.screen_transaction(
        transaction_id=f"api-{uuid.uuid4().hex[:12]}",
        from_participant=request.from_participant,
        to_participant=request.to_participant,
        amount_usd=request.amount_usd,
        currency=request.currency,
        from_jurisdiction="BB",
        to_jurisdiction="JM",
        purpose=request.purpose,
    )
    return {
        "passed": result.passed,
        "score": result.score,
        "requires_review": result.requires_review,
        "issues": result.details.get("issues", []),
    }


@app.get("/market/state", tags=["Market"])
async def get_market_state():
    """Get current FX market state — flows, matches, liquidity."""
    from carib_clear.agents.flow_visibility import FlowVisibilityAgent
    from carib_clear.agents.liquidity_pools import LiquidityPoolManager

    # Flows
    flow = FlowVisibilityAgent()
    flow.generate_mock_flows(count=10)

    # Liquidity
    lp = LiquidityPoolManager()
    lp.generate_mock_providers()

    return {
        "flows": {
            "demand_count": len(flow.demand_flows),
            "supply_count": len(flow.supply_flows),
        },
        "liquidity": lp.get_stats(),
    }


@app.get("/demo/trade_finance", tags=["Demo"])
async def demo_trade_finance():
    """Run the Trade Finance invoice factoring demo."""
    from io import StringIO
    import sys
    from carib_clear.agents.trade_finance import TradeFinanceModule

    module = TradeFinanceModule()
    invoices = TradeFinanceModule.generate_mock_invoices("Demo Business", count=5)

    results = []
    for inv in invoices:
        jurisdiction = "BB" if "Barbados" in inv.counterparty else \
                      "JM" if "Jamaica" in inv.counterparty or "Digicel" in inv.counterparty else \
                      "TT" if "Trinidad" in inv.counterparty or "Caribbean" in inv.counterparty or "Flour" in inv.counterparty else \
                      "HT" if "Haiti" in inv.counterparty or "Teleco" in inv.counterparty else \
                      "ECCB"
        sector = "services" if "Bank" in inv.counterparty or "Treasury" in inv.counterparty or "Ministry" in inv.counterparty or "Hotel" in inv.counterparty or "Tourism" in inv.counterparty else \
                 "energy" if "Energy" in inv.counterparty else \
                 "transport" if "Airlines" in inv.counterparty else \
                 "tech" if "Digicel" in inv.counterparty or "Teleco" in inv.counterparty else \
                 "manufacturing" if "Flour" in inv.counterparty else \
                 "retail"

        req = module.submit_invoice("demo_biz", "Demo Business", jurisdiction, inv)
        ev = module.evaluate(req, sector=sector)
        agreement = module.fund(ev, "demo_biz", "Demo Business") if ev.approved else None

        results.append({
            "invoice_id": inv.invoice_id,
            "debtor": inv.counterparty,
            "amount_usd": inv.amount_usd,
            "status": inv.status,
            "approved": ev.approved,
            "advance_rate": ev.advance_rate,
            "advance_amount_usd": ev.advance_amount_usd,
            "fee_pct": ev.discount_fee_pct,
            "risk_score": ev.risk_score,
        })

    return {
        "results": results,
        "stats": module.get_stats(),
    }


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────


def main():
    """Run the FastAPI server."""
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    logger.info("Starting CARIB-CLEAR API on http://0.0.0.0:8000")
    logger.info("Swagger docs at http://localhost:8000/docs")
    uvicorn.run(
        "carib_clear.api:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()