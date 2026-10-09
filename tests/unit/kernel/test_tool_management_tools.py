"""Unit tests for ToolManagementSuite and McpHubManager AST lifecycle operations."""

from pathlib import Path

import pytest

from agent_os.kernel.tool_management_tools import ToolManagementSuite
from agent_os.mcp.hub import McpHubManager


@pytest.fixture
def hub_and_suite(tmp_path: Path) -> tuple[McpHubManager, ToolManagementSuite]:
    hub = McpHubManager(tmp_path)
    hub.ensure_scaffold()
    reloads: list[int] = []
    suite = ToolManagementSuite(hub, on_reload=lambda: reloads.append(1))
    return hub, suite


def test_tool_inspect_refactor_retire(hub_and_suite: tuple[McpHubManager, ToolManagementSuite]) -> None:
    hub, suite = hub_and_suite

    # 1. Register an initial tool
    initial_code = '''@hub.tool()
def sample_tool(path: str = "C:\\\\") -> str:
    """Sample docstring."""
    return f"Listing {path}"
'''
    hub.register_tool_code("sample_tool", initial_code)

    # 2. Inspect tool
    inspect_res = suite.tool_inspect("sample_tool")
    assert inspect_res.success
    assert "def sample_tool" in inspect_res.output
    assert "Sample docstring" in inspect_res.output

    # 3. Refactor tool with valid code
    updated_code = '''@hub.tool()
def sample_tool(path: str = "D:\\\\", verbose: bool = True) -> str:
    """Updated docstring with verbose flag."""
    return f"Verbose listing of {path}"
'''
    refactor_res = suite.tool_refactor("sample_tool", updated_code)
    assert refactor_res.success
    assert "refactored and hot-reloaded successfully" in refactor_res.output

    # Verify updated inspection
    re_inspect = suite.tool_inspect("sample_tool")
    assert re_inspect.success
    assert "verbose: bool = True" in re_inspect.output
    assert "Updated docstring" in re_inspect.output

    # 4. Refactor with syntax error should be rejected
    bad_code = "def broken(path: str: pass"
    bad_res = suite.tool_refactor("sample_tool", bad_code)
    assert not bad_res.success
    assert "Syntax error" in bad_res.error

    # 5. Retire tool
    retire_res = suite.tool_retire("sample_tool")
    assert retire_res.success
    assert "retired and removed" in retire_res.output

    # 6. Verify retirement
    gone_res = suite.tool_inspect("sample_tool")
    assert not gone_res.success
