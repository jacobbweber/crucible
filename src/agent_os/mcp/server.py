import json
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import MCPServer

from agent_os.domain.kernel import UserTurnRequest
from agent_os.domain.wiki import ProtectedFolder

if TYPE_CHECKING:
    pass


def create_mcp_server(kernel: Any, name: str = "agent-os-node") -> MCPServer:
    """Build and configure a Model Context Protocol (MCP) server exposing kernel capabilities.

    Args:
        kernel: Initialized AgentOSKernel runtime.
        name: Identifier for this node in the MCP registry.

    Returns:
        Configured MCPServer ready for stdio or SSE transport.
    """
    server = MCPServer(name)

    # --------------------------------------------------------------------------
    # 1. Register Core Kernel Tools
    # --------------------------------------------------------------------------

    # Telemetry Tools
    async def telemetry_get_health_summary(hours: int = 24) -> str:
        """Query node health score, error rates, and operational findings."""
        res = await kernel.execute_tool("telemetry_get_health_summary", {"hours": hours})
        return res.output if res.success else f"Error: {res.error}"

    async def telemetry_audit_errors(limit: int = 10) -> str:
        """Audit recent error traces and failure events."""
        res = await kernel.execute_tool("telemetry_audit_errors", {"limit": limit})
        return res.output if res.success else f"Error: {res.error}"

    async def telemetry_stage_rca(
        title: str,
        issue_summary: str,
        root_cause: str,
        suggested_fix: str,
        severity: str = "warning",
    ) -> str:
        """Stage an RCA postmortem proposal into 00_Inbox for human review."""
        res = await kernel.execute_tool(
            "telemetry_stage_rca",
            {
                "title": title,
                "issue_summary": issue_summary,
                "root_cause": root_cause,
                "suggested_fix": suggested_fix,
                "severity": severity,
            },
        )
        return res.output if res.success else f"Error: {res.error}"

    async def telemetry_prune_old_records(retention_days: int = 30) -> str:
        """Prune telemetry metrics, events, and spans older than retention_days."""
        res = await kernel.execute_tool(
            "telemetry_prune_old_records", {"retention_days": retention_days}
        )
        return res.output if res.success else f"Error: {res.error}"

    # History & Search Tools
    async def session_search_history(
        query: str, include_archive: bool = True, limit: int = 10
    ) -> str:
        """Search past conversations across active sessions.db and cold sessions_archive.db."""
        res = await kernel.execute_tool(
            "session_search_history",
            {"query": query, "include_archive": include_archive, "limit": limit},
        )
        return res.output if res.success else f"Error: {res.error}"

    # Warehouse Wiki Tools
    async def warehouse_read(path: str, max_lines: int = 200) -> str:
        """Read note frontmatter and body from the warehouse vault."""
        res = await kernel.execute_tool("warehouse_read", {"path": path, "max_lines": max_lines})
        return res.output if res.success else f"Error: {res.error}"

    async def warehouse_write(
        path: str,
        title: str,
        category: str,
        tags: list[str],
        body: str,
        overwrite: bool = False,
    ) -> str:
        """Write note with frontmatter into the warehouse vault."""
        res = await kernel.execute_tool(
            "warehouse_write",
            {
                "path": path,
                "title": title,
                "category": category,
                "tags": tags,
                "body": body,
                "overwrite": overwrite,
            },
        )
        return res.output if res.success else f"Error: {res.error}"

    async def warehouse_list_category(category: str) -> str:
        """List notes in a warehouse folder (00_Inbox, 01_Knowledge, 02_Resources, 03_Archive)."""
        res = await kernel.execute_tool("warehouse_list_category", {"category": category})
        return res.output if res.success else f"Error: {res.error}"

    async def warehouse_search(query: str, limit: int = 5) -> str:
        """Search notes in 01_Knowledge by keyword or tag."""
        res = await kernel.execute_tool("warehouse_search", {"query": query, "limit": limit})
        return res.output if res.success else f"Error: {res.error}"

    async def warehouse_graduate_inbox() -> str:
        """Validate frontmatter of notes in 00_Inbox/ and graduate valid notes into 01_Knowledge."""
        res = await kernel.execute_tool("warehouse_graduate_inbox")
        return res.output if res.success else f"Error: {res.error}"

    # High-Level Directives & Interactive Conversation
    async def execute_task(task: str) -> str:
        """Dispatch a background task through the dynamic recipe assembly line."""
        pipeline_res = await kernel.execute_job(session_id="mcp_directive", task=task)
        env = pipeline_res.dispatch_result.envelope
        return f"[{env.status.upper()}] {env.summary}"

    async def chat_turn(message: str, session_id: str = "mcp_session") -> str:
        """Execute a conversational interaction turn with the companion."""
        req = UserTurnRequest(session_id=session_id, user_input=message)
        turn_resp = await kernel.handle_user_turn(req)
        return turn_resp.response_text

    # Register all tools on the MCP server
    tool_list = [
        (telemetry_get_health_summary, "telemetry_get_health_summary", "Query node health vitals"),
        (telemetry_audit_errors, "telemetry_audit_errors", "Audit recent operational errors"),
        (telemetry_stage_rca, "telemetry_stage_rca", "Stage an RCA postmortem into 00_Inbox"),
        (
            telemetry_prune_old_records,
            "telemetry_prune_old_records",
            "Prune telemetry older than N days",
        ),
        (
            session_search_history,
            "session_search_history",
            "Search hot & cold conversation history",
        ),
        (warehouse_read, "warehouse_read", "Read warehouse note contents"),
        (warehouse_write, "warehouse_write", "Write a note into the warehouse"),
        (warehouse_list_category, "warehouse_list_category", "List files in warehouse category"),
        (warehouse_search, "warehouse_search", "Search notes in 01_Knowledge"),
        (
            warehouse_graduate_inbox,
            "warehouse_graduate_inbox",
            "Graduate valid notes from 00_Inbox",
        ),
        (execute_task, "execute_task", "Dispatch an autonomous background directive"),
        (chat_turn, "chat_turn", "Send a conversational message to the companion"),
    ]
    for fn, t_name, t_desc in tool_list:
        server.add_tool(fn, name=t_name, description=t_desc)

    # --------------------------------------------------------------------------
    # 2. Register MCP Resources
    # --------------------------------------------------------------------------
    @server.resource("warehouse://inbox", name="Warehouse Inbox", mime_type="application/json")
    async def resource_inbox() -> str:
        """List files currently staged in 00_Inbox awaiting graduation."""
        inbox_dir = kernel.wiki_store.root_dir / ProtectedFolder.INBOX.value
        if not inbox_dir.exists():
            return json.dumps([])
        files = [p.name for p in sorted(inbox_dir.glob("*.md"))]
        return json.dumps({"staged_count": len(files), "notes": files}, indent=2)

    @server.resource(
        "warehouse://knowledge", name="Warehouse Knowledge", mime_type="application/json"
    )
    async def resource_knowledge() -> str:
        """List graduated knowledge files organized in 01_Knowledge."""
        k_folder = kernel.wiki_store.knowledge_folder
        k_dir = kernel.wiki_store.root_dir / k_folder
        if not k_dir.exists():
            return json.dumps([])
        files = [str(p.relative_to(k_dir)).replace("\\", "/") for p in sorted(k_dir.rglob("*.md"))]
        return json.dumps({"knowledge_count": len(files), "notes": files}, indent=2)

    @server.resource(
        "telemetry://health", name="System Health Vitals", mime_type="application/json"
    )
    async def resource_health() -> str:
        """Current operational health vitals, error rates, and findings."""
        report = kernel.collector.compile_health_report(hours=24)
        return json.dumps(
            {
                "health_score": report.health_score,
                "error_rate_percent": report.error_rate_percent,
                "avg_latency_ms": report.avg_latency_ms,
                "findings": report.findings,
            },
            indent=2,
        )

    # --------------------------------------------------------------------------
    # 3. Register MCP Prompts
    # --------------------------------------------------------------------------
    @server.prompt("self_health_audit", description="Audit node vitals and stage RCA if degraded")
    async def prompt_health_audit() -> str:
        return (
            "Please inspect the node's health summary and audit error traces. "
            "If anomalies exist, stage an RCA in 00_Inbox."
        )

    @server.prompt(
        "weekly_warehouse_graduation",
        description="Review 00_Inbox and graduate approved notes",
    )
    async def prompt_graduation() -> str:
        return (
            "Review notes in 00_Inbox, validate their frontmatter schema, "
            "and graduate valid notes into 01_Knowledge."
        )

    @server.prompt(
        "deep_topic_synthesis",
        description="Research a topic across past history and synthesize a note",
    )
    async def prompt_synthesis(topic: str) -> str:
        return (
            f"Search our historical conversations for '{topic}' across both hot and cold storage, "
            "and synthesize a knowledge note."
        )

    return server
