import importlib
import os
import time

from fastapi.testclient import TestClient


def test_api_ingest_to_approval_to_execute(tmp_path):
    os.environ["JARVIS_API_KEY"] = "test-key"

    api_module = importlib.import_module("jarvis.api.app")

    api_module.jarvis_runtime = api_module.JarvisApp(approvals_db_path=str(tmp_path / "approvals.db"))

    class _FakeHermes:
        def run_tool(self, name, arguments):
            return {"ok": True, "tool": name, "arguments": arguments}

    api_module.jarvis_runtime.hermes = _FakeHermes()

    client = TestClient(api_module.app)
    headers = {"x-api-key": "test-key"}

    ingest = client.post(
        "/control/ingest",
        headers=headers,
        json={"session_id": "api-s1", "text": "run command echo hi"},
    )
    assert ingest.status_code == 200
    payload = ingest.json()
    assert payload["requires_approval"] is True
    approval_id = payload["approval_id"]

    listed = client.get("/control/approvals", headers=headers)
    assert listed.status_code == 200
    ids = [x["approval_id"] for x in listed.json()["approvals"]]
    assert approval_id in ids

    approved = client.post(f"/control/approvals/{approval_id}/approve", headers=headers)
    assert approved.status_code == 200
    body = approved.json()
    assert body["ok"] is True
    assert body["executed"] is True


def test_api_rejects_invalid_key(tmp_path):
    os.environ["JARVIS_API_KEY"] = "secret"

    api_module = importlib.import_module("jarvis.api.app")

    api_module.jarvis_runtime = api_module.JarvisApp(approvals_db_path=str(tmp_path / "approvals-auth.db"))
    client = TestClient(api_module.app)

    r = client.get("/control/approvals", headers={"x-api-key": "wrong"})
    assert r.status_code == 401


def test_api_sweeper_start_stop_and_reclaim(tmp_path):
    os.environ["JARVIS_API_KEY"] = "test-key"

    api_module = importlib.import_module("jarvis.api.app")
    api_module.stop_sweeper()
    api_module.jarvis_runtime = api_module.JarvisApp(
        approvals_db_path=str(tmp_path / "approvals-sweeper.db"),
        approval_lease_seconds=0.1,
    )

    # Create and claim one approval, then force stale lease.
    first = api_module.jarvis_runtime.handle_text("api-sweep", "run command date")
    approval_id = first["approval_id"]
    claimed = api_module.jarvis_runtime.approvals.claim_for_execution(
        approval_id,
        worker_id="worker-a",
        lease_seconds=0.1,
    )
    assert claimed is not None

    stale_ts = time.time() - 10.0
    with api_module.jarvis_runtime.approvals._conn() as conn:
        conn.execute(
            "UPDATE approvals SET lease_until = ?, updated_at = ? WHERE approval_id = ?",
            (stale_ts, stale_ts, approval_id),
        )
        conn.commit()

    api_module.start_sweeper(interval_seconds=0.01)
    time.sleep(0.05)
    api_module.stop_sweeper()

    item = api_module.jarvis_runtime.approvals.get(approval_id)
    assert item is not None
    assert item.status == "pending"


def test_api_metrics_endpoint(tmp_path):
    os.environ["JARVIS_API_KEY"] = "test-key"

    api_module = importlib.import_module("jarvis.api.app")
    api_module.jarvis_runtime = api_module.JarvisApp(approvals_db_path=str(tmp_path / "approvals-api-metrics.db"))
    client = TestClient(api_module.app)
    headers = {"x-api-key": "test-key"}

    # Empty metrics.
    r = client.get("/control/metrics", headers=headers)
    assert r.status_code == 200
    m = r.json()["metrics"]
    assert m["total"] == 0

    # Ingest one, check pending count.
    client.post("/control/ingest", headers=headers, json={"session_id": "m1", "text": "run command echo 1"})
    r = client.get("/control/metrics", headers=headers)
    assert r.json()["metrics"]["pending"] == 1
    assert r.json()["metrics"]["total"] == 1


def test_dashboard_loads_and_shows_metrics(tmp_path):
    os.environ["JARVIS_API_KEY"] = "test-key"

    api_module = importlib.import_module("jarvis.api.app")
    api_module.jarvis_runtime = api_module.JarvisApp(approvals_db_path=str(tmp_path / "approvals-dash.db"))

    class _DFake:
        def run_tool(self, name, arguments):
            return {"ok": True, "tool": name}

    api_module.jarvis_runtime.hermes = _DFake()
    client = TestClient(api_module.app)

    # Dashboard loads unauthenticated.
    r = client.get("/dashboard")
    assert r.status_code == 200
    html = r.text
    assert "JARVIS Control Dashboard" in html
    assert "Pending" in html
    assert "Total" in html
    assert "<div class=\"empty\">No pending approvals</div>" in html

    # Ingest one, check dashboard shows it.
    client.post(
        "/control/ingest",
        headers={"x-api-key": "test-key"},
        json={"session_id": "dash1", "text": "run command whoami"},
    )
    r2 = client.get("/dashboard")
    assert r2.status_code == 200
    assert "0s" in r2.text  # age
    assert "terminal" in r2.text  # action from router

    # Htmx partials work.
    metrics_partial = client.get("/dashboard/_metrics")
    assert metrics_partial.status_code == 200
    assert "green" in metrics_partial.text

    pending_partial = client.get("/dashboard/_pending")
    assert pending_partial.status_code == 200
    assert "<table>" in pending_partial.text


def test_jarvis_health_script_exists_and_compiles():
    import importlib.util
    spec = importlib.util.spec_from_file_location("health", os.path.expanduser("~/.hermes/scripts/jarvis-health.py"))
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    # Just check it compiles without error by loading source.
    with open(spec.origin) as f:
        compile(f.read(), spec.origin, "exec")
    assert True


def test_system_status_endpoint(tmp_path):
    os.environ["JARVIS_API_KEY"] = "test-key"

    api_module = importlib.import_module("jarvis.api.app")
    api_module.jarvis_runtime = api_module.JarvisApp(
        approvals_db_path=str(tmp_path / "approvals-status.db"),
    )

    class _FakeHermes:
        def run_tool(self, name, arguments):
            return {"ok": True, "tool": name}

    api_module.jarvis_runtime.hermes = _FakeHermes()
    client = TestClient(api_module.app)

    # Status without auth
    r = client.get("/system/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["api"] == "healthy"
    assert "voice_running" in body
    assert "approvals_pending" in body
    assert "drift_missing" in body
    assert "capability_count" in body
    assert isinstance(body["drift_missing"], list)
    assert isinstance(body["approvals_pending"], int)

    # After creating a pending approval, pending count increases
    client.post(
        "/control/ingest",
        headers={"x-api-key": "test-key"},
        json={"session_id": "s1", "text": "run command echo hi"},
    )
    r2 = client.get("/system/status")
    assert r2.status_code == 200
    assert r2.json()["approvals_pending"] >= 1
