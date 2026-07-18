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

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import os

from carib_clear.secrets import get_secret

logger = logging.getLogger(__name__)

DEFAULT_VERSION = os.getenv("CARIB_CLEAR_VERSION", "0.1.0")

app = FastAPI(
    title="CARIB-CLEAR API",
    description="CARICOM FX Swap Network + MSME Credit Layer — Agentic financial infrastructure for the Caribbean",
    version=DEFAULT_VERSION,
)

# Allow CORS for browser-based demos
# In production, set CARIB_CLEAR_ALLOWED_ORIGINS to a comma-separated list
def _build_cors_origins() -> List[str]:
    env_name = os.getenv("CARIB_CLEAR_ENV", "local").lower()
    raw = get_secret("CARIB_CLEAR_ALLOWED_ORIGINS", "")
    if not raw and env_name == "local":
        raw = "http://localhost:5173"
    return [o.strip() for o in raw.split(",") if o.strip()]

origin_list = _build_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=origin_list or [],
    allow_credentials=bool(origin_list),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

logger.info(
    "[CORS] allow_origins=%s allow_credentials=%s",
    origin_list or ["<none>"],
    bool(origin_list),
)

# Structured error envelope + entity headers
from carib_clear.errors import register_error_handlers  # noqa: E402
register_error_handlers(app)

from carib_clear.auth import require_api_key, require_verified_participant, require_admin, AuthenticatedIdentity  # noqa: E402
from carib_clear.compliance.screening import ComplianceScreeningEngine  # noqa: E402
from carib_clear.audit import audit as _audit  # noqa: E402


def require_demo_enabled(request: Request):
    """Gate /demo/* endpoints behind env/feature flag."""
    flag = request.headers.get("X-Demo-Flag") or os.getenv("CARIB_CLEAR_DEMO_ENABLED", "false")
    if str(flag).lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=404, detail="Demo endpoints are disabled")
    return flag


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

# Register API hardening (rate limiting, error handlers, graceful shutdown)
try:
    from carib_clear.api_hardening import register_hardening
    register_hardening(app)
except Exception as exc:
    logger.warning("[Hardening] Could not register: %s", exc)


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


class SettlementTransactionRequest(BaseModel):
    """Request to submit a settlement transaction."""
    rail: str = Field("stellar_usdc", description="Preferred settlement rail")
    from_currency: str = Field(..., description="Source currency", json_schema_extra={"example": "BBD"})
    to_currency: str = Field(..., description="Destination currency", json_schema_extra={"example": "JMD"})
    from_participant: Optional[str] = Field(None, description="Counterparty sending funds")
    to_participant: Optional[str] = Field(None, description="Counterparty receiving funds")
    from_jurisdiction: Optional[str] = Field(None, description="ISO jurisdiction code for source", json_schema_extra={"example": "BB"})
    to_jurisdiction: Optional[str] = Field(None, description="ISO jurisdiction code for destination", json_schema_extra={"example": "JM"})
    amount_usd: float = Field(..., gt=0, description="Notional amount in USD", json_schema_extra={"example": 500})
    amount_from: float = Field(..., gt=0, description="Amount in source currency", json_schema_extra={"example": 250})
    amount_to: float = Field(..., gt=0, description="Expected amount in destination currency", json_schema_extra={"example": 385})
    rate: float = Field(..., gt=0, description="Expected conversion rate", json_schema_extra={"example": 1.54})
    fees_usd: float = Field(0.0, ge=0, description="Estimated fees in USD")
    order_id: Optional[str] = Field(None, description="Optional caller-provided order id")
    business_key: str = Field("fx", description="Business scope/category for downstream routing", json_schema_extra={"example": "fx"})
    raw_response: Optional[Dict[str, Any]] = Field(default=None, description="Client-provided raw payload")
    priority: str = Field("cost", description="Rail selection priority: cost, speed, reliability")


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
        },
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
    from_jurisdiction: Optional[str] = Field(None, description="Jurisdiction of the sender")
    to_jurisdiction: Optional[str] = Field(None, description="Jurisdiction of the receiver")
    amount_usd: float
    currency: str = "USD"
    purpose: str = "trade"


class ComplianceReviewDecision(BaseModel):
    """Reviewer decision for a compliance review queue item."""
    queue_id: str
    status: str = Field("approved", description="approved or rejected")
    reviewer_id: str = Field(..., description="Reviewer identity/user id")
    reason: str = Field("", description="Required if rejected")


class ComplianceChecksQuery(BaseModel):
    """Query parameters for compliance check listing."""
    participant_id: Optional[str] = None
    check_type: Optional[str] = None
    limit: int = 100


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
    description: str = Field(default="", description="Human-readable description")
    retry_count: int = Field(default=3, ge=0, le=10)
    timeout_seconds: int = Field(default=10, ge=1, le=60)


class WebhookResponse(BaseModel):
    """Webhook registration response."""
    webhook_id: str
    url: str
    events: List[str]
    participant_id: str
    created_at: str
    secret_preview: str = ""


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
        version=DEFAULT_VERSION,
        uptime_seconds=round(time.time() - _start_time, 2),
        agents_ready=True,
        gpu_available=gpu_ok,
        gpu_name=gpu_name,
        compute_env=compute_env,
    )


@app.get("/livez", tags=["Info"])
async def livez():
    """Kubernetes liveness probe — lightweight app-liveness check."""
    return {"status": "ok"}


@app.get("/readyz", tags=["Info"])
async def readyz():
    """Kubernetes readiness probe — checks DB, webhooks, and optional broker."""
    from carib_clear.db import get_db
    from carib_clear.webhooks import get_registry

    deps = {"database": "ok"}
    status = "ready"
    try:
        db = get_db()
        db._conn.execute("SELECT 1")
    except Exception as exc:
        deps["database"] = f"error: {exc}"
        status = "not_ready"
    try:
        reg = get_registry()
        deps["webhooks"] = "ok"
    except Exception as exc:
        deps["webhooks"] = f"degraded: {exc}"
        status = "not_ready" if status == "ready" else "not_ready"
    if status != "ready":
        raise HTTPException(status_code=503, detail={"status": status, "dependencies": deps})
    return {"status": "ready", "dependencies": deps}


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
        'carib_clear_info{version="' + DEFAULT_VERSION + '"} 1',
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
async def demo_fx_swap(request: Request):
    """Run the Layer 1 FX Swap Network demo — offloaded to thread pool."""
    require_demo_enabled(request)
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
async def demo_msme_credit(request: Request):
    """Run the Layer 2 MSME Credit demo — offloaded to thread pool."""
    require_demo_enabled(request)
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
async def demo_full(request: Request):
    """Run the full pipeline (Layer 1 + Layer 2) — offloaded to thread pool."""
    require_demo_enabled(request)
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


@app.post("/webhooks/register", response_model=WebhookResponse, tags=["Webhooks"], dependencies=[Depends(require_api_key)])
async def register_webhook(request: WebhookRegisterRequest, identity: AuthenticatedIdentity = Depends(require_api_key)):
    """Register a webhook endpoint for event notifications."""
    from carib_clear.webhooks import get_registry

    participant_id = identity.participant_id or "anonymous"
    if not participant_id:
        raise HTTPException(status_code=400, detail="participant_id is required")

    reg = get_registry()
    wh = reg.register(
        url=request.url,
        events=request.events,
        participant_id=participant_id,
        description=request.description,
        retry_count=request.retry_count,
        timeout_seconds=request.timeout_seconds,
    )
    _audit(
        event="webhook.register",
        actor=participant_id,
        action="register_webhook",
        entity="webhook",
        entity_id=wh.webhook_id,
        payload={"url": request.url, "events": request.events},
        outcome="success",
    )
    return WebhookResponse(
        webhook_id=wh.webhook_id,
        url=wh.url,
        events=wh.events,
        participant_id=wh.participant_id,
        created_at=wh.created_at,
        secret_preview=f"{wh.secret[:6]}...",
    )


@app.get("/webhooks", tags=["Webhooks"], dependencies=[Depends(require_api_key)])
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


@app.delete("/webhooks/{webhook_id}", tags=["Webhooks"], dependencies=[Depends(require_api_key)])
async def delete_webhook(webhook_id: str):
    """Unregister a webhook."""
    from carib_clear.webhooks import get_registry

    reg = get_registry()
    if reg.unregister(webhook_id):
        _audit(
            event="webhook.delete",
            actor="api",
            action="delete_webhook",
            entity="webhook",
            entity_id=webhook_id,
            payload={"webhook_id": webhook_id},
            outcome="success",
        )
        return {"status": "deleted", "webhook_id": webhook_id}
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Webhook not found")


@app.get("/webhooks/{webhook_id}/deliveries", tags=["Webhooks"], dependencies=[Depends(require_api_key)])
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


@app.post("/webhooks/_test", tags=["Webhooks"], dependencies=[Depends(require_api_key)])
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


@app.post("/webhooks/_test_settlement", tags=["Webhooks"], dependencies=[Depends(require_api_key)])
async def test_settlement_webhook_dispatch():
    """Dispatch deterministic settlement.completed and settlement.failed events."""
    from carib_clear.webhooks import dispatch_event

    completed_results = dispatch_event("settlement.completed", {
        "cycle_id": "test-cycle-001",
        "instruction_id": "net-inst-001",
        "from_participant": "bb_hotel_001",
        "to_participant": "jm_supplier_001",
        "from_currency": "BBD",
        "to_currency": "JMD",
        "amount_usd": 10000,
        "rail": "stellar_usdc",
        "tx_hash": "0xcarib-test",
        "status": "filled",
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    })

    failed_results = dispatch_event("settlement.failed", {
        "cycle_id": "test-cycle-001",
        "instruction_id": "net-inst-002",
        "from_participant": "tt_energy_001",
        "to_participant": "ht_artisan_001",
        "from_currency": "TTD",
        "to_currency": "HTG",
        "amount_usd": 5000,
        "rail": "ach_tt",
        "error": "Insufficient liquidity",
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    })

    all_results = completed_results + failed_results
    return {
        "dispatched": len(all_results),
        "successful": sum(1 for r in all_results if r.status == "success"),
        "failed": sum(1 for r in all_results if r.status == "failed"),
        "events": [
            {"event_type": "settlement.completed", "deliveries": len(completed_results)},
            {"event_type": "settlement.failed", "deliveries": len(failed_results)},
        ],
    }


@app.post("/loan/apply", response_model=LoanResponse, tags=["Lending"], dependencies=[Depends(require_api_key)])
async def apply_for_loan(request: LoanRequest, identity: AuthenticatedIdentity = Depends(require_api_key)):
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
                "participant_id": identity.participant_id or "",
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

        _audit(
            event="loan.apply",
            actor=identity.participant_id or "api",
            action="apply_for_loan",
            entity="loan_application",
            entity_id=app_id,
            payload={
                "business_name": request.business_name,
                "amount_usd": request.amount_usd,
                "approved": decision.approved,
                "lender": decision.lender_id,
            },
            outcome="success" if decision.approved else "declined",
        )

        if decision.approved:
            message = (
                f"Approved! ${decision.approved_amount_usd:,.0f} at "
                f"{decision.interest_rate_annual_pct:.1f}% APR through "
                f"{decision.lender_id.upper()}. "
                f"{'No collateral required.' if not decision.collateral_required else 'Collateral required.'}"
            )
        else:
            message = "Declined: No eligible lending product found"

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


@app.get("/loan/applications", tags=["Lending"], dependencies=[Depends(require_api_key)])
async def list_applications(identity: AuthenticatedIdentity = Depends(require_api_key), limit: int = 10):
    """List recent loan applications, filtered by caller identity when available."""
    from carib_clear.db import get_db
    params: list = []
    where = "1=1"
    pid = identity.participant_id
    if pid:
        where += " AND participant_id = ?"
        params.append(pid)
    params.append(max(limit, 1))
    rows = get_db().query(
        f"SELECT * FROM loan_applications WHERE {where} ORDER BY created_at DESC LIMIT ?",
        tuple(params),
    )
    if not rows and _loan_history:
        rows = _loan_history[-max(limit, 1):]
    return {"applications": rows}


@app.get("/loan/status/{application_id}", tags=["Lending"], dependencies=[Depends(require_api_key)])
async def get_loan_status(application_id: str, identity: AuthenticatedIdentity = Depends(require_api_key)):
    """Get status of a specific loan application."""
    from carib_clear.db import get_db
    pid = identity.participant_id or ""
    row = get_db().query_one(
        "SELECT * FROM loan_applications WHERE application_id = ? AND (? = '' OR participant_id = ?)",
        (application_id, pid, pid),
    )
    if not row:
        for app in _loan_history:
            if app["application_id"] == application_id:
                return app
        raise HTTPException(status_code=404, detail="Application not found")
    return row


@app.post("/settlements", tags=["Settlement"], dependencies=[Depends(require_verified_participant)])
async def submit_settlement(request: SettlementTransactionRequest, identity: AuthenticatedIdentity = Depends(require_verified_participant)):
    """Submit a new settlement transaction and record immutable audit events."""
    from carib_clear.compliance.screening import ComplianceScreeningEngine

    listing_path = os.getenv("CARIB_CLEAR_COMPLIANCE_LISTS")
    engine = ComplianceScreeningEngine(lists_path=listing_path)
    engine.initialize()

    from_jurisdiction = request.from_jurisdiction or ""
    to_jurisdiction = request.to_jurisdiction or ""
    if not from_jurisdiction or not to_jurisdiction:
        raise HTTPException(status_code=400, detail="from_jurisdiction and to_jurisdiction are required")
    from_jurisdiction = from_jurisdiction.strip().upper()
    to_jurisdiction = to_jurisdiction.strip().upper()

    from_participant = request.from_participant or identity.participant_id or ""
    to_participant = request.to_participant or ""
    if not to_participant:
        raise HTTPException(status_code=400, detail="to_participant is required")

    screen = engine.screen_transaction(
        transaction_id=uuid.uuid4().hex[:12],
        from_participant=from_participant,
        to_participant=to_participant,
        amount_usd=request.amount_usd,
        currency=request.from_currency,
        from_jurisdiction=from_jurisdiction.strip().upper(),
        to_jurisdiction=to_jurisdiction.strip().upper(),
        purpose="trade",
    )

    issues = screen.get("issues", []) or []
    if any(issue not in {"pep_involved", "aml_reporting_threshold_exceeded"} for issue in issues):
        violation_list = ", ".join(sorted(set(issues)))
        _audit(
            event="compliance.screen",
            actor=identity.participant_id or "api",
            action="screen_settlement",
            entity="settlement",
            entity_id=uuid.uuid4().hex[:12],
            payload={"issues": issues, "amount_usd": request.amount_usd, "currency_from": request.from_currency},
            outcome="blocked",
        )
        raise HTTPException(
            status_code=400,
            detail={"message": f"Compliance screening failed: {violation_list}", "issues": issues, "passed": False},
        )

    from carib_clear.db import get_db
    from carib_clear.settlement import to_settlement_id, submit, complete
    from carib_clear.broker.base import SettlementOrder
    from carib_clear.broker.stellar_adapter import StellarAdapter

    order_id = request.order_id or f"order-{uuid.uuid4().hex[:12]}"
    settlement_id = to_settlement_id(request.rail, order_id)

    submitted = submit(
        rail=request.rail,
        order_id=order_id,
        business_key=request.business_key,
        payload={
            "participant_id": identity.participant_id or "",
            "amount_usd": request.amount_usd,
            "currency_from": request.from_currency,
            "currency_to": request.to_currency,
            "amount_from": request.amount_from,
            "amount_to": request.amount_to,
            "rate": request.rate,
            "fees_usd": request.fees_usd,
            "raw_response": request.raw_response or {},
            "source": "api",
        },
    )
    if not submitted:
        raise HTTPException(status_code=500, detail="Settlement create failed")

    order = SettlementOrder(
        order_id=order_id,
        from_currency=request.from_currency,
        to_currency=request.to_currency,
        amount_from=request.amount_from,
        amount_to=request.amount_to,
        rate=request.rate,
        rail=request.rail,
    )
    adapter = StellarAdapter({"mock_mode": True})
    adapter.initialize()
    result = adapter.submit_settlement(order)
    finalized = complete(
        request.rail,
        order_id,
        {
            "success": result.status in {"filled", "success"},
            "tx_hash": result.tx_hash,
            "raw_response": result.raw_response,
            "source": "api-broker",
        },
    )
    _audit(
        event="settlement.submit",
        actor=identity.participant_id or "api",
        action="submit_settlement",
        entity="settlement",
        entity_id=settlement_id,
        payload={
            "order_id": order_id,
            "status": finalized.get("status"),
            "rail": request.rail,
            "amount_usd": request.amount_usd,
            "tx_hash": result.tx_hash,
        },
        outcome="success" if finalized.get("status") in {"filled", "success"} else "failed",
    )
    return {
        "settlement_id": settlement_id,
        "status": finalized.get("status", submitted.get("status", "pending")),
        "order_id": order_id,
        "participant_id": identity.participant_id,
        "amount_usd": request.amount_usd,
        "currency_from": request.from_currency,
        "currency_to": request.to_currency,
        "amount_from": request.amount_from,
        "amount_to": request.amount_to,
        "rate": request.rate,
        "fees_usd": request.fees_usd,
        "rail": request.rail,
        "tx_hash": result.tx_hash,
        "compliance": {
            "passed": screen.get("passed", True),
            "requires_review": screen.get("requires_review", False),
            "issues": issues,
            "sanctions": screen.get("sanctions", {}),
            "pep": screen.get("pep", {}),
        },
        "raw_response": result.raw_response,
    }


@app.get("/settlements", tags=["Settlement"], dependencies=[Depends(require_api_key)])
async def list_settlements(identity: AuthenticatedIdentity = Depends(require_api_key), status: Optional[str] = None, limit: int = 20):
    """List settlement records for the authenticated participant."""
    from carib_clear.db import get_db
    rows = get_db().list_settlements(participant_id=identity.participant_id, status=status, limit=max(limit, 1))
    return {"settlements": rows[-max(limit, 1):]}


@app.get("/settlements/{settlement_id}", tags=["Settlement"], dependencies=[Depends(require_api_key)])
async def get_settlement(settlement_id: str, identity: AuthenticatedIdentity = Depends(require_api_key)):
    """Return one settlement after identity-scoped access check."""
    from carib_clear.db import get_db
    row = get_db().get_settlement(settlement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Settlement not found")
    if identity.participant_id and row.get("participant_id") not in {identity.participant_id, ""}:
        raise HTTPException(status_code=403, detail="Forbidden")
    return row


@app.get("/settlements/{settlement_id}/events", tags=["Settlement"], dependencies=[Depends(require_api_key)])
async def get_settlement_events(settlement_id: str, identity: AuthenticatedIdentity = Depends(require_api_key)):
    """Return immutable transition events for a settlement."""
    from carib_clear.db import get_db
    if not get_db().get_settlement(settlement_id):
        raise HTTPException(status_code=404, detail="Settlement not found")
    events = get_db().get_settlement_events(settlement_id)
    return {"settlement_id": settlement_id, "events": events}


@app.get("/liquidity/state", tags=["Market"], dependencies=[Depends(require_api_key)])
async def get_liquidity_state():
    """Get current liquidity pool state."""
    from carib_clear.agents.liquidity_pools import LiquidityPoolManager

    lp = LiquidityPoolManager()
    lp.generate_mock_providers()
    return lp.get_stats()


@app.get("/compliance/jurisdictions", tags=["Compliance"], dependencies=[Depends(require_api_key)])
async def list_jurisdictions():
    """List supported jurisdictions and their regulators."""
    from carib_clear.compliance.screening import ComplianceScreeningEngine

    listing_path = os.getenv("CARIB_CLEAR_COMPLIANCE_LISTS", "")
    engine = ComplianceScreeningEngine(lists_path=listing_path)
    engine.initialize()
    return {
        jur: {
            "regulator": rules["regulator"],
            "required_docs": rules["kyc_required"],
            "sanctions_lists": rules["sanctions_lists"],
        }
        for jur, rules in engine.get_jurisdiction_entries().items()
    }


@app.get("/compliance/profile/{participant_id}", tags=["Compliance"], dependencies=[Depends(require_api_key)])
async def get_compliance_profile(participant_id: str, identity: AuthenticatedIdentity = Depends(require_api_key)):
    """Get compliance profile for a participant."""
    if identity.participant_id and identity.participant_id not in {participant_id, "anonymous"}:
        raise HTTPException(status_code=403, detail="Forbidden")
    listing_path = os.getenv("CARIB_CLEAR_COMPLIANCE_LISTS", "")
    engine = ComplianceScreeningEngine(lists_path=listing_path)
    engine.initialize()
    profile = engine.get_profile(participant_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Participant not found")
    return {
        "participant_id": profile.participant_id,
        "jurisdiction": profile.jurisdiction,
        "kyc_status": profile.kyc_status,
        "kyc_tier": profile.kyc_tier,
        "kyc_documents": profile.kyc_documents,
        "aml_risk_score": profile.aml_risk_score,
        "sanctions_cleared": profile.sanctions_cleared,
        "pep_status": profile.pep_status,
        "last_screening": profile.last_screening,
        "restrictions": profile.restrictions,
        "metadata": profile.metadata,
    }


@app.post("/compliance/onboard", tags=["Compliance"], dependencies=[Depends(require_api_key)])
async def onboard_participant(request: ComplianceOnboardRequest, identity: AuthenticatedIdentity = Depends(require_api_key)):
    """Onboard a new participant with KYC documents."""
    participant_id = request.participant_id or identity.participant_id
    if not participant_id:
        raise HTTPException(status_code=400, detail="participant_id is required")

    listing_path = os.getenv("CARIB_CLEAR_COMPLIANCE_LISTS", "")
    engine = ComplianceScreeningEngine(lists_path=listing_path)
    engine.initialize()
    result = engine.onboard_participant(
        participant_id=participant_id,
        jurisdiction=request.jurisdiction,
        kyc_documents=request.documents,
    )

    if result.passed:
        try:
            from carib_clear.db import get_db
            get_db().update_participant_status(participant_id=participant_id, status="verified")
        except Exception:
            pass

    outcome = "success" if result.passed else "failed"
    _audit(
        event="participant.onboard",
        actor=identity.participant_id or "api",
        action="onboard_participant",
        entity="participant",
        entity_id=participant_id,
        payload={"jurisdiction": request.jurisdiction, "score": result.score},
        outcome=outcome,
    )
    return {
        "participant_id": participant_id,
        "passed": result.passed,
        "score": result.score,
        "details": result.details,
    }


@app.post("/compliance/screen", tags=["Compliance"], dependencies=[Depends(require_api_key)])
async def screen_transaction(request: TransactionScreenRequest):
    """Screen a transaction for compliance."""
    from carib_clear.db import get_db

    listing_path = os.getenv("CARIB_CLEAR_COMPLIANCE_LISTS")
    engine = ComplianceScreeningEngine(lists_path=listing_path)
    engine.initialize()
    from_jurisdiction = (request.from_jurisdiction or "").strip().upper()
    to_jurisdiction = (request.to_jurisdiction or "").strip().upper()
    if not from_jurisdiction or not to_jurisdiction:
        raise HTTPException(status_code=400, detail="from_jurisdiction and to_jurisdiction are required")
    result = engine.screen_transaction(
        transaction_id=f"api-{uuid.uuid4().hex[:12]}",
        from_participant=request.from_participant,
        to_participant=request.to_participant,
        amount_usd=request.amount_usd,
        currency=request.currency,
        from_jurisdiction=from_jurisdiction,
        to_jurisdiction=to_jurisdiction,
        purpose=request.purpose,
    )

    db = get_db()
    if db:
        from datetime import datetime, timezone
        check_id = result.get("transaction_id") or f"api-screen-{uuid.uuid4().hex[:12]}"
        db.insert_compliance_check(
            check_id=check_id,
            participant_id=f"{request.from_participant}:{request.to_participant}",
            check_type="transaction",
            passed=bool(result.get("passed")),
            score=1.0 if result.get("passed") else 0.0,
            details=result,
            requires_review=bool(result.get("requires_review")),
            reviewer_notes=f"{len(result.get('issues', []))} issues found",
        )
        timestamp = datetime.now(timezone.utc).isoformat()
        for idx, issue in enumerate(result.get("issues", [])):
            db.insert_aml_pep_hit(
                hit_id=f"{check_id}:{idx}",
                participant_id=f"{request.from_participant}:{request.to_participant}",
                check_id=check_id,
                issue=issue,
                payload={"sanctions": result.get("sanctions", {}), "pep": result.get("pep", {})},
            )

    return {
        "passed": result.get("passed", False),
        "requires_review": result.get("requires_review", False),
        "issues": result.get("issues", []),
        "sanctions": result.get("sanctions", {}),
        "pep": result.get("pep", {}),
    }


@app.post("/compliance/review", tags=["Compliance"], dependencies=[Depends(require_api_key)])
async def review_compliance_queue(request: ComplianceReviewDecision):
    """Approve or reject a compliance review queue item with reviewer evidence."""
    from carib_clear.db import get_db
    items = get_db().get_review_queue_items(status="pending")
    target = [item for item in items if item.get("queue_id") == request.queue_id]
    if not target:
        raise HTTPException(status_code=404, detail="Review item not found")
    target = target[0]
    if request.status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="status must be approved or rejected")
    if request.status == "rejected" and not request.reason.strip():
        raise HTTPException(status_code=400, detail="reason is required for rejection")
    get_db().update_review_queue_item(
        queue_id=request.queue_id,
        status=request.status,
        reviewer_id=request.reviewer_id,
        reason=request.reason,
    )
    return {"queue_id": request.queue_id, "status": request.status, "reviewer_id": request.reviewer_id}


@app.post("/compliance/reload-lists", tags=["Compliance"], dependencies=[Depends(require_api_key)])
async def reload_compliance_lists(request: Request, token: Optional[str] = None, identity: AuthenticatedIdentity = Depends(require_api_key)):
    """Reload compliance lists from current env-configured file with audit and admin guard."""
    from carib_clear.config_reloader import reload_compliance_lists as reloader

    reload_token = os.getenv("CARIB_CLEAR_COMPLIANCE_RELOAD_TOKEN", "")
    environment = os.getenv("CARIB_CLEAR_ENV", "local")
    if reload_token:
        provided = token or request.headers.get("X-Reload-Token", "")
        if provided != reload_token:
            raise HTTPException(status_code=403, detail="reload token required")
    elif environment not in {"local", "demo"}:
        raise HTTPException(status_code=403, detail="reload disabled outside local/demo")

    path = os.getenv("CARIB_CLEAR_COMPLIANCE_LISTS", "")
    if not path:
        raise HTTPException(status_code=400, detail="missing CARIB_CLEAR_COMPLIANCE_LISTS")

    actor = identity.participant_id or "api"
    result = reloader(path=path, actor=actor)
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("reason", "reload failed"))
    return result


@app.get("/compliance/checks", tags=["Compliance"], dependencies=[Depends(require_api_key)])
async def list_compliance_checks(
    participant_id: Optional[str] = None,
    check_type: Optional[str] = None,
    limit: int = 100,
):
    """List persisted compliance checks with optional filters."""
    from carib_clear.db import get_db
    rows = get_db().list_compliance_checks(participant_id=participant_id, check_type=check_type, limit=limit)
    return {"checks": rows}


@app.get("/compliance/lists", tags=["Compliance"], dependencies=[Depends(require_api_key)])
async def list_compliance_lists():
    """Return loaded compliance list metadata for operators."""
    from carib_clear.compliance.screening import ComplianceScreeningEngine

    listing_path = os.getenv("CARIB_CLEAR_COMPLIANCE_LISTS", "")
    try:
        engine = ComplianceScreeningEngine(lists_path=listing_path)
        engine.initialize()
        keyword_groups = sorted((engine.lists.keywords or {}).keys())
        source_count = len(engine.providers)
    except Exception as exc:
        logger.warning("compliance list metadata read failed: %s", exc)
        keyword_groups = []
        source_count = 0

    return {
        "file": listing_path,
        "source_count": source_count,
        "keyword_groups": keyword_groups,
    }


@app.get("/market/state", tags=["Market"], dependencies=[Depends(require_api_key)])
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


# ──────────────────────────────────────────────────────────────────────
# Operator audit API
# ──────────────────────────────────────────────────────────────────────


class AuditQuery(BaseModel):
    """Operator audit query."""

    event: Optional[str] = Field(default=None, description="Filter by event name")
    entity: Optional[str] = Field(default=None, description="Filter by entity")
    actor: Optional[str] = Field(default=None, description="Filter by actor")
    outcome: Optional[str] = Field(default=None, description="Filter by outcome")
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)

@app.get("/audit/events", tags=["Admin"], dependencies=[Depends(require_admin)])
async def get_audit_events(request: Request, query: Optional[AuditQuery] = None):
    """Query audit events with optional filters."""
    from carib_clear.audit import list_audit_trail_admin, count_audit_trail_admin
    from carib_clear.db import get_db

    params = query or AuditQuery()
    db = get_db()
    rows = list_audit_trail_admin(
        db=db,
        limit=int(params.limit),
        offset=int(params.offset),
        event=params.event,
        entity=params.entity,
        actor=params.actor,
        outcome=params.outcome,
    )
    total = count_audit_trail_admin(
        db=db,
        event=params.event,
        entity=params.entity,
        actor=params.actor,
        outcome=params.outcome,
    )
    return {
        "total": total,
        "limit": int(params.limit),
        "offset": int(params.offset),
        "events": rows,
    }


@app.get("/demo/trade_finance", tags=["Demo"], dependencies=[Depends(require_api_key)])
async def demo_trade_finance(request: Request):
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


@app.get("/rails/status", tags=["Settlement"], dependencies=[Depends(require_api_key)])
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


@app.get("/stellar/quote", tags=["Settlement"], dependencies=[Depends(require_api_key)])
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


@app.get("/stellar/network", tags=["Settlement"], dependencies=[Depends(require_api_key)])
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