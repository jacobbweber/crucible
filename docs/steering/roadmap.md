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

---

## 3. Findings Tracker

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · ⚪ Low

| ID | Sev | Area | Description | Status |
|---|---|---|---|---|
| **C1** | 🔴 | Bootstrap | No composition root or entry point. | ✅ Fixed (Phase 0) |
| **C2** | 🔴 | Runner | ReAct workers are never provided tool schemas or action format in prompt. | ✅ Fixed (Phase 6) |
| **C3** | 🔴 | Policy | Policy bypass in workers (`STATE_CHANGE` forced on all tools). | ✅ Fixed (Phase 4) |
| **C4** | 🔴 | Integration | Chat cannot trigger jobs or tools (isolated halves). | ✅ Fixed (Phase 10) |
| **H1** | 🟠 | Dispatch | Recipe lexical matching ORs every word with low threshold fallback. | ✅ Fixed (Phase 2) |
| **H2** | 🟠 | Runner | Recipe `execution_engine` ignored; PEV and stategraph unreachable. | ✅ Fixed (Phase 6) |
| **H3** | 🟠 | Gateway | Runner sends `role="tool"` without `tool_call_id`. | ✅ Fixed (Phase 1) |
| **H4** | 🟠 | Security | Secrets scrubbed from output but not error; MAC-address default key derivation. | ✅ Fixed (Phase 4) |
| **H5** | 🟠 | Isolation | Global nudge queue leaks results across sessions. | ✅ Fixed (Phase 8) |
| **H6** | 🟠 | Scheduler | In-memory routines lose state on restart; catch-up logic unwired. | ✅ Fixed (Phase 8) |
| **H7** | 🟠 | Concurrency | Inference semaphore only guards scheduler, bypassing chat & manual jobs. | ✅ Fixed (Phase 1) |
| **H8** | 🟠 | Wiki | Inbox note graduation silently overwrites same-named files. | ✅ Fixed (Phase 3) |
| **M1** | 🟡 | Layering | Raw SQL executed from kernel signaling dispatcher. | ✅ Fixed (Phase 5) |
| **M2** | 🟡 | Chat | Foreign key violations on unknown session swallowed silently. | ✅ Fixed (Phase 5) |
| **M3** | 🟡 | Education | Education datetime parsing and pedagogical advancement unwired. | ✅ Fixed (Phase 9) |
| **M4** | 🟡 | Code Quality | Duplicate attribute aliases throughout codebase. | ✅ Fixed |
| **M5** | 🟡 | Context | Token counting hardcoded to `len // 4` without model budget limits. | ✅ Fixed (Phase 5) |
| **M6** | 🟡 | Runner | Execution timeouts passed but not enforced. | ✅ Fixed (Phase 6) |
| **M7** | 🟡 | Config | `AGENT_OS_DATA_DIR` mismatch in `.env.example`. | ✅ Fixed (Phase 0) |
| **M8** | 🟡 | Clean Code | Multiple files exceeding 300-line modularity threshold. | ✅ Fixed |
| **L1** | ⚪ | Wiki | Linear file search in wiki store; wiki_read calls private _resolve_safe_path. | ✅ Addressed (Phase 3) |
| **L2** | ⚪ | Docs | Missing operational and architecture documentation. | ✅ Complete |
| **G1** | 🟠 | Gateway | Reasoning models exhaust reply budget if `max_tokens` is constrained. | ✅ Fixed (Phase 0/1) |
| **G2** | 🟠 | Gateway | Disparate thinking toggle syntax across vLLM and Ollama. | ✅ Fixed (Phase 0/1) |
| **G3** | 🟡 | Gateway | Thinking length varies ~15x between model architectures. | ✅ Addressed (Phase 1) |
| **K1** | 🟡 | Kernel | User turn execution buffers entire stream instead of progressive yielding. | ✅ Fixed (Phase 1) |
| **K2** | ⚪ | Config | Vestigial `KernelConfig.storage_root` required but unused. | ✅ Fixed |
