# Architecture & Isolation Rules

## 1. Anti-Monolithic Modular Design
- **Avoid Monoliths & "God Objects"**: Do not build mega-classes, monolithic modules, or all-in-one managers that simultaneously handle orchestration, persistence, parsing, and execution. Break systems into discrete, decoupled packages.
- **Granular File & Module Scope**: Keep files focused and right-sized. As a guideline, avoid single files growing beyond ~250–300 lines; decompose complex components by extracting data models, interfaces, execution engines, and utilities into dedicated files.
- **High Cohesion & Loose Coupling**: Components within a module should be closely related in purpose, while dependencies between distinct subsystems should remain minimal, explicit, and abstract.

## 2. Context Isolation
- Every agent process and automation workflow must have an isolated context scope (memory, filesystem sandbox, and tool permissions).
- Do not share global mutable state across concurrent agent tasks.
- Shared state must be managed via explicit, serialized message passing or isolated transactional databases.

## 3. Subsystem Boundaries
- Decouple agent dispatchers, execution runtimes, and persistence layers.
- Define explicit interfaces/protocols for all communication between the host supervisor and child agents.
- Favor event-driven messaging and structured task lifecycle hooks (`init`, `execute`, `cleanup`).

## 4. Local-First Data Storage
- Use embedded or local-first storage engines (e.g., SQLite, structured JSON/YAML, or local vector indexes) rather than requiring external database servers for core functionality.
- Ensure data schemas support straightforward schema migrations and backups.

## 5. Relative Paths & Portability
- **No Hardcoded Absolute Paths**: Never use or commit machine-specific absolute paths (e.g., drive letters `C:\`, `D:\`, or user home directories `/home/username`).
- **Relative Path Resolution**: All file references, documentation links, configuration values, and module imports must be relative to the repository root or the isolated execution context.
- **Portability**: Code, rules, and configurations must function deterministically across different host environments, operating systems, and clone locations.

