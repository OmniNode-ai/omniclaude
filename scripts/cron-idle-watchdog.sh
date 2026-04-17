#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# cron-idle-watchdog.sh — Headless idle-watchdog tick [OMN-9053]
#
# Reads the last-15-min tool-call log, invokes the activity classifier
# (omniclaude/plugins/onex/hooks/lib/tick_activity_classifier.py) to decide
# whether the tick was idle, and emits a friction event via
# /onex:record_friction only when the tick is classified idle AND the backlog
# is non-empty. Prevents overnight silence-as-compliance (retro §4.4).
#
# Refs:
#   * Plan: docs/plans/2026-04-17-overnight-process-hardening.md Task 9
#   * OMN-9036: original stub this replaces

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONEX_REGISTRY_ROOT="${OMNI_HOME:-${ONEX_REGISTRY_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}}"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
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
export ONEX_UNSAFE_ALLOW_EDITS=1

ALLOWED_TOOLS="Bash,Read,Write,Edit,Glob,Grep"

# Tool-call log. Override via TOOL_CALL_LOG for tests. Default is the standard
# hook tool-call JSONL location under $ONEX_STATE_DIR.
STATE_ROOT="${ONEX_STATE_DIR:-${ONEX_REGISTRY_ROOT}/.onex_state}"
TOOL_CALL_LOG="${TOOL_CALL_LOG:-${STATE_ROOT}/hooks/tool-calls.jsonl}"

# Backlog signal. Override via BACKLOG_COUNT for tests. Default 0 means
# "assume no backlog" (safest — no friction emitted) unless the caller sets it.
BACKLOG_COUNT="${BACKLOG_COUNT:-0}"

preflight() {
  if ! command -v claude &>/dev/null; then
    echo "ERROR: claude CLI not found on PATH" >&2
    exit 1
  fi
  PYTHON_BIN="${PLUGIN_PYTHON_BIN:-python3}"
  if ! command -v "${PYTHON_BIN}" &>/dev/null; then
    echo "ERROR: python interpreter '${PYTHON_BIN}' not found" >&2
    exit 1
  fi
}

preflight

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

LOCK_DIR="${STATE_DIR}/cron-idle-watchdog.lock.d"
LOCK_TIMEOUT=600

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
  if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
    echo "SKIP: Lock re-acquired by another process after stale-cleanup"
    exit 0
  fi
fi

echo "pid=$$ started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${LOCK_DIR}/meta"
trap 'rm -rf "${LOCK_DIR}"' EXIT

log() {
  local msg
  msg="[cron-idle-watchdog $(date -u +"%H:%M:%S")] $1"
  echo "${msg}"
  echo "${msg}" >> "${LOG_DIR}/${RUN_ID}.log"
}

log "=== idle-watchdog tick ${RUN_ID} starting ==="
log "tool_call_log=${TOOL_CALL_LOG} backlog_count=${BACKLOG_COUNT}"

CLASSIFY_PY_SCRIPT="$(cat <<'PYEOF'
import json, sys, pathlib

lib_dir = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(lib_dir))

try:
    from tick_activity_classifier import is_idle_tick
except Exception as exc:
    print(f"classifier import failed: {exc}", file=sys.stderr)
    sys.exit(2)

calls = []
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        calls.append(json.loads(line))
    except json.JSONDecodeError:
        continue

sys.exit(0 if is_idle_tick(calls) else 1)
PYEOF
)"

classify() {
  # Invoke the classifier on stdin-fed JSONL (one tool-call record per line).
  # Exits 0 when tick is idle, 1 when active, 2 on classifier error.
  "${PYTHON_BIN}" -c "${CLASSIFY_PY_SCRIPT}" "$@"
}

# Collect last-15-min tool calls. If log missing, treat as empty (idle).
CALLS_INPUT=""
if [[ -f "${TOOL_CALL_LOG}" ]]; then
  # Filter to lines newer than 15 min via file mtime + tail. Simplest: take
  # last 1000 lines; classifier tolerates slightly older entries since the
  # ratio check is order-insensitive.
  CALLS_INPUT="$(tail -n 1000 "${TOOL_CALL_LOG}" 2>/dev/null || true)"
fi

LIB_DIR="${REPO_ROOT}/plugins/onex/hooks/lib"

idle_exit=0
echo "${CALLS_INPUT}" | classify "${LIB_DIR}" || idle_exit=$?

case ${idle_exit} in
  0)
    log "tick classified: IDLE"
    IS_IDLE=true
    ;;
  1)
    log "tick classified: ACTIVE"
    IS_IDLE=false
    ;;
  *)
    log "classifier error (exit ${idle_exit}); treating as ACTIVE to avoid false friction"
    IS_IDLE=false
    ;;
esac

if [[ "${IS_IDLE}" != "true" ]]; then
  log "idle-watchdog tick ${RUN_ID} complete (active — no friction emitted)"
  exit 0
fi

if [[ "${BACKLOG_COUNT}" -le 0 ]]; then
  log "idle-watchdog tick ${RUN_ID} complete (idle but backlog=0 — no friction emitted)"
  exit 0
fi

OUTPUT_FILE="${STATE_DIR}/${RUN_ID}.txt"
DESCRIPTION="idle tick detected: mutating/total < 0.1 with backlog=${BACKLOG_COUNT}"
PROMPT="/onex:record_friction --skill cron_idle_watchdog --surface idle_watchdog/tick --severity medium --description \"${DESCRIPTION}\""

if [[ "${DRY_RUN}" == "true" ]]; then
  log "[DRY RUN] Would execute: claude -p '${PROMPT}' --allowedTools '${ALLOWED_TOOLS}'"
  exit 0
fi

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
  log "TIMEOUT: idle-watchdog exceeded ${PHASE_TIMEOUT}s"
  exit 1
fi

if [[ ${exit_code} -ne 0 ]]; then
  log "FAILED: idle-watchdog exited with code ${exit_code}"
  exit 1
fi

log "idle-watchdog tick ${RUN_ID} complete (idle — friction emitted)"
exit 0
