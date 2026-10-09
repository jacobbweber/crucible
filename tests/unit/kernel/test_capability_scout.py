"""Unit tests for CapabilityScout and dynamic MCP capability proposal staging."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_os.domain.pipeline import JobAssemblyRequest
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.capability_scout import CapabilityScout
from agent_os.kernel.pipeline import JobAssemblyPipeline
from agent_os.kernel.signaling import CompletionSignaler


def test_identify_missing_domain():
    """Verify domain detection when required tools are missing from tool list."""
    scout = CapabilityScout(wiki_store=None)

    # 1. Docker task without docker tool
    domain = scout.identify_missing_domain(
        "list running docker containers", ["warehouse_read", "telemetry_tools"]
    )
    assert domain == "Docker Container Management"

    # 2. Docker task when docker tool is present
    domain_present = scout.identify_missing_domain(
        "list running docker containers", ["docker_list_containers", "warehouse_read"]
    )
    assert domain_present is None

    # 3. Git task without git tool
    git_domain = scout.identify_missing_domain("commit changes to git repo", ["warehouse_read"])
    assert git_domain == "Git Version Control"

    # 4. Standard warehouse task
    wh_domain = scout.identify_missing_domain(
        "write a note about architecture", ["warehouse_write"]
    )
    assert wh_domain is None


def test_stage_mcp_proposal(tmp_path: Path):
    """Verify structured proposal note is generated in 00_Inbox."""
    wiki_store = WikiStore(root_dir=tmp_path / "wiki_vault")
    scout = CapabilityScout(wiki_store=wiki_store)

    relative_path = scout.stage_mcp_proposal(
        task="list running docker containers", domain="Docker Container Management"
    )
    assert "00_Inbox/proposal_docker_container_management_mcp.md" in relative_path

    staged_file = tmp_path / "wiki_vault" / relative_path
    assert staged_file.exists()

    content = staged_file.read_text(encoding="utf-8")
    assert (
        "title: Capability Proposal - Docker Container Management via Model Context Protocol (MCP)"
        in content
    )
    assert "Option B: Dedicated MCP Server Integration (Recommended)" in content
    assert "Deterministic Sandboxing" in content
    assert "00_Inbox" in content


@pytest.mark.asyncio
async def test_pipeline_stages_proposal_on_missing_domain(tmp_path: Path):
    """Verify JobAssemblyPipeline stages proposal when missing domain is requested."""
    wiki_store = WikiStore(root_dir=tmp_path / "wiki_vault")
    scout = CapabilityScout(wiki_store=wiki_store)

    mock_dispatcher = MagicMock()
    mock_dispatcher.threshold = 0.5
    mock_signaler = CompletionSignaler()
    mock_recipe_repo = MagicMock()
    mock_recipe_repo.match_intent.return_value = []

    pipeline = JobAssemblyPipeline(
        dispatcher=mock_dispatcher,
        signaler=mock_signaler,
        recipe_repo=mock_recipe_repo,
        capability_scout=scout,
    )

    statuses: list[str] = []
    req = JobAssemblyRequest(
        session_id="test_sess",
        task="list running docker containers",
        available_tools=["warehouse_read", "warehouse_write"],
    )

    res = await pipeline.run_pipeline(req, on_status=statuses.append)

    assert res.dispatch_result.envelope.status == "completed"
    assert "Missing tool for 'Docker Container Management'" in res.dispatch_result.envelope.summary
    assert any("Detected missing capability" in s for s in statuses)

    # Verify staged proposal file exists
    inbox_files = list((tmp_path / "wiki_vault" / "00_Inbox").glob("*.md"))
    assert len(inbox_files) == 1
    assert "docker" in inbox_files[0].name
