"""Tests for MCP client module (data structures and parsing only).

Actual server connection tests require a running MCP server.
These tests validate the tool data model and tool call parsing logic.
"""

from __future__ import annotations

from typing import Any, Dict

from jarvis.voice.mcp_client import MCPManager, MCPServerConfig, MCPTool


def test_mcp_tool_full_name() -> None:
    """Verify full_name property combines server and tool name."""
    tool = MCPTool(
        server_name="weather",
        name="get_forecast",
        description="Get weather forecast",
        input_schema={"type": "object", "properties": {"city": {"type": "string"}}},
    )
    assert tool.full_name == "weather.get_forecast"


def test_mcp_tool_description_block() -> None:
    """Verify tool description formatting."""
    tool = MCPTool(
        server_name="weather",
        name="get_forecast",
        description="Get weather forecast for a city",
        input_schema={"type": "object"},
    )
    block = tool.to_description_block()
    assert "weather.get_forecast" in block
    assert "Get weather forecast" in block
    assert "type" in block or "object" in block


def test_mcp_manager_empty() -> None:
    """Verify empty MCP manager state."""
    mgr = MCPManager()
    assert mgr.tool_count() == 0
    assert mgr.tool_names() == []
    assert mgr.tools_for_llm() == ""


def test_mcp_parse_tool_call_valid() -> None:
    """Verify parsing a valid tool call from LLM response."""
    mgr = MCPManager()
    text = 'Some response text. TOOL_CALL: weather.get_forecast | {"city": "Port-au-Prince"} More text.'
    result = mgr.parse_tool_call(text)
    assert result is not None
    full_name, args = result
    assert full_name == "weather.get_forecast"
    assert args == {"city": "Port-au-Prince"}


def test_mcp_parse_tool_call_no_tool() -> None:
    """Verify no match when there's no tool call syntax."""
    mgr = MCPManager()
    text = "The weather in Port-au-Prince is sunny."
    result = mgr.parse_tool_call(text)
    assert result is None


def test_mcp_parse_tool_call_no_args() -> None:
    """Verify parsing with empty arguments."""
    mgr = MCPManager()
    text = 'TOOL_CALL: weather.get_forecast | {}'
    result = mgr.parse_tool_call(text)
    assert result is not None
    full_name, args = result
    assert full_name == "weather.get_forecast"
    assert args == {}


def test_mcp_parse_tool_call_invalid_json() -> None:
    """Verify fallback to empty dict on invalid JSON."""
    mgr = MCPManager()
    text = 'TOOL_CALL: weather.get_forecast | {bad json}'
    result = mgr.parse_tool_call(text)
    assert result is not None
    _, args = result
    assert args == {}


def test_mcp_parse_tool_call_multiline() -> None:
    """Verify parsing multiline responses with tool calls."""
    mgr = MCPManager()
    text = """I'll check the weather for you.

TOOL_CALL: weather.get_forecast | {"city": "Kingston", "days": 3}

Let me get the results."""
    result = mgr.parse_tool_call(text)
    assert result is not None
    full_name, args = result
    assert full_name == "weather.get_forecast"
    assert args == {"city": "Kingston", "days": 3}


def test_mcp_server_config_from_dict() -> None:
    """Verify MCPServerConfig creation."""
    config = MCPServerConfig(
        name="test-server",
        command="uvx",
        args=["test-mcp"],
        enabled=True,
    )
    assert config.name == "test-server"
    assert config.command == "uvx"
    assert config.args == ["test-mcp"]
    assert config.enabled is True


def test_mcp_disabled_server_skipped() -> None:
    """Verify disabled servers don't affect tool count."""
    mgr = MCPManager()
    mgr.add_server(MCPServerConfig(
        name="disabled-server",
        command="nonexistent",
        enabled=False,
    ))
    assert mgr.tool_count() == 0
    assert mgr._discovered is False
