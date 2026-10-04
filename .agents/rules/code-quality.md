# Code Quality & Standards

## 1. SOLID Design Principles
- **Single Responsibility (SRP)**: Each class, module, and function must have one well-defined responsibility and a single reason to change. Decompose multi-purpose routines into focused, cohesive units.
- **Open/Closed (OCP)**: Design components to be open for extension but closed for modification. Leverage protocols, abstract interfaces, and pluggable hooks rather than hardcoded branching.
- **Liskov Substitution (LSP)**: Implementations and sub-classes must satisfy the behavioral contracts of their parent interfaces so they can be swapped without side effects.
- **Interface Segregation (ISP)**: Favor small, focused, role-specific interfaces over bulky, "kitchen-sink" interfaces. Clients should never be forced to depend on methods they do not use.
- **Dependency Inversion (DIP)**: High-level orchestration policies must depend on abstractions/protocols, not low-level concrete implementations. Inject dependencies to keep components loosely coupled and easily testable.

## 2. DRY (Don't Repeat Yourself) & Pragmatic Abstraction
- Eliminate copy-pasted logic, magic strings, and duplicated business rules by consolidating them into reusable modules or utilities.
- Avoid premature or overly complex abstractions: prefer clear, explicit code over convoluted indirection if a pattern is not yet well-established.

## 3. Clean, Readable Code
- Write expressive, self-documenting code with clear, intention-revealing names for variables, functions, and types.
- Keep functions small and focused on a single task (aim for under 30–50 lines per function where feasible) to minimize cognitive load.
- Reserve comments for explaining the "why" (architectural rationale, trade-offs, constraints, or non-obvious domain logic) rather than restating the obvious "what".

## 4. Type Safety & Validation
- Enforce strict typing across all interfaces, function signatures, and data payloads.
- Use explicit data schemas (e.g., Pydantic models, dataclasses with validation, or equivalent typed definitions) to validate tool arguments and agent messages at system boundaries.

## 5. Error Handling & Resilience
- Never silently swallow exceptions or errors. Always log meaningful context before raising or handling.
- Differentiate between fatal runtime failures and recoverable agent task errors (e.g., failed tool invocation vs. runtime crash).
- Implement timeouts and cancellation token support on all long-running or async agent tasks.

## 6. Lean Testing & Verification (High-Signal, Low-Overhead)
- **Rely on Type Checking & Schemas**: Use static type checking and runtime validation schemas (e.g., Pydantic) to catch interface contracts and data errors without maintaining brittle test code.
- **End-to-End Smoke Tests Over Mocks**: Prefer lightweight, real smoke scenarios (e.g. executing a CLI task end-to-end) over sprawling suites of fine-grained, mock-heavy unit tests.
- **Avoid Speculative Test Bloat & Mock Churn**: Do not write unit tests with complex mocks during rapid prototyping or architectural exploration. Heavy mocks create high maintenance drag and consume excessive context tokens.
- **Test Only Critical Invariants**: Reserve unit tests for pure, self-contained business logic or deterministic state transitions where regression risk is genuinely high.

