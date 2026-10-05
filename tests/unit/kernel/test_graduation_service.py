"""Unit tests for GraduationService and wiki_graduate_inbox capability tool."""

from pathlib import Path

from agent_os.domain.policy import ActionTier
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.graduation import GraduationService
from agent_os.kernel.wiki_tools import WikiToolSuite


def test_graduation_service_moves_compliant_notes(tmp_path: Path) -> None:
    """Verify GraduationService graduates compliant notes from inbox into category notes."""
    store = WikiStore(tmp_path)
    store.init_vault()

    inbox = tmp_path / "00_Inbox"
    (inbox / "note1.md").write_text(
        "---\ntitle: Note 1\ncategory: dev\ntags: [python, ai]\n---\nBody content 1\n",
        encoding="utf-8",
    )
    (inbox / "note2.md").write_text(
        "---\ntitle: Note 2\ncategory: ops\ntags: [linux]\n---\nBody content 2\n",
        encoding="utf-8",
    )

    service = GraduationService(store)
    report = service.execute_graduation()

    assert report.graduated_count == 2
    assert report.failed_count == 0
    assert (tmp_path / "01_Notes" / "dev" / "note1.md").is_file()
    assert (tmp_path / "01_Notes" / "ops" / "note2.md").is_file()
    assert not (inbox / "note1.md").exists()
    assert not (inbox / "note2.md").exists()


def test_graduation_service_quarantines_invalid_notes(tmp_path: Path) -> None:
    """Verify invalid notes remain quarantined in 00_Inbox/ with failure reasons listed."""
    store = WikiStore(tmp_path)
    store.init_vault()

    inbox = tmp_path / "00_Inbox"
    (inbox / "invalid.md").write_text(
        "---\ntitle: Note without tags\ncategory: dev\ntags: []\n---\nBody content\n",
        encoding="utf-8",
    )

    service = GraduationService(store)
    report = service.execute_graduation()

    assert report.graduated_count == 0
    assert report.failed_count == 1
    assert (inbox / "invalid.md").is_file()
    assert len(report.failures) == 1
    assert report.failures[0].filename == "invalid.md"
    assert len(report.failures[0].reasons) > 0
    assert any("tags" in r.lower() for r in report.failures[0].reasons)


def test_wiki_graduate_inbox_tool_execution(tmp_path: Path) -> None:
    """Verify executing wiki_graduate_inbox tool yields success and formatted markdown output."""
    store = WikiStore(tmp_path)
    store.init_vault()

    inbox = tmp_path / "00_Inbox"
    (inbox / "good.md").write_text(
        "---\ntitle: K8s Config\ncategory: infra\ntags: [k8s]\n---\nCluster guide\n",
        encoding="utf-8",
    )
    (inbox / "bad.md").write_text(
        "---\ntitle: ''\ncategory: infra\ntags: [k8s]\n---\nMissing title\n",
        encoding="utf-8",
    )

    suite = WikiToolSuite(store)
    result = suite.wiki_graduate_inbox()

    assert result.success is True
    assert "Graduated 1 notes, 1 failed." in result.output
    assert "good.md" in result.output
    assert "bad.md" in result.output
    assert (tmp_path / "01_Notes" / "infra" / "good.md").is_file()
    assert (inbox / "bad.md").is_file()


def test_wiki_tool_definitions_includes_graduation(tmp_path: Path) -> None:
    """Verify get_definitions includes wiki_graduate_inbox with ActionTier.STATE_CHANGE."""
    store = WikiStore(tmp_path)
    store.init_vault()
    suite = WikiToolSuite(store)

    definitions = suite.get_definitions()
    grad_def = next((d for d in definitions if d.name == "wiki_graduate_inbox"), None)

    assert grad_def is not None
    assert grad_def.action_tier == ActionTier.STATE_CHANGE
    assert grad_def.parameters == []
