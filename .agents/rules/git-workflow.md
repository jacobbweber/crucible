# Git Workflow & Commit Standards

This rule defines the hands-off, automated version control and commit standards for AI agents operating in this repository.

---

## 1. Hands-Off Operation

* **Automated Progression**: When a logical milestone, phase, or coherent set of fixes is completed and verified, the agent should proactively create clean git commits without requiring manual user micromanagement for routine commit steps.
* **Pre-Flight Verification**: An agent MUST NEVER commit code unless all of the following verification gates pass cleanly:
  1. `pytest` (full test suite passes hermetically)
  2. `ruff check .` (no linting violations)
  3. `pyright` (zero type errors)

---

## 2. Commit Message Standards

Commits must follow the **Conventional Commits** specification:

* `feat(<scope>): <short description>` — New features, components, or user-facing capabilities.
* `fix(<scope>): <short description>` — Bug fixes, error handling, or behavioral corrections.
* `refactor(<scope>): <short description>` — Code restructuring without functional changes.
* `test(<scope>): <short description>` — Adding or updating test suites, probes, or fixtures.
* `docs(<scope>): <short description>` — Documentation, steering updates, or ADR records.
* `chore(<scope>): <short description>` — Build tooling, dependency management, or workspace configurations.

### Guidelines
* Keep the subject line concise ($\le 72$ characters), imperative, and lower-case after the type/scope prefix.
* Use a bulleted body for non-obvious context, architectural rationales, or lists of addressed findings IDs.
* Never commit sensitive credentials, local private IP addresses, or machine-specific filesystem paths.
