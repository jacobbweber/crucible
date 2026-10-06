# Product Steering: Agent OS

> **Purpose**: Defines the core product vision, architectural philosophy, True North metrics, and explicit anti-goals for the Agent OS runtime. This document serves as the project's permanent reference anchor for all design and implementation decisions.

---

## 1. Product Vision

**Agent OS** is an autonomous, lightweight personal computing environment and localized agentic operating system designed to run on dedicated local hardware (e.g., Nvidia DGX Spark, 128 GB unified memory hosts) with zero-cost external fallbacks. It bridges conversational assistance, deep workflow execution, and personal knowledge management without token bloat, monolithic context pollution, or external vendor lock-in.

---

## 2. Core Philosophy

* **Context Isolation Over Monolithic Prompts**: Heavy execution belongs in the sandbox, not the conversation. The front-door chat loop remains lean, bounded, and fast, while isolated workers in the Recipe Chamber execute complex, multi-step runbooks and return compressed, typed envelopes.
* **Declarative Recipes Over Monolithic Personas**: Deterministic execution graphs, runbooks, and recipes define system capabilities. The user interacts with a single coherent companion; specialized operational roles exist exclusively as ephemeral execution routines.
* **Hardware-Gated Scheduling**: Autonomous background work must never crash or starve the host system. Execution schedules respect hardware limits, enforcing concurrency limits, graceful queueing, and intelligent catch-up policies upon boot or wake.
* **Hermetic Reliability & Deterministic Storage**: SQLite (FTS5 enabled) and standard local file structures form the ground truth. Search, fact retrieval, credential access, and state graduation rely on deterministic, audited algorithms rather than unpredictable vector bloat.

---

## 3. True North

* **Sub-Millisecond Fact Recall**: Immediate, exact recall of user preferences, system constraints, and atomic entities via indexed relational stores without injecting thousands of tokens of raw history.
* **Zero-Leakage Worker Sandboxes**: Ephemeral workers in the Recipe Chamber receive strictly scoped task briefs with zero personal identity context, and return immutable summaries constrained to $\le 200$ tokens.
* **Seamless Dual-Channel Observability**: Ambient awareness through non-blocking UI nudges and turn-deferred prompt injection, allowing background tasks to complete quietly without interrupting the active conversational stream.
* **Local-First Privacy & Zero-Context Security**: Credentials stay encrypted at rest via hardware-keyed vaults (`credentials.db`) and are scrubbed just-in-time from logs, traces, and model prompts via symbolic aliases (`vault://`).
* **Continuous, Structured Knowledge Evolution**: A self-maintaining 4-folder Wiki structure where unorganized thoughts in `00_Inbox` graduate into validated notes in `01_Notes` via automated linting and strict metadata schemas.

---

## 4. Anti-Goals

> [!CAUTION]
> If any planned feature or implementation violates these anti-goals, it must be rejected or redesigned.

* **No Multi-Agent Circus in User Space**: Avoid simulating multiple chatting personas, artificial team meetings, or competing agent personalities. The user talks to one companion core; background workers are anonymous, ephemeral execution units.
* **No Unbounded Context Accumulation**: Never allow conversational history to grow indefinitely into bloated prompt buffers. Do not dump complete task scratchpads, execution logs, or multi-page documentation into conversational working memory.
* **No Framework Bloat**: Reject reliance on heavy, opaque multi-agent orchestration frameworks (e.g., LangChain, CrewAI, AutoGen). System orchestration, tool policy evaluation, and ReAct loops must remain pure Python, strictly typed, and transparent.
* **No Vector-Only Fragility**: Do not depend exclusively on approximate nearest-neighbor vector embeddings for exact technical lookups, paths, part numbers, or commands. Pair lexical indexing (SQLite FTS5) with targeted semantic techniques only when necessary.
* **No Cloud-Tethered Core Dependencies**: Never require an active internet connection or cloud-hosted database for basic operating system functions, memory recall, note graduation, or local model execution.
