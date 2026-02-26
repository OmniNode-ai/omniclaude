#!/usr/bin/env bash
# ci-status.sh -- STANDALONE backend for ci-watch CI status extraction
#
# Wraps `gh pr checks` and `gh run view --log-failed` into structured JSON.
# Skills call this when ONEX_TIER != FULL_ONEX.
#
# FULL_ONEX equivalent: inbox-wait (push-based CI notifications via event bus)
#
# Usage:
#   ci-status.sh --pr <number> --repo <org/repo> [--wait] [--timeout <seconds>]
#
# Modes:
#   Default: snapshot -- return current CI status and exit
#   --wait:  poll until terminal state (all checks pass/fail) or timeout
#
# Output: JSON object to stdout with fields:
#   { "pr": N, "repo": "...", "status": "passing|failing|pending",
#     "checks": [...], "failing_checks": [...], "log_excerpt": "..." }
set -euo pipefail

PR=""
REPO=""
WAIT=false
TIMEOUT=3600  # 1 hour default

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pr)       PR="$2";       shift 2 ;;
    --repo)     REPO="$2";     shift 2 ;;
    --wait)     WAIT=true;     shift   ;;
    --timeout)  TIMEOUT="$2";  shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$PR" || -z "$REPO" ]]; then
  echo "Error: --pr and --repo are required" >&2
  exit 1
fi

# Fetch current checks as JSON
fetch_checks() {
  gh pr checks "$PR" --repo "$REPO" --json name,state,conclusion,startedAt,completedAt,detailsUrl 2>/dev/null || echo "[]"
}

# Determine overall status from checks array
compute_status() {
  local checks_json="$1"
  local has_pending has_failing
  has_pending=$(echo "$checks_json" | jq '[.[] | select(.state == "PENDING" or .state == "QUEUED" or .state == "IN_PROGRESS")] | length')
  has_failing=$(echo "$checks_json" | jq '[.[] | select(.conclusion == "FAILURE" or .conclusion == "TIMED_OUT" or .conclusion == "CANCELLED")] | length')

  if [[ "$has_failing" -gt 0 ]]; then
    echo "failing"
  elif [[ "$has_pending" -gt 0 ]]; then
    echo "pending"
  else
    echo "passing"
  fi
}

# Extract failing check details
extract_failures() {
  local checks_json="$1"
  echo "$checks_json" | jq '[.[] | select(.conclusion == "FAILURE" or .conclusion == "TIMED_OUT")]'
}

# Fetch failed run log excerpt
fetch_failed_log() {
  local branch
  branch=$(gh pr view "$PR" --repo "$REPO" --json headRefName -q '.headRefName' 2>/dev/null || echo "")
  if [[ -z "$branch" ]]; then
    echo ""
    return
  fi

  local run_id
  run_id=$(gh run list --branch "$branch" --repo "$REPO" -L 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || echo "")
  if [[ -z "$run_id" ]]; then
    echo ""
    return
  fi

  # Get last 200 lines of failed log
  gh run view "$run_id" --repo "$REPO" --log-failed 2>/dev/null | tail -200 || echo ""
}

if [[ "$WAIT" == "true" ]]; then
  START_TIME=$(date +%s)
  while true; do
    CHECKS=$(fetch_checks)
    STATUS=$(compute_status "$CHECKS")

    if [[ "$STATUS" != "pending" ]]; then
      break
    fi

    ELAPSED=$(( $(date +%s) - START_TIME ))
    if [[ "$ELAPSED" -ge "$TIMEOUT" ]]; then
      STATUS="timeout"
      break
    fi

    sleep 30
  done
else
  CHECKS=$(fetch_checks)
  STATUS=$(compute_status "$CHECKS")
fi

FAILING=$(extract_failures "$CHECKS")

LOG_EXCERPT=""
if [[ "$STATUS" == "failing" ]]; then
  LOG_EXCERPT=$(fetch_failed_log)
fi

# Output structured JSON
jq -n \
  --argjson pr "$PR" \
  --arg repo "$REPO" \
  --arg status "$STATUS" \
  --argjson checks "$CHECKS" \
  --argjson failing_checks "$FAILING" \
  --arg log_excerpt "$LOG_EXCERPT" \
  '{
    pr: $pr,
    repo: $repo,
    status: $status,
    checks: $checks,
    failing_checks: $failing_checks,
    log_excerpt: $log_excerpt
  }'
