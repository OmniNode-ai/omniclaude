#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Thin dispatch surface over the watchdog reducer.
# The reducer is the permanent logic: omniclaude.shared.models.model_watchdog_state
#
# watchdog-state-read.sh — Read watchdog state for a loop
#
# Returns the current escalation level, recent failure history, and
# recommended action for a given loop. Used by the watchdog-check.sh
# escalation script and by CronCreate watchdog prompts.
#
# Usage:
#   watchdog-state-read.sh <loop_name>           # Human-readable summary
#   watchdog-state-read.sh <loop_name> --json    # Raw JSON for the loop
#   watchdog-state-read.sh <loop_name> --level   # Just the escalation level (0-5)
#   watchdog-state-read.sh <loop_name> --action  # Just the recommended action
#
# Exit codes:
#   0: State read successfully
#   1: Error (missing jq, bad arguments)
#   2: No state file exists (first run)

set -euo pipefail

ONEX_REGISTRY_ROOT="${ONEX_REGISTRY_ROOT:?ONEX_REGISTRY_ROOT required}"
STATE_FILE="${ONEX_REGISTRY_ROOT}/.onex_state/watchdog/loop-health.json"

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------

LOOP_NAME="${1:?Usage: watchdog-state-read.sh <loop_name> [--json|--level|--action]}"
OUTPUT_MODE="${2:---summary}"

if [[ "${LOOP_NAME}" != "closeout" && "${LOOP_NAME}" != "buildloop" ]]; then
  echo "ERROR: loop_name must be 'closeout' or 'buildloop', got '${LOOP_NAME}'" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Check state file exists
# ---------------------------------------------------------------------------

if [[ ! -f "${STATE_FILE}" ]]; then
  case "${OUTPUT_MODE}" in
    --json)  echo '{"runs":[],"failure_streaks":{},"escalation_level":0,"actions_taken":[]}' ;;
    --level) echo "0" ;;
    --action) echo "restart" ;;
    *)
      echo "No watchdog state file found (first run)."
      echo "Recommended action: restart"
      ;;
  esac
  exit 2
fi

if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required but not found" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Escalation level to action mapping
# ---------------------------------------------------------------------------

level_to_action() {
  local level="$1"
  local policy_file
  policy_file="$(cd "$(dirname "$0")" && pwd)/watchdog-escalation-policy.yaml"

  # Try declarative policy lookup first
  if [[ -f "${policy_file}" ]] && command -v python3 &>/dev/null; then
    local result
    result=$(python3 -c "
import yaml, sys
with open('${policy_file}') as f:
    policy = yaml.safe_load(f)
level = int(${level})
for level_def in policy['escalation_levels']:
    if level_def['level'] == level:
        print(level_def['action'])
        sys.exit(0)
# Fallback: highest level
print(policy['escalation_levels'][-1]['action'])
" 2>/dev/null) && { echo "${result}"; return; }
  fi

  # Hardcoded fallback
  case "${level}" in
    0) echo "restart" ;;
    1) echo "restart" ;;
    2) echo "investigate" ;;
    3) echo "fix" ;;
    4) echo "ticket" ;;
    *) echo "alert_user" ;;
  esac
}

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

LEVEL=$(jq -r ".loops.${LOOP_NAME}.escalation_level // 0" "${STATE_FILE}")
ACTION=$(level_to_action "${LEVEL}")

case "${OUTPUT_MODE}" in
  --json)
    jq ".loops.${LOOP_NAME}" "${STATE_FILE}"
    ;;

  --level)
    echo "${LEVEL}"
    ;;

  --action)
    echo "${ACTION}"
    ;;

  --summary|*)
    echo "=== Watchdog State: ${LOOP_NAME} ==="
    echo "Escalation level: ${LEVEL}"
    echo "Recommended action: ${ACTION}"
    echo ""

    # Show active failure streaks
    STREAKS=$(jq -r ".loops.${LOOP_NAME}.failure_streaks | to_entries[] | select(.value > 0) | \"\(.key): \(.value) consecutive failures\"" "${STATE_FILE}" 2>/dev/null)
    if [[ -n "${STREAKS}" ]]; then
      echo "Active failure streaks:"
      echo "${STREAKS}" | while read -r line; do echo "  ${line}"; done
      echo ""
    fi

    # Show last 5 runs
    echo "Recent runs:"
    jq -r ".loops.${LOOP_NAME}.runs[:5][] | \"  [\(.timestamp)] \(.result) phase=\(.phase)\(if .error_message then \" error=\" + .error_message else \"\" end)\"" "${STATE_FILE}" 2>/dev/null || echo "  (none)"
    echo ""

    # Show recent actions taken
    ACTIONS=$(jq -r ".loops.${LOOP_NAME}.actions_taken[:3][]? | \"  [\(.timestamp)] \(.action) — \(.detail)\"" "${STATE_FILE}" 2>/dev/null)
    if [[ -n "${ACTIONS}" ]]; then
      echo "Recent actions:"
      echo "${ACTIONS}"
    fi
    ;;
esac
