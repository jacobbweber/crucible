"""Tabular and frontmatter parser for Pocock-formatted SKILL.md runbooks."""

import re
from typing import Any

import yaml

from agent_os.domain.runbook import RunbookDefinition


class PocockRunbookParser:
    """Parser and validator for Pocock-standardized SKILL.md operational runbooks."""

    @staticmethod
    def _extract_list_items(text: str) -> list[str]:
        """Extract bulleted or numbered list items from markdown section text."""
        items: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("- ") or stripped.startswith("* "):
                item = stripped[2:].strip()
                if item:
                    items.append(item)
            else:
                num_match = re.match(r"^\d+\.\s+(.*)$", stripped)
                if num_match:
                    item = num_match.group(1).strip()
                    if item:
                        items.append(item)
        return items

    @classmethod
    def parse_runbook(cls, markdown_content: str) -> RunbookDefinition:
        """Parse, validate, and construct a RunbookDefinition from SKILL.md content."""
        lines = markdown_content.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            raise ValueError("Runbook frontmatter missing: content must begin with '---'")

        closing_idx = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                closing_idx = i
                break

        if closing_idx == -1:
            raise ValueError("Runbook frontmatter missing closing '---' delimiter")

        yaml_text = "".join(lines[1:closing_idx])
        body = "".join(lines[closing_idx + 1 :])

        if not yaml_text.strip():
            raise ValueError("Runbook frontmatter block cannot be empty")

        try:
            data: Any = yaml.safe_load(yaml_text)
        except Exception as exc:
            raise ValueError(f"Unparseable YAML frontmatter: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError("Runbook frontmatter must be a YAML mapping")

        # Validate required frontmatter keys
        name = data.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            raise ValueError("Runbook frontmatter requires a non-empty 'name'")

        description = data.get("description")
        if not description or not isinstance(description, str) or not description.strip():
            raise ValueError("Runbook frontmatter requires a non-empty 'description'")

        if len(description) > 200:
            raise ValueError(
                f"Runbook description length ({len(description)}) exceeds 200 characters"
            )

        raw_tags = data.get("tags")
        if not isinstance(raw_tags, list) or len(raw_tags) == 0:
            raise ValueError("Runbook frontmatter requires a non-empty 'tags' list")
        tags = [str(t).strip() for t in raw_tags if str(t).strip()]
        if not tags:
            raise ValueError("Runbook tags list cannot be empty")

        raw_tools = data.get("required_tools", [])
        if not isinstance(raw_tools, list):
            raise ValueError("Runbook 'required_tools' must be a list of tool names")
        required_tools = [str(t).strip() for t in raw_tools if str(t).strip()]

        # Extract markdown H2 sections
        heading_matches = list(re.finditer(r"^##\s+(.+)$", body, re.MULTILINE))
        sections: dict[str, str] = {}
        for i, match in enumerate(heading_matches):
            title = match.group(1).strip()
            start = match.end()
            end = heading_matches[i + 1].start() if i + 1 < len(heading_matches) else len(body)
            sections[title] = body[start:end].strip()

        required_sections = [
            "What it does",
            "When to reach for it",
            "Structured Procedural Steps",
            "Verification & Completion Criteria",
        ]
        for req_sec in required_sections:
            if req_sec not in sections or not sections[req_sec]:
                raise ValueError(f"Missing or empty required section: '## {req_sec}'")

        procedural_steps = cls._extract_list_items(sections["Structured Procedural Steps"])
        if not procedural_steps:
            raise ValueError(
                "Section '## Structured Procedural Steps' must contain at least one list item"
            )

        verification_criteria = cls._extract_list_items(
            sections["Verification & Completion Criteria"]
        )
        if not verification_criteria:
            raise ValueError(
                "Section '## Verification & Completion Criteria' requires at least one list item"
            )

        prerequisites = cls._extract_list_items(sections.get("Prerequisites & Tool Bindings", ""))

        try:
            return RunbookDefinition(
                name=name.strip(),
                description=description.strip(),
                required_tools=required_tools,
                tags=tags,
                what_it_does=sections["What it does"],
                when_to_reach_for_it=sections["When to reach for it"],
                prerequisites=prerequisites,
                procedural_steps=procedural_steps,
                verification_criteria=verification_criteria,
            )
        except Exception as exc:
            raise ValueError(f"Runbook validation failed: {exc}") from exc
