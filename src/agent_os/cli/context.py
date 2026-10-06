"""Console rendering helpers and the shared REPL context."""

import json
import os
import sys
from dataclasses import dataclass
from typing import Any

from agent_os.bootstrap import Runtime
from agent_os.kernel.master_kernel import AgentOSKernel

_CODES = {
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "magenta": "\033[35m",
    "bold": "\033[1m",
}
_RESET = "\033[0m"


class Console:
    """Minimal ANSI console writer."""

    def __init__(self) -> None:
        if os.name == "nt":
            os.system("")  # enables VT escape processing on legacy Windows consoles
        try:
            reconfig_out = getattr(sys.stdout, "reconfigure", None)
            if callable(reconfig_out):
                reconfig_out(encoding="utf-8", errors="replace")
            reconfig_err = getattr(sys.stderr, "reconfigure", None)
            if callable(reconfig_err):
                reconfig_err(encoding="utf-8", errors="replace")
        except Exception:
            pass

    def write(self, text: str, style: str | None = None, end: str = "\n") -> None:
        prefix = _CODES.get(style or "", "")
        sys.stdout.write(f"{prefix}{text}{_RESET if prefix else ''}{end}")
        sys.stdout.flush()

    def info(self, text: str) -> None:
        self.write(text, "cyan")

    def ok(self, text: str) -> None:
        self.write(text, "green")

    def warn(self, text: str) -> None:
        self.write(text, "yellow")

    def error(self, text: str) -> None:
        self.write(text, "red")

    def dim(self, text: str) -> None:
        self.write(text, "dim")

    def json(self, data: Any) -> None:
        self.write(json.dumps(data, indent=2, default=str))


class TraceConsole:
    """Trace sink that renders model traffic with labelled, colour-coded sections."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self._mode: str | None = None

    def __call__(self, kind: str, text: str) -> None:
        if kind == "request":
            self._mode = None
            self.console.write(f"\n┌─ MODEL REQUEST {text.splitlines()[0]}", "magenta")
            self.console.dim("\n".join(text.splitlines()[1:]))
            return
        if kind == "end":
            self._mode = None
            self.console.write(f"\n└─ END {text}", "magenta")
            return
        if kind != self._mode:
            label = "│ reasoning ▸ " if kind == "reasoning" else "│ response ▸ "
            self.console.write(f"\n{label}", "magenta", end="")
            self._mode = kind
        self.console.write(text, "dim" if kind == "reasoning" else "green", end="")


@dataclass
class ReplContext:
    """Mutable state shared across REPL command handlers."""

    runtime: Runtime
    console: Console
    session_id: str
    running: bool = True

    @property
    def kernel(self) -> AgentOSKernel:
        return self.runtime.kernel
