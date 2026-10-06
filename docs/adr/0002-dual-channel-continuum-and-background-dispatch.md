# ADR-0002: Dual-Channel Continuum & Conversational Background Dispatch

> **Date**: 2026-10-06  
> **Status**: Accepted  
> **Deciders**: Human Product Owner, AI Assistant  
> **Context**: Phase 10 End-to-End System Hardening & Bridging Conversational / Worker Halves

---

## 1. Context & Problem Statement

Agent OS is split into two foundational operational halves:
1. **Front-Door Conversational Companion**: Fast, responsive, low-latency conversational interface maintaining personal working memory, tone, and active dialogue.
2. **Recipe Chamber & Worker Runtime**: Sandboxed, multi-step execution chamber capable of searching databases, reading notes, modifying local vaults, and executing recipes.

Prior to Phase 10 (Suspect **C4**), these halves were completely isolated:
* The user chatting with the companion could not trigger background workers, jobs, or tools.
* Heavy execution could only be invoked out-of-band via developer scripts or static routines.
* If a model attempted to invoke a tool within chat, either the turn blocked indefinitely or the invocation text was echoed as useless conversational output.
* If background tasks finished, there was no safe, non-blocking mechanism to notify the user without interrupting their ongoing conversational stream.

---

## 2. Decision Drivers

* **Context Isolation Over Monolithic Prompts**: Heavy execution logs and scratchpads belong in the worker sandbox, not in the front-door conversation buffer.
* **No Multi-Agent Circus**: The user interacts with a single, coherent companion. Operational roles exist exclusively as ephemeral background routines.
* **Dual-Channel Observability**: Ambient awareness through non-blocking UI nudges and turn-deferred prompt injection, allowing background tasks to complete quietly without conversational disruption.
* **Deterministic Sandboxing & Typing**: Clean event streams (`StreamTurnEvent`) and typed envelopes rather than ad-hoc chat regex hacks.

---

## 3. Considered Options

* **Option 1: Monolithic Inline Tool Calling in Chat Loop**
  * *Description*: Traditional ReAct pattern where the companion directly invokes tools within its own turn, pausing the chat stream until all tools finish.
  * *Trade-off*: Monolithic prompt bloat, high latency, context pollution with raw tool payloads, and loss of responsive companion interaction.
* **Option 2: Multi-Persona Group Chat**
  * *Description*: Simulate multiple agents chatting in the user's conversation (e.g., AutoGen, CrewAI).
  * *Trade-off*: Directly violates the "No Multi-Agent Circus in User Space" anti-goal. Introduces token waste, confusing multi-voice responses, and conversational chaos.
* **Option 3: Dual-Channel Directive Dispatch with Ambient Nudges & Deferred Injection** (Chosen)
  * *Description*: The companion emits declarative directives (`[DISPATCH: <task>]` or `[TOOL: <name>(<args>)]`). The kernel intercepts these directives, yields a clean `job_dispatched` event, dispatches the job to the Recipe Chamber asynchronously, and enqueues completion summaries into a session-isolated nudge queue.

---

## 4. Decision Outcome

Chosen option: **Option 3**. The system implements an asynchronous dual-channel continuum:

### 4.1 Directive Extraction & Immediate Acknowledgment
* The companion system prompt includes a concise directive reference: `[DISPATCH: <task description>]` for multi-step jobs and `[TOOL: <tool_name>(<args>)]` for instant inspection.
* During stream turn evaluation in `chat_loop.py`, directives are parsed with bracket-balanced extraction.
* The chat loop yields a `StreamTurnEvent(event_type="job_dispatched", ...)` event, allowing the companion to provide an immediate conversational acknowledgment without waiting for execution.

### 4.2 Sandboxed Worker Routing
* The kernel receives the dispatched task, resolves appropriate tools and role profiles, and delegates execution to `RecipeChamber` / `Runner`.
* The worker runs in a separate context with zero identity leakage and a dedicated turn/token budget.

### 4.3 Ambient Nudges & Deferred Turn Injection
* When the background worker completes, its compressed deliverable ($\le 200$ tokens) is stored in the SQLite session repository as a pending nudge (`status="pending"`).
* **Channel 1 (Real-time Ambient Nudge)**: A UI-level signal (e.g., `🔔`) is surfaced in the CLI/client to inform the user that background work has completed without injecting text into their current typing stream.
* **Channel 2 (Turn-Deferred Working Memory Injection)**: On the next user conversational turn, `PromptAssembler` queries unconsumed session nudges and renders a structured `<background_completions>` block directly into the companion's working context:
  ```xml
  <background_completions>
  The following background tasks finished since your last interaction:
  - [ephemeral_worker]: Search results for 'quantum computing': Found 2 notes in 01_Notes.
  Integrate this information naturally if relevant. Do not recite raw metadata.
  </background_completions>
  ```
* Once assembled, the nudges are marked as consumed (`status="consumed"`), preventing duplicate context injection.

---

## 5. Consequences & Trade-offs

### Positive Consequences
* The companion chat loop remains lean, bounded, and fast (<500ms initial token latency).
* Full multi-step runbook execution and database searching are seamlessly accessible through natural language.
* Conversational history remains completely free of raw tool logs, JSON schemas, and execution scratchpads.
* Background work seamlessly re-integrates into dialogue without race conditions or conversational interruptions.

### Negative Consequences / Trade-offs
* Results from background tasks are not injected mid-turn into an already-streaming companion answer; the user sees the output on the subsequent turn or via the ambient nudge. This is an intentional design trade-off prioritizing conversation stability over mid-stream prompt mutation.
