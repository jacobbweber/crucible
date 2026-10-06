# Recipe Authoring & Tool Reference

> **Purpose**: Guide for writing declarative runbooks, registering tools, and authoring automated knowledge routines in Agent OS.

---

## 1. What is a Recipe?

In Agent OS, recipes replace monolithic, brittle agent personas with **deterministic execution graphs**.
Recipes live as Markdown files in `data/wiki/03_Recipes/` and are indexed into SQLite FTS5 for rapid lexical matching.

When the companion encounters a task matching a recipe's trigger intent, the kernel dispatches the recipe to the Recipe Chamber where an isolated worker executes it step-by-step.

---

## 2. Recipe File Format

A recipe is a Markdown document with strict YAML frontmatter:

```markdown
---
id: recipe-wiki-digest
title: Daily Knowledge Digest
description: Aggregates recent notes from 00_Inbox and compiles a structured summary into 01_Notes.
version: 1.0.0
trigger_phrases:
  - "daily digest"
  - "summarize new notes"
  - "compile knowledge digest"
execution_engine: react
max_turns: 10
timeout_seconds: 60
required_tools:
  - wiki_list
  - wiki_read
  - wiki_write
---

# Operational Runbook: Daily Knowledge Digest

## Objective
Review notes created in `00_Inbox` over the last 24 hours. Extract key insights, identify recurring themes, and output a concise digest note into `01_Notes/Digests/`.

## Execution Steps
1. Call `wiki_list` with path `00_Inbox` to identify pending notes.
2. Read notes using `wiki_read` and extract key bullet points.
3. Call `wiki_write` to save the formatted digest to `01_Notes/Digests/YYYY-MM-DD-digest.md`.
4. Return a summary envelope of $\le 200$ tokens referencing the generated file path.
```

---

## 3. Supported Execution Engines

| Engine | Ideal Use Case | Behavior |
|---|---|---|
| `react` (Default) | Exploratory tasks, multi-step search & analysis | Model alternates between `Thought:`, `Action:`, and `Observation:` until task goal is achieved. Cycle detection prevents loops. |
| `pev` | Structured data pipelines | **Plan-Execute-Verify**: First step compiles a deterministic plan, second step runs batch tools, third step verifies outputs against constraints. |
| `stategraph` | Complex multi-branch workflows | Explicit finite-state machine transitions defined in recipe metadata. |

---

## 4. Built-in Tool Dictionary

Tools are pure-Python callable classes registered in the kernel. All parameters are strictly typed.

### 4.1 Knowledge & Wiki Tools
* `wiki_search(query: str, limit: int = 5)`: Full-text lexical search across all Wiki folders using SQLite FTS5.
* `wiki_read(path: str)`: Safely reads the text of a Markdown note. Path traversal (`../`) is strictly rejected.
* `wiki_write(path: str, content: str, tags: list[str] = [])`: Writes or updates a note with YAML frontmatter.
* `wiki_list(folder: str)`: Lists notes within `00_Inbox`, `01_Notes`, `02_Archive`, or `03_Recipes`.

### 4.2 Fact Store Tools
* `fact_search(query: str, limit: int = 5)`: Queries the atomic user facts database (`facts.db`) for specific preferences, hardware paths, or constraints.
* `fact_record(fact: str, category: str)`: Persists a validated atomic fact into SQLite.

### 4.3 Education & Mastery Tools
* `flashcard_review(topic: str, limit: int = 5)`: Fetches due cards for spaced-repetition review based on SM-2 intervals.
* `flashcard_update(card_id: str, score: int)`: Updates card interval, easiness factor, and mastery level based on performance score (0 to 5).

---

## 5. Knowledge Graduation Pipeline

Agent OS enforces continuous, structured knowledge evolution across the 4-folder Wiki structure:

```
[00_Inbox]  ──(Linting & Tag Validation)──>  [01_Notes]  ──(Deprecation)──>  [02_Archive]
```

1. **Inbox Entry**: Notes in `00_Inbox` can be rough drafts or unformatted thoughts.
2. **Graduation Service**:
   * Evaluates notes for valid YAML frontmatter (`title`, `tags`, `created_at`).
   * Validates backlinks and markdown syntax.
   * Resolves file name collisions deterministically (e.g. appending `-1`, `-2` rather than overwriting existing notes).
   * Moves validated notes to `01_Notes`.
