"""Unit tests for WikiStore filesystem engine."""

from pathlib import Path

import pytest

from agent_os.domain.wiki import NoteFrontmatter, ProtectedFolder
from agent_os.infrastructure.wiki.store import WikiStore


def test_init_vault_creates_protected_folders(tmp_path: Path) -> None:
    """Verify init_vault creates all 4 root folders and 02_Resources/templates/."""
    vault_root = tmp_path / "vault"
    store = WikiStore(vault_root)
    store.init_vault()

    assert (vault_root / ProtectedFolder.INBOX.value).is_dir()
    assert (vault_root / ProtectedFolder.NOTES.value).is_dir()
    assert (vault_root / ProtectedFolder.RESOURCES.value).is_dir()
    assert (vault_root / ProtectedFolder.ARCHIVE.value).is_dir()
    assert (vault_root / ProtectedFolder.RESOURCES.value / "templates").is_dir()


def test_path_traversal_prevention(tmp_path: Path) -> None:
    """Verify reading/writing outside vault root raises ValueError."""
    vault_root = tmp_path / "vault"
    store = WikiStore(vault_root)
    store.init_vault()

    frontmatter = NoteFrontmatter(
        title="Exploit",
        category="security",
        tags=["exploit"],
    )

    with pytest.raises(ValueError, match="Path traversal detected"):
        store.read_note("../../etc/passwd")

    with pytest.raises(ValueError, match="Path traversal detected"):
        store.write_note("../../etc/passwd", frontmatter, "malicious payload")


def test_write_and_read_note_line_budget(tmp_path: Path) -> None:
    """Verify read_note truncates at max_lines."""
    vault_root = tmp_path / "vault"
    store = WikiStore(vault_root)
    store.init_vault()

    frontmatter = NoteFrontmatter(
        title="Line Budget Note",
        category="testing",
        tags=["budget"],
    )
    long_body = "\n".join(f"Line {i}" for i in range(100))

    note_path = "01_Notes/testing/long_note.md"
    store.write_note(note_path, frontmatter, long_body)

    fm_read, body_read = store.read_note(note_path, max_lines=25)

    assert fm_read.title == "Line Budget Note"
    lines = body_read.splitlines()
    assert len(lines) == 25
    assert lines[0] == "Line 0"
    assert lines[-1] == "Line 24"


def test_resolve_safe_path_public_and_alias(tmp_path: Path) -> None:
    """Verify resolve_safe_path returns absolute path within vault and rejects traversal."""
    vault_root = tmp_path / "vault"
    store = WikiStore(vault_root)
    store.init_vault()

    safe = store.resolve_safe_path("01_Notes/sub/note.md")
    assert safe == (vault_root / "01_Notes/sub/note.md").resolve()

    # Alias check
    assert store._resolve_safe_path("01_Notes/sub/note.md") == safe

    with pytest.raises(ValueError, match="Path traversal detected"):
        store.resolve_safe_path("../outside.md")


def test_read_note_detailed_budget_metrics(tmp_path: Path) -> None:
    """Verify read_note_detailed returns total_lines and is_clamped accurate metrics."""
    vault_root = tmp_path / "vault"
    store = WikiStore(vault_root)
    store.init_vault()

    fm = NoteFrontmatter(title="Metrics Test", category="testing", tags=["metrics"])
    body = "\n".join(f"Line {i}" for i in range(50))
    note_path = "01_Notes/testing/metrics.md"
    store.write_note(note_path, fm, body)

    # When clamped
    fm_read, body_clamped, total_lines, is_clamped = store.read_note_detailed(
        note_path, max_lines=20
    )
    assert fm_read.title == "Metrics Test"
    assert total_lines == 50
    assert is_clamped is True
    assert len(body_clamped.splitlines()) == 20

    # When not clamped
    _, body_full, total_lines2, is_clamped2 = store.read_note_detailed(note_path, max_lines=100)
    assert total_lines2 == 50
    assert is_clamped2 is False
    assert len(body_full.splitlines()) == 50


def test_search_notes_matching_fields_and_limit(tmp_path: Path) -> None:
    """Verify search_notes matches title, tags, and body while skipping non-matching files."""
    vault_root = tmp_path / "vault"
    store = WikiStore(vault_root)
    store.init_vault()

    store.write_note(
        "01_Notes/dev/python.md",
        NoteFrontmatter(title="Python Guide", category="dev", tags=["async", "typing"]),
        "Python guidelines and best practices.",
    )
    store.write_note(
        "01_Notes/ops/docker.md",
        NoteFrontmatter(title="Container Setup", category="ops", tags=["docker", "compose"]),
        "Instructions on how to configure and run Docker containers.",
    )
    store.write_note(
        "01_Notes/ops/irrelevant.md",
        NoteFrontmatter(title="Something Else", category="ops", tags=["misc"]),
        "Completely unrelated text without any keywords.",
    )

    # Match by title
    matches = store.search_notes("Python")
    assert len(matches) == 1
    assert "01_Notes/dev/python.md" in matches[0][0]

    # Match by tag
    matches = store.search_notes("compose")
    assert len(matches) == 1
    assert "01_Notes/ops/docker.md" in matches[0][0]

    # Match by body
    matches = store.search_notes("best practices")
    assert len(matches) == 1
    assert "01_Notes/dev/python.md" in matches[0][0]

    # No match
    matches = store.search_notes("nonexistent_term")
    assert len(matches) == 0
