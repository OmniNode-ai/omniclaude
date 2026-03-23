# OmniClaude Hooks Conventions

## Hook Registration (hooks.json)
- All hooks registered in `plugins/onex/hooks/hooks.json`.
- Each entry has `type` (SessionStart/PreToolUse/PostToolUse/etc), optional `matcher` regex,
  and a `hooks` array with `{"type": "command", "command": "..."}`.
- `matcher` is a regex against tool name (e.g., `^(Edit|Write)$`).
- Commands use `${CLAUDE_PLUGIN_ROOT}` for path resolution.

## Shell Script Patterns
- Shebang: `#!/usr/bin/env bash` with `set -eo pipefail`.
- Read tool input from stdin: `INPUT=$(cat)`.
- Extract fields with jq: `FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')`.
- Exit 0 = allow, exit 2 = block. Never exit 1 (treated as error, not block).
- Resolve plugin root: `PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"`.

## Emit Client Usage
- Import: `from omniclaude.hooks.lib.emit_client_wrapper import emit_event`.
- Events go to Kafka via the emit daemon (background process).
- Always include `correlation_id` and `session_id` in event payloads.
- Use typed event constants from `omniclaude.hooks.lib.emit_client_wrapper`.

## Subprocess Model
- Each PreToolUse/PostToolUse invocation spawns a new process.
- No persistent state between invocations. Read config from disk each time.
- Keep execution fast (<50ms). Heavy work should be async/background.
- Python libs live in `plugins/onex/hooks/lib/`. Shell scripts in `scripts/`.

## Existing Hook Inventory (PreToolUse)
- `pre_tool_use_authorization_shim.sh` — Edit/Write authorization
- `pre_tool_use_pipeline_gate.sh` — Pipeline gate for Edit/Write/Bash
- `pre_tool_use_bash_guard.sh` — Bash command safety
- `pre_tool_use_prepush_validator.sh` — Pre-push validation
- `pre_tool_use_poly_enforcer.sh` — Task/Agent polymorphic enforcement
- `pre_tool_use_context_scope_auditor.sh` — Context budget auditing
- `pre_tool_use_dod_completion_guard.sh` — Linear DoD guard
