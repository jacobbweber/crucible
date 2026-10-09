"""Unit tests for ToolsmithWorker synthesis, pre-flight dry run, and activation."""

from pathlib import Path

import pytest

from agent_os.domain.toolsmith import ToolsmithSynthesisRequest
from agent_os.domain.workspace import WorkspaceConfig
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.infrastructure.workspace.command_runner import SandboxedCommandRunner
from agent_os.infrastructure.workspace.manager import WorkspaceManager
from agent_os.kernel.toolsmith import ToolsmithWorker
from agent_os.mcp.client import McpClientSupervisor
from agent_os.mcp.hub import McpHubManager


@pytest.fixture
def toolsmith_setup(tmp_path: Path):
    """Fixture providing an isolated ToolsmithWorker and supporting dependencies."""
    ws_root = tmp_path / "workspace"
    ws_cfg = WorkspaceConfig(root_dir=ws_root)
    ws_manager = WorkspaceManager(ws_cfg)
    cmd_runner = SandboxedCommandRunner(ws_cfg)
    mcp_hub = McpHubManager(ws_root)
    wiki_store = WikiStore(tmp_path / "wiki")
    supervisor = McpClientSupervisor()

    worker = ToolsmithWorker(
        workspace_manager=ws_manager,
        command_runner=cmd_runner,
        mcp_hub=mcp_hub,
        model_adapter=None,  # Tests deterministic fallback
        wiki_store=wiki_store,
    )
    return worker, supervisor, mcp_hub, wiki_store


@pytest.mark.asyncio
async def test_toolsmith_synthesis_and_dry_run(toolsmith_setup):
    """Verify tool synthesis, ephemeral dry-run execution, and 00_Inbox staging."""
    worker, supervisor, mcp_hub, wiki_store = toolsmith_setup

    try:
        req = ToolsmithSynthesisRequest(
            task="List running containers on host",
            domain="Docker Container Management",
        )
        proposal = await worker.synthesize_and_verify(req)

        # 1. Proposal must be verified
        assert proposal.verified is True
        assert "docker_container_management" in proposal.tool_name
        assert "DRY_RUN_OUTPUT" in proposal.dry_run_output
        assert proposal.staged_path.startswith("00_Inbox/")

        # 2. Markdown note must exist in wiki store
        inbox_file = wiki_store.root_dir / proposal.staged_path
        assert inbox_file.exists()
        content = inbox_file.read_text(encoding="utf-8")
        assert "Pre-Flight Dry Run" in content
        assert proposal.tool_name in content

        # 3. Activate proposal into Hub
        tools = await worker.activate_proposal(proposal, supervisor)
        mounted_names = [t.name for t in tools]
        assert f"mcp_hub_{proposal.tool_name}" in mounted_names

        # 4. Invoke newly mounted tool through supervisor
        call_res = await supervisor.call_tool(
            f"mcp_hub_{proposal.tool_name}", {"query": "live_test"}
        )
        assert call_res.success is True
        assert "live_test" in call_res.output

    finally:
        await supervisor.disconnect_all()


@pytest.mark.asyncio
async def test_toolsmith_proposal_lifecycle(toolsmith_setup):
    """Verify proposal caching, lookup by name, activation, and rejection."""
    worker, supervisor, mcp_hub, wiki_store = toolsmith_setup
    try:
        req = ToolsmithSynthesisRequest(task="Test proposal lookup", domain="Homelab")
        p = await worker.synthesize_and_verify(req)
        assert len(worker.list_proposals()) == 1
        assert worker.get_proposal(p.tool_name) == p

        # Activate by name
        tools = await worker.activate_proposal_by_name(p.tool_name, supervisor)
        assert any(t.name == f"mcp_hub_{p.tool_name}" for t in tools)

        # Reject proposal
        assert worker.reject_proposal(p.tool_name) is True
        assert worker.get_proposal(p.tool_name) is None
        assert len(worker.list_proposals()) == 0
    finally:
        await supervisor.disconnect_all()
