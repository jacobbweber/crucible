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

    def register_tool_code(self, tool_name: str, code_snippet: str) -> None:
        """Append or update a @hub.tool() function snippet in the hub server script."""
        self.ensure_scaffold()
        content = self.server_script.read_text(encoding="utf-8")

        # Marker before entry point
        entry_marker = 'if __name__ == "__main__":'
        clean_snippet = code_snippet.strip() + "\n\n"

        if entry_marker in content:
            pre, post = content.split(entry_marker, 1)
            updated_content = f"{pre.rstrip()}\n\n{clean_snippet}{entry_marker}{post}"
        else:
            updated_content = f"{content.rstrip()}\n\n{clean_snippet}\n{entry_marker}\n    hub.run()\n"

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

    def load_persisted_tools(self) -> dict[str, tuple[Any, str]]:
        """Load callable tools and descriptions registered in hub_server.py without stdio overhead."""
        if not self.server_script.exists():
            return {}
        try:
            code = self.server_script.read_text(encoding="utf-8")
            ns: dict[str, Any] = {}
            exec(code, ns)
            hub = ns.get("hub")
            if not hub or not hasattr(hub, "_tool_manager"):
                return {}
            loaded: dict[str, tuple[Any, str]] = {}
            for name, tool_obj in getattr(hub._tool_manager, "_tools", {}).items():
                if name == "system_echo":
                    continue
                fn = getattr(tool_obj, "fn", None)
                if callable(fn):
                    desc = getattr(tool_obj, "description", None) or f"Synthesized tool: {name}"
                    loaded[name] = (fn, desc)
            return loaded
        except Exception:
            return {}

