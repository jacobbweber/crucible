"""Dual-channel notification and deferred completion queue manager."""

import uuid

from agent_os.domain.ipc import SubJobReturnEnvelope
from agent_os.domain.signaling import AmbientNudge, DeferredCompletionBuffer


class CompletionSignaler:
    """Coordinates ambient UI nudges and deferred turn prompt injection."""

    def __init__(self) -> None:
        self._nudge_queue: list[AmbientNudge] = []
        self._deferred_buffers: dict[str, list[SubJobReturnEnvelope]] = {}
        self._discovery_notices: list[str] = []

    def signal_completion(self, session_id: str, envelope: SubJobReturnEnvelope) -> AmbientNudge:
        """Signal completion across both ambient UI and deferred prompt channels."""
        # Channel 1: Ambient UI Event
        short_notice = (f"Sub-job {envelope.journey_id[:8]} finished: {envelope.status.upper()}")[
            :120
        ]
        nudge = AmbientNudge(
            nudge_id=str(uuid.uuid4()),
            session_id=session_id,
            journey_id=envelope.journey_id,
            status=envelope.status,
            short_notice=short_notice,
        )
        self._nudge_queue.append(nudge)

        # Channel 2: Deferred Turn Injection
        self._deferred_buffers.setdefault(session_id, []).append(envelope)

        return nudge

    def signal_discovery(
        self,
        session_id: str,
        message: str,
        pattern_id: str = "pattern_scout",
    ) -> AmbientNudge:
        """Signal a discovered pattern or capability candidate for ambient notification."""
        nudge = AmbientNudge(
            nudge_id=str(uuid.uuid4()),
            session_id=session_id,
            journey_id=pattern_id,
            status="discovery",
            short_notice=message[:120],
        )
        self._nudge_queue.append(nudge)
        self._discovery_notices.append(f"- [Discovery Notice] {message}")
        return nudge

    def poll_ambient_nudges(
        self, session_id: str | None = None, limit: int = 10
    ) -> list[AmbientNudge]:
        """Poll and pop up to `limit` ambient nudges in FIFO order.

        If `session_id` is provided, only pops nudges addressed to that session
        or system broadcasts (session_id in ("", "system_scheduler")), preserving
        other sessions' queued nudges (H5).
        """
        if limit <= 0:
            return []

        if session_id is None:
            popped = self._nudge_queue[:limit]
            self._nudge_queue = self._nudge_queue[limit:]
            return popped

        matched: list[AmbientNudge] = []
        remaining: list[AmbientNudge] = []
        for nudge in self._nudge_queue:
            if len(matched) < limit and (
                nudge.session_id == session_id or nudge.session_id in ("", "system_scheduler")
            ):
                matched.append(nudge)
            else:
                remaining.append(nudge)
        self._nudge_queue = remaining
        return matched

    def drain_deferred_completions(self, session_id: str) -> list[SubJobReturnEnvelope]:
        """Pop and clear all deferred completion return envelopes for session_id."""
        envelopes = self._deferred_buffers.pop(session_id, [])
        if session_id != "system_scheduler":
            system_envelopes = self._deferred_buffers.pop("system_scheduler", [])
            envelopes.extend(system_envelopes)
        return envelopes

    def format_deferred_prompt_block(self, session_id: str) -> str:
        """Drain deferred envelopes and discovery notices as an XML block for prompt injection."""
        envelopes = self.drain_deferred_completions(session_id)
        notices = list(self._discovery_notices)
        self._discovery_notices.clear()

        if not envelopes and not notices:
            return ""

        lines = [
            f"- [Status: {env.status.upper()}] Journey {env.journey_id}: {env.summary}"
            for env in envelopes
        ]
        lines.extend(notices)
        return "\n".join(["<background_completions>", *lines, "</background_completions>"])

    def get_deferred_buffer(self, session_id: str) -> DeferredCompletionBuffer:
        """Inspect pending return envelopes for session_id without draining."""
        return DeferredCompletionBuffer(
            session_id=session_id,
            pending_envelopes=list(self._deferred_buffers.get(session_id, [])),
        )
