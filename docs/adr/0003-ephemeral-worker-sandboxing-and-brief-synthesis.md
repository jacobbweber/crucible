# ADR-0003: Ephemeral Worker Sandboxing & Brief Synthesis

> **Date**: 2026-10-06  
> **Status**: Accepted  
> **Deciders**: Human Product Owner, AI Assistant  
> **Context**: Phase 6 & Phase 7 Subsystem Hardening (Worker Isolation, Tool Schemas, Policy Gates)

---

## 1. Context & Problem Statement

Background tasks, scheduled routines, and user-dispatched jobs require executing multi-step tools (e.g., searching SQLite, reading Markdown files, linting inbox entries, updating cards). 

Initial implementations suffered from critical failure modes:
1. **Context & Identity Pollution**: Workers either received full conversational history or were forced to adopt companion personas, wasting thousands of tokens and risking identity confusion.
2. **Missing Tool Schema Guidance (Suspect C2)**: Workers were invoked without tool definitions or expected action formats in their prompts, resulting in repetitive hallucinations.
3. **Policy Bypass Vulnerability (Suspect C3)**: Tool calls were executed with forced `STATE_CHANGE` action tiers, bypassing safety checks and parameter verification.
4. **Execution Loops & Tool Incompleteness**: Ephemeral planners would select a search tool without pairing it with a read tool, trapping workers in dead ends. Models would emit terminal keywords (`"none"`, `"finish"`) that were erroneously parsed as invalid tool executions.

---

## 2. Decision Drivers

* **Zero-Leakage Sandboxes**: Background workers must receive strictly scoped task briefs with zero personal identity tokens or conversational chatter.
* **Hermetic Reliability**: Workers must operate deterministically within strict step budgets, execution timeouts, and cycle detection boundaries.
* **Deterministic Sandboxing & Policy Gating**: Every tool invocation must pass through an auditable Policy Gate; secrets must be scrubbed using `vault://` aliases.
* **Compressed Returns**: Workers must synthesize and return immutable summaries constrained to $\le 200$ tokens to protect the parent conversation from prompt bloat.

---

## 3. Considered Options

* **Option 1: Shared Conversational Context Workers**
  * *Description*: Pass the entire conversation history and companion prompt to the worker, letting it act as an extension of the chat assistant.
  * *Trade-off*: Severe context bloat, token starvation on reasoning models (e.g., Nemotron), high latency, and frequent context leakage between unrelated tasks.
* **Option 2: Hardcoded Subagent Personas**
  * *Description*: Define static, persistent agent personas (e.g., "ResearchAgent", "CodingAgent", "OrganizerAgent").
  * *Trade-off*: Monolithic persona drift, rigid architectures, maintenance overhead, and multi-agent coordination circus.
* **Option 3: Ephemeral Brief Synthesis with Complementary Tool Pairing & Compressed Return Marshalling** (Chosen)
  * *Description*: Workers are ephemeral, anonymous execution units. When a task is dispatched, the kernel synthesizes a dynamic, self-contained `TaskBrief` with explicit tool schemas, pairs required complementary tools, executes under a ReAct engine with cycle detection, and marshals output through a compressed envelope.

---

## 4. Decision Outcome

Chosen option: **Option 3**. The worker runtime operates under a clean, sandboxed architecture:

### 4.1 Ephemeral Brief Synthesis & Anonymity
* The `BriefAssembler` compiles an anonymous task prompt containing:
  * Strict Task Objective and Boundaries.
  * Explicit Tool Schemas formatted with parameter types and descriptions.
  * Strict ReAct Action Grammar: `Thought: ...`, `Action: {"action": "tool_name", "parameters": {...}}`, `Observation: ...`.
  * Contextual facts directly relevant to the task (retrieved via lexical prefetch).
* All user identity tokens, personal banter, and unrelated chat history are completely excluded.

### 4.2 Complementary Tool Pairing
* When the ephemeral planner selects tools dynamically, complementary pairings are enforced (e.g., `wiki_search` automatically includes `wiki_read`; `flashcard_review` includes `flashcard_update`).
* Workers never find themselves in an orphaned state where they can discover an item but lack the tool to inspect or update it.

### 4.3 ReAct Engine Hardening
* **Cycle Detection**: The runner maintains a hash history of recent `(tool_name, parameters)` pairs. Repetitive loops trigger an immediate warning observation to force the model to branch.
* **Terminal Pseudo-Tool Filtering**: Terminal actions such as `{"action": "none"}` or `{"action": "finish"}` are recognized as completions rather than invalid tools, preventing spurious policy rejections.
* **Turn & Timeout Budgets**: Default budget set to 15 turns with hard timeouts passed down to the inference gateway.

### 4.4 Policy Gate & Secret Scrubbing
* Every tool execution is evaluated by `PolicyGate` against an `ActionTier` (`READ_ONLY`, `STATE_CHANGE`, `DESTRUCTIVE`).
* Any credentials or sensitive tokens in parameters or outputs are substituted with symbolic aliases (`vault://<alias>`), ensuring secrets never appear in model logs or execution traces.

### 4.5 Return Marshalling
* The `ReturnMarshaller` extracts the final observation/thought and clamps the response to $\le 200$ tokens, formatting it into a typed `WorkerResult` envelope.

---

## 5. Consequences & Trade-offs

### Positive Consequences
* Workers are 100% focused, fast, and token-efficient.
* Complete isolation ensures tasks cannot corrupt each other or leak sensitive information into conversation logs.
* Deterministic ReAct grammar works reliably across differing local models (both vLLM Nemotron and Ollama Qwen).
* Eliminates the entire class of runner bugs (C2, C3, H2, M6).

### Negative Consequences / Trade-offs
* Tasks requiring deep, multi-page document generation cannot return their entire raw text directly through the conversational nudge; they must persist full output to the Wiki (`01_Notes` or `00_Inbox`) and return a file reference in the summary.
