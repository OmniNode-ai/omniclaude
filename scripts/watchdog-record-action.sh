#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Thin dispatch surface over the watchdog reducer.
# The reducer is the permanent logic: omniclaude.shared.models.model_watchdog_state
#
# watchdog-record-action.sh — Record an action taken by the watchdog
#
# Usage:
#   watchdog-record-action.sh <loop_name> <action> <detail>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONEX_REGISTRY_ROOT="${ONEX_REGISTRY_ROOT:?ONEX_REGISTRY_ROOT required}"
export ONEX_REGISTRY_ROOT
STATE_FILE="${ONEX_REGISTRY_ROOT}/.onex_state/watchdog/loop-health.json"

LOOP_NAME="${1:?Usage: watchdog-record-action.sh <loop_name> <action> <detail>}"
ACTION="${2:?Usage: watchdog-record-action.sh <loop_name> <action> <detail>}"
DETAIL="${3:?Usage: watchdog-record-action.sh <loop_name> <action> <detail>}"

# Dispatch to Python reducer
REDUCER_CLI="${SCRIPT_DIR}/watchdog_reducer_cli.py"
REPO_PYTHON="${SCRIPT_DIR}/../.venv/bin/python"

PYTHON_BIN=""
if [[ -x "${REPO_PYTHON}" ]]; then PYTHON_BIN="${REPO_PYTHON}";
elif command -v python3 &>/dev/null; then PYTHON_BIN="python3"; fi

if [[ -n "${PYTHON_BIN}" ]] && [[ -f "${REDUCER_CLI}" ]]; then
  exec "${PYTHON_BIN}" "${REDUCER_CLI}" action "${LOOP_NAME}" "${ACTION}" "${DETAIL}"
fi

# Fallback: jq
DETAIL="${DETAIL:0:200}"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
MAX_ACTIONS=20

if [[ "${LOOP_NAME}" != "closeout" && "${LOOP_NAME}" != "buildloop" ]]; then
  echo "ERROR: loop_name must be 'closeout' or 'buildloop', got '${LOOP_NAME}'" >&2
  exit 1
fi

if [[ ! -f "${STATE_FILE}" ]]; then
  echo "WARN: No state file found. Run watchdog-state-write.sh first." >&2
  exit 0
fi

if ! command -v jq &>/dev/null; then
  echo "ERROR: neither python3 nor jq found" >&2
  exit 1
fi

TEMP_FILE="${STATE_FILE}.tmp.$$"

jq --arg loop "${LOOP_NAME}" \
   --arg action "${ACTION}" \
   --arg detail "${DETAIL}" \
   --arg ts "${TIMESTAMP}" \
   --argjson max "${MAX_ACTIONS}" \
   '
   .loops[$loop].actions_taken = (
     [{
       "action": $action,
       "detail": $detail,
       "timestamp": $ts
     }] + (.loops[$loop].actions_taken // [])
   )[:$max]
   ' "${STATE_FILE}" > "${TEMP_FILE}"

mv "${TEMP_FILE}" "${STATE_FILE}"

echo "Recorded action: ${ACTION} for ${LOOP_NAME}"
