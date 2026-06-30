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
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

app = FastAPI(
    title="CARIB-CLEAR API",
    description="CARICOM FX Swap Network + MSME Credit Layer — Agentic financial infrastructure for the Caribbean",
    version="0.1.0-buildathon",
)

# Allow CORS for browser-based demos
# In production, restrict to your frontend domain via CARIB_CLEAR_ALLOWED_ORIGINS
allowed_origins = os.getenv("CARIB_CLEAR_ALLOWED_ORIGINS", "")
origin_list = [o.strip() for o in allowed_origins.split(",") if o.strip()] if allowed_origins else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# Structured error envelope + entity headers
from carib_clear.errors import register_error_handlers  # noqa: E402
register_error_handlers(app)

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach X-Request-ID to every response for traceability."""
    import uuid as _uuid
    request_id = request.headers.get("X-Request-ID", str(_uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# Serve static dashboard
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Register SEP-31 compliance endpoints
try:
    from carib_clear.sep31 import register_with_app
    register_with_app(app)
    logger.info("[SEP-31] Compliance layer registered at /sep31/*")
except Exception as exc:
    logger.warning("[SEP-31] Could not register: %s", exc)

# Register ISO 20022 endpoints
try:
    from carib_clear.iso20022.api import register_iso20022
    register_iso20022(app)
    logger.info("[ISO20022] Bank integration endpoints at /iso20022/*")
except Exception as exc:
    logger.warning("[ISO20022] Could not register: %s", exc)


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
    cost_comparison: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Cost comparison between traditional banking and CARIB-CLEAR",
        json_schema_extra={
            "example": {
                "traditional_fee_usd": 4000,
                "carib_clear_fee_usd": 50,
                "savings_percent": 98.75,
                "time_saved_days": 3,
            }
        }
    )


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
    gpu_available: bool = False
    gpu_name: str = ""
    compute_env: str = "cpu"


class WebhookRegisterRequest(BaseModel):
    """Webhook registration request."""
    url: str = Field(..., description="URL to POST events to")
    events: List[str] = Field(default=["*"], description="Event types to receive (or ['*'] for all)")
    participant_id: str = Field(..., description="Participant ID")
    description: str = Field(default="", description="Human-readable description")
    retry_count: int = Field(default=3, ge=0, le=10)
    timeout_seconds: int = Field(default=10, ge=1, le=60)


class WebhookResponse(BaseModel):
    """Webhook registration response."""
    webhook_id: str
    url: str
    events: List[str]
    participant_id: str
    secret: str
    created_at: str


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
    """Health check endpoint — includes GPU status for H200 deployments."""
    from carib_clear.config.gpu import have_gpu

    gpu_ok = have_gpu()
    gpu_name = ""
    compute_env = os.environ.get("CARIB_CLEAR_ENV", "cpu")
    if gpu_ok:
        try:
            import torch
            gpu_name = torch.cuda.get_device_name(0)
        except Exception:
            gpu_name = "H200 (unknown)"
        compute_env = "h200"

    return HealthResponse(
        status="healthy",
        version="0.1.0-buildathon",
        uptime_seconds=round(time.time() - _start_time, 2),
        agents_ready=True,
        gpu_available=gpu_ok,
        gpu_name=gpu_name,
        compute_env=compute_env,
    )


@app.get("/metrics", tags=["Info"])
async def metrics():
    """Prometheus-formatted metrics endpoint."""
    from carib_clear.agents.liquidity_pools import LiquidityPoolManager
    from carib_clear.webhooks import get_registry

    uptime = time.time() - _start_time
    lines = [
        "# HELP carib_clear_uptime_seconds Uptime in seconds",
        "# TYPE carib_clear_uptime_seconds gauge",
        f"carib_clear_uptime_seconds {uptime:.0f}",
        "",
        "# HELP carib_clear_loans_total Total loan applications",
        "# TYPE carib_clear_loans_total counter",
        f"carib_clear_loans_total {len(_loan_history)}",
        "",
        "# HELP carib_clear_webhooks_total Total registered webhooks",
        "# TYPE carib_clear_webhooks_total gauge",
        f"carib_clear_webhooks_total {len(get_registry().list())}",
        "",
        "# HELP carib_clear_info Static info",
        "# TYPE carib_clear_info gauge",
        'carib_clear_info{version="0.1.0-buildathon"} 1',
    ]

    try:
        lp = LiquidityPoolManager()
        for pool_name, pool in lp._pools.items():
            lines.append(f'carib_clear_pool_liquidity_usd{{currency="{pool_name}"}} {pool.total_liquidity_usd}')
            lines.append(f'carib_clear_pool_providers{{currency="{pool_name}"}} {pool.provider_count}')
    except Exception:
        pass

    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/demo/fx_swap", response_model=DemoResponse, tags=["Demo"])
async def demo_fx_swap():
    """Run the Layer 1 FX Swap Network demo — offloaded to thread pool."""
    from carib_clear.engine.demo_runner import DemoRunner

    def _run() -> tuple:
        """Run demo synchronously in a thread, capturing stdout."""
        from io import StringIO
        import sys
        demo = _get_demo_class()
        runner = DemoRunner()
        old = sys.stdout
        sys.stdout = buf = StringIO()
        try:
            t0 = time.time()
            demo.run_fx_swap_demo(live=False, runner=runner)
            dur = time.time() - t0
            return buf.getvalue(), runner.build_result(dur)
        finally:
            sys.stdout = old

    import asyncio
    try:
        output, result = await asyncio.to_thread(_run)
    except Exception as exc:
        return DemoResponse(status="error", layers=["fx_swap"], metrics={},
                            duration_seconds=0, html_output=f"<pre>Error: {exc}</pre>")

    return DemoResponse(
        status=result.status, layers=result.layers,
        metrics=result.metrics, duration_seconds=result.duration_seconds,
        cost_comparison=result.cost_comparison,
        html_output=f"<pre>{output[:5000]}</pre>",
    )


@app.get("/demo/msme_credit", response_model=DemoResponse, tags=["Demo"])
async def demo_msme_credit():
    """Run the Layer 2 MSME Credit demo — offloaded to thread pool."""
    from carib_clear.engine.demo_runner import DemoRunner

    def _run() -> tuple:
        from io import StringIO
        import sys
        demo = _get_demo_class()
        runner = DemoRunner()
        old = sys.stdout
        sys.stdout = buf = StringIO()
        try:
            t0 = time.time()
            demo.run_msme_credit_demo()
            dur = time.time() - t0
            return buf.getvalue(), runner.build_result(dur)
        finally:
            sys.stdout = old

    import asyncio
    output, result = await asyncio.to_thread(_run)

    return DemoResponse(
        status="complete",
        layers=["msme_credit"],
        metrics=result.metrics,
        duration_seconds=result.duration_seconds,
        html_output=f"<pre>{output[:5000]}</pre>",
    )


@app.get("/demo/full", response_model=DemoResponse, tags=["Demo"])
async def demo_full():
    """Run the full pipeline (Layer 1 + Layer 2) — offloaded to thread pool."""
    from carib_clear.engine.demo_runner import DemoRunner

    def _run() -> tuple:
        from io import StringIO
        import sys
        demo = _get_demo_class()
        runner = DemoRunner()
        old = sys.stdout
        sys.stdout = buf = StringIO()
        try:
            t0 = time.time()
            demo.run_full_demo()
            dur = time.time() - t0
            return buf.getvalue(), runner.build_result(dur)
        finally:
            sys.stdout = old

    import asyncio
    output, result = await asyncio.to_thread(_run)

    return DemoResponse(
        status="complete",
        layers=["fx_swap", "msme_credit"],
        metrics=result.metrics,
        duration_seconds=result.duration_seconds,
        html_output=f"<pre>{output[:8000]}</pre>",
        cost_comparison=result.cost_comparison,
    )


# ──────────────────────────────────────────────────────────────────────
# Webhook Endpoints
# ──────────────────────────────────────────────────────────────────────


@app.post("/webhooks/register", response_model=WebhookResponse, tags=["Webhooks"])
async def register_webhook(request: WebhookRegisterRequest):
    """Register a webhook endpoint for event notifications."""
    from carib_clear.webhooks import get_registry

    reg = get_registry()
    wh = reg.register(
        url=request.url,
        events=request.events,
        participant_id=request.participant_id,
        description=request.description,
        retry_count=request.retry_count,
        timeout_seconds=request.timeout_seconds,
    )
    return WebhookResponse(
        webhook_id=wh.webhook_id,
        url=wh.url,
        events=wh.events,
        participant_id=wh.participant_id,
        secret=wh.secret,
        created_at=wh.created_at,
    )


@app.get("/webhooks", tags=["Webhooks"])
async def list_webhooks(participant_id: Optional[str] = None):
    """List registered webhooks, optionally filtered by participant."""
    from carib_clear.webhooks import get_registry

    reg = get_registry()
    hooks = reg.list(participant_id)
    return {
        "webhooks": [
            {
                "webhook_id": w.webhook_id,
                "url": w.url,
                "events": w.events,
                "participant_id": w.participant_id,
                "description": w.description,
                "active": w.active,
                "created_at": w.created_at,
            }
            for w in hooks
        ],
        "total": len(hooks),
    }


@app.delete("/webhooks/{webhook_id}", tags=["Webhooks"])
async def delete_webhook(webhook_id: str):
    """Unregister a webhook."""
    from carib_clear.webhooks import get_registry

    reg = get_registry()
    if reg.unregister(webhook_id):
        return {"status": "deleted", "webhook_id": webhook_id}
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Webhook not found")


@app.get("/webhooks/{webhook_id}/deliveries", tags=["Webhooks"])
async def webhook_deliveries(webhook_id: str, limit: int = 20):
    """Get delivery history for a webhook."""
    from carib_clear.webhooks import get_registry

    reg = get_registry()
    deliveries = reg.get_deliveries(webhook_id, limit=min(limit, 100))
    return {
        "deliveries": [
            {
                "delivery_id": d.delivery_id,
                "event_type": d.event_type,
                "status": d.status,
                "status_code": d.status_code,
                "attempt_number": d.attempt_number,
                "duration_ms": d.duration_ms,
                "timestamp": d.timestamp,
            }
            for d in deliveries
        ],
        "total": len(deliveries),
    }


@app.post("/webhooks/_test", tags=["Webhooks"])
async def test_webhook_dispatch():
    """Dispatch a test event to all registered webhooks."""
    from carib_clear.webhooks import dispatch_event

    results = dispatch_event("test.ping", {
        "message": "CARIB-CLEAR webhook test",
        "timestamp": __import__("time").time(),
    })
    return {
        "dispatched": len(results),
        "successful": sum(1 for r in results if r.status == "success"),
        "failed": sum(1 for r in results if r.status == "failed"),
    }


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
        # Persist to SQLite
        try:
            from carib_clear.db import get_db
            from datetime import datetime, timezone
            get_db().insert("loan_applications", {
                "application_id": app_id,
                "business_name": request.business_name,
                "amount_usd": float(decision.approved_amount_usd or 0),
                "jurisdiction": request.jurisdiction,
                "approved": 1 if decision.approved else 0,
                "lender": (decision.lender_id or "").upper(),
                "interest_rate_pct": float(decision.interest_rate_annual_pct or 0),
                "sector": request.sector,
                "purpose": request.purpose,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass

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
# Settlement Rails & Stellar Endpoints
# ──────────────────────────────────────────────────────────────────────


@app.get("/rails/status", tags=["Settlement"])
async def get_rails_status():
    """Get status and quotes from all settlement rails."""
    from carib_clear.broker.stellar_adapter import StellarAdapter
    from carib_clear.broker.ach_adapter import LocalACHAdapter
    from carib_clear.broker.mobile_money_adapter import MobileMoneyAdapter
    from carib_clear.broker.base import MultiRailRouter

    router = MultiRailRouter([
        StellarAdapter({"mock_mode": False}),
        LocalACHAdapter({"jurisdiction": "JM", "mock_mode": True}),
        LocalACHAdapter({"jurisdiction": "BB", "mock_mode": True}),
        MobileMoneyAdapter({"provider": "moncash", "mock_mode": True}),
    ])

    rails = {}
    for rail_id, broker in router.brokers.items():
        info = broker.rail_info
        health = broker.health_check()
        quote = broker.get_quote("BBD", "USD", 50000)
        rails[rail_id] = {
            "name": info.name,
            "healthy": health,
            "currencies": info.supported_currencies,
            "jurisdictions": info.jurisdictions,
            "fee_bps": info.fee_bps,
            "estimated_time_seconds": info.estimated_time_seconds,
            "min_amount_usd": info.min_amount_usd,
            "max_amount_usd": info.max_amount_usd,
            "quote_bbd_usd": quote,
        }

    return {
        "status": "ok",
        "rails": rails,
        "stellar_connected": rails.get("stellar_usdc", {}).get("healthy", False),
    }


@app.get("/stellar/quote", tags=["Settlement"])
async def get_stellar_quote(
    from_currency: str = "BBD",
    to_currency: str = "USD",
    amount_usd: float = 50000,
):
    """Get a Stellar DEX quote for a currency pair."""
    from carib_clear.broker.stellar_adapter import StellarAdapter

    adapter = StellarAdapter({"mock_mode": False})
    adapter.initialize()

    quote = adapter.get_quote(from_currency.upper(), to_currency.upper(), amount_usd)
    if not quote:
        raise HTTPException(
            status_code=400,
            detail=f"Pair {from_currency}→{to_currency} not supported",
        )

    return {
        "from": from_currency.upper(),
        "to": to_currency.upper(),
        "amount_usd": amount_usd,
        "rate": quote["rate"],
        "fees_bps": quote["fees_bps"],
        "estimated_time_seconds": quote["estimated_time_seconds"],
        "path": quote["path"],
        "mode": quote.get("mode", "estimated"),
    }


@app.get("/stellar/network", tags=["Settlement"])
async def get_stellar_network_info():
    """Get Stellar testnet network info and hub account."""
    from stellar_sdk import Server
    import os

    horizon_url = os.getenv("STELLAR_HORIZON_URL", "https://horizon-testnet.stellar.org")

    try:
        server = Server(horizon_url)
        root = server.root().call()
        hub_pk = os.getenv("STELLAR_HUB_PUBLIC", "unknown")

        hub_info = None
        if hub_pk and hub_pk != "unknown":
            try:
                hub_account = server.accounts().account_id(hub_pk).call()
                hub_info = {
                    "public_key": hub_pk,
                    "balance_xlm": float(hub_account["balances"][0]["balance"]),
                    "sequence": hub_account["sequence"],
                }
            except Exception:
                hub_info = {"public_key": hub_pk, "error": "Could not load"}

        return {
            "horizon_url": horizon_url,
            "network_passphrase": root.get("network_passphrase", ""),
            "core_version": root.get("core_version", ""),
            "latest_ledger": root.get("history_latest_ledger", 0),
            "hub_account": hub_info,
            "connected": True,
        }
    except Exception as e:
        return {
            "horizon_url": horizon_url,
            "connected": False,
            "error": str(e),
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