"""Workspace tool implementations, parameter schemas, and execution handlers."""

import inspect
import json
from typing import Any

from agent_os.domain.policy import ActionTier
from agent_os.domain.tools import (
    ToolDefinition,
    ToolExecutionResult,
    ToolParameterSchema,
)
from agent_os.infrastructure.workspace.command_runner import SandboxedCommandRunner
from agent_os.infrastructure.workspace.manager import WorkspaceManager


def _p(name: str, type_name: str, desc: str, req: bool = True, default: Any = None) -> ToolParameterSchema:
    return ToolParameterSchema(name=name, type_name=type_name, description=desc, required=req, default=default)


class WorkspaceToolSuite:
    """Tool suite providing agent access to workspace file operations and sandboxed execution."""

    def __init__(self, manager: WorkspaceManager, runner: SandboxedCommandRunner) -> None:
        self.manager = manager
        self.runner = runner

    def get_definitions(self) -> list[ToolDefinition]:
        """Return tool definitions and schemas for all workspace primitives."""
        return [
            ToolDefinition(
                name="workspace_tree",
                description="List files and directories in workspace up to max_depth.",
                action_tier=ActionTier.READ,
                parameters=[
                    _p("relative_path", "string", "Subdir to list relative to root.", False, "."),
                    _p("max_depth", "integer", "Max directory recursion depth.", False, 3),
                ],
            ),
            ToolDefinition(
                name="workspace_read",
                description="Read lines from a workspace file with pagination.",
                action_tier=ActionTier.READ,
                parameters=[
                    _p("relative_path", "string", "Relative path of file to read."),
                    _p("start_line", "integer", "Starting line number (1-indexed).", False, 1),
                    _p("line_count", "integer", "Number of lines to read.", False, 100),
                ],
            ),
            ToolDefinition(
                name="workspace_write",
                description="Create or overwrite a file in workspace with snapshotting.",
                action_tier=ActionTier.STATE_CHANGE,
                parameters=[
                    _p("relative_path", "string", "Relative target path."),
                    _p("content", "string", "File content to write."),
                    _p("overwrite", "boolean", "Overwrite existing file.", False, False),
                ],
            ),
            ToolDefinition(
                name="workspace_patch",
                description="Perform exact single-block replacement in a workspace file.",
                action_tier=ActionTier.STATE_CHANGE,
                parameters=[
                    _p("relative_path", "string", "Relative file path."),
                    _p("target_content", "string", "Exact text chunk to replace."),
                    _p("replacement_content", "string", "Replacement text content."),
                ],
            ),
            ToolDefinition(
                name="workspace_command",
                description="Execute a shell command within workspace with secret scrubbing.",
                action_tier=ActionTier.STATE_CHANGE,
                parameters=[
                    _p("command", "string", "Shell command line to execute."),
                    _p("relative_cwd", "string", "Working directory relative to root.", False, "."),
                    _p("timeout_seconds", "integer", "Max seconds before timeout.", False, 60),
                ],
            ),
            ToolDefinition(
                name="workspace_rollback",
                description="Rollback a file modification using a snapshot ID.",
                action_tier=ActionTier.STATE_CHANGE,
                parameters=[
                    _p("snapshot_id", "string", "Snapshot ID from write/patch."),
                ],
            ),
        ]

    def workspace_tree(self, relative_path: str = ".", max_depth: int = 3) -> ToolExecutionResult:
        """List files and directories in workspace up to max_depth."""
        try:
            entries = self.manager.list_tree(relative_path=relative_path, max_depth=max_depth)
            output = [
                {"path": e.relative_path, "is_dir": e.is_dir, "size_bytes": e.size_bytes, "modified_at": e.modified_at}
                for e in entries
            ]
            return ToolExecutionResult(tool_name="workspace_tree", success=True, output=json.dumps({"entries": output}))
        except Exception as exc:
            return ToolExecutionResult(tool_name="workspace_tree", success=False, output="", error=str(exc))

    def workspace_read(self, relative_path: str, start_line: int = 1, line_count: int = 100) -> ToolExecutionResult:
        """Read lines from a workspace file with pagination."""
        try:
            content, total, b_read = self.manager.read_file(relative_path, start_line=start_line, line_count=line_count)
            return ToolExecutionResult(
                tool_name="workspace_read",
                success=True,
                output=json.dumps({
                    "path": relative_path, "content": content, "start_line": start_line,
                    "line_count": len(content.splitlines()), "total_lines": total, "bytes_read": b_read,
                }),
            )
        except Exception as exc:
            return ToolExecutionResult(tool_name="workspace_read", success=False, output="", error=str(exc))

    def workspace_write(self, relative_path: str, content: str, overwrite: bool = False) -> ToolExecutionResult:
        """Write content to a workspace file with rollback snapshotting."""
        try:
            snap_id = self.manager.write_file(relative_path, content, overwrite=overwrite)
            return ToolExecutionResult(
                tool_name="workspace_write",
                success=True,
                output=json.dumps({"path": relative_path, "snapshot_id": snap_id, "bytes_written": len(content.encode("utf-8"))}),
            )
        except Exception as exc:
            return ToolExecutionResult(tool_name="workspace_write", success=False, output="", error=str(exc))

    def workspace_patch(self, relative_path: str, target_content: str, replacement_content: str) -> ToolExecutionResult:
        """Perform exact single-block replacement in a workspace file."""
        try:
            snap_id, matches = self.manager.patch_file(relative_path, target_content, replacement_content)
            return ToolExecutionResult(
                tool_name="workspace_patch",
                success=True,
                output=json.dumps({"path": relative_path, "snapshot_id": snap_id, "matches_replaced": matches}),
            )
        except Exception as exc:
            return ToolExecutionResult(tool_name="workspace_patch", success=False, output="", error=str(exc))

    async def workspace_command(self, command: str, relative_cwd: str = ".", timeout_seconds: int = 60) -> ToolExecutionResult:
        """Execute a shell command within the workspace with secret scrubbing."""
        try:
            res = await self.runner.run(command, relative_cwd=relative_cwd, timeout_seconds=timeout_seconds)
            return ToolExecutionResult(
                tool_name="workspace_command",
                success=res.exit_code == 0,
                output=json.dumps({
                    "command": command, "exit_code": res.exit_code, "stdout": res.stdout,
                    "stderr": res.stderr, "duration_ms": res.duration_ms, "timed_out": res.timed_out,
                }),
                error=res.stderr if res.exit_code != 0 else None,
            )
        except Exception as exc:
            return ToolExecutionResult(tool_name="workspace_command", success=False, output="", error=str(exc))

    def workspace_rollback(self, snapshot_id: str) -> ToolExecutionResult:
        """Rollback a file modification using a snapshot ID."""
        try:
            success = self.manager.rollback_snapshot(snapshot_id)
            return ToolExecutionResult(
                tool_name="workspace_rollback",
                success=success,
                output=json.dumps({"snapshot_id": snapshot_id, "rolled_back": success}),
            )
        except Exception as exc:
            return ToolExecutionResult(tool_name="workspace_rollback", success=False, output="", error=str(exc))

    async def execute(self, tool_name: str, params: dict[str, Any]) -> ToolExecutionResult:
        """Route and execute a workspace tool call."""
        fn = getattr(self, tool_name, None)
        if not fn:
            return ToolExecutionResult(tool_name=tool_name, success=False, output="", error=f"Unknown tool: {tool_name}")
        res = fn(**params)
        return await res if inspect.iscoroutine(res) else res
