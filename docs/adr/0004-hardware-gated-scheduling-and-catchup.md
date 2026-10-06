# ADR-0004: Hardware-Gated Scheduling & Catch-Up Execution

> **Date**: 2026-10-06  
> **Status**: Accepted  
> **Deciders**: Human Product Owner, AI Assistant  
> **Context**: Phase 8 Signaling, Persistence, and Scheduler Hardening

---

## 1. Context & Problem Statement

Autonomous agent operating systems require proactive background routines:
* Daily digests and memory consolidation.
* Spaced-repetition review triggers.
* Wiki health inspections and note graduation checks.

Running these routines on dedicated local hardware (e.g., Nvidia DGX Spark, local mini-PCs) presents strict constraints:
1. **Hardware Starvation / OOM**: Multiple concurrent inference calls (e.g., chat + background routine) easily overwhelm local GPU VRAM.
2. **State Loss on Reboot (Suspect H6)**: In-memory schedulers lose routine state when the host restarts, enters sleep, or restarts the process.
3. **Missed-Routine Thundering Herd**: When a machine wakes up or boots after being offline for days, a naive scheduler attempts to run all missed executions at once, crashing the inference server.
4. **Session Nudge Leakage (Suspect H5)**: Routine outputs stored in a global queue leak into the wrong user session.

---

## 2. Decision Drivers

* **Hardware-Gated Scheduling**: Background work must never crash, starve, or degrade the host system. Execution schedules must respect hardware concurrency limits.
* **Hermetic Reliability & Deterministic Storage**: SQLite (WAL enabled) is the source of truth for all routine metadata, execution logs, and scheduling state.
* **Session-Scoped Isolation**: Background notifications must be cleanly isolated to their originating or designated session.
* **Graceful Catch-Up**: System boot/wake-up must execute at most one catch-up run for overdue routines, never flooding queues.

---

## 3. Considered Options

* **Option 1: OS-Level Cron / Systemd Timers**
  * *Description*: Rely on OS-level cron to invoke CLI subcommands.
  * *Trade-off*: Non-portable across Windows/Linux, detached from runtime inference state, no awareness of GPU concurrency semaphores, and fragile error handling.
* **Option 2: Pure In-Memory Scheduler (e.g., APScheduler MemoryJobStore)**
  * *Description*: Schedule routines in-process in memory.
  * *Trade-off*: All execution history and next-run intervals vanish on restart. Cannot calculate missed downtime or perform safe catch-up.
* **Option 3: SQLite-Backed Routine Persistence with Concurrency Gating & Session-Scoped Nudges** (Chosen)
  * *Description*: Store routine definitions, last run timestamps, and intervals in SQLite (`routines` table). Use a cooperative scheduler loop with concurrency semaphore gating, bounded catch-up on boot, and session-tagged nudge queues.

---

## 4. Decision Outcome

Chosen option: **Option 3**. The scheduler architecture is structured around four components:

### 4.1 SQLite Ground Truth Schema
* Routines are persisted in `storage/routine_repo.py`:
  * `routine_id`, `name`, `interval_seconds`, `last_run_at`, `status`, `target_job`, `target_session_id`.
* Timestamps are stored in ISO 8601 UTC strings and parsed deterministically.
* Routines persist across process restarts, power loss, and upgrades.

### 4.2 Single-Fire Catch-Up Policy
* Upon startup, the `Scheduler` scans all active routines against the current clock:
  $$\Delta t = t_{\text{now}} - t_{\text{last\_run}}$$
* If $\Delta t \ge \text{interval}$, the routine is flagged as overdue.
* To prevent thundering herds, the catch-up policy executes exactly **one** catch-up run per overdue routine, immediately updating `last_run_at = now`. It never queues multiple backlogged executions.

### 4.3 Unified Concurrency Gating
* Every scheduled routine delegates actual model execution through the unified Gateway and its `InferenceSemaphore`.
* Background jobs yield priority to interactive user chat turns: if an inference slot is full, the scheduler queues or delays execution rather than forcing GPU allocation.

### 4.4 Session-Isolated Nudge Delivery
* When a background routine completes, its deliverable is enqueued via `SignalingDispatcher.send_nudge(session_id, ...)`:
  * Nudges are tied to a specific `session_id`.
  * If a routine is system-wide, it targets the default companion session or is marked ambient.
  * User sessions only receive nudges intended for them, completely eliminating cross-session leakage.

---

## 5. Consequences & Trade-offs

### Positive Consequences
* The system survives machine reboots and power cycles without lost state or erratic behavior.
* Eliminates GPU VRAM exhaustion caused by uncoordinated background executions.
* Completely resolves suspects **H5** (cross-session nudge leakage) and **H6** (unpersisted routines).
* Keeps scheduling logic transparent, testable, and dependency-light (pure Python and SQLite).

### Negative Consequences / Trade-offs
* Routine granularity is bounded by the scheduler tick rate (typically 1–5 seconds), which is optimal for agent workflows but not designed for sub-second real-time cron tasks.
