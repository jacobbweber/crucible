# Reference Repositories Rules

## 1. Purpose
- Crucible may consult external reference repositories for **ideas, inspiration, and likeness in intent** when weighing design decisions. They are a sounding board, not a template.
- Reference names and their machine-local locations are listed in the gitignored file `.agents/references.local.md`. Read it on demand; never commit host-specific paths.

## 2. When to Consult
- **Do** consult at design decision points: introducing or reshaping a subsystem, choosing between architectural options, or when trade-offs are unclear.
- **Do not** scan references during routine implementation, bug fixes, or refactors where the direction is already decided.

## 3. How to Compare
- For the decision at hand, summarize **what each reference does conceptually**, **how well it works** (evidence, not assumption), and a verdict: **adopt the concept**, **adapt it**, or **reject it**, tied to Crucible's design pillars.
- Treat reference code as potentially stale: confirm a feature is actually wired and used before treating it as representative. Dead code, abandoned directions, and leftover ideas are expected.
- Record the comparison in the relevant design note or decision record so the reasoning survives.

## 4. Boundaries
- **Adopt ideas, never implementations.** Do not copy code, file layouts, or naming verbatim; re-express concepts in Crucible's own clean, modular style.
- **Crucible's approach wins conflicts.** Explicit anti-goal: heavy, hands-on management of agents, skills, tools, and their RBAC/scoping. Concepts that reintroduce that cognitive load must be rejected or redesigned toward zero-catalog, low-friction defaults.
- References are **read-only**: never modify, run migrations in, or write files to a reference repository.
