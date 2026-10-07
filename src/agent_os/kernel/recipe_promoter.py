"""On-demand recipe promotion engine staging discovered workflows to 00_Inbox."""

import re
from pathlib import Path
from typing import Any

from agent_os.domain.session import JourneyRecord
from agent_os.domain.wiki import ProtectedFolder
from agent_os.infrastructure.storage.journey_repo import JourneyRepository
from agent_os.infrastructure.wiki.store import WikiStore


def slugify_recipe_id(name: str) -> str:
    """Convert display name into safe lowercase alphanumeric identifier."""
    slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", name.strip().lower()).strip("_")
    return slug or "promoted_recipe"


class RecipePromoter:
    """Extracts execution telemetry from completed journeys and stages recipes in 00_Inbox."""

    def __init__(self, journey_repo: JourneyRepository, wiki_store: WikiStore) -> None:
        self.journey_repo = journey_repo
        self.wiki_store = wiki_store

    def build_recipe_markdown(
        self,
        journey: JourneyRecord,
        recipe_name: str,
        description: str | None = None,
        scratchpad_steps: list[dict[str, Any]] | None = None,
    ) -> str:
        """Synthesize YAML frontmatter and runbook body from journey telemetry."""
        recipe_id = slugify_recipe_id(recipe_name)
        desc = description or journey.task

        # Collect tools used in journey steps
        steps = scratchpad_steps or self.journey_repo.get_journey_scratchpad(journey.journey_id)
        tools_used: list[str] = []
        for step in steps:
            node = step.get("node_name", "")
            if node and node not in tools_used:
                tools_used.append(node)

        yaml_lines = [
            "---",
            f'title: "Recipe: {recipe_name}"',
            'category: "recipes"',
            "tags:",
            "  - recipe",
            "  - user_promoted",
            f"recipe_id: {recipe_id}",
            f'name: "{recipe_name}"',
            f'description: "{desc}"',
            'execution_engine: "react"',
            'target_model_tier: "reasoning"',
            "required_tools:",
        ]
        for t in tools_used:
            yaml_lines.append(f"  - {t}")
        yaml_lines.extend(
            [
                "timeout_seconds: 300",
                "---",
                "",
                f"# Recipe: {recipe_name}",
                "",
                "## Goal",
                journey.task,
                "",
                "## Summary",
                journey.summary or "Executed successfully via dynamic task brief.",
                "",
                "## Procedural Steps",
            ]
        )

        if steps:
            for idx, s in enumerate(steps, 1):
                node = s.get("node_name", "step")
                yaml_lines.append(f"{idx}. Execute `{node}` to perform required actions.")
        else:
            yaml_lines.append("1. Execute task according to goal directive.")

        yaml_lines.extend(
            [
                "",
                "## Verification Criteria",
                "- Verify output satisfies task completion standard",
                "- Check that no context isolation or permission invariants were breached",
                "",
            ]
        )

        return "\n".join(yaml_lines)

    def promote_journey(
        self,
        journey_id: str,
        recipe_name: str,
        description: str | None = None,
    ) -> Path:
        """Promote a specific completed journey into a staged recipe in 00_Inbox."""
        journey = self.journey_repo.get_journey(journey_id)
        if journey is None:
            raise ValueError(f"Journey not found: {journey_id}")
        if journey.status != "completed":
            raise ValueError(f"Journey {journey_id} is not completed (status: {journey.status})")

        steps = self.journey_repo.get_journey_scratchpad(journey_id)
        content = self.build_recipe_markdown(
            journey=journey,
            recipe_name=recipe_name,
            description=description,
            scratchpad_steps=steps,
        )

        recipe_id = slugify_recipe_id(recipe_name)
        filename = f"{recipe_id}.md"

        # The Sacred Rule of 00_Inbox: Stage into 00_Inbox for validation and graduation
        inbox_dir = self.wiki_store.root_dir / ProtectedFolder.INBOX.value
        inbox_dir.mkdir(parents=True, exist_ok=True)
        dest_path = inbox_dir / filename
        dest_path.write_text(content, encoding="utf-8")
        return dest_path

    def promote_recent_for_session(
        self,
        session_id: str,
        recipe_name: str,
        description: str | None = None,
    ) -> Path:
        """Promote the most recent completed ephemeral workflow in a session to 00_Inbox."""
        journey = self.journey_repo.get_latest_completed_journey(session_id)
        if journey is None:
            raise ValueError(f"No completed journeys found for session: {session_id}")
        return self.promote_journey(
            journey_id=journey.journey_id,
            recipe_name=recipe_name,
            description=description,
        )
