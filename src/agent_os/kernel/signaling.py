"""Dual-channel notification and deferred completion queue manager."""

import uuid

from agent_os.domain.ipc import SubJobReturnEnvelope
from agent_os.domain.signaling import AmbientNudge, DeferredCompletionBuffer


class CompletionSignaler:
    """Coordinates ambient UI nudges and deferred turn prompt injection."""

    def __init__(self) -> None:
        self._nudge_queue: list[AmbientNudge] = []
        self._deferred_buffers: dict[str, list[SubJobReturnEnvelope]] = {}

    def signal_completion(self, session_id: str, envelope: SubJobReturnEnvelope) -> AmbientNudge:
        """Signal completion across both ambient UI and deferred prompt channels."""
        # Channel 1: Ambient UI Event
        short_notice = (f"Sub-job {envelope.journey_id[:8]} finished: {envelope.status.upper()}")[
            :120
        ]
        nudge = AmbientNudge(
            nudge_id=str(uuid.uuid4()),
            journey_id=envelope.journey_id,
            status=envelope.status,
            short_notice=short_notice,
        )
        self._nudge_queue.append(nudge)

        # Channel 2: Deferred Turn Injection
        self._deferred_buffers.setdefault(session_id, []).append(envelope)

        return nudge

    def poll_ambient_nudges(self, limit: int = 10) -> list[AmbientNudge]:
        """Poll and pop up to `limit` ambient nudges from the queue in FIFO order."""
        if limit <= 0:
            return []
        popped = self._nudge_queue[:limit]
        self._nudge_queue = self._nudge_queue[limit:]
        return popped

    def drain_deferred_completions(self, session_id: str) -> list[SubJobReturnEnvelope]:
        """Pop and clear all deferred completion return envelopes for session_id."""
        return self._deferred_buffers.pop(session_id, [])

    def format_deferred_prompt_block(self, session_id: str) -> str:
        """Drain deferred envelopes and format as an XML block for prompt injection."""
        envelopes = self.drain_deferred_completions(session_id)
        if not envelopes:
            return ""

        lines = [
            f"- [Status: {env.status.upper()}] Journey {env.journey_id}: {env.summary}"
            for env in envelopes
        ]
        return "\n".join(["<background_completions>", *lines, "</background_completions>"])

    def get_deferred_buffer(self, session_id: str) -> DeferredCompletionBuffer:
        """Inspect pending return envelopes for session_id without draining."""
        return DeferredCompletionBuffer(
            session_id=session_id,
            pending_envelopes=list(self._deferred_buffers.get(session_id, [])),
        )
