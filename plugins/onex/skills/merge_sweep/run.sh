#!/usr/bin/env bash
# run.sh — Headless launcher for merge-sweep overnight pipelines
#
# Usage:
#   ./run.sh [additional args]
#   ./run.sh --repos omniclaude,omnibase_core
#   ./run.sh --skip-polish --since 2026-03-01
#
# Invokes claude -p (headless/print mode) with a constrained --allowedTools list
# to prevent passivity and force completion without interactive approval gates.
#
# Failure doctrine: fail-fast with checkpointable state.
# - On missing credentials: exit 2 immediately (non-retryable)
# - On ambiguity: emit structured JSON to stderr, exit 3 (checkpointable)
# - On blocked tool use: exit 4 (allowedTools violation — never silently skip)
# - On partial completion: exit 5 (some repos failed; state file lists failures)
#
# OMN-6235

set -euo pipefail

# Credentials check — fail-fast before any API calls
if ! gh auth status &>/dev/null; then
  echo '{"error":"missing_credentials","required":"gh auth (GitHub CLI)","exit_code":2}' >&2
  exit 2
fi

ADDITIONAL_ARGS=("$@")
RUN_ID="$(date +%Y%m%d_%H%M%S)_$$"

# Tool allowlist for merge-sweep overnight runs.
# Covers: GitHub CLI (via Bash), PR state reads, file writes for worktrees.
# Does NOT include: browser tools, arbitrary web fetch, Linear write tools.
ALLOWED_TOOLS=(
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
  "mcp__linear-server__save_comment"
)
ALLOWED_TOOLS_CSV=$(IFS=','; echo "${ALLOWED_TOOLS[*]}")

# State checkpoint directory
STATE_DIR="${ONEX_STATE_DIR:-${HOME}/.onex_state}/merge-sweep"
mkdir -p "${STATE_DIR}"
CHECKPOINT_FILE="${STATE_DIR}/run_${RUN_ID}.json"

cat > "${CHECKPOINT_FILE}" <<CHECKPOINT
{
  "run_id": "${RUN_ID}",
  "launched_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "mode": "headless",
  "status": "started",
  "additional_args": $(printf '%s\n' "${ADDITIONAL_ARGS[@]:-}" | python3 -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")
}
CHECKPOINT

echo "[merge-sweep:run.sh] Launching headless. Run: ${RUN_ID} | State: ${CHECKPOINT_FILE}"

# Launch claude -p (headless/print mode)
claude -p \
  --allowedTools "${ALLOWED_TOOLS_CSV}" \
  "Run the merge-sweep skill --mode close-out --run-id ${RUN_ID} ${ADDITIONAL_ARGS[*]:-}.

HEADLESS MODE: This is an overnight pipeline run. Apply fail-fast doctrine:
- Do NOT pause for human input at any point
- Do NOT use browser or web tools
- MODE is close-out — do NOT implement features or create tickets
- If credentials are missing: write error to ${STATE_DIR}/credential_failure.json and exit
- If ambiguous state is encountered: write to ${STATE_DIR}/ambiguity_$(date +%s).json and exit
- Partial failure is acceptable: record failed repos in ModelSkillResult and continue others
- On completion: write final ModelSkillResult to ${STATE_DIR}/result_${RUN_ID}.json

Resume: re-run with same --run-id to pick up from last checkpoint (idempotency ledger applies)"

EXIT_CODE=$?
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
