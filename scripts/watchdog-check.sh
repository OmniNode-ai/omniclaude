#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Calls the watchdog reducer (Python) to check escalation level.
# The reducer is the permanent logic — this shell script is just a dispatch surface.
# See: omniclaude.shared.models.model_watchdog_state.check_escalation()
#
# watchdog-check.sh — Mechanical escalation policy for cron loop failures
#
# Exit codes match the escalation policy:
#   0: restart (safe to proceed)
#   2: investigate (do NOT restart blindly)
#   3: fix (attempt fix)
#   4: ticket (create Linear ticket)
#   5: alert_user (STOP — do not restart)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OMNI_HOME="${OMNI_HOME:?OMNI_HOME required}"
export OMNI_HOME
STATE_FILE="${OMNI_HOME}/.onex_state/watchdog/loop-health.json"

LOOP_NAME="${1:?Usage: watchdog-check.sh <loop_name>}"

if [[ "${LOOP_NAME}" != "closeout" && "${LOOP_NAME}" != "buildloop" ]]; then
  echo "ERROR: loop_name must be 'closeout' or 'buildloop', got '${LOOP_NAME}'" >&2
  exit 1
fi

# No state file = first run, allow restart
if [[ ! -f "${STATE_FILE}" ]]; then
  echo '{"action":"restart","level":0,"reason":"No watchdog state file — first run","exit_code":0}'
  exit 0
fi

# ---------------------------------------------------------------------------
# Dispatch to Python reducer
# ---------------------------------------------------------------------------

REDUCER_CLI="${SCRIPT_DIR}/watchdog_reducer_cli.py"
REPO_PYTHON="${SCRIPT_DIR}/../.venv/bin/python"

PYTHON_BIN=""
if [[ -x "${REPO_PYTHON}" ]]; then PYTHON_BIN="${REPO_PYTHON}";
elif command -v python3 &>/dev/null; then PYTHON_BIN="python3"; fi

if [[ -n "${PYTHON_BIN}" ]] && [[ -f "${REDUCER_CLI}" ]]; then
  "${PYTHON_BIN}" "${REDUCER_CLI}" check "${LOOP_NAME}"
  exit $?
fi

# ---------------------------------------------------------------------------
# Fallback: jq-based check (degraded mode — no FSM state in output)
# ---------------------------------------------------------------------------

if ! command -v jq &>/dev/null; then
  echo "ERROR: neither python3 nor jq found" >&2
  exit 1
fi

LEVEL=$(jq -r ".loops.${LOOP_NAME}.escalation_level // 0" "${STATE_FILE}")

TOP_PHASE=$(jq -r "
  .loops.${LOOP_NAME}.failure_streaks
  | to_entries | sort_by(-.value) | .[0]
  | if . then .key else \"none\" end
" "${STATE_FILE}")

TOP_STREAK=$(jq -r "
  .loops.${LOOP_NAME}.failure_streaks
  | to_entries | sort_by(-.value) | .[0]
  | if . then .value else 0 end
" "${STATE_FILE}")

LAST_ERROR=$(jq -r "
  .loops.${LOOP_NAME}.runs[0]
  | if . and .result == \"fail\" then .error_message // \"unknown\" else \"none\" end
" "${STATE_FILE}")

LAST_RUN=$(jq -r ".loops.${LOOP_NAME}.runs[0].timestamp // \"never\"" "${STATE_FILE}")

case "${LEVEL}" in
  0|1) ACTION="restart"; EXIT_CODE=0; DESC="Safe to restart" ;;
  2)   ACTION="investigate"; EXIT_CODE=2; DESC="Investigate root cause" ;;
  3)   ACTION="fix"; EXIT_CODE=3; DESC="Attempt fix" ;;
  4)   ACTION="ticket"; EXIT_CODE=4; DESC="Create ticket" ;;
  *)   ACTION="alert_user"; EXIT_CODE=5; DESC="STOP restarting" ;;
esac

if [[ "${TOP_STREAK}" -gt 0 ]]; then
  REASON="Phase '${TOP_PHASE}' has failed ${TOP_STREAK} times consecutively. ${DESC}. Last error: ${LAST_ERROR}"
else
  REASON="${DESC}"
fi

jq -n \
  --arg action "${ACTION}" \
  --argjson level "${LEVEL}" \
  --arg reason "${REASON}" \
  --arg top_phase "${TOP_PHASE}" \
  --argjson top_streak "${TOP_STREAK}" \
  --arg last_error "${LAST_ERROR}" \
  --arg last_run "${LAST_RUN}" \
  --arg loop "${LOOP_NAME}" \
  '{action:$action, level:$level, reason:$reason, loop:$loop, top_failing_phase:$top_phase, consecutive_failures:$top_streak, last_error:$last_error, last_run:$last_run}'

exit "${EXIT_CODE}"
