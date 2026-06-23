"""MCP Client — connect to MCP servers, discover tools, invoke them.

JARVIS uses MCP to discover and invoke tools at runtime from one or more
MCP servers. Each server exposes tools that the LLM can call.

Workflow:
  1. Configure MCP servers in VoiceConfig (command + args)
  2. VoiceLLMClient discovers tools and injects descriptions into system prompt
  3. LLM can request tool use with a special syntax
  4. MCP client invokes the tool and injects the result

Transport: stdio (spawn server subprocess) or SSE (future).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("jarvis.voice.mcp")


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class MCPTool:
    """A tool discovered from an MCP server."""

    server_name: str
    name: str
    description: str
    input_schema: Dict[str, Any]

    @property
    def full_name(self) -> str:
        """Unique name: ``{server_name}.{name}``."""
        return f"{self.server_name}.{self.name}"

    def to_description_block(self) -> str:
        """Format as an LLM-friendly description block."""
        schema = json.dumps(self.input_schema, indent=2) if self.input_schema else "{}"
        return (
            f"  • {self.full_name}: {self.description or 'No description'}\n"
            f"    Schema: {schema}\n"
        )


class MCPManager:
    """Manages MCP server connections, tool discovery, and invocation.

    Stores server configs so tools can be invoked after discovery.
    Designed to work with the async MCP SDK while exposing a synchronous
    interface for the voice loop.
    """

    def __init__(self, servers: Optional[List[MCPServerConfig]] = None) -> None:
        self._servers: Dict[str, MCPServerConfig] = {}
        self._tools: Dict[str, MCPTool] = {}
        self._discovered: bool = False

        if servers:
            for s in servers:
                self._servers[s.name] = s

    def add_server(self, config: MCPServerConfig) -> None:
        """Add or update a server configuration."""
        self._servers[config.name] = config
        self._discovered = False

    # ── Discovery ──────────────────────────────────────────────────────────

    def discover(self) -> int:
        """Discover tools from all enabled servers (blocking).

        Runs the async discovery loop synchonously. Returns tool count.
        """
        return asyncio.run(self._discover_all())

    async def _discover_all(self) -> int:
        """Async: connect to all servers and list their tools."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._tools = {}
        total = 0

        for server in self._servers.values():
            if not server.enabled:
                continue

            count = await self._discover_server(server)
            total += count

        self._discovered = True
        logger.info("MCP discovery complete: %d tools across %d servers", total, len(self._servers))
        return total

    async def _discover_server(self, server: MCPServerConfig) -> int:
        """Connect to one server and discover its tools."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        try:
            env = dict(os.environ)
            env.update(server.env)

            params = StdioServerParameters(
                command=server.command,
                args=server.args,
                env=env,
            )

            count = 0
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()

                    for tool in result.tools:
                        discovered = MCPTool(
                            server_name=server.name,
                            name=tool.name,
                            description=tool.description or "",
                            input_schema=tool.inputSchema or {},
                        )
                        self._tools[discovered.full_name] = discovered
                        count += 1

            logger.info("Server '%s': %d tools", server.name, count)
            return count

        except Exception as exc:
            logger.error("Server '%s' failed: %s", server.name, exc)
            return 0

    # ── Tool invocation ───────────────────────────────────────────────────

    def call_tool(self, full_name: str, arguments: Dict[str, Any]) -> str:
        """Call a tool by its full name (blocking).

        Args:
            full_name: ``{server_name}.{tool_name}`` format.
            arguments: Tool input arguments.

        Returns:
            Tool result as a string.
        """
        return asyncio.run(self._call_tool_async(full_name, arguments))

    async def _call_tool_async(self, full_name: str, arguments: Dict[str, Any]) -> str:
        """Async: reconnect to the server and call the tool."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        tool = self._tools.get(full_name)
        if not tool:
            return f"Error: unknown tool '{full_name}'"

        server = self._servers.get(tool.server_name)
        if not server:
            return f"Error: server '{tool.server_name}' not configured"

        try:
            env = dict(os.environ)
            env.update(server.env)

            params = StdioServerParameters(
                command=server.command,
                args=server.args,
                env=env,
            )

            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool.name, arguments)

                    if hasattr(result, 'content') and result.content:
                        parts = []
                        for item in result.content:
                            if hasattr(item, 'text'):
                                parts.append(item.text)
                            elif hasattr(item, 'data'):
                                parts.append(str(item.data))
                        return "\n".join(parts)

            return "Tool executed but returned no content."

        except Exception as exc:
            logger.error("Tool '%s' failed: %s", full_name, exc)
            return f"Error executing tool '{full_name}': {exc}"

    # ── LLM interface ─────────────────────────────────────────────────────

    def tools_for_llm(self) -> str:
        """Format all discovered tools for injection into the LLM system prompt.

        Returns a block of text describing each tool, its purpose, and its
        input schema. The LLM can then request tool calls.
        """
        if not self._tools:
            return ""

        lines = [
            "## Available MCP Tools\n",
            "You can call these tools by including a tool call in your response.",
            "Format: TOOL_CALL: server.tool_name | {\"key\": \"value\"}",
            "",
        ]

        # Group by server
        by_server: Dict[str, List[MCPTool]] = {}
        for tool in self._tools.values():
            by_server.setdefault(tool.server_name, []).append(tool)

        for srv in sorted(by_server):
            lines.append(f"### Server: {srv}")
            for t in sorted(by_server[srv], key=lambda x: x.name):
                lines.append(t.to_description_block())
            lines.append("")

        return "\n".join(lines)

    def parse_tool_call(self, text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Parse a tool call from LLM response text.

        Looks for pattern: ``TOOL_CALL: server.tool | {...}``

        Returns:
            (full_name, arguments_dict) or None if no tool call found.
        """
        import re

        pattern = r"TOOL_CALL:\s*([\w.]+)\s*\|\s*(\{.*\})"
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            return None

        full_name = match.group(1).strip()
        try:
            args = json.loads(match.group(2))
        except json.JSONDecodeError:
            args = {}

        return full_name, args

    # ── Utilities ──────────────────────────────────────────────────────────

    def tool_count(self) -> int:
        return len(self._tools)

    def tool_names(self) -> List[str]:
        return sorted(self._tools.keys())

    def cleanup(self) -> None:
        """Release resources."""
        self._tools.clear()
        self._discovered = False
        logger.debug("MCPManager cleaned up")
