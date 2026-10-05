"""Envelope compression and token budget ceiling engine for worker journey returns."""

from typing import Literal

from agent_os.domain.ipc import SubJobReturnEnvelope


class SubJobMarshaller:
    """Compresses raw worker outputs into strictly bounded SubJobReturnEnvelopes."""

    @staticmethod
    def compress_summary(text: str, max_chars: int = 800) -> str:
        """Clamp raw string down to max_chars, appending ellipsis within budget if truncated."""
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return text[:max_chars]
        return text[: max_chars - 3] + "..."

    @classmethod
    def marshal_envelope(
        cls,
        journey_id: str,
        status: Literal["completed", "failed", "aborted"],
        raw_output: str,
        artifact_paths: list[str] | None = None,
        state_mutations: list[str] | None = None,
        duration_ms: int = 0,
    ) -> SubJobReturnEnvelope:
        """Compress raw_output into summary and construct bounded return envelope."""
        summary = cls.compress_summary(raw_output, max_chars=800)
        token_estimate = len(summary) // 4
        return SubJobReturnEnvelope(
            journey_id=journey_id,
            status=status,
            summary=summary,
            artifact_paths=artifact_paths or [],
            state_mutations=state_mutations or [],
            token_estimate=token_estimate,
            duration_ms=duration_ms,
        )
