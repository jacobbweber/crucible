"""HTTP and Server-Sent Event (SSE) route handlers for Agent OS Web UI."""

import json
from collections.abc import AsyncGenerator
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from agent_os.domain.kernel import UserTurnRequest
from agent_os.kernel.master_kernel import AgentOSKernel
from agent_os.mcp.client import McpServerConfig
from agent_os.web.session_queries import get_session_turn_history, list_recent_sessions


def build_api_routes(kernel: AgentOSKernel) -> list[Route]:
    """Construct Starlette Route instances for the Agent OS Web API."""
    db_path = kernel.session_repo.db_path

    async def get_health(_request: Request) -> JSONResponse:
        report = kernel.collector.compile_health_report(hours=24)
        return JSONResponse(
            {
                "health_score": report.health_score,
                "error_rate_percent": report.error_rate_percent,
                "avg_latency_ms": report.avg_latency_ms,
                "findings": report.findings,
            }
        )

    async def get_sessions(_request: Request) -> JSONResponse:
        sessions = list_recent_sessions(db_path, limit=50)
        return JSONResponse(sessions)

    async def create_session(request: Request) -> JSONResponse:
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            pass
        title = body.get("title", "New Conversation")
        sess = kernel.session_repo.create_session(title=title)
        return JSONResponse(
            {
                "session_id": sess.session_id,
                "title": sess.title,
                "created_at": sess.created_at.isoformat(),
            }
        )

    async def get_session_turns(request: Request) -> JSONResponse:
        session_id = request.path_params["session_id"]
        turns = get_session_turn_history(db_path, session_id)
        return JSONResponse(turns)

    async def get_ambient_nudges(request: Request) -> JSONResponse:
        session_id = request.query_params.get("session_id", "default")
        nudges = kernel.signaler.poll_ambient_nudges(session_id=session_id)
        return JSONResponse(
            [
                {
                    "nudge_id": n.nudge_id,
                    "session_id": n.session_id,
                    "journey_id": n.journey_id,
                    "status": n.status,
                    "short_notice": n.short_notice,
                    "created_at": n.created_at.isoformat(),
                }
                for n in nudges
            ]
        )

    async def chat_stream(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        session_id = body.get("session_id")
        user_input = body.get("message", "").strip()
        if not session_id or not user_input:
            return JSONResponse(
                {"error": "Both session_id and message are required"}, status_code=400
            )

        req = UserTurnRequest(session_id=session_id, user_input=user_input)

        async def sse_event_generator() -> AsyncGenerator[str, None]:
            try:
                async for event in kernel.stream_user_turn(req):
                    if event.event_type == "delta":
                        yield f"event: delta\ndata: {json.dumps({'delta': event.delta})}\n\n"
                    elif event.event_type == "thinking":
                        t_data = json.dumps({"reasoning": event.reasoning})
                        yield f"event: thinking\ndata: {t_data}\n\n"
                    elif event.event_type == "tool_executed":
                        tool_data = {
                            "tool_name": getattr(event.tool_result, "tool_name", "tool"),
                            "success": getattr(event.tool_result, "success", True),
                        }
                        yield f"event: tool_executed\ndata: {json.dumps(tool_data)}\n\n"
                    elif event.event_type == "status":
                        s_data = json.dumps({"message": event.delta})
                        yield f"event: status\ndata: {s_data}\n\n"
                    elif event.event_type == "job_dispatched":
                        job = event.dispatched_job
                        disp_res = getattr(job, "dispatch_result", None)
                        env = getattr(disp_res, "envelope", None)
                        job_data = {
                            "task": getattr(job, "task", "directive"),
                            "status": getattr(env, "status", "completed") if env else "completed",
                            "summary": getattr(env, "summary", "") if env else "",
                        }
                        yield f"event: job_dispatched\ndata: {json.dumps(job_data)}\n\n"
                    elif event.event_type == "error":
                        err_data = json.dumps({"error": event.error_message})
                        yield f"event: error\ndata: {err_data}\n\n"

                # Check ambient nudges after the turn
                for nudge in kernel.signaler.poll_ambient_nudges(session_id=session_id):
                    n_data = json.dumps({"notice": nudge.short_notice})
                    yield f"event: ambient_nudge\ndata: {n_data}\n\n"

                yield f"event: done\ndata: {json.dumps({'session_id': session_id})}\n\n"
            except Exception as exc:
                yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

        return StreamingResponse(sse_event_generator(), media_type="text/event-stream")

    async def get_mcp_status(_request: Request) -> JSONResponse:
        servers = [
            {"server_id": sid, "tools": kernel.mcp_supervisor.get_server_tools(sid)}
            for sid in kernel.mcp_supervisor.list_connected_servers()
        ]
        proposals = []
        if getattr(kernel, "toolsmith", None):
            for p in kernel.toolsmith.list_proposals():
                proposals.append({
                    "tool_name": p.tool_name,
                    "domain": p.domain,
                    "description": p.description,
                    "verified": p.verified,
                    "dry_run_output": p.dry_run_output,
                    "staged_path": p.staged_path,
                })
        tools = [
            {"name": name, "tier": str(tier.value if hasattr(tier, "value") else tier)}
            for name, tier in kernel._tool_tiers.items()
        ]
        return JSONResponse({"servers": servers, "proposals": proposals, "tools": tools})

    async def connect_mcp_server(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        server_id = body.get("server_id")
        if not server_id:
            return JSONResponse({"error": "server_id is required"}, status_code=400)
        cfg = McpServerConfig(
            server_id=server_id,
            transport=body.get("transport", "stdio"),
            command=body.get("command"),
            args=body.get("args", []),
            url=body.get("url"),
            env=body.get("env", {}),
        )
        try:
            mcp_tools = await kernel.mount_mcp_server(cfg)
            return JSONResponse({
                "server_id": server_id,
                "status": "connected",
                "tools": [t.name for t in mcp_tools],
            })
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    async def activate_proposal(request: Request) -> JSONResponse:
        tool_name = request.path_params["tool_name"]
        try:
            live_tools = await kernel.activate_tool_proposal(tool_name)
            return JSONResponse({
                "status": "activated",
                "tool_name": tool_name,
                "live_tools": [t.name for t in live_tools],
            })
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    async def reject_proposal(request: Request) -> JSONResponse:
        tool_name = request.path_params["tool_name"]
        if getattr(kernel, "toolsmith", None):
            res = kernel.toolsmith.reject_proposal(tool_name)
            return JSONResponse({"status": "rejected" if res else "not_found", "tool_name": tool_name})
        return JSONResponse({"error": "Toolsmith not configured"}, status_code=500)

    return [
        Route("/api/health", get_health, methods=["GET"]),
        Route("/api/sessions", get_sessions, methods=["GET"]),
        Route("/api/sessions", create_session, methods=["POST"]),
        Route("/api/sessions/{session_id}/turns", get_session_turns, methods=["GET"]),
        Route("/api/ambient", get_ambient_nudges, methods=["GET"]),
        Route("/api/chat/stream", chat_stream, methods=["POST"]),
        Route("/api/mcp/status", get_mcp_status, methods=["GET"]),
        Route("/api/mcp/servers", connect_mcp_server, methods=["POST"]),
        Route("/api/mcp/proposals/{tool_name}/activate", activate_proposal, methods=["POST"]),
        Route("/api/mcp/proposals/{tool_name}/reject", reject_proposal, methods=["POST"]),
    ]
