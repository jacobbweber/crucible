"""Domain models for agentic workspace, file operations, and sandboxed execution."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class FileEntry:
    """Metadata describing a file or directory within an agentic workspace."""

    relative_path: str
    is_dir: bool
    size_bytes: int = 0
    modified_at: str = ""


@dataclass(frozen=True)
class CommandExecutionResult:
    """Output packet from a sandboxed command execution."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Snapshot record for rollback protection before file mutations."""

    snapshot_id: str
    relative_path: str
    original_content: str | None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True)
class WorkspaceConfig:
    """Configuration parameters for workspace bounds and execution limits."""

    root_dir: Path
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_output_bytes: int = 1024 * 1024  # 1 MB
    default_timeout_seconds: int = 60
    allow_git: bool = True
