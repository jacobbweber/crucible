"""Slash-command registry and argument parsing helpers."""

import argparse
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agent_os.cli.context import ReplContext

Handler = Callable[[ReplContext, list[str]], Awaitable[None]]


class UsageError(Exception):
    """Raised when a command receives invalid arguments."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise UsageError(f"{message}\n{self.format_usage().strip()}")

    def exit(self, status: int = 0, message: str | None = None) -> None:  # type: ignore[override]
        raise UsageError(message or self.format_help())


def make_parser(prog: str, description: str = "") -> argparse.ArgumentParser:
    """Create an argparse parser that raises UsageError instead of exiting."""
    return _Parser(prog=prog, description=description, add_help=True)


@dataclass
class Command:
    name: str
    summary: str
    handler: Handler


class CommandRegistry:
    """Maps slash-command names to async handlers."""

    def __init__(self) -> None:
        self.commands: dict[str, Command] = {}

    def register(self, name: str, summary: str) -> Callable[[Handler], Handler]:
        def decorator(fn: Handler) -> Handler:
            self.commands[name] = Command(name=name, summary=summary, handler=fn)
            return fn

        return decorator

    async def dispatch(self, ctx: ReplContext, line: str) -> None:
        try:
            tokens = shlex.split(line[1:], posix=True)
        except ValueError as exc:
            ctx.console.error(f"Parse error: {exc}")
            return
        if not tokens:
            return
        cmd = self.commands.get(tokens[0])
        if cmd is None:
            ctx.console.error(f"Unknown command '/{tokens[0]}'. Try /help.")
            return
        try:
            await cmd.handler(ctx, tokens[1:])
        except UsageError as exc:
            ctx.console.warn(str(exc))
