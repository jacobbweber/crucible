# ADR-0007: Capability Evolution, Dynamic Planning, and Pattern Discovery

> **Date**: 2026-10-06  
> **Status**: Accepted  
> **Deciders**: Human Product Owner, AI Assistant  
> **Context**: Definition of the capability lifecycle, on-the-fly planning, and after-hours recipe synthesis

---

## 1. Context & Problem Statement

Agent OS executes multi-step workflows via declarative Recipes stored in `01_Knowledge/recipes/`. However:
1. **Unanticipated User Demands**: Users frequently request tasks for which no pre-packaged recipe exists. The system must not fail or reject requests simply because a file is missing.
2. **Opaque Planning Latency**: When dynamic planning is required, a silent multi-second pause makes the user believe the companion has frozen.
3. **Manual Recipe Authoring Friction**: Users rarely take the time to write YAML frontmatter and Markdown runbooks manually. If recipes must be hand-coded, the system remains static and never grows.
4. **Autonomous Capability Drift**: If the AI is allowed to silently write permanent execution code or modify active runbooks in production, it risks hallucinating unsafe procedures.

---

## 2. Decision Drivers

* **User Transparency & Flow**: When synthesizing a new capability on the fly, the companion must explicitly acknowledge the planning phase.
* **Continuous, Data-Driven Growth**: The system should learn from how it is used by analyzing execution frequency, tool sequences, and success rates.
* **The Sacred Rule of 00_Inbox**: Proposed recipes must arrive on the loading dock (`00_Inbox`) for user inspection and automated graduation, never directly placed into `01_Knowledge/recipes/`.
* **Zero Cognitive Overhead**: Transitioning from a successful one-off execution to a reusable recipe should require minimal or zero human effort.

---

## 3. Decision Outcome

We establish a three-tiered capability lifecycle:

### 3.1 Dynamic Planning & Ephemeral Brief Synthesis
* When a user request matches no existing recipe in `recipes.db`:
  * **Companion Acknowledgment**: The companion responds transparently:
    > *"I don't have a saved recipe for [task] yet. I'm assembling an on-the-fly task brief and selecting the right tools now..."*
  * **Ephemeral Planner**: Inspects registered tools in the kernel, synthesizes a temporary `TaskBrief` with required tools and step boundaries, and delegates execution to the Recipe Chamber.
  * **Telemetry Logging**: Every step, parameter payload, tool invocation, and duration is logged to `journey_steps` in `sessions.db`.

### 3.2 On-Demand Recipe Promotion
* Following any successful ephemeral task, the user can say:
  > *"Save that workflow as a recipe called [name]."*
* The system extracts the successful step sequence and tool definitions from the journey log, formats a clean Markdown recipe with YAML frontmatter, and stages it into `warehouse/00_Inbox/[name].md`.

### 3.3 The After-Hours Pattern Scout
* A recurring background routine runs during idle hours (e.g. weekly):
  1. **Pattern Extraction**: Scans `journey_steps` across recent sessions, clustering repeated sequences of tool invocations ($N \ge 3$) with $\ge 90\%$ success rates.
  2. **Candidate Synthesis**: Automatically writes a structured candidate recipe with generalized parameters:
     `warehouse/00_Inbox/suggested_[pattern_name].md`
  3. **Ambient Discovery Notification**: On the next morning's briefing or digest, the companion informs the user:
     > *"Good morning! I noticed we've performed [task pattern] several times recently. I drafted a reusable recipe for it and staged it in your `00_Inbox`. Take a look when you have a moment, and we can graduate it into your permanent recipes."*

---

## 4. Consequences & Trade-offs

### Positive Consequences
* The companion feels genuinely alive and evolving with the user's real daily habits.
* Completely eliminates the need for manual recipe coding.
* Upholds safety by requiring all suggested recipes to pass through `00_Inbox` and the formal Graduation Service.
* Keeps the conversational experience authentic by communicating when planning is happening.

### Negative Consequences / Trade-offs
* Pattern clustering across journey telemetry requires a light SQLite query against `journey_steps`, which must be bounded to avoid heavy processing on low-power host nodes.
