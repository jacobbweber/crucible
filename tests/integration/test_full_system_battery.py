"""Master end-to-end integration battery validating all agent-os runtime subsystems."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.domain.kernel import KernelConfig, UserTurnRequest
from agent_os.domain.pipeline import PipelineExecutionResult
from agent_os.domain.policy import ActionTier
from agent_os.domain.recipe import RecipeMetadata, RecipeRecord
from agent_os.domain.schedule import ScheduledRoutine
from agent_os.domain.security import CredentialType
from agent_os.domain.tools import ToolExecutionResult
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.security.cipher import derive_master_key
from agent_os.infrastructure.security.vault_repo import CredentialVaultRepository
from agent_os.infrastructure.storage.education_repo import EducationRepository
from agent_os.infrastructure.storage.facts_repo import FactRepository
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.master_kernel import AgentOSKernel


class RecordingMockModelAdapter(BaseModelAdapter):
    """Hermetic model adapter recording requests and streaming predefined response chunks."""

    def __init__(self, responses: list[list[StreamChunk] | str] | None = None) -> None:
        self.responses = responses or []
        self.requests: list[CompletionRequest] = []
        self.call_count = 0

    def add_response(self, resp: list[StreamChunk] | str) -> None:
        """Queue another mock response for subsequent completions."""
        self.responses.append(resp)

    async def complete(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        """Record the request and stream back the next queued response."""
        self.requests.append(request)
        if self.responses:
            idx = min(self.call_count, len(self.responses) - 1)
            resp = self.responses[idx]
            self.call_count += 1
            if isinstance(resp, str):
                yield StreamChunk(delta=resp)
            else:
                for chunk in resp:
                    yield chunk
        else:
            yield StreamChunk(delta="OK")


def _build_test_kernel(
    tmp_path: Path,
    adapter: BaseModelAdapter,
) -> tuple[
    AgentOSKernel,
    SessionRepository,
    FactRepository,
    RecipeRepository,
    CredentialVaultRepository,
]:
    """Helper to assemble an AgentOSKernel instance with isolated SQLite repositories."""
    session_repo = SessionRepository(tmp_path / "session_store.db")
    facts_repo = FactRepository(tmp_path / "memory_facts.db")
    recipe_repo = RecipeRepository(tmp_path / "recipes.db")
    education_repo = EducationRepository(tmp_path / "education.db")
    key = derive_master_key(salt=b"test-salt-123456", passphrase="test-password")
    vault_repo = CredentialVaultRepository(tmp_path / "vault.db", master_key=key)
    wiki_store = WikiStore(tmp_path / "wiki_vault")

    config = KernelConfig(
        storage_root=str(tmp_path),
        companion_name="Astra",
        max_concurrency=2,
        approval_mode="balanced",
    )

    kernel = AgentOSKernel(
        config=config,
        session_repo=session_repo,
        facts_repo=facts_repo,
        recipe_repo=recipe_repo,
        education_repo=education_repo,
        vault_repo=vault_repo,
        wiki_store=wiki_store,
        model_adapter=adapter,
    )

    return kernel, session_repo, facts_repo, recipe_repo, vault_repo


@pytest.mark.asyncio
async def test_full_system_interactive_conversation_with_facts(tmp_path: Path) -> None:
    """Verify conversational turn extracts facts into prompt, streams events, and persists."""
    adapter = RecordingMockModelAdapter(
        [
            [
                StreamChunk(delta="Your configured setup ", finish_reason=None),
                StreamChunk(delta="runs TrueNAS SCALE with 64GB ECC RAM.", finish_reason="stop"),
            ]
        ]
    )
    kernel, session_repo, facts_repo, _, _ = _build_test_kernel(tmp_path, adapter)

    # 1. Seed facts under entity_key="user"
    facts_repo.save_fact(
        entity_key="user",
        fact_text="User setup runs TrueNAS with 64GB RAM.",
        category="infrastructure",
    )

    # 2. Submit user turn
    session = session_repo.create_session("Interactive Dialogue")
    request = UserTurnRequest(
        session_id=session.session_id,
        user_input="What is my configured setup?",
    )
    response = await kernel.handle_user_turn(request)

    # 3. Assertions
    assert response.recalled_facts_count >= 1
    assert len(response.stream_events) >= 2
    assert "Your configured setup runs TrueNAS SCALE" in response.response_text

    # Verify session persistence
    stored_turns = session_repo.get_recent_turns(session.session_id)
    assert len(stored_turns) == 2
    assert stored_turns[0].role == "user"
    assert stored_turns[0].content == "What is my configured setup?"
    assert stored_turns[1].role == "assistant"
    assert "TrueNAS" in stored_turns[1].content

    # Verify prompt received fact injection
    assert len(adapter.requests) == 1
    system_msg = adapter.requests[0].messages[0]
    assert "<recalled_facts>" in system_msg.content
    assert "TrueNAS with 64GB RAM" in system_msg.content


@pytest.mark.asyncio
async def test_full_system_delegated_job_execution(tmp_path: Path) -> None:
    """Verify sandboxed sub-job executes, records steps, and leaves parent turns unpolluted."""
    adapter = RecordingMockModelAdapter(["Cluster nodes verified: All 8 nodes healthy."])
    kernel, session_repo, _, recipe_repo, _ = _build_test_kernel(tmp_path, adapter)

    # 1. Seed catalog recipe
    recipe_record = RecipeRecord(
        metadata=RecipeMetadata(
            recipe_id="recipe_audit_001",
            name="System Audit",
            description="Audit cluster nodes and generate report",
            execution_engine="direct",
            target_model_tier="reasoning",
            tags=["audit", "cluster"],
            required_tools=[],
            timeout_seconds=300,
        ),
        markdown_path="recipes/audit.md",
        body="Execute cluster node audit and verify all system invariants hold.",
    )
    recipe_repo.upsert_recipe(recipe_record)

    # 2. Execute job
    session = session_repo.create_session("Delegated Job Parent Session")
    result = await kernel.execute_job(
        session_id=session.session_id,
        task="audit cluster nodes",
    )

    # 3. Assertions
    assert isinstance(result, PipelineExecutionResult)
    assert result.dispatch_result.envelope.status == "completed"
    assert len(result.dispatch_result.envelope.summary) <= 800
    assert result.dispatch_result.envelope.token_estimate <= 200

    # Step telemetry recorded in journey steps
    steps = session_repo.get_journey_scratchpad(result.dispatch_result.envelope.journey_id)
    assert len(steps) >= 1

    # Invariant: parent conversation turns receive zero worker pollution
    parent_turns = session_repo.get_recent_turns(session.session_id)
    assert len(parent_turns) == 0
    assert session_repo.count_turns(session.session_id) == 0


@pytest.mark.asyncio
async def test_full_system_background_scheduler_and_catchup(tmp_path: Path) -> None:
    """Verify scheduled routine runs in background, logs success, and injects completions."""
    adapter = RecordingMockModelAdapter()
    adapter.add_response("Database backup completed successfully: 3 snapshots retained.")
    adapter.add_response("All maintenance routines are nominal.")

    kernel, session_repo, _, recipe_repo, _ = _build_test_kernel(tmp_path, adapter)

    # 1. Seed matching recipe for background routine
    recipe_record = RecipeRecord(
        metadata=RecipeMetadata(
            recipe_id="recipe_backup_001",
            name="Backup Routine",
            description="Backup database and rotate snapshot archives",
            execution_engine="direct",
            tags=["backup", "maintenance"],
            required_tools=[],
            timeout_seconds=300,
        ),
        markdown_path="recipes/backup.md",
        body="Execute database snapshot backup and prune archives.",
    )
    recipe_repo.upsert_recipe(recipe_record)

    # 2. Register scheduled routine with catch-up policy due in past
    now = datetime.now(UTC)
    past_due = now - timedelta(hours=2)
    routine = ScheduledRoutine(
        routine_id="routine_backup_001",
        name="Hourly Database Backup",
        cron_expression="@hourly",
        task_payload="backup database and rotate",
        catch_up_policy="run_once_immediately",
        next_run_at=past_due,
    )
    kernel.scheduler.register_routine(routine)

    # 3. Trigger tick and verify background execution
    logs = await kernel.trigger_scheduler_tick(now)
    assert len(logs) == 1
    assert logs[0].status == "success", f"Error: {logs[0].error_message}"
    assert logs[0].routine_id == "routine_backup_001"

    # 4. Subsequent user turn receives injected <background_completions>
    session = session_repo.create_session("Maintenance Query Session")
    resp = await kernel.handle_user_turn(
        UserTurnRequest(
            session_id=session.session_id,
            user_input="Are the database backups up to date?",
        )
    )
    assert resp.response_text != ""

    # Verify adapter received background completions in prompt
    last_request = adapter.requests[-1]
    system_content = last_request.messages[0].content
    assert "<background_completions>" in system_content
    assert "Database backup completed successfully" in system_content
    assert "</background_completions>" in system_content


@pytest.mark.asyncio
async def test_full_system_credential_proxy_and_guardrail(tmp_path: Path) -> None:
    """Verify vault secret unmasking JIT for tool execution and automatic output scrubbing."""
    adapter = RecordingMockModelAdapter()
    kernel, _, _, _, vault_repo = _build_test_kernel(tmp_path, adapter)

    # 1. Store secret in encrypted vault
    vault_repo.store_credential(
        alias="vault://test-token",
        cred_type=CredentialType.API_KEY,
        secret_payload={"token": "ghp_SecretAuthTokenXYZ987"},
    )

    # 2. Register custom tool
    received_secret: str | None = None

    def deploy_service(api_key: str, cluster: str) -> ToolExecutionResult:
        nonlocal received_secret
        received_secret = api_key
        return ToolExecutionResult(
            tool_name="deploy_service",
            success=True,
            output=f"Cluster {cluster} deployed using token: {api_key}.",
        )

    kernel.register_tool(
        name="deploy_service",
        fn=deploy_service,
        action_tier=ActionTier.STATE_CHANGE,
    )

    # 3. Dispatch tool call referencing vault alias
    result = await kernel.execute_tool(
        tool_name="deploy_service",
        parameters={"api_key": "vault://test-token", "cluster": "prod-alpha"},
    )

    # 4. Assertions: policy gate permits, secret unmasked JIT, output scrubbed
    assert result.success is True
    assert received_secret == "ghp_SecretAuthTokenXYZ987"
    assert "[REDACTED_SECRET]" in result.output
    assert "ghp_SecretAuthTokenXYZ987" not in result.output
    assert "Cluster prod-alpha deployed using token: [REDACTED_SECRET]." in result.output

    # 5. Tool raising exception with secret in message -> assert error is scrubbed (H4)
    def fail_service(api_key: str) -> None:
        raise RuntimeError(f"Connection failed for {api_key} on backend")

    kernel.register_tool(
        name="fail_service",
        fn=fail_service,
        action_tier=ActionTier.STATE_CHANGE,
    )
    fail_result = await kernel.execute_tool(
        tool_name="fail_service",
        parameters={"api_key": "vault://test-token"},
    )
    assert fail_result.success is False
    assert "ghp_SecretAuthTokenXYZ987" not in fail_result.error
    assert "[REDACTED_SECRET]" in fail_result.error
    assert "Connection failed for [REDACTED_SECRET] on backend" in fail_result.error
