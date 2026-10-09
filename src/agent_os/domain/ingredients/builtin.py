"""Contract declarations for built-in tool suites across workspace, wiki, session, and telemetry."""

from typing import Any

from agent_os.domain.ingredients.contracts import (
    ContractExample,
    ToolContract,
    ToolRuntime,
)
from agent_os.domain.ingredients.envelope import (
    IngredientKind,
    IngredientStatus,
    Provenance,
)
from agent_os.domain.ingredients.signature import CapabilitySignature
from agent_os.domain.ingredients.vocabulary import Effect, Scope, Verb


def _make_tool(
    tool_id: str,
    description: str,
    verb: Verb,
    resource: str,
    scope: Scope,
    effect: Effect,
    input_properties: dict[str, Any],
    required_inputs: list[str],
    output_properties: dict[str, Any],
    examples: list[ContractExample],
) -> ToolContract:
    return ToolContract(
        id=tool_id,
        version=1,
        kind=IngredientKind.TOOL,
        status=IngredientStatus.ACTIVE,
        provenance=Provenance(author="system"),
        description=description,
        capability=CapabilitySignature(
            verb=verb,
            resource=resource,
            scope=scope,
            effect=effect,
        ),
        input_schema={
            "type": "object",
            "properties": input_properties,
            "required": required_inputs,
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": output_properties,
            "additionalProperties": True,
        },
        examples=examples,
        runtime=ToolRuntime.BUILTIN,
    )


def get_builtin_tool_contracts() -> list[ToolContract]:
    """Return contract specifications for all built-in system tools."""
    return [
        _make_tool(
            tool_id="workspace_tree",
            description="List files and directories in the workspace up to max_depth.",
            verb=Verb.LIST,
            resource="workspace.directory",
            scope=Scope.WORKSPACE,
            effect=Effect.READ_ONLY,
            input_properties={
                "relative_path": {"type": "string", "default": "."},
                "max_depth": {"type": "integer", "default": 3},
            },
            required_inputs=[],
            output_properties={
                "entries": {"type": "array", "items": {"type": "string"}},
                "total_count": {"type": "integer"},
            },
            examples=[
                ContractExample(
                    input={"relative_path": ".", "max_depth": 2},
                    description="List top two levels of the workspace",
                )
            ],
        ),
        _make_tool(
            tool_id="workspace_read",
            description="Read lines from a workspace file with pagination.",
            verb=Verb.READ,
            resource="workspace.file",
            scope=Scope.WORKSPACE,
            effect=Effect.READ_ONLY,
            input_properties={
                "relative_path": {"type": "string"},
                "start_line": {"type": "integer", "default": 1},
                "line_count": {"type": "integer", "default": 100},
            },
            required_inputs=["relative_path"],
            output_properties={
                "lines": {"type": "array", "items": {"type": "string"}},
                "total_lines": {"type": "integer"},
            },
            examples=[
                ContractExample(
                    input={"relative_path": "README.md", "start_line": 1, "line_count": 50},
                    description="Read first 50 lines of README.md",
                )
            ],
        ),
        _make_tool(
            tool_id="workspace_write",
            description="Create or overwrite a file in the workspace.",
            verb=Verb.WRITE,
            resource="workspace.file",
            scope=Scope.WORKSPACE,
            effect=Effect.STATE_CHANGE,
            input_properties={
                "relative_path": {"type": "string"},
                "content": {"type": "string"},
            },
            required_inputs=["relative_path", "content"],
            output_properties={
                "bytes_written": {"type": "integer"},
                "path": {"type": "string"},
            },
            examples=[
                ContractExample(
                    input={"relative_path": "output.txt", "content": "hello world\n"},
                    description="Write text into output.txt",
                )
            ],
        ),
        _make_tool(
            tool_id="workspace_run",
            description="Execute a sandboxed command inside the workspace directory.",
            verb=Verb.EXECUTE,
            resource="workspace.command",
            scope=Scope.WORKSPACE,
            effect=Effect.STATE_CHANGE,
            input_properties={
                "command": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 30},
            },
            required_inputs=["command"],
            output_properties={
                "exit_code": {"type": "integer"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
            },
            examples=[
                ContractExample(
                    input={"command": "python --version", "timeout_seconds": 10},
                    description="Check Python version in sandbox",
                )
            ],
        ),
        _make_tool(
            tool_id="wiki_list",
            description="Enumerate document and note paths in the knowledge vault.",
            verb=Verb.LIST,
            resource="vault.note",
            scope=Scope.VAULT,
            effect=Effect.READ_ONLY,
            input_properties={
                "subdirectory": {"type": "string", "default": ""},
            },
            required_inputs=[],
            output_properties={
                "notes": {"type": "array", "items": {"type": "string"}},
            },
            examples=[
                ContractExample(
                    input={"subdirectory": ""},
                    description="List all notes in root vault",
                )
            ],
        ),
        _make_tool(
            tool_id="wiki_read",
            description="Read the markdown body and metadata of a vault note.",
            verb=Verb.READ,
            resource="vault.note",
            scope=Scope.VAULT,
            effect=Effect.READ_ONLY,
            input_properties={
                "note_path": {"type": "string"},
            },
            required_inputs=["note_path"],
            output_properties={
                "title": {"type": "string"},
                "content": {"type": "string"},
            },
            examples=[
                ContractExample(
                    input={"note_path": "index.md"},
                    description="Read the vault index note",
                )
            ],
        ),
        _make_tool(
            tool_id="wiki_write",
            description="Create or update a note in the personal knowledge vault.",
            verb=Verb.WRITE,
            resource="vault.note",
            scope=Scope.VAULT,
            effect=Effect.STATE_CHANGE,
            input_properties={
                "note_path": {"type": "string"},
                "content": {"type": "string"},
            },
            required_inputs=["note_path", "content"],
            output_properties={
                "status": {"type": "string"},
                "note_path": {"type": "string"},
            },
            examples=[
                ContractExample(
                    input={"note_path": "inbox/ideas.md", "content": "# Ideas\n- new concept"},
                    description="Write ideas note to vault inbox",
                )
            ],
        ),
        _make_tool(
            tool_id="session_search",
            description="Search conversation turns and history for matching topics or queries.",
            verb=Verb.SEARCH,
            resource="session.history",
            scope=Scope.SESSION,
            effect=Effect.READ_ONLY,
            input_properties={
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            required_inputs=["query"],
            output_properties={
                "matches": {"type": "array", "items": {"type": "object"}},
            },
            examples=[
                ContractExample(
                    input={"query": "backup configuration", "limit": 5},
                    description="Search session history for backup configuration",
                )
            ],
        ),
        _make_tool(
            tool_id="telemetry_audit",
            description="Audit runtime health, recent failures, and system diagnostics.",
            verb=Verb.AUDIT,
            resource="runtime.health",
            scope=Scope.RUNTIME,
            effect=Effect.READ_ONLY,
            input_properties={
                "hours": {"type": "integer", "default": 24},
            },
            required_inputs=[],
            output_properties={
                "healthy": {"type": "boolean"},
                "error_count": {"type": "integer"},
                "diagnostic_summary": {"type": "string"},
            },
            examples=[
                ContractExample(
                    input={"hours": 12},
                    description="Audit telemetry over the past 12 hours",
                )
            ],
        ),
    ]
