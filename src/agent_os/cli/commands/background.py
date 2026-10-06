"""Scheduler, signaling, and wiki inspection commands."""

from datetime import UTC, datetime, timedelta

from agent_os.cli.context import ReplContext
from agent_os.cli.registry import CommandRegistry, UsageError, make_parser
from agent_os.domain.schedule import ScheduledRoutine
from agent_os.kernel.scheduler import compute_next_run

_routine_parser = make_parser("/routine add")
_routine_parser.add_argument("routine_id")
_routine_parser.add_argument("cron", help='e.g. "*/5 * * * *", @hourly, "@interval 60"')
_routine_parser.add_argument("task", nargs="+")
_routine_parser.add_argument(
    "--policy", default="run_once_immediately",
    choices=["run_once_immediately", "skip_to_next", "queue_all"],
)
_routine_parser.add_argument("--due-in", type=int, default=None, help="minutes (negative=overdue)")


def register(reg: CommandRegistry) -> None:
    @reg.register("routine", "Routines: /routine add <id> <cron> <task...> [--due-in M] | list")
    async def _routine(ctx: ReplContext, args: list[str]) -> None:
        sched = ctx.kernel.scheduler
        if not args or args[0] not in ("add", "list"):
            raise UsageError("usage: /routine add -h | list")
        if args[0] == "add":
            ns = _routine_parser.parse_args(args[1:])
            now = datetime.now(UTC)
            next_run = (
                now + timedelta(minutes=ns.due_in)
                if ns.due_in is not None
                else compute_next_run(ns.cron, now)
            )
            sched.register_routine(ScheduledRoutine(
                routine_id=ns.routine_id, name=ns.routine_id, cron_expression=ns.cron,
                task_payload=" ".join(ns.task), catch_up_policy=ns.policy,
                next_run_at=next_run,
            ))
            ctx.console.ok(f"registered {ns.routine_id}, next_run_at={next_run.isoformat()}")
            return
        for r in sched.list_routines():
            ctx.console.write(
                f"{r.routine_id} cron='{r.cron_expression}' active={r.is_active} "
                f"next={r.next_run_at} last={r.last_run_at} policy={r.catch_up_policy}"
            )

    @reg.register("tick", "Run a scheduler tick: /tick [+minutes offset]")
    async def _tick(ctx: ReplContext, args: list[str]) -> None:
        now = datetime.now(UTC) + timedelta(minutes=int(args[0]) if args else 0)
        logs = await ctx.kernel.trigger_scheduler_tick(now)
        if not logs:
            ctx.console.dim(f"nothing due at {now.isoformat()}")
        for log in logs:
            style = "green" if log.status == "success" else "red"
            ctx.console.write(f"{log.routine_id}: {log.status} {log.error_message or ''}", style)

    @reg.register("signals", "Inspect signaling: /signals [nudges|pending [session_id]]")
    async def _signals(ctx: ReplContext, args: list[str]) -> None:
        sig = ctx.kernel.signaler
        if args and args[0] == "nudges":
            ctx.console.json([n.model_dump() for n in sig.poll_ambient_nudges()])
            return
        sid = args[1] if len(args) > 1 else ctx.session_id
        for key in (sid, "system_scheduler"):
            buf = sig.get_deferred_buffer(key)
            ctx.console.info(f"pending for {key}: {len(buf.pending_envelopes)}")
            for env in buf.pending_envelopes:
                ctx.console.write(f"  [{env.status}] {env.journey_id}: {env.summary[:120]}")
        ctx.console.dim(f"ambient nudges queued: {len(sig._nudge_queue)} (global)")

    @reg.register("wiki", "Show wiki vault tree on disk")
    async def _wiki(ctx: ReplContext, args: list[str]) -> None:
        root = ctx.kernel.wiki_store.root_dir
        ctx.console.info(str(root))
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            indent = "  " * (len(rel.parts) - 1)
            ctx.console.write(f"{indent}{rel.name}{'/' if path.is_dir() else ''}")
