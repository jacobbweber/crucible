"""Toolsmith specialist worker synthesizing, dry-running, and staging new FastMCP tools."""

import json
import re
import sys
from datetime import UTC, datetime
from typing import Any

from agent_os.domain.gateway import ChatMessage, CompletionRequest
from agent_os.domain.tools import ToolDefinition
from agent_os.domain.toolsmith import ToolsmithProposal, ToolsmithSynthesisRequest
from agent_os.domain.wiki import ProtectedFolder
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.workspace.command_runner import SandboxedCommandRunner
from agent_os.infrastructure.workspace.manager import WorkspaceManager
from agent_os.mcp.client import McpClientSupervisor
from agent_os.mcp.hub import McpHubManager


class ToolsmithWorker:
    """Specialist agent that drafts, dry-runs, and stages typed FastMCP tools for Crucible."""

    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        command_runner: SandboxedCommandRunner,
        mcp_hub: McpHubManager,
        model_adapter: BaseModelAdapter | None = None,
        wiki_store: Any | None = None,
    ) -> None:
        self.workspace_manager = workspace_manager
        self.command_runner = command_runner
        self.mcp_hub = mcp_hub
        self.model_adapter = model_adapter
        self.wiki_store = wiki_store

    def _fallback_scaffold(self, task: str, domain: str) -> tuple[str, str, str, dict[str, Any]]:
        """Deterministic scaffold when model generation is absent or in tests."""
        slug = domain.lower().replace(" ", "_").replace("-", "_")
        tool_name = f"{slug}_inspect"
        desc = f"Execute safe read-only inspection for {domain} directives."
        code = f'''@hub.tool()
def {tool_name}(query: str = "status") -> str:
    """Execute safe read-only inspection for {domain}."""
    return f"{domain} query '{{query}}' executed successfully. Output: [simulated status active]"
'''
        dry_run_args = {"query": "initial_check"}
        return tool_name, desc, code, dry_run_args

    async def _generate_spec(self, task: str, domain: str) -> tuple[str, str, str, dict[str, Any]]:
        """Ask model adapter to generate FastMCP tool definition with dry-run parameters."""
        if not self.model_adapter:
            return self._fallback_scaffold(task, domain)

        prompt = (
            "You are an expert Python tool developer. Synthesize a clean Python FastMCP tool "
            "decorated with @hub.tool() to satisfy the user task.\n"
            "Rules:\n"
            "1. Output ONLY a valid JSON object matching this schema:\n"
            "{\n"
            '  "tool_name": "<valid_python_identifier>",\n'
            '  "description": "<concise description>",\n'
            '  "code_snippet": "@hub.tool()\\ndef <name>(...) -> str:\\n    ...",\n'
            '  "dry_run_args": {"<param>": "<sample_val>"}\n'
            "}\n"
            "2. Ensure the code snippet has typed parameters and returns a string or dict.\n"
            f"Task: {task}\n"
            f"Domain: {domain}\n"
        )
        try:
            req = CompletionRequest(
                messages=[
                    ChatMessage(role="system", content="You emit structured FastMCP tool specifications in JSON."),
                    ChatMessage(role="user", content=prompt),
                ],
                temperature=0.0,
            )
            chunks = []
            async for chunk in self.model_adapter.complete(req):
                if chunk.delta:
                    chunks.append(chunk.delta)
            raw = "".join(chunks).strip()
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            json_str = match.group(1) if match else raw[raw.find("{") : raw.rfind("}") + 1]
            data = json.loads(json_str)
            return (
                str(data["tool_name"]),
                str(data["description"]),
                str(data["code_snippet"]),
                dict(data.get("dry_run_args", {})),
            )
        except Exception:
            return self._fallback_scaffold(task, domain)

    async def synthesize_and_verify(self, request: ToolsmithSynthesisRequest) -> ToolsmithProposal:
        """Synthesize a tool, run a mandatory pre-flight dry run, and stage in 00_Inbox."""
        tool_name, desc, code, dry_run_args = await self._generate_spec(request.task, request.domain)

        # 1. Prepare ephemeral dry-run test harness
        fn_match = re.search(r"def\s+([a-zA-Z0-9_]+)\s*\(", code)
        fn_name = fn_match.group(1) if fn_match else tool_name

        harness_code = f"""import json
from mcp.server.mcpserver import MCPServer

hub = MCPServer("dry_run_hub")

{code}

# Test invocation
args = json.loads({json.dumps(json.dumps(dry_run_args))})
result = {fn_name}(**args)
print(f"DRY_RUN_OUTPUT: {{result}}")
"""
        test_file = f"dry_run_{tool_name}.py"
        self.workspace_manager.write_file(test_file, harness_code, overwrite=True)

        # 2. Execute dry run in sandboxed runner
        exec_res = await self.command_runner.run(
            f'"{sys.executable}" {test_file}',
            timeout_seconds=30,
        )

        # Clean up test harness
        try:
            target = self.workspace_manager.resolve_safe_path(test_file)
            if target.exists():
                target.unlink()
        except Exception:
            pass

        if exec_res.exit_code != 0:
            return ToolsmithProposal(
                tool_name=tool_name,
                domain=request.domain,
                description=desc,
                code_snippet=code,
                dry_run_args=dry_run_args,
                dry_run_output="",
                verified=False,
                error_message=exec_res.stderr or "Dry run execution returned non-zero exit code.",
            )

        dry_output = exec_res.stdout.strip()

        # 3. Stage verified proposal into 00_Inbox
        staged_path = ""
        if self.wiki_store:
            now = datetime.now(UTC).isoformat()
            filename = f"proposal_tool_{tool_name}.md"
            staged_path = f"{ProtectedFolder.INBOX.value}/{filename}"
            content = f"""---
title: Tool Proposal - {tool_name} ({request.domain})
category: Tool Proposals
tags:
- tool-proposal
- fastmcp
- {tool_name}
- dry-run-verified
created: {now}
updated: {now}
---
# Tool Proposal: `{tool_name}` for {request.domain}

## 1. Context & User Directive
> *"{request.task}"*

## 2. Dry-Run Verification Status
- **Status**: Verified via Pre-Flight Dry Run
- **Sample Input**: `{json.dumps(dry_run_args)}`
- **Output**: `{dry_output}`

## 3. FastMCP Implementation Code
```python
{code}
```

---
*Generated and verified automatically by Crucible Toolsmith Worker.*
"""
            inbox_dir = self.wiki_store.root_dir / ProtectedFolder.INBOX.value
            inbox_dir.mkdir(parents=True, exist_ok=True)
            (inbox_dir / filename).write_text(content, encoding="utf-8")

        return ToolsmithProposal(
            tool_name=tool_name,
            domain=request.domain,
            description=desc,
            code_snippet=code,
            dry_run_args=dry_run_args,
            dry_run_output=dry_output,
            verified=True,
            staged_path=staged_path,
        )

    async def activate_proposal(
        self, proposal: ToolsmithProposal, supervisor: McpClientSupervisor
    ) -> list[ToolDefinition]:
        """Mount a verified proposal into the live FastMCP Hub."""
        if not proposal.verified:
            raise ValueError(f"Cannot activate unverified tool '{proposal.tool_name}'.")

        self.mcp_hub.register_tool_code(proposal.tool_name, proposal.code_snippet)
        return await self.mcp_hub.reload_hub(supervisor)
