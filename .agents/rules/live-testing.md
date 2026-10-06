# Live Model Testing Rules

## 1. Multi-Target Requirement
- Every live test (REPL probes, experiments, phase exit checks) must run against **all** configured model targets, never just one.
- Targets are defined as local, gitignored profile files named `.env.target.<name>` in the repository root (copy `.env.example`). Each profile sets its own endpoint, model name, thinking control, and an isolated `AGENT_OS_DATA_DIR`.
- Never commit target profiles: they contain host-specific endpoints.

## 2. Running the Matrix
- Replay a probe script across every target with `uv run python scripts/live_matrix.py <probe-script.txt>`.
- Report results side by side per target (latency, token usage, correctness, failures). Treat a behavioral difference between targets as a finding in its own right.

## 3. Hermetic Unit Tests
- Unit and integration tests under `tests/` must stay hermetic: mock adapters only, and never read a local `.env` or target profile.
