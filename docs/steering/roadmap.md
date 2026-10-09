# Steering Roadmap: Testing & Hardening

> **Purpose**: Living execution tracker for systematic live-testing, review findings, and subsystem hardening across all configured model targets.

---

## 1. Multi-Target Test Matrix

Per `.agents/rules/live-testing.md`, every live test and smoke verification must succeed across all configured model targets before a phase is marked complete.

| Target | Host / Endpoint | Model Name | Context Window | Thinking Controls |
|---|---|---|---|---|
| **Nemotron** (vLLM / Spark) | `http://192.168.1.218:8099/v1` | `nemotron-3.5-lightning` | 65,536 | `chat_template_kwargs.enable_thinking` |
| **Qwen** (Ollama) | `http://192.168.1.29:11434/v1` | `qwen3.8:latest` (27B) | 32,768 | `reasoning_effort: "none"` |

---

## 2. Phase Execution Roadmap

| # | Phase | Core Focus | Live Verification Scenarios | Target Suspects | Status |
|---|---|---|---|---|---|
| 0 | **Test Bench & Wiring** | Composition root, dev REPL, tracing | Bootstrap runtime, multi-target probe, streaming with reasoning capture | C1, M7, G1, G2 | ✅ Complete |
| 1 | **Gateway & Model Routing** | Model I/O, streaming, canonical message parts | Stream completion, token budgeting, concurrency semaphore, timeout handling | H3, H7, M5, G3, K1 | ✅ Complete |
| 2 | **Storage & Ground Truth** | 5 SQLite DBs, WAL, FTS5 | Inspect schemas, atomic fact search ranking, recipe match lexical ranking | H1 | ✅ Complete |
| 3 | **Wiki Vault & Graduation** | 4-folder vault, graduation pipeline | Ingestion, path-traversal rejection, safe collision resolution on graduation | H8, L1 | ✅ Complete |
| 4 | **Security & Policy Gate** | Hardware-keyed vault, credential proxy, policy gate | Secret storage, `vault://` symbolic alias scrubbing, strict/balanced modes | H4, C3 | ✅ Complete |
| 5 | **Front Door & Memory** | Prompt assembly, fact recall, chat memory | Multi-turn chat with active trace, fact recall, sliding window past 15 turns | M1, M2, M5 | ✅ Complete |
| 6 | **Worker Runtime** | Recipe chamber, runner modalities, journeys | ReAct runner with live model calling wiki tools, cycle detection, brief schema | **C2**, H2, M6 | ✅ Complete |
| 7 | **Dispatch & Pipeline** | Recipe vs ephemeral task routing | Near-miss recipe matching, ephemeral brief synthesis, graduation evaluation | H1, H2 | ✅ Complete |
| 8 | **Signaling & Scheduler** | Background routines, session isolation | Multi-session nudge isolation, persistence across restarts, routine catch-up | H5, H6, M1 | ✅ Complete |
| 9 | **Education Engine** | SM-2 spaced repetition, pedagogical stages | Card review intervals, skill advancement via tool invocation | M3 | ✅ Complete |
| 10 | **End-to-End System** | Complete user day-in-the-life | Complex conversational task dispatching background worker, ambient nudge return | C4 | ✅ Complete |
| 11 | **Observability & History** | Local MELT, dual-DB search, RCA staging | 50 concurrent workers, hot/cold 90d archiving, health audit, live multi-target matrix | H9, H10, M9, M10 | ✅ Complete |
| 12 | **FastMCP Tool Hub & Synthesis** | In-process dynamic tool execution | Live synthesis, ephemeral dry-run, in-process FastMCP mounting without Docker | H11 | ✅ Complete |
| 13 | **Zero-Catalog Semantic Triage** | Autonomous capability gap scouting | LLM capability scout with anti-hijack guardrails, zero regex shortcuts | H1, R1 | ⚠️ Reopened → superseded by Phases 18–21 (keyword triage still present) |
| 14 | **In-Process Compilation & Schemas** | Typed JSON parameter preservation | Dynamic parameter extraction via inspect, alias normalization, AnyIO scope isolation | H11, H12, R4 | ⚠️ Partially superseded (in-kernel `exec` replaced in Phase 23) |
| 15 | **Recipe Contracts & Self-Authoring** | Declarative ingredients & autonomy | Recipe CRUD tools, ingredient schema contracts (tools/model/context), tool refactor/retire | H14 | ⚠️ Reopened → superseded by Phases 19–20 (ingredient contracts never implemented) |
| 16 | **Systemic Live Telemetry Hooks** | Active turn & pipeline tracing | Wire TelemetryCollector into user turn loop, pipeline runner, and tool invoker | H13 | ✅ Complete |

### ADR-0015 Rebuild: Contract-First Ingredients & Structured Intent Resolution

| # | Phase | Core Focus | Live Verification Scenarios | Target Suspects | Status |
|---|---|---|---|---|---|
| 17 | **Truth Reset** | Roadmap, ADR status, doc drift | Docs reflect code ground truth; superseded ADRs marked; ruff/format/pyright gates green | R6 | ✅ Complete |
| 18 | **Structured Gateway Channel** | Native tool calls + JSON-schema constrained output | Both targets: 9/9 schema-valid outputs, 9/9 streamed tool calls valid and correctly classified, 0/3 false tool calls on conversation | R2, G4–G7 | ✅ Complete |
| 19 | **Ingredient Contracts & Vocabulary** | Typed contracts, capability signatures, vocabulary registry | Invalid contracts rejected on write; 8 crafting rules enforced; built-in suites declared; 280 tests pass | H14, R1 | ✅ Complete |
| 20 | **Ingredient Store & Capability Index** | `ingredients.db`, versioned rows, in-process `EmbeddingProvider` (bge-small ONNX) + recall-only vector index | Seeded recipes migrated; index rebuildable from ground truth | R1 | ⏳ Planned |
| 21 | **Intent Resolver** | Intent → Retrieve → Bind → Adjudicate | Paraphrased requests resolve to same recipe; params bind via schema; keyword triage deleted | R1 | ⏳ Planned |
| 22 | **Companion Front Door** | `fulfill_request` native tool call | `[DISPATCH:]`/`[TOOL:]` regex removed; conversational turns never dispatch | R2 | ⏳ Planned |
| 23 | **Contract-First Toolsmith & Sandboxed Hub** | Contract → implement → contract tests; out-of-process execution | Synthesized code never `exec`'d in kernel; mounting honors approval mode | R4, R5 | ⏳ Planned |
| 24 | **Telemetry Fix & Lifecycle Promotion** | Tool-level journey steps; draft → candidate → active | Candidate promoted after verified runs on distinct inputs | R3 | ⏳ Planned |
| 25 | **Nightly Curator Routine** | Signature clustering, contract regression, demotion, merge | Repeated ephemeral jobs proposed as candidates; failing tools demoted with RCA | R3 | ⏳ Planned |

---

## 3. Findings Tracker

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · ⚪ Low

| ID | Sev | Area | Description | Status |
|---|---|---|---|---|
| **C1** | 🔴 | Bootstrap | No composition root or entry point. | ✅ Fixed (Phase 0) |
| **C2** | 🔴 | Runner | ReAct workers are never provided tool schemas or action format in prompt. | ✅ Fixed (Phase 6) |
| **C3** | 🔴 | Policy | Policy bypass in workers (`STATE_CHANGE` forced on all tools). | ✅ Fixed (Phase 4) |
| **C4** | 🔴 | Integration | Chat cannot trigger jobs or tools (isolated halves). | ✅ Fixed (Phase 10) |
| **H1** | 🟠 | Dispatch | Recipe lexical matching ORs every word with low threshold fallback. | ✅ Fixed (Phase 2/13) |
| **H2** | 🟠 | Runner | Recipe `execution_engine` ignored; PEV and stategraph unreachable. | ✅ Fixed (Phase 6) |
| **H3** | 🟠 | Gateway | Runner sends `role="tool"` without `tool_call_id`. | ✅ Fixed (Phase 1) |
| **H4** | 🟠 | Security | Secrets scrubbed from output but not error; MAC-address default key derivation. | ✅ Fixed (Phase 4) |
| **H5** | 🟠 | Isolation | Global nudge queue leaks results across sessions. | ✅ Fixed (Phase 8) |
| **H6** | 🟠 | Scheduler | In-memory routines lose state on restart; catch-up logic unwired. | ✅ Fixed (Phase 8) |
| **H7** | 🟠 | Concurrency | Inference semaphore only guards scheduler, bypassing chat & manual jobs. | ✅ Fixed (Phase 1) |
| **H8** | 🟠 | Wiki | Inbox note graduation silently overwrites same-named files. | ✅ Fixed (Phase 3) |
| **H9** | 🟠 | Warehouse | `WikiStore` initialized both `01_Notes` and `01_Knowledge`, diverting graduation. | ✅ Fixed (Phase 11) |
| **H10** | 🟠 | Telemetry | Unbounded `telemetry.db` span growth on long-running nodes. | ✅ Fixed (Phase 11) |
| **H11** | 🟠 | Runner / Hub | AnyIO cancel scope collision when executing synthesized tools across nested event loops. | ✅ Fixed (Phase 14) |
| **H12** | 🟠 | Tools / Schema | ToolDefinition constructed with empty parameters `[]`, stripping arguments from ReAct prompt. | ✅ Fixed (Phase 14) |
| **H13** | 🟠 | Telemetry | Telemetry database initialized but live runtime turns and pipelines uninstrumented. | ✅ Fixed (Phase 16) |
| **H14** | 🟠 | Autonomy | System cannot inspect, refactor, or retire its own recipe ingredients or broken tools. | ⚠️ Partial — tool inspect/refactor/retire exist; ingredient contracts do not (Phase 19) |
| **R1** | 🔴 | Dispatch | Recipe matching, gap detection, and tool selection rely on hardcoded keyword sets, regexes, and recipe-id string checks (`recipe_triage.py`, `capability_scout.identify_missing_domain`, pipeline filesystem branches, chamber/dispatcher tool injection). | ⏳ Open (Phases 19–21) |
| **R2** | 🔴 | Gateway | No structured model I/O: `CompletionRequest` lacks `tools`/`response_format`; all decisions parse JSON or `[DISPATCH:]` directives out of prose. | 🟡 Gateway channel fixed (Phase 18); callers migrate in Phases 21–22 |
| **R3** | 🟠 | Telemetry | Journey steps store `step_type` as `node_name`, so Pattern Scout and Recipe Promoter cluster on thought/tool_call markers instead of tool identities. | ⏳ Open (Phase 24) |
| **R4** | 🔴 | Security | Synthesized tool code is `exec`'d inside the kernel process after a subprocess dry run, and auto-mounted mid-pipeline. | ⏳ Open (Phase 23) |
| **R5** | 🟠 | Policy | Approval mode is fixed at boot, governs only execution (not mounting/promotion), and cannot be changed at runtime. | ⏳ Open (Phase 23) |
| **R6** | 🟡 | Docs | Roadmap, ADR-0011/0013/0014, and `recipes.md` describe behavior not present in code. | ✅ Fixed (Phase 17) |
| **G4** | 🟠 | Gateway | Both targets ignore `$ref`/`$defs` in tool schemas and double-encode nested objects as JSON strings. | ✅ Fixed (Phase 18) — model-facing schemas are inlined (`inline_refs`) |
| **G5** | 🟡 | Gateway | vLLM streams tool-call arguments as index-keyed fragments; Ollama emits whole calls. | ✅ Fixed (Phase 18) — `ToolCallAccumulator` emits assembled calls on the terminal chunk |
| **G6** | 🟡 | Gateway | `tool_choice: "required"` produces duplicate calls on the vLLM target; tool use without a system prompt is inconsistent. | ✅ Addressed — `required` unsupported; use `auto` or a named tool with a system prompt |
| **G7** | 🟠 | Intent | Context-free schema extraction misclassifies "folders on my M drive" as `filesystem.file` 3/3 on both targets; the companion tool-call path classifies 9/9 correctly. | ⏳ Open (Phases 19/21) — extract intent via companion `fulfill_request`; per-value vocabulary descriptions; dual retrieval + bind gate |
| **M1** | 🟡 | Layering | Raw SQL executed from kernel signaling dispatcher. | ✅ Fixed (Phase 5) |
| **M2** | 🟡 | Chat | Foreign key violations on unknown session swallowed silently. | ✅ Fixed (Phase 5) |
| **M3** | 🟡 | Education | Education datetime parsing and pedagogical advancement unwired. | ✅ Fixed (Phase 9) |
| **M4** | 🟡 | Code Quality | Duplicate attribute aliases throughout codebase (`chamber`/`recipe_chamber`, `threshold`/`match_threshold`, `repo`/`session_repo`, `adapter`/`model_adapter`). | ⚠️ Reopened (cleanup during Phases 21–22) |
| **M5** | 🟡 | Context | Token counting hardcoded to `len // 4` without model budget limits. | ✅ Fixed (Phase 5) |
| **M6** | 🟡 | Runner | Execution timeouts passed but not enforced. | ✅ Fixed (Phase 6) |
| **M7** | 🟡 | Config | `AGENT_OS_DATA_DIR` mismatch in `.env.example`. | ✅ Fixed (Phase 0) |
| **M8** | 🟡 | Clean Code | Multiple files exceeding 300-line modularity threshold. | ✅ Fixed |
| **M9** | 🟡 | Signaling | RCA postmortems staged in `00_Inbox` without ambient companion notification. | ✅ Fixed (Phase 11) |
| **M10** | 🟡 | Retention | Cold-archived sessions (>90d) inaccessible to conversation queries. | ✅ Fixed (Phase 11) |
| **L1** | ⚪ | Wiki | Linear file search in wiki store; wiki_read calls private _resolve_safe_path. | ✅ Addressed (Phase 3) |
| **L2** | ⚪ | Docs | Missing operational and architecture documentation. | ✅ Complete |
| **G1** | 🟠 | Gateway | Reasoning models exhaust reply budget if `max_tokens` is constrained. | ✅ Fixed (Phase 0/1) |
| **G2** | 🟠 | Gateway | Disparate thinking toggle syntax across vLLM and Ollama. | ✅ Fixed (Phase 0/1) |
| **G3** | 🟡 | Gateway | Thinking length varies ~15x between model architectures. | ✅ Addressed (Phase 1) |
| **K1** | 🟡 | Kernel | User turn execution buffers entire stream instead of progressive yielding. | ✅ Fixed (Phase 1) |
| **K2** | ⚪ | Config | Vestigial `KernelConfig.storage_root` required but unused. | ✅ Fixed |
