"""Transport runners for Agent OS MCP server gateway."""

import logging

from agent_os.kernel.master_kernel import AgentOSKernel
from agent_os.mcp.server import create_mcp_server

logger = logging.getLogger(__name__)


async def run_mcp_server(
    kernel: AgentOSKernel,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    name: str = "agent-os-node",
) -> None:
    """Run the MCP server over stdio or SSE transport.

    Args:
        kernel: Initialized AgentOSKernel runtime.
        transport: 'stdio' or 'sse'.
        host: Host binding for SSE (default 127.0.0.1).
        port: Port binding for SSE (default 8000).
        name: MCP server node name.
    """
    server = create_mcp_server(kernel=kernel, name=name)
    if transport == "stdio":
        logger.info("Starting Agent OS MCP server over stdio (node: %s)", name)
        await server.run_stdio_async()
    elif transport == "sse":
        logger.info(
            "Starting Agent OS MCP server over SSE at http://%s:%d (node: %s)",
            host,
            port,
            name,
        )
        await server.run_sse_async(host=host, port=port)
    else:
        msg = f"Unsupported MCP transport: {transport}. Choose 'stdio' or 'sse'."
        raise ValueError(msg)
