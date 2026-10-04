"""Infrastructure configuration and environment resolver."""

import os
from pathlib import Path


def resolve_data_dir(cli_dir: str | Path | None = None) -> Path:
    """Resolve and ensure the data directory for agent-os.

    Precedence order:
    1. CLI argument (`cli_dir`).
    2. `AGENT_OS_DATA_DIR` environment variable.
    3. Default fallback: `~/.local-agent-os`.
    """
    if cli_dir is not None:
        target = Path(cli_dir).expanduser().resolve()
    elif "AGENT_OS_DATA_DIR" in os.environ:
        target = Path(os.environ["AGENT_OS_DATA_DIR"]).expanduser().resolve()
    else:
        target = (Path.home() / ".local-agent-os").resolve()

    target.mkdir(parents=True, exist_ok=True)
    return target
