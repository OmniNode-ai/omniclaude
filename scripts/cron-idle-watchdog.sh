#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# cron-idle-watchdog.sh — Headless idle-watchdog tick [OMN-9036]
#
# STUB: The session-idle classifier from plan Task 9 has not yet shipped.
# Until then, this script emits a single friction event via /onex:record_friction
# so the blocker stays visible in the friction registry. When the classifier
# lands, replace the prompt body with the real idle-watchdog invocation.
#
# Follow-up: wire classifier (plan Task 9) and swap the prompt below.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONEX_REGISTRY_ROOT="${OMNI_HOME:-${ONEX_REGISTRY_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}}"
STATE_DIR="${ONEX_REGISTRY_ROOT}/.onex_state/idle-watchdog-results"
LOG_DIR="/tmp/idle-watchdog-logs"
PHASE_TIMEOUT=300
RUN_ID="idle-watchdog-$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [[ -f "${HOME}/.omnibase/.env" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.omnibase/.env"
fi

export ONEX_RUN_ID="${RUN_ID}"

ALLOWED_TOOLS="Bash,Read,Write,Edit,Glob,Grep"

preflight() {
  if ! command -v claude &>/dev/null; then
    echo "ERROR: claude CLI not found on PATH" >&2
    exit 1
  fi
}

preflight

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

LOCK_FILE="${STATE_DIR}/cron-idle-watchdog.lock"
LOCK_TIMEOUT=600

if [[ -f "${LOCK_FILE}" ]]; then
  lock_time=$(stat -f %m "${LOCK_FILE}" 2>/dev/null || stat -c %Y "${LOCK_FILE}" 2>/dev/null || echo 0)
  now=$(date +%s)
  age=$(( now - lock_time ))
  if [[ ${age} -lt ${LOCK_TIMEOUT} ]]; then
    echo "SKIP: Previous invocation still running (lock age: ${age}s < ${LOCK_TIMEOUT}s)"
    exit 0
  else
    echo "WARN: Stale lock detected (age: ${age}s). Removing."
    rm -f "${LOCK_FILE}"
  fi
fi

echo "pid=$$ started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${LOCK_FILE}"
trap 'rm -f "${LOCK_FILE}"' EXIT

log() {
  local msg
  msg="[cron-idle-watchdog $(date -u +"%H:%M:%S")] $1"
  echo "${msg}"
  echo "${msg}" >> "${LOG_DIR}/${RUN_ID}.log"
}

log "=== idle-watchdog tick ${RUN_ID} starting (STUB mode) ==="

OUTPUT_FILE="${STATE_DIR}/${RUN_ID}.txt"
# STUB delegate: record a friction event against the missing classifier. When the
# classifier ships (plan Task 9), replace this prompt with the real invocation.
PROMPT='/onex:record_friction --skill cron_idle_watchdog --surface idle_watchdog/tick --severity low --description "idle-watchdog classifier (plan Task 9) not yet shipped; stub tick fired"'

if [[ "${DRY_RUN}" == "true" ]]; then
  log "[DRY RUN] Would execute: claude -p '${PROMPT}' --allowedTools '${ALLOWED_TOOLS}'"
  exit 0
fi

exit_code=0
timeout "${PHASE_TIMEOUT}" claude -p "${PROMPT}" \
  --print \
  --allowedTools "${ALLOWED_TOOLS}" \
  > "${OUTPUT_FILE}" 2>&1 || exit_code=$?

if [[ ${exit_code} -eq 124 ]]; then
  log "TIMEOUT: idle-watchdog exceeded ${PHASE_TIMEOUT}s"
  exit 1
fi

if [[ ${exit_code} -ne 0 ]]; then
  log "FAILED: idle-watchdog exited with code ${exit_code}"
  exit 1
fi

log "idle-watchdog tick ${RUN_ID} complete (STUB)"
exit 0
