# ADR-0008: Local Observability, Health Auditing, and RCA Proposal Staging

> **Date**: 2026-10-06  
> **Status**: Accepted  
> **Deciders**: Human Product Owner, AI Assistant  
> **Context**: Definition of the local observability architecture (MELT), companion self-health auditing recipes, and non-invasive proposal staging for system improvement.

---

## 1. Context & Problem Statement

To operate as a dependable, long-term personal AI operating system, Agent OS must be self-aware of its own operational vitals:
1. **Opaque Degradation**: Without unified telemetry, silent performance bottlenecks (e.g. slow database writes, model queueing, intermittent tool timeouts) go unnoticed until catastrophic failure.
2. **Privacy Risks of Telemetry**: Standard industry observability stacks rely on remote SaaS collectors (Datadog, OpenTelemetry to cloud). This violates our fundamental Local-First tenet.
3. **Safety Hazard of Unchecked Self-Coding**: Allowing an AI to directly rewrite its own running codebase in production creates severe risks of hallucinations, regression loops, and corrupted runtimes.
4. **Friction of Manual Diagnostics**: The user should not have to inspect raw log files or query SQLite tables manually to know if the system is healthy.

---

## 2. Decision Drivers

* **Local-First & Zero Egress**: All metrics, events, traces, and logs must be stored locally in SQLite (`telemetry.db`), never transmitted across the network.
* **Declarative Self-Inspection**: The companion must use standard recipes (`01_Knowledge/recipes/`) to inspect its own health, treating system diagnostics as standard workflows.
* **Strict Boundary Against Silent Self-Coding**: The runtime must not directly modify its own source code, binaries, or active execution pipelines.
* **The Sacred Rule of 00_Inbox**: All diagnostic postmortems, Root Cause Analyses (RCAs), and tuning recommendations must arrive on the loading dock (`00_Inbox`) as structured proposals for human review.

---

## 3. Decision Outcome

We establish a local observability framework paired with non-invasive self-improvement:

### 3.1 The Local Flight Recorder (`telemetry.db`)
We capture the four pillars of observability locally with zero runtime overhead:
* **Metrics (KPIs)**: TTFT (Time-to-First-Token), token generation velocity, prompt/completion token burn, tool success rates, routine punctuality drift, and SQLite file sizes.
* **Events**: Subsystem lifecycle changes, dynamic brief triggers, policy blocks, and credential scrubber redactions.
* **Traces**: Distributed span hierarchy linking User Turn $\rightarrow$ Fact Prefetch $\rightarrow$ Gateway $\rightarrow$ Sandbox Runner $\rightarrow$ Tool Calls $\rightarrow$ Return Marshaling.
* **Logs**: Credential-scrubbed JSONL audit logs with timestamps and error classifications.

### 3.2 Self-Monitoring Recipes
The companion inspects its own health through declarative recipes:
* `system_health_audit.md`: Audits error rates, database fragmentation, and routine punctuality over the last 24h/7d.
* `sandbox_security_audit.md`: Inspects blocked policy calls and scrubbed credentials.
* Users can ask in plain English: *"How are you feeling? Check your system health."* The companion runs the recipe and provides an ambient conversational summary.

### 3.3 Root Cause Analysis (RCA) & Improvement Proposals
When recurring anomalies, high failure rates ($>20\%$), or storage bloat are detected:
1. **No Direct Code Modification**: The runtime is strictly prohibited from altering Python files or production configuration directly.
2. **Staged Proposals in `00_Inbox`**: The companion drafts an incident postmortem and remediation document into:
   `warehouse/00_Inbox/rca_[issue_slug].md` or `warehouse/00_Inbox/proposal_[slug].md`
   Every proposal includes:
   - **Executive Summary & Severity**: Plain-English explanation of the observed issue.
   - **Telemetry Evidence**: Trace IDs, error log snippets, and impacted metrics.
   - **Root Cause Analysis**: Why the degradation occurred.
   - **Suggested Remediation**: Concrete steps (e.g. timeout adjustments, database vacuuming, or code diffs) for human review and approval.

### 3.4 Future Horizon: Sandboxed Code Self-Repair
Autonomous code self-repair (e.g. creating an isolated git worktree, applying a patch, running full test suites, and requesting promotion) is explicitly deferred to a future phase.

---

## 4. Consequences & Trade-offs

### Positive Consequences
* The companion gains complete operational self-awareness with zero cloud dependencies.
* Completely eliminates the hazard of self-induced runtime corruption.
* Preserves user agency: the user is presented with transparent evidence and can decide whether to approve or apply changes.
* Integrates seamlessly with The Warehouse taxonomy and the Sacred Rule of `00_Inbox`.

### Negative Consequences / Trade-offs
* Telemetry writes require bounded SQLite tables and automated retention pruning to prevent `telemetry.db` from growing unbounded over time.
