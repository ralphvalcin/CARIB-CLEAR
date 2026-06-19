from jarvis.hermes_bridge.client import CLIHermesClient


def test_chat_returns_error_when_binary_missing():
    c = CLIHermesClient(hermes_bin="definitely-not-a-real-hermes-bin")
    out = c.chat("hello")
    assert "hermes_chat_error" in out


def test_run_tool_returns_error_shape_when_binary_missing():
    c = CLIHermesClient(hermes_bin="definitely-not-a-real-hermes-bin")
    res = c.run_tool("web_search", {"query": "jarvis", "limit": 1})
    assert res["ok"] is False
    assert res["tool"] == "web_search"
    assert res["transport"] == "hermes-cli"
