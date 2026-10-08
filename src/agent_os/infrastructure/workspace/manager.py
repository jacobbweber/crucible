"""Isolated workspace filesystem manager with sandboxing, snapshots, and git awareness."""

import os
from datetime import UTC, datetime
from pathlib import Path

from agent_os.domain.workspace import (
    FileEntry,
    WorkspaceConfig,
    WorkspaceSnapshot,
)


class WorkspaceManager:
    """Manages files within an isolated workspace directory with strict boundary checks."""

    IGNORED_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache", ".mypy_cache"}

    def __init__(self, config: WorkspaceConfig) -> None:
        self.config = config
        self.root_dir = config.root_dir.resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._snapshots: dict[str, WorkspaceSnapshot] = {}

    def resolve_safe_path(self, relative_path: str) -> Path:
        """Resolve path relative to root_dir, strictly preventing path traversal outside root."""
        clean_rel = relative_path.strip().lstrip("/\\")
        target = (self.root_dir / clean_rel).resolve()
        try:
            target.relative_to(self.root_dir)
        except ValueError as exc:
            raise PermissionError(
                f"Access denied: path '{relative_path}' traverses outside workspace root."
            ) from exc
        return target

    def list_tree(self, relative_path: str = ".", max_depth: int = 3) -> list[FileEntry]:
        """List files and directories up to max_depth, filtering standard noise directories."""
        base_dir = self.resolve_safe_path(relative_path)
        if not base_dir.exists() or not base_dir.is_dir():
            return []

        entries: list[FileEntry] = []
        base_depth = len(base_dir.parts)

        for root, dirs, files in os.walk(base_dir):
            current_path = Path(root)
            depth = len(current_path.parts) - base_depth
            if depth >= max_depth:
                dirs.clear()
                continue

            # In-place filter out ignored directories
            dirs[:] = [d for d in dirs if d not in self.IGNORED_DIRS]

            for d in dirs:
                dir_path = current_path / d
                rel = str(dir_path.relative_to(self.root_dir)).replace("\\", "/")
                entries.append(FileEntry(relative_path=rel, is_dir=True))

            for f in files:
                file_path = current_path / f
                rel = str(file_path.relative_to(self.root_dir)).replace("\\", "/")
                try:
                    stat = file_path.stat()
                    size = stat.st_size
                    mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
                except OSError:
                    size = 0
                    mtime = ""
                entries.append(
                    FileEntry(relative_path=rel, is_dir=False, size_bytes=size, modified_at=mtime)
                )

        return entries

    def read_file(
        self, relative_path: str, start_line: int = 1, line_count: int = 100
    ) -> tuple[str, int, int]:
        """Read lines from a file. Returns (content, total_lines, bytes_read)."""
        target = self.resolve_safe_path(relative_path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"File not found: {relative_path}")

        file_size = target.stat().st_size
        if file_size > self.config.max_file_size_bytes:
            raise ValueError(
                f"File {relative_path} ({file_size} bytes) exceeds limit "
                f"({self.config.max_file_size_bytes} bytes)"
            )

        content = target.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines(keepends=True)
        total_lines = len(lines)

        s_idx = max(0, start_line - 1)
        e_idx = min(total_lines, s_idx + line_count)
        selected_lines = "".join(lines[s_idx:e_idx])
        return selected_lines, total_lines, len(selected_lines.encode("utf-8"))

    def write_file(self, relative_path: str, content: str, overwrite: bool = False) -> str:
        """Write content to a file, taking a pre-write snapshot for rollback safety."""
        target = self.resolve_safe_path(relative_path)
        if target.exists() and not overwrite:
            raise FileExistsError(
                f"File '{relative_path}' already exists. Pass overwrite=True to replace."
            )

        original_content = (
            target.read_text(encoding="utf-8", errors="replace") if target.exists() else None
        )
        snap_id = f"snap_{len(self._snapshots) + 1}_{int(datetime.now(UTC).timestamp())}"
        self._snapshots[snap_id] = WorkspaceSnapshot(
            snapshot_id=snap_id,
            relative_path=relative_path,
            original_content=original_content,
        )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return snap_id

    def patch_file(
        self, relative_path: str, target_content: str, replacement_content: str
    ) -> tuple[str, int]:
        """Perform exact substring replacement in a file with pre-write snapshot."""
        target = self.resolve_safe_path(relative_path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"File not found: {relative_path}")

        current = target.read_text(encoding="utf-8", errors="replace")
        if target_content not in current:
            raise ValueError(
                f"Target content not found in '{relative_path}'. Check exact lines/whitespace."
            )

        occurrences = current.count(target_content)
        if occurrences > 1:
            raise ValueError(
                f"Target content matched {occurrences} times in '{relative_path}'. Must be unique."
            )

        snap_id = f"snap_{len(self._snapshots) + 1}_{int(datetime.now(UTC).timestamp())}"
        self._snapshots[snap_id] = WorkspaceSnapshot(
            snapshot_id=snap_id,
            relative_path=relative_path,
            original_content=current,
        )

        new_content = current.replace(target_content, replacement_content, 1)
        target.write_text(new_content, encoding="utf-8")
        return snap_id, occurrences

    def rollback_snapshot(self, snapshot_id: str) -> bool:
        """Rollback a file to its state before a write or patch mutation."""
        snapshot = self._snapshots.get(snapshot_id)
        if not snapshot:
            return False

        target = self.resolve_safe_path(snapshot.relative_path)
        if snapshot.original_content is None:
            if target.exists():
                target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(snapshot.original_content, encoding="utf-8")

        del self._snapshots[snapshot_id]
        return True
