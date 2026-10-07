"""Native multi-modal execution runner with cycle detection and policy gates."""

import asyncio
import json
import time
from collections.abc import Callable, Coroutine
from typing import Any

from agent_os.domain.gateway import ChatMessage, CompletionRequest
from agent_os.domain.policy import ActionTier, PolicyDecisionType, ToolCallRequest
from agent_os.domain.runner import RunnerExecutionRequest, RunnerResult, RunnerStepEvent
from agent_os.domain.tools import ToolDefinition, ToolExecutionResult
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.kernel.policy_gate import ToolPolicyGate
from agent_os.kernel.react_parser import format_tools_prompt, parse_react_response
from agent_os.kernel.runner_modalities import execute_plan_execute_verify, execute_stategraph


class NativeRunner:
    """Pure Python execution engine for direct, ReAct, plan-execute-verify, and stategraph."""

    _parse_react_response = staticmethod(parse_react_response)

    def __init__(
        self,
        model_adapter: BaseModelAdapter,
        policy_gate: ToolPolicyGate,
        tool_dispatcher: dict[str, Callable[..., Coroutine[Any, Any, ToolExecutionResult]]],
    ) -> None:
        self.model_adapter = model_adapter
        self.policy_gate = policy_gate
        self.tool_dispatcher = tool_dispatcher

    async def execute(self, request: RunnerExecutionRequest) -> RunnerResult:
        """Branch to modality handlers based on execution request with timeout (M6)."""
        try:
            async with asyncio.timeout(request.timeout_seconds):
                if request.modality == "direct":
                    return await self._execute_direct(request)
                if request.modality == "react":
                    return await self._execute_react(request)
                if request.modality == "plan_execute_verify":
                    return await self._execute_plan_execute_verify(request)
                if request.modality == "stategraph":
                    return await self._execute_stategraph(request)
                raise ValueError(f"Unsupported execution modality: {request.modality}")
        except TimeoutError:
            return RunnerResult(
                success=False,
                final_output="",
                steps=[],
                total_turns=0,
                error=f"Execution timed out after {request.timeout_seconds}s",
            )

    async def _execute_direct(self, request: RunnerExecutionRequest) -> RunnerResult:
        """Execute single direct completion request."""
        messages: list[ChatMessage] = []
        if request.system_prompt:
            messages.append(ChatMessage(role="system", content=request.system_prompt))
        messages.append(ChatMessage(role="user", content=request.task))

        chunks: list[str] = []
        async for chunk in self.model_adapter.complete(CompletionRequest(messages=messages)):
            if chunk.delta:
                chunks.append(chunk.delta)
        output = "".join(chunks)

        step = RunnerStepEvent(
            step_index=0,
            modality="direct",
            step_type="thought",
            content=output,
        )
        return RunnerResult(
            success=True,
            final_output=output,
            steps=[step],
            total_turns=1,
        )

    def _evaluate_policy(
        self,
        tool_name: str,
        params_dict: dict[str, Any],
        tool_def_map: dict[str, ToolDefinition],
    ) -> tuple[bool, str]:
        """Evaluate action tier and parameters against the policy gate."""
        tool_def = tool_def_map.get(tool_name)
        action_tier = tool_def.action_tier if tool_def else ActionTier.DESTRUCTIVE
        safe_params: dict[str, str | int | float | bool | None] = {}
        for k, v in params_dict.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                safe_params[k] = v
            else:
                safe_params[k] = str(v)

        call_request = ToolCallRequest(
            tool_name=tool_name,
            action_tier=action_tier,
            parameters=safe_params,
        )
        decision = self.policy_gate.evaluate(call_request)
        if decision.decision == PolicyDecisionType.BLOCK or decision.requires_prompt:
            return False, decision.reason or "Action rejected by policy gate"
        return True, ""

    async def _dispatch_tool(
        self,
        tool_name: str,
        params_dict: dict[str, Any],
    ) -> tuple[ToolExecutionResult, int]:
        """Invoke tool through the registered tool dispatcher with timing."""
        if tool_name not in self.tool_dispatcher:
            return (
                ToolExecutionResult(
                    tool_name=tool_name,
                    success=False,
                    output="",
                    error=f"Tool '{tool_name}' not found in dispatcher",
                ),
                0,
            )
        start_time = time.monotonic()
        try:
            res = await self.tool_dispatcher[tool_name](**params_dict)
        except Exception as e:
            res = ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                output="",
                error=str(e),
            )
        duration_ms = int((time.monotonic() - start_time) * 1000)
        return res, duration_ms

    async def _execute_react(self, request: RunnerExecutionRequest) -> RunnerResult:
        """Execute bounded ReAct loop with tool schemas, cycle detection, and policy gates."""
        steps: list[RunnerStepEvent] = []
        messages: list[ChatMessage] = []

        tools_block = format_tools_prompt(request.tools)
        system_content = request.system_prompt
        if tools_block:
            system_content = f"{system_content}\n\n{tools_block}" if system_content else tools_block
        if system_content:
            messages.append(ChatMessage(role="system", content=system_content))
        messages.append(ChatMessage(role="user", content=request.task))

        tool_def_map: dict[str, ToolDefinition] = {t.name: t for t in request.tools}
        call_history: list[tuple[str, str]] = []

        turn_count = 0
        while turn_count < request.max_turns:
            turn_count += 1
            chunks: list[str] = []
            async for chunk in self.model_adapter.complete(CompletionRequest(messages=messages)):
                if chunk.delta:
                    chunks.append(chunk.delta)
            response_text = "".join(chunks)

            thought, tool_name, parameters = self._parse_react_response(response_text)
            if tool_name is None:
                return RunnerResult(
                    success=True,
                    final_output=response_text,
                    steps=steps,
                    total_turns=turn_count,
                )

            thought_text = thought if thought else f"Calling tool: {tool_name}"
            steps.append(
                RunnerStepEvent(
                    step_index=len(steps),
                    modality="react",
                    step_type="thought",
                    content=thought_text,
                )
            )

            params_dict = parameters or {}
            params_key = json.dumps(params_dict, sort_keys=True)
            call_history.append((tool_name, params_key))
            if len(call_history) >= 3 and call_history[-1] == call_history[-2] == call_history[-3]:
                return RunnerResult(
                    success=False,
                    final_output="",
                    steps=steps,
                    total_turns=turn_count,
                    error="Cycle detected: tool called 3x with identical arguments",
                    aborted_by_cycle_detection=True,
                )

            steps.append(
                RunnerStepEvent(
                    step_index=len(steps),
                    modality="react",
                    step_type="tool_call",
                    content=f"Tool call: {tool_name}",
                    tool_name=tool_name,
                    tool_input=params_dict,
                )
            )

            allowed, reason = self._evaluate_policy(tool_name, params_dict, tool_def_map)
            if not allowed:
                block_msg = f"Policy gate blocked tool {tool_name}: {reason}"
                steps.append(
                    RunnerStepEvent(
                        step_index=len(steps),
                        modality="react",
                        step_type="tool_result",
                        content=block_msg,
                        tool_name=tool_name,
                        tool_output=f"BLOCKED: {reason}",
                    )
                )
                return RunnerResult(
                    success=False,
                    final_output="",
                    steps=steps,
                    total_turns=turn_count,
                    error=block_msg,
                )

            tool_res, duration_ms = await self._dispatch_tool(tool_name, params_dict)
            output_str = tool_res.output if tool_res.success else (tool_res.error or "Failed")
            steps.append(
                RunnerStepEvent(
                    step_index=len(steps),
                    modality="react",
                    step_type="tool_result",
                    content=output_str,
                    tool_name=tool_name,
                    tool_output=output_str,
                    duration_ms=duration_ms,
                )
            )
            if not tool_res.success and "not found in dispatcher" in (tool_res.error or ""):
                return RunnerResult(
                    success=False,
                    final_output="",
                    steps=steps,
                    total_turns=turn_count,
                    error=tool_res.error,
                )

            messages.append(ChatMessage(role="assistant", content=response_text))
            messages.append(
                ChatMessage(
                    role="tool",
                    content=f"Observation from {tool_name}: {output_str}",
                    name=tool_name,
                )
            )

        return RunnerResult(
            success=False,
            final_output="",
            steps=steps,
            total_turns=turn_count,
            error="Turn limit reached without final completion",
        )

    async def _execute_plan_execute_verify(self, request: RunnerExecutionRequest) -> RunnerResult:
        """Synthesize plan -> execute steps -> verify output against directive."""
        return await execute_plan_execute_verify(request, self.model_adapter)

    async def _execute_stategraph(self, request: RunnerExecutionRequest) -> RunnerResult:
        """Transition through defined execution graph nodes."""
        return await execute_stategraph(request, self.model_adapter)
