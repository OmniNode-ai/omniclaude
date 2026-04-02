#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# cron-merge-sweep.sh — Headless merge-sweep orchestrator with auth recovery
#
# Wraps merge-sweep in a headless claude -p invocation with:
# - Scoped --allowedTools matching SKILL.md minimum allowlist
# - Auth failure detection: if gh fails with auth error → gh auth refresh → retry once
# - Max 2 auth refreshes per cycle; abort if both fail
# - Structured result YAML at .onex_state/merge-sweep-results/{timestamp}.yaml
#
# Usage:
#   ./scripts/cron-merge-sweep.sh                     # Full merge-sweep
#   ./scripts/cron-merge-sweep.sh --dry-run            # Print without executing
#   ./scripts/cron-merge-sweep.sh --skip-polish        # Merge-only (no Track B)
#   ./scripts/cron-merge-sweep.sh --repos omniclaude   # Limit to specific repos
#   ./scripts/cron-merge-sweep.sh --resume             # Resume from checkpoint
#
# Requires: claude CLI, gh CLI (authenticated), ANTHROPIC_API_KEY
#
# Design: Follows the headless decomposition pattern from cron-closeout.sh
# - One task per invocation (bounded context)
# - State handoff via files (no shared session state)
# - Idempotent (safe to re-run)
# - Auth recovery with circuit breaker
#
# [OMN-7256]

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OMNI_HOME="/Volumes/PRO-G40/Code/omni_home"  # local-path-ok: script runs on local machine only
STATE_DIR="${OMNI_HOME}/.onex_state/merge-sweep-results"
LOG_DIR="/tmp/merge-sweep-logs"
PHASE_TIMEOUT=900  # 15 minutes — merge-sweep can be slow with polish
RUN_ID="merge-sweep-$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
DRY_RUN=false

# Auth recovery state
AUTH_REFRESH_COUNT=0
MAX_AUTH_REFRESHES=2

# Pass-through args for merge-sweep skill
SWEEP_ARGS=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --skip-polish) SWEEP_ARGS="${SWEEP_ARGS} --skip-polish"; shift ;;
    --resume) SWEEP_ARGS="${SWEEP_ARGS} --resume"; shift ;;
    --repos) SWEEP_ARGS="${SWEEP_ARGS} --repos $2"; shift 2 ;;
    --repos=*) SWEEP_ARGS="${SWEEP_ARGS} --repos ${1#*=}"; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

if [[ -f "${HOME}/.omnibase/.env" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.omnibase/.env"
fi

export ONEX_RUN_ID="${RUN_ID}"
export ONEX_UNSAFE_ALLOW_EDITS=1

# Source headless emit wrapper for unified event emission [OMN-7034]
# shellcheck disable=SC1091
source "$(dirname "$0")/headless-emit-wrapper.sh"

# ---------------------------------------------------------------------------
# Tool allowlist (from SKILL.md minimum headless allowlist)
# ---------------------------------------------------------------------------

ALLOWED_TOOLS="Bash,Read,Write,Edit,Glob,Grep"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

preflight() {
  local missing=()

  if ! command -v claude &>/dev/null; then
    missing+=("claude CLI")
  fi

  if [[ "${DRY_RUN}" != "true" && -z "${ANTHROPIC_API_KEY:-}" ]]; then
    missing+=("ANTHROPIC_API_KEY")
  fi

  if ! command -v gh &>/dev/null; then
    missing+=("gh CLI")
  fi

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: Missing requirements: ${missing[*]}" >&2
    exit 1
  fi
}

preflight

# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

# ---------------------------------------------------------------------------
# Lock file — prevent concurrent runs
# ---------------------------------------------------------------------------

LOCK_FILE="${STATE_DIR}/cron-merge-sweep.lock"
LOCK_TIMEOUT=1800  # 30 minutes

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
  local msg="[cron-merge-sweep $(date -u +"%H:%M:%S")] $1"
  echo "${msg}"
  echo "${msg}" >> "${LOG_DIR}/${RUN_ID}.log"
}

# Check if output contains a GitHub auth failure
is_auth_failure() {
  local output_file="$1"
  if [[ ! -f "${output_file}" ]]; then
    return 1
  fi
  if grep -qi "HTTP 401\|authentication\|auth token\|could not authenticate\|gh auth login\|gh auth refresh\|SAML enforcement\|token expired\|bad credentials" "${output_file}" 2>/dev/null; then
    return 0
  fi
  return 1
}

# Attempt gh auth refresh with circuit breaker
try_auth_refresh() {
  if [[ ${AUTH_REFRESH_COUNT} -ge ${MAX_AUTH_REFRESHES} ]]; then
    log "AUTH CIRCUIT BREAKER: ${MAX_AUTH_REFRESHES} auth refreshes exhausted. Aborting."
    return 1
  fi

  AUTH_REFRESH_COUNT=$((AUTH_REFRESH_COUNT + 1))
  log "Auth refresh attempt ${AUTH_REFRESH_COUNT}/${MAX_AUTH_REFRESHES}"

  if gh auth refresh 2>&1; then
    log "Auth refresh succeeded"
    return 0
  else
    log "Auth refresh FAILED"
    return 1
  fi
}

# Run merge-sweep via headless claude -p with auth recovery
run_merge_sweep() {
  local attempt="$1"
  local output_file="${STATE_DIR}/${RUN_ID}-attempt-${attempt}.txt"
  local prompt="/merge-sweep --run-id ${RUN_ID}${SWEEP_ARGS}"

  log "Starting merge-sweep (attempt ${attempt}): ${prompt}"

  if [[ "${DRY_RUN}" == "true" ]]; then
    log "[DRY RUN] Would execute: claude -p '${prompt}' --allowedTools '${ALLOWED_TOOLS}'"
    echo "DRY_RUN: merge-sweep" > "${output_file}"
    return 0
  fi

  local exit_code=0
  timeout "${PHASE_TIMEOUT}" claude -p "${prompt}" \
    --print \
    --allowedTools "${ALLOWED_TOOLS}" \
    > "${output_file}" 2>&1 || exit_code=$?

  if [[ ${exit_code} -eq 124 ]]; then
    log "TIMEOUT: merge-sweep exceeded ${PHASE_TIMEOUT}s"
    echo "TIMEOUT" >> "${output_file}"
    return 1
  fi

  # Check for auth failure — eligible for retry
  if is_auth_failure "${output_file}"; then
    log "Auth failure detected in merge-sweep output"
    return 2  # special code: auth failure
  fi

  if [[ ${exit_code} -ne 0 ]]; then
    log "FAILED: merge-sweep exited with code ${exit_code}"
    return 1
  fi

  log "Completed merge-sweep (attempt ${attempt})"
  return 0
}

# Write structured result YAML
write_result_yaml() {
  local status="$1"
  local attempts="$2"
  local auth_refreshes="$3"
  local timestamp
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  local result_file="${STATE_DIR}/${RUN_ID}.yaml"

  cat > "${result_file}" << EOF
# merge-sweep result — generated by cron-merge-sweep.sh [OMN-7256]
run_id: "${RUN_ID}"
completed_at: "${timestamp}"
status: "${status}"
dry_run: ${DRY_RUN}
attempts: ${attempts}
auth_refreshes: ${auth_refreshes}
sweep_args: "${SWEEP_ARGS}"
output_files:
EOF

  # List all attempt output files
  for f in "${STATE_DIR}/${RUN_ID}"-attempt-*.txt; do
    if [[ -f "$f" ]]; then
      echo "  - \"$(basename "$f")\"" >> "${result_file}"
    fi
  done

  log "Result YAML written: ${result_file}"
}

# ===========================================================================
# Main execution
# ===========================================================================

log "=== Merge-sweep run ${RUN_ID} starting ==="
log "State dir: ${STATE_DIR}"
log "Sweep args:${SWEEP_ARGS:- (none)}"

emit_task_event "task-assigned" "${RUN_ID}" "\"session_id\": \"${ONEX_RUN_ID}\", \"phase\": \"merge-sweep-start\""

# Pre-check: verify gh auth is working before invoking claude
if ! gh auth status &>/dev/null; then
  log "gh auth check failed at start — attempting refresh"
  if ! try_auth_refresh; then
    log "ABORT: Cannot authenticate with GitHub at startup"
    write_result_yaml "auth_failed" 0 "${AUTH_REFRESH_COUNT}"
    exit 2
  fi
fi

# Run merge-sweep with auth recovery loop
ATTEMPT=1
FINAL_STATUS="unknown"

while [[ ${ATTEMPT} -le 2 ]]; do
  run_merge_sweep "${ATTEMPT}"
  result=$?

  if [[ ${result} -eq 0 ]]; then
    FINAL_STATUS="complete"
    break
  elif [[ ${result} -eq 2 ]]; then
    # Auth failure — try to recover
    if try_auth_refresh; then
      log "Auth recovered, retrying merge-sweep"
      ATTEMPT=$((ATTEMPT + 1))
      continue
    else
      FINAL_STATUS="auth_failed"
      break
    fi
  else
    # Non-auth failure — no retry
    FINAL_STATUS="failed"
    break
  fi
done

# ===========================================================================
# Finalize
# ===========================================================================

log "=== Finalizing merge-sweep run ==="

emit_task_event "task-completed" "${RUN_ID}" "\"session_id\": \"${ONEX_RUN_ID}\", \"phase\": \"merge-sweep-complete\", \"status\": \"${FINAL_STATUS}\", \"attempts\": ${ATTEMPT}, \"auth_refreshes\": ${AUTH_REFRESH_COUNT}"

write_result_yaml "${FINAL_STATUS}" "${ATTEMPT}" "${AUTH_REFRESH_COUNT}"

log "Merge-sweep run ${RUN_ID} finished: status=${FINAL_STATUS}, attempts=${ATTEMPT}, auth_refreshes=${AUTH_REFRESH_COUNT}"
log "Full log: ${LOG_DIR}/${RUN_ID}.log"

# Exit codes:
# 0 = success
# 1 = non-auth failure
# 2 = auth failure (unrecoverable)
case "${FINAL_STATUS}" in
  complete) exit 0 ;;
  auth_failed) exit 2 ;;
  *) exit 1 ;;
esac
