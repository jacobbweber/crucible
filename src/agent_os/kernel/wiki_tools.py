"""Wiki tool implementations, parameter schemas, and execution handlers."""

from agent_os.domain.policy import ActionTier
from agent_os.domain.tools import (
    ToolDefinition,
    ToolExecutionResult,
    ToolParameterSchema,
)
from agent_os.domain.wiki import NoteFrontmatter, ProtectedFolder
from agent_os.infrastructure.wiki.store import WikiStore


class WikiToolSuite:
    """Tool suite providing agent access to the 4-folder wiki store."""

    def __init__(self, wiki_store: WikiStore) -> None:
        self.store = wiki_store
        self.wiki_store = wiki_store

    def get_definitions(self) -> list[ToolDefinition]:
        """Return tool definitions and parameter schemas for all wiki capabilities."""
        base_defs = [
            ToolDefinition(
                name="wiki_read",
                description="Read and parse note frontmatter and body with line-bounded reading.",
                action_tier=ActionTier.READ,
                parameters=[
                    ToolParameterSchema(
                        name="path",
                        type_name="string",
                        description="Relative path of the note to read within the wiki vault.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="max_lines",
                        type_name="integer",
                        description="Maximum number of body lines to read.",
                        required=False,
                        default=200,
                    ),
                ],
            ),
            ToolDefinition(
                name="wiki_write",
                description="Write or overwrite a note with validated YAML frontmatter.",
                action_tier=ActionTier.STATE_CHANGE,
                parameters=[
                    ToolParameterSchema(
                        name="path",
                        type_name="string",
                        description="Relative target path for the note.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="title",
                        type_name="string",
                        description="Title of the note.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="category",
                        type_name="string",
                        description="Category for the note.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="tags",
                        type_name="array",
                        description="List of tags associated with the note.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="body",
                        type_name="string",
                        description="Markdown body content of the note.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="overwrite",
                        type_name="boolean",
                        description="Whether to overwrite existing file.",
                        required=False,
                        default=False,
                    ),
                ],
            ),
            ToolDefinition(
                name="wiki_list_category",
                description="List relative paths of notes inside a protected category folder.",
                action_tier=ActionTier.READ,
                parameters=[
                    ToolParameterSchema(
                        name="category",
                        type_name="string",
                        description="Protected category folder name (e.g. '01_Notes').",
                        required=True,
                    ),
                ],
            ),
            ToolDefinition(
                name="wiki_search",
                description="Search notes under 01_Notes/ by query matching title, tags, or body.",
                action_tier=ActionTier.READ,
                parameters=[
                    ToolParameterSchema(
                        name="query",
                        type_name="string",
                        description="Search term to locate across note contents.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="limit",
                        type_name="integer",
                        description="Maximum number of matched notes to return.",
                        required=False,
                        default=5,
                    ),
                ],
            ),
            ToolDefinition(
                name="wiki_graduate_inbox",
                description=(
                    "Deterministically validate frontmatter of all notes in 00_Inbox/ "
                    "and graduate passing notes into 01_Notes/<category>/"
                ),
                action_tier=ActionTier.STATE_CHANGE,
                parameters=[],
            ),
        ]
        warehouse_defs = [
            ToolDefinition(
                name=d.name.replace("wiki_", "warehouse_"),
                description=(
                    d.description.replace("wiki", "warehouse").replace("01_Notes", "01_Knowledge")
                ),
                action_tier=d.action_tier,
                parameters=d.parameters,
            )
            for d in base_defs
        ]
        return base_defs + warehouse_defs

    def wiki_read(self, path: str, max_lines: int = 200) -> ToolExecutionResult:
        """Read note frontmatter and body content, enforcing max_lines ceiling."""
        try:
            frontmatter, body, total_lines, clamped = self.store.read_note_detailed(
                path, max_lines=max_lines
            )

            meta_lines = [
                "---",
                f"title: {frontmatter.title}",
                f"category: {frontmatter.category}",
                f"tags: [{', '.join(frontmatter.tags)}]",
                "---",
                body,
            ]
            if clamped:
                meta_lines.append(
                    f"\n[Note clamped to {max_lines} lines; {total_lines} total lines in note]"
                )

            return ToolExecutionResult(
                tool_name="wiki_read",
                success=True,
                output="\n".join(meta_lines),
            )
        except (FileNotFoundError, ValueError) as e:
            return ToolExecutionResult(
                tool_name="wiki_read",
                success=False,
                output="",
                error=str(e),
            )
        except Exception as e:
            return ToolExecutionResult(
                tool_name="wiki_read",
                success=False,
                output="",
                error=str(e),
            )

    def wiki_write(
        self,
        path: str,
        title: str,
        category: str,
        tags: list[str],
        body: str,
        overwrite: bool = False,
    ) -> ToolExecutionResult:
        """Create or update a note with structured YAML frontmatter."""
        try:
            frontmatter = NoteFrontmatter(title=title, category=category, tags=tags)
            self.store.write_note(path, frontmatter, body, overwrite=overwrite)
            return ToolExecutionResult(
                tool_name="wiki_write",
                success=True,
                output=f"Successfully written to {path}",
            )
        except Exception as e:
            return ToolExecutionResult(
                tool_name="wiki_write",
                success=False,
                output="",
                error=str(e),
            )

    def wiki_list_category(self, category: str) -> ToolExecutionResult:
        """List note relative paths within a designated protected folder category."""
        valid_folders = [f.value for f in ProtectedFolder]
        if category not in valid_folders:
            return ToolExecutionResult(
                tool_name="wiki_list_category",
                success=False,
                output="",
                error=f"Invalid category '{category}'. Must be one of: {valid_folders}",
            )

        try:
            folder = ProtectedFolder(category)
            notes = self.store.list_category(folder)
            if not notes:
                output = f"No notes found in {category}."
            else:
                output = "\n".join(f"- {note}" for note in notes)

            return ToolExecutionResult(
                tool_name="wiki_list_category",
                success=True,
                output=output,
            )
        except Exception as e:
            return ToolExecutionResult(
                tool_name="wiki_list_category",
                success=False,
                output="",
                error=str(e),
            )

    def wiki_search(self, query: str, limit: int = 5) -> ToolExecutionResult:
        """Search markdown notes in 01_Notes/ matching query against title, tags, and body."""
        try:
            matches = self.store.search_notes(query=query, limit=limit)
            if not matches:
                output = f"No notes matched query: '{query}'"
            else:
                output = "\n".join(f"- [{rel}]: {snip}" for rel, snip in matches)

            return ToolExecutionResult(
                tool_name="wiki_search",
                success=True,
                output=output,
            )
        except Exception as e:
            return ToolExecutionResult(
                tool_name="wiki_search",
                success=False,
                output="",
                error=str(e),
            )

    def wiki_graduate_inbox(self) -> ToolExecutionResult:
        """Validate frontmatter of staged notes in 00_Inbox/ and graduate valid notes."""
        report = self.store.graduate_inbox()
        lines: list[str] = [
            f"Graduated {report.graduated_count} notes, {report.failed_count} failed."
        ]

        if report.graduated_files:
            lines.append("\nGraduated Notes:")
            for filename in report.graduated_files:
                lines.append(f"- {filename}")

        if report.failures:
            lines.append("\nFailed Notes:")
            for failure in report.failures:
                reasons_str = "; ".join(failure.reasons)
                lines.append(f"- {failure.filename}: {reasons_str}")

        output_md = "\n".join(lines)
        return ToolExecutionResult(
            tool_name="wiki_graduate_inbox",
            success=True,
            output=output_md,
        )

    warehouse_read = wiki_read
    warehouse_write = wiki_write
    warehouse_list_category = wiki_list_category
    warehouse_search = wiki_search
    warehouse_graduate_inbox = wiki_graduate_inbox


WarehouseToolSuite = WikiToolSuite

