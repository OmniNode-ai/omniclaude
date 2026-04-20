#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# cron-quick-merge.sh — Stop-gap direct-gh merge-sweep tick [OMN-9347]
#
# Runs in parallel to cron-merge-sweep.sh while the full /onex:merge_sweep
# skill is gated by a red Track C probe (OMN-9215 wire drift).
#
# Scope (deliberately minimal):
#   1. Arm GitHub auto-merge on open PRs that are mergeStateStatus=CLEAN
#      and have no autoMergeRequest armed. Queue-aware:
#        - merge-queue repos → gh pr merge --auto (method controlled by queue)
#        - non-queue repos   → gh pr merge --squash --auto
#   2. Detect merge-queue stalls: isInMergeQueue=true for >15min with zero
#      merge_group workflow runs on the queue head SHA. Remediate via
#      dequeuePullRequest + enablePullRequestAutoMerge GraphQL mutations
#      (pattern: feedback_merge_queue_stall_remediation.md).
#
# Explicitly NOT doing:
#   - Masking real CI failures (skip PRs with RollupState=FAILURE/ERROR).
#   - Touching owned-PR exclusion list (#1353, #865-family — see $EXCLUDE_PRS).
#   - Any skill-wrapper, Kafka probe, or contract-dependent work.
#
# Idempotent: armed PRs are skipped; stall remediation only fires when the
# zero-workflow condition is met.
#
# Per-PR failures are logged and skipped; the tick continues through the
# remaining PR list.
#
# Usage:
#   ./scripts/cron-quick-merge.sh                   # act on live state
#   ./scripts/cron-quick-merge.sh --dry-run         # log intent, no mutations
#
# Expiration: delete this script + its plist when either (a) bypass-loop-builder
# ships the proper contract-driven replacement (task #35), or (b) Track C is
# green for 6+ consecutive merge-sweep runs.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONEX_REGISTRY_ROOT="${ONEX_REGISTRY_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

LOG_DIR="/tmp"
LOCK_FILE="/tmp/cron-quick-merge.lock"
LOCK_TIMEOUT=1200  # 20 minutes — upper bound on a full scan
PHASE_TIMEOUT=600  # 10 minutes per tick run

# State dir for first-seen timestamps (queue-entry time tracking).
# Uses ONEX_STATE_DIR if set, otherwise falls back to /tmp.
STATE_DIR="${ONEX_STATE_DIR:-/tmp}/cron-quick-merge"

DRY_RUN="${DRY_RUN:-false}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      ;;
    --help|-h)
      echo "Usage: $0 [--dry-run]"
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      exit 1
      ;;
  esac
  shift
done

# Repos to scan. Keep in sync with canonical registry in omni_home/CLAUDE.md.
REPOS=(
  "OmniNode-ai/omniclaude"
  "OmniNode-ai/omnibase_core"
  "OmniNode-ai/omnibase_infra"
  "OmniNode-ai/omnibase_spi"
  "OmniNode-ai/omnibase_compat"
  "OmniNode-ai/omnidash"
  "OmniNode-ai/omniintelligence"
  "OmniNode-ai/omnimemory"
  "OmniNode-ai/omninode_infra"
  "OmniNode-ai/omniweb"
  "OmniNode-ai/onex_change_control"
  "OmniNode-ai/omnimarket"
)

# Exclusion list: PRs owned by specific workers right now.
# Format: "repo#num" — exact match against "${repo_short}#${num}".
EXCLUDE_PRS=(
  "omnibase_infra#1353"
  "omnibase_infra#865"
)

# Stall thresholds
STALL_MINUTES=15

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

if [[ -f "${HOME}/.omnibase/.env" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.omnibase/.env"
fi

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

if ! command -v gh &>/dev/null; then
  echo "ERROR: gh CLI not found on PATH" >&2
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo "ERROR: jq not found on PATH" >&2
  exit 1
fi

if ! gh auth status &>/dev/null; then
  echo "ERROR: gh not authenticated" >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

if [[ -f "${LOCK_FILE}" ]]; then
  lock_time=$(stat -f %m "${LOCK_FILE}" 2>/dev/null || stat -c %Y "${LOCK_FILE}" 2>/dev/null || echo 0)
  now=$(date +%s)
  age=$(( now - lock_time ))

  if [[ ${age} -lt ${LOCK_TIMEOUT} ]]; then
    echo "SKIP: previous invocation still running (lock age: ${age}s < ${LOCK_TIMEOUT}s)"
    exit 0
  else
    echo "WARN: stale lock (age ${age}s) — removing"
    rm -f "${LOCK_FILE}"
  fi
fi

echo "pid=$$ started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${LOCK_FILE}"
trap 'rm -f "${LOCK_FILE}"' EXIT

# Global timeout circuit breaker: kill the whole process tree if the tick
# runs past PHASE_TIMEOUT. macOS `timeout` lives in coreutils (gtimeout),
# so fall back to a background watchdog for portability.
(
  sleep "${PHASE_TIMEOUT}"
  echo "[quick-merge] TIMEOUT after ${PHASE_TIMEOUT}s — killing pid $$" >&2
  kill -TERM $$ 2>/dev/null || true
) &
WATCHDOG_PID=$!
trap 'rm -f "${LOCK_FILE}"; kill "${WATCHDOG_PID}" 2>/dev/null || true' EXIT

mkdir -p "${STATE_DIR}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RUN_ID="quick-merge-$(date -u +"%Y-%m-%dT%H-%M-%SZ")"

log() {
  echo "[quick-merge $(date -u +"%H:%M:%S")] $*"
}

is_excluded() {
  local key="$1"
  local ex
  for ex in "${EXCLUDE_PRS[@]}"; do
    if [[ "${key}" == "${ex}" ]]; then
      return 0
    fi
  done
  return 1
}

# Returns 0 if the repo has a merge queue enabled on default branch.
# We detect this dynamically rather than maintaining a static list — the set
# of queue-enabled repos drifts and hardcoding is a failure mode the existing
# merge-sweep pattern already cautions against.
repo_has_merge_queue() {
  local repo="$1"
  # mergeQueueEnabled is a repository-level boolean; GraphQL is the only place
  # it surfaces cheaply.
  local enabled
  enabled="$(
    gh api graphql \
      -f query='query($owner:String!, $name:String!){ repository(owner:$owner, name:$name){ mergeQueue { id } } }' \
      -F owner="${repo%%/*}" \
      -F name="${repo##*/}" \
      --jq '.data.repository.mergeQueue != null' 2>/dev/null || echo "false"
  )"
  [[ "${enabled}" == "true" ]]
}

# Count merge_group workflow runs on a queue head SHA. Zero after the stall
# window means the check-suite dispatcher is wedged (OMN-9288 pattern).
count_merge_group_runs() {
  local repo="$1"
  local sha="$2"
  gh api "repos/${repo}/actions/runs?head_sha=${sha}&event=merge_group" \
    --jq '.total_count' 2>/dev/null || echo "0"
}

# Return the epoch time when a PR entered the merge queue, derived from
# AddedToMergeQueueEvent in the PR timeline. Falls back to persisting the
# first observation per repo#number/sha in STATE_DIR so stall age is
# measured from actual queue-entry, not PR creation.
get_queue_entry_epoch() {
  local repo="$1"
  local number="$2"
  local head_sha="$3"
  local state_key
  state_key="${STATE_DIR}/queue-entry-$(echo "${repo}" | tr '/' '-')-${number}-${head_sha}"

  # Use cached value if available (same head SHA = same queue entry).
  if [[ -f "${state_key}" ]]; then
    cat "${state_key}"
    return 0
  fi

  # Try to read AddedToMergeQueueEvent from GitHub timeline.
  local entry_ts
  entry_ts="$(
    gh api graphql \
      -f query='query($owner:String!, $name:String!, $num:Int!){
        repository(owner:$owner, name:$name){
          pullRequest(number:$num){
            timelineItems(itemTypes:[ADDED_TO_MERGE_QUEUE_EVENT], last:10){
              nodes { ... on AddedToMergeQueueEvent { createdAt } }
            }
          }
        }
      }' \
      -F owner="${repo%%/*}" \
      -F name="${repo##*/}" \
      -F num="${number}" \
      --jq '.data.repository.pullRequest.timelineItems.nodes | last | .createdAt // empty' \
      2>/dev/null || true
  )"

  local now_epoch
  now_epoch=$(date -u +%s)

  if [[ -n "${entry_ts}" ]]; then
    local entry_epoch
    entry_epoch=$(date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "${entry_ts}" +%s 2>/dev/null || echo "${now_epoch}")
    echo "${entry_epoch}" > "${state_key}"
    echo "${entry_epoch}"
  else
    # No timeline event found; record now as first observation so stall
    # age is measured from when we first saw this PR in the queue, not
    # from PR creation.
    echo "${now_epoch}" > "${state_key}"
    echo "${now_epoch}"
  fi
}

# Dequeue + re-arm via GraphQL (pattern from feedback_merge_queue_stall_remediation.md).
# Do NOT use `gh pr merge --auto` here — it picks the wrong method and is blocked
# by the bash-guard on the queue path.
remediate_queue_stall() {
  local repo="$1"
  local number="$2"
  local pr_global_id="$3"

  log "  stall-remediate ${repo}#${number} (node=${pr_global_id})"

  if [[ "${DRY_RUN}" == "true" ]]; then
    log "    [DRY_RUN] would dequeue + re-arm ${repo}#${number}"
    return 0
  fi

  # Step 1: dequeue
  if ! gh api graphql \
      -f query='mutation($id:ID!){ dequeuePullRequest(input:{id:$id}){ pullRequest { number } } }' \
      -F id="${pr_global_id}" >/dev/null 2>&1; then
    log "    WARN: dequeue failed for ${repo}#${number}"
    return 1
  fi

  # Step 2: re-arm auto-merge (SQUASH — queue batching method)
  if ! gh api graphql \
      -f query='mutation($id:ID!){ enablePullRequestAutoMerge(input:{pullRequestId:$id, mergeMethod: SQUASH}){ pullRequest { number } } }' \
      -F id="${pr_global_id}" >/dev/null 2>&1; then
    log "    WARN: re-arm failed for ${repo}#${number} — PR is now DEQUEUED without auto-merge"
    return 1
  fi

  log "    re-armed ${repo}#${number}"
  return 0
}

arm_auto_merge() {
  # Uses GraphQL enablePullRequestAutoMerge with explicit mergeMethod: SQUASH.
  # We do NOT use the gh CLI's --auto flag — it silently picks the wrong
  # merge method regardless of --squash (OMN-8838, bash-guard blocks it).
  # SQUASH is correct for both queue and non-queue repos: queue repos
  # override method via their ruleset; non-queue repos honor our explicit
  # choice; in neither case does MERGE belong.
  local repo="$1"
  local number="$2"
  local pr_id="$3"

  if [[ "${DRY_RUN}" == "true" ]]; then
    log "    [DRY_RUN] would enable auto-merge (SQUASH) on ${repo}#${number}"
    return 0
  fi

  if ! gh api graphql \
      -f query='mutation($id:ID!){ enablePullRequestAutoMerge(input:{pullRequestId:$id, mergeMethod: SQUASH}){ pullRequest { number } } }' \
      -F id="${pr_id}" >/dev/null 2>&1; then
    log "    WARN: arm failed for ${repo}#${number}"
    return 1
  fi

  log "    armed ${repo}#${number}"
  return 0
}

# ---------------------------------------------------------------------------
# Per-repo scan
# ---------------------------------------------------------------------------

SCANNED=0
ARMED=0
STALL_REMEDIATED=0
SKIPPED_EXCLUDED=0
SKIPPED_RED=0
SKIPPED_ALREADY_ARMED=0
SKIPPED_NOT_CLEAN=0
ERRORS=0

scan_repo() {
  local repo="$1"
  local repo_short="${repo##*/}"

  local has_queue="false"
  if repo_has_merge_queue "${repo}"; then
    has_queue="true"
  fi

  # Extract PR summary as TSV in one jq pass — one subshell per repo instead
  # of O(N*fields) subshells. Fields (tab-separated):
  #   1 number
  #   2 mergeStateStatus       (CLEAN / BLOCKED / QUEUED / BEHIND / DIRTY / UNKNOWN)
  #   3 autoMergeArmed         ("true"/"false")
  #   4 inQueue                ("true"/"false") — derived from mergeStateStatus==QUEUED
  #                            (older gh versions lack the isInMergeQueue field)
  #   5 headRefOid
  #   6 createdAt
  #   7 id (PR node global ID)
  #   8 realRed                ("true"/"false") — any FAILURE/ERROR/CANCELLED in statusCheckRollup
  local tsv
  if ! tsv="$(
    gh pr list \
      --repo "${repo}" \
      --state open \
      --json number,mergeStateStatus,autoMergeRequest,headRefOid,createdAt,statusCheckRollup,id \
      --limit 100 2>/dev/null \
    | jq -r '.[] | [
        .number,
        .mergeStateStatus,
        (.autoMergeRequest != null),
        (.mergeStateStatus == "QUEUED"),
        .headRefOid,
        .createdAt,
        .id,
        ([.statusCheckRollup[]? | (.conclusion // .status // "") | ascii_upcase] | map(select(. == "FAILURE" or . == "ERROR" or . == "CANCELLED")) | length > 0)
      ] | @tsv'
  )"; then
    log "  ERROR: gh pr list failed for ${repo}"
    ERRORS=$((ERRORS + 1))
    return 0  # fail-open per-repo
  fi

  local count
  count="$([[ -z "${tsv}" ]] && echo 0 || echo "${tsv}" | wc -l | tr -d ' ')"
  log "${repo}: ${count} open PRs, queue=${has_queue}"

  if [[ -z "${tsv}" ]]; then
    return 0
  fi

  local number merge_state auto_armed in_queue head_sha created_at pr_id real_red
  while IFS=$'\t' read -r number merge_state auto_armed in_queue head_sha created_at pr_id real_red; do
    SCANNED=$((SCANNED + 1))
    local key="${repo_short}#${number}"

    if is_excluded "${key}"; then
      log "  ${key}: SKIP (excluded)"
      SKIPPED_EXCLUDED=$((SKIPPED_EXCLUDED + 1))
      continue
    fi

    # --- Stall-remediation path -----------------------------------------
    if [[ "${in_queue}" == "true" ]]; then
      local run_count
      run_count="$(count_merge_group_runs "${repo}" "${head_sha}")"

      if [[ "${run_count}" == "0" ]]; then
        local now_epoch queue_entry_epoch age_min
        now_epoch=$(date -u +%s)
        queue_entry_epoch=$(get_queue_entry_epoch "${repo}" "${number}" "${head_sha}")
        age_min=$(( (now_epoch - queue_entry_epoch) / 60 ))

        if [[ ${age_min} -ge ${STALL_MINUTES} ]]; then
          log "  ${key}: queue-stalled (0 merge_group runs, age=${age_min}m)"
          if remediate_queue_stall "${repo}" "${number}" "${pr_id}"; then
            STALL_REMEDIATED=$((STALL_REMEDIATED + 1))
          else
            ERRORS=$((ERRORS + 1))
          fi
        fi
      fi
      continue
    fi

    # --- Arm-auto-merge path --------------------------------------------
    if [[ "${auto_armed}" == "true" ]]; then
      SKIPPED_ALREADY_ARMED=$((SKIPPED_ALREADY_ARMED + 1))
      continue
    fi

    if [[ "${merge_state}" != "CLEAN" ]]; then
      SKIPPED_NOT_CLEAN=$((SKIPPED_NOT_CLEAN + 1))
      continue
    fi

    if [[ "${real_red}" == "true" ]]; then
      log "  ${key}: SKIP (real CI failure on non-required check)"
      SKIPPED_RED=$((SKIPPED_RED + 1))
      continue
    fi

    log "  ${key}: CLEAN + un-armed — arming (queue=${has_queue})"
    if arm_auto_merge "${repo}" "${number}" "${pr_id}"; then
      ARMED=$((ARMED + 1))
    else
      ERRORS=$((ERRORS + 1))
    fi
  done <<< "${tsv}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

log "=== quick-merge tick ${RUN_ID} starting (dry_run=${DRY_RUN}) ==="

# set +e so one repo's failure doesn't abort the rest; scan_repo already logs.
set +e
for repo in "${REPOS[@]}"; do
  scan_repo "${repo}"
done
set -e

log "=== summary ==="
log "  scanned:              ${SCANNED}"
log "  armed:                ${ARMED}"
log "  stall-remediated:     ${STALL_REMEDIATED}"
log "  skipped/excluded:     ${SKIPPED_EXCLUDED}"
log "  skipped/already-armed:${SKIPPED_ALREADY_ARMED}"
log "  skipped/not-clean:    ${SKIPPED_NOT_CLEAN}"
log "  skipped/real-red:     ${SKIPPED_RED}"
log "  errors:               ${ERRORS}"
log "=== quick-merge tick ${RUN_ID} complete ==="

# Exit code: 0 on clean runs, 1 if any errors surfaced (but we still did work).
if [[ ${ERRORS} -gt 0 ]]; then
  exit 1
fi
exit 0
