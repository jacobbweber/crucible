# ADR-0001: Local Multi-Model Gateway & Role Routing

> **Date**: 2026-10-05  
> **Status**: Accepted  
> **Deciders**: Human Product Owner, AI Assistant  
> **Context**: Phase 1 Gateway Hardening & Multi-Target Local Execution

---

## 1. Context & Problem Statement

Agent OS is designed as a local-first computing environment running on local inference endpoints (e.g., Nvidia DGX Spark running vLLM, and secondary Ollama hosts). Live testing against these endpoints revealed fundamental variations in behavior:
1. **Thinking / Reasoning Controls**: vLLM requires `chat_template_kwargs: {"enable_thinking": ...}`, whereas Ollama ignores this and expects `reasoning_effort: "none"`. Reasoning tokens consume the output token budget, resulting in empty responses if output limits are too tight.
2. **Context & Budgeting Variance**: Context windows differ drastically (e.g., 65k vs 32k), and thinking lengths range from ~66 tokens (Qwen) to ~1,000+ tokens (Nemotron) on identical prompts.
3. **Hardcoded Monolithic Call Sites**: The kernel historically invoked a single adapter with a hardcoded `max_tokens=4096` and text-only messages, lacking support for multimodal parts, tool call continuity, or role-based specializations.
4. **Concurrency Leaks**: The inference semaphore previously guarded only background routines, allowing concurrent user chat and worker tasks to overload local GPU VRAM.

---

## 2. Decision Drivers

* **Local-First & Subscription-Free**: Optimized exclusively for zero-cost, private local hardware targets.
* **Context Isolation**: Chat front door must remain fast and lean; heavy reasoning and tool executions run in ephemeral roles.
* **Determinism Around Non-Deterministic Models**: Model selection, budget allocation, thinking toggles, and concurrency gating must follow strict, auditable code rules.
* **Anti-Monolithic / SOLID**: Small, composable modules (<300 lines) with declarative provider profiles rather than sprawling `if vendor == ...` branches.

---

## 3. Considered Options

* **Option 1: Monolithic OpenAI Proxy Wrapper** (like AutoReiv).
  * *Description*: Route everything through a single OpenAI-compatible client, using regexes, header sniffing, and ad-hoc string formatting to paper over differences.
  * *Trade-off*: Rapid initial setup, but leads to brittle code, fragile repair loops, and impossible multimodal extensions.
* **Option 2: Third-Party Framework Gateway** (e.g., LiteLLM, LangChain).
  * *Description*: Delegate all provider translations and routing to an external heavy dependency.
  * *Trade-off*: Violates the "No Framework Bloat" and "Local-First / Hermetic" anti-goals. Introduces opaque abstractions and upstream breaking changes.
* **Option 3: Pure-Python Canonical Message Engine & Declarative Profiles** (Chosen).
  * *Description*: Define a neutral canonical message part schema in `domain/gateway.py`. Build declarative provider profiles that translate to wire protocols, managed by a role-based router with hardware concurrency gating.

---

## 4. Decision Outcome

Chosen option: **Option 3**. We establish a modular Gateway v2 architecture structured around four clean seams:

### 4.1 Canonical Message Parts & Sealed Envelope
Messages are composed of typed, immutable parts rather than raw strings:
* `TextPart`: Natural language strings.
* `ImagePart` / `FileRefPart`: Local filesystem path or hash reference (never raw base64 bloat in session history).
* `ToolCallPart` & `ToolResultPart`: Structured tool invocations with strict `tool_call_id` linkage.
* `ThinkingPart`: Reasoning stream tokens, containing an opaque `provider_data` dictionary (the sealed envelope) to preserve continuity tokens or thought signatures across turns without polluting domain types.

### 4.2 Role Router & Ephemeral Execution Roles
The kernel never requests a specific model name. Instead, it requests an operational **Role**:
* `chat`: Fast, concise companion front door (thinking: `none` or `low`, responsive latency).
* `planner`: Deep reasoning and decomposition (thinking: `high`, expanded token budget).
* `worker`: Tool execution in the Recipe Chamber (structured JSON action formatting).
* `verifier`: Output inspection and policy compliance checking.

Roles map to concrete model configurations via a declarative configuration file. Any unconfigured role falls back to the default local model.

### 4.3 Normalized Thinking Ladder
A 5-level thinking enum (`none`, `low`, `medium`, `high`, `max`). Provider profiles translate this ladder into endpoint-specific payloads (`chat_template_kwargs`, `reasoning_effort`, or token budgets), stepping down gracefully to the nearest weaker level if an endpoint lacks exact support.

### 4.4 Unified Concurrency & Budget Guard
All model invocations across chat, scheduler, and worker sandboxes must acquire an asynchronous concurrency semaphore before dispatch, preventing local GPU OOM. Output token limits are calculated dynamically based on role needs and effective model context.

---

## 5. Consequences & Trade-offs

### Positive Consequences
* Completely isolates the core kernel from vendor-specific API idiosyncrasies.
* Prevents GPU memory exhaustion on local DGX/Spark and mini-PC hosts.
* Eliminates the G1/G2 bug classes (token starvation and incompatible thinking toggles).
* Leaves a clean extension point for future providers without modifying existing kernel logic.

### Negative Consequences / Trade-offs
* Requires a small schema migration in the SQLite session storage layer to persist structured message parts rather than plain strings.
