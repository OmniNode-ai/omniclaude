#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Calls the watchdog reducer (Python) to record a run result.
# The reducer is the permanent logic — this shell script is just a dispatch surface.
# See: omniclaude.shared.models.model_watchdog_state.reduce()
#
# watchdog-state-write.sh — Record a loop run result to the watchdog state file
#
# Usage:
#   watchdog-state-write.sh <loop_name> <result> <phase> [error_message]
#
# Arguments:
#   loop_name:     "closeout" or "buildloop"
#   result:        "pass" or "fail"
#   phase:         Phase that failed (e.g., "B1_runtime_sweep") or "complete" on success
#   error_message: Optional error description (truncated to 200 chars)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OMNI_HOME="${OMNI_HOME:-/Users/jonah/Code/omni_home}"
export OMNI_HOME

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------

LOOP_NAME="${1:?Usage: watchdog-state-write.sh <loop_name> <result> <phase> [error_message]}"
RESULT="${2:?Usage: watchdog-state-write.sh <loop_name> <result> <phase> [error_message]}"
PHASE="${3:?Usage: watchdog-state-write.sh <loop_name> <result> <phase> [error_message]}"
ERROR_MSG="${4:-}"

# Validate
if [[ "${RESULT}" != "pass" && "${RESULT}" != "fail" ]]; then
  echo "ERROR: result must be 'pass' or 'fail', got '${RESULT}'" >&2
  exit 1
fi
if [[ "${LOOP_NAME}" != "closeout" && "${LOOP_NAME}" != "buildloop" ]]; then
  echo "ERROR: loop_name must be 'closeout' or 'buildloop', got '${LOOP_NAME}'" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Dispatch to Python reducer
# ---------------------------------------------------------------------------

# Try the Python reducer CLI first (canonical path)
REDUCER_CLI="${SCRIPT_DIR}/watchdog_reducer_cli.py"
REPO_PYTHON="${SCRIPT_DIR}/../.venv/bin/python"

# Prefer the project venv Python (has all deps), fall back to system python3
PYTHON_BIN=""
if [[ -x "${REPO_PYTHON}" ]]; then PYTHON_BIN="${REPO_PYTHON}";
elif command -v python3 &>/dev/null; then PYTHON_BIN="python3"; fi

if [[ -n "${PYTHON_BIN}" ]] && [[ -f "${REDUCER_CLI}" ]]; then
  exec "${PYTHON_BIN}" "${REDUCER_CLI}" run "${LOOP_NAME}" "${RESULT}" "${PHASE}" "${ERROR_MSG}"
fi

# ---------------------------------------------------------------------------
# Fallback: jq-based state mutation (degraded mode — no FSM, no intents)
# ---------------------------------------------------------------------------

STATE_DIR="${OMNI_HOME}/.onex_state/watchdog"
STATE_FILE="${STATE_DIR}/loop-health.json"
MAX_HISTORY=20

mkdir -p "${STATE_DIR}"

if [[ ! -f "${STATE_FILE}" ]]; then
  cat > "${STATE_FILE}" << 'JSON'
{
  "schema_version": "1.0",
  "loops": {
    "closeout": {"runs": [], "failure_streaks": {}, "escalation_level": 0, "actions_taken": [], "fsm_state": "healthy"},
    "buildloop": {"runs": [], "failure_streaks": {}, "escalation_level": 0, "actions_taken": [], "fsm_state": "healthy"}
  }
}
JSON
fi

if ! command -v jq &>/dev/null; then
  echo "ERROR: neither python3 nor jq found" >&2
  exit 1
fi

ERROR_MSG="${ERROR_MSG:0:200}"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

NEW_RUN=$(jq -n \
  --arg result "${RESULT}" \
  --arg phase "${PHASE}" \
  --arg error "${ERROR_MSG}" \
  --arg ts "${TIMESTAMP}" \
  '{
    "result": $result,
    "phase": $phase,
    "error_message": (if $error == "" then null else $error end),
    "timestamp": $ts,
    "correlation_id": "jq-fallback"
  }')

TEMP_FILE="${STATE_FILE}.tmp.$$"

jq --argjson new_run "${NEW_RUN}" \
   --arg loop "${LOOP_NAME}" \
   --argjson max_history "${MAX_HISTORY}" \
   '
   .loops[$loop].runs = ([$new_run] + .loops[$loop].runs)[:$max_history] |
   if $new_run.result == "fail" then
     .loops[$loop].failure_streaks[$new_run.phase] = (
       (.loops[$loop].failure_streaks[$new_run.phase] // 0) + 1
     ) |
     .loops[$loop].escalation_level = (
       [.loops[$loop].failure_streaks | to_entries[].value] | max // 0
     ) |
     if .loops[$loop].escalation_level > 5 then
       .loops[$loop].escalation_level = 5
     else . end
   else
     .loops[$loop].failure_streaks = {} |
     .loops[$loop].escalation_level = 0 |
     .loops[$loop].fsm_state = "healthy"
   end
   ' "${STATE_FILE}" > "${TEMP_FILE}"

mv "${TEMP_FILE}" "${STATE_FILE}"
echo "Watchdog state updated: loop=${LOOP_NAME} result=${RESULT} phase=${PHASE} escalation=$(jq -r ".loops.${LOOP_NAME}.escalation_level" "${STATE_FILE}")"
