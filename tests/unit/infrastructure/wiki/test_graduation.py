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


def test_graduate_collision_disambiguates_without_overwriting(tmp_path: Path) -> None:
    """Verify existing note in category is NOT overwritten; incoming note gets numbered suffix."""
    vault_root = tmp_path / "vault"
    store = WikiStore(vault_root)
    store.init_vault()

    # Pre-existing permanent note
    dest_dir = vault_root / ProtectedFolder.NOTES.value / "homelab"
    dest_dir.mkdir(parents=True, exist_ok=True)
    existing_file = dest_dir / "server.md"
    existing_file.write_text("ORIGINAL PERMANENT CONTENT", encoding="utf-8")

    # Staged note with identical filename
    fm = NoteFrontmatter(
        title="Server Architecture v2",
        category="homelab",
        tags=["proxmox"],
    )
    store.write_note("00_Inbox/server.md", fm, "NEW CONTENT")

    report = store.graduate_inbox(collision_resolution="rename")

    assert report.graduated_count == 1
    assert report.failed_count == 0
    assert report.graduated_files == ["server_1.md"]
    assert not (vault_root / ProtectedFolder.INBOX.value / "server.md").exists()

    # Verify original note is untouched
    assert existing_file.read_text(encoding="utf-8") == "ORIGINAL PERMANENT CONTENT"

    # Verify disambiguated note exists
    disambiguated = dest_dir / "server_1.md"
    assert disambiguated.is_file()
    fm_read, body_read = store.read_note("01_Notes/homelab/server_1.md")
    assert fm_read.title == "Server Architecture v2"
    assert "NEW CONTENT" in body_read

    # Stage another note with same name to verify server_2.md
    store.write_note("00_Inbox/server.md", fm, "THIRD CONTENT")
    report2 = store.graduate_inbox(collision_resolution="rename")
    assert report2.graduated_files == ["server_2.md"]
    assert (dest_dir / "server_2.md").is_file()


def test_graduate_collision_fail_mode(tmp_path: Path) -> None:
    """Verify collision_resolution='fail' halts graduation without data loss."""
    vault_root = tmp_path / "vault"
    store = WikiStore(vault_root)
    store.init_vault()

    dest_dir = vault_root / ProtectedFolder.NOTES.value / "homelab"
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "server.md").write_text("ORIGINAL CONTENT", encoding="utf-8")

    fm = NoteFrontmatter(
        title="Server Architecture",
        category="homelab",
        tags=["proxmox"],
    )
    inbox_file = vault_root / ProtectedFolder.INBOX.value / "server.md"
    store.write_note("00_Inbox/server.md", fm, "NEW CONTENT")

    report = store.graduate_inbox(collision_resolution="fail")

    assert report.graduated_count == 0
    assert report.failed_count == 1
    assert inbox_file.is_file()
    assert any("already exists" in r.lower() for r in report.failures[0].reasons)
    assert (dest_dir / "server.md").read_text(encoding="utf-8") == "ORIGINAL CONTENT"


def test_graduate_rejects_category_path_traversal(tmp_path: Path) -> None:
    """Verify notes with escaping categories are rejected and quarantined."""
    vault_root = tmp_path / "vault"
    store = WikiStore(vault_root)
    store.init_vault()

    fm = NoteFrontmatter(
        title="Malicious Note",
        category="../../outside",
        tags=["exploit"],
    )
    inbox_file = vault_root / ProtectedFolder.INBOX.value / "exploit.md"
    store.write_note("00_Inbox/exploit.md", fm, "malicious payload")

    report = store.graduate_inbox()

    assert report.graduated_count == 0
    assert report.failed_count == 1
    assert inbox_file.is_file()
    assert any("invalid" in r.lower() or "escape" in r.lower() for r in report.failures[0].reasons)
