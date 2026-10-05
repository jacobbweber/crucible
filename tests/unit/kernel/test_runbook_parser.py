"""Unit tests for PocockRunbookParser SKILL.md parsing and validation."""

import pytest

from agent_os.kernel.runbook_parser import PocockRunbookParser

VALID_SKILL_MARKDOWN = """---
name: deploy-service
description: Automates cloud service deployment and health verification.
tags:
  - ops
  - deployment
required_tools:
  - bash
  - curl
---

## What it does
Builds, deploys, and verifies an isolated cloud microservice instance.

## When to reach for it
Reach for this runbook whenever promoting an artifact from staging to production.

## Prerequisites & Tool Bindings
- Cloud credentials configured in vault
- Active network connection

## Structured Procedural Steps
1. Pull latest verified container image
2. Apply Kubernetes manifest
- Wait for rollout completion

## Verification & Completion Criteria
- HTTP 200 returned from /health endpoint
- Zero crash loop backoffs detected
"""


def test_parse_valid_pocock_runbook() -> None:
    """Parse compliant SKILL.md; verify all fields populate cleanly into RunbookDefinition."""
    runbook = PocockRunbookParser.parse_runbook(VALID_SKILL_MARKDOWN)

    assert runbook.name == "deploy-service"
    assert runbook.description == "Automates cloud service deployment and health verification."
    assert runbook.tags == ["ops", "deployment"]
    assert runbook.required_tools == ["bash", "curl"]
    assert (
        runbook.what_it_does
        == "Builds, deploys, and verifies an isolated cloud microservice instance."
    )
    assert (
        runbook.when_to_reach_for_it
        == "Reach for this runbook whenever promoting an artifact from staging to production."
    )
    assert runbook.prerequisites == [
        "Cloud credentials configured in vault",
        "Active network connection",
    ]
    assert runbook.procedural_steps == [
        "Pull latest verified container image",
        "Apply Kubernetes manifest",
        "Wait for rollout completion",
    ]
    assert runbook.verification_criteria == [
        "HTTP 200 returned from /health endpoint",
        "Zero crash loop backoffs detected",
    ]


def test_parse_description_length_enforced() -> None:
    """Verify frontmatter with description > 200 chars raises ValueError."""
    long_desc = "A" * 201
    invalid_markdown = VALID_SKILL_MARKDOWN.replace(
        "Automates cloud service deployment and health verification.",
        long_desc,
    )

    with pytest.raises(ValueError, match="exceeds 200 characters"):
        PocockRunbookParser.parse_runbook(invalid_markdown)


def test_parse_missing_required_section_raises() -> None:
    """Omit ## Verification & Completion Criteria; verify parser raises ValueError."""
    lines = [
        line
        for line in VALID_SKILL_MARKDOWN.splitlines(keepends=True)
        if "Verification & Completion Criteria" not in line
        and "HTTP 200" not in line
        and "Zero crash loop" not in line
    ]
    missing_section_markdown = "".join(lines)

    with pytest.raises(ValueError, match="Missing or empty required section"):
        PocockRunbookParser.parse_runbook(missing_section_markdown)
