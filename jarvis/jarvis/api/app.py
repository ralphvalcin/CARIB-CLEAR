from __future__ import annotations

from dataclasses import asdict
import os
import threading
import time
from typing import Any, Dict, Optional

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from jarvis.events.models import Event
from jarvis.events.store import JsonlEventStore, SqliteEventStore
from jarvis.runtime.policy import DefaultPolicyEngine
from jarvis.main import JarvisApp
from jarvis.knowledge.self_doc import SelfKnowledgeBuilder

@asynccontextmanager
async def lifespan(_: FastAPI):
    start_sweeper()
    try:
        yield
    finally:
        stop_sweeper()


app = FastAPI(title="JARVIS Control API", version="0.4.0", lifespan=lifespan)
policy = DefaultPolicyEngine()
jsonl_store = JsonlEventStore()
sqlite_store = SqliteEventStore()
jarvis_runtime = JarvisApp()
_sweeper_stop = threading.Event()
_sweeper_thread: Optional[threading.Thread] = None


def _sweeper_loop(interval_seconds: float) -> None:
    while not _sweeper_stop.wait(interval_seconds):
        try:
            jarvis_runtime.sweep_stale_approvals()
        except Exception:
            # Keep loop alive; failures should not crash API process.
            continue


def start_sweeper(interval_seconds: Optional[float] = None) -> None:
    global _sweeper_thread
    if _sweeper_thread and _sweeper_thread.is_alive():
        return
    interval = interval_seconds or float(os.getenv("JARVIS_SWEEP_INTERVAL_SECONDS", "15"))
    _sweeper_stop.clear()
    _sweeper_thread = threading.Thread(target=_sweeper_loop, args=(interval,), daemon=True, name="jarvis-approval-sweeper")
    _sweeper_thread.start()


def stop_sweeper() -> None:
    _sweeper_stop.set()


class PolicyRequest(BaseModel):
    action: str = Field(..., description="Action/tool name")
    payload: Dict[str, Any] = Field(default_factory=dict)


class EventRequest(BaseModel):
    session_id: str
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    level: str = "info"


class ApprovalDecisionRequest(BaseModel):
    reason: Optional[str] = None


class IngestRequest(BaseModel):
    session_id: str
    text: str


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    configured = os.getenv("JARVIS_API_KEY")
    if not configured:
        return
    if x_api_key != configured:
        raise HTTPException(status_code=401, detail="invalid api key")



DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS Dashboard</title>
<script src="https://unpkg.com/htmx.org@2.0.4" crossorigin="anonymous"></script>
<style>
  :root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--dim:#8b949e;--green:#3fb950;--yellow:#d29922;--red:#f85149;--blue:#58a6ff;--purple:#bc8cff}
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);padding:24px;max-width:1200px;margin:0 auto}
  h1{font-size:1.5rem;margin-bottom:4px;color:#fff}
  h2{font-size:1.1rem;margin-bottom:12px;margin-top:0}
  .subtitle{color:var(--dim);font-size:.85rem;margin-bottom:24px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}
  .section{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:24px}
  .section h2{margin-bottom:12px}
  .card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;text-align:center}
  .card .num{font-size:2rem;font-weight:700}
  .card .label{font-size:.8rem;color:var(--dim);margin-top:4px}
  .card-sm{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px 16px;display:flex;align-items:center;gap:12px}
  .card-sm .label{font-size:.8rem;color:var(--dim)}
  .card-sm .value{font-size:1rem;font-weight:600}
  .green{color:var(--green)}.yellow{color:var(--yellow)}.red{color:var(--red)}.blue{color:var(--blue)}.purple{color:var(--purple)}
  table{width:100%;border-collapse:collapse;background:var(--card);border-radius:8px;overflow:hidden}
  th{text-align:left;padding:10px 12px;border-bottom:1px solid var(--border);color:var(--dim);font-size:.8rem;text-transform:uppercase;letter-spacing:.5px}
  td{padding:10px 12px;border-bottom:1px solid var(--border);font-size:.85rem}
  .badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:.75rem;font-weight:600}
  .badge-pending{background:#3fb95022;color:var(--green)}
  .badge-approved{background:#d2992222;color:var(--yellow)}
  .badge-executed{background:#58a6ff22;color:var(--blue)}
  .badge-denied{background:#f8514922;color:var(--red)}
  .badge-failed{background:#f8514944;color:var(--red)}
  .badge-ok{background:#3fb95022;color:var(--green)}
  .badge-drifted{background:#f8514922;color:var(--red)}
  .mono{font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace;font-size:.8rem}
  .age{color:var(--dim);font-size:.8rem}
  .empty{color:var(--dim);padding:24px;text-align:center}
  .btn{display:inline-block;padding:4px 12px;border-radius:6px;font-size:.75rem;font-weight:600;cursor:pointer;text-decoration:none;background:transparent;border:1px solid;transition:opacity .15s}
  .btn:hover{opacity:.8}
  .btn-approve{color:var(--green);border-color:var(--green)}
  .btn-deny{color:var(--red);border-color:var(--red)}
  .status-dot{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:6px;vertical-align:middle}
  .status-healthy{background:var(--green);box-shadow:0 0 8px var(--green)}
  .status-drifted{background:var(--yellow);box-shadow:0 0 8px var(--yellow)}
  .status-down{background:var(--red);box-shadow:0 0 8px var(--red)}
</style>
</head>
<body>

<h1>⚙ JARVIS Control Dashboard</h1>
<p class="subtitle">System overview · approvals · events · drift · live refresh every 10s</p>

<!-- Health + Drift Status Row -->
<div id="health-panel" hx-get="/dashboard/_health" hx-trigger="every 10s" hx-swap="innerHTML" class="grid" style="grid-template-columns:1fr 1fr">
  <div class="card-sm"><div class="label">Loading health...</div></div>
  <div class="card-sm"><div class="label">Loading knowledge...</div></div>
</div>

<!-- Approval Metrics -->
<div class="grid" id="metrics-panel" hx-get="/dashboard/_metrics" hx-trigger="every 10s" hx-swap="innerHTML">
  {{ metrics_cards }}
</div>

<!-- Pending Approvals -->
<div class="section">
  <h2>Pending Approvals</h2>
  <div id="pending-panel" hx-get="/dashboard/_pending" hx-trigger="every 10s" hx-swap="innerHTML">
    {{ pending_rows }}
  </div>
</div>

<!-- Events -->
<div class="section">
  <h2>Recent Events</h2>
  <div id="events-panel" hx-get="/dashboard/_events" hx-trigger="every 10s" hx-swap="innerHTML">
    <div class="empty">Loading events...</div>
  </div>
</div>

<!-- Voice Log -->
<div class="section">
  <h2>🗣️ Recent Voice Interactions</h2>
  <div id="voice-log-panel" hx-get="/dashboard/_voice_log" hx-trigger="every 10s" hx-swap="innerHTML">
    <div class="empty">Loading voice log...</div>
  </div>
</div>

<!-- Voice Selector -->
<div class="section">
  <h2>🎙️ TTS Voice Selector</h2>
  <div id="voice-panel" hx-get="/dashboard/_voices" hx-trigger="load, every 30s" hx-swap="innerHTML">
    <div class="empty">Loading voices...</div>
  </div>
</div>

</body>
</html>"""

DASHBOARD_METRICS_CARDS = """\
<div class="card"><div class="num green">{pending}</div><div class="label">Pending</div></div>
<div class="card"><div class="num yellow">{approved}</div><div class="label">Approved</div></div>
<div class="card"><div class="num blue">{executed}</div><div class="label">Executed</div></div>
<div class="card"><div class="num purple">{denied}</div><div class="label">Denied</div></div>
<div class="card"><div class="num red">{failed}</div><div class="label">Failed</div></div>
<div class="card"><div class="num" style="color:#fff">{total}</div><div class="label">Total</div></div>"""


def _format_age(ts: float) -> str:
    secs = time.time() - ts
    if secs < 60:
        return f"{secs:.0f}s"
    mins = secs / 60
    if mins < 60:
        return f"{mins:.0f}m"
    hours = mins / 60
    return f"{hours:.1f}h"


def _badge(status: str) -> str:
    cls = f"badge badge-{status}"
    return f'<span class="{cls}">{status}</span>'


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> str:
    m = jarvis_runtime.metrics()["metrics"]
    pending_list = jarvis_runtime.list_approvals(status="pending")["approvals"]

    cards = DASHBOARD_METRICS_CARDS.format(**m)

    if not pending_list:
        rows = '<div class="empty">No pending approvals</div>'
    else:
        rows = """<table><thead><tr><th>ID</th><th>Action</th><th>Reason</th><th>Age</th><th>Status</th></tr></thead><tbody>"""
        for a in pending_list:
            rows += f"""<tr>
<td class="mono">{a["approval_id"][:8]}</td>
<td>{a.get("action", "-")}</td>
<td>{a.get("reason", "-")}</td>
<td class="age">{_format_age(a.get("created_at", 0))}</td>
<td>{_badge(a.get("status", "pending"))}</td>
</tr>"""
        rows += "</tbody></table>"

    return DASHBOARD_HTML.replace("{{ metrics_cards }}", cards).replace("{{ pending_rows }}", rows)


@app.get("/dashboard/_metrics", response_class=HTMLResponse)
def dashboard_metrics() -> str:
    m = jarvis_runtime.metrics()["metrics"]
    return DASHBOARD_METRICS_CARDS.format(**m)


@app.get("/dashboard/_pending", response_class=HTMLResponse)
def dashboard_pending() -> str:
    pending_list = jarvis_runtime.list_approvals(status="pending")["approvals"]
    if not pending_list:
        return '<div class="empty">No pending approvals</div>'

    rows = """<table><thead><tr><th>ID</th><th>Action</th><th>Reason</th><th>Age</th><th>Action</th></tr></thead><tbody>"""
    for a in pending_list:
        aid = a["approval_id"]
        rows += f"""<tr>
<td class="mono">{aid[:8]}</td>
<td>{a.get("action", "-")}</td>
<td>{a.get("reason", "-")}</td>
<td class="age">{_format_age(a.get("created_at", 0))}</td>
<td>
  <a href="#" class="btn btn-approve" hx-post="/control/approvals/{aid}/approve" hx-target="closest tr" hx-swap="outerHTML">Approve</a>
  <a href="#" class="btn btn-deny" hx-post="/control/approvals/{aid}/deny" hx-vals='{{"reason":"denied from dashboard"}}' hx-target="closest tr" hx-swap="outerHTML">Deny</a>
</td>
</tr>"""
    rows += "</tbody></table>"
    return rows


@app.get("/dashboard/_health", response_class=HTMLResponse)
def dashboard_health() -> str:
    """Health + drift status card."""
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:8000/health", timeout=3)
        health_ok = resp.status == 200
    except Exception:
        health_ok = False

    health_dot = "status-healthy" if health_ok else "status-down"
    health_text = "Healthy" if health_ok else "Unreachable"

    # Drift status
    try:
        from jarvis.knowledge.self_doc import SelfKnowledgeBuilder
        doc = SelfKnowledgeBuilder().build()
        drift_count = len(doc.drift.missing) + len(doc.drift.unexpected) if doc.drift else 0
        caps_count = doc.to_dict().get("capability_count", 0)
        drift_dot = "status-healthy" if drift_count == 0 else "status-drifted"
        drift_text = f"In Sync" if drift_count == 0 else f"{drift_count} Drifted"
        last_check = time.strftime("%H:%M:%S", time.localtime(doc.drift.checked_at)) if doc.drift else "N/A"
    except Exception:
        drift_dot = "status-drifted"
        drift_text = "Unknown"
        caps_count = "?"
        last_check = "N/A"

    return f"""<div class="card-sm"><span class="status-dot {health_dot}"></span><div><div class="value { 'green' if health_ok else 'red' }">{health_text}</div><div class="label">API Server /health</div></div></div>
<div class="card-sm"><span class="status-dot {drift_dot}"></span><div><div class="value">{drift_text}</div><div class="label">{caps_count} capabilities · checked {last_check}</div></div></div>"""


@app.get("/dashboard/_events", response_class=HTMLResponse)
def dashboard_events(limit: int = 10) -> str:
    """Recent events table."""
    from jarvis.events.store import JsonlEventStore
    try:
        store = JsonlEventStore()
        events = store.recent(limit=limit)
    except Exception:
        events = []

    if not events:
        return '<div class="empty">No events recorded yet</div>'

    rows = """<table><thead><tr><th>Time</th><th>Type</th><th>Level</th><th>Details</th></tr></thead><tbody>"""
    for evt in events[:limit]:
        if isinstance(evt, dict):
            ts = time.strftime("%H:%M:%S", time.localtime(evt.get("ts", 0)))
            typ = evt.get("type", "unknown")
            lvl = evt.get("level", "info")
            payload = evt.get("payload", {})
        else:
            ts = time.strftime("%H:%M:%S", time.localtime(getattr(evt, 'ts', 0)))
            typ = getattr(evt, 'type', 'unknown')
            lvl = getattr(evt, 'level', 'info')
            payload = getattr(evt, 'payload', {})
        # Show first 60 chars of payload as detail
        detail = str(payload)[:60] if payload else ""
        rows += f"""<tr>
<td class="age">{ts}</td>
<td class="mono">{typ}</td>
<td>{_badge(str(lvl))}</td>
<td class="mono" style="color:var(--dim)">{detail}</td>
</tr>"""
    rows += "</tbody></table>"
    return rows


@app.get("/voice-log", response_class=HTMLResponse)
@app.get("/voice-log/recent", response_class=HTMLResponse)
def voice_log_recent(limit: int = 20) -> str:
    """Recent voice interactions log."""
    try:
        from jarvis.voice.log import VoiceLogger
        logger = VoiceLogger()
        entries = logger.recent(limit=limit)
    except Exception:
        return '<div class="empty">Voice log unavailable</div>'

    if not entries:
        return '<div class="empty">No voice interactions recorded yet</div>'

    rows = """<table><thead><tr><th>Time</th><th>Transcription</th><th>Response</th><th>Path</th><th>Wake</th></tr></thead><tbody>"""
    for e in entries:
        ts = time.strftime("%H:%M:%S", time.localtime(e.get("timestamp", 0)))
        trans = e.get("transcription", "")[:50]
        resp = e.get("response_text", "")[:50]
        path = e.get("response_path", "")
        wake = "🎤" if e.get("wake_word") else ""
        rows += f"""<tr>
<td class="age">{ts}</td>
<td class="mono">{trans}</td>
<td class="mono">{resp}</td>
<td>{_badge(path) if path else ""}</td>
<td>{wake}</td>
</tr>"""
    rows += "</tbody></table>"
    rows += f'<p style="color:var(--dim);font-size:.8rem;margin-top:8px">{len(entries)} entries</p>'
    return rows


@app.get("/dashboard/_voice_log", response_class=HTMLResponse)
def dashboard_voice_log(limit: int = 10) -> str:
    """htmx partial — voice log table for the dashboard."""
    try:
        from jarvis.voice.log import VoiceLogger
        logger = VoiceLogger()
        entries = logger.recent(limit=limit)
    except Exception:
        return '<div class="empty">Voice log unavailable</div>'

    if not entries:
        return '<div class="empty">No voice interactions recorded yet</div>'

    rows = """<table><thead><tr><th>Time</th><th>You said</th><th>JARVIS said</th><th>Wake</th></tr></thead><tbody>"""
    for e in entries:
        ts = time.strftime("%H:%M:%S", time.localtime(e.get("timestamp", 0)))
        trans = e.get("transcription", "")[:40]
        resp = e.get("response_text", "")[:40]
        wake = "🎤" if e.get("wake_word") else ""
        rows += f"""<tr>
<td class="age">{ts}</td>
<td class="mono">{trans}</td>
<td class="mono" style="color:var(--dim)">{resp}</td>
<td>{wake}</td>
</tr>"""
    rows += "</tbody></table>"
    return rows


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "jarvis-api"}


@app.get("/system/status")
def system_status() -> Dict[str, Any]:
    """Consolidated system status for menu bar, notifications, and external UIs."""
    # Health
    api_status = "healthy"

    # Approvals
    try:
        m = jarvis_runtime.metrics()["metrics"]
        approvals_pending = m.get("pending", 0)
    except Exception:
        approvals_pending = 0

    # Drift
    try:
        from jarvis.knowledge.self_doc import SelfKnowledgeBuilder

        doc = SelfKnowledgeBuilder().build()
        drift_missing = list(doc.drift.missing) if doc.drift else []
        capability_count = doc.to_dict().get("capability_count", 0)
    except Exception:
        drift_missing = []
        capability_count = 0

    # Voice (via guard file)
    from pathlib import Path

    guard = Path.home() / ".jarvis_voice_guard"
    kill = Path.home() / ".jarvis_voice_kill"
    voice_running = guard.exists() and not kill.exists()

    return {
        "ok": True,
        "api": api_status,
        "voice_running": voice_running,
        "approvals_pending": approvals_pending,
        "drift_missing": drift_missing,
        "capability_count": capability_count,
        "drift_count": len(drift_missing),
    }


# ── Voice management endpoints ────────────────────────────────────────────────


@app.get("/voice/voices")
def list_voices() -> Dict[str, Any]:
    """List all available Piper voices with download status."""
    from jarvis.voice.voice_manager import VoiceManager
    vm = VoiceManager()
    voices = vm.list_voices()
    return {
        "ok": True,
        "voices": [
            {
                "voice_id": v.voice_id,
                "name": v.name,
                "gender": v.gender,
                "accent": v.accent,
                "description": v.description,
                "downloaded": v.downloaded,
                "size_mb": v.size_mb,
                "selected": v.selected,
            }
            for v in voices
        ],
    }


@app.post("/voice/select")
def select_voice(voice_id: str) -> Dict[str, Any]:
    """Select a TTS voice by ID. Voice must be downloaded first."""
    from jarvis.voice.voice_manager import VoiceManager
    vm = VoiceManager()
    ok = vm.select_voice(voice_id)
    if not ok:
        return {"ok": False, "error": f"Voice '{voice_id}' not available. Download it first via /voice/download/{voice_id}"}
    # Signal to TTSEngine that voice changed by writing to a shared flag file
    from pathlib import Path
    flag = Path(__file__).resolve().parent.parent.parent / "piper_voices" / ".voice_changed"
    flag.write_text(voice_id)
    return {"ok": True, "voice_id": voice_id}


@app.post("/voice/download/{voice_id}")
def download_voice(voice_id: str) -> Dict[str, Any]:
    """Download a Piper voice model from HuggingFace."""
    from jarvis.voice.voice_manager import VoiceManager
    vm = VoiceManager()
    ok = vm.download_voice(voice_id)
    if ok:
        return {"ok": True, "voice_id": voice_id, "message": f"Voice '{voice_id}' downloaded"}
    return {"ok": False, "error": f"Failed to download voice '{voice_id}'"}


@app.post("/voice/remove/{voice_id}")
def remove_voice(voice_id: str) -> Dict[str, Any]:
    """Remove a downloaded voice (cannot remove the default)."""
    from jarvis.voice.voice_manager import VoiceManager
    vm = VoiceManager()
    ok = vm.remove_voice(voice_id)
    if ok:
        return {"ok": True, "voice_id": voice_id, "message": f"Voice '{voice_id}' removed"}
    return {"ok": False, "error": f"Could not remove voice '{voice_id}' (default voice is protected)"}


@app.get("/dashboard/_voices", response_class=HTMLResponse)
def dashboard_voices() -> str:
    """htmx partial — voice selector panel for the dashboard."""
    from jarvis.voice.voice_manager import VoiceManager
    vm = VoiceManager()
    voices = vm.list_voices()

    rows = ""
    for v in voices:
        status = "✅" if v.downloaded else "⬇️"
        select_btn = ""
        if v.downloaded:
            if v.selected:
                select_btn = """<span class="badge badge-ok">Active</span>"""
            else:
                select_btn = f"""<a href="#" class="btn btn-approve" hx-post="/voice/select?voice_id={v.voice_id}" hx-target="closest .section" hx-swap="outerHTML" hx-trigger="click">Select</a>"""
        else:
            size_label = f"{v.size_mb:.0f}MB" if v.size_mb > 0 else "~60MB"
            select_btn = f"""<a href="#" class="btn btn-approve" hx-post="/voice/download/{v.voice_id}" hx-target="closest tr" hx-swap="outerHTML" hx-trigger="click">Download ({size_label})</a>"""

        rows += f"""<tr>
<td>{status} {v.name}</td>
<td class="mono">{v.gender}</td>
<td class="mono">{v.accent}</td>
<td style="color:var(--dim);font-size:.8rem">{v.description}</td>
<td>{select_btn}</td>
</tr>"""

    return f"""<table><thead><tr><th>Voice</th><th>Gender</th><th>Accent</th><th>Description</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table>"""


_self_knowledge_builder: SelfKnowledgeBuilder | None = None


@app.get("/knowledge/self")
def get_self_knowledge() -> Dict[str, Any]:
    """Return a structured self-knowledge document about JARVIS."""
    global _self_knowledge_builder
    if _self_knowledge_builder is None:
        _self_knowledge_builder = SelfKnowledgeBuilder()
    doc = _self_knowledge_builder.build()
    return doc.to_dict()


@app.get("/knowledge/self/markdown", response_class=HTMLResponse)
def get_self_knowledge_markdown() -> str:
    """Return the self-knowledge document rendered as markdown."""
    global _self_knowledge_builder
    if _self_knowledge_builder is None:
        _self_knowledge_builder = SelfKnowledgeBuilder()
    doc = _self_knowledge_builder.build()
    html_content = doc.to_markdown().replace("\n", "<br>\n")
    return f"<pre style='font-family: monospace; white-space: pre-wrap;'>{html_content}</pre>"


@app.post("/control/evaluate", dependencies=[Depends(require_api_key)])
def evaluate_policy(req: PolicyRequest) -> Dict[str, str]:
    result = policy.evaluate(action=req.action, payload=req.payload)
    return {"decision": result.decision, "reason": result.reason}


@app.get("/control/approvals", dependencies=[Depends(require_api_key)])
def list_approvals(status: Optional[str] = None) -> Dict[str, Any]:
    return jarvis_runtime.list_approvals(status=status)


@app.post("/control/approvals/{approval_id}/approve", dependencies=[Depends(require_api_key)])
def approve_action(approval_id: str) -> Dict[str, Any]:
    return jarvis_runtime.approve_action(approval_id)


@app.post("/control/approvals/{approval_id}/deny", dependencies=[Depends(require_api_key)])
def deny_action(approval_id: str, req: ApprovalDecisionRequest) -> Dict[str, Any]:
    return jarvis_runtime.deny_action(approval_id, reason=req.reason)


@app.post("/control/approvals/sweep", dependencies=[Depends(require_api_key)])
def sweep_stale_approvals() -> Dict[str, Any]:
    return jarvis_runtime.sweep_stale_approvals()


@app.get("/control/metrics", dependencies=[Depends(require_api_key)])
def get_metrics() -> Dict[str, Any]:
    return jarvis_runtime.metrics()


@app.post("/control/ingest", dependencies=[Depends(require_api_key)])
def ingest_text(req: IngestRequest) -> Dict[str, Any]:
    return jarvis_runtime.handle_text(session_id=req.session_id, text=req.text)


@app.get("/control/memory/stats", dependencies=[Depends(require_api_key)])
def memory_stats() -> Dict[str, Any]:
    """Conversation memory statistics."""
    return jarvis_runtime.memory_stats()


@app.get("/control/memory/facts", dependencies=[Depends(require_api_key)])
def memory_facts() -> Dict[str, Any]:
    """List all saved memory facts."""
    return jarvis_runtime.get_memory_facts()


@app.post("/control/memory/facts/{key}", dependencies=[Depends(require_api_key)])
def save_memory_fact(key: str, req: EventRequest) -> Dict[str, Any]:
    """Save a memory fact."""
    value = req.payload.get("value", "")
    category = req.payload.get("category", "general")
    jarvis_runtime.memory.save_fact(key, value, category)
    return {"ok": True, "key": key, "value": value}


@app.delete("/control/memory/facts/{key}", dependencies=[Depends(require_api_key)])
def delete_memory_fact(key: str) -> Dict[str, Any]:
    """Delete a specific memory fact."""
    removed = jarvis_runtime.memory.delete_fact(key)
    return {"ok": removed, "key": key}


@app.get("/control/memory/search", dependencies=[Depends(require_api_key)])
def search_memory(query: str) -> Dict[str, Any]:
    """Search conversation memory."""
    conv = jarvis_runtime.memory.search_conversations(query, limit=10)
    facts = jarvis_runtime.memory.search_facts(query, limit=10)
    return {"ok": True, "query": query, "conversation_matches": conv, "fact_matches": facts}


@app.post("/events", dependencies=[Depends(require_api_key)])
def create_event(req: EventRequest) -> Dict[str, Any]:
    evt = Event(
        session_id=req.session_id,
        type=req.type,
        payload=req.payload,
        level=req.level,  # type: ignore[arg-type]
    )
    jsonl_store.append(evt)
    sqlite_store.append(evt)
    return {"ok": True, "event": asdict(evt)}
