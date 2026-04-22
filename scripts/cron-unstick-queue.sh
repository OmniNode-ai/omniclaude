#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# cron-unstick-queue.sh — launchd tick wrapper for /onex:unstick_queue [OMN-9065]
#
# Invokes scripts/lib/run-unstick-queue.py which probes each repo's merge queue,
# classifies the head PR via queue_stall_classifier, and performs
# dequeue+re-enqueue for PRs stuck AWAITING_CHECKS with an orphaned third-party
# check-run. Escalations (same PR unstuck >=3 times in 1h) emit a friction event
# via /onex:record_friction instead of continuing to auto-heal.
#
# Usage:
#   ./scripts/cron-unstick-queue.sh                   # live run
#   ./scripts/cron-unstick-queue.sh --dry-run          # classify + log only
#   ./scripts/cron-unstick-queue.sh --repos omniclaude # limit scope
#
# Design matches cron-idle-watchdog.sh / cron-merge-sweep.sh:
#   * PID-file lock prevents overlapping ticks
#   * Timeout via `timeout` / `gtimeout`
#   * Fail-open on per-repo errors (runner counts them); hard-fail only on
#     preflight gaps or runner crash
#   * Never swallows the runner exit code silently

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONEX_REGISTRY_ROOT="${ONEX_REGISTRY_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
PHASE_TIMEOUT=300
RUN_ID="unstick-queue-$(date -u +"%Y-%m-%dT%H-%M-%SZ")"

DRY_RUN=false
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --repos) EXTRA_ARGS+=("--repos" "$2"); shift 2 ;;
    --repos=*) EXTRA_ARGS+=("--repos" "${1#*=}"); shift ;;
    --awaiting-minutes) EXTRA_ARGS+=("--awaiting-minutes" "$2"); shift 2 ;;
    --orphan-minutes) EXTRA_ARGS+=("--orphan-minutes" "$2"); shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -f "${HOME}/.omnibase/.env" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.omnibase/.env"
fi

export ONEX_RUN_ID="${RUN_ID}"
export ONEX_STATE_DIR="${ONEX_STATE_DIR:-${ONEX_REGISTRY_ROOT}/.onex_state}"
# Derive STATE_DIR and LOG_DIR after ONEX_STATE_DIR is finalised so a
# configured state root (from env or .omnibase/.env) is honoured for
# lock files, result ndjson, and diagnostic logs.
STATE_DIR="${ONEX_STATE_DIR}/queue-unstick-results"
LOG_DIR="${ONEX_STATE_DIR}/queue-unstick-logs"

preflight() {
  if ! command -v gh &>/dev/null; then
    echo "ERROR: gh CLI not found on PATH" >&2
    exit 2
  fi
  if ! command -v uv &>/dev/null; then
    echo "ERROR: uv not found on PATH" >&2
    exit 2
  fi
}

preflight

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

LOCK_DIR="${STATE_DIR}/cron-unstick-queue.lock.d"
LOCK_TIMEOUT=600

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  lock_time=$(stat -f %m "${LOCK_DIR}" 2>/dev/null || stat -c %Y "${LOCK_DIR}" 2>/dev/null || echo 0)
  now=$(date +%s)
  age=$(( now - lock_time ))
  if [[ ${age} -lt ${LOCK_TIMEOUT} ]]; then
    echo "SKIP: previous invocation still running (lock age ${age}s)"
    exit 0
  fi
  echo "WARN: stale lock (age ${age}s) — removing"
  rm -rf "${LOCK_DIR}"
  if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
    echo "SKIP: lock re-acquired by another process"
    exit 0
  fi
fi

echo "pid=$$ started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${LOCK_DIR}/meta"
trap 'rm -rf "${LOCK_DIR}"' EXIT

log() {
  local msg
  msg="[cron-unstick-queue $(date -u +"%H:%M:%S")] $1"
  echo "${msg}"
  echo "${msg}" >> "${LOG_DIR}/${RUN_ID}.log"
}

log "=== unstick-queue tick ${RUN_ID} starting (dry_run=${DRY_RUN}) ==="

RUNNER="${SCRIPT_DIR}/lib/run-unstick-queue.py"
if [[ ! -f "${RUNNER}" ]]; then
  log "ABORT: runner missing at ${RUNNER}"
  exit 2
fi

timeout_cmd=""
if command -v timeout &>/dev/null; then
  timeout_cmd="timeout ${PHASE_TIMEOUT}"
elif command -v gtimeout &>/dev/null; then
  timeout_cmd="gtimeout ${PHASE_TIMEOUT}"
fi

OUTPUT_FILE="${STATE_DIR}/${RUN_ID}.ndjson"

RUNNER_ARGS=()
if [[ "${DRY_RUN}" == "true" ]]; then
  RUNNER_ARGS+=("--dry-run")
fi
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  RUNNER_ARGS+=("${EXTRA_ARGS[@]}")
fi

exit_code=0
# shellcheck disable=SC2086
${timeout_cmd} uv run --project "${ONEX_REGISTRY_ROOT}/omniclaude" \
  python "${RUNNER}" "${RUNNER_ARGS[@]}" \
  > "${OUTPUT_FILE}" 2>> "${LOG_DIR}/${RUN_ID}.log" || exit_code=$?

if [[ ${exit_code} -eq 124 ]]; then
  log "TIMEOUT: runner exceeded ${PHASE_TIMEOUT}s"
  exit 1
fi

if [[ ${exit_code} -ne 0 ]]; then
  log "FAILED: runner exited ${exit_code}"
  exit "${exit_code}"
fi

# Aggregate counts from the final summary line for the tick log.
SUMMARY="$(tail -n 1 "${OUTPUT_FILE}" 2>/dev/null || echo '{}')"
log "summary: ${SUMMARY}"

# Surface ESCALATE verdicts as friction events. Fail-open: best-effort.
# The runner prints one JSON per repo; we look for "action":"escalate".
ESCALATIONS="$(grep '"action": "escalate"' "${OUTPUT_FILE}" 2>/dev/null || true)"
if [[ -n "${ESCALATIONS}" ]] && [[ "${DRY_RUN}" != "true" ]]; then
  while IFS= read -r line; do
    repo="$(echo "${line}" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("repo",""))' 2>/dev/null || echo "")"
    pr="$(echo "${line}" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("head_pr",""))' 2>/dev/null || echo "")"
    if [[ -z "${repo}" ]] || [[ -z "${pr}" ]]; then
      continue
    fi
    log "ESCALATE: ${repo}#${pr} — emitting friction"
    # Best-effort: if claude CLI present, call record_friction; else log only.
    if command -v claude &>/dev/null; then
      claude -p "/onex:record_friction --skill unstick_queue --surface queue_stall/${repo}#${pr} --severity high --description 'repeat-offender merge queue stall (>=3 unsticks in 1h, ticket OMN-9065)'" \
        --print \
        --allowedTools "Bash,Read,Write" \
        >> "${LOG_DIR}/${RUN_ID}.log" 2>&1 || \
        log "WARN: record_friction call failed for ${repo}#${pr}"
    fi
  done <<< "${ESCALATIONS}"
fi

log "=== unstick-queue tick ${RUN_ID} complete ==="
exit 0
