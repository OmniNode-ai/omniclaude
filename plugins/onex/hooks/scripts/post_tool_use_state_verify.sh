#!/usr/bin/env bash
# post_tool_use_state_verify.sh
# PostToolUse hook: verify that service-start commands actually brought up the expected port.
# Fires on Bash tool completions. Checks command against a narrow allowlist.
# Exits 0 always (informational only — warnings emitted to stdout).
#
# v1 scope: intentionally narrow. Only checks docker compose up → port 5436.
# Extend COMMAND_PORT_MAP incrementally; do not generalize to all processes.

set -euo pipefail

# --- Lite mode guard [OMN-5398] ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _SCRIPT_DIR _MODE_SH

INPUT=$(cat)

# Guard: jq required for JSON processing; pass through on failure
if ! command -v jq >/dev/null 2>&1; then
  printf '%s\n' "$INPUT"
  exit 0
fi

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null || true)

if [[ "$TOOL_NAME" != "Bash" ]]; then
  printf '%s\n' "$INPUT"
  exit 0
fi

COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null || true)

EXIT_CODE=$(echo "$INPUT" | jq -r '
  if (.tool_response | type) == "object"
  then (.tool_response.exit_code // .tool_response.exitCode // "0")
  else "0"
  end' 2>/dev/null || echo "0")

# Only check when the command exited 0 (claimed success)
if [[ "$EXIT_CODE" != "0" ]]; then
  printf '%s\n' "$INPUT"
  exit 0
fi

# Allowlist of command patterns → expected port
# Format: "pattern|port"
ALLOWLIST=(
  "docker compose up|5436"
  "docker-compose up|5436"
  "infra-up|5436"
)

MATCHED_PORT=""
for entry in "${ALLOWLIST[@]}"; do
  PATTERN="${entry%%|*}"
  PORT="${entry##*|}"
  if echo "$COMMAND" | grep -qF "$PATTERN"; then
    MATCHED_PORT="$PORT"
    break
  fi
done

if [[ -z "$MATCHED_PORT" ]]; then
  printf '%s\n' "$INPUT"
  exit 0
fi

# Check if the expected port is actually listening
if ! lsof -nP -iTCP:"$MATCHED_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  # Inject warning as hookSpecificOutput — must be valid JSON
  echo "$INPUT" | jq --arg port "$MATCHED_PORT" '
    .hookSpecificOutput = (.hookSpecificOutput // {}) |
    .hookSpecificOutput.message = (
      [(.hookSpecificOutput.message // ""), ("WARNING: Command claimed success but port " + $port + " is not listening. Verify state.")]
      | map(select(length > 0))
      | join("\n\n")
    )'
  exit 0
fi

printf '%s\n' "$INPUT"
exit 0
