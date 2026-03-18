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

TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null || true)

if [[ "$TOOL_NAME" != "Bash" ]]; then
  exit 0
fi

COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
inp = d.get('tool_input', {})
print(inp.get('command', ''))
" 2>/dev/null || true)

EXIT_CODE=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
resp = d.get('tool_response', {})
# tool_response may be a string or dict
if isinstance(resp, dict):
    print(resp.get('exit_code', resp.get('exitCode', '0')))
else:
    print('0')
" 2>/dev/null || echo "0")

# Only check when the command exited 0 (claimed success)
if [[ "$EXIT_CODE" != "0" ]]; then
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
  exit 0
fi

# Check if the expected port is actually listening
if ! lsof -nP -iTCP:"$MATCHED_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo ""
  echo "⚠ Command claimed success but port $MATCHED_PORT is not listening. Verify state."
fi

exit 0
