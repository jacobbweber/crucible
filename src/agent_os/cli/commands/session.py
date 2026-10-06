"""Session, tracing, and raw-inspection commands."""

from agent_os.cli.context import ReplContext
from agent_os.cli.registry import CommandRegistry, UsageError
from agent_os.cli.sqlite_view import list_tables, open_readonly, query, truncate_row


def register(reg: CommandRegistry) -> None:
    @reg.register("help", "List commands")
    async def _help(ctx: ReplContext, args: list[str]) -> None:
        ctx.console.info("Plain text = chat turn. Slash commands (add -h for usage):")
        for name, cmd in sorted(reg.commands.items()):
            ctx.console.write(f"  /{name:<10} {cmd.summary}")

    @reg.register("quit", "Exit the REPL")
    async def _quit(ctx: ReplContext, args: list[str]) -> None:
        ctx.running = False

    @reg.register("trace", "Toggle model traffic tracing: /trace [on|off]")
    async def _trace(ctx: ReplContext, args: list[str]) -> None:
        tracer = ctx.runtime.tracer
        tracer.enabled = (args[0] == "on") if args else not tracer.enabled
        ctx.console.ok(f"trace = {'on' if tracer.enabled else 'off'}")

    @reg.register("think", "Reasoning-model thinking: /think [on|off|default]")
    async def _think(ctx: ReplContext, args: list[str]) -> None:
        cfg = ctx.runtime.app_config
        if args:
            cfg.vllm_enable_thinking = {"on": True, "off": False}.get(args[0])
        ctx.console.ok(f"enable_thinking = {cfg.vllm_enable_thinking} (None = server default)")

    @reg.register("session", "Show/switch sessions: /session [new [title]|list|<id>]")
    async def _session(ctx: ReplContext, args: list[str]) -> None:
        repo = ctx.kernel.session_repo
        if not args:
            ctx.console.info(f"active session: {ctx.session_id}")
            ctx.console.json(repo.get_session(ctx.session_id))
        elif args[0] == "new":
            ctx.session_id = repo.create_session(" ".join(args[1:]) or "REPL Session").session_id
            ctx.console.ok(f"switched to new session {ctx.session_id}")
        elif args[0] == "list":
            with open_readonly(ctx.runtime.data_dir, "session") as conn:
                rows = query(
                    conn,
                    "SELECT s.session_id, s.title, s.updated_at, COUNT(t.turn_id) AS turns "
                    "FROM sessions s LEFT JOIN turns t USING(session_id) "
                    "GROUP BY s.session_id ORDER BY s.updated_at DESC LIMIT 20",
                )
            ctx.console.json(rows)
        else:
            if repo.get_session(args[0]) is None:
                ctx.console.warn(f"session {args[0]} does not exist (switching anyway)")
            ctx.session_id = args[0]
            ctx.console.ok(f"switched to {ctx.session_id}")

    @reg.register("history", "Show recent turns: /history [n]")
    async def _history(ctx: ReplContext, args: list[str]) -> None:
        limit = int(args[0]) if args else 10
        for t in ctx.kernel.session_repo.get_recent_turns(ctx.session_id, limit=limit):
            ctx.console.write(f"#{t.turn_index} [{t.role}] ", "cyan", end="")
            ctx.console.write(t.content)

    @reg.register("db", "Read-only DB view: /db <session|facts|recipes|education|vault> [table]")
    async def _db(ctx: ReplContext, args: list[str]) -> None:
        if not args:
            raise UsageError("usage: /db <db> [table] [limit]")
        with open_readonly(ctx.runtime.data_dir, args[0]) as conn:
            if len(args) == 1:
                ctx.console.json(list_tables(conn))
                return
            table = args[1]
            if table not in list_tables(conn):
                raise UsageError(f"no table '{table}'")
            limit = int(args[2]) if len(args) > 2 else 10
            rows = query(conn, f'SELECT * FROM "{table}" ORDER BY rowid DESC LIMIT ?', (limit,))
        ctx.console.json([truncate_row(r) for r in rows])
