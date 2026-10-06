# ADR-0005: The Warehouse Architecture & Knowledge Taxonomy

> **Date**: 2026-10-06  
> **Status**: Accepted  
> **Deciders**: Human Product Owner, AI Assistant  
> **Context**: Terminology alignment, vault structure standardization, and agent vocabulary definition

---

## 1. Context & Problem Statement

Earlier design iterations referred to the local document repository as "Wiki", with notes organized under `01_Notes/` and recipes under `03_Recipes/`. 
Review with the Product Owner identified critical conceptual misalignments:
1. **Misleading Nomenclature**: "Wiki" implies an encyclopedia or personal scratchpad rather than an industrial, local-first computing repository holding domain knowledge, operational manuals, agent skills, and runbooks.
2. **Root Folder Pollution**: Placing recipes in `03_Recipes/` violated the strict 4-folder taxonomy established in AutoReiv, where `03_` is reserved exclusively for cold-storage archive.
3. **Ambiguous Agent Vocabulary**: Terms like "instructions", "brief", "runbook", "persona", and "recipe" were used inconsistently across documentation and code, creating confusion between permanent files and dynamic runtime assignments.

---

## 2. Decision Drivers

* **Zero-Confusion Product Ownership**: Code, documentation, and user interfaces must strictly reflect the product owner's mental model without developer jargon.
* **Deterministic Local-First Storage**: Standard local folder structures accessible via Obsidian or standard OS file browsers over LAN shares.
* **Strict Depth Boundaries**: Prevent automated agents from creating chaotic, deeply nested directory hierarchies.
* **Hermetic Loading Dock Discipline**: Strict staging requirements where unvetted documents cannot bypass inbox ingestion.

---

## 3. Decision Outcome

We formally adopt **"The Warehouse"** architecture and standardize our core agent taxonomy:

### 3.1 The 4 Sacred Roots of the Warehouse
The root repository directory is named **`warehouse/`** (default `data/warehouse/`). It strictly contains only **4 numbered folders**:

```text
warehouse/
├── 00_Inbox          # Staging area / Loading dock (ALL new documents arrive here first)
├── 01_Knowledge      # Active inventory (Curated, groomed documents; maximum 1-2 subfolders deep)
├── 02_Resources      # Aids, operating manuals, and _Templates
└── 03_Archive        # Cold storage (Preserved history, retired notes; NEVER deleted)
```

### 3.2 The Sacred Rule of 00_Inbox
* **No Direct Placement**: Neither human nor agent may write directly to `01_Knowledge` or `03_Archive`.
* **Automated Graduation**: Files land in `00_Inbox` first. Only the rule-based **Graduation Service** moves files into `01_Knowledge` after verifying:
  1. Valid YAML frontmatter.
  2. Subfolder depth constraint ($\le 2$ levels).
  3. Safe file collision resolution (never silently overwriting existing notes).

### 3.3 Maximum Depth Limit in 01_Knowledge
* Documents within `01_Knowledge` are categorized by domain with a strict depth ceiling of **1 to 2 folders deep** (e.g. `01_Knowledge/operations/homelab/`, `01_Knowledge/computer_science/ai/`).
* Subfolders for agent capabilities live inside `01_Knowledge`:
  * `01_Knowledge/roles/`
  * `01_Knowledge/skills/`
  * `01_Knowledge/recipes/`

### 3.4 Standardized Agent Vocabulary
We permanently define the five core agent concepts:

| Term | Definition | Persistence |
|---|---|---|
| **Role** | The persona, tone, operational posture, and operating rules ("how to be a good agent"). | Permanent file (`.md`) |
| **Skill** | The deterministic procedure, steps, and success criteria for how to do a specific job. | Permanent file (`.md`) |
| **Tool** | A concrete Python capability callable by an engine (e.g., search, read, write, bash). | Pure Python code |
| **Recipe** | The complete packaged workflow: **Role + Skill + Tools**. | Permanent file in `01_Knowledge/recipes/` |
| **Task Brief** | The **ephemeral, temporary assignment** handed to a worker model right before execution. | In-memory execution envelope |

---

## 4. Consequences & Trade-offs

### Positive Consequences
* Complete conceptual alignment between Product Owner, user documentation, and codebase.
* The Warehouse can be opened directly as an Obsidian vault over LAN with immediate, predictable folder navigation.
* Recipes, skills, and roles are treated as first-class, versioned knowledge assets.
* Eliminates the risk of runaway directory nesting by autonomous agents.

### Negative Consequences / Transition Plan
* Code references to `data/wiki` and tool naming (`wiki_search`, `wiki_read`, etc.) will be migrated to `warehouse_*` while retaining backward-compatible aliases to prevent breaking existing tests.
