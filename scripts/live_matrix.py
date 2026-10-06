"""Replay a REPL probe script against every configured model target, side by side.

Usage:
    uv run python scripts/live_matrix.py <probe.txt> [--targets name1,name2] [extra REPL args]

Targets are local, gitignored profiles named `.env.target.<name>` in the repository root.
Targets run concurrently; each transcript is printed and saved under .agent-os-data/matrix/.
"""

import argparse
import io
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def discover_targets(selected: str | None) -> dict[str, Path]:
    """Map target name -> profile path, optionally filtered by a comma list."""
    found = {p.name.removeprefix(".env.target."): p for p in REPO_ROOT.glob(".env.target.*")}
    if selected:
        wanted = [s.strip() for s in selected.split(",") if s.strip()]
        missing = [w for w in wanted if w not in found]
        if missing:
            sys.exit(f"Unknown target(s): {missing}. Available: {sorted(found)}")
        return {w: found[w] for w in wanted}
    return dict(sorted(found.items()))


def run_target(name: str, profile: Path, probe: str, extra: list[str]) -> tuple[str, str, float]:
    """Run one REPL session for a target and return (name, transcript, seconds)."""
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "agent_os.cli.app", "--env-file", str(profile), *extra],
        input=probe,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return name, proc.stdout + proc.stderr, time.monotonic() - started


def main() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", type=Path)
    parser.add_argument("--targets", default=None)
    args, extra = parser.parse_known_args()

    targets = discover_targets(args.targets)
    if not targets:
        sys.exit("No .env.target.* profiles found in the repository root.")
    probe = args.probe.read_text(encoding="utf-8")
    out_dir = REPO_ROOT / ".agent-os-data" / "matrix" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = [pool.submit(run_target, n, p, probe, extra) for n, p in targets.items()]
        results = [f.result() for f in futures]

    for name, transcript, seconds in results:
        (out_dir / f"{name}.log").write_text(transcript, encoding="utf-8")
        print(f"\n{'=' * 30} TARGET: {name} ({seconds:.1f}s) {'=' * 30}")
        print(transcript)
    print(f"\nTranscripts saved to {out_dir.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
