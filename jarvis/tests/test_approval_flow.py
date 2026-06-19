import time

from jarvis.main import JarvisApp


class _FakeHermes:
    def __init__(self):
        self.calls = 0

    def run_tool(self, name, arguments):
        self.calls += 1
        return {"ok": True, "tool": name, "arguments": arguments, "transport": "fake", "call_count": self.calls}


class _FlakyHermes:
    def __init__(self, fail_times: int):
        self.calls = 0
        self.fail_times = fail_times

    def run_tool(self, name, arguments):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("simulated tool failure")
        return {"ok": True, "tool": name, "arguments": arguments, "transport": "fake", "call_count": self.calls}


def test_requires_approval_then_approve_executes(tmp_path):
    db_path = tmp_path / "approvals.db"
    app = JarvisApp(approvals_db_path=str(db_path))
    app.hermes = _FakeHermes()

    first = app.handle_text("s-approval", "run command echo hello")
    assert first["requires_approval"] is True
    approval_id = first["approval_id"]

    pending = app.list_pending_approvals()
    assert any(x["approval_id"] == approval_id for x in pending["pending"])

    approved = app.approve_action(approval_id)
    assert approved["ok"] is True
    assert approved["executed"] is True
    assert approved["approval"]["status"] == "executed"
    assert approved["tool_result"]["tool"] == "terminal"


def test_requires_approval_then_deny(tmp_path):
    db_path = tmp_path / "approvals.db"
    app = JarvisApp(approvals_db_path=str(db_path))
    first = app.handle_text("s-deny", "run command whoami")
    approval_id = first["approval_id"]

    denied = app.deny_action(approval_id, reason="no shell allowed")
    assert denied["ok"] is True
    assert denied["approval"]["status"] == "denied"


def test_approval_queue_persists_across_app_restarts(tmp_path):
    db_path = tmp_path / "approvals-persist.db"

    app1 = JarvisApp(approvals_db_path=str(db_path))
    first = app1.handle_text("s-persist", "run command date")
    approval_id = first["approval_id"]

    app2 = JarvisApp(approvals_db_path=str(db_path))
    pending = app2.list_pending_approvals()
    ids = [x["approval_id"] for x in pending["pending"]]
    assert approval_id in ids


def test_double_approve_is_idempotent_executes_once(tmp_path):
    db_path = tmp_path / "approvals-idempotent.db"
    app = JarvisApp(approvals_db_path=str(db_path))
    fake = _FakeHermes()
    app.hermes = fake

    first = app.handle_text("s-idempotent", "run command uptime")
    approval_id = first["approval_id"]

    r1 = app.approve_action(approval_id)
    r2 = app.approve_action(approval_id)

    assert r1["ok"] is True
    assert r1["executed"] is True
    assert r2["ok"] is True
    assert r2["executed"] is True
    assert fake.calls == 1
    assert r2["approval"]["status"] == "executed"


def test_approved_item_is_not_reclaimed_before_lease_expiry(tmp_path):
    db_path = tmp_path / "approvals-lease-active.db"
    app = JarvisApp(approvals_db_path=str(db_path), approval_lease_seconds=60.0)

    first = app.handle_text("s-lease-active", "run command pwd")
    approval_id = first["approval_id"]

    claimed = app.approvals.claim_for_execution(approval_id, worker_id="w1", lease_seconds=60.0)
    assert claimed is not None
    assert claimed.status == "approved"

    second_claim = app.approvals.claim_for_execution(approval_id, worker_id="w2", lease_seconds=60.0)
    assert second_claim is None


def test_stale_approved_item_can_be_reclaimed_after_lease_expiry(tmp_path):
    db_path = tmp_path / "approvals-lease-stale.db"
    app = JarvisApp(approvals_db_path=str(db_path), approval_lease_seconds=1.0)
    fake = _FakeHermes()
    app.hermes = fake

    first = app.handle_text("s-lease-stale", "run command whoami")
    approval_id = first["approval_id"]

    claimed = app.approvals.claim_for_execution(approval_id, worker_id="w1", lease_seconds=1.0)
    assert claimed is not None

    stale_ts = time.time() - 10.0
    with app.approvals._conn() as conn:
        conn.execute(
            "UPDATE approvals SET updated_at = ?, lease_until = ? WHERE approval_id = ?",
            (stale_ts, stale_ts, approval_id),
        )
        conn.commit()

    result = app.approve_action(approval_id)
    assert result["ok"] is True
    assert result["executed"] is True
    assert fake.calls == 1
    assert result["approval"]["status"] == "executed"


def test_failed_approval_retries_then_executes(tmp_path):
    db_path = tmp_path / "approvals-retry.db"
    app = JarvisApp(approvals_db_path=str(db_path), max_execution_retries=2)
    flaky = _FlakyHermes(fail_times=1)
    app.hermes = flaky

    first = app.handle_text("s-retry", "run command id")
    approval_id = first["approval_id"]

    r1 = app.approve_action(approval_id)
    assert r1["ok"] is False
    assert r1["approval"]["status"] == "pending"
    assert r1["approval"]["retry_count"] == 1

    r2 = app.approve_action(approval_id)
    assert r2["ok"] is True
    assert r2["executed"] is True
    assert r2["approval"]["status"] == "executed"


def test_failed_approval_exhausts_retries_and_terminal_state(tmp_path):
    db_path = tmp_path / "approvals-retry-exhaust.db"
    app = JarvisApp(approvals_db_path=str(db_path), max_execution_retries=1)
    flaky = _FlakyHermes(fail_times=10)
    app.hermes = flaky

    first = app.handle_text("s-retry-exhaust", "run command uname")
    approval_id = first["approval_id"]

    r1 = app.approve_action(approval_id)
    assert r1["ok"] is False
    assert r1["approval"]["status"] == "pending"

    r2 = app.approve_action(approval_id)
    assert r2["ok"] is False
    assert r2["approval"]["status"] == "failed"

    r3 = app.approve_action(approval_id)
    assert r3["ok"] is False
    assert r3["approval"]["status"] == "failed"
    assert r3["error_code"] == "APPROVAL_EXECUTION_FAILED"


def test_approve_unknown_id_returns_error_code(tmp_path):
    db_path = tmp_path / "approvals-missing.db"
    app = JarvisApp(approvals_db_path=str(db_path))

    out = app.approve_action("missing-id")
    assert out["ok"] is False
    assert out["error_code"] == "APPROVAL_NOT_FOUND"


def test_deny_unknown_id_returns_error_code(tmp_path):
    db_path = tmp_path / "approvals-missing-deny.db"
    app = JarvisApp(approvals_db_path=str(db_path))

    out = app.deny_action("missing-id")
    assert out["ok"] is False
    assert out["error_code"] == "APPROVAL_NOT_FOUND"


def test_approval_queue_metrics_returns_counts(tmp_path):
    db_path = tmp_path / "approvals-metrics.db"
    app = JarvisApp(approvals_db_path=str(db_path))

    # No approvals yet.
    m0 = app.metrics()
    assert m0["ok"] is True
    assert m0["metrics"]["total"] == 0
    assert m0["metrics"]["pending"] == 0

    # Create one pending.
    app.handle_text("s-m1", "run command echo 1")
    m1 = app.metrics()
    assert m1["metrics"]["total"] == 1
    assert m1["metrics"]["pending"] == 1

    # Create another and approve + execute it.
    with app.approvals._conn() as conn:
        conn.execute(
            "INSERT INTO approvals (approval_id, session_id, action, payload_json, reason, status,"
            " result_json, created_at, updated_at, claimed_by, claimed_at, lease_until, retry_count, last_error)"
            " VALUES ('m2', 's-m2', 'web_search', '{}', 'test', 'executed',"
            " '{}', 1, 1, 'w1', 1, NULL, 0, NULL)"
        )
        conn.commit()

    m2 = app.metrics()
    assert m2["metrics"]["total"] == 2
    assert m2["metrics"]["pending"] == 1
    assert m2["metrics"]["executed"] == 1
