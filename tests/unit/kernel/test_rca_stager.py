"""Unit tests for RcaProposalStager and 00_Inbox proposal graduation."""

from pathlib import Path

import pytest

from agent_os.domain.wiki import ProtectedFolder
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.graduation import GraduationService
from agent_os.kernel.rca_stager import RcaProposalStager, slugify_rca_title


@pytest.fixture
def temp_warehouse(tmp_path: Path):
    warehouse_dir = tmp_path / "warehouse"
    warehouse_dir.mkdir(parents=True, exist_ok=True)
    wiki_store = WikiStore(warehouse_dir)
    return wiki_store, warehouse_dir


def test_slugify_rca_title():
    assert slugify_rca_title("Web Fetch Timeout Spike") == "web_fetch_timeout_spike"
    assert slugify_rca_title("  High Memory Leak! (v1)  ") == "high_memory_leak_v1"
    assert slugify_rca_title("") == "unspecified_issue"


def test_stage_issue_to_inbox_and_graduate(temp_warehouse):
    wiki_store, warehouse_dir = temp_warehouse
    stager = RcaProposalStager(wiki_store)

    staged_path = stager.stage_issue(
        title="Web Fetch Timeout Spike",
        issue_summary="Tool web_fetch failed 6 out of 18 times during peak hours.",
        root_cause="Default timeout was set to 10.0s, insufficient for slow internal services.",
        suggested_remediation="Increase default web_fetch timeout to 20.0s.",
        severity="warning",
        evidence={"failed_spans": ["span_1", "span_2"], "error_rate": "33%"},
    )

    # 1. Verify placed in 00_Inbox (The Sacred Rule of 00_Inbox)
    assert staged_path.exists()
    assert staged_path.parent == warehouse_dir / ProtectedFolder.INBOX.value
    assert staged_path.name == "rca_web_fetch_timeout_spike.md"

    # 2. Verify file content structure and frontmatter
    content = staged_path.read_text(encoding="utf-8")
    assert 'title: "RCA: Web Fetch Timeout Spike"' in content
    assert 'category: "proposals"' in content
    assert "- rca" in content
    assert "- health_audit" in content
    assert 'severity: "warning"' in content
    assert "Root Cause Analysis: Web Fetch Timeout Spike" in content
    assert "span_1" in content

    # 3. Verify GraduationService can graduate this proposal into 01_Knowledge/proposals/
    grad_service = GraduationService(wiki_store)
    report = grad_service.execute_graduation()
    assert report.graduated_count == 1
    assert report.failed_count == 0

    target_knowledge_folder = (
        ProtectedFolder.KNOWLEDGE.value
        if (warehouse_dir / ProtectedFolder.KNOWLEDGE.value).exists()
        else ProtectedFolder.NOTES.value
    )
    graduated_file = (
        warehouse_dir / target_knowledge_folder / "proposals" / "rca_web_fetch_timeout_spike.md"
    )
    assert graduated_file.exists()
    assert not staged_path.exists()  # Removed from 00_Inbox upon graduation
