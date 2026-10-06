"""Composition root: builds a fully wired AgentOSKernel from configuration."""

from dataclasses import dataclass
from pathlib import Path

from agent_os.domain.config import AppConfig
from agent_os.domain.kernel import KernelConfig
from agent_os.infrastructure.config import resolve_data_dir
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.gateway.semaphore import InferenceSemaphore
from agent_os.infrastructure.gateway.tracing import TraceSink, TracingModelAdapter
from agent_os.infrastructure.gateway.vllm import VllmAdapter
from agent_os.infrastructure.security.key_provider import load_or_create_master_key
from agent_os.infrastructure.security.vault_repo import CredentialVaultRepository
from agent_os.infrastructure.storage.education_repo import EducationRepository
from agent_os.infrastructure.storage.facts_repo import FactRepository
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.master_kernel import AgentOSKernel


@dataclass
class Runtime:
    """A bootstrapped runtime: kernel plus the resolved environment it runs in."""

    kernel: AgentOSKernel
    app_config: AppConfig
    data_dir: Path
    tracer: TracingModelAdapter


def _null_sink(_kind: str, _text: str) -> None:
    """Discard trace events."""


def build_runtime(
    app_config: AppConfig | None = None,
    data_dir: str | Path | None = None,
    kernel_config: KernelConfig | None = None,
    adapter: BaseModelAdapter | None = None,
    trace_sink: TraceSink | None = None,
) -> Runtime:
    """Resolve storage, provision key material, and assemble the kernel and subsystems."""
    cfg = app_config or AppConfig()
    root = resolve_data_dir(data_dir if data_dir is not None else cfg.data_dir)
    k_cfg = kernel_config or KernelConfig(
        storage_root=str(root),
        context_window=cfg.vllm_context_window,
    )
    semaphore = InferenceSemaphore(max_concurrency=k_cfg.max_concurrency)

    wiki_store = WikiStore(root / "wiki_vault")
    wiki_store.init_vault()

    base_adapter = adapter or VllmAdapter(cfg, semaphore=semaphore)
    tracer = TracingModelAdapter(base_adapter, sink=trace_sink or _null_sink)
    master_key = load_or_create_master_key(root, cfg.vault_passphrase)

    kernel = AgentOSKernel(
        config=k_cfg,
        session_repo=SessionRepository(root / "session_store.db"),
        facts_repo=FactRepository(root / "memory_facts.db"),
        recipe_repo=RecipeRepository(root / "recipes.db"),
        education_repo=EducationRepository(root / "education.db"),
        vault_repo=CredentialVaultRepository(root / "vault.db", master_key=master_key),
        wiki_store=wiki_store,
        model_adapter=tracer,
        semaphore=semaphore,
    )
    return Runtime(kernel=kernel, app_config=cfg, data_dir=root, tracer=tracer)
