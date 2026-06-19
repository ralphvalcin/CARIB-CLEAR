from jarvis.main import JarvisApp


class _FakeHermes:
    def run_tool(self, name, arguments):
        return {"ok": True, "tool": name, "arguments": arguments, "transport": "fake"}


def _make_app(tmp_path, **kwargs) -> JarvisApp:
    """Helper: create JarvisApp with LLM disabled (avoids Ollama timeouts)."""
    app = JarvisApp(
        approvals_db_path=str(tmp_path / "approvals.db"),
        memory_db_path=str(tmp_path / "conv_memory.db"),
        **kwargs,
    )
    app.llm.enabled = False  # use fallback responses, no Ollama
    return app


def test_handle_text_drift_check_path(tmp_path):
    app = _make_app(tmp_path)
    res = app.handle_text("s1", "run drift check")
    assert res["path"] == "drift_check"
    assert "drift_report" in res


def test_handle_text_tool_action_with_allow_policy(tmp_path):
    app = _make_app(tmp_path)
    app.hermes = _FakeHermes()
    res = app.handle_text("s2", "search latest jarvis frameworks")
    assert res["path"] == "tool_action"
    assert res["tool_result"]["ok"] is True
    assert res["tool_result"]["tool"] == "web_search"


def test_handle_text_direct_response_returns_fallback(tmp_path):
    """When LLM is disabled, direct_response should return fallback text."""
    app = _make_app(tmp_path)
    app.llm.enabled = False
    res = app.handle_text("s3", "hello")
    assert res["path"] == "direct_response"
    assert "response" in res
    assert "llm_available" not in res or res.get("llm_available") is False
    assert len(res["response"]) > 0


def test_handle_text_direct_response_has_llm_model(tmp_path):
    app = _make_app(tmp_path)
    res = app.handle_text("s4", "help")
    assert "llm_model" in res
    assert res["llm_model"] == "llama3.2:3b"


def test_handle_text_fallback_route(tmp_path):
    """Text that doesn't match any route should go to direct_response (LLM)."""
    app = _make_app(tmp_path)
    res = app.handle_text("s5", "what's on your mind")
    assert res["path"] == "direct_response"
    assert "response" in res
    assert len(res["response"]) > 0


def test_handle_text_memory_save(tmp_path):
    app = _make_app(tmp_path)
    res = app.handle_text("s6", "remember my name is Ralph")
    assert res["path"] == "memory_action"
    assert res["action"] == "memory_save"
    assert res["ok"] is True
    assert "Ralph" in res.get("response", "")


def test_handle_text_memory_search(tmp_path):
    app = _make_app(tmp_path)
    # First save a fact
    app.memory.save_fact("api_keys", "in .env file")
    # Then search
    res = app.handle_text("s7", "recall api_keys")
    assert res["path"] == "memory_action"
    assert res["action"] == "memory_search"
    assert res["ok"] is True
    assert len(res["fact_matches"]) > 0
    assert "api_keys" in str(res["fact_matches"])


def test_handle_text_memory_clear(tmp_path):
    app = _make_app(tmp_path)
    # Save something first
    app.memory.save_fact("test_key", "test_value")
    res = app.handle_text("s8", "forget")
    assert res["path"] == "memory_action"
    assert res["action"] == "memory_clear"
    assert res["ok"] is True


def test_handle_text_drift_repair_path(tmp_path):
    app = _make_app(tmp_path)
    res = app.handle_text("s9", "fix yourself")
    assert res["path"] == "drift_repair"
    assert "repair_result" in res
    assert "recheck" in res


def test_memory_persists_across_calls(tmp_path):
    """Saved memory facts are retrievable across different sessions."""
    app = _make_app(tmp_path)
    app.memory.save_fact("preferred_language", "Python")
    app2 = _make_app(tmp_path)
    val = app2.memory.get_fact("preferred_language")
    assert val == "Python"


def test_auto_repair_on_drift_check(tmp_path):
    """When auto_repair_drift is on, drift_check includes repair attempt."""
    app = _make_app(tmp_path, auto_repair_drift=True)
    res = app.handle_text("s10", "run drift check")
    if res["drift_report"]["missing"]:
        assert "auto_repair" in res


class TestSystemPreamble:
    def test_preamble_includes_llm_status_when_enabled(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        app.llm._available = True
        app.llm.enabled = True
        preamble = app._get_preamble()
        assert "Using local LLM: llama3.2:3b" in preamble

    def test_preamble_skips_llm_status_when_disabled(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        app.llm._available = False
        preamble = app._get_preamble()
        assert "Using local LLM:" not in preamble

    def test_preamble_respects_default_identity(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        res = app.handle_text("s21", "who are you")
        text = res.get("response", "")
        assert "JARVIS" in text or "hello" in text.lower()

    def test_preamble_mentions_local_model_when_available(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        app.llm._available = True
        app.llm.enabled = True
        preamble = app._get_preamble()
        assert "llama3.2:3b" in preamble
