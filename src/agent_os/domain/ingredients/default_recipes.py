"""Migrated default recipes declared as contract-first RecipeContracts."""

from agent_os.domain.ingredients.contracts import (
    AcceptanceCheck,
    AcceptanceCheckType,
    RecipeContract,
)
from agent_os.domain.ingredients.envelope import (
    IngredientKind,
    IngredientStatus,
    Provenance,
)
from agent_os.domain.ingredients.signature import CapabilitySignature
from agent_os.domain.ingredients.vocabulary import Effect, Scope, Verb


def get_default_recipe_contracts() -> list[RecipeContract]:
    """Return contract-first declarations for core system workflows."""
    return [
        RecipeContract(
            id="self_health_audit",
            version=1,
            kind=IngredientKind.RECIPE,
            status=IngredientStatus.ACTIVE,
            provenance=Provenance(author="system"),
            description="Audit runtime health, recent failures, and system diagnostics.",
            capability=CapabilitySignature(
                verb=Verb.AUDIT,
                resource="runtime.health",
                scope=Scope.RUNTIME,
                effect=Effect.READ_ONLY,
            ),
            inputs_schema={
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "default": 24},
                },
                "additionalProperties": False,
            },
            outputs_schema={
                "type": "object",
                "properties": {
                    "healthy": {"type": "boolean"},
                    "error_count": {"type": "integer"},
                    "diagnostic_summary": {"type": "string"},
                },
                "required": ["healthy"],
            },
            tools=["telemetry_audit@1"],
            acceptance=[
                AcceptanceCheck(
                    check_type=AcceptanceCheckType.JSON_SCHEMA,
                    rule="outputs.healthy is boolean",
                    description="Ensures healthy flag is boolean",
                )
            ],
            intent_examples=[
                "how healthy is the system",
                "any errors lately",
                "run a health check on yourself",
                "audit telemetry logs",
            ],
        ),
        RecipeContract(
            id="wiki_capture_note",
            version=1,
            kind=IngredientKind.RECIPE,
            status=IngredientStatus.ACTIVE,
            provenance=Provenance(author="system"),
            description="Capture, format, and stage notes or conversation summaries in the vault.",
            capability=CapabilitySignature(
                verb=Verb.WRITE,
                resource="vault.note",
                scope=Scope.VAULT,
                effect=Effect.STATE_CHANGE,
            ),
            inputs_schema={
                "type": "object",
                "properties": {
                    "note_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["note_path", "content"],
                "additionalProperties": False,
            },
            outputs_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "note_path": {"type": "string"},
                },
                "required": ["status"],
            },
            tools=["wiki_write@1"],
            acceptance=[
                AcceptanceCheck(
                    check_type=AcceptanceCheckType.DETERMINISTIC,
                    rule="outputs.status == 'ok'",
                    description="Ensures note write succeeded",
                )
            ],
            intent_examples=[
                "save this as a note",
                "add that idea to my vault",
                "capture a summary of our chat",
                "save this to my inbox",
                "stash that explanation in my knowledge base",
            ],
        ),
        RecipeContract(
            id="wiki_list_notes",
            version=1,
            kind=IngredientKind.RECIPE,
            status=IngredientStatus.ACTIVE,
            provenance=Provenance(author="system"),
            description="Enumerate documents and notes in the knowledge vault.",
            capability=CapabilitySignature(
                verb=Verb.LIST,
                resource="vault.note",
                scope=Scope.VAULT,
                effect=Effect.READ_ONLY,
            ),
            inputs_schema={
                "type": "object",
                "properties": {
                    "subdirectory": {"type": "string", "default": ""},
                },
                "additionalProperties": False,
            },
            outputs_schema={
                "type": "object",
                "properties": {
                    "notes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["notes"],
            },
            tools=["wiki_list@1"],
            acceptance=[
                AcceptanceCheck(
                    check_type=AcceptanceCheckType.JSON_SCHEMA,
                    rule="outputs.notes is array",
                    description="Notes output is a list",
                )
            ],
            intent_examples=[
                "list my notes in the vault",
                "what notes do I have in inbox",
                "show my vault documents",
                "browse notes in knowledge base",
            ],
        ),
        RecipeContract(
            id="session_search_history",
            version=1,
            kind=IngredientKind.RECIPE,
            status=IngredientStatus.ACTIVE,
            provenance=Provenance(author="system"),
            description="Search conversation history and turns for topics or queries.",
            capability=CapabilitySignature(
                verb=Verb.SEARCH,
                resource="session.history",
                scope=Scope.SESSION,
                effect=Effect.READ_ONLY,
            ),
            inputs_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            outputs_schema={
                "type": "object",
                "properties": {
                    "matches": {"type": "array"},
                },
                "required": ["matches"],
            },
            tools=["session_search@1"],
            acceptance=[
                AcceptanceCheck(
                    check_type=AcceptanceCheckType.JSON_SCHEMA,
                    rule="outputs.matches is array",
                    description="Search results returned as array",
                )
            ],
            intent_examples=[
                "what did we talk about last week",
                "find when I mentioned my trip",
                "search our chat history",
                "search history for docker compose",
                "didn't we discuss the router config a few days ago?",
            ],
        ),
        RecipeContract(
            id="workspace_inspect_directory",
            version=1,
            kind=IngredientKind.RECIPE,
            status=IngredientStatus.ACTIVE,
            provenance=Provenance(author="system"),
            description="List files and directories in the workspace.",
            capability=CapabilitySignature(
                verb=Verb.LIST,
                resource="workspace.directory",
                scope=Scope.WORKSPACE,
                effect=Effect.READ_ONLY,
            ),
            inputs_schema={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string", "default": "."},
                    "max_depth": {"type": "integer", "default": 3},
                },
                "additionalProperties": False,
            },
            outputs_schema={
                "type": "object",
                "properties": {
                    "entries": {"type": "array"},
                    "total_count": {"type": "integer"},
                },
                "required": ["entries"],
            },
            tools=["workspace_tree@1"],
            acceptance=[
                AcceptanceCheck(
                    check_type=AcceptanceCheckType.JSON_SCHEMA,
                    rule="outputs.entries is array",
                    description="Entries is an array",
                )
            ],
            intent_examples=[
                "what's in my workspace folder",
                "list the files in the workspace",
                "show me workspace directories",
                "enumerate everything in workspace",
            ],
        ),
        RecipeContract(
            id="workspace_read_file",
            version=1,
            kind=IngredientKind.RECIPE,
            status=IngredientStatus.ACTIVE,
            provenance=Provenance(author="system"),
            description="Read lines from a workspace file with pagination.",
            capability=CapabilitySignature(
                verb=Verb.READ,
                resource="workspace.file",
                scope=Scope.WORKSPACE,
                effect=Effect.READ_ONLY,
            ),
            inputs_schema={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "start_line": {"type": "integer", "default": 1},
                    "line_count": {"type": "integer", "default": 100},
                },
                "required": ["relative_path"],
                "additionalProperties": False,
            },
            outputs_schema={
                "type": "object",
                "properties": {
                    "lines": {"type": "array"},
                    "total_lines": {"type": "integer"},
                },
                "required": ["lines"],
            },
            tools=["workspace_read@1"],
            acceptance=[
                AcceptanceCheck(
                    check_type=AcceptanceCheckType.JSON_SCHEMA,
                    rule="outputs.lines is array",
                    description="Lines is an array",
                )
            ],
            intent_examples=[
                "read README.md",
                "show me what's inside pyproject.toml",
                "print the contents of the log file",
                "open the file config.yaml and tell me what it says",
            ],
        ),
        RecipeContract(
            id="workspace_execute_command",
            version=1,
            kind=IngredientKind.RECIPE,
            status=IngredientStatus.ACTIVE,
            provenance=Provenance(author="system"),
            description="Execute a sandboxed shell command in the workspace.",
            capability=CapabilitySignature(
                verb=Verb.EXECUTE,
                resource="workspace.command",
                scope=Scope.WORKSPACE,
                effect=Effect.STATE_CHANGE,
            ),
            inputs_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "default": 30},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            outputs_schema={
                "type": "object",
                "properties": {
                    "exit_code": {"type": "integer"},
                    "stdout": {"type": "string"},
                    "stderr": {"type": "string"},
                },
                "required": ["exit_code"],
            },
            tools=["workspace_run@1"],
            acceptance=[
                AcceptanceCheck(
                    check_type=AcceptanceCheckType.JSON_SCHEMA,
                    rule="outputs.exit_code is integer",
                    description="Exit code is an integer",
                )
            ],
            intent_examples=[
                "run python --version in workspace",
                "execute tests in sandbox",
                "run git status in workspace",
                "check python environment in workspace",
            ],
        ),
    ]
