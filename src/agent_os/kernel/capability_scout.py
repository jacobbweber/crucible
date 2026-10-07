"""Capability scout and proposal stager for unfulfilled external tool requirements."""

import re
from datetime import UTC, datetime
from typing import Any

from agent_os.domain.wiki import ProtectedFolder


class CapabilityScout:
    """Detects missing system capabilities and stages structured MCP integration proposals."""

    def __init__(self, wiki_store: Any) -> None:
        self.wiki_store = wiki_store

    @staticmethod
    def identify_missing_domain(task: str, available_tools: list[str]) -> str | None:
        """Determine if a task targets an external domain missing from available tools."""
        lower_task = task.lower()
        tool_names = " ".join(available_tools).lower()

        domain_patterns = [
            (r"\bdocker\b|\bcontainer[s]?\b|\bcompose\b", "docker", "Docker Container Management"),
            (r"\bgit\b|\bcommit\b|\bbranch\b|\brepo\b", "git", "Git Version Control"),
            (r"\bpostgres\b|\bmysql\b|\bsql\b|\bdatabase\b", "database", "Database Operations"),
            (r"\bk8s\b|\bkubernetes\b|\bpod[s]?\b", "kubernetes", "Kubernetes Cluster Management"),
        ]

        for pattern, tool_keyword, domain_name in domain_patterns:
            if re.search(pattern, lower_task):
                if tool_keyword not in tool_names:
                    return domain_name

        return None

    def stage_mcp_proposal(self, task: str, domain: str) -> str:
        """Stage a capability proposal markdown note into 00_Inbox."""
        slug = domain.lower().replace(" ", "_").replace("/", "_")
        filename = f"proposal_{slug}_mcp.md"
        relative_path = f"{ProtectedFolder.INBOX.value}/{filename}"

        now = datetime.now(UTC).isoformat()
        content = f"""---
title: Capability Proposal - {domain} via Model Context Protocol (MCP)
category: Architecture Proposals
tags:
- capability-proposal
- mcp-integration
- {slug}
- sandboxing
created: {now}
updated: {now}
---
# Capability Proposal: {domain} via Model Context Protocol (MCP)

## 1. Context & Task Trigger
A user directive requested a task for which no built-in tool or recipe exists:
> *"{task}"*

## 2. Tool Architecture: MCP vs. CLI
When equipping Agent OS with capabilities for **{domain}**, two strategies were evaluated:

### Option A: Raw Host CLI Execution (e.g. CLI tools)
- **Security Risks**: Requires arbitrary shell execution, violating Core Tenet 3.
- **Policy Vulnerability**: Difficult to reliably parse and policy-gate raw bash strings.
- **Unstructured Outputs**: Returns terminal stdout with varying table widths and ANSI codes.

### Option B: Dedicated MCP Server Integration (Recommended)
- **Deterministic Sandboxing**: Structured, typed JSON-RPC tools with parameter validation.
- **Granular Policy Gating**:
  - *Read Operations* (e.g., list, inspect, logs): **Tier 1 (Autonomous)**
  - *Mutating Operations* (e.g., start, stop, delete): **Tier 2 (Strict / Human Approval)**
- **Reliable Local Inference**: Small local models inspect clean JSON schemas.

## 3. Recommended Actions
1. Configure a local MCP server for `{domain}` in `mcp_servers.json`.
2. Register the resulting tools into the Agent OS tool dispatcher under designated policy tiers.
3. Formulate and persist a catalog recipe for recurring `{domain}` directives.

---
*Staged automatically by Agent OS Capability Scout in accordance with the Sacred Rule of 00_Inbox.*
"""
        inbox_dir = self.wiki_store.root_dir / ProtectedFolder.INBOX.value
        inbox_dir.mkdir(parents=True, exist_ok=True)
        file_path = inbox_dir / filename
        file_path.write_text(content, encoding="utf-8")

        return relative_path
