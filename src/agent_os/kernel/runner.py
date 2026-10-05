"""Native multi-modal execution runner with cycle detection and policy gates."""

import json
import re
import time
from collections.abc import Callable, Coroutine
from typing import Any

from agent_os.domain.gateway import ChatMessage, CompletionRequest
from agent_os.domain.policy import ActionTier, PolicyDecisionType, ToolCallRequest
from agent_os.domain.runner import RunnerExecutionRequest, RunnerResult, RunnerStepEvent
from agent_os.domain.tools import ToolDefinition, ToolExecutionResult
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.kernel.policy_gate import ToolPolicyGate


class NativeRunner:
    """Pure Python execution engine for direct, ReAct, plan-execute-verify, and stategraph."""

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
        """Branch to modality handlers based on execution request."""
        if request.modality == "direct":
            return await self._execute_direct(request)
        if request.modality == "react":
            return await self._execute_react(request)
        if request.modality == "plan_execute_verify":
            return await self._execute_plan_execute_verify(request)
        if request.modality == "stategraph":
            return await self._execute_stategraph(request)
        raise ValueError(f"Unsupported execution modality: {request.modality}")

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

    def _parse_react_response(
        self, text: str
    ) -> tuple[str | None, str | None, dict[str, Any] | None]:
        """Parse model reasoning vs structured tool invocations.

        Returns (thought, tool_name, parameters) or (None, None, None) if final answer.
        """
        start_pos = 0
        while True:
            idx = text.find("{", start_pos)
            if idx == -1:
                break

            depth = 0
            in_string = False
            escape = False
            end_idx = -1
            for i in range(idx, len(text)):
                c = text[i]
                if escape:
                    escape = False
                    continue
                if c == "\\":
                    escape = True
                    continue
                if c == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            end_idx = i
                            break

            if end_idx != -1:
                json_str = text[idx : end_idx + 1]
                try:
                    data = json.loads(json_str)
                    if (
                        isinstance(data, dict)
                        and "action" in data
                        and isinstance(data["action"], str)
                        and len(data["action"].strip()) > 0
                    ):
                        tool_name = data["action"].strip()
                        raw_params = data.get("parameters", data.get("args", {}))
                        parameters = raw_params if isinstance(raw_params, dict) else {}

                        thought = data.get("thought")
                        if not thought or not str(thought).strip():
                            raw_pre = text[:idx]
                            cleaned_pre = re.sub(r"```(?:json)?\s*$", "", raw_pre).strip()
                            thought = cleaned_pre if cleaned_pre else f"Calling tool: {tool_name}"
                        return str(thought), tool_name, parameters
                except json.JSONDecodeError:
                    try:
                        sanitized = re.sub(r"\bTrue\b", "true", json_str)
                        sanitized = re.sub(r"\bFalse\b", "false", sanitized)
                        sanitized = re.sub(r"\bNone\b", "null", sanitized)
                        data = json.loads(sanitized)
                        if (
                            isinstance(data, dict)
                            and "action" in data
                            and isinstance(data["action"], str)
                            and len(data["action"].strip()) > 0
                        ):
                            tool_name = data["action"].strip()
                            raw_params = data.get("parameters", data.get("args", {}))
                            parameters = raw_params if isinstance(raw_params, dict) else {}

                            thought = data.get("thought")
                            if not thought or not str(thought).strip():
                                raw_pre = text[:idx]
                                cleaned_pre = re.sub(r"```(?:json)?\s*$", "", raw_pre).strip()
                                thought = cleaned_pre or f"Calling tool: {tool_name}"
                            return str(thought), tool_name, parameters
                    except json.JSONDecodeError:
                        pass
                start_pos = idx + 1
            else:
                break

        return None, None, None

    async def _execute_react(self, request: RunnerExecutionRequest) -> RunnerResult:
        """Execute bounded ReAct loop with cycle detection and policy gates."""
        steps: list[RunnerStepEvent] = []
        messages: list[ChatMessage] = []
        if request.system_prompt:
            messages.append(ChatMessage(role="system", content=request.system_prompt))
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

            # Final answer reached when no tool call is requested
            if tool_name is None:
                return RunnerResult(
                    success=True,
                    final_output=response_text,
                    steps=steps,
                    total_turns=turn_count,
                )

            # Record thought step
            thought_text = thought if thought else f"Calling tool: {tool_name}"
            steps.append(
                RunnerStepEvent(
                    step_index=len(steps),
                    modality="react",
                    step_type="thought",
                    content=thought_text,
                )
            )

            # Repeat-call cycle detector
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

            # Record tool call step
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

            # Policy check
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
                block_reason = decision.reason or "Action rejected by policy gate"
                steps.append(
                    RunnerStepEvent(
                        step_index=len(steps),
                        modality="react",
                        step_type="tool_result",
                        content=f"Policy gate blocked tool: {block_reason}",
                        tool_name=tool_name,
                        tool_output=f"BLOCKED: {block_reason}",
                    )
                )
                return RunnerResult(
                    success=False,
                    final_output="",
                    steps=steps,
                    total_turns=turn_count,
                    error=f"Policy gate blocked tool {tool_name}: {block_reason}",
                )

            # Tool dispatch
            if tool_name not in self.tool_dispatcher:
                err_msg = f"Tool '{tool_name}' not found in dispatcher"
                steps.append(
                    RunnerStepEvent(
                        step_index=len(steps),
                        modality="react",
                        step_type="tool_result",
                        content=err_msg,
                        tool_name=tool_name,
                        tool_output=err_msg,
                    )
                )
                return RunnerResult(
                    success=False,
                    final_output="",
                    steps=steps,
                    total_turns=turn_count,
                    error=err_msg,
                )

            start_time = time.monotonic()
            tool_fn = self.tool_dispatcher[tool_name]
            try:
                tool_res = await tool_fn(**params_dict)
            except Exception as e:
                tool_res = ToolExecutionResult(
                    tool_name=tool_name,
                    success=False,
                    output="",
                    error=str(e),
                )
            duration_ms = int((time.monotonic() - start_time) * 1000)

            tool_output_str = (
                tool_res.output if tool_res.success else (tool_res.error or "Tool execution failed")
            )
            steps.append(
                RunnerStepEvent(
                    step_index=len(steps),
                    modality="react",
                    step_type="tool_result",
                    content=tool_output_str,
                    tool_name=tool_name,
                    tool_output=tool_output_str,
                    duration_ms=duration_ms,
                )
            )

            # Feed observation back to conversation context
            messages.append(ChatMessage(role="assistant", content=response_text))
            messages.append(
                ChatMessage(
                    role="tool",
                    content=f"Observation from {tool_name}: {tool_output_str}",
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
        steps: list[RunnerStepEvent] = []

        # 1. Synthesize plan
        plan_prompt = f"Create a step-by-step plan for the following task:\n{request.task}"
        plan_messages = [ChatMessage(role="user", content=plan_prompt)]
        if request.system_prompt:
            plan_messages.insert(0, ChatMessage(role="system", content=request.system_prompt))

        plan_chunks: list[str] = []
        async for chunk in self.model_adapter.complete(CompletionRequest(messages=plan_messages)):
            if chunk.delta:
                plan_chunks.append(chunk.delta)
        plan_text = "".join(plan_chunks)
        steps.append(
            RunnerStepEvent(
                step_index=len(steps),
                modality="plan_execute_verify",
                step_type="plan",
                content=plan_text,
            )
        )

        # 2. Execute plan
        exec_prompt = f"Execute the plan for task:\nTask: {request.task}\nPlan: {plan_text}"
        exec_messages = [ChatMessage(role="user", content=exec_prompt)]
        if request.system_prompt:
            exec_messages.insert(0, ChatMessage(role="system", content=request.system_prompt))

        exec_chunks: list[str] = []
        async for chunk in self.model_adapter.complete(CompletionRequest(messages=exec_messages)):
            if chunk.delta:
                exec_chunks.append(chunk.delta)
        exec_text = "".join(exec_chunks)
        steps.append(
            RunnerStepEvent(
                step_index=len(steps),
                modality="plan_execute_verify",
                step_type="thought",
                content=exec_text,
            )
        )

        # 3. Verify output
        verify_prompt = (
            f"Verify the execution output against the task directive:\n"
            f"Task: {request.task}\n"
            f"Execution Output: {exec_text}\n"
            f"Provide the final verified response."
        )
        verify_messages = [ChatMessage(role="user", content=verify_prompt)]
        if request.system_prompt:
            verify_messages.insert(0, ChatMessage(role="system", content=request.system_prompt))

        verify_chunks: list[str] = []
        async for chunk in self.model_adapter.complete(CompletionRequest(messages=verify_messages)):
            if chunk.delta:
                verify_chunks.append(chunk.delta)
        verify_text = "".join(verify_chunks)
        steps.append(
            RunnerStepEvent(
                step_index=len(steps),
                modality="plan_execute_verify",
                step_type="verify",
                content=verify_text,
            )
        )

        return RunnerResult(
            success=True,
            final_output=verify_text,
            steps=steps,
            total_turns=3,
        )

    async def _execute_stategraph(self, request: RunnerExecutionRequest) -> RunnerResult:
        """Transition through defined execution graph nodes."""
        steps: list[RunnerStepEvent] = []
        nodes = ["entry", "process", "exit"]
        current_content = request.task

        for node in nodes:
            steps.append(
                RunnerStepEvent(
                    step_index=len(steps),
                    modality="stategraph",
                    step_type="node_transition",
                    content=f"Transitioned to node: {node}",
                )
            )
            if node == "exit":
                break

            node_prompt = f"Node [{node}]: Process the following context:\n{current_content}"
            node_messages = [ChatMessage(role="user", content=node_prompt)]
            if request.system_prompt:
                node_messages.insert(0, ChatMessage(role="system", content=request.system_prompt))

            node_chunks: list[str] = []
            async for chunk in self.model_adapter.complete(
                CompletionRequest(messages=node_messages)
            ):
                if chunk.delta:
                    node_chunks.append(chunk.delta)
            current_content = "".join(node_chunks)
            steps.append(
                RunnerStepEvent(
                    step_index=len(steps),
                    modality="stategraph",
                    step_type="thought",
                    content=current_content,
                )
            )

        return RunnerResult(
            success=True,
            final_output=current_content,
            steps=steps,
            total_turns=len(nodes),
        )
