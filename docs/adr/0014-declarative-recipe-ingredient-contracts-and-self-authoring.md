# ADR-0014: Declarative Recipe Ingredient Contracts & Autonomous Self-Authoring

> **Date**: 2026-10-09  
> **Status**: Superseded by [ADR-0015](0015-contract-first-ingredients-and-structured-intent-resolution.md) — the ingredient contract in §3.1 was never implemented; the self-authoring tool primitives (§3.2) remain valid and are carried forward.  
> **Deciders**: Human Product Owner, AI Assistant  
> **Context**: How recipes serve as declarative playbooks (combining tools, models, context, and runbooks as modular ingredients) and how Crucible is given the autonomous primitives to inspect, create, modify, and retire its own capabilities.

---

## 1. Context & Problem Statement

To achieve the vision of **one lifelong companion with zero-friction capability evolution**, the system must overcome two major design bottlenecks:
1. **Monolithic & Hardcoded Configurations**:
   - In traditional architectures, model selection, tool bindings, context retrieval, and execution policies are hardcoded into rigid Python classes or scattered config files.
   - Adding a new capability requires modifying source code, adding dedicated routers, and restarting the service.
2. **The "Self-Healing Litmus Test" Failure**:
   - If Crucible encounters an issue with one of its own tools (e.g. a parameter typo, a deprecated API, or an outdated recipe), it currently lacks the primitives to inspect, refactor, or retire that tool on its own.
   - The user is forced into "hands-on fixing mode," acting as developer and debugger rather than a companion.

---

## 2. Decision Drivers

* **Ansible-Like Playbook Architecture**: Recipes must act like declarative Ansible playbooks and inventories. A recipe is not just a tool list; it binds the exact **ingredients** needed for a task:
  - **Tools**: Required executable capabilities and typed parameter schemas.
  - **Model & Routing**: Model tier, provider, reasoning effort, temperature, and token budget.
  - **Context Sources**: Targeted memory facts, wiki folders, or system environment state.
  - **Runbook**: Execution engine (`react`, `stategraph`, `pev`), instructions, and verification criteria.
* **Autonomous Capability Lifecycle (The Litmus Test)**: Crucible must have the built-in primitives to perform full CRUD on its recipes and lifecycle operations on its tools (`inspect`, `refactor`, `retire`).
* **Strict Two-Tier Boundaries**:
  - **Userland (Evolvable)**: Tools in `.agent-os-data/workspace/mcp_servers/hub/`, recipes in `recipes.db`, and wiki notes can be autonomously authored, modified, and deleted by the agent.
  - **Kernel Core (Protected)**: Core runtime code in `src/agent_os/` remains immutable, deterministic, and sandboxed.
* **Non-Technical User Experience**: The companion manages ingredients under the hood. The user simply asks for an outcome, and Crucible orchestrates, assembles, or heals the ingredients autonomously.

---

## 3. Decision Outcome

We define the declarative recipe schema and autonomous capability suite:

### 3.1 Declarative Ingredient Contract

```json
{
  "recipe_id": "host_filesystem_inspection",
  "name": "Host Filesystem Inspection",
  "description": "Lists contents and inspects metadata of host filesystem drives and directories.",
  "ingredients": {
    "tools": [
      {
        "name": "list_drive_contents",
        "parameters": {
          "path": {"type": "string", "default": "C:\\", "description": "Absolute filesystem path to inspect"}
        }
      }
    ],
    "model_routing": {
      "tier": "fast_local",
      "model": "qwen3.8:latest",
      "reasoning_effort": "none",
      "max_tokens": 1024
    },
    "context_sources": [
      {"type": "system_info", "scope": "mounted_drives"}
    ],
    "runbook": {
      "engine": "react",
      "max_turns": 5,
      "verification_criteria": "Directory listing must include item names, sizes, or type markers."
    }
  },
  "intent_tags": ["filesystem", "directory", "disk", "drive", "storage", "list"]
}
```

### 3.2 Autonomous Self-Authoring Primitives

To pass the Litmus Test, Crucible is equipped with two dedicated management suites:

1. **Recipe Management Tool Suite (`RecipeToolSuite`)**:
   - `recipe_list(filter_tag: Optional[str]) -> List[RecipeSummary]`
   - `recipe_get(recipe_id: str) -> RecipeDefinition`
   - `recipe_upsert(recipe: RecipeDefinition) -> bool`
   - `recipe_delete(recipe_id: str) -> bool`
2. **Tool Lifecycle Primitives (`ToolsmithWorker` / `McpHubManager`)**:
   - `tool_inspect(tool_name: str) -> ToolSourceCode`
   - `tool_refactor(tool_name: str, new_code: str) -> RefactorResult` (with automated pre-flight dry-run verification before overwriting `hub_server.py`)
   - `tool_retire(tool_name: str) -> bool` (cleans up AST and imports from `hub_server.py`)

---

## 4. Consequences

### Positive
* Crucible can self-heal: if a tool has a bad parameter, Crucible can inspect its code, refactor it, dry-run test the fix, and mount the updated version without human code intervention.
* Recipes become portable, declarative runbooks that can be shared, backed up, or fine-tuned.
* Model routing and context scopes are decoupled from hardcoded Python code.

### Negative / Trade-offs
* Tool refactoring modifies `hub_server.py` at runtime; AST parsing and AST replacement must be robust to avoid corrupting other tools in the file.
* Requires pre-flight dry-run tests to run in an isolated subprocess before committing changes to active memory.
