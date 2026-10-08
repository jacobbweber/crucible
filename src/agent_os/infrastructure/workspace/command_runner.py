"""Sandboxed command runner with secret scrubbing, dangerous command filters, and byte limits."""

import asyncio
import os
import re
import time
from pathlib import Path

from agent_os.domain.workspace import CommandExecutionResult, WorkspaceConfig


class SandboxedCommandRunner:
    """Executes system commands within workspace boundaries with strict security scrubbing."""

    # Keywords that must NEVER leak into child execution environments
    SENSITIVE_ENV_PATTERN = re.compile(
        r"(KEY|TOKEN|SECRET|PASSWORD|AUTH|CREDENTIAL|PRIVATE|API_KEY)",
        re.IGNORECASE,
    )

    # Catastrophic command patterns blocked unconditionally
    DANGEROUS_PATTERNS = [
        re.compile(r"\brm\s+-(?:r[fF]|f[rR])\s+[/~]", re.IGNORECASE),
        re.compile(r"\bmkfs\b", re.IGNORECASE),
        re.compile(r"\bformat\s+[a-zA-Z]:", re.IGNORECASE),
        re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:", re.IGNORECASE),
        re.compile(r"\bdd\s+if=.*?\s+of=/dev/", re.IGNORECASE),
        re.compile(r"\bshutdown\b", re.IGNORECASE),
    ]

    SAFE_ENV_ALLOWLIST = {
        "PATH",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "USER",
        "USERNAME",
        "HOME",
        "HOMEPATH",
        "HOMEDRIVE",
        "PYTHONPATH",
        "COMSPEC",
        "PATHEXT",
    }

    def __init__(self, config: WorkspaceConfig) -> None:
        self.config = config
        self.root_dir = config.root_dir.resolve()

    def build_clean_environment(self, extra_env: dict[str, str] | None = None) -> dict[str, str]:
        """Scrub ambient environment variables to prevent secret leakage to child processes."""
        clean_env: dict[str, str] = {}

        # Preserve safe system variables
        for key, val in os.environ.items():
            upper_k = key.upper()
            if upper_k in self.SAFE_ENV_ALLOWLIST:
                if not self.SENSITIVE_ENV_PATTERN.search(key):
                    clean_env[key] = val

        # Ensure Python unbuffered stdout
        clean_env["PYTHONUNBUFFERED"] = "1"

        if extra_env:
            for k, v in extra_env.items():
                if not self.SENSITIVE_ENV_PATTERN.search(k):
                    clean_env[k] = v

        return clean_env

    def validate_command_safety(self, command: str) -> None:
        """Reject dangerous or catastrophic commands unconditionally."""
        trimmed = command.strip()
        for pat in self.DANGEROUS_PATTERNS:
            if pat.search(trimmed):
                raise PermissionError(f"Command rejected by safety gate: matches forbidden pattern '{pat.pattern}'")

    async def run(
        self,
        command: str,
        relative_cwd: str = ".",
        timeout_seconds: int | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> CommandExecutionResult:
        """Execute a shell command within the workspace with timeout and output clamping."""
        self.validate_command_safety(command)

        work_dir = (self.root_dir / relative_cwd.strip().lstrip("/\\")).resolve()
        try:
            work_dir.relative_to(self.root_dir)
        except ValueError as exc:
            raise PermissionError(f"CWD '{relative_cwd}' traverses outside workspace root.") from exc

        if not work_dir.exists():
            work_dir.mkdir(parents=True, exist_ok=True)

        timeout = timeout_seconds or self.config.default_timeout_seconds
        clean_env = self.build_clean_environment(extra_env)
        start_time = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(work_dir),
                env=clean_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            raw_stdout, raw_stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(timeout),
            )
            duration_ms = (time.monotonic() - start_time) * 1000.0

            max_bytes = self.config.max_output_bytes
            stdout_text = raw_stdout.decode("utf-8", errors="replace")
            stderr_text = raw_stderr.decode("utf-8", errors="replace")

            truncated = False
            if len(stdout_text.encode("utf-8")) > max_bytes:
                stdout_text = stdout_text[: max_bytes // 2] + "\n... [TRUNCATED] ..."
                truncated = True
            if len(stderr_text.encode("utf-8")) > max_bytes:
                stderr_text = stderr_text[: max_bytes // 2] + "\n... [TRUNCATED] ..."
                truncated = True

            return CommandExecutionResult(
                exit_code=proc.returncode if proc.returncode is not None else -1,
                stdout=stdout_text,
                stderr=stderr_text,
                duration_ms=round(duration_ms, 2),
                timed_out=False,
                truncated=truncated,
            )

        except TimeoutError:
            duration_ms = (time.monotonic() - start_time) * 1000.0
            try:
                proc.kill()
            except Exception:
                pass
            return CommandExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {timeout} seconds.",
                duration_ms=round(duration_ms, 2),
                timed_out=True,
            )
