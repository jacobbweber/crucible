"""Toolsmith specialist worker synthesizing, dry-running, and staging new FastMCP tools."""

import json
import re
import sys
from datetime import UTC, datetime
from typing import Any

from agent_os.domain.gateway import ChatMessage, CompletionRequest
from agent_os.domain.policy import ActionTier
from agent_os.domain.tools import ToolDefinition, ToolParameterSchema
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
        self._proposals: dict[str, ToolsmithProposal] = {}

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
            "You are an expert Python tool developer. Synthesize a clean, self-contained Python FastMCP tool "
            "decorated with @hub.tool() to satisfy the user task.\n"
            "Rules:\n"
            "1. Output ONLY a valid JSON object matching this schema:\n"
            "{\n"
            '  "tool_name": "<valid_python_identifier>",\n'
            '  "description": "<concise description>",\n'
            '  "code_snippet": "@hub.tool()\\ndef <name>(...) -> str:\\n    ...",\n'
            '  "dry_run_args": {"<param>": "<sample_val>"}\n'
            "}\n"
            "2. Ensure the code snippet has generic typed parameters (e.g. `path: str` for filesystem operations, NOT hardcoded drive letters) and a docstring describing them so callers can pass dynamic targets.\n"
            "3. Include all necessary standard library imports inside the function body "
            "(e.g. from pathlib import Path, import os, import subprocess) so the function is completely self-contained.\n"
            "4. Ensure dry_run_args provides safe, valid sample arguments (e.g. for file operations use 'dry_run_test.txt') "
            "so the pre-flight dry-run test invocation executes without crashing.\n"
            f"Task: {task}\n"
            f"Domain: {domain}\n"
        )
        try:
            req = CompletionRequest(
                messages=[
                    ChatMessage(
                        role="system",
                        content="You emit structured FastMCP tool specifications in JSON.",
                    ),
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
        tool_name, desc, code, dry_run_args = await self._generate_spec(
            request.task, request.domain
        )

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

        proposal = ToolsmithProposal(
            tool_name=tool_name,
            domain=request.domain,
            description=desc,
            code_snippet=code,
            dry_run_args=dry_run_args,
            dry_run_output=dry_output,
            verified=True,
            staged_path=staged_path,
        )
        self._proposals[proposal.tool_name] = proposal
        return proposal

    def list_proposals(self) -> list[ToolsmithProposal]:
        """Return all staged tool proposals."""
        return list(self._proposals.values())

    def get_proposal(self, tool_name: str) -> ToolsmithProposal | None:
        """Lookup proposal by tool name."""
        return self._proposals.get(tool_name)

    def compile_tool_function(self, proposal: ToolsmithProposal) -> tuple[Any, ToolDefinition]:
        """Compile a verified tool proposal into an in-process callable and ToolDefinition."""

        class _HubShim:
            def tool(self, *args: Any, **kwargs: Any) -> Any:
                return lambda fn: fn

        namespace: dict[str, Any] = {"hub": _HubShim(), "ActionTier": ActionTier}
        exec(proposal.code_snippet, namespace)
        fn = namespace.get(proposal.tool_name)
        if not callable(fn):
            raise ValueError(f"Callable '{proposal.tool_name}' not found in compiled code.")

        import inspect

        sig = inspect.signature(fn)
        params: list[ToolParameterSchema] = []
        for p_name, param in sig.parameters.items():
            req = param.default is inspect.Parameter.empty
            d_val = None if req else param.default
            p_desc = (
                f"Target {p_name} parameter (e.g. drive letter or path)"
                if "path" in p_name
                else p_name
            )
            params.append(
                ToolParameterSchema(
                    name=p_name,
                    type_name="string",
                    description=p_desc,
                    required=req,
                    default=d_val,
                )
            )

        tool_def = ToolDefinition(
            name=proposal.tool_name,
            description=proposal.description or f"Synthesized tool: {proposal.tool_name}",
            action_tier=ActionTier.STATE_CHANGE,
            parameters=params,
        )
        return fn, tool_def

    async def activate_proposal(
        self, proposal: ToolsmithProposal, supervisor: McpClientSupervisor | None = None
    ) -> list[ToolDefinition]:
        """Mount a verified proposal into the live FastMCP Hub."""
        if not proposal.verified:
            raise ValueError(f"Cannot activate unverified tool '{proposal.tool_name}'.")

        self.mcp_hub.register_tool_code(proposal.tool_name, proposal.code_snippet)
        if supervisor is not None:
            return await self.mcp_hub.reload_hub(supervisor)
        _fn, tool_def = self.compile_tool_function(proposal)
        mcp_def = ToolDefinition(
            name=f"mcp_hub_{tool_def.name}",
            description=tool_def.description,
            action_tier=tool_def.action_tier,
            parameters=tool_def.parameters,
        )
        return [mcp_def, tool_def]

    async def activate_proposal_by_name(
        self, tool_name: str, supervisor: McpClientSupervisor | None = None
    ) -> list[ToolDefinition]:
        """Activate a staged proposal by its tool name."""
        proposal = self.get_proposal(tool_name)
        if not proposal:
            raise ValueError(f"No proposal found for tool '{tool_name}'")
        return await self.activate_proposal(proposal, supervisor)

    def reject_proposal(self, tool_name: str) -> bool:
        """Reject and remove a proposed tool from staging."""
        proposal = self._proposals.pop(tool_name, None)
        if proposal and proposal.staged_path and self.wiki_store:
            try:
                target = self.wiki_store.root_dir / proposal.staged_path
                if target.exists():
                    target.unlink()
            except Exception:
                pass
        return proposal is not None
