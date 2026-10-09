# ADR-0012: In-Process Tool Compilation & Cancel Scope Resolution

> **Date**: 2026-10-08  
> **Status**: Superseded in part by [ADR-0015](0015-contract-first-ingredients-and-structured-intent-resolution.md) — in-process `exec` of synthesized code is replaced by out-of-process hub execution; schema extraction is replaced by declared contracts.  
> **Deciders**: Human Product Owner, AI Assistant  
> **Context**: How dynamically synthesized FastMCP tools are loaded and executed in-process without crashing async worker threads due to AnyIO cancel scope collisions or cross-thread event loop mismatch.

---

## 1. Context & Problem Statement

When the `ToolsmithWorker` synthesizes a new tool, it writes Python code decorating functions with `@mcp.tool()` into `.agent-os-data/workspace/mcp_servers/hub/hub_server.py`.

In live testing with small local models:
1. **Subprocess Overhead & Windows Stdio Latency**: Running external MCP servers as separate subprocesses over stdio on Windows introduced connection timeouts, zombie processes, and high latency during ephemeral single-turn tool calls.
2. **AnyIO Cancel Scope Collision**: When calling FastMCP tools in-process from within an asynchronous runner (such as `ReActRunner` running inside an AnyIO event loop thread), invoking synchronous or nested async FastMCP functions triggered `RuntimeError: cancel scope stack corrupted` or cross-thread loop deadlocks.
3. **Parameter Omission**: Initial dynamic tool loaders created `ToolDefinition(name=..., parameters=[])` without extracting parameters from the compiled function's Python signature. This stripped typed JSON schemas from the ReAct runner prompt, leading the model to believe the tool accepted no arguments (`Parameters: None`).

---

## 2. Decision Drivers

* **Sub-Millisecond In-Process Execution**: Synthesized tools must execute inside the master runtime with minimal overhead and zero child process management friction.
* **Deterministic Event Loop Isolation**: Tool execution must run safely without corrupting the surrounding AnyIO cancel scope or event loop stack.
* **Typed JSON Schema Preservation**: Dynamic tools must reflect exact Python function signatures (argument names, types, default values, and docstrings) in their tool schemas.
* **Parameter Alias Normalization**: Accommodate minor argument naming mismatches from local models (e.g. `path` vs `drive_path` vs `target_path`) transparently before dispatch.

---

## 3. Decision Outcome

We implemented the following design in `src/agent_os/mcp/hub.py` and `src/agent_os/kernel/tool_invoker.py`:

1. **In-Process Python Module Compilation**:
   - `McpHubManager.load_persisted_tools()` dynamically loads `hub_server.py` using `importlib.util.spec_from_file_location`.
   - Iterates over decorated tool functions directly in memory.
2. **Parameter Signature Extraction**:
   - Uses `inspect.signature(fn)` to extract each argument's name, type annotation, default value, and docstring into a typed `ToolParameterSchema`.
   - Populates `ToolDefinition(name=..., parameters=extracted_params)`.
3. **Thread-Safe Scope Isolation (`tool_invoker.py`)**:
   - Tool execution is wrapped in a dedicated thread executor (`asyncio.to_thread` or clean synchronous dispatch) to ensure AnyIO cancel scopes in the parent ReAct loop are never corrupted.
4. **Parameter Alias Normalization**:
   - If a tool requires `path` but the model calls `drive_path`, `target_path`, or `dir_path`, the tool invoker maps the alias to the canonical parameter name before execution.

---

## 4. Consequences

### Positive
* In-process execution is virtually instantaneous (<10ms).
* ReAct models receive full parameter documentation and types in the system prompt.
* No AnyIO cancel scope collisions or cross-thread crashes.

### Negative / Trade-offs
* In-process execution runs with the permissions of the Crucible process. Untrusted third-party code must be dry-run tested and verified by the Toolsmith dry-run gate before loading.
