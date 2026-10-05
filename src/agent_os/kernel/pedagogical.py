"""Pedagogical stage progression manager, rubrics, and transition evaluation."""

from agent_os.domain.education import PedagogicalStage

STAGE_PROGRESSION: list[PedagogicalStage] = [
    "stage_1_primer",
    "stage_2_mental_models",
    "stage_3_scenario_probes",
    "stage_4_code_analysis",
    "stage_5_troubleshooting",
    "stage_6_synthesis",
]

STAGE_RUBRICS: dict[PedagogicalStage, str] = {
    "stage_1_primer": (
        "Focus on fundamental definitions, core terminology, and high-level intuition. "
        "Evaluate whether the learner understands basic concepts and vocabulary without jargon."
    ),
    "stage_2_mental_models": (
        "Focus on architectural abstractions, structural analogies, and conceptual invariants. "
        "Evaluate whether the learner can explain subsystem relationships and design patterns."
    ),
    "stage_3_scenario_probes": (
        "Focus on edge conditions, distributed concurrency hazards, and partial failure modes. "
        "Evaluate whether the learner anticipates race conditions, timeouts, and boundary states."
    ),
    "stage_4_code_analysis": (
        "Focus on concrete implementation details and algorithmic complexity. "
        "Evaluate whether the learner can trace code execution paths and critique data structures."
    ),
    "stage_5_troubleshooting": (
        "Focus on live incident remediation, diagnostic root cause analysis, and log parsing. "
        "Evaluate whether the learner isolates failure symptoms and formulates corrective actions."
    ),
    "stage_6_synthesis": (
        "Focus on end-to-end system design, multi-dimensional trade-offs, and architecture. "
        "Evaluate whether the learner designs resilient, context-isolated, production systems."
    ),
}


class PedagogicalOrchestrator:
    """Orchestrates 6-stage pedagogical advancement, curriculum rubrics, and transitions."""

    @classmethod
    def get_stage_rubric(cls, stage: PedagogicalStage) -> str:
        """Retrieve evaluation rubric and questioning guidelines for a pedagogical stage."""
        return STAGE_RUBRICS.get(
            stage,
            "General technical assessment rubric evaluating concept clarity and correctness.",
        )

    @classmethod
    def evaluate_stage_transition(
        cls,
        current_stage: PedagogicalStage,
        consecutive_high_grades: int,
        mastery_score: float,
    ) -> tuple[PedagogicalStage, bool]:
        """Evaluate criteria to transition to the next pedagogical stage."""
        if consecutive_high_grades >= 3 and mastery_score >= 80.0:
            try:
                curr_idx = STAGE_PROGRESSION.index(current_stage)
            except ValueError:
                return current_stage, False

            if curr_idx < len(STAGE_PROGRESSION) - 1:
                return STAGE_PROGRESSION[curr_idx + 1], True
            return current_stage, False

        return current_stage, False
