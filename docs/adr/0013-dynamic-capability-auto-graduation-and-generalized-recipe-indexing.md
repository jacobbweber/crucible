# ADR-0013: Dynamic Capability Auto-Graduation & Generalized Recipe Indexing

> **Date**: 2026-10-09  
> **Status**: Accepted  
> **Deciders**: Human Product Owner, AI Assistant  
> **Context**: How Crucible automatically promotes successfully synthesized tools into reusable, generalized recipes so the system learns from its own successes and never repeats expensive synthesis loops.

---

## 1. Context & Problem Statement

When Crucible successfully synthesized a tool to satisfy a specific user query (e.g. `list the contents of the D drive`), the synthesized tool existed only as a low-level Python function in `hub_server.py`.

On the next turn, when the user asked to `list the contents of the M drive`:
1. The system did not have a matching recipe for the `M` drive because the previous interaction was tied specifically to `D`.
2. The capability scout was re-triggered, wasting 20 seconds of LLM inference re-evaluating whether a new tool was needed.
3. This violated the core user expectation: **a directory listing capability is generic and parameterized by path, not hardcoded to a specific drive letter**.

---

## 2. Decision Drivers

* **Zero Repetitive Synthesis**: Once Crucible creates a capability for an operational domain (e.g. filesystem inspection), it must never re-synthesize it for variations in input parameters.
* **Autonomous Auto-Graduation**: Successful tool execution must trigger automatic recipe generation and persistence without requiring user prompting or developer intervention.
* **Generalized Intent Indexing**: Recipes must be tagged with broad semantic intent tags (e.g., `["filesystem", "directory", "disk", "drive", "storage", "inspection", "list"]`) and typed parameters (`path: str`).
* **Sub-Second Stage-1 Recall**: Subsequent queries across different paths or targets must match the graduated recipe in Stage 1 triage and execute in $\le 1$s.

---

## 3. Decision Outcome

We implemented auto-graduation in `src/agent_os/kernel/pipeline.py` and generalized matching in `recipe_triage.py`:

1. **Auto-Graduation Hook (`pipeline.py`)**:
   - When a job completes using an ephemeral synthesized tool, the pipeline inspects the generated tool definition.
   - If the tool is verified and executed successfully, Crucible generates a generalized `RecipeDefinition` (e.g., `host_filesystem_inspection`) with:
     - `required_tools = [tool_name]`
     - Broad intent tags covering the capability domain.
     - A clean parameter schema (`path: str = "C:\\"`).
   - The recipe is saved to `recipes.db` via `RecipeRepository.save()`.
2. **Generalized Triage Matching (`recipe_triage.py`)**:
   - `triage_capability_gap()` checks if any mounted or synthesized tool provides coverage for the domain.
   - For filesystem operations, if any directory or drive inspection tool is mounted, Stage 1 immediately mounts the generalized recipe and dispatches directly to the ReAct runner, bypassing the LLM capability scout.

---

## 4. Consequences

### Positive
* Asking for `D:\` creates the tool and recipe.
* Asking for `M:\`, `C:\Users`, or `E:\` immediately reuses the graduated recipe in $\le 1$ second.
* The system builds a persistent library of capabilities that expands organically with every user interaction.

### Negative / Trade-offs
* If a synthesized tool has edge-case bugs (e.g. failing on network shares or symlinks), the auto-graduated recipe will carry that tool until refactored or retired.
