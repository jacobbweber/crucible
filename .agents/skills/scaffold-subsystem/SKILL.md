---
name: scaffold-subsystem
description: >-
  Use this skill when scaffolding a new subsystem, context-isolated agent runtime,
  or tool integration within the agent-os ecosystem.
---

# Scaffolding an Agent-OS Subsystem

Follow this procedural runbook when introducing a new subsystem, agent module, or tool provider to ensure compliance with agent-os isolation and architectural standards.

---

## Workflow Steps

### Step 1: Define Module Boundaries and Interfaces
1. Identify the subsystem's role (e.g., storage engine, agent dispatcher, tool provider, or protocol bridge).
2. Define a clean interface contract with strict types and schemas.
3. Ensure no global mutable state is introduced.

### Step 2: Implement Context Isolation
1. Ensure the subsystem accepts an explicit execution context (e.g., task ID, isolated workspace path, cancellation token).
2. Validate that resource cleanup (open file handles, subprocesses, database locks) is guaranteed via context managers or explicit `close`/`cleanup` methods.

### Step 3: Implement Error Handling & Logging
1. Define custom, typed error exceptions for domain-specific failure modes.
2. Ensure failure does not panic or crash the supervising process.
3. Add structured logging at key lifecycle events (`start`, `execute`, `complete`, `error`).

### Step 4: Verify with Static Typing & Smoke Execution
1. Run `uv run pyright` to verify strict typing contracts without writing brittle test code.
2. Run `uv run ruff check` to ensure formatting and lint standards.
3. Validate runtime integration by executing a real, unmocked smoke scenario or test suite.
4. Only add targeted unit tests for pure, deterministic business logic where regression risk is genuinely high.

