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
