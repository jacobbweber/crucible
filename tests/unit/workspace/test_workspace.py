"""Unit tests for workspace management, sandboxed execution, and tool primitives."""

import os
import pytest
from pathlib import Path

from agent_os.domain.workspace import WorkspaceConfig
from agent_os.infrastructure.workspace.command_runner import SandboxedCommandRunner
from agent_os.infrastructure.workspace.manager import WorkspaceManager
from agent_os.kernel.workspace_tools import WorkspaceToolSuite


@pytest.fixture
def workspace_setup(tmp_path: Path):
    """Fixture providing an isolated WorkspaceManager, CommandRunner, and WorkspaceToolSuite."""
    cfg = WorkspaceConfig(root_dir=tmp_path / "test_workspace")
    manager = WorkspaceManager(cfg)
    runner = SandboxedCommandRunner(cfg)
    suite = WorkspaceToolSuite(manager, runner)
    return manager, runner, suite, cfg.root_dir


def test_path_traversal_prevention(workspace_setup):
    """Attempting to resolve paths outside workspace root must raise PermissionError."""
    manager, _, _, _ = workspace_setup
    with pytest.raises(PermissionError):
        manager.resolve_safe_path("../../outside.txt")


def test_write_read_patch_rollback(workspace_setup):
    """Verify write, read, patch, and rollback lifecycle."""
    manager, _, _, _ = workspace_setup

    # 1. Write file
    snap1 = manager.write_file("scripts/hello.py", "print('hello')\n")
    assert snap1.startswith("snap_")

    # 2. Read file
    content, total_lines, bytes_read = manager.read_file("scripts/hello.py")
    assert content == "print('hello')\n"
    assert total_lines == 1

    # 3. Patch file
    snap2, count = manager.patch_file("scripts/hello.py", "'hello'", "'world'")
    assert count == 1
    content, _, _ = manager.read_file("scripts/hello.py")
    assert content == "print('world')\n"

    # 4. Rollback patch
    assert manager.rollback_snapshot(snap2) is True
    content, _, _ = manager.read_file("scripts/hello.py")
    assert content == "print('hello')\n"

    # 5. Rollback initial write (deletes file)
    assert manager.rollback_snapshot(snap1) is True
    target = manager.resolve_safe_path("scripts/hello.py")
    assert not target.exists()


def test_list_tree_filters_ignored_dirs(workspace_setup):
    """Ignored directories like .git and __pycache__ must be excluded from listing."""
    manager, _, _, root_dir = workspace_setup
    (root_dir / ".git").mkdir(parents=True)
    (root_dir / ".git" / "config").write_text("dummy")
    (root_dir / "src").mkdir(parents=True)
    (root_dir / "src" / "main.py").write_text("print(1)")

    entries = manager.list_tree()
    paths = [e.relative_path for e in entries]
    assert "src" in paths
    assert "src/main.py" in paths
    assert not any(".git" in p for p in paths)


@pytest.mark.asyncio
async def test_secret_scrubbing(workspace_setup, monkeypatch):
    """Subprocess runner must strip sensitive tokens and API keys from environment."""
    _, runner, _, _ = workspace_setup
    monkeypatch.setenv("CRUCIBLE_API_KEY", "super-secret-token")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "sensitive-secret")
    monkeypatch.setenv("MY_PASSWORD", "p@ssword")

    clean_env = runner.build_clean_environment()
    assert "CRUCIBLE_API_KEY" not in clean_env
    assert "AWS_SECRET_ACCESS_KEY" not in clean_env
    assert "MY_PASSWORD" not in clean_env
    assert clean_env.get("PYTHONUNBUFFERED") == "1"


def test_dangerous_command_filter(workspace_setup):
    """Dangerous command patterns must be rejected unconditionally."""
    _, runner, _, _ = workspace_setup
    with pytest.raises(PermissionError):
        runner.validate_command_safety("rm -rf /")

    with pytest.raises(PermissionError):
        runner.validate_command_safety("mkfs.ext4 /dev/sda1")


@pytest.mark.asyncio
async def test_sandboxed_command_execution(workspace_setup):
    """Run a safe command and verify stdout, exit_code, and duration."""
    _, runner, _, root_dir = workspace_setup
    res = await runner.run("python -c \"print('Crucible Workspace Live!')\"")
    assert res.exit_code == 0
    assert "Crucible Workspace Live!" in res.stdout
    assert res.duration_ms > 0
    assert res.timed_out is False


@pytest.mark.asyncio
async def test_workspace_tool_suite_execution(workspace_setup):
    """Verify tool suite endpoints via execute()."""
    import json

    _, _, suite, _ = workspace_setup

    # Test workspace_write
    w_res = await suite.execute(
        "workspace_write",
        {"relative_path": "test.txt", "content": "hello from suite", "overwrite": True},
    )
    assert w_res.success is True
    w_out = json.loads(w_res.output)
    snap_id = w_out["snapshot_id"]

    # Test workspace_read
    r_res = await suite.execute("workspace_read", {"relative_path": "test.txt"})
    assert r_res.success is True
    r_out = json.loads(r_res.output)
    assert r_out["content"] == "hello from suite"

    # Test workspace_tree
    t_res = await suite.execute("workspace_tree", {"relative_path": "."})
    assert t_res.success is True
    t_out = json.loads(t_res.output)
    assert any(e["path"] == "test.txt" for e in t_out["entries"])

    # Test workspace_rollback
    rb_res = await suite.execute("workspace_rollback", {"snapshot_id": snap_id})
    assert rb_res.success is True
    rb_out = json.loads(rb_res.output)
    assert rb_out["rolled_back"] is True

