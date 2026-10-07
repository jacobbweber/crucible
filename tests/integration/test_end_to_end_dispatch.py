"""End-to-end integration test validating conversational background job dispatch (C4)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.domain.kernel import KernelConfig, UserTurnRequest
from agent_os.domain.recipe import RecipeMetadata, RecipeRecord
from agent_os.domain.wiki import NoteFrontmatter
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.security.cipher import derive_master_key
from agent_os.infrastructure.security.vault_repo import CredentialVaultRepository
from agent_os.infrastructure.storage.education_repo import EducationRepository
from agent_os.infrastructure.storage.facts_repo import FactRepository
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.master_kernel import AgentOSKernel


class MockMultiTurnModelAdapter(BaseModelAdapter):
    """Model adapter returning sequentially scheduled responses for front-door and worker."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.requests: list[CompletionRequest] = []
        self.call_count = 0

    async def complete(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        self.requests.append(request)
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
        else:
            resp = "Default response"
        yield StreamChunk(delta=resp, finish_reason="stop")


def _build_kernel(tmp_path: Path, adapter: BaseModelAdapter) -> AgentOSKernel:
    session_repo = SessionRepository(tmp_path / "sessions.db")
    facts_repo = FactRepository(tmp_path / "facts.db")
    recipe_repo = RecipeRepository(tmp_path / "recipes.db")
    education_repo = EducationRepository(tmp_path / "education.db")
    key = derive_master_key(salt=b"test-salt-123456", passphrase="test-password")
    vault_repo = CredentialVaultRepository(tmp_path / "vault.db", master_key=key)
    wiki_store = WikiStore(tmp_path / "wiki_vault")
    wiki_store.init_vault()

    # Seed a wiki note
    wiki_store.write_note(
        "01_Notes/ml_basics.md",
        NoteFrontmatter(title="ML Basics", category="notes", tags=["ml"]),
        "Content about neural networks",
    )

    # Seed a recipe
    recipe_repo.upsert_recipe(
        RecipeRecord(
            metadata=RecipeMetadata(
                recipe_id="recipe-wiki-summary",
                name="Wiki Summarizer",
                description="Summarize wiki notes",
                execution_engine="react",
                tags=["wiki", "summary"],
                required_tools=["wiki_read"],
            ),
            markdown_path="recipes/wiki_summary.md",
            body="## Summarize Notes\nRead notes and synthesize summary.",
        )
    )

    config = KernelConfig(
        storage_root=str(tmp_path),
        companion_name="Astra",
        max_concurrency=2,
        approval_mode="balanced",
    )

    return AgentOSKernel(
        config=config,
        session_repo=session_repo,
        facts_repo=facts_repo,
        recipe_repo=recipe_repo,
        education_repo=education_repo,
        vault_repo=vault_repo,
        wiki_store=wiki_store,
        model_adapter=adapter,
    )


@pytest.mark.asyncio
async def test_end_to_end_conversational_job_dispatch(tmp_path: Path) -> None:
    """Validate user prompt -> companion emits [DISPATCH] -> worker executes -> nudge & prompt."""
    # Response sequence:
    # 1. Front-door companion turn 1: emits [DISPATCH: summarize wiki notes]
    # 2. Worker ReAct step in Recipe Chamber: completes task
    # 3. Front-door companion turn 2: companion receives background completion in prompt
    responses = [
        "I will summarize the notes for you.\n[DISPATCH: summarize wiki notes]",
        (
            "```json\n"
            "{\n"
            '  "thought": "Reading ML notes from wiki.",\n'
            '  "action": "wiki_read",\n'
            '  "parameters": {"path": "01_Notes/ml_basics.md"}\n'
            "}\n"
            "```"
        ),
        "Found 1 note covering neural network fundamentals.",
        "The background worker finished. Found 1 note covering neural network fundamentals.",
    ]

    adapter = MockMultiTurnModelAdapter(responses)
    kernel = _build_kernel(tmp_path, adapter)
    session = kernel.session_repo.create_session("E2E Session")
    session_id = session.session_id

    # Turn 1: User asks to summarize notes
    req1 = UserTurnRequest(session_id=session_id, user_input="Please summarize my wiki notes")
    turn1_resp = await kernel.handle_user_turn(req1)

    assert "I will summarize the notes for you" in turn1_resp.response_text
    assert len(turn1_resp.dispatched_subjobs) == 1
    dispatched = turn1_resp.dispatched_subjobs[0]
    assert dispatched.dispatch_result.envelope.status == "completed"
    expected_summary = "Found 1 note covering neural network fundamentals."
    assert expected_summary in dispatched.dispatch_result.envelope.summary
    assert len(turn1_resp.ambient_nudges) >= 1
    assert "completed" in turn1_resp.ambient_nudges[0].short_notice.lower()

    # Turn 2: User follows up
    req2 = UserTurnRequest(session_id=session_id, user_input="What did you find?")
    turn2_resp = await kernel.handle_user_turn(req2)

    # Verify that turn 2 system prompt contained the deferred background completion!
    turn2_request = adapter.requests[-1]
    system_prompt = next((m.content for m in turn2_request.messages if m.role == "system"), "")
    assert "<background_completions>" in system_prompt
    assert "Found 1 note covering neural network fundamentals." in system_prompt
    assert "</background_completions>" in system_prompt
    assert "Found 1 note covering neural network fundamentals." in turn2_resp.response_text
