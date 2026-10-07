"""Root Cause Analysis (RCA) proposal stager formatting and staging reports to 00_Inbox."""

import re
from pathlib import Path
from typing import Any

from agent_os.domain.telemetry import RCAProposal
from agent_os.domain.wiki import ProtectedFolder
from agent_os.infrastructure.wiki.store import WikiStore


def slugify_rca_title(title: str) -> str:
    """Convert issue title into safe lowercase slug for filename."""
    slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", title.strip().lower()).strip("_")
    return slug or "unspecified_issue"


class RcaProposalStager:
    """Formats incident postmortems and drafts improvement proposals to 00_Inbox."""

    def __init__(self, wiki_store: WikiStore) -> None:
        self.wiki_store = wiki_store

    def build_rca_markdown(self, proposal: RCAProposal) -> str:
        """Render a structured Markdown document with valid YAML frontmatter."""
        detected_str = proposal.detected_at.isoformat()

        yaml_lines = [
            "---",
            f'title: "RCA: {proposal.title}"',
            'category: "proposals"',
            "tags:",
        ]
        for tag in proposal.tags:
            yaml_lines.append(f"  - {tag}")
        yaml_lines.extend(
            [
                f'severity: "{proposal.severity}"',
                f'detected_at: "{detected_str}"',
                f"proposal_id: {proposal.proposal_id}",
                "---",
                "",
                f"# Root Cause Analysis: {proposal.title}",
                "",
                "## 1. Executive Summary",
                proposal.issue_summary,
                "",
                "## 2. Telemetry Evidence",
            ]
        )

        if proposal.telemetry_evidence:
            for k, v in proposal.telemetry_evidence.items():
                if isinstance(v, list):
                    yaml_lines.append(f"- **{k}**:")
                    for item in v[:5]:
                        yaml_lines.append(f"  - `{item}`")
                elif isinstance(v, dict):
                    yaml_lines.append(f"- **{k}**: `{v}`")
                else:
                    yaml_lines.append(f"- **{k}**: {v}")
        else:
            yaml_lines.append("- No explicit span telemetry attached.")

        yaml_lines.extend(
            [
                "",
                "## 3. Root Cause Analysis",
                proposal.root_cause,
                "",
                "## 4. Suggested Remediation (Human Approval Required)",
                proposal.suggested_remediation,
                "",
                "## 5. Review Notes",
                "- [ ] Review diagnostic findings and verify local traces.",
                "- [ ] Apply configuration, recipe, or code changes if accepted.",
                "- [ ] Move to archive or graduate after resolution.",
                "",
            ]
        )

        return "\n".join(yaml_lines)

    def stage_proposal(self, proposal: RCAProposal) -> Path:
        """Stage an RCA proposal into 00_Inbox conforming to the Sacred Rule of 00_Inbox."""
        inbox_dir = self.wiki_store.root_dir / ProtectedFolder.INBOX.value
        inbox_dir.mkdir(parents=True, exist_ok=True)

        slug = slugify_rca_title(proposal.title)
        filename = f"rca_{slug}.md"
        dest_path = inbox_dir / filename

        content = self.build_rca_markdown(proposal)
        dest_path.write_text(content, encoding="utf-8")
        return dest_path

    def stage_issue(
        self,
        title: str,
        issue_summary: str,
        root_cause: str,
        suggested_remediation: str,
        severity: str = "warning",
        evidence: dict[str, Any] | None = None,
    ) -> Path:
        """Helper to construct and stage an RCA proposal directly from parameters."""
        proposal = RCAProposal(
            title=title,
            issue_summary=issue_summary,
            root_cause=root_cause,
            suggested_remediation=suggested_remediation,
            severity=severity,  # type: ignore[arg-type]
            telemetry_evidence=evidence or {},
        )
        return self.stage_proposal(proposal)
