"""Unit tests for inbox graduation mechanism."""

from pathlib import Path

from agent_os.domain.wiki import NoteFrontmatter, ProtectedFolder
from agent_os.infrastructure.wiki.store import WikiStore


def test_graduate_valid_note_moves_to_category(tmp_path: Path) -> None:
    """Verify staged note with valid category: homelab moves from 00_Inbox/ to 01_Notes/homelab/."""
    vault_root = tmp_path / "vault"
    store = WikiStore(vault_root)
    store.init_vault()

    frontmatter = NoteFrontmatter(
        title="Server Architecture",
        category="homelab",
        tags=["proxmox", "linux"],
    )
    store.write_note("00_Inbox/server.md", frontmatter, "# Server Guide")

    report = store.graduate_inbox()

    assert report.graduated_count == 1
    assert report.failed_count == 0
    assert "server.md" in report.graduated_files
    assert not (vault_root / ProtectedFolder.INBOX.value / "server.md").exists()

    destination_file = vault_root / ProtectedFolder.NOTES.value / "homelab" / "server.md"
    assert destination_file.is_file()

    fm_read, body_read = store.read_note("01_Notes/homelab/server.md")
    assert fm_read.title == "Server Architecture"
    assert fm_read.category == "homelab"
    assert fm_read.tags == ["proxmox", "linux"]
    assert "# Server Guide" in body_read


def test_graduate_invalid_note_stays_in_inbox_with_reasons(tmp_path: Path) -> None:
    """Verify note missing tags remains in 00_Inbox/ and report lists explicit failure reason."""
    vault_root = tmp_path / "vault"
    store = WikiStore(vault_root)
    store.init_vault()

    invalid_content = "---\ntitle: Untagged Note\ncategory: homelab\n---\n# Content without tags"
    inbox_file = vault_root / ProtectedFolder.INBOX.value / "invalid_note.md"
    inbox_file.write_text(invalid_content, encoding="utf-8")

    report = store.graduate_inbox()

    assert report.graduated_count == 0
    assert report.failed_count == 1
    assert inbox_file.is_file()
    assert len(report.failures) == 1
    assert report.failures[0].filename == "invalid_note.md"
    assert any("tags" in reason.lower() for reason in report.failures[0].reasons)
