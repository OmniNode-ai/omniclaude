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
# Requires: claude CLI (with OAuth or API key), gh CLI (authenticated)
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

# Resolve ONEX_REGISTRY_ROOT: prefer env var, fall back to resolving relative to script location
# Script lives at omni_home/omniclaude/scripts/cron-merge-sweep.sh → two levels up
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONEX_REGISTRY_ROOT="${ONEX_REGISTRY_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
STATE_DIR="${ONEX_REGISTRY_ROOT}/.onex_state/merge-sweep-results"
LOG_DIR="/tmp/merge-sweep-logs"
PHASE_TIMEOUT=900  # 15 minutes — merge-sweep can be slow with polish
RUN_ID="merge-sweep-$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
DRY_RUN=false

# Auth recovery state
AUTH_REFRESH_COUNT=0
MAX_AUTH_REFRESHES=2

# Pass-through args for merge-sweep skill
#
# OMN-9065: enable admin-merge-fallback by default so the tick auto-unsticks
# queue stalls (PRs stuck AWAITING_CHECKS > threshold). Without this, a
# hanging third-party check-run (e.g. CodeRabbit) can wedge the queue head
# indefinitely — observed 2026-04-17 with omnibase_infra#1330 stalled 70+ min
# across multiple tick cycles because the feature was off.
#
# Threshold 15 min = unstick within ~2 tick cycles at the 5-min tick interval.
# CLI invocations can override via later flags (last-wins in argument parsing).
SWEEP_ARGS="--enable-admin-merge-fallback --admin-fallback-threshold-minutes=15"

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

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo '{"status":"quarantined","reason":"OMN-10165 SEAM-5a: merge_sweep skill dispatch is structurally broken until repaired","ticket":"OMN-10165"}' >&2
  exit 64
fi
return 0

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

# Source canonical-clone preflight — pulls omniclaude before running the skill [OMN-9405]
# shellcheck disable=SC1091
source "$(dirname "$0")/lib/canonical-clone-preflight.sh"

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
    missing+=("claude CLI (ensure ~/.local/bin is in PATH)")
  fi

  # Auth is handled by the claude CLI (OAuth session or API key).
  # Do NOT check ANTHROPIC_API_KEY here — Claude Code sessions use OAuth.

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
  local msg
  msg="[cron-merge-sweep $(date -u +"%H:%M:%S")] $1"
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
  local prompt="/onex:merge_sweep --run-id ${RUN_ID} ${SWEEP_ARGS}"

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
log "ONEX_REGISTRY_ROOT: ${ONEX_REGISTRY_ROOT}"
log "State dir: ${STATE_DIR}"
log "Sweep args:${SWEEP_ARGS:- (none)}"

# Pull canonical clone before running the skill so the latest code is always executed [OMN-9405]
canonical_clone_preflight "preflight" || {
  log "ABORT: canonical-clone preflight failed — refusing to run stale code"
  exit 1
}

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

# ---------------------------------------------------------------------------
# PR stall detection — runs after sweep, fail-open [OMN-9406]
# ---------------------------------------------------------------------------
# Calls HandlerPrSnapshot via run-stall-detector.py, which persists a rolling
# two-snapshot diff to $ONEX_STATE_DIR/pr-snapshots/. On the second identical
# snapshot for a blocked PR it emits a stall event. file-stall-tickets.sh
# converts each event into a Linear ticket (tagged auto-stall-detected).
# Non-zero exit from either step is logged but does NOT abort the tick.

STALL_DETECTOR="${SCRIPT_DIR}/lib/run-stall-detector.py"
STALL_FILER="${SCRIPT_DIR}/lib/file-stall-tickets.sh"

if [[ -f "${STALL_DETECTOR}" ]] && [[ -f "${STALL_FILER}" ]]; then
  log "Running PR stall detector..."
  stall_output=""
  stall_exit=0
  stall_output="$(uv run python "${STALL_DETECTOR}" 2>>"${LOG_DIR}/${RUN_ID}.log")" || stall_exit=$?

  if [[ ${stall_exit} -ne 0 ]]; then
    log "WARN: stall detector exited ${stall_exit} — skipping ticket filing"
  else
    echo "${stall_output}" | bash "${STALL_FILER}" 2>>"${LOG_DIR}/${RUN_ID}.log" || \
      log "WARN: stall ticket filer failed (non-fatal)"
  fi
else
  log "WARN: stall detector scripts not found — skipping (${STALL_DETECTOR})"
fi

log "Merge-sweep run ${RUN_ID} finished: status=${FINAL_STATUS}, attempts=${ATTEMPT}, auth_refreshes=${AUTH_REFRESH_COUNT}"
log "Full log: ${LOG_DIR}/${RUN_ID}.log"

# ---------------------------------------------------------------------------
# Queue method-mismatch heal — runs after sweep, fail-open [OMN-9434]
# ---------------------------------------------------------------------------
# Detects PRs that are armed (autoMergeRequest non-null) + CLEAN but are NOT
# present in mergeQueue.entries. This is the symptom of a silent queue-drop
# caused by a mergeMethod mismatch between the arm call and the queue ruleset
# (see memory/feedback_merge_queue_method_mismatch.md).
#
# Recovery: dequeue + re-enqueue (enqueuePullRequest uses the queue's own
# method, eliminating any mismatch).
#
# Fail-open: any GraphQL or gh error is logged but does NOT abort the tick.
# Each heal action is logged to stdout for audit trail.

_queue_heal() {
  local org="OmniNode-ai"
  # Repos that use merge queues — must match the org's queue-enabled repos.
  # Sourced from ONEX_QUEUE_REPOS env var (CSV) or falls back to the known set.
  local repos_csv="${ONEX_QUEUE_REPOS:-omniclaude,omnibase_core,omnibase_spi,omnibase_infra,omnibase_compat,omniintelligence,omnimemory,omninode_infra,onex_change_control}"
  # Configurable dequeue→requeue pause (seconds). Default 2. Override for tests.
  local heal_sleep="${ONEX_QUEUE_HEAL_SLEEP:-2}"
  local heal_count=0
  local check_count=0

  log "[queue-heal] Starting method-mismatch scan across ${repos_csv}"

  # Use tr+while for bash 3.2 compatibility (read -a/-ra requires bash 4+).
  # Each token is trimmed of leading/trailing whitespace before use.
  while IFS= read -r repo_name; do
    # Trim whitespace and skip empty/whitespace-only tokens
    repo_name="${repo_name#"${repo_name%%[! ]*}"}"
    repo_name="${repo_name%"${repo_name##*[! ]}"}"
    [[ -z "${repo_name}" ]] && continue
    # Reject tokens containing slashes or shell-special chars (already org-qualified entries)
    if echo "${repo_name}" | grep -qE '[^a-zA-Z0-9_.-]'; then
      log "[queue-heal] WARN: skipping invalid repo token '${repo_name}'"
      continue
    fi

    local full_repo="${org}/${repo_name}"

    # Fetch open PRs that have auto-merge armed and are in CLEAN state.
    # --limit 300: gh pr list defaults to 30; raise to cover repos with many open PRs.
    # --json fields: number, id (node_id for GraphQL), autoMergeRequest, mergeStateStatus
    local pr_json
    pr_json=$(gh pr list \
      --repo "${full_repo}" \
      --state open \
      --limit 300 \
      --json number,id,autoMergeRequest,mergeStateStatus \
      2>>"${LOG_DIR}/${RUN_ID}.log") || {
      log "[queue-heal] WARN: gh pr list failed for ${full_repo} — skipping"
      continue
    }

    # Filter: armed (autoMergeRequest != null) + CLEAN state; emit "number:id" pairs
    local armed_prs
    armed_prs=$(echo "${pr_json}" | \
      jq -r '.[] | select(.autoMergeRequest != null and .mergeStateStatus == "CLEAN") | "\(.number):\(.id)"' \
      2>>"${LOG_DIR}/${RUN_ID}.log") || {
      log "[queue-heal] WARN: jq filter failed for ${full_repo} — skipping"
      continue
    }

    if [[ -z "${armed_prs}" ]]; then
      continue
    fi

    # Fetch current merge queue entries for this repo.
    # GitHub's merge queue API hard-caps at 100 entries per queue (enforced server-side).
    # PRs beyond 100 cannot be in the queue regardless of the 'first' value we pass.
    # Using first:100 therefore covers the entire possible queue membership set.
    local queue_entries
    queue_entries=$(gh api graphql \
      -f query="{ repository(owner: \"${org}\", name: \"${repo_name}\") {
        mergeQueue { entries(first: 100) { nodes { pullRequest { number } } } }
      } }" \
      --jq '.data.repository.mergeQueue.entries.nodes[].pullRequest.number' \
      2>>"${LOG_DIR}/${RUN_ID}.log") || {
      log "[queue-heal] WARN: mergeQueue query failed for ${full_repo} — skipping"
      continue
    }

    # For each armed+CLEAN PR, check if it is in the queue.
    # Each line is "number:node_id" — split on ':' to avoid an extra REST call per PR.
    while IFS= read -r pr_entry; do
      [[ -z "${pr_entry}" ]] && continue
      local pr_num pr_node_id
      pr_num="${pr_entry%%:*}"
      pr_node_id="${pr_entry#*:}"
      check_count=$((check_count + 1))

      if echo "${queue_entries}" | grep -qx "${pr_num}"; then
        # PR is in the queue — no heal needed
        continue
      fi

      # PR is armed + CLEAN but NOT in queue: silent method-mismatch drop
      log "[queue-heal] HEALING ${full_repo}#${pr_num}: armed+CLEAN but not in mergeQueue — dequeue+requeue"

      # Dequeue (no-op if not queued; safe to call regardless).
      # DequeuePullRequestInput uses 'id' (not 'pullRequestId') per GitHub schema.
      gh api graphql \
        -f query="mutation(\$pr: ID!) { dequeuePullRequest(input: {id: \$pr}) { clientMutationId } }" \
        -f pr="${pr_node_id}" \
        >>"${LOG_DIR}/${RUN_ID}.log" 2>&1 || {
        log "[queue-heal] WARN: dequeuePullRequest failed for ${full_repo}#${pr_num} — attempting requeue anyway"
      }

      # Brief pause so GitHub processes the dequeue before re-entry
      sleep "${heal_sleep}"

      # Re-enqueue: enqueuePullRequest uses the queue's configured method (no mergeMethod arg).
      # EnqueuePullRequestInput uses 'pullRequestId' per GitHub schema.
      local requeue_result
      requeue_result=$(gh api graphql \
        -f query="mutation(\$pr: ID!) { enqueuePullRequest(input: {pullRequestId: \$pr}) { mergeQueueEntry { position state } } }" \
        -f pr="${pr_node_id}" \
        2>>"${LOG_DIR}/${RUN_ID}.log") || {
        log "[queue-heal] WARN: enqueuePullRequest failed for ${full_repo}#${pr_num} — heal incomplete"
        continue
      }

      # Validate GraphQL response for semantic errors (gh exits 0 even on schema errors)
      if echo "${requeue_result}" | jq -e '.errors | if . then length > 0 else false end' >/dev/null 2>&1; then
        local gql_err
        gql_err=$(echo "${requeue_result}" | jq -r '.errors[0].message // "unknown"' 2>/dev/null)
        log "[queue-heal] WARN: enqueuePullRequest GraphQL error for ${full_repo}#${pr_num}: ${gql_err} — heal incomplete"
        continue
      fi

      local position
      position=$(echo "${requeue_result}" | jq -r '.data.enqueuePullRequest.mergeQueueEntry.position // "unknown"' 2>/dev/null)
      log "[queue-heal] HEALED ${full_repo}#${pr_num}: re-enqueued at position ${position}"
      heal_count=$((heal_count + 1))

    done <<< "${armed_prs}"
  done <<< "$(echo "${repos_csv}" | tr ',' '\n')"

  log "[queue-heal] Complete: checked ${check_count} armed+CLEAN PRs, healed ${heal_count} method-mismatch drops"
}

# Run heal block fail-open — errors inside _queue_heal are already logged;
# a non-zero exit from _queue_heal must not abort the tick.
_queue_heal 2>>"${LOG_DIR}/${RUN_ID}.log" || \
  log "[queue-heal] WARN: heal block exited non-zero (fail-open, tick continues)"

# Exit codes:
# 0 = success
# 1 = non-auth failure
# 2 = auth failure (unrecoverable)
case "${FINAL_STATUS}" in
  complete) exit 0 ;;
  auth_failed) exit 2 ;;
  *) exit 1 ;;
esac
