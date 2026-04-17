#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# cron-overseer-verify.sh — Headless overseer-verify tick [OMN-9036]
#
# Thin wrapper that delegates to the /onex:session skill (overseer-verify phase)
# via claude -p. No inline business logic. See setup-session-crons.sh for the
# canonical overseer-verify prompt.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONEX_REGISTRY_ROOT="${OMNI_HOME:-${ONEX_REGISTRY_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}}"
STATE_DIR="${ONEX_REGISTRY_ROOT}/.onex_state/overseer-verify-results"
LOG_DIR="/tmp/overseer-verify-logs"
PHASE_TIMEOUT=900
RUN_ID="overseer-verify-$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
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
export ONEX_UNSAFE_ALLOW_EDITS=1

ALLOWED_TOOLS="Bash,Read,Write,Edit,Glob,Grep,mcp__linear-server__*"

preflight() {
  if ! command -v claude &>/dev/null; then
    echo "ERROR: claude CLI not found on PATH" >&2
    exit 1
  fi
}

preflight

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

LOCK_FILE="${STATE_DIR}/cron-overseer-verify.lock"
LOCK_TIMEOUT=1800

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
  msg="[cron-overseer-verify $(date -u +"%H:%M:%S")] $1"
  echo "${msg}"
  echo "${msg}" >> "${LOG_DIR}/${RUN_ID}.log"
}

log "=== overseer-verify tick ${RUN_ID} starting ==="

OUTPUT_FILE="${STATE_DIR}/${RUN_ID}.txt"
PROMPT='/onex:session --phase overseer-verify'

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
  log "TIMEOUT: overseer-verify exceeded ${PHASE_TIMEOUT}s"
  exit 1
fi

if [[ ${exit_code} -ne 0 ]]; then
  log "FAILED: overseer-verify exited with code ${exit_code}"
  exit 1
fi

log "overseer-verify tick ${RUN_ID} complete"
exit 0
