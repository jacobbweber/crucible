"""Unit tests for FactPrefetcher entity matching, prefetching, and token budget clamping."""

from pathlib import Path

from agent_os.domain.gateway import estimate_tokens
from agent_os.infrastructure.storage.facts_repo import FactRepository
from agent_os.kernel.fact_prefetcher import FactPrefetcher


def test_prefetch_user_alias_matching(tmp_path: Path) -> None:
    """Verify user pronoun alias triggers entity_key='user' fact recall and XML tagging."""
    repo = FactRepository(tmp_path / "facts.db")
    repo.save_fact(
        entity_key="user",
        fact_text="User prefers Python and dark mode IDE theme.",
        category="preferences",
    )

    prefetcher = FactPrefetcher(repo)
    payload = prefetcher.prefetch_for_turn("Can you remind me of my preferred setup?")

    assert payload.recalled_count == 1
    assert "user" in payload.matched_entity_keys
    assert "<recalled_facts>" in payload.rendered_block
    assert "- [user]: User prefers Python and dark mode IDE theme." in payload.rendered_block
    assert "</recalled_facts>" in payload.rendered_block
    assert payload.token_estimate == estimate_tokens(payload.rendered_block)


def test_prefetch_explicit_entity_matching(tmp_path: Path) -> None:
    """Verify explicit entity keyword in query matches facts for that entity."""
    repo = FactRepository(tmp_path / "facts.db")
    repo.save_fact(
        entity_key="homelab",
        fact_text="Homelab runs TrueNAS SCALE with 64GB ECC RAM.",
        category="infrastructure",
    )
    repo.save_fact(
        entity_key="gaming",
        fact_text="Plays strategy games on weekend.",
        category="hobbies",
    )

    prefetcher = FactPrefetcher(repo)
    payload = prefetcher.prefetch_for_turn("What did we set up on homelab?")

    assert payload.recalled_count == 1
    assert "homelab" in payload.matched_entity_keys
    assert "gaming" not in payload.matched_entity_keys
    assert "Homelab runs TrueNAS SCALE" in payload.rendered_block
    assert "strategy games" not in payload.rendered_block


def test_prefetch_budget_clamping(tmp_path: Path) -> None:
    """Verify prefetcher enforces token and character ceilings when many facts match."""
    repo = FactRepository(tmp_path / "facts.db")
    for i in range(20):
        repo.save_fact(
            entity_key="homelab",
            fact_text=f"Server node #{i} has configured network gateway and storage volume.",
            category="infrastructure",
        )

    prefetcher = FactPrefetcher(repo, token_ceiling=300)
    payload = prefetcher.prefetch_for_turn("Show homelab status")

    assert payload.token_estimate <= 300
    assert len(payload.rendered_block) <= 1200
    assert payload.recalled_count > 0
    assert payload.recalled_count < 20
    assert "<recalled_facts>" in payload.rendered_block
    assert "</recalled_facts>" in payload.rendered_block


def test_prefetch_empty_when_no_matches(tmp_path: Path) -> None:
    """Verify empty string and zero counters when no facts match query tokens."""
    repo = FactRepository(tmp_path / "facts.db")
    repo.save_fact(
        entity_key="kubernetes",
        fact_text="Cluster version is 1.30.",
        category="infra",
    )

    prefetcher = FactPrefetcher(repo)
    payload = prefetcher.prefetch_for_turn("Hello how are you?")

    assert payload.rendered_block == ""
    assert payload.recalled_count == 0
    assert payload.token_estimate == 0
    assert payload.matched_entity_keys == []
