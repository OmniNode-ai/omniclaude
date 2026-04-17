#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# cron-dispatch-engine.sh — Headless dispatch-engine tick [OMN-9036]
#
# Thin wrapper that delegates to the /onex:dispatch_engine skill via claude -p.
# Mirrors the pattern in cron-merge-sweep.sh; no inline business logic.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONEX_REGISTRY_ROOT="${OMNI_HOME:-${ONEX_REGISTRY_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}}"
STATE_DIR="${ONEX_REGISTRY_ROOT}/.onex_state/dispatch-engine-results"
LOG_DIR="/tmp/dispatch-engine-logs"
PHASE_TIMEOUT=900
RUN_ID="dispatch-engine-$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
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

# Atomic directory-based lock (mkdir is atomic across processes).
LOCK_DIR="${STATE_DIR}/cron-dispatch-engine.lock.d"
LOCK_TIMEOUT=1800

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  lock_time=$(stat -f %m "${LOCK_DIR}" 2>/dev/null || stat -c %Y "${LOCK_DIR}" 2>/dev/null || echo 0)
  now=$(date +%s)
  age=$(( now - lock_time ))
  if [[ ${age} -lt ${LOCK_TIMEOUT} ]]; then
    echo "SKIP: Previous invocation still running (lock age: ${age}s < ${LOCK_TIMEOUT}s)"
    exit 0
  fi
  echo "WARN: Stale lock detected (age: ${age}s). Removing."
  rm -rf "${LOCK_DIR}"
  # Single retry; if it still fails, a third process won the race — bail gracefully.
  if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
    echo "SKIP: Lock re-acquired by another process after stale-cleanup"
    exit 0
  fi
fi

echo "pid=$$ started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${LOCK_DIR}/meta"
trap 'rm -rf "${LOCK_DIR}"' EXIT

log() {
  local msg
  msg="[cron-dispatch-engine $(date -u +"%H:%M:%S")] $1"
  echo "${msg}"
  echo "${msg}" >> "${LOG_DIR}/${RUN_ID}.log"
}

log "=== dispatch-engine tick ${RUN_ID} starting ==="
log "ONEX_REGISTRY_ROOT: ${ONEX_REGISTRY_ROOT}"

OUTPUT_FILE="${STATE_DIR}/${RUN_ID}.txt"
PROMPT='/onex:dispatch_engine'

if [[ "${DRY_RUN}" == "true" ]]; then
  log "[DRY RUN] Would execute: claude -p '${PROMPT}' --allowedTools '${ALLOWED_TOOLS}'"
  exit 0
fi

# timeout / gtimeout fallback (macOS Homebrew ships gtimeout; BSD base has neither).
timeout_cmd=""
if command -v timeout &>/dev/null; then
  timeout_cmd="timeout ${PHASE_TIMEOUT}"
elif command -v gtimeout &>/dev/null; then
  timeout_cmd="gtimeout ${PHASE_TIMEOUT}"
fi

exit_code=0
${timeout_cmd} claude -p "${PROMPT}" \
  --print \
  --allowedTools "${ALLOWED_TOOLS}" \
  > "${OUTPUT_FILE}" 2>&1 || exit_code=$?

if [[ ${exit_code} -eq 124 ]]; then
  log "TIMEOUT: dispatch-engine exceeded ${PHASE_TIMEOUT}s"
  exit 1
fi

if [[ ${exit_code} -ne 0 ]]; then
  log "FAILED: dispatch-engine exited with code ${exit_code}"
  exit 1
fi

log "dispatch-engine tick ${RUN_ID} complete"
exit 0
