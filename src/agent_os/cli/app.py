"""Entry point for the agent-os developer REPL."""

import argparse
import asyncio
import sys

from agent_os.bootstrap import build_runtime
from agent_os.cli.commands import build_registry
from agent_os.cli.context import Console, ReplContext, TraceConsole
from agent_os.cli.registry import CommandRegistry
from agent_os.domain.config import AppConfig
from agent_os.domain.kernel import KernelConfig, UserTurnRequest


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="agent-os", description="agent-os developer REPL")
    p.add_argument("--env-file", default=None, help="target profile, e.g. .env.target.qwen")
    p.add_argument("--data-dir", default=None, help="override data directory")
    p.add_argument("--session", default=None, help="resume an existing session id")
    p.add_argument("--trace", action="store_true", help="start with model tracing on")
    p.add_argument("--think", choices=["on", "off", "default"], default=None)
    p.add_argument("--policy", default="balanced", choices=["strict", "balanced", "autonomous"])
    p.add_argument("--name", default="Companion", help="companion display name")
    p.add_argument("--mcp", action="store_true", help="run headless as an MCP server")
    p.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport protocol (default: stdio)",
    )
    p.add_argument("--host", default=None, help="Host binding (default: from .env or 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="MCP SSE port (default: 8000)")
    p.add_argument("--ui", action="store_true", help="run the local companion Web UI")
    p.add_argument(
        "--ui-port", type=int, default=None, help="Web UI port (default: from .env or 3000)"
    )
    return p.parse_args(argv)


async def _chat_turn(ctx: ReplContext, text: str) -> None:
    req = UserTurnRequest(session_id=ctx.session_id, user_input=text)
    response_chunks: list[str] = []
    is_tracing = ctx.runtime.tracer.enabled
    async for event in ctx.kernel.stream_user_turn(req):
        if event.event_type == "delta":
            if not is_tracing:
                sys.stdout.write(event.delta)
                sys.stdout.flush()
            response_chunks.append(event.delta)
        elif event.event_type == "job_dispatched":
            job = event.dispatched_job
            job_desc = getattr(job, "task", "job") if job else "job"
            ctx.console.info(f"\n⚡ Dispatched background job: {job_desc}")
        elif event.event_type == "tool_executed":
            tool_res = event.tool_result
            tool_name = getattr(tool_res, "tool_name", "tool") if tool_res else "tool"
            ctx.console.info(f"\n🔧 Tool executed: {tool_name}")
        elif event.event_type == "error":
            ctx.console.error(f"\nturn error: {event.error_message}")
    if response_chunks:
        if not is_tracing:
            sys.stdout.write("\n")
            sys.stdout.flush()
    else:
        ctx.console.write("(empty response)", "dim")
    for nudge in ctx.kernel.signaler.poll_ambient_nudges(session_id=ctx.session_id):
        ctx.console.warn(f"🔔 {nudge.short_notice}")


async def _loop(ctx: ReplContext, registry: CommandRegistry) -> None:
    interactive = sys.stdin.isatty()
    while ctx.running:
        try:
            line = await asyncio.to_thread(input, "you> " if interactive else "")
        except EOFError:
            break
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not interactive:
            ctx.console.write(f"you> {line}", "cyan")
        try:
            if line.startswith("/"):
                await registry.dispatch(ctx, line)
            else:
                await _chat_turn(ctx, line)
        except Exception as exc:  # keep the REPL alive while surfacing failures
            ctx.console.error(f"{type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> None:
    """Bootstrap the runtime and start the REPL."""
    args = _parse_args(argv)
    console = Console()
    app_config = AppConfig.from_env_file(args.env_file) if args.env_file else AppConfig()
    if args.think:
        app_config.vllm_enable_thinking = {"on": True, "off": False}.get(args.think)

    runtime = build_runtime(
        app_config=app_config,
        data_dir=args.data_dir,
        kernel_config=KernelConfig(
            storage_root="",
            companion_name=args.name,
            approval_mode=args.policy,
            context_window=app_config.vllm_context_window,
        ),
        trace_sink=TraceConsole(console),
    )
    runtime.tracer.enabled = args.trace
    session_id = args.session or runtime.kernel.session_repo.create_session("REPL").session_id

    if args.mcp:
        from agent_os.mcp.transport import run_mcp_server

        console.info(
            f"agent-os MCP gateway | data={runtime.data_dir} | transport={args.transport} "
            f"| node={args.name}"
        )
        mcp_host = args.host or "127.0.0.1"
        asyncio.run(
            run_mcp_server(
                kernel=runtime.kernel,
                transport=args.transport,
                host=mcp_host,
                port=args.port,
                name=args.name,
            )
        )
        return

    if args.ui:
        from agent_os.web.runner import run_web_server

        ui_host = args.host or app_config.web_host
        ui_port = args.ui_port or app_config.web_port
        console.info(f"agent-os Web UI | data={runtime.data_dir} | http://{ui_host}:{ui_port}")
        run_web_server(kernel=runtime.kernel, host=ui_host, port=ui_port)
        return

    console.info(f"agent-os REPL | data={runtime.data_dir}")
    console.info(
        f"model={app_config.vllm_model_name} @ {app_config.vllm_base_url} "
        f"thinking={app_config.vllm_enable_thinking} policy={args.policy}"
    )
    console.info(f"session={session_id} | /help for commands")
    ctx = ReplContext(runtime=runtime, console=console, session_id=session_id)
    asyncio.run(_loop(ctx, build_registry()))


if __name__ == "__main__":
    main()
