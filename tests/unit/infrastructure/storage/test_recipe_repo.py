"""Unit tests for RecipeRepository persistence, intent matching, and FTS5 synchronization."""

from pathlib import Path

from agent_os.domain.recipe import RecipeMetadata, RecipeRecord
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository


def test_upsert_and_retrieve_recipe(tmp_path: Path) -> None:
    """Insert RecipeRecord; retrieve by ID; assert all fields match."""
    db_file = tmp_path / "recipes.db"
    repo = RecipeRepository(db_file)

    metadata = RecipeMetadata(
        recipe_id="recipe_briefing_001",
        name="Morning Briefing Routine",
        description="Scrapes RSS feeds and prepares daily executive summary",
        execution_engine="react",
        target_model_tier="reasoning",
        tags=["briefing", "daily", "rss"],
        required_tools=["rss_fetcher", "markdown_writer"],
        timeout_seconds=300,
    )
    record = RecipeRecord(
        metadata=metadata,
        markdown_path="recipes/daily/morning_briefing.md",
        body="## Morning Briefing\nRun daily at 8am to aggregate RSS feeds.",
    )

    saved = repo.upsert_recipe(record)
    assert saved.metadata.recipe_id == "recipe_briefing_001"

    retrieved = repo.get_recipe("recipe_briefing_001")
    assert retrieved is not None
    assert retrieved.metadata.recipe_id == record.metadata.recipe_id
    assert retrieved.metadata.name == record.metadata.name
    assert retrieved.metadata.description == record.metadata.description
    assert retrieved.metadata.execution_engine == record.metadata.execution_engine
    assert retrieved.metadata.target_model_tier == record.metadata.target_model_tier
    assert retrieved.metadata.tags == record.metadata.tags
    assert retrieved.metadata.required_tools == record.metadata.required_tools
    assert retrieved.metadata.timeout_seconds == record.metadata.timeout_seconds
    assert retrieved.markdown_path == record.markdown_path
    assert retrieved.body == record.body
    assert retrieved.created_at == record.created_at
    assert retrieved.updated_at == record.updated_at

    # Non-existent ID returns None
    assert repo.get_recipe("non_existent_recipe") is None


def test_match_intent_by_keyword(tmp_path: Path) -> None:
    """Insert recipe for 'Morning Briefing Routine'; match on 'run my morning briefing'.

    Assert recipe returned at rank 1 with score > 0.
    """
    db_file = tmp_path / "recipes.db"
    repo = RecipeRepository(db_file)

    metadata = RecipeMetadata(
        recipe_id="recipe_briefing_001",
        name="Morning Briefing Routine",
        description="Daily digest of important headlines and updates",
        execution_engine="react",
        target_model_tier="reasoning",
        tags=["briefing", "daily", "rss"],
        required_tools=["rss_fetcher"],
        timeout_seconds=300,
    )
    record = RecipeRecord(
        metadata=metadata,
        markdown_path="recipes/morning_briefing.md",
        body="Morning briefing instructions.",
    )
    repo.upsert_recipe(record)

    # Insert another non-matching recipe to test ranking
    other_metadata = RecipeMetadata(
        recipe_id="recipe_code_review_002",
        name="Pull Request Code Reviewer",
        description="Inspects git diffs and reports bugs",
        execution_engine="react",
        target_model_tier="coding",
        tags=["git", "code", "review"],
        required_tools=["git_diff"],
        timeout_seconds=300,
    )
    other_record = RecipeRecord(
        metadata=other_metadata,
        markdown_path="recipes/code_review.md",
        body="Code review instructions.",
    )
    repo.upsert_recipe(other_record)

    matches = repo.match_intent("run my morning briefing")
    assert len(matches) >= 1
    top_match = matches[0]
    assert top_match.recipe.metadata.recipe_id == "recipe_briefing_001"
    assert top_match.recipe.metadata.name == "Morning Briefing Routine"
    assert top_match.score > 0.0


def test_match_intent_by_tag(tmp_path: Path) -> None:
    """Match on 'rss'; verify morning briefing recipe matched via tags_text."""
    db_file = tmp_path / "recipes.db"
    repo = RecipeRepository(db_file)

    metadata = RecipeMetadata(
        recipe_id="recipe_briefing_001",
        name="Morning Briefing Routine",
        description="Daily digest of important headlines and updates",
        execution_engine="react",
        target_model_tier="reasoning",
        tags=["briefing", "daily", "rss"],
        required_tools=["rss_fetcher"],
        timeout_seconds=300,
    )
    record = RecipeRecord(
        metadata=metadata,
        markdown_path="recipes/morning_briefing.md",
        body="Morning briefing instructions.",
    )
    repo.upsert_recipe(record)

    matches = repo.match_intent("rss")
    assert len(matches) == 1
    assert matches[0].recipe.metadata.recipe_id == "recipe_briefing_001"
    assert matches[0].recipe.metadata.name == "Morning Briefing Routine"
    assert "rss" in matches[0].recipe.metadata.tags
    assert matches[0].score > 0.0


def test_delete_recipe_clears_fts(tmp_path: Path) -> None:
    """Delete recipe; verify subsequent match_intent() returns an empty list."""
    db_file = tmp_path / "recipes.db"
    repo = RecipeRepository(db_file)

    metadata = RecipeMetadata(
        recipe_id="recipe_temp_001",
        name="Temporary Cleanup Task",
        description="One-time file cleanup routine",
        execution_engine="direct",
        target_model_tier="fast",
        tags=["cleanup", "temp"],
        required_tools=[],
        timeout_seconds=60,
    )
    record = RecipeRecord(
        metadata=metadata,
        markdown_path="recipes/temp_cleanup.md",
        body="Cleanup temporary files.",
    )
    repo.upsert_recipe(record)

    assert len(repo.match_intent("cleanup")) == 1

    deleted = repo.delete_recipe("recipe_temp_001")
    assert deleted is True
    assert repo.get_recipe("recipe_temp_001") is None

    # Deleting again returns False
    assert repo.delete_recipe("recipe_temp_001") is False

    # FTS index search must return empty list
    assert repo.match_intent("cleanup") == []


def test_match_intent_rejects_stop_word_false_positives(tmp_path: Path) -> None:
    """Verify that unrelated queries sharing only stop words return 0 matches (H1)."""
    db_file = tmp_path / "recipes.db"
    repo = RecipeRepository(db_file)

    metadata = RecipeMetadata(
        recipe_id="recipe_daily_001",
        name="Daily Summary Report",
        description="Reads daily notes and creates executive digest",
        execution_engine="direct",
        target_model_tier="fast",
        tags=["summary", "notes"],
        required_tools=[],
        timeout_seconds=60,
    )
    record = RecipeRecord(
        metadata=metadata,
        markdown_path="recipes/daily.md",
        body="Read notes from the inbox and summarize.",
    )
    repo.upsert_recipe(record)

    # Unrelated task sharing only stop words like 'what', 'is', 'the', 'to'
    unrelated = "What is the best way to slice a 3D model for printing?"
    matches = repo.match_intent(unrelated)
    assert matches == []

    # Relevant task matches cleanly with score >= 0.5
    relevant = "Summarize my daily notes"
    matches_rel = repo.match_intent(relevant)
    assert len(matches_rel) == 1
    assert matches_rel[0].score >= 0.5
    assert matches_rel[0].recipe.metadata.recipe_id == "recipe_daily_001"
