"""5-Beat task brief assembly and execution packet compilation engine."""

from agent_os.domain.runbook import (
    CompiledExecutionPacket,
    RunbookDefinition,
    TaskBrief,
)


class TaskBriefAssembler:
    """Assembles structured 5-Beat prompts and compiles execution packets."""

    @classmethod
    def compile_packet(
        cls,
        brief: TaskBrief,
        runbook: RunbookDefinition | None = None,
    ) -> CompiledExecutionPacket:
        """Compile a TaskBrief and optional RunbookDefinition into an execution packet."""
        invariants_rendered = "\n".join(f"- {inv}" for inv in brief.scope_invariants)
        beats = [
            f"<role_anchor>{brief.role_anchor}</role_anchor>",
            f"<core_directive>{brief.core_directive}</core_directive>",
            f"<scope_invariants>\n{invariants_rendered}\n</scope_invariants>",
            f"<capability_strategy>{brief.capability_strategy}</capability_strategy>",
            f"<completion_standard>{brief.completion_standard}</completion_standard>",
        ]

        target_tools: list[str] = []
        if runbook is not None:
            steps_rendered = "\n".join(f"- {step}" for step in runbook.procedural_steps)
            criteria_rendered = "\n".join(f"- {crit}" for crit in runbook.verification_criteria)
            runbook_block = (
                f'<runbook name="{runbook.name}">\n'
                f"<what_it_does>{runbook.what_it_does}</what_it_does>\n"
                f"<procedural_steps>\n{steps_rendered}\n</procedural_steps>\n"
                f"<verification_criteria>\n{criteria_rendered}\n</verification_criteria>\n"
                f"</runbook>"
            )
            beats.append(runbook_block)
            target_tools.extend(runbook.required_tools)

        rendered_prompt = "\n\n".join(beats)

        # Context isolation invariant: zero human profile leakage
        if "<human_profile>" in rendered_prompt or "</human_profile>" in rendered_prompt:
            raise ValueError(
                "Context isolation violation: <human_profile> detected in task brief prompt"
            )

        token_estimate = len(rendered_prompt) // 4

        return CompiledExecutionPacket(
            system_prompt=rendered_prompt,
            target_tools=target_tools,
            token_estimate=token_estimate,
        )
