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
from agent_os.kernel.recipe_triage import select_best_recipe_match



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

        if "wiki_search" in selected_tools and "wiki_read" in allowed_tools:
            if "wiki_read" not in selected_tools:
                selected_tools.append("wiki_read")
        if "wiki_read" in selected_tools and "wiki_search" in allowed_tools:
            if "wiki_search" not in selected_tools:
                selected_tools.append("wiki_search")
        if "warehouse_search" in selected_tools and "warehouse_read" in allowed_tools:
            if "warehouse_read" not in selected_tools:
                selected_tools.append("warehouse_read")
        if "warehouse_read" in selected_tools and "warehouse_search" in allowed_tools:
            if "warehouse_search" not in selected_tools:
                selected_tools.append("warehouse_search")

        return brief, selected_tools

    async def _execute_ephemeral_stage(
        self,
        session_id: str,
        task: str,
        available_tools: list[str] | None,
        timeout_seconds: int = 300,
        context_payload: str = "",
    ) -> DispatchResult:
        """Stage 2: Assemble ephemeral task brief using model adapter and execute sub-job."""
        tools_list = available_tools or []
        prompt_content = (
            "You are an expert task planner. Given a user task and available tools, emit a JSON "
            "object specifying the TaskBrief and selecting appropriate tools.\n"
            "Select all necessary tools to search, read, or inspect relevant resources.\n"
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
                timeout_seconds=timeout_seconds,
                context_payload=context_payload,
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
        timeout_seconds: int = 300,
        context_payload: str = "",
    ) -> DispatchResult:
        """Dispatch task via Stage 1 (catalog recipe) or Stage 2 (ephemeral assembly)."""
        matches = self.recipe_repo.match_intent(task, limit=5)
        best_match = select_best_recipe_match(task, matches, self.threshold)

        # Stage 1: Match Intent via SQLite FTS5 Index if tools are available
        if best_match is not None:
            recipe = best_match.recipe

            # Verify that required tools for the matched recipe are actually present
            allowed_tools = set(available_tools) if available_tools is not None else None
            missing_tools = [
                t
                for t in recipe.metadata.required_tools
                if allowed_tools is not None and t not in allowed_tools
            ]

            if not missing_tools:
                packet = CompiledExecutionPacket(
                    system_prompt=recipe.body,
                    target_tools=recipe.metadata.required_tools,
                    token_estimate=estimate_tokens(recipe.body),
                    modality=recipe.metadata.execution_engine,
                )
                envelope = await self.chamber.execute_sub_job(
                    SubJobExecutionRequest(
                        session_id=session_id,
                        task=task,
                        packet=packet,
                        timeout_seconds=recipe.metadata.timeout_seconds,
                        context_payload=context_payload,
                    )
                )
                return DispatchResult(
                    decision=DispatchDecision(
                        task=task,
                        stage="matched_recipe",
                        matched_recipe_id=recipe.metadata.recipe_id,
                        confidence_score=best_match.score,
                    ),
                    envelope=envelope,
                )

        # Stage 2: Dynamic Ephemeral Assembly (unmatched recipe or capability gap)
        return await self._execute_ephemeral_stage(
            session_id=session_id,
            task=task,
            available_tools=available_tools,
            timeout_seconds=timeout_seconds,
            context_payload=context_payload,
        )

