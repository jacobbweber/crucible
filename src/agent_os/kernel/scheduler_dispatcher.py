"""Signaling dispatcher adapter for background routines scheduled by the kernel."""

from typing import Any

from agent_os.domain.dispatch import DispatchResult
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.kernel.dispatcher import ZeroCatalogDispatcher
from agent_os.kernel.signaling import CompletionSignaler


class SchedulerSignalingDispatcher:
    """Wraps ZeroCatalogDispatcher for background routines to signal completion."""

    def __init__(
        self,
        dispatcher: ZeroCatalogDispatcher,
        signaler: CompletionSignaler,
        session_repo: SessionRepository,
        tools: dict[str, Any] | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._signaler = signaler
        self._session_repo = session_repo
        self._tools = tools or {}

    async def dispatch_task(
        self,
        session_id: str,
        task: str,
        available_tools: list[str] | None = None,
    ) -> DispatchResult:
        self._session_repo.ensure_session(session_id, title=f"System Session: {session_id}")
        tools_list = available_tools if available_tools is not None else list(self._tools.keys())
        res = await self._dispatcher.dispatch_task(session_id, task, available_tools=tools_list)
        self._signaler.signal_completion(session_id, res.envelope)
        return res

    def __getattr__(self, name: str) -> Any:
        return getattr(self._dispatcher, name)
