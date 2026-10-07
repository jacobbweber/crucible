"""Session history tools for searching conversation turns across hot and cold archives."""

import json

from agent_os.domain.policy import ActionTier
from agent_os.domain.tools import (
    ToolDefinition,
    ToolExecutionResult,
    ToolParameterSchema,
)
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.infrastructure.storage.session_search import search_session_history


class SessionToolSuite:
    """Tool suite providing agent access to hot and cold conversation history."""

    def __init__(self, session_repo: SessionRepository) -> None:
        self.session_repo = session_repo

    def get_definitions(self) -> list[ToolDefinition]:
        """Return tool definitions and schemas for session inspection tools."""
        return [
            ToolDefinition(
                name="session_search_history",
                description="Search conversation history across active sessions and cold archives.",
                action_tier=ActionTier.READ,
                parameters=[
                    ToolParameterSchema(
                        name="query",
                        type_name="string",
                        description="Keywords or phrase to locate across messages and titles.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="include_archive",
                        type_name="boolean",
                        description="Whether to query the cold sessions_archive.db (default True).",
                        required=False,
                        default=True,
                    ),
                    ToolParameterSchema(
                        name="limit",
                        type_name="integer",
                        description="Maximum number of historical turns to return (default 10).",
                        required=False,
                        default=10,
                    ),
                ],
            ),
        ]

    def session_search_history(
        self, query: str, include_archive: bool = True, limit: int = 10
    ) -> ToolExecutionResult:
        """Search active and cold archived session turns matching query."""
        try:
            matches = search_session_history(
                db_path=self.session_repo.db_path,
                archive_db_path=self.session_repo.archive_db_path,
                query=query,
                limit=limit,
                include_archive=include_archive,
            )
            if not matches:
                return ToolExecutionResult(
                    tool_name="session_search_history",
                    success=True,
                    output=f"No conversation history matched query: '{query}'",
                )

            data = [m.to_dict() for m in matches]
            formatted_lines = [f"Found {len(matches)} historical turn(s) for query: '{query}':"]
            for m in matches:
                src_label = "[Cold Archive]" if m.is_archived else "[Active Session]"
                formatted_lines.append(
                    f"- {src_label} Session '{m.session_title}' ({m.session_id}) "
                    f"[{m.created_at[:10]}] {m.role.upper()}: {m.snippet}"
                )

            payload = {
                "count": len(matches),
                "summary": "\n".join(formatted_lines),
                "matches": data,
            }
            return ToolExecutionResult(
                tool_name="session_search_history",
                success=True,
                output=json.dumps(payload, indent=2),
            )
        except Exception as exc:
            return ToolExecutionResult(
                tool_name="session_search_history",
                success=False,
                output="",
                error=f"Failed to search session history: {exc}",
            )
