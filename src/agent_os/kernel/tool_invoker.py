"""Tool invoker factory wrapping parameter resolution, execution, and secret scrubbing."""

import inspect
from collections.abc import Callable, Coroutine
from typing import Any

from agent_os.domain.tools import ToolExecutionResult
from agent_os.kernel.credential_proxy import CredentialProxyGate


def make_tool_invoker(
    tool_name: str,
    fn: Callable[..., Any],
    credential_proxy: CredentialProxyGate,
) -> Callable[..., Coroutine[Any, Any, ToolExecutionResult]]:
    """Create an async invoker wrapping parameter unmasking, execution, and output scrubbing."""

    async def _invoker(**kwargs: Any) -> ToolExecutionResult:
        resolved = credential_proxy.resolve_parameters(kwargs)
        params = dict(resolved.resolved_params)
        try:
            sig = inspect.signature(fn)
            if "path" in params and "path" not in sig.parameters:
                for alt in ("drive_path", "target_path", "dir_path", "folder_path", "directory"):
                    if alt in sig.parameters:
                        params[alt] = params.pop("path")
                        break
            elif "drive_path" in params and "drive_path" not in sig.parameters:
                for alt in ("path", "target_path", "dir_path", "folder_path", "directory"):
                    if alt in sig.parameters:
                        params[alt] = params.pop("drive_path")
                        break
            res = fn(**params)
            tool_res = await res if inspect.iscoroutine(res) else res
            if not isinstance(tool_res, ToolExecutionResult):
                tool_res = ToolExecutionResult(tool_name=tool_name, success=True, output=str(tool_res))
        except Exception as e:
            tool_res = ToolExecutionResult(tool_name=tool_name, success=False, output="", error=str(e))

        output, error = tool_res.output, tool_res.error
        if resolved.secrets_to_scrub:
            s = resolved.secrets_to_scrub
            if output:
                output = credential_proxy.scrub_text(output, s).sanitized_text
            if error:
                error = credential_proxy.scrub_text(error, s).sanitized_text

        return ToolExecutionResult(
            tool_name=tool_name, success=tool_res.success, output=output, error=error
        )

    return _invoker
