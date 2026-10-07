"""After-Hours Pattern Scout analyzing journey telemetry to propose reusable recipes."""

import re
from collections import defaultdict
from pathlib import Path

from agent_os.domain.session import JourneyRecord
from agent_os.domain.wiki import ProtectedFolder
from agent_os.infrastructure.storage.journey_repo import JourneyRepository
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.signaling import CompletionSignaler


def slugify_pattern_name(name: str) -> str:
    """Convert pattern description into safe lowercase filename slug."""
    slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", name.strip().lower()).strip("_")
    return slug or "discovered_pattern"


class PatternScout:
    """Scans telemetry for repeated tool sequences and drafts candidate recipes to 00_Inbox."""

    def __init__(
        self,
        journey_repo: JourneyRepository,
        recipe_repo: RecipeRepository,
        wiki_store: WikiStore,
        signaler: CompletionSignaler | None = None,
    ) -> None:
        self.journey_repo = journey_repo
        self.recipe_repo = recipe_repo
        self.wiki_store = wiki_store
        self.signaler = signaler

    def _get_existing_recipe_toolsets(self) -> list[set[str]]:
        """Retrieve toolsets of all existing catalog recipes to avoid proposing duplicates."""
        existing = self.recipe_repo.list_recipes()
        return [set(r.metadata.required_tools) for r in existing if r.metadata.required_tools]

    def _build_candidate_markdown(
        self,
        tool_sequence: tuple[str, ...],
        journeys: list[JourneyRecord],
    ) -> str:
        """Synthesize candidate recipe Markdown document with valid YAML frontmatter."""
        tools_list = list(tool_sequence)
        slug = "_".join(tools_list)
        pattern_title = " -> ".join(tools_list).replace("_", " ").title()
        recipe_id = f"suggested_{slug}"
        sample_task = journeys[0].task if journeys else "Perform recurring workflow"

        yaml_lines = [
            "---",
            f'title: "Candidate Recipe: {pattern_title}"',
            'category: "recipes"',
            "tags:",
            "  - recipe",
            "  - pattern_scout",
            "  - candidate",
            f"recipe_id: {recipe_id}",
            f'name: "{pattern_title}"',
            (
                f'description: "Auto-discovered pattern using {", ".join(tools_list)} '
                f'(observed {len(journeys)} times)."'
            ),
            'execution_engine: "react"',
            'target_model_tier: "reasoning"',
            "required_tools:",
        ]
        for tool in tools_list:
            yaml_lines.append(f"  - {tool}")
        yaml_lines.extend(
            [
                "timeout_seconds: 300",
                "---",
                "",
                f"# Candidate Recipe: {pattern_title}",
                "",
                "## Goal",
                f"Execute workflow commonly requested as: {sample_task}",
                "",
                "## Pattern Insights",
                f"- Discovered by Pattern Scout across {len(journeys)} successful runs.",
                f"- Involves tool sequence: `{', '.join(tools_list)}`.",
                "",
                "## Procedural Steps",
            ]
        )

        for idx, tool in enumerate(tools_list, 1):
            yaml_lines.append(f"{idx}. Execute `{tool}` with required runtime parameters.")

        yaml_lines.extend(
            [
                "",
                "## Verification Criteria",
                "- Verify all tool sequence operations succeed without errors",
                "- Validate output consistency against previous execution patterns",
                "",
            ]
        )

        return "\n".join(yaml_lines)

    def run_scout_cycle(
        self,
        min_frequency: int = 3,
        scan_limit: int = 100,
    ) -> list[Path]:
        """Scan recent journey steps, cluster repeated patterns, and stage candidate recipes."""
        completed_journeys = self.journey_repo.get_recent_completed_journeys(limit=scan_limit)
        if not completed_journeys:
            return []

        # Cluster journeys by their ordered tool sequence
        clusters: dict[tuple[str, ...], list[JourneyRecord]] = defaultdict(list)
        for journey in completed_journeys:
            steps = self.journey_repo.get_journey_scratchpad(journey.journey_id)
            tool_seq = tuple(str(step["node_name"]) for step in steps if step.get("node_name"))
            if tool_seq:
                clusters[tool_seq].append(journey)

        existing_toolsets = self._get_existing_recipe_toolsets()
        inbox_dir = self.wiki_store.root_dir / ProtectedFolder.INBOX.value
        inbox_dir.mkdir(parents=True, exist_ok=True)

        staged_files: list[Path] = []

        for tool_seq, matching_journeys in clusters.items():
            if len(matching_journeys) < min_frequency:
                continue

            tool_set = set(tool_seq)
            # Skip if an existing recipe already covers this exact toolset
            if tool_set in existing_toolsets:
                continue

            slug = "_".join(tool_seq)
            candidate_filename = f"suggested_{slug}.md"
            dest_path = inbox_dir / candidate_filename

            # If already proposed in 00_Inbox, do not overwrite
            if dest_path.exists():
                continue

            content = self._build_candidate_markdown(tool_seq, matching_journeys)
            dest_path.write_text(content, encoding="utf-8")
            staged_files.append(dest_path)

            # Signal ambient discovery notification
            if self.signaler is not None:
                notice = (
                    f"Good morning! I noticed we've performed {' -> '.join(tool_seq)} "
                    f"{len(matching_journeys)} times. I drafted a reusable recipe in 00_Inbox."
                )
                self.signaler.signal_discovery(
                    session_id="",
                    message=notice,
                    pattern_id=f"suggested_{slug}",
                )

        return staged_files
