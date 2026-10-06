# Agent OS: System Operator Handbook

> **Audience**: System Operators, Developers, and Self-Hosters  
> **Target Hardware**: Dedicated local workstations, Nvidia DGX Spark, or high-memory local hosts (128GB+ unified memory).

---

## 1. Quick Start

### 1.1 Prerequisites
* Python 3.12+
* `uv` package manager (`pip install uv` or `winget install astral-sh.uv`)
* Local inference backend running at least one model:
  * **vLLM** (e.g. `nemotron-3.5-lightning` or similar on port 8099/8000)
  * **Ollama** (e.g. `qwen3.8:latest` or similar on port 11434)

### 1.2 Environment Setup
Copy `.env.example` to `.env` and configure your endpoints:

```bash
cp .env.example .env
```

```env
# Agent OS Data Root
AGENT_OS_DATA_DIR=./data

# Primary Model Target (vLLM / Spark)
AGENT_OS_LLM_BASE_URL=http://192.168.1.218:8099/v1
AGENT_OS_LLM_MODEL=nemotron-3.5-lightning
AGENT_OS_LLM_API_KEY=EMPTY

# Concurrency & Execution Limits
AGENT_OS_MAX_CONCURRENT_INFERENCE=2
AGENT_OS_RUNNER_TIMEOUT_SECONDS=60
AGENT_OS_POLICY_GATE_MODE=balanced
```

### 1.3 Launching the CLI
```bash
# Interactive Chat REPL
uv run agent-os chat

# Single Run / Job Dispatch
uv run agent-os run "Summarize recent notes on local inference"
```

---

## 2. Directory Architecture & Ground Truth

Agent OS persists all operational ground truth locally within `AGENT_OS_DATA_DIR` (default `./data`):

```
data/
├── storage/              # SQLite relational databases (WAL mode enabled)
│   ├── sessions.db       # Chat history, turn logs, ambient nudge queues
│   ├── facts.db          # Atomic user facts with SQLite FTS5 lexical index
│   ├── recipes.db        # Runbook definitions, step execution history
│   ├── routines.db       # Scheduled background jobs and catch-up states
│   ├── education.db      # Spaced repetition cards, review logs, mastery levels
│   └── credentials.db    # Hardware-keyed encrypted secret vault
│
└── wiki/                 # 4-folder personal knowledge vault (Markdown)
    ├── 00_Inbox/         # Raw thoughts, unverified web captures, draft notes
    ├── 01_Notes/         # Graduated, linted notes with strict YAML frontmatter
    ├── 02_Archive/       # Deprecated or historical notes
    └── 03_Recipes/       # Declarative runbook recipes (.md / .yaml)
```

---

## 3. Local Model Gateway Configuration

The Gateway abstracts vendor variations using declarative profiles in `src/agent_os/domain/gateway.py`.

### 3.1 Model Roles
The kernel never requests a specific model name; it requests an operational **Role**:
* `chat`: Fast, low-latency conversational companion.
* `planner`: Deep reasoning and runbook decomposition.
* `worker`: Sandboxed tool execution in the Recipe Chamber.
* `verifier`: Policy compliance and output validation.

### 3.2 Thinking & Reasoning Controls
| Provider | Target Endpoint | Thinking Control | Output Token Headroom |
|---|---|---|---|
| **vLLM** (Nemotron, DeepSeek) | `http://<host>:8099/v1` | `chat_template_kwargs: {"enable_thinking": true}` | Minimum 2048 clamped tokens |
| **Ollama** (Qwen, Llama) | `http://<host>:11434/v1` | `reasoning_effort: "none"` or `"low"` | Standard context limits |

---

## 4. Security & Hardware-Keyed Vault

### 4.1 Secret Storage
Secrets (e.g., API keys, database credentials) are encrypted at rest using AES-GCM-256 in `credentials.db`.
The encryption key is derived using hardware-unique host entropy (fallback to machine ID / OS UUID), preventing vault decryption if the database file is copied to another machine.

### 4.2 Symbolic Aliasing (`vault://`)
Never hardcode secrets into recipes or prompts. Use symbolic references:
```yaml
tools:
  - name: external_api_fetch
    headers:
      Authorization: "Bearer vault://github_pat"
```
The `CredentialProxy` resolves `vault://` references just-in-time during tool execution, scrubbing secrets from logs, traces, and model prompts.

### 4.3 Policy Gate Modes
Configured via `AGENT_OS_POLICY_GATE_MODE`:
* `strict`: Requires explicit operator approval for any `STATE_CHANGE` or `DESTRUCTIVE` tool.
* `balanced` (default): Automatically allows `READ_ONLY` and verified `STATE_CHANGE` tools; blocks `DESTRUCTIVE` tools without confirmation.
* `permissive`: Bypasses non-critical prompts (for testing only).

---

## 5. Background Routines & Schedulers

* **Scheduler Loop**: Background routines run on cooperative intervals defined in `routines.db`.
* **Catch-Up Policy**: If the host is shut down or sleeps, overdue routines trigger **at most once** upon startup.
* **Ambient Nudges**: Worker completions are tagged with `session_id` and queued non-blocking. The user sees a `🔔` in the CLI and receives `<background_completions>` context on their subsequent turn.

---

## 6. Verification & Health Checks

Run the verification battery at any time:

```bash
# Run unit and integration tests (181 tests)
uv run pytest

# Static type check
uv run pyright

# Linter and code style
uv run ruff check .

# Multi-target live test matrix
uv run python scripts/live_matrix.py scripts/probe_phase10.txt
```
