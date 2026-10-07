"""Unit tests for ReAct parser and tool prompt formatting utilities (C2)."""

from agent_os.domain.policy import ActionTier
from agent_os.domain.tools import ToolDefinition, ToolParameterSchema
from agent_os.kernel.react_parser import format_tools_prompt, parse_react_response


def test_format_tools_prompt_empty() -> None:
    """Verify empty tools list returns empty string."""
    assert format_tools_prompt([]) == ""


def test_format_tools_prompt_with_parameters() -> None:
    """Verify formatted tools prompt includes action tiers, parameters, and contract."""
    tool = ToolDefinition(
        name="wiki_search",
        description="Search notes via FTS5",
        action_tier=ActionTier.READ,
        parameters=[
            ToolParameterSchema(
                name="query",
                type_name="string",
                description="Search query string",
                required=True,
            ),
            ToolParameterSchema(
                name="limit",
                type_name="integer",
                description="Max results",
                required=False,
                default=5,
            ),
        ],
    )
    prompt = format_tools_prompt([tool])

    assert "<tools>" in prompt
    assert "### `wiki_search`" in prompt
    assert "Description: Search notes via FTS5" in prompt
    assert "Action Tier: read" in prompt
    assert "- `query` (string, required): Search query string" in prompt
    assert "- `limit` (integer, optional, default: 5): Max results" in prompt
    assert "Tool Invocation Contract:" in prompt
    assert '"action": "<tool_name>"' in prompt
    assert "</tools>" in prompt


def test_parse_react_response_standard_json() -> None:
    text = (
        '{"thought": "Searching docs", "action": "wiki_search", "parameters": {"query": "python"}}'
    )
    thought, action, params = parse_react_response(text)
    assert thought == "Searching docs"
    assert action == "wiki_search"
    assert params == {"query": "python"}


def test_parse_react_response_markdown_block() -> None:
    """Verify markdown-fenced json block is parsed."""
    text = """I will search the vault.
```json
{
  "thought": "Find index",
  "action": "wiki_read",
  "parameters": {"path": "01_Notes/index.md"}
}
```"""
    thought, action, params = parse_react_response(text)
    assert thought == "Find index"
    assert action == "wiki_read"
    assert params == {"path": "01_Notes/index.md"}


def test_parse_react_response_missing_thought_extracts_preamble() -> None:
    """Verify missing thought extracts the text preceding the JSON action."""
    text = """Examining current environment.
{"action": "env_probe", "parameters": {}}"""
    thought, action, params = parse_react_response(text)
    assert thought == "Examining current environment."
    assert action == "env_probe"
    assert params == {}


def test_parse_react_response_python_literals() -> None:
    """Verify python booleans True/False and None are sanitized and parsed."""
    text = '{"action": "toggle_feature", "parameters": {"enabled": True, "filter": None}}'
    thought, action, params = parse_react_response(text)
    assert action == "toggle_feature"
    assert params == {"enabled": True, "filter": None}


def test_parse_react_response_final_answer() -> None:
    """Verify plain text without action JSON returns (None, None, None)."""
    text = "The task has been completed successfully with verified results."
    thought, action, params = parse_react_response(text)
    assert thought is None
    assert action is None
    assert params is None
