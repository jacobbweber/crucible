"""Unit tests for WikiToolSuite tool definitions, bounded reading, and note search."""

from pathlib import Path

from agent_os.domain.policy import ActionTier
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.wiki_tools import WikiToolSuite


def test_wiki_tools_definitions(tmp_path: Path) -> None:
    """Verify get_definitions returns all 4 wiki tools with accurate action tier classification."""
    store = WikiStore(tmp_path)
    store.init_vault()
    suite = WikiToolSuite(store)

    definitions = suite.get_definitions()
    assert len(definitions) >= 4

    def_map = {d.name: d for d in definitions}
    assert {
        "wiki_read",
        "wiki_write",
        "wiki_list_category",
        "wiki_search",
    }.issubset(def_map.keys())

    assert def_map["wiki_write"].action_tier == ActionTier.STATE_CHANGE
    assert def_map["wiki_read"].action_tier == ActionTier.READ
    assert def_map["wiki_list_category"].action_tier == ActionTier.READ
    assert def_map["wiki_search"].action_tier == ActionTier.READ


def test_wiki_write_and_read(tmp_path: Path) -> None:
    """Verify wiki_write creates file in vault and wiki_read recovers frontmatter and body."""
    store = WikiStore(tmp_path)
    store.init_vault()
    suite = WikiToolSuite(store)

    write_res = suite.wiki_write(
        path="01_Notes/projects/agent.md",
        title="Agent OS",
        category="projects",
        tags=["ai", "os"],
        body="Main architecture overview.",
    )
    assert write_res.success
    assert "Successfully written" in write_res.output
    assert (tmp_path / "01_Notes/projects/agent.md").exists()

    read_res = suite.wiki_read("01_Notes/projects/agent.md")
    assert read_res.success
    assert "Agent OS" in read_res.output
    assert "projects" in read_res.output
    assert "Main architecture overview." in read_res.output


def test_wiki_read_line_clamping(tmp_path: Path) -> None:
    """Verify wiki_read enforces max_lines and output explicitly indicates line clamping."""
    store = WikiStore(tmp_path)
    store.init_vault()
    suite = WikiToolSuite(store)

    long_body = "\n".join(f"Line content #{i}" for i in range(250))
    suite.wiki_write(
        path="01_Notes/long_note.md",
        title="Long Note",
        category="general",
        tags=["benchmark"],
        body=long_body,
    )

    read_res = suite.wiki_read("01_Notes/long_note.md", max_lines=50)
    assert read_res.success
    assert "clamped" in read_res.output.lower() or "truncated" in read_res.output.lower()
    assert "50" in read_res.output


def test_wiki_list_category(tmp_path: Path) -> None:
    """Verify wiki_list_category lists relative paths of notes in the specified protected root."""
    store = WikiStore(tmp_path)
    store.init_vault()
    suite = WikiToolSuite(store)

    suite.wiki_write(
        path="01_Notes/homelab/node1.md",
        title="Node 1",
        category="homelab",
        tags=["infra"],
        body="Specs of Node 1.",
    )

    list_res = suite.wiki_list_category(category="01_Notes")
    assert list_res.success
    assert "homelab/node1.md" in list_res.output


def test_wiki_search_finds_matching_snippets(tmp_path: Path) -> None:
    """Verify wiki_search scans 01_Notes/ and returns matching note relative path and snippet."""
    store = WikiStore(tmp_path)
    store.init_vault()
    suite = WikiToolSuite(store)

    suite.wiki_write(
        path="01_Notes/network/hardware.md",
        title="Network Gear",
        category="network",
        tags=["lan"],
        body="Includes Ubiquiti switch configuration and router setup.",
    )

    search_res = suite.wiki_search(query="switch")
    assert search_res.success
    assert "01_Notes/network/hardware.md" in search_res.output
    assert "Ubiquiti switch configuration" in search_res.output
