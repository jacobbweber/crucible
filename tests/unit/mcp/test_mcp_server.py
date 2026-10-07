"""Unit tests for Agent OS MCP server gateway."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_os.bootstrap import build_runtime
from agent_os.domain.config import AppConfig
from agent_os.domain.kernel import KernelConfig
from agent_os.mcp.server import create_mcp_server
from agent_os.mcp.transport import run_mcp_server


@pytest.fixture
def temp_runtime(tmp_path: Path):
    """Create an isolated test runtime for MCP testing."""
    kernel_config = KernelConfig(
        storage_root=str(tmp_path / "sessions.db"),
        companion_name="MCPCompanion",
        approval_mode="autonomous",
    )
    return build_runtime(
        app_config=AppConfig(),
        data_dir=str(tmp_path),
        kernel_config=kernel_config,
    )


@pytest.mark.asyncio
async def test_mcp_server_lists_all_tools(temp_runtime):
    """Verify all 12 core tools are exposed over MCP."""
    server = create_mcp_server(temp_runtime.kernel, name="test-node")
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    expected_tools = {
        "telemetry_get_health_summary",
        "telemetry_audit_errors",
        "telemetry_stage_rca",
        "telemetry_prune_old_records",
        "session_search_history",
        "warehouse_read",
        "warehouse_write",
        "warehouse_list_category",
        "warehouse_search",
        "warehouse_graduate_inbox",
        "execute_task",
        "chat_turn",
    }
    assert expected_tools.issubset(tool_names)
    assert len(tools) >= 12


@pytest.mark.asyncio
async def test_mcp_server_telemetry_and_warehouse_tools(temp_runtime):
    """Verify tool execution round-trip through MCP call_tool interface."""
    server = create_mcp_server(temp_runtime.kernel, name="test-node")

    # 1. Telemetry vitals
    health_res: Any = await server.call_tool("telemetry_get_health_summary", {"hours": 24})
    assert not health_res.is_error
    health_data = json.loads(health_res.content[0].text)
    assert health_data["health_score"] == 100

    # 2. Write note to warehouse
    write_res: Any = await server.call_tool(
        "warehouse_write",
        {
            "path": "00_Inbox/test_remote_note.md",
            "title": "Remote Edge Note",
            "category": "00_Inbox",
            "tags": ["edge", "mcp"],
            "body": "This note was staged via an MCP tool call from a remote client.",
            "overwrite": True,
        },
    )
    assert not write_res.is_error
    assert "written" in write_res.content[0].text.lower()

    # 3. Read note back
    read_res: Any = await server.call_tool(
        "warehouse_read",
        {"path": "00_Inbox/test_remote_note.md", "max_lines": 50},
    )
    assert not read_res.is_error
    assert "Remote Edge Note" in read_res.content[0].text


@pytest.mark.asyncio
async def test_mcp_server_session_search_tool(temp_runtime):
    """Verify session search executes via MCP tool call."""
    server = create_mcp_server(temp_runtime.kernel, name="test-node")

    # Seed a session and turn
    sess = temp_runtime.kernel.session_repo.create_session("Edge Session")
    temp_runtime.kernel.session_repo.append_turn(
        sess.session_id, "user", "Searching for edge computing concepts"
    )

    res: Any = await server.call_tool(
        "session_search_history",
        {"query": "edge", "include_archive": True, "limit": 5},
    )
    assert not res.is_error
    assert "Found" in res.content[0].text


@pytest.mark.asyncio
async def test_mcp_server_resources(temp_runtime):
    """Verify reading warehouse and telemetry resources."""
    server = create_mcp_server(temp_runtime.kernel, name="test-node")
    resources = await server.list_resources()
    resource_uris = {str(r.uri) for r in resources}

    assert "warehouse://inbox" in resource_uris
    assert "warehouse://knowledge" in resource_uris
    assert "telemetry://health" in resource_uris

    # Read health resource
    health_res = list(await server.read_resource("telemetry://health"))
    assert len(health_res) == 1
    health_json = json.loads(getattr(health_res[0], "content", "{}"))
    assert "health_score" in health_json

    # Read inbox resource
    inbox_res = list(await server.read_resource("warehouse://inbox"))
    assert len(inbox_res) == 1
    inbox_json = json.loads(getattr(inbox_res[0], "content", "{}"))
    assert "staged_count" in inbox_json


@pytest.mark.asyncio
async def test_mcp_server_prompts(temp_runtime):
    """Verify prompt templates are retrievable over MCP."""
    server = create_mcp_server(temp_runtime.kernel, name="test-node")
    prompts = await server.list_prompts()
    prompt_names = {p.name for p in prompts}

    assert "self_health_audit" in prompt_names
    assert "weekly_warehouse_graduation" in prompt_names
    assert "deep_topic_synthesis" in prompt_names

    prompt_res: Any = await server.get_prompt("self_health_audit")
    assert len(prompt_res.messages) == 1
    assert "health summary" in prompt_res.messages[0].content.text


@pytest.mark.asyncio
async def test_mcp_transport_unsupported_error(temp_runtime):
    """Verify ValueError is raised when unsupported transport protocol is requested."""
    with pytest.raises(ValueError, match="Unsupported MCP transport"):
        await run_mcp_server(temp_runtime.kernel, transport="invalid_proto")
