"""Domain models for agentic tool synthesis, dry-run verification, and proposal gating."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolsmithProposal:
    """Proposal record for an agent-synthesized tool verified by pre-flight dry run."""

    tool_name: str
    domain: str
    description: str
    code_snippet: str
    dry_run_args: dict[str, Any]
    dry_run_output: str
    verified: bool
    staged_path: str = ""
    error_message: str | None = None


@dataclass
class ToolsmithSynthesisRequest:
    """Request payload to synthesize and test a new tool for an unfulfilled capability."""

    task: str
    domain: str
    available_tools: list[str] = field(default_factory=list)
