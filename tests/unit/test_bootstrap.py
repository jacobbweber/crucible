"""Smoke tests for the composition root and vault key provisioning."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agent_os.bootstrap import build_runtime
from agent_os.domain.config import AppConfig
from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.domain.kernel import UserTurnRequest
from agent_os.domain.wiki import ProtectedFolder
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.security.key_provider import load_or_create_master_key


class _EchoAdapter(BaseModelAdapter):
    async def complete(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta="", reasoning="thinking...")
        yield StreamChunk(delta=f"echo: {request.messages[-1].content}", finish_reason="stop")


@pytest.mark.asyncio
async def test_build_runtime_wires_storage_and_traces_turn(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    runtime = build_runtime(
        app_config=AppConfig(),
        data_dir=tmp_path / "data",
        adapter=_EchoAdapter(),
        trace_sink=lambda kind, text: events.append((kind, text)),
    )
    runtime.tracer.enabled = True

    for name in ("session_store.db", "memory_facts.db", "recipes.db", "vault.db", "vault.key"):
        assert (runtime.data_dir / name).exists()
    for folder in ProtectedFolder:
        assert (runtime.data_dir / "wiki_vault" / folder.value).is_dir()

    session = runtime.kernel.session_repo.create_session("smoke")
    resp = await runtime.kernel.handle_user_turn(
        UserTurnRequest(session_id=session.session_id, user_input="ping")
    )
    assert resp.response_text == "echo: ping"
    assert [k for k, _ in events] == ["request", "reasoning", "delta", "end"]


def test_keyfile_is_stable_across_loads(tmp_path: Path) -> None:
    first = load_or_create_master_key(tmp_path)
    assert load_or_create_master_key(tmp_path) == first


def test_passphrase_key_uses_persisted_salt(tmp_path: Path) -> None:
    first = load_or_create_master_key(tmp_path, passphrase="pw")
    assert (tmp_path / "vault.salt").exists()
    assert load_or_create_master_key(tmp_path, passphrase="pw") == first
    assert load_or_create_master_key(tmp_path, passphrase="other") != first
