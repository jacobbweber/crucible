"""Model Context Protocol (MCP) client supervisor managing stdio and SSE connections."""

import contextlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client

from agent_os.domain.policy import ActionTier
from agent_os.domain.tools import (
    ToolDefinition,
    ToolExecutionResult,
    ToolParameterSchema,
)


@dataclass
class McpServerConfig:
    """Configuration for connecting to an external or local MCP server."""

    server_id: str
    transport: str = "stdio"  # "stdio" | "sse"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None


READ_ACTION_PATTERNS = re.compile(
    r"\b(get|list|read|search|query|status|inspect|check|audit|view|fetch|echo)\b",
    re.IGNORECASE,
)


class McpClientSupervisor:
    """Manages connection lifecycles, tool discovery, and execution against MCP servers."""

    def __init__(self) -> None:
        self._exit_stacks: dict[str, contextlib.AsyncExitStack] = {}
        self._sessions: dict[str, ClientSession] = {}
        self._tool_to_server: dict[str, str] = {}
        self._tool_definitions: dict[str, ToolDefinition] = {}

    def is_connected(self, server_id: str) -> bool:
        """Check if an MCP server connection is active."""
        return server_id in self._sessions

    def list_connected_servers(self) -> list[str]:
        """Return list of active server IDs."""
        return list(self._sessions.keys())

    def get_server_tools(self, server_id: str) -> list[str]:
        """Return list of tool names associated with a server ID."""
        return [t for t, sid in self._tool_to_server.items() if sid == server_id]

    def get_registered_tools(self) -> list[ToolDefinition]:
        """Return all discovered tool definitions across all active MCP servers."""
        return list(self._tool_definitions.values())

    async def connect(self, config: McpServerConfig) -> list[ToolDefinition]:
        """Connect to an MCP server, perform handshake, and discover capabilities."""
        if config.server_id in self._sessions:
            await self.disconnect(config.server_id)

        stack = contextlib.AsyncExitStack()
        try:
            if config.transport == "stdio":
                if not config.command:
                    raise ValueError(f"Stdio transport for '{config.server_id}' requires a 'command'.")
                params = StdioServerParameters(
                    command=config.command,
                    args=config.args,
                    env=config.env or None,
                    cwd=config.cwd or None,
                )
                read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
            elif config.transport == "sse":
                if not config.url:
                    raise ValueError(f"SSE transport for '{config.server_id}' requires a 'url'.")
                read_stream, write_stream = await stack.enter_async_context(sse_client(config.url))
            else:
                raise ValueError(f"Unsupported transport '{config.transport}'. Must be 'stdio' or 'sse'.")

            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()

            self._exit_stacks[config.server_id] = stack
            self._sessions[config.server_id] = session

            # Discover tools
            tools_result = await session.list_tools()
            discovered: list[ToolDefinition] = []

            for mcp_tool in tools_result.tools:
                tool_name = f"mcp_{config.server_id}_{mcp_tool.name}"
                desc = mcp_tool.description or f"MCP tool: {mcp_tool.name}"

                # Infer action tier
                tier = (
                    ActionTier.READ
                    if READ_ACTION_PATTERNS.search(mcp_tool.name) or READ_ACTION_PATTERNS.search(desc)
                    else ActionTier.STATE_CHANGE
                )

                # Convert JSON schema parameters
                parameters: list[ToolParameterSchema] = []
                schema = getattr(mcp_tool, "input_schema", None) or getattr(mcp_tool, "inputSchema", None) or {}
                properties = schema.get("properties", {})
                required_set = set(schema.get("required", []))

                for p_name, p_spec in properties.items():
                    p_type = p_spec.get("type", "string")
                    p_desc = p_spec.get("description", p_name)
                    p_req = p_name in required_set
                    p_default = p_spec.get("default")
                    parameters.append(
                        ToolParameterSchema(
                            name=p_name,
                            type_name=p_type,
                            description=p_desc,
                            required=p_req,
                            default=p_default,
                        )
                    )

                tool_def = ToolDefinition(
                    name=tool_name,
                    description=desc,
                    action_tier=tier,
                    parameters=parameters,
                )
                self._tool_to_server[tool_name] = config.server_id
                self._tool_definitions[tool_name] = tool_def
                discovered.append(tool_def)

            return discovered

        except Exception:
            await stack.aclose()
            raise

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        """Invoke an MCP tool through its active server session."""
        server_id = self._tool_to_server.get(tool_name)
        if not server_id or server_id not in self._sessions:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                output="",
                error=f"Tool '{tool_name}' not found on any active MCP connection.",
            )

        session = self._sessions[server_id]
        # Strip prefix: mcp_<server_id>_<actual_name>
        prefix = f"mcp_{server_id}_"
        actual_name = tool_name[len(prefix) :] if tool_name.startswith(prefix) else tool_name

        try:
            res = await session.call_tool(actual_name, arguments=arguments)
            outputs: list[str] = []
            is_error = getattr(res, "isError", False)

            for content_block in res.content:
                text = getattr(content_block, "text", None)
                if text is not None:
                    outputs.append(text)
                else:
                    outputs.append(str(content_block))

            merged_output = "\n".join(outputs) if outputs else "Tool execution succeeded with no content."
            if is_error:
                return ToolExecutionResult(
                    tool_name=tool_name,
                    success=False,
                    output="",
                    error=merged_output,
                )
            return ToolExecutionResult(tool_name=tool_name, success=True, output=merged_output)

        except Exception as exc:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                output="",
                error=f"MCP call failed: {exc}",
            )

    async def disconnect(self, server_id: str) -> bool:
        """Disconnect an MCP server and unregister its tools."""
        stack = self._exit_stacks.pop(server_id, None)
        self._sessions.pop(server_id, None)

        # Remove tool mappings
        to_remove = [k for k, v in self._tool_to_server.items() if v == server_id]
        for t in to_remove:
            del self._tool_to_server[t]
            self._tool_definitions.pop(t, None)

        if stack:
            await stack.aclose()
            return True
        return False

    async def disconnect_all(self) -> None:
        """Disconnect all active MCP connections and clean up resources."""
        server_ids = list(self._sessions.keys())
        for s_id in server_ids:
            await self.disconnect(s_id)
