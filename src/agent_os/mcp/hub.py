"""Native dynamic MCP Hub manager hosting local agent-synthesized tools."""

import sys
from pathlib import Path
from typing import Any

from agent_os.domain.tools import ToolDefinition
from agent_os.mcp.client import McpClientSupervisor, McpServerConfig

DEFAULT_HUB_TEMPLATE = '''"""Crucible Native Dynamic MCP Hub Server."""

from mcp.server.mcpserver import MCPServer

hub = MCPServer("hub")


@hub.tool()
def system_echo(message: str) -> str:
    """Echo a message back to verify MCP Hub connectivity."""
    return f"Hub Active: {message}"


if __name__ == "__main__":
    hub.run()
'''


def _find_tool_slice(code: str, tool_name: str) -> tuple[int, int] | None:
    """Locate the starting (including decorator) and ending line of a tool function using AST."""
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == tool_name:
            start_line = node.decorator_list[0].lineno if node.decorator_list else node.lineno
            end_line = node.end_lineno or node.lineno
            return (start_line - 1, end_line)
    return None


class McpHubManager:
    """Manages the lifecycle, code persistence, and hot-reload of the native FastMCP Hub."""

    def __init__(self, workspace_root: Path) -> None:
        self.hub_dir = (workspace_root / "mcp_servers" / "hub").resolve()
        self.server_script = self.hub_dir / "hub_server.py"

    def ensure_scaffold(self) -> Path:
        """Create the hub directory and default server script if they do not exist."""
        self.hub_dir.mkdir(parents=True, exist_ok=True)
        if not self.server_script.exists():
            self.server_script.write_text(DEFAULT_HUB_TEMPLATE, encoding="utf-8")
        return self.server_script

    def get_tool_code(self, tool_name: str) -> str | None:
        """Extract the Python source code of a registered tool from hub_server.py."""
        if not self.server_script.exists():
            return None
        code = self.server_script.read_text(encoding="utf-8")
        span = _find_tool_slice(code, tool_name)
        if not span:
            return None
        lines = code.splitlines(keepends=True)
        return "".join(lines[span[0] : span[1]])

    def refactor_tool_code(self, tool_name: str, new_code: str) -> bool:
        """Replace the source code of an existing tool in hub_server.py."""
        self.ensure_scaffold()
        code = self.server_script.read_text(encoding="utf-8")
        span = _find_tool_slice(code, tool_name)
        if not span:
            return False
        lines = code.splitlines(keepends=True)
        clean_new = new_code.strip() + "\n\n"
        lines[span[0] : span[1]] = [clean_new]
        self.server_script.write_text("".join(lines), encoding="utf-8")
        return True

    def retire_tool_code(self, tool_name: str) -> bool:
        """Retire and remove a tool function from hub_server.py."""
        if not self.server_script.exists():
            return False
        code = self.server_script.read_text(encoding="utf-8")
        span = _find_tool_slice(code, tool_name)
        if not span:
            return False
        lines = code.splitlines(keepends=True)
        del lines[span[0] : span[1]]
        self.server_script.write_text("".join(lines), encoding="utf-8")
        return True

    def register_tool_code(self, tool_name: str, code_snippet: str) -> None:
        """Append or update a @hub.tool() function snippet in the hub server script."""
        self.ensure_scaffold()
        code = self.server_script.read_text(encoding="utf-8")
        if _find_tool_slice(code, tool_name) is not None:
            self.refactor_tool_code(tool_name, code_snippet)
            return

        # Marker before entry point
        entry_marker = 'if __name__ == "__main__":'
        clean_snippet = code_snippet.strip() + "\n\n"

        if entry_marker in code:
            pre, post = code.split(entry_marker, 1)
            updated_content = f"{pre.rstrip()}\n\n{clean_snippet}{entry_marker}{post}"
        else:
            updated_content = f"{code.rstrip()}\n\n{clean_snippet}\n{entry_marker}\n    hub.run()\n"

        self.server_script.write_text(updated_content, encoding="utf-8")

    async def start_hub(self, supervisor: McpClientSupervisor) -> list[ToolDefinition]:
        """Launch the native Hub over stdio and register its tools in the supervisor."""
        self.ensure_scaffold()
        config = McpServerConfig(
            server_id="hub",
            transport="stdio",
            command=sys.executable,
            args=[str(self.server_script)],
            cwd=str(self.hub_dir),
            env={"PYTHONUNBUFFERED": "1"},
        )
        return await supervisor.connect(config)

    async def reload_hub(self, supervisor: McpClientSupervisor) -> list[ToolDefinition]:
        """Hot-reload the hub to discover newly registered tool code."""
        if supervisor.is_connected("hub"):
            await supervisor.disconnect("hub")
        return await self.start_hub(supervisor)

    def load_persisted_tools(self) -> dict[str, tuple[Any, ToolDefinition]]:
        """Load callable tools and ToolDefinitions from hub_server.py without stdio overhead."""
        if not self.server_script.exists():
            return {}
        try:
            import inspect

            from agent_os.domain.policy import ActionTier
            from agent_os.domain.tools import ToolDefinition, ToolParameterSchema

            code = self.server_script.read_text(encoding="utf-8")
            ns: dict[str, Any] = {}
            exec(code, ns)
            hub = ns.get("hub")
            if not hub or not hasattr(hub, "_tool_manager"):
                return {}
            loaded: dict[str, tuple[Any, ToolDefinition]] = {}
            for name, tool_obj in getattr(hub._tool_manager, "_tools", {}).items():
                if name == "system_echo":
                    continue
                fn = getattr(tool_obj, "fn", None)
                if callable(fn):
                    desc = (
                        getattr(tool_obj, "description", None)
                        or inspect.getdoc(fn)
                        or f"Synthesized tool: {name}"
                    )
                    sig = inspect.signature(fn)
                    params: list[ToolParameterSchema] = []
                    for p_name, param in sig.parameters.items():
                        req = param.default is inspect.Parameter.empty
                        d_val = None if req else param.default
                        p_desc = (
                            f"Target {p_name} parameter (e.g. drive letter or path)"
                            if "path" in p_name
                            else p_name
                        )
                        params.append(
                            ToolParameterSchema(
                                name=p_name,
                                type_name="string",
                                description=p_desc,
                                required=req,
                                default=d_val,
                            )
                        )
                    t_def = ToolDefinition(
                        name=name,
                        description=desc,
                        action_tier=ActionTier.STATE_CHANGE,
                        parameters=params,
                    )
                    loaded[name] = (fn, t_def)
            return loaded
        except Exception:
            return {}
