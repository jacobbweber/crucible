"""Integration test validating end-to-end self-developing Toolsmith synthesis, auto-mount, and execution."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.domain.kernel import KernelConfig, UserTurnRequest
from agent_os.domain.tools import ToolDefinition, ToolExecutionResult
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.security.cipher import derive_master_key
from agent_os.infrastructure.security.vault_repo import CredentialVaultRepository
from agent_os.infrastructure.storage.education_repo import EducationRepository
from agent_os.infrastructure.storage.facts_repo import FactRepository
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.master_kernel import AgentOSKernel


class MockToolsmithModelAdapter(BaseModelAdapter):
    """Model adapter orchestrating prompt responses across front-door, toolsmith, and chamber."""

    def __init__(self, target_file_path: Path) -> None:
        self.target_file_path = target_file_path
        self.requests: list[CompletionRequest] = []

    async def complete(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        self.requests.append(request)
        content = request.messages[-1].content

        # 1. Capability Evaluator
        if "You are an expert system capability evaluator" in content:
            resp = json.dumps({"has_capability": False, "missing_domain": "Host Filesystem Operations"})
        # 2. Toolsmith synthesis request
        elif "You are an expert Python tool developer" in content:
            tool_code = (
                "@hub.tool()\n"
                "def host_write_file(path: str, content: str) -> str:\n"
                "    '''Write content to specified path.'''\n"
                "    from pathlib import Path\n"
                "    p = Path(path)\n"
                "    p.parent.mkdir(parents=True, exist_ok=True)\n"
                "    p.write_text(content, encoding='utf-8')\n"
                "    return f'Wrote {len(content)} chars to {path}'\n"
            )
            spec = {
                "tool_name": "host_write_file",
                "description": "Write text content to host path",
                "code_snippet": tool_code,
                "dry_run_args": {"path": "dry_run_sample.txt", "content": "sample verification"},
            }
            resp = json.dumps(spec)
        # 3. Ephemeral Stage 2 Brief Assembler
        elif "You are an expert task planner" in content or "TaskBrief" in content:
            brief = {
                "role_anchor": "Host System Worker",
                "core_directive": f"Write hello world into {self.target_file_path}",
                "scope_invariants": ["Verify file written"],
                "capability_strategy": "Use host_write_file to create file",
                "completion_standard": "File exists with content",
                "selected_tools": ["host_write_file"],
            }
            resp = json.dumps(brief)
        # 4. Recipe Chamber ReAct execution
        elif request.messages[-1].role == "tool" or "Observation from" in request.messages[-1].content:
            resp = f"Successfully wrote hello world to {self.target_file_path}."
        elif "Host System Worker" in str(request.messages[0].content) or "To invoke a tool, emit a JSON block" in str(request.messages[0].content):
            resp = json.dumps({
                "thought": f"I need to write 'hello world' to {self.target_file_path} using host_write_file.",
                "action": "host_write_file",
                "parameters": {"path": str(self.target_file_path), "content": "hello world"},
            })
        # 5. Front-door companion turn: emit dispatch directive
        elif "Can you create me a file named" in content:
            resp = (
                "<think>This requires host file system access.</think>\n\n"
                f"[DISPATCH: Create file at {self.target_file_path} and write hello world into it.]\n\n"
                "I have dispatched a directive to create the file."
            )
        else:
            resp = f"Successfully wrote hello world to {self.target_file_path}."

        yield StreamChunk(delta=resp, finish_reason="stop")


@pytest.mark.asyncio
async def test_end_to_end_host_filesystem_synthesis_and_execution(tmp_path: Path) -> None:
    """Verify that an unfulfilled host file task triggers Toolsmith synthesis, auto-mount, and writes file."""
    target_file = tmp_path / "host_drive" / "test123.txt"
    adapter = MockToolsmithModelAdapter(target_file)

    session_repo = SessionRepository(tmp_path / "sessions.db")
    facts_repo = FactRepository(tmp_path / "facts.db")
    recipe_repo = RecipeRepository(tmp_path / "recipes.db")
    education_repo = EducationRepository(tmp_path / "education.db")
    key = derive_master_key(salt=b"test-salt-123456", passphrase="test-password")
    vault_repo = CredentialVaultRepository(tmp_path / "vault.db", master_key=key)
    wiki_store = WikiStore(tmp_path / "wiki_vault")
    wiki_store.init_vault()

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
        model_adapter=adapter,
    )

    # Mock tool activation in kernel to simulate live FastMCP reload in test environment
    async def mock_activate(tool_name: str) -> list[ToolDefinition]:
        async def fake_host_writer(path: str, content: str) -> ToolExecutionResult:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ToolExecutionResult(tool_name="host_write_file", success=True, output=f"Wrote to {path}")

        from agent_os.domain.policy import ActionTier
        tool_def = ToolDefinition(name=tool_name, description="Host writer", action_tier=ActionTier.STATE_CHANGE)
        kernel.register_tool(tool_name, fake_host_writer, action_tier=ActionTier.STATE_CHANGE, definition=tool_def)
        return [tool_def]

    kernel.assembly_pipeline.on_activate_tool = mock_activate

    session = kernel.session_repo.create_session("Host Filesystem Test")
    user_msg = f"Can you create me a file named test123.txt at {target_file}, and in it write hello world"
    req = UserTurnRequest(session_id=session.session_id, user_input=user_msg)

    resp = await kernel.handle_user_turn(req)

    # 1. Assert file was physically created with expected content
    assert target_file.exists(), "Target file should have been physically created"
    assert target_file.read_text(encoding="utf-8") == "hello world"

    # 2. Assert subjob dispatched and succeeded
    assert len(resp.dispatched_subjobs) == 1
    job = resp.dispatched_subjobs[0]
    assert job.dispatch_result.envelope.status == "completed"
    assert job.flagged_for_graduation is True
