"""Unit tests for RecipeToolSuite inspection, upsert, and deletion."""

from pathlib import Path

import pytest

from agent_os.domain.recipe import RecipeMetadata, RecipeRecord
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.kernel.recipe_tools import RecipeToolSuite


@pytest.fixture
def recipe_suite(tmp_path: Path) -> RecipeToolSuite:
    repo = RecipeRepository(tmp_path / "recipes.db")
    return RecipeToolSuite(repo)


def test_recipe_crud_lifecycle(recipe_suite: RecipeToolSuite) -> None:
    # 1. Initially empty
    list_res = recipe_suite.recipe_list()
    assert list_res.success
    assert "No recipes found" in list_res.output

    # 2. Upsert a recipe
    upsert_res = recipe_suite.recipe_upsert(
        recipe_id="host_fs_test",
        name="Host Filesystem Test",
        description="Inspects directories on host",
        required_tools="list_drive_contents, read_file",
        tags="filesystem, storage, test",
        body="Inspect target path and return contents.",
        execution_engine="react",
        timeout_seconds=90,
    )
    assert upsert_res.success
    assert "saved successfully" in upsert_res.output

    # 3. Retrieve the recipe
    get_res = recipe_suite.recipe_get("host_fs_test")
    assert get_res.success
    assert "host_fs_test" in get_res.output
    assert "list_drive_contents" in get_res.output

    # 4. Filter list by tag
    tag_res = recipe_suite.recipe_list(tag="storage")
    assert tag_res.success
    assert "host_fs_test" in tag_res.output

    nomatch_res = recipe_suite.recipe_list(tag="nonexistent")
    assert nomatch_res.success
    assert "No recipes found" in nomatch_res.output

    # 5. Delete the recipe
    del_res = recipe_suite.recipe_delete("host_fs_test")
    assert del_res.success
    assert "deleted successfully" in del_res.output

    # 6. Verify deletion
    assert not recipe_suite.recipe_get("host_fs_test").success
