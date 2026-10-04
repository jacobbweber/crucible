"""YAML frontmatter parsing and serialization."""

from typing import Any, overload

import yaml

from agent_os.domain.wiki import NoteFrontmatter


def parse_frontmatter(content: str) -> tuple[NoteFrontmatter, str]:
    """Parse leading YAML frontmatter enclosed by '---' and return frontmatter and body.

    Raises:
        ValueError: If frontmatter is missing, unclosed, invalid YAML, or fails validation.
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("Frontmatter block is missing: content must start with '---'")

    closing_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            closing_idx = i
            break

    if closing_idx == -1:
        raise ValueError("Frontmatter block is not closed: missing terminating '---'")

    yaml_text = "".join(lines[1:closing_idx])
    body = "".join(lines[closing_idx + 1 :])

    if not yaml_text.strip():
        raise ValueError("Frontmatter block is empty")

    try:
        data: Any = yaml.safe_load(yaml_text)
    except Exception as exc:
        raise ValueError(f"Unparseable YAML frontmatter: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Frontmatter must be a YAML mapping")

    try:
        frontmatter = NoteFrontmatter.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Frontmatter validation failed: {exc}") from exc

    return frontmatter, body


@overload
def serialize_note(frontmatter: tuple[NoteFrontmatter, str]) -> str: ...


@overload
def serialize_note(frontmatter: NoteFrontmatter, body: str) -> str: ...


def serialize_note(
    frontmatter: NoteFrontmatter | tuple[NoteFrontmatter, str],
    body: str | None = None,
) -> str:
    """Serialize NoteFrontmatter into standardized YAML block prepended to markdown body."""
    if isinstance(frontmatter, tuple):
        fm, raw_body = frontmatter
        actual_body = body if body is not None else raw_body
    else:
        fm = frontmatter
        actual_body = body if body is not None else ""

    data = fm.model_dump()
    yaml_block = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    return f"---\n{yaml_block}---\n{actual_body}"
