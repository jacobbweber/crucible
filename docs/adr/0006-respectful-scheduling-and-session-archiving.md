# ADR-0006: Respectful Scheduling & Hot/Cold Session Archiving

> **Date**: 2026-10-06  
> **Status**: Accepted  
> **Deciders**: Human Product Owner, AI Assistant  
> **Context**: Day-in-the-Life walkthrough alignment on hardware scheduling and chat retention

---

## 1. Context & Problem Statement

Through product review of our 8-step operating workflow, two critical operational risks were identified:
1. **Startup Resource Contention**: When a system boots or wakes from sleep, immediately executing backlogged scheduled routines competes for GPU/CPU resources, creates boot lag, and interrupts the user's initial morning interaction.
2. **Unbounded Session Growth vs. Data Loss**: As conversational turns accumulate over months, an unmanaged `sessions.db` degrades query performance and increases memory footprint. Conversely, blindly deleting old sessions violates the local-first "Never Delete Ground Truth" tenet.
3. **Noisy Automatic Summarization**: Unprompted automatic background summarization of casual chats produces low-signal junk notes in `00_Inbox`.

---

## 2. Decision Drivers

* **User Agency & Focus**: The companion must never nag, interrupt, or compete for system resources upon system boot.
* **Hermetic Local Ground Truth**: Data is never deleted; hot active data is kept lean and fast, while historical turns are preserved in cold storage.
* **Deliberate Knowledge Capture**: Only intentional, high-signal information should enter the `00_Inbox` loading dock.

---

## 3. Decision Outcome

We adopt three operational policies:

### 3.1 Respectful Wake/Boot Routine Policy
* When the system boots or wakes after downtime:
  * Missed routines are **not** immediately executed.
  * Their execution clocks are reset to their **next normal scheduled interval**.
  * An ambient notification is queued to the companion:
    > *"While the system was offline, [N] scheduled routines were missed. They are set to run on their next normal schedule, or you can say 'run missed routines' to execute them now."*
  * The user retains full control: do nothing (runs on schedule), or trigger on-demand execution in priority sequence.

### 3.2 Hot/Cold Session Retention Tiering
* We split conversational persistence into two distinct, identically-schematized SQLite databases:
  * **`sessions.db` (Hot Tier)**: Configurable retention window (default: 90 days). Stores active turns, immediate sliding window history, and pending nudges. Stays lean (<50MB) for sub-millisecond query performance.
  * **`sessions_archive.db` (Cold Tier)**: Long-term archive (default: 365+ days or indefinite). Stores historical sessions migrated from the hot tier.
* **Query Routing**:
  * Active chat and prompt assembly query only `sessions.db`.
  * Specialized research recipes and workers query both `sessions.db` and `sessions_archive.db` when historical context is explicitly requested.

### 3.3 Deliberate Knowledge Ingestion
* Chat conversations are only staged into `00_Inbox` through **deliberate user action**:
  1. Conversational directive: *"Save our discussion about X as a note."*
  2. UI message action: A *"Save as Note"* button attached to responses in the UI.
* Unprompted, automatic background summarization of casual chats is strictly rejected to preserve `00_Inbox` purity.

---

## 4. Consequences & Trade-offs

### Positive Consequences
* Zero boot lag or GPU resource contention when starting or waking the machine.
* `sessions.db` remains blisteringly fast regardless of how many years the system is used.
* Historical context is permanently preserved in cold storage with zero risk of accidental data loss.
* `00_Inbox` remains pristine, containing only high-value, intentional notes.

### Negative Consequences / Trade-offs
* Requires a lightweight background migration job to transfer completed turns older than 90 days from `sessions.db` to `sessions_archive.db`.
