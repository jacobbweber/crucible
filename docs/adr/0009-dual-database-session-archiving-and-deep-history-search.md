# ADR-0009: Dual-Database Session Archiving & Deep History Search

> **Date**: 2026-10-06  
> **Status**: Accepted  
> **Deciders**: Human Product Owner, AI Assistant  
> **Context**: Architectural definition of the hot/cold database partition for interactive sessions and the transparent cross-database history search engine.

---

## 1. Context & Problem Statement

As a companion operating over months and years, conversation history grows continuously:
1. **Chat Latency Degradation**: Unbounded growth of `sessions.db` eventually slows down index lookups, turn serialization, and context window assembly.
2. **Context Window Limits**: LLMs cannot ingest months of raw turn logs into prompt context; history must be searched selectively.
3. **Loss of Historical Knowledge**: When sessions older than 90 days are archived into cold storage (`sessions_archive.db`), naive session readers only look in active storage, losing awareness of decisions and discussions made months prior.
4. **Friction of Manual Archival Queries**: Users should not need to specify which database holds their memories when asking: *"What did we decide about our Docker deployment six months ago?"*

---

## 2. Decision Drivers

* **Sub-Millisecond Hot Path**: Daily interactive chat turns must query only active, hot sessions without scanning millions of historical tokens.
* **Zero Long-Term Knowledge Loss**: Archived conversations must remain 100% accessible on local disk without requiring cloud sync or complex migration scripts.
* **Transparent Unified Search**: A single unified search mechanism must seamlessly locate relevant turns across both hot and cold storage.
* **Strict Modularity & Anti-Monolithic Tenet**: Keep storage repositories focused and lightweight ($<300$ lines), factoring search algorithms into specialized engines.
* **The Sacred Rule of 00_Inbox**: Complex syntheses of past history must stage into `00_Inbox/` as draft notes for review and graduation.

---

## 3. Decision Outcome

We establish a **Hot/Cold Partitioned Session Architecture** coupled with a **Dual-Database History Search Engine**:

```mermaid
flowchart TD
    USER_QUERY["User: 'What did we decide about Docker 6 months ago?'"] --> AGENT["Companion / ReAct Runner"]
    AGENT --> TOOL["Tool: session_search_history"]
    TOOL --> ENGINE["session_search.py Engine"]

    subgraph HOT_STORAGE["Hot Active Storage (<=90d)"]
        S_HOT["sessions.db (WAL)"]
    end

    subgraph COLD_STORAGE["Cold Archive Storage (>90d)"]
        S_COLD["sessions_archive.db (WAL)"]
    end

    ENGINE -->|Query turns & titles| S_HOT
    ENGINE -->|Query turns & titles (if include_archive=True)| S_COLD

    S_HOT --> COMBINE["Aggregate & Rank Chronologically"]
    S_COLD --> COMBINE

    COMBINE --> RESULTS["Structured Matches with Provenance Badges:<br/>[Active Session] vs [Cold Archive]"]
    RESULTS --> AGENT
    AGENT --> INBOX["00_Inbox/docker_synthesis.md"]
```

### 3.1 Hot / Cold Partitioning Strategy
* **Hot Storage (`sessions.db`)**: Holds interactive sessions and turns from the past 90 days. Backed by SQLite WAL mode for high concurrency.
* **Cold Storage (`sessions_archive.db`)**: Holds migrated sessions and turns $>90$ days old. Shares an identical schema (`sessions`, `turns`), enabling deterministic querying.
* **Atomic Migration**: Handled via `SessionRepository.archive_old_sessions(retention_days=90)` during scheduled maintenance or on-demand.

### 3.2 Dual-Database Search Engine (`session_search.py`)
To prevent monolithic bloat in `session_repo.py`, history search is isolated in [`session_search.py`](file:///d:/Projects/Active/crucible/src/agent_os/infrastructure/storage/session_search.py):
* Scans `turns` and `sessions` using parameterized substring and token matching.
* Extracts localized text windows ($\approx 140$ characters) surrounding matched query tokens.
* Attaches explicit provenance metadata (`is_archived: bool`) so the companion and user know whether the discussion came from active memory or cold archival records.
* Merges and sorts results chronologically descending.

### 3.3 Runtime Tool & Recipe Integration
* **`session_search_history` Tool**: Exposed through [`SessionToolSuite`](file:///d:/Projects/Active/crucible/src/agent_os/kernel/session_tools.py) with parameters `query`, `include_archive=True`, and `limit=10`.
* **`deep_topic_synthesis` Recipe**: Pre-seeded in [`default_recipes.py`](file:///d:/Projects/Active/crucible/src/agent_os/kernel/default_recipes.py) to orchestrate cross-session research, structuring past discussions into Background, Decisions, and References, and saving the draft to `00_Inbox/`.

---

## 4. Consequences & Trade-offs

### Positive
* **Fast Daily Operations**: Active chat turns only hit a lean `sessions.db`, keeping turn latency and database checkpointing fast.
* **Long-Term Context Preservation**: Any decision recorded since system inception remains searchable in milliseconds.
* **Explainable Memory**: Provenance tags prevent the companion from confusing an old archival preference with an active conversational goal.

### Negative / Mitigations
* **File Handle Overhead**: Dual-database queries momentarily open connections to two SQLite files; mitigated by Python context managers that immediately return connections to the OS.
* **No Vector Indexing Yet**: Search currently uses lexical/FTS token matching; semantic embeddings can be layered cleanly on top of `session_search.py` in future phases.
