"""Tool lifecycle management tools allowing the companion to inspect, refactor, and retire its own tools."""

import ast
from collections.abc import Callable
from typing import Any

from agent_os.domain.policy import ActionTier
from agent_os.domain.tools import (
    ToolDefinition,
    ToolExecutionResult,
    ToolParameterSchema,
)
from agent_os.mcp.hub import McpHubManager


def _p(
    name: str, type_name: str, desc: str, req: bool = True, default: Any = None
) -> ToolParameterSchema:
    return ToolParameterSchema(
        name=name, type_name=type_name, description=desc, required=req, default=default
    )


class ToolManagementSuite:
    """Tool suite providing agent access to inspect, refactor, and retire synthesized tools."""

    def __init__(
        self,
        mcp_hub: McpHubManager,
        on_reload: Callable[[], Any] | None = None,
    ) -> None:
        self.mcp_hub = mcp_hub
        self.on_reload = on_reload

    def get_definitions(self) -> list[ToolDefinition]:
        """Return tool definitions and schemas for tool lifecycle operations."""
        return [
            ToolDefinition(
                name="tool_inspect",
                description="Inspect the Python source code and parameter signature of an existing FastMCP tool.",
                action_tier=ActionTier.READ,
                parameters=[
                    _p(
                        "tool_name",
                        "string",
                        "Name of the tool function to inspect (e.g. 'list_drive_contents').",
                    ),
                ],
            ),
            ToolDefinition(
                name="tool_refactor",
                description="Refactor or fix the source code of an existing FastMCP tool with pre-flight syntax validation.",
                action_tier=ActionTier.STATE_CHANGE,
                parameters=[
                    _p("tool_name", "string", "Name of the tool function to refactor."),
                    _p(
                        "new_code",
                        "string",
                        "Complete updated Python function code decorated with @hub.tool().",
                    ),
                ],
            ),
            ToolDefinition(
                name="tool_retire",
                description="Retire and remove an obsolete or broken FastMCP tool from the dynamic tool registry.",
                action_tier=ActionTier.DESTRUCTIVE,
                parameters=[
                    _p("tool_name", "string", "Name of the tool function to retire."),
                ],
            ),
        ]

    def tool_inspect(self, tool_name: str) -> ToolExecutionResult:
        """Inspect source code of a registered tool."""
        try:
            code = self.mcp_hub.get_tool_code(tool_name)
            if not code:
                return ToolExecutionResult(
                    tool_name="tool_inspect",
                    success=False,
                    output="",
                    error=f"Tool '{tool_name}' not found in active FastMCP hub.",
                )
            return ToolExecutionResult(
                tool_name="tool_inspect",
                success=True,
                output=f"Source code for tool `{tool_name}`:\n```python\n{code}\n```",
            )
        except Exception as exc:
            return ToolExecutionResult(
                tool_name="tool_inspect", success=False, output="", error=str(exc)
            )

    def tool_refactor(self, tool_name: str, new_code: str) -> ToolExecutionResult:
        """Refactor code of a registered tool with syntax validation."""
        try:
            # 1. Syntax check
            try:
                ast.parse(new_code)
            except SyntaxError as syn_err:
                return ToolExecutionResult(
                    tool_name="tool_refactor",
                    success=False,
                    output="",
                    error=f"Syntax error in replacement code: {syn_err}",
                )

            # 2. Refactor in hub_server.py
            ok = self.mcp_hub.refactor_tool_code(tool_name, new_code)
            if not ok:
                return ToolExecutionResult(
                    tool_name="tool_refactor",
                    success=False,
                    output="",
                    error=f"Tool '{tool_name}' could not be located in hub_server.py to refactor.",
                )

            # 3. Reload in kernel if callback provided
            if self.on_reload:
                try:
                    self.on_reload()
                except Exception as reload_err:
                    return ToolExecutionResult(
                        tool_name="tool_refactor",
                        success=True,
                        output=f"Tool `{tool_name}` refactored in file, but hot-reload warned: {reload_err}",
                    )

            return ToolExecutionResult(
                tool_name="tool_refactor",
                success=True,
                output=f"Tool `{tool_name}` refactored and hot-reloaded successfully.",
            )
        except Exception as exc:
            return ToolExecutionResult(
                tool_name="tool_refactor", success=False, output="", error=str(exc)
            )

    def tool_retire(self, tool_name: str) -> ToolExecutionResult:
        """Retire a registered tool."""
        try:
            ok = self.mcp_hub.retire_tool_code(tool_name)
            if not ok:
                return ToolExecutionResult(
                    tool_name="tool_retire",
                    success=False,
                    output="",
                    error=f"Tool '{tool_name}' not found in hub_server.py to retire.",
                )

            if self.on_reload:
                try:
                    self.on_reload()
                except Exception as reload_err:
                    return ToolExecutionResult(
                        tool_name="tool_retire",
                        success=True,
                        output=f"Tool `{tool_name}` retired from file, but hot-reload warned: {reload_err}",
                    )

            return ToolExecutionResult(
                tool_name="tool_retire",
                success=True,
                output=f"Tool `{tool_name}` retired and removed from active FastMCP registry.",
            )
        except Exception as exc:
            return ToolExecutionResult(
                tool_name="tool_retire", success=False, output="", error=str(exc)
            )
