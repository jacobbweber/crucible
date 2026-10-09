# ADR-0011: Zero-Catalog Semantic Triage & Anti-Hijack Capability Scouting

> **Date**: 2026-10-08  
> **Status**: Superseded by [ADR-0015](0015-contract-first-ingredients-and-structured-intent-resolution.md) — implementation retained keyword/regex triage (`recipe_triage.py`) contrary to this ADR's drivers.  
> **Deciders**: Human Product Owner, AI Assistant  
> **Context**: How Crucible detects missing capabilities and dispatches to tool synthesis without fragile regex keyword matching or monolithic catalog bloat, while protecting against conversational prompt hijacking.

---

## 1. Context & Problem Statement

In early iterations of Crucible and AutoReiv, capability discovery suffered from two opposing failure modes:
1. **Catalog Bloat & Prompt Sluggishness**: Mounting dozens of pre-baked tools into every conversation bloated context windows, degraded small local LLM reasoning, and increased latency.
2. **Fragile Regex Gatekeeping**: Using regex pattern matching (e.g., searching for keywords like `"drive"`, `"disk"`, `"file"`) is brittle, fails on natural linguistic variations, and constantly requires developer intervention whenever a user phrases an intent differently.
3. **Conversational Hijacking**: If the system relies on an LLM to scout capabilities, conversational or generic queries (e.g., *"How's the weather?"*, *"Tell me about Roman history"*, *"What can you do?"*) risk being mistakenly diagnosed as capability gaps, needlessly launching expensive 20-second tool synthesis loops.

---

## 2. Decision Drivers

* **Zero Regex Shortcuts**: Routing decisions must not rely on brittle hardcoded keyword lists or regex expressions.
* **Cost-Free Local Tokens**: Leverage local reasoning models (`qwen3.8`, `nemotron`) for structured semantic evaluations without cloud token expense.
* **Deterministic Stage-1 Catalog Dispatch**: If a recipe or tool already exists in `recipes.db`, dispatch immediately in $\le 1$ second without calling scout reasoning.
* **Anti-Hijack Guardrails**: Ensure pure conversational queries, questions, or clarification requests are never escalated to capability synthesis.
* **Strict JSON Schemas**: Scouts must output typed, structured envelopes (`CapabilityAssessment`) with deterministic fields (`has_capability`, `reasoning`, `tool_name`, `suggested_action`).

---

## 3. Decision Outcome

We implemented a two-stage triage pipeline (`src/agent_os/kernel/recipe_triage.py`):

1. **Stage 1: Deterministic Lexical & Semantic Recipe Match**:
   - Queries `recipes.db` for existing recipes matching user intent.
   - If a confident match is found, mounts the recipe's ingredients and executes immediately.
2. **Stage 2: Capability Gap Scout with Anti-Hijack Prompting**:
   - Only invoked when no existing recipe matches.
   - Evaluates the user's intent against existing tools using a strictly structured prompt that enforces:
     - Direct conversational responses for knowledge questions, general queries, and greetings.
     - Capability gap declaration **only** for concrete, actionable system operations that require interacting with the host environment, files, or external services.
   - Emits a structured JSON envelope. If a capability gap is verified, dispatches directly to the `ToolsmithWorker`.

---

## 4. Consequences

### Positive
* No hardcoded regex patterns to maintain or break over time.
* Fast-path execution for known capabilities ($\le 1$s).
* Clean separation between normal chat and autonomous tool creation.

### Negative / Trade-offs
* First-time execution of novel capabilities incurs a 15–20s synthesis and dry-run evaluation turn before returning the result.
* Requires the local model to reliably output parseable JSON under system constraints.
