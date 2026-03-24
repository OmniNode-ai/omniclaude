#!/usr/bin/env bash
# run.sh — Headless launcher for epic-team overnight pipelines
#
# Usage:
#   ./run.sh <epic_id> [additional args]
#   ./run.sh OMN-2000 --dry-run
#   ./run.sh OMN-2000 --resume
#
# Invokes claude -p (headless/print mode) with a constrained --allowedTools list
# to prevent passivity and force completion without interactive approval gates.
#
# Failure doctrine: fail-fast with checkpointable state.
# - On missing epic_id: exit 1 immediately with structured error (no partial run)
# - On missing credentials: exit 2 immediately (non-retryable)
# - On ambiguity: emit structured JSON to stderr, exit 3 (checkpointable — state on disk)
# - On blocked tool use: exit 4 (allowedTools violation — never silently skip)
#
# OMN-6235

set -euo pipefail

EPIC_ID="${1:-}"
if [[ -z "${EPIC_ID}" ]]; then
  echo '{"error":"missing_epic_id","message":"Usage: run.sh <epic_id> [args]","exit_code":1}' >&2
  exit 1
fi
shift

# Validate epic ID format (OMN-NNNN)
if ! [[ "${EPIC_ID}" =~ ^OMN-[0-9]+$ ]]; then
  echo "{\"error\":\"invalid_epic_id\",\"value\":\"${EPIC_ID}\",\"expected\":\"OMN-NNNN\",\"exit_code\":1}" >&2
  exit 1
fi

# Credentials check — fail-fast before any API calls
if [[ -z "${LINEAR_API_KEY:-}" && -z "${MCP_LINEAR_API_KEY:-}" ]]; then
  echo '{"error":"missing_credentials","required":"LINEAR_API_KEY or MCP_LINEAR_API_KEY","exit_code":2}' >&2
  exit 2
fi

ADDITIONAL_ARGS=("$@")

# Tool allowlist for epic-team overnight runs.
# Covers: Linear/GitHub MCP, Task dispatch, file writes for worktrees, bash for git ops.
# Does NOT include: browser tools, arbitrary web fetch, interactive UI tools.
ALLOWED_TOOLS=(
  "mcp__linear-server__get_issue"
  "mcp__linear-server__list_issues"
  "mcp__linear-server__save_issue"
  "mcp__linear-server__save_comment"
  "mcp__linear-server__list_projects"
  "mcp__linear-server__get_project"
  "mcp__linear-server__list_teams"
  "Bash"
  "Read"
  "Write"
  "Edit"
  "Glob"
  "Grep"
  "Task"
  "TaskCreate"
  "TaskUpdate"
  "TaskGet"
  "TaskList"
  "SendMessage"
)
ALLOWED_TOOLS_CSV=$(IFS=','; echo "${ALLOWED_TOOLS[*]}")

# State checkpoint directory — written before dispatch for crash recovery
STATE_DIR="${ONEX_STATE_DIR:-${HOME}/.onex_state}/epics/${EPIC_ID}"
mkdir -p "${STATE_DIR}"
CHECKPOINT_FILE="${STATE_DIR}/run_headless_$(date +%Y%m%d_%H%M%S).json"

cat > "${CHECKPOINT_FILE}" <<CHECKPOINT
{
  "epic_id": "${EPIC_ID}",
  "launched_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "mode": "headless",
  "status": "started",
  "additional_args": $(printf '%s\n' "${ADDITIONAL_ARGS[@]:-}" | python3 -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")
}
CHECKPOINT

echo "[epic-team:run.sh] Launching headless. Epic: ${EPIC_ID} | State: ${CHECKPOINT_FILE}"

# Launch claude -p (headless/print mode)
# --allowedTools: constrain to the minimum set needed; prevents passivity via denied tool attempts
# FAILURE DOCTRINE: claude -p exits non-zero on tool denial or unrecoverable error.
#   - Ambiguity → checkpoint state, emit structured error to stderr, exit 3
#   - Blocked tool → allowedTools violation logged; exit 4
#   - Context limit → state is in STATE_DIR; re-run with --resume to continue
claude -p \
  --allowedTools "${ALLOWED_TOOLS_CSV}" \
  "Run the epic-team skill for ${EPIC_ID} --mode build ${ADDITIONAL_ARGS[*]:-}.

HEADLESS MODE: This is an overnight pipeline run. Apply fail-fast doctrine:
- Do NOT pause for human input at any point
- Do NOT use browser or web tools
- If credentials are missing: write error to ${STATE_DIR}/credential_failure.json and exit
- If ambiguous: write structured diagnosis to ${STATE_DIR}/ambiguity_$(date +%s).json and exit
- If context limit approaches: checkpoint state to ${STATE_DIR}/state.yaml then stop cleanly
- All state writes MUST precede any exit — checkpointable state is required

Resume checkpoint: ${CHECKPOINT_FILE}"

EXIT_CODE=$?
# Update checkpoint with final status
python3 -c "
import json, sys
try:
    with open('${CHECKPOINT_FILE}') as f:
        data = json.load(f)
    data['status'] = 'completed' if ${EXIT_CODE} == 0 else 'failed'
    data['exit_code'] = ${EXIT_CODE}
    data['completed_at'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
    with open('${CHECKPOINT_FILE}', 'w') as f:
        json.dump(data, f, indent=2)
except Exception as e:
    print(f'WARNING: Could not update checkpoint: {e}', file=sys.stderr)
" 2>/dev/null || true

exit "${EXIT_CODE}"
