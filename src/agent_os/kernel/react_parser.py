"""Parsing and prompt formatting utilities for ReAct execution workers."""

import json
import re
from typing import Any

from agent_os.domain.tools import ToolDefinition


def format_tools_prompt(tools: list[ToolDefinition]) -> str:
    """Format available tool definitions and JSON invocation contract for ReAct workers (C2)."""
    if not tools:
        return ""

    lines: list[str] = [
        "<tools>",
        "You have access to the following tools to accomplish your task:\n",
    ]
    for tool in tools:
        lines.append(f"### `{tool.name}`")
        lines.append(f"Description: {tool.description}")
        lines.append(f"Action Tier: {tool.action_tier.value}")
        if tool.parameters:
            lines.append("Parameters:")
            for p in tool.parameters:
                req_str = "required" if p.required else "optional"
                default_str = f", default: {p.default}" if p.default is not None else ""
                lines.append(
                    f"  - `{p.name}` ({p.type_name}, {req_str}{default_str}): {p.description}"
                )
        else:
            lines.append("Parameters: None")
        lines.append("")

    contract = (
        "Tool Invocation Contract:\n"
        "To invoke a tool, emit a JSON block matching this exact schema:\n"
        "```json\n"
        "{\n"
        '  "thought": "<reasoning about why you are taking this action>",\n'
        '  "action": "<tool_name>",\n'
        '  "parameters": {\n'
        '    "<param_name>": <value>\n'
        "  }\n"
        "}\n"
        "```\n"
        "When you have completed the task or do not need to call any more tools, "
        "output your final response directly as plain text without an action JSON block."
    )
    lines.append(contract)
    lines.append("</tools>")
    return "\n".join(lines)


def parse_react_response(
    text: str,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Parse model reasoning vs structured tool invocations.

    Returns (thought, tool_name, parameters) or (None, None, None) if final answer.
    """
    start_pos = 0
    while True:
        idx = text.find("{", start_pos)
        if idx == -1:
            break

        depth = 0
        in_string = False
        escape = False
        end_idx = -1
        for i in range(idx, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if not in_string:
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        end_idx = i
                        break

        if end_idx != -1:
            json_str = text[idx : end_idx + 1]
            try:
                data = json.loads(json_str)
                if (
                    isinstance(data, dict)
                    and "action" in data
                    and isinstance(data["action"], str)
                    and len(data["action"].strip()) > 0
                ):
                    tool_name = data["action"].strip()
                    if tool_name.lower() in (
                        "none", "null", "finish", "done", "stop", "final_answer", "no_tool"
                    ):
                        return None, None, None
                    raw_params = data.get("parameters", data.get("args", {}))
                    parameters = raw_params if isinstance(raw_params, dict) else {}

                    thought = data.get("thought")
                    if not thought or not str(thought).strip():
                        raw_pre = text[:idx]
                        cleaned_pre = re.sub(r"```(?:json)?\s*$", "", raw_pre).strip()
                        thought = cleaned_pre if cleaned_pre else f"Calling tool: {tool_name}"
                    return str(thought), tool_name, parameters
            except json.JSONDecodeError:
                try:
                    sanitized = re.sub(r"\bTrue\b", "true", json_str)
                    sanitized = re.sub(r"\bFalse\b", "false", sanitized)
                    sanitized = re.sub(r"\bNone\b", "null", sanitized)
                    data = json.loads(sanitized)
                    if (
                        isinstance(data, dict)
                        and "action" in data
                        and isinstance(data["action"], str)
                        and len(data["action"].strip()) > 0
                    ):
                        tool_name = data["action"].strip()
                        if tool_name.lower() in (
                            "none", "null", "finish", "done", "stop", "final_answer", "no_tool"
                        ):
                            return None, None, None
                        raw_params = data.get("parameters", data.get("args", {}))
                        parameters = raw_params if isinstance(raw_params, dict) else {}

                        thought = data.get("thought")
                        if not thought or not str(thought).strip():
                            raw_pre = text[:idx]
                            cleaned_pre = re.sub(r"```(?:json)?\s*$", "", raw_pre).strip()
                            thought = cleaned_pre or f"Calling tool: {tool_name}"
                        return str(thought), tool_name, parameters
                except json.JSONDecodeError:
                    pass
            start_pos = idx + 1
        else:
            break

    return None, None, None
