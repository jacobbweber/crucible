# ADR-0015: Contract-First Ingredients & Structured Intent Resolution

> **Date**: 2026-10-09
> **Status**: Accepted
> **Deciders**: Human Product Owner, AI Agent
> **Supersedes**: ADR-0011, ADR-0013, ADR-0014 §3.1; ADR-0012 in part

---

## 1. Context & Problem Statement

The companion's core loop is: *if a recipe exists, use it. If not, can existing ingredients form one? If not, craft the missing ingredients, then save and use the new recipe.* Recipes are also crafted overnight from telemetry.

The current implementation can't support this reliably:
- **No ingredient contracts.** A recipe is a list of tool names plus a markdown body. Tools have no output schema, declared capability, version, or tests.
- **Keyword lookup.** FTS5 ORs every word, and hardcoded keyword sets, regexes, and recipe-id checks veto or inject results (finding R1).
- **No structured model I/O.** Every decision pulls JSON or `[DISPATCH:]` directives out of prose (R2). When parsing fails, code falls back to keyword heuristics.
- **Curation is blind.** Telemetry records step types instead of tool identities (R3).
- **Synthesized code runs in the kernel process** and is auto-mounted with no approval (R4). The approval mode is static and only governs execution (R5).

---

## 2. Decision Drivers

* **Long-term reliability over short-term ease.** Lookup must survive paraphrase, new domains, and catalog growth without code edits.
* **No keyword or regex decision paths.** Every routing decision goes through typed structures.
* **Local-first.** Chat models run on local endpoints; the embedding model runs in-process on CPU. All indexes live in SQLite.
* **Evidence before trust.** Nothing becomes reusable without passing validation and verified runs.
* **User-controlled autonomy**, adjustable at runtime and later from a settings UI.

---

## 3. Considered Options

* **Option 1: Lexical (FTS5) + keyword guards.** Current state. Rejected: fails on paraphrase and needs a code change per domain.
* **Option 2: Pure structured matching on a controlled vocabulary.** Deterministic, but one wrong intent classification means a total miss, with no fallback.
* **Option 3: Contract-first ingredients + dual retrieval (structured signature ∪ local semantic embeddings), hard-gated by schema binding and policy, with bounded model adjudication.** Chosen.

---

## 4. Decision Outcome

### 4.1 Structured gateway channel (prerequisite) — implemented in Phase 18
`CompletionRequest` gains `tools`, `tool_choice` (`auto` \| `none` \| tool name), and `response_schema`. The adapter maps these to native function calling and JSON-schema constrained decoding on both vLLM and Ollama (`openai_payload.py`). Streamed tool-call fragments are assembled into complete `ToolCallPart`s (`tool_call_accumulator.py`). `structured.py` is the only path for typed output: Pydantic validation, **one** retry carrying the validation error, then `StructuredOutputError`. Parsing JSON out of prose and keyword fallbacks are not allowed.

Live constraints (findings G4–G7):
* Model-facing schemas must be **self-contained**. `$ref` is inlined, and recursive models are rejected.
* `tool_choice: "required"` is not used, because it produced duplicate calls on vLLM.
* Intent is extracted through the companion's native tool call rather than context-free schema extraction. The tool-call path scored 9/9 on classification; the context-free path scored 6/9.

### 4.2 Ingredient contracts
All ingredients share an envelope: `id`, `version`, `kind`, `status`, `provenance`, `description`, `content_hash`.

| Kind | Key fields |
|---|---|
| `tool` | `capability`, `input_schema`, `output_schema`, `examples` (≥1), `runtime` (`builtin` \| `mcp_hub` \| `mcp_external`) |
| `context_source` | `source` (`facts` \| `vault` \| `session_history` \| `system_info`), parameterized `query`, `max_tokens` |
| `model_profile` | `role`, `thinking_level`, `max_tokens`, `temperature` |
| `runbook` | `engine`, ordered `steps` (tool ref + input bindings), `max_turns`, `timeout_seconds` |
| `recipe` | `capability`, `inputs`/`outputs` schemas, refs to tools / context / model / runbook (`id@version`), `acceptance` checks, `intent_examples`, `stats` |

**Capability signature** = `verb` (closed enum) · `resource` (registry-backed) · `scope` (`host` \| `workspace` \| `vault` \| `network`) · `effect` (`read_only` \| `state_change` \| `destructive`, mapped to `ActionTier`). **Every vocabulary value carries its own description**, which is rendered into model-facing schemas (G7). New resource types come from curation as approval-gated proposals.

### 4.3 Hard crafting rules (enforced on every write)
1. Contracts validate against Pydantic models. Invalid ingredients are rejected and never stored.
2. A tool has exactly one verb and one resource. Inputs and outputs are typed JSON Schema (no blanket `string`).
3. A tool ships at least one contract example. Examples run on synthesis, on refactor, and nightly.
4. Every value derived from a request is a declared recipe input. Recipe defaults can't come from request content.
5. Recipe references resolve to `candidate` or `active` ingredients at a pinned version.
6. Declared `effect` is enforced by the policy gate. A tool can't exceed it.
7. Synthesized code runs only in the out-of-process hub. It is never `exec`'d in the kernel.
8. One canonical id per ingredient. No alias registrations (`mcp_hub_*`, `warehouse_*`).

### 4.4 Lookup: Intent → Retrieve → Bind → Adjudicate
1. **Intent.** The companion calls a native `fulfill_request` tool. Its argument is a schema-constrained `TaskIntent` (signature fields with enums injected from the live vocabulary, `parameters`, `desired_output`, normalized `utterance`). Conversational turns simply don't call it.
2. **Retrieve.** Take the union of (a) relational matches on the signature and (b) top-k cosine similarity between the intent embedding and each recipe's `intent_examples` and description. Rank by a weighted fusion in which signature agreement outranks similarity.
3. **Bind (hard gate).** `intent.parameters` must validate against `recipe.inputs`. All refs must be mounted. The effect must be permitted. Anything failing is dropped.
4. **Adjudicate.** With 0 viable candidates, go to composition. With 1, execute. With 2–3, the model picks one or `none` via an enum-constrained response.
5. **Verify.** Outputs are validated against `recipe.outputs` and `acceptance` (deterministic checks first, rubric judge as fallback). The outcome is recorded against `recipe@version` with the intent signature.

**Embeddings** are produced **in-process on CPU** behind an `EmbeddingProvider` port. The default is ONNX `bge-small-en-v1.5` (via fastembed): 67 MB, ~210 MB RSS, ~2.6 ms per query. A local `/v1/embeddings` endpoint is an optional adapter. Running in-process keeps one consistent index regardless of chat target and works offline. Weights are fetched once by a setup command into `<data_dir>`, pinned by hash. Vectors are a **derived, rebuildable index** in `ingredients.db`, stored with `(model_id, dim, content_hash)`; changing the model triggers a rebuild. Search is brute-force cosine, since catalog size doesn't justify a vector DB. Each verified run appends its normalized utterance to the recipe's `intent_examples` (capped and deduplicated), so recall improves with use.

**Embeddings are recall-only and never decide.** In a spike (12 recipes, 36 paraphrases, 7 models), the best model scored top-1 78% and top-3 89–94%. In every model, chitchat similarity overlapped correct-match similarity (bge-small: chitchat max 0.75 > correct min 0.57), so no similarity threshold is viable. Nearly all misses confused operations on the same resource (list vs. read vs. delete), which is exactly what the structured signature disambiguates. Larger models (bge-base, nomic) did not improve top-1. Embeddings therefore contribute only top-k candidates (k=5) to the fusion; the signature, bind gate, and adjudication decide.

### 4.5 Lifecycle
`draft` → `candidate` → `active` → `deprecated` → `retired`.
* **Real-time.** No viable recipe → compose a draft from tools matching sub-capabilities. Missing tool → the toolsmith gets a **ToolContract first**, then implements it and runs the contract examples in a sandbox. A verified run saves the recipe as `candidate`.
* **Promotion.** `candidate` → `active` after N verified runs across distinct input sets (default N=2), or on user confirmation, subject to the approval mode.
* **Nightly curation.** Cluster verified runs by intent signature, propose candidates, re-run all contract examples, demote failing tools to `deprecated` (staging an RCA), merge duplicates, and report one ambient summary.

### 4.6 Autonomy settings
The existing `ApprovalMode` (`autonomous` / `balanced` / `strict`) becomes a **runtime setting** that governs every trust gate, not only execution:

| Gate | autonomous | balanced | strict |
|---|---|---|---|
| Mount synthesized `read_only` tool | auto | auto | approve |
| Mount `state_change` / `destructive` tool | auto | approve | approve |
| Promote candidate → active | auto | auto if all tools read_only, else approve | approve |
| Execute `destructive` | auto | confirm | confirm |
| Execute `state_change` | auto | auto | confirm |
| Add vocabulary resource type | auto | approve | approve |

Settings are stored in `<data_dir>/settings.db` as typed key/value rows (precedence: DB > `.env` > code default) and read at decision time, so changes apply without restart. Pending approvals are persisted in the same store. They're surfaced today via `/approve` and `/mode` chat commands, and later through `GET/PUT /api/settings` and an approvals panel in the web UI.

### Positive Consequences
* Paraphrase-robust lookup with two independent retrieval signals and a deterministic schema gate.
* Every ingredient is testable, versioned, and auditable. Curation operates on real tool identities.
* Large deletions: keyword triage, regex fallbacks, alias registrations, and directive parsing.
* The user controls autonomy live, ready for a settings UI.

### Negative Consequences / Trade-offs
* Adds an ONNX runtime dependency (~67 MB model, ~210 MB RSS when loaded) and a one-time model fetch. Constrained decoding must be live-verified on every target.
* Migration cost: built-in tool suites must declare signatures, schemas, and examples. `recipes.db` is replaced by `ingredients.db`.
* Out-of-process hub execution adds per-call latency over in-process calls (accepted for R4).
* The controlled vocabulary needs curation discipline to avoid sprawl.
