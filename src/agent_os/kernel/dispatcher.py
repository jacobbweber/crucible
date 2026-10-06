"""Two-stage zero-catalog intent matching and dynamic ephemeral assembler dispatch."""

import json
import re
from typing import Any

from agent_os.domain.dispatch import DispatchDecision, DispatchResult
from agent_os.domain.gateway import ChatMessage, CompletionRequest, estimate_tokens
from agent_os.domain.ipc import SubJobExecutionRequest
from agent_os.domain.runbook import CompiledExecutionPacket, TaskBrief
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.kernel.brief_assembler import TaskBriefAssembler
from agent_os.kernel.recipe_chamber import RecipeChamber


class ZeroCatalogDispatcher:
    """Coordinates two-stage zero-catalog dispatch via indexed recipes or ephemeral workers."""

    def __init__(
        self,
        recipe_repo: RecipeRepository,
        recipe_chamber: RecipeChamber,
        model_adapter: BaseModelAdapter,
        match_threshold: float = 0.5,
    ) -> None:
        self.recipe_repo = recipe_repo
        self.recipe_chamber = recipe_chamber
        self.chamber = recipe_chamber
        self.model_adapter = model_adapter
        self.match_threshold = match_threshold
        self.threshold = match_threshold

    @staticmethod
    def _parse_model_brief(
        raw_response: str,
        available_tools: list[str],
    ) -> tuple[TaskBrief, list[str]]:
        """Parse raw model output into a valid TaskBrief and filtered ephemeral tools."""
        text = raw_response.strip()
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                json_str = text[start : end + 1]
            else:
                json_str = text

        try:
            data: dict[str, Any] = json.loads(json_str)
        except Exception:
            data = {}

        role_anchor = str(data.get("role_anchor") or "Ephemeral Worker")
        core_directive = str(data.get("core_directive") or "Execute requested task")
        raw_invariants = data.get("scope_invariants")
        if isinstance(raw_invariants, list) and raw_invariants:
            scope_invariants = [str(x) for x in raw_invariants if str(x).strip()]
        else:
            scope_invariants = ["Maintain context isolation and task invariants"]
        if not scope_invariants:
            scope_invariants = ["Maintain context isolation and task invariants"]

        capability_strategy = str(data.get("capability_strategy") or "Execute directly and verify")
        completion_standard = str(data.get("completion_standard") or "Task completed successfully")

        brief = TaskBrief(
            role_anchor=role_anchor,
            core_directive=core_directive,
            scope_invariants=scope_invariants,
            capability_strategy=capability_strategy,
            completion_standard=completion_standard,
        )

        allowed_tools = set(available_tools)
        raw_tools = data.get("selected_tools")
        selected_tools: list[str] = []
        if isinstance(raw_tools, list):
            for tool_name in raw_tools:
                name_str = str(tool_name)
                if name_str in allowed_tools and name_str not in selected_tools:
                    selected_tools.append(name_str)

        return brief, selected_tools

    async def _execute_ephemeral_stage(
        self,
        session_id: str,
        task: str,
        available_tools: list[str] | None,
    ) -> DispatchResult:
        """Stage 2: Assemble ephemeral task brief using model adapter and execute sub-job."""
        tools_list = available_tools or []
        prompt_content = (
            "You are an expert task planner. Given a user task and available tools, emit a JSON "
            "object specifying the TaskBrief and selecting appropriate tools.\n"
            "JSON Schema:\n"
            "{\n"
            '  "role_anchor": "<string>",\n'
            '  "core_directive": "<string>",\n'
            '  "scope_invariants": ["<string>", ...],\n'
            '  "capability_strategy": "<string>",\n'
            '  "completion_standard": "<string>",\n'
            '  "selected_tools": ["<tool_name>", ...]\n'
            "}\n\n"
            f"Task: {task}\n"
            f"Available Tools: {json.dumps(tools_list)}\n"
            "Output only the JSON object."
        )

        request = CompletionRequest(
            messages=[
                ChatMessage(
                    role="system",
                    content="You emit structured TaskBrief JSON specifications.",
                ),
                ChatMessage(role="user", content=prompt_content),
            ],
            temperature=0.0,
        )

        chunks: list[str] = []
        async for chunk in self.model_adapter.complete(request):
            if chunk.delta:
                chunks.append(chunk.delta)
        raw_response = "".join(chunks)

        brief, selected_tools = self._parse_model_brief(raw_response, tools_list)
        packet = TaskBriefAssembler.compile_packet(brief)
        for t in selected_tools:
            if t not in packet.target_tools:
                packet.target_tools.append(t)

        envelope = await self.chamber.execute_sub_job(
            SubJobExecutionRequest(
                session_id=session_id,
                task=task,
                packet=packet,
            )
        )

        return DispatchResult(
            decision=DispatchDecision(
                task=task,
                stage="assembled_ephemeral",
                ephemeral_tools=packet.target_tools,
            ),
            envelope=envelope,
        )

    async def dispatch_task(
        self,
        session_id: str,
        task: str,
        available_tools: list[str] | None = None,
    ) -> DispatchResult:
        """Dispatch task via Stage 1 (catalog recipe) or Stage 2 (ephemeral assembly)."""
        matches = self.recipe_repo.match_intent(task, limit=1)

        # Stage 1: Match Intent via SQLite FTS5 Index
        if matches and matches[0].score >= self.threshold:
            top_match = matches[0]
            recipe = top_match.recipe
            packet = CompiledExecutionPacket(
                system_prompt=recipe.body,
                target_tools=recipe.metadata.required_tools,
                token_estimate=estimate_tokens(recipe.body),
            )
            envelope = await self.chamber.execute_sub_job(
                SubJobExecutionRequest(
                    session_id=session_id,
                    task=task,
                    packet=packet,
                    timeout_seconds=recipe.metadata.timeout_seconds,
                )
            )
            return DispatchResult(
                decision=DispatchDecision(
                    task=task,
                    stage="matched_recipe",
                    matched_recipe_id=recipe.metadata.recipe_id,
                    confidence_score=top_match.score,
                ),
                envelope=envelope,
            )

        # Stage 2: Dynamic Ephemeral Assembly
        return await self._execute_ephemeral_stage(
            session_id=session_id,
            task=task,
            available_tools=available_tools,
        )
