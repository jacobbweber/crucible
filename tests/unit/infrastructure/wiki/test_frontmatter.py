"""Unit tests for YAML frontmatter parser and serializer."""

import pytest

from agent_os.infrastructure.wiki.frontmatter import parse_frontmatter, serialize_note


def test_parse_valid_frontmatter() -> None:
    """Verify valid YAML block parses and cleanly separates markdown body."""
    raw_content = (
        "---\n"
        "title: Setup Homelab\n"
        "category: homelab\n"
        "tags:\n"
        "  - server\n"
        "  - docker\n"
        "---\n"
        "# Homelab Architecture\n\n"
        "This is the body content."
    )

    frontmatter, body = parse_frontmatter(raw_content)

    assert frontmatter.title == "Setup Homelab"
    assert frontmatter.category == "homelab"
    assert frontmatter.tags == ["server", "docker"]
    assert body.strip() == "# Homelab Architecture\n\nThis is the body content."


def test_parse_missing_frontmatter_raises() -> None:
    """Verify content without '---' raises ValueError."""
    raw_content = "# Just a markdown header without frontmatter\nBody text"
    with pytest.raises(ValueError, match="Frontmatter block is missing"):
        parse_frontmatter(raw_content)


def test_parse_missing_required_fields() -> None:
    """Verify YAML missing tags or category fails validation."""
    missing_tags = "---\ntitle: Missing Tags Note\ncategory: homelab\n---\nBody content"
    with pytest.raises(ValueError, match="Frontmatter validation failed"):
        parse_frontmatter(missing_tags)

    missing_category = "---\ntitle: Missing Category Note\ntags:\n  - linux\n---\nBody content"
    with pytest.raises(ValueError, match="Frontmatter validation failed"):
        parse_frontmatter(missing_category)


def test_serialize_round_trip() -> None:
    """Verify serialize_note(parse_frontmatter(text)) maintains full fidelity."""
    original_text = (
        "---\n"
        "title: Round Trip Test\n"
        "category: devops\n"
        "tags:\n"
        "- k8s\n"
        "- ci\n"
        "---\n"
        "# Markdown Body\n"
        "Exact text preserved during serialization."
    )

    parsed_tuple = parse_frontmatter(original_text)
    serialized_str = serialize_note(parsed_tuple)

    fm_roundtrip, body_roundtrip = parse_frontmatter(serialized_str)

    assert fm_roundtrip.title == parsed_tuple[0].title
    assert fm_roundtrip.category == parsed_tuple[0].category
    assert fm_roundtrip.tags == parsed_tuple[0].tags
    assert body_roundtrip == parsed_tuple[1]
