# Product Steering: Agent OS

> **Purpose**: Defines the core product vision, architectural philosophy, True North metrics, and explicit anti-goals for the Agent OS runtime. This document serves as the project's permanent reference anchor for all design, capability evolution, and implementation decisions.

---

## 1. Product Vision

**Agent OS** is an autonomous, localized agentic operating system designed to run on dedicated local hardware with zero-cost local token execution and strict privacy boundaries. It bridges conversational partnership, deep background workflow execution, and personal knowledge management without token bloat, monolithic context pollution, or manual operational friction.

The user interacts with **one lifelong companion in a single persistent conversational continuum**. The companion handles memory extraction, context compaction, background dispatch, and capability discovery organically. Users do not manage multiple competing agents, switch between siloed sessions, or manually code integrations for basic operational directives.

---

## 2. Core Philosophy

* **The Single Companion Paradigm**: The user should never have to manually manage session lifecycles, start new sessions for clean context windows, or arbitrate between competing agent personas. Compaction, archival storage, and fact pre-fetching occur automatically.
* **Declarative Recipes as Capability Playbooks**: Recipes are not hardcoded agent roles or rigid prompts; they are declarative, modular playbooks—analogous to **Ansible playbooks and inventories**. A recipe brings together the exact **ingredients** required for a task:
  - **Tools**: Required verified executable capabilities.
  - **Model & Routing**: The optimal model tier, provider, and inference parameters.
  - **Context Sources**: Targeted memory facts, warehouse notes, or environment state.
  - **Procedural Runbook**: Deterministic execution steps, verification criteria, and recovery playbooks.
* **Autonomous Capability Discovery & Synthesis**: If the companion lacks an ingredient (tool, script, recipe) to satisfy a directive, it must not refuse or require external developer intervention. It autonomously scouts the gap, synthesizes the missing capability in an isolated sandbox, validates it via pre-flight dry-run execution, mounts it into live runtime memory, and auto-graduates successful executions into reusable, parameterized recipes.
* **Context Isolation Over Monolithic Prompts**: Heavy execution belongs in isolated sandboxes, not the user's conversational prompt. The front-door chat loop remains lean, bounded, and fast, while isolated workers in the Recipe Chamber execute multi-step runbooks and return compressed, typed envelopes.
* **Two-Tier Execution Boundaries**:
  - **Userland Evolution**: Synthesized FastMCP tools, recipes, wiki notes, and workspace files can be dynamically created, inspected, modified, and retired by the system.
  - **Protected Kernel Core**: The core operating system runtime (`src/agent_os/`) remains strictly sandboxed, deterministic, and protected against unvalidated in-memory self-mutation.
* **Deterministic Storage Over Vector Bloat**: SQLite (WAL + FTS5) and standard local file structures form the ground truth. Search, fact retrieval, credential access, and recipe matching rely on deterministic lexical indexing and verified relational schemas.

---

## 3. True North Metrics

* **Zero-Intervention Tool Synthesis**: When presented with an unfulfilled operational directive, the system synthesizes, verifies, mounts, and executes the required tool autonomously with zero human code intervention.
* **One-Turn Recipe Reusability**: Once a capability is graduated into a recipe, subsequent requests across different targets (e.g. `D:\`, `M:\`, `C:\Users`) execute in $\le 1$ second via stage-1 catalog dispatch without repeated scouting overhead.
* **Sub-Millisecond Fact Recall**: Immediate, exact recall of user preferences, system constraints, and atomic entities via indexed relational stores without injecting thousands of tokens of raw history.
* **Zero-Leakage Worker Sandboxes**: Ephemeral workers in the Recipe Chamber receive strictly scoped task briefs with zero personal identity context, and return immutable summaries constrained to $\le 200$ tokens.
* **Seamless Dual-Channel Observability**: Ambient awareness through non-blocking UI nudges and turn-deferred prompt injection, allowing background tasks to complete quietly without interrupting the active conversational stream.
* **Local-First Privacy & Zero-Context Security**: Credentials stay encrypted at rest via hardware-keyed vaults (`vault.db`) and are scrubbed just-in-time from logs, traces, and model prompts via symbolic aliases (`vault://`).

---

## 4. Anti-Goals

> [!CAUTION]
> If any planned feature or implementation violates these anti-goals, it must be rejected or redesigned.

* **No Multi-Agent Circus in User Space**: Avoid simulating multiple chatting personas, artificial team meetings, or competing agent personalities. The user talks to one companion core; background workers are anonymous, ephemeral execution units.
* **No Literal Hardcoded Recipes**: Never bind recipes or tools to specific literal values (e.g. pinning a recipe to `D:\` drive instead of parameterizing `path: str`). Capabilities must be generic, parameterized inventories.
* **No Fragile Regex Gatekeeping**: Do not use brittle regex pattern checks or hardcoded keyword shortcuts to decide capability gaps. Use local reasoning models with structured JSON schemas.
* **No Unbounded Context Accumulation**: Never allow conversational history to grow indefinitely into bloated prompt buffers. Do not dump complete task scratchpads, execution logs, or multi-page documentation into conversational working memory.
* **No Framework Bloat**: Reject reliance on heavy, opaque multi-agent orchestration frameworks (e.g., LangChain, CrewAI, AutoGen). System orchestration, tool policy evaluation, and ReAct loops must remain pure Python, strictly typed, and transparent.
* **No Cloud-Tethered Core Dependencies**: Never require an active internet connection or cloud-hosted database for basic operating system functions, memory recall, note graduation, or local model execution.
