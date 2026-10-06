---
name: product-walkthrough
description: Guides the product owner through the application step-by-step using plain English, literal scenarios, and conceptual alignment without developer jargon.
---

# Product Walkthrough Skill

Use this skill whenever the user asks to "walk through", "walk me through", "step through", or review how the system works from a product and vision perspective.

## Core Directives

1. **Plain English & Zero Developer Jargon**:
   - Never throw raw database tables, API signatures, or internal implementation details at the user.
   - Use physical, intuitive metaphors (e.g., "loading dock", "post-it notes", "operating manual").

2. **Strict Ground-Truth Terminology**:
   - **The Warehouse**: The root local document repository (`warehouse/`).
   - **00_Inbox**: Staging area / loading dock. ALL new documents land here first. Nothing bypasses inbox.
   - **01_Knowledge**: Curated inventory. Validated documents with YAML frontmatter. Maximum 1–2 folders deep. Contains user domains, `recipes/`, `skills/`, and `roles/`.
   - **02_Resources**: Templates, operating manuals, and reference aids.
   - **03_Archive**: Cold storage. Retired items are preserved forever and never deleted.
   - **Role**: Persona, tone, and operating rules ("how to be a good agent").
   - **Skill**: Deterministic procedure, steps, and success criteria.
   - **Recipe**: A packaged workflow combining `Role + Skill + Tools`.
   - **Task Brief**: The ephemeral assignment handed to a worker model right before execution.

3. **Step-by-Step Cadence**:
   - Walk through the product one turn or one user action at a time.
   - Describe what the user does, what the companion says, and what happens under the hood in simple terms.
   - Stop and ask a direct, conversational check-in question before advancing to the next step.
   - Always prioritize validating the product owner's mental model over rushing to code.
