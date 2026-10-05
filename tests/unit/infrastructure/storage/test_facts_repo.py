"""Unit tests for FactRepository persistence, entity lookup, and FTS5 search."""

from pathlib import Path

from agent_os.infrastructure.storage.facts_repo import FactRepository


def test_save_and_retrieve_fact(tmp_path: Path) -> None:
    """Verify saving fact persists into SQLite and retrieves identical fields."""
    db_file = tmp_path / "memory_facts.db"
    repo = FactRepository(db_file)

    saved = repo.save_fact(
        entity_key="user_profile",
        fact_text="User prefers Python over JavaScript",
        category="preferences",
        source_turn_id="turn_123",
    )

    assert saved.entity_key == "user_profile"
    assert saved.fact_text == "User prefers Python over JavaScript"
    assert saved.category == "preferences"
    assert saved.source_turn_id == "turn_123"

    retrieved = repo.get_fact(saved.fact_id)
    assert retrieved is not None
    assert retrieved.fact_id == saved.fact_id
    assert retrieved.entity_key == saved.entity_key
    assert retrieved.fact_text == saved.fact_text
    assert retrieved.category == saved.category
    assert retrieved.source_turn_id == saved.source_turn_id
    assert retrieved.created_at == saved.created_at
    assert retrieved.updated_at == saved.updated_at

    # Non-existent fact
    assert repo.get_fact("non_existent_fact_id") is None


def test_list_by_entity_key(tmp_path: Path) -> None:
    """Insert facts across multiple entity keys; verify querying homelab returns matches."""
    db_file = tmp_path / "memory_facts.db"
    repo = FactRepository(db_file)

    repo.save_fact(entity_key="user", fact_text="User name is Alice")
    f_home1 = repo.save_fact(entity_key="homelab", fact_text="Proxmox node IP is 192.168.1.50")
    f_home2 = repo.save_fact(entity_key="homelab", fact_text="ZFS pool has 4x 8TB drives")
    repo.save_fact(entity_key="nas", fact_text="Synology NAS running DSM 7")

    homelab_facts = repo.list_by_entity("homelab")
    assert len(homelab_facts) == 2
    assert {f.fact_id for f in homelab_facts} == {f_home1.fact_id, f_home2.fact_id}
    assert all(f.entity_key == "homelab" for f in homelab_facts)


def test_fts5_lexical_search(tmp_path: Path) -> None:
    """Insert trimmer assertion, execute search query 'trimmer', assert positive score."""
    db_file = tmp_path / "memory_facts.db"
    repo = FactRepository(db_file)

    assertion = "Ryobi 4-cycle string trimmer requires 40:1 fuel mixture"
    saved = repo.save_fact(
        entity_key="garden_tools",
        fact_text=assertion,
        category="maintenance",
    )

    results = repo.search_facts("trimmer")
    assert len(results) >= 1
    top_result = results[0]
    assert top_result.fact.fact_id == saved.fact_id
    assert top_result.fact.fact_text == assertion
    assert top_result.score > 0.0


def test_update_fact_syncs_fts(tmp_path: Path) -> None:
    """Update fact text; verify search on old text returns 0 results and new text matches."""
    db_file = tmp_path / "memory_facts.db"
    repo = FactRepository(db_file)

    fact = repo.save_fact(
        entity_key="server_hardware",
        fact_text="Database server runs on Dell PowerEdge R720",
    )

    # Initial search matches old text
    assert len(repo.search_facts("PowerEdge")) == 1

    # Update fact to new hardware
    updated = repo.update_fact(
        fact_id=fact.fact_id,
        new_text="Database server migrated to Supermicro EPYC server",
    )
    assert updated.fact_text == "Database server migrated to Supermicro EPYC server"
    assert updated.updated_at >= fact.updated_at

    # Old text should return zero results
    assert len(repo.search_facts("PowerEdge")) == 0

    # New text should match
    new_results = repo.search_facts("Supermicro")
    assert len(new_results) == 1
    assert new_results[0].fact.fact_id == fact.fact_id


def test_delete_fact_removes_from_fts(tmp_path: Path) -> None:
    """Delete fact; verify subsequent FTS search returns empty list."""
    db_file = tmp_path / "memory_facts.db"
    repo = FactRepository(db_file)

    fact = repo.save_fact(
        entity_key="temporary_memo",
        fact_text="Secret password rotation scheduled for midnight",
    )

    assert len(repo.search_facts("rotation")) == 1

    deleted = repo.delete_fact(fact.fact_id)
    assert deleted is True
    assert repo.get_fact(fact.fact_id) is None

    # Deleting again returns False
    assert repo.delete_fact(fact.fact_id) is False

    # Search should now return empty list
    assert repo.search_facts("rotation") == []
