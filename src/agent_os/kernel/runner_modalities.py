"""Execution modalities for plan-execute-verify and stategraph runners."""

from agent_os.domain.gateway import ChatMessage, CompletionRequest
from agent_os.domain.runner import RunnerExecutionRequest, RunnerResult, RunnerStepEvent
from agent_os.infrastructure.gateway.base import BaseModelAdapter


async def execute_plan_execute_verify(
    request: RunnerExecutionRequest,
    model_adapter: BaseModelAdapter,
) -> RunnerResult:
    """Synthesize plan -> execute steps -> verify output against directive."""
    steps: list[RunnerStepEvent] = []

    # 1. Synthesize plan
    plan_prompt = f"Create a step-by-step plan for the following task:\n{request.task}"
    plan_messages = [ChatMessage(role="user", content=plan_prompt)]
    if request.system_prompt:
        plan_messages.insert(0, ChatMessage(role="system", content=request.system_prompt))

    plan_chunks: list[str] = []
    async for chunk in model_adapter.complete(CompletionRequest(messages=plan_messages)):
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
    async for chunk in model_adapter.complete(CompletionRequest(messages=exec_messages)):
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
    async for chunk in model_adapter.complete(CompletionRequest(messages=verify_messages)):
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


async def execute_stategraph(
    request: RunnerExecutionRequest,
    model_adapter: BaseModelAdapter,
) -> RunnerResult:
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
        async for chunk in model_adapter.complete(CompletionRequest(messages=node_messages)):
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
