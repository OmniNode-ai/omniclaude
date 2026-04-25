#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# rebase-wave.sh — Coordinated rebase of multiple branches against origin/main
#
# Use case: an upstream breaking change (CI gate evolution, schema change,
# dependency pin) lands on main and N open feature branches need to rebase
# before their PRs can merge. This script automates the wave.
#
# Usage:
#   ./scripts/rebase-wave.sh --branches branch-a branch-b branch-c
#   ./scripts/rebase-wave.sh --from-pr-list [--repo omniclaude]
#   ./scripts/rebase-wave.sh --branches branch-a --dry-run
#   ./scripts/rebase-wave.sh --branches branch-a --pre-commit
#   ./scripts/rebase-wave.sh --help
#
# Flags:
#   --branches <name> [<name>...]  Explicit list of branches to rebase
#   --from-pr-list                 Discover branches from open PRs (requires gh + --repo)
#   --repo <name>                  GitHub repo name (default: detected from git remote)
#   --org <name>                   GitHub org (default: OmniNode-ai)
#   --dry-run                      Do everything except git push
#   --pre-commit                   Run pre-commit on rebased branch before push
#
# Exit codes:
#   0  All branches rebased (or skipped) — no conflicts
#   1  One or more branches conflicted
#
# Design:
#   - Operates on the repo where the script is invoked (git remote origin)
#   - Uses --force-with-lease (not --force) to avoid clobbering unexpected pushes
#   - On conflict: git rebase --abort, log files, continue to next branch
#   - Summary printed to stdout; machine-readable line per branch to stderr
#   - PID-lock prevents overlapping runs
#
# [OMN-9726]

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_ID="rebase-wave-$(date -u +"%Y-%m-%dT%H-%M-%SZ")"

DRY_RUN=false
PRE_COMMIT=false
FROM_PR_LIST=false
BRANCHES=()
REPO_NAME=""
ORG="OmniNode-ai"

# Result tracking
REBASED=()
CONFLICTED=()
SKIPPED=()
CONFLICT_FILES=()   # parallel array indexed with CONFLICTED

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

usage() {
  grep '^#' "$0" | grep -v '#!/' | sed 's/^# \?//' | head -40
  exit 0
}

if [[ $# -eq 0 ]]; then
  echo "ERROR: No arguments provided. Use --help for usage." >&2
  exit 1
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage ;;
    --dry-run) DRY_RUN=true; shift ;;
    --pre-commit) PRE_COMMIT=true; shift ;;
    --from-pr-list) FROM_PR_LIST=true; shift ;;
    --repo)
      [[ $# -lt 2 ]] && { echo "ERROR: --repo requires a value" >&2; exit 1; }
      REPO_NAME="$2"; shift 2 ;;
    --repo=*) REPO_NAME="${1#*=}"; shift ;;
    --org)
      [[ $# -lt 2 ]] && { echo "ERROR: --org requires a value" >&2; exit 1; }
      ORG="$2"; shift 2 ;;
    --org=*) ORG="${1#*=}"; shift ;;
    --branches)
      shift
      while [[ $# -gt 0 && "$1" != --* ]]; do
        BRANCHES+=("$1"); shift
      done
      ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
  echo "[rebase-wave $(date -u +"%H:%M:%S")] $1"
}

log_machine() {
  # Machine-readable per-branch record (to stderr for pipeline consumption)
  echo "$1" >&2
}

detect_repo_name() {
  local remote_url
  remote_url=$(git -C "${REPO_ROOT}" remote get-url origin 2>/dev/null) || {
    echo "ERROR: Cannot detect repo name — no git remote 'origin' found" >&2
    exit 1
  }
  # Works for both git@ and https:// URLs
  basename "${remote_url}" .git
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

preflight() {
  local missing=()

  if ! command -v git &>/dev/null; then
    missing+=("git")
  fi

  if [[ "${FROM_PR_LIST}" == "true" ]] && ! command -v gh &>/dev/null; then
    missing+=("gh CLI (required for --from-pr-list)")
  fi

  if [[ "${PRE_COMMIT}" == "true" ]] && ! command -v pre-commit &>/dev/null; then
    # pre-commit may be available via uv run — soft warning, not hard failure
    log "WARN: pre-commit not in PATH; will attempt via 'uv run pre-commit'"
  fi

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: Missing requirements: ${missing[*]}" >&2
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# PID-lock
# ---------------------------------------------------------------------------

LOCK_FILE="/tmp/rebase-wave.lock"
LOCK_TIMEOUT=1800  # 30 minutes

acquire_lock() {
  if [[ -f "${LOCK_FILE}" ]]; then
    # stat -f on macOS, stat -c on Linux
    lock_time=$(stat -f %m "${LOCK_FILE}" 2>/dev/null || stat -c %Y "${LOCK_FILE}" 2>/dev/null || echo 0)
    now=$(date +%s)
    age=$(( now - lock_time ))

    if [[ ${age} -lt ${LOCK_TIMEOUT} ]]; then
      echo "ERROR: Another rebase-wave is running (lock age: ${age}s). PID: $(cat "${LOCK_FILE}" 2>/dev/null || echo unknown)" >&2
      exit 1
    fi
    log "WARN: Stale lock detected (age: ${age}s). Removing."
    rm -f "${LOCK_FILE}"
  fi
  echo "$$" > "${LOCK_FILE}"
  trap 'rm -f "${LOCK_FILE}"' EXIT
}

# ---------------------------------------------------------------------------
# Branch discovery via gh
# ---------------------------------------------------------------------------

discover_branches_from_prs() {
  local full_repo="${ORG}/${REPO_NAME}"
  log "Discovering open PR branches from ${full_repo}..."

  local branches_json
  branches_json=$(gh pr list \
    --repo "${full_repo}" \
    --state open \
    --limit 200 \
    --json headRefName \
    2>&1) || {
    echo "ERROR: gh pr list failed for ${full_repo}: ${branches_json}" >&2
    exit 1
  }

  local discovered
  discovered=$(echo "${branches_json}" | jq -r '.[].headRefName' 2>/dev/null) || {
    echo "ERROR: Failed to parse gh pr list output" >&2
    exit 1
  }

  if [[ -z "${discovered}" ]]; then
    log "No open PRs found for ${full_repo}"
    return
  fi

  while IFS= read -r branch; do
    [[ -n "${branch}" ]] && BRANCHES+=("${branch}")
  done <<< "${discovered}"

  log "Discovered ${#BRANCHES[@]} branches from open PRs"
}

# ---------------------------------------------------------------------------
# Per-branch rebase
# ---------------------------------------------------------------------------

rebase_branch() {
  local branch="$1"

  log "--- Processing: ${branch}"

  # Fetch the branch and main
  git -C "${REPO_ROOT}" fetch origin "${branch}" 2>/dev/null || {
    log "WARN: Could not fetch origin/${branch} — branch may not exist remotely, skipping"
    SKIPPED+=("${branch} (fetch-failed)")
    log_machine "SKIPPED branch=${branch} reason=fetch-failed"
    return
  }
  git -C "${REPO_ROOT}" fetch origin main 2>/dev/null

  # Check if branch is already up-to-date with main
  local branch_sha main_sha merge_base
  branch_sha=$(git -C "${REPO_ROOT}" rev-parse "origin/${branch}" 2>/dev/null) || {
    log "WARN: origin/${branch} not found after fetch — skipping"
    SKIPPED+=("${branch} (ref-not-found)")
    log_machine "SKIPPED branch=${branch} reason=ref-not-found"
    return
  }
  main_sha=$(git -C "${REPO_ROOT}" rev-parse "origin/main")
  merge_base=$(git -C "${REPO_ROOT}" merge-base "${branch_sha}" "${main_sha}")

  if [[ "${merge_base}" == "${main_sha}" ]]; then
    log "SKIP: ${branch} is already up-to-date with origin/main"
    SKIPPED+=("${branch}")
    log_machine "SKIPPED branch=${branch} reason=already-up-to-date"
    return
  fi

  # Create/reset local branch tracking the remote
  git -C "${REPO_ROOT}" checkout -B "${branch}" "origin/${branch}" 2>/dev/null

  # Attempt rebase
  local conflict_files
  if git -C "${REPO_ROOT}" rebase origin/main >"${TMPDIR:-/tmp}/rebase-wave-${branch//\//-}.log" 2>&1; then
    log "OK: ${branch} rebased successfully"
  else
    # Capture conflict files before aborting
    conflict_files=$(git -C "${REPO_ROOT}" diff --name-only --diff-filter=U 2>/dev/null | tr '\n' ',')
    git -C "${REPO_ROOT}" rebase --abort 2>/dev/null || true

    CONFLICTED+=("${branch}")
    CONFLICT_FILES+=("${conflict_files:-unknown}")
    log "CONFLICT: ${branch} — conflicting files: ${conflict_files:-unknown}"
    log_machine "CONFLICTED branch=${branch} files=${conflict_files:-unknown}"
    return
  fi

  # Optional: run pre-commit on rebased branch
  if [[ "${PRE_COMMIT}" == "true" ]]; then
    log "Running pre-commit on ${branch}..."
    local pc_exit=0
    (cd "${REPO_ROOT}" && uv run pre-commit run --all-files) || pc_exit=$?
    if [[ ${pc_exit} -ne 0 ]]; then
      log "WARN: pre-commit failed on ${branch} (exit ${pc_exit}) — skipping push"
      SKIPPED+=("${branch} (pre-commit-failed)")
      log_machine "SKIPPED branch=${branch} reason=pre-commit-failed exit=${pc_exit}"
      git -C "${REPO_ROOT}" checkout - 2>/dev/null || true
      return
    fi
  fi

  # Push
  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY-RUN: would push ${branch} --force-with-lease"
    REBASED+=("${branch} (dry-run)")
    log_machine "REBASED branch=${branch} dry_run=true"
  else
    local push_exit=0
    git -C "${REPO_ROOT}" push --force-with-lease origin "${branch}" 2>/dev/null || push_exit=$?
    if [[ ${push_exit} -ne 0 ]]; then
      log "WARN: push failed for ${branch} (exit ${push_exit}) — branch rebased locally but not pushed"
      SKIPPED+=("${branch} (push-failed)")
      log_machine "SKIPPED branch=${branch} reason=push-failed exit=${push_exit}"
    else
      REBASED+=("${branch}")
      log_machine "REBASED branch=${branch}"
    fi
  fi

  # Return to detached HEAD / prior state
  git -C "${REPO_ROOT}" checkout - 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print_summary() {
  echo ""
  echo "=============================="
  echo " rebase-wave summary"
  echo " Run ID: ${RUN_ID}"
  [[ "${DRY_RUN}" == "true" ]] && echo " Mode: DRY-RUN (no pushes)"
  echo "=============================="
  echo ""

  echo "REBASED: ${#REBASED[@]}"
  for b in "${REBASED[@]}"; do
    echo "  + ${b}"
  done

  echo ""
  echo "CONFLICTED: ${#CONFLICTED[@]}"
  for i in "${!CONFLICTED[@]}"; do
    echo "  x ${CONFLICTED[$i]}"
    [[ -n "${CONFLICT_FILES[$i]:-}" ]] && echo "    files: ${CONFLICT_FILES[$i]}"
  done

  echo ""
  echo "SKIPPED: ${#SKIPPED[@]}"
  for b in "${SKIPPED[@]}"; do
    echo "  - ${b}"
  done

  echo ""
  if [[ ${#CONFLICTED[@]} -gt 0 ]]; then
    echo "RESULT: ${#CONFLICTED[@]} branch(es) need manual attention."
    echo "        Rebase conflict logs: ${TMPDIR:-/tmp}/rebase-wave-<branch>.log"
  else
    echo "RESULT: All branches processed successfully."
  fi
}

# ===========================================================================
# Main
# ===========================================================================

preflight
acquire_lock

if [[ -z "${REPO_NAME}" ]]; then
  REPO_NAME=$(detect_repo_name)
fi

log "=== rebase-wave ${RUN_ID} starting ==="
log "Repo: ${ORG}/${REPO_NAME} (root: ${REPO_ROOT})"
log "Dry-run: ${DRY_RUN} | Pre-commit: ${PRE_COMMIT} | From-PR-list: ${FROM_PR_LIST}"

if [[ "${FROM_PR_LIST}" == "true" ]]; then
  discover_branches_from_prs
fi

if [[ ${#BRANCHES[@]} -eq 0 ]]; then
  echo "ERROR: No branches to process. Use --branches or --from-pr-list." >&2
  exit 1
fi

log "Branches to process (${#BRANCHES[@]}): ${BRANCHES[*]}"

for branch in "${BRANCHES[@]}"; do
  rebase_branch "${branch}"
done

print_summary

if [[ ${#CONFLICTED[@]} -gt 0 ]]; then
  exit 1
fi
exit 0
