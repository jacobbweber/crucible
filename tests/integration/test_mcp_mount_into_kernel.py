"""Integration test verifying dynamic MCP server mounting into AgentOSKernel."""

import pytest
from pathlib import Path

from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.domain.kernel import KernelConfig
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.security.cipher import derive_master_key
from agent_os.infrastructure.security.vault_repo import CredentialVaultRepository
from agent_os.infrastructure.storage.education_repo import EducationRepository
from agent_os.infrastructure.storage.facts_repo import FactRepository
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.master_kernel import AgentOSKernel
from agent_os.mcp.client import McpServerConfig


class MockAdapter(BaseModelAdapter):
    async def complete(self, request: CompletionRequest):
        yield StreamChunk(delta="OK")


@pytest.fixture
def kernel_fixture(tmp_path: Path):
    """Construct an isolated AgentOSKernel instance."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    db_path = data_dir / "sessions.db"

    session_repo = SessionRepository(db_path)
    facts_repo = FactRepository(data_dir / "facts.db")
    recipe_repo = RecipeRepository(data_dir / "recipes.db")
    education_repo = EducationRepository(data_dir / "education.db")
    vault_repo = CredentialVaultRepository(
        data_dir / "vault.db",
        master_key=derive_master_key(salt=b"test_salt_16byte", passphrase="test-passphrase"),
    )
    wiki_store = WikiStore(data_dir / "wiki")
    adapter = MockAdapter()

    kernel = AgentOSKernel(
        config=KernelConfig(),
        session_repo=session_repo,
        facts_repo=facts_repo,
        recipe_repo=recipe_repo,
        education_repo=education_repo,
        vault_repo=vault_repo,
        wiki_store=wiki_store,
        model_adapter=adapter,
    )
    return kernel, data_dir


@pytest.mark.asyncio
async def test_mount_mcp_hub_into_kernel(kernel_fixture):
    """Verify mounting the native FastMCP Hub into the live kernel tool registry."""
    kernel, data_dir = kernel_fixture

    try:
        # 1. Ensure Hub scaffold exists
        hub_script = kernel.mcp_hub.ensure_scaffold()

        # 2. Mount Hub via mount_mcp_server
        import sys
        config = McpServerConfig(
            server_id="hub",
            transport="stdio",
            command=sys.executable,
            args=[str(hub_script)],
            cwd=str(hub_script.parent),
            env={"PYTHONUNBUFFERED": "1"},
        )
        mounted_tools = await kernel.mount_mcp_server(config)
        assert len(mounted_tools) >= 1
        assert "mcp_hub_system_echo" in kernel.tools

        # 3. Execute tool through MasterKernel.execute_tool
        result = await kernel.execute_tool(
            "mcp_hub_system_echo",
            {"message": "Crucible Kernel Handshake"},
        )
        assert result.success is True
        assert "Hub Active: Crucible Kernel Handshake" in result.output

    finally:
        await kernel.mcp_supervisor.disconnect_all()
