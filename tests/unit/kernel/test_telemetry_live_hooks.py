"""Unit tests verifying live telemetry instrumentation across user turns, tools, and jobs."""

from pathlib import Path

import pytest

from agent_os.domain.kernel import KernelConfig, UserTurnRequest
from agent_os.domain.policy import ActionTier
from agent_os.domain.tools import ToolDefinition, ToolExecutionResult
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.security.cipher import derive_master_key
from agent_os.infrastructure.security.vault_repo import CredentialVaultRepository
from agent_os.infrastructure.storage.education_repo import EducationRepository
from agent_os.infrastructure.storage.facts_repo import FactRepository
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.infrastructure.storage.telemetry_repo import TelemetryRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.master_kernel import AgentOSKernel


class DummyAdapter(BaseModelAdapter):
    async def complete(self, request):  # type: ignore[no-untyped-def]
        from agent_os.domain.gateway import StreamChunk

        yield StreamChunk(delta="Hello telemetry!")

    async def stream(self, request):  # type: ignore[no-untyped-def]
        from agent_os.domain.gateway import StreamChunk

        yield StreamChunk(delta="Hello telemetry!")


@pytest.mark.asyncio
async def test_live_telemetry_recording(tmp_path: Path) -> None:
    session_repo = SessionRepository(tmp_path / "sessions.db")
    facts_repo = FactRepository(tmp_path / "facts.db")
    recipe_repo = RecipeRepository(tmp_path / "recipes.db")
    education_repo = EducationRepository(tmp_path / "education.db")
    key = derive_master_key(salt=b"test-salt-123456", passphrase="test-password")
    vault_repo = CredentialVaultRepository(tmp_path / "vault.db", master_key=key)
    wiki_store = WikiStore(tmp_path / "wiki_vault")
    wiki_store.init_vault()
    telemetry_repo = TelemetryRepository(tmp_path / "telemetry.db")

    config = KernelConfig(
        storage_root=str(tmp_path),
        companion_name="Astra",
        max_concurrency=2,
        approval_mode="autonomous",
    )

    kernel = AgentOSKernel(
        config=config,
        session_repo=session_repo,
        facts_repo=facts_repo,
        recipe_repo=recipe_repo,
        education_repo=education_repo,
        vault_repo=vault_repo,
        wiki_store=wiki_store,
        model_adapter=DummyAdapter(),
        telemetry_repo=telemetry_repo,
    )

    # 1. Verify execute_tool records spans and metrics
    tool_def = ToolDefinition(
        name="echo_test", description="Echo", action_tier=ActionTier.STATE_CHANGE
    )
    kernel.register_tool(
        "echo_test",
        lambda msg="hi": ToolExecutionResult(tool_name="echo_test", success=True, output=msg),
        definition=tool_def,
    )

    res = await kernel.execute_tool("echo_test", {"msg": "telemetry-works"})
    assert res.success

    # Verify tool span was recorded in telemetry.db
    tool_spans = telemetry_repo.get_recent_spans(subsystem="kernel.tool", limit=10)
    assert len(tool_spans) >= 1
    assert tool_spans[0].name == "tool:echo_test"
    assert tool_spans[0].status == "ok"

    # 2. Verify handle_user_turn records spans and metrics
    sess = session_repo.create_session("Telemetry Chat")
    turn_resp = await kernel.handle_user_turn(
        UserTurnRequest(session_id=sess.session_id, user_input="Hello Astra")
    )
    assert "Hello telemetry!" in turn_resp.response_text

    chat_spans = telemetry_repo.get_recent_spans(subsystem="kernel.chat", limit=10)
    assert len(chat_spans) >= 1
    assert chat_spans[0].name == "kernel.user_turn"
    assert chat_spans[0].status == "ok"
