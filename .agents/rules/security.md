# Security & Sandboxing Rules

## 1. Local Boundaries & Telemetry
- Strictly prohibit unauthorized network egress of user data, conversation histories, or local filesystem contents.
- Any network access must be explicit, auditable, and configurable by the user.

## 2. Tool Execution & Sandboxing
- Tool executions that modify files, run shell commands, or interact with external processes must execute within designated working boundaries.
- Sanitize and validate all arguments passed to terminal commands or system processes to prevent command injection.
- Prevent directory traversal vulnerabilities by strictly checking and resolving target paths against allowed workspace boundaries using relative path resolution.
- Never hardcode or leak absolute host paths; all tool operations must resolve relative to the task or repository boundary.

## 3. Credential & Secret Management
- Never commit secrets, API keys, tokens, or credentials into version control.
- Read credentials strictly from local environment variables or secure local credential stores.
