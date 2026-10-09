"""Unit and integration tests for MCP client supervisor and native FastMCP Hub."""

from pathlib import Path

import pytest

from agent_os.domain.policy import ActionTier
from agent_os.mcp.client import McpClientSupervisor, McpServerConfig
from agent_os.mcp.hub import McpHubManager


@pytest.fixture
def hub_setup(tmp_path: Path):
    """Fixture providing an isolated McpHubManager and McpClientSupervisor."""
    hub_manager = McpHubManager(tmp_path / "workspace")
    supervisor = McpClientSupervisor()
    return hub_manager, supervisor


@pytest.mark.asyncio
async def test_invalid_mcp_config():
    """Connecting with invalid config must raise ValueError."""
    supervisor = McpClientSupervisor()
    with pytest.raises(ValueError, match="command"):
        await supervisor.connect(McpServerConfig(server_id="bad", transport="stdio", command=None))

    with pytest.raises(ValueError, match="url"):
        await supervisor.connect(McpServerConfig(server_id="bad_sse", transport="sse", url=None))

    with pytest.raises(ValueError, match="Unsupported transport"):
        await supervisor.connect(McpServerConfig(server_id="bad_t", transport="grpc", command="x"))


@pytest.mark.asyncio
async def test_hub_scaffold_and_start(hub_setup):
    """Verify Hub scaffolding, stdio launch, tool discovery, and execution."""
    hub_manager, supervisor = hub_setup

    try:
        # 1. Start Hub
        tools = await hub_manager.start_hub(supervisor)
        assert len(tools) >= 1
        tool_names = [t.name for t in tools]
        assert "mcp_hub_system_echo" in tool_names

        # 2. Check tool schema
        echo_def = next(t for t in tools if t.name == "mcp_hub_system_echo")
        assert echo_def.action_tier == ActionTier.READ  # Inferred from 'echo' or default
        param_names = [p.name for p in echo_def.parameters]
        assert "message" in param_names

        # 3. Call tool
        res = await supervisor.call_tool("mcp_hub_system_echo", {"message": "Crucible Live"})
        assert res.success is True
        assert "Hub Active: Crucible Live" in res.output

    finally:
        await supervisor.disconnect_all()


@pytest.mark.asyncio
async def test_hub_dynamic_tool_registration(hub_setup):
    """Dynamically register a new tool into Hub and verify hot reload."""
    hub_manager, supervisor = hub_setup

    try:
        # Register a custom tool
        custom_code = '''
@hub.tool()
def calculate_zfs_health(pool_name: str) -> str:
    """Check simulated ZFS pool health."""
    return f"Pool {pool_name}: ONLINE, 0 errors, 42TB free"
'''
        hub_manager.register_tool_code("calculate_zfs_health", custom_code)

        # Start or reload hub
        tools = await hub_manager.start_hub(supervisor)
        tool_names = [t.name for t in tools]
        assert "mcp_hub_calculate_zfs_health" in tool_names

        # Call dynamically registered tool
        res = await supervisor.call_tool("mcp_hub_calculate_zfs_health", {"pool_name": "tank0"})
        assert res.success is True
        assert "Pool tank0: ONLINE" in res.output

    finally:
        await supervisor.disconnect_all()
