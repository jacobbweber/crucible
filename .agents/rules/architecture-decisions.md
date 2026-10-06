# Architecture Decision Records (ADRs)

This rule defines how and when Architecture Decision Records are maintained in `docs/adr/`.

---

## 1. When to Write an ADR

* **One-Way Doors Only**: ADRs are strictly reserved for significant architectural forks in the road ("one-way doors")—structural boundaries, canonical message protocols, persistence schema strategies, or core security models.
* **No Paperwork Drag**: Never create ADRs for routine bug fixes, routine tool additions, configuration tweaks, or minor refactors. Keep development flow rapid and lean.

---

## 2. Location & Naming

* ADRs live in `docs/adr/`.
* File naming convention: `XXXX-short-title-in-kebab-case.md` (e.g., `0001-local-multi-model-gateway-and-role-routing.md`).
* Sequential 4-digit numbering starting at `0001`.

---

## 3. Standard Template (1-2 Pages Maximum)

Every ADR must follow this concise structure:

```markdown
# ADR-XXXX: [Title]

> **Date**: YYYY-MM-DD
> **Status**: Proposed / Accepted / Superseded
> **Deciders**: Human Product Owner, AI Agent

---

## 1. Context & Problem Statement
What problem are we solving? What forces and constraints are at play?

---

## 2. Decision Drivers
Key criteria (e.g., local-first, zero cloud dependencies, bounded memory, typed safety).

---

## 3. Considered Options
* **Option 1**: [Brief description]
* **Option 2**: [Brief description]

---

## 4. Decision Outcome
Chosen option and trade-off rationale.

### Positive Consequences
* Benefit 1

### Negative Consequences / Trade-offs
* Operational overhead or acknowledged constraint
```

---

## 4. Lifecycle & Updates

* When a prior ADR is modified by a new design direction, update its status to `Superseded` and link to the new ADR.
* ADRs must reflect actual codebase ground truth; if implementation details shift during build, update the outcome section accordingly.
