"""Companion Front Door: structured intent tool specification and parsing.

Per ADR-0015 §4.4, the front-door companion invokes the native 'fulfill_request'
tool call with a schema-constrained TaskIntent instead of emitting fragile regex
directives in prose. Conversational turns do not invoke the tool.
"""

from typing import Any

from agent_os.domain.gateway import ToolCallPart, ToolSpec
from agent_os.domain.ingredients.intent import TaskIntent
from agent_os.domain.ingredients.vocabulary import (
    SCOPE_DESCRIPTIONS,
    VERB_DESCRIPTIONS,
    ResourceVocabularyRegistry,
    Scope,
    Verb,
)
from agent_os.infrastructure.gateway.structured import parse_tool_arguments


def build_fulfill_request_tool_spec(
    vocabulary: ResourceVocabularyRegistry | None = None,
) -> ToolSpec:
    """Build the self-contained native ToolSpec for 'fulfill_request'.

    Per findings G4 and G7:
    - The JSON schema is completely self-contained (no $ref or $defs).
    - Every vocabulary value (verbs, resources, scopes) carries its own description
      in the property description to ensure accurate classification across models.
    """
    registry = vocabulary or ResourceVocabularyRegistry.default_registry()
    resources = registry.list_resources()

    verb_descriptions = "\n".join(f"- '{v.value}': {desc}" for v, desc in VERB_DESCRIPTIONS.items())
    resource_descriptions = "\n".join(f"- '{r.name}': {r.description}" for r in resources)
    scope_descriptions = "\n".join(
        f"- '{s.value}': {desc}" for s, desc in SCOPE_DESCRIPTIONS.items()
    )

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "verb": {
                "type": "string",
                "enum": [v.value for v in Verb],
                "description": f"Action verb to perform. Valid verbs:\n{verb_descriptions}",
            },
            "resource": {
                "type": "string",
                "enum": [r.name for r in resources],
                "description": f"Target resource type. Valid resources:\n{resource_descriptions}",
            },
            "scope": {
                "type": "string",
                "enum": [s.value for s in Scope],
                "description": f"Operational boundary scope. Valid scopes:\n{scope_descriptions}",
            },
            "parameters": {
                "type": "object",
                "description": (
                    "Key-value argument parameters extracted from the user's request needed "
                    "to perform the operation (e.g. {'relative_path': 'src', 'query': 'kernel'})."
                ),
                "additionalProperties": True,
            },
            "desired_output": {
                "type": "string",
                "description": "Short description of the expected deliverable, result, or output.",
            },
            "normalized_utterance": {
                "type": "string",
                "description": (
                    "Clean, normalized phrasing of the user's intent without conversational filler."
                ),
            },
        },
        "required": ["verb", "resource", "scope", "normalized_utterance"],
        "additionalProperties": False,
    }

    return ToolSpec(
        name="fulfill_request",
        description=(
            "Call this tool to fulfill an operational task, query system state, execute a command, "
            "or inspect/modify resources (files, directories, notes, containers, health, etc.). "
            "DO NOT call this tool for general conversational turns, greetings, chit-chat, "
            "or questions answered directly from conversation history."
        ),
        parameters=parameters,
    )


def parse_task_intent(call: ToolCallPart) -> TaskIntent:
    """Validate and parse a fulfill_request ToolCallPart into a typed TaskIntent."""
    return parse_tool_arguments(call, TaskIntent)
