"""Unit tests verifying warehouse_* tool suite aliases and execution."""

from pathlib import Path

from agent_os.infrastructure.wiki.store import WarehouseStore
from agent_os.kernel.wiki_tools import WarehouseToolSuite


def test_warehouse_tools_read_write_and_search(tmp_path: Path) -> None:
    """Verify warehouse_* tools operate correctly across the warehouse vault."""
    store = WarehouseStore(tmp_path / "warehouse")
    store.init_vault()

    suite = WarehouseToolSuite(store)

    # 1. Write note using warehouse_write
    write_res = suite.warehouse_write(
        path="00_Inbox/homelab_plan.md",
        title="Homelab Architecture",
        category="operations/homelab",
        tags=["homelab", "proxmox"],
        body="## Cluster nodes\nNode 1 at 192.168.1.50\n",
    )
    assert write_res.success is True
    assert (tmp_path / "warehouse" / "00_Inbox" / "homelab_plan.md").is_file()

    # 2. Read note using warehouse_read
    read_res = suite.warehouse_read("00_Inbox/homelab_plan.md")
    assert read_res.success is True
    assert "192.168.1.50" in read_res.output

    # 3. Graduate note using warehouse_graduate_inbox
    grad_res = suite.warehouse_graduate_inbox()
    assert grad_res.success is True
    assert "homelab_plan.md" in grad_res.output

    # 4. Search notes using warehouse_search
    search_res = suite.warehouse_search("proxmox")
    assert search_res.success is True
    assert "homelab_plan.md" in search_res.output
