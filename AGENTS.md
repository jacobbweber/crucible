# Agent Guidelines

As an AI agent collaborating in this codebase, you must adhere to the core principles, architectural guidelines, and workflows outlined below.

---

## 1. Core Tenets

1. **Local-First & Privacy-Centric**: All user data, memory states, logs, and artifacts must remain on the user's local machine by default. Never introduce unprompted cloud telemetry or remote tracking.
2. **Context Isolation**: Every agent, workflow, and automated task must execute within isolated contexts. Context leakage between unrelated tasks or agents must be strictly prevented.
3. **Deterministic Sandboxing**: Runtimes and external tool executions must run with explicit permission boundaries and sandboxed environments.
4. **Anti-Monolithic & Modular by Default**: Strictly adhere to SOLID and DRY principles. Avoid monolithic "God objects" and sprawling files; decompose subsystems into small, focused, and composable modules.
5. **Product-Agnostic Core**: The codebase and repository must remain strictly product-agnostic and brand-neutral. Use generic terminology such as `agent_os`, `agent-os`, runtime, or generic subsystem names across all code, configurations, and documentation. Do not hardcode specific product names or companion names.

---

## 2. Repository Customizations

This repository uses standard Antigravity workspace customizations:

* **Rules (`.agents/rules/`)**: Directory-wide constraints and guidelines that are always active.
  * [`architecture.md`](.agents/rules/architecture.md) — Anti-monolithic architecture, runtime contracts, and context isolation.
  * [`code-quality.md`](.agents/rules/code-quality.md) — SOLID & DRY principles, clean code standards, typing, and testing expectations.
  * [`security.md`](.agents/rules/security.md) — Sandboxing, secret handling, and execution boundaries.
  * [`live-testing.md`](.agents/rules/live-testing.md) — Every live test runs against all configured model targets.
  * [`reference-repos.md`](.agents/rules/reference-repos.md) — Consulting reference repositories for concepts (never implementations) at design decision points.
  * [`git-workflow.md`](.agents/rules/git-workflow.md) — Hands-off automated git workflow and Conventional Commits.
  * [`architecture-decisions.md`](.agents/rules/architecture-decisions.md) — Lean, one-way-door Architecture Decision Records in `docs/adr/`.
* **Steering & Roadmaps (`docs/steering/`)**:
  * [`product.md`](docs/steering/product.md) — Core vision, philosophy, true north, and explicit anti-goals.
  * [`roadmap.md`](docs/steering/roadmap.md) — Living 10-phase test and hardening roadmap with findings tracker.
* **Skills (`.agents/skills/`)**: On-demand runbooks and procedural workflows.
  * [`scaffold-subsystem`](.agents/skills/scaffold-subsystem/SKILL.md) — Step-by-step workflow for creating new agent subsystems or runtime providers.

---

## 3. General Development Workflow

* **Clean Code & SOLID/DRY**: Write concise, self-documenting code with small functions (<30–50 lines) and right-sized files (<250–300 lines). Eliminate duplication without over-engineering.
* **Verification & Lean Testing**: Verify changes with static typing and end-to-end smoke executions. Avoid speculative mock-heavy test suites that cause context bloat; test real outcomes over internal implementation details.
* **Git Conventions**: Use Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`). Keep commit messages descriptive and concise.
* **Code Cleanliness**: Follow language-specific formatting standards and maintain strict typing across all interfaces.
