#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# ci-status.sh -- Extract CI failure details for a PR or branch.
#
# Outputs structured JSON suitable for consumption by node_ci_repair_effect
# and the enhanced ci-fix-pipeline skill.
#
# Usage:
#   ci-status.sh --pr <PR_NUMBER> [--repo <OWNER/REPO>] [--wait] [--timeout <seconds>]
#   ci-status.sh --branch <BRANCH>  [--repo <OWNER/REPO>] [--wait] [--timeout <seconds>]
#
# Modes:
#   Default: snapshot -- return current CI status and exit
#   --wait:  poll until terminal state (all checks pass/fail) or timeout
#
# Output JSON:
#   {
#     "status": "failing" | "passing" | "pending" | "unknown",
#     "pr_number": 42,
#     "repo": "OmniNode-ai/omniclaude",
#     "branch": "jonah/omn-2829-self-healing-ci",
#     "run_id": "12345678",
#     "failed_jobs": [
#       {
#         "job_id": "56174634733",
#         "job_name": "lint / ruff",
#         "step": "Run ruff check",
#         "conclusion": "failure",
#         "log_excerpt": "..."
#       }
#     ],
#     "failure_summary": "2 jobs failed: lint / ruff, test / pytest",
#     "fetched_at": "2026-02-26T13:00:00Z"
#   }
#
# Exit codes:
#   0 - Success (data retrieved, may include failures)
#   1 - Error (missing dependencies, API failure)
#   2 - No CI runs found

set -euo pipefail

# --- Argument parsing ---
PR=""
BRANCH=""
REPO=""
WAIT=false
TIMEOUT=3600  # 1 hour default

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pr)       PR="$2";       shift 2 ;;
    --branch)   BRANCH="$2";   shift 2 ;;
    --repo)     REPO="$2";     shift 2 ;;
    --wait)     WAIT=true;     shift   ;;
    --timeout)  TIMEOUT="$2";  shift 2 ;;
    --help|-h)
      echo "Usage: ci-status.sh --pr <N> [--repo ORG/REPO] [--wait] [--timeout <seconds>]"
      echo "       ci-status.sh --branch <NAME> [--repo ORG/REPO] [--wait] [--timeout <seconds>]"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# --- Dependency check ---
if ! command -v gh &>/dev/null; then
  echo '{"error": "gh CLI not found. Install: brew install gh"}' >&2
  exit 1
fi
if ! command -v jq &>/dev/null; then
  echo '{"error": "jq not found. Install: brew install jq"}' >&2
  exit 1
fi

# --- Resolve repo ---
if [[ -z "$REPO" ]]; then
  REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner' 2>/dev/null || true)
  if [[ -z "$REPO" ]]; then
    echo '{"error": "Could not detect repo. Use --repo ORG/REPO"}' >&2
    exit 1
  fi
fi

# --- Resolve branch from PR if needed ---
if [[ -n "$PR" && -z "$BRANCH" ]]; then
  BRANCH=$(gh pr view "$PR" --repo "$REPO" --json headRefName -q '.headRefName' 2>/dev/null || true)
  if [[ -z "$BRANCH" ]]; then
    echo "{\"error\": \"Could not resolve branch for PR #$PR\"}" >&2
    exit 1
  fi
fi

if [[ -z "$BRANCH" ]]; then
  BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
fi

if [[ -z "$BRANCH" ]]; then
  echo '{"error": "No branch specified and not in a git repository"}' >&2
  exit 1
fi

# --- Fetch CI status (with optional polling) ---
fetch_run_status() {
  local run_json ci_status

  run_json=$(gh run list \
    --branch "$BRANCH" \
    --repo "$REPO" \
    -L 1 \
    --json databaseId,status,conclusion,name \
    2>/dev/null || echo "[]")

  if [[ "$run_json" == "[]" || -z "$run_json" ]]; then
    echo "no_runs"
    return
  fi

  local run_status run_conclusion
  run_status=$(echo "$run_json" | jq -r '.[0].status')
  run_conclusion=$(echo "$run_json" | jq -r '.[0].conclusion')

  if [[ "$run_status" == "in_progress" || "$run_status" == "queued" || "$run_status" == "waiting" ]]; then
    echo "pending"
  elif [[ "$run_conclusion" == "success" ]]; then
    echo "passing"
  elif [[ "$run_conclusion" == "failure" || "$run_conclusion" == "timed_out" ]]; then
    echo "failing"
  else
    echo "unknown"
  fi
}

if [[ "$WAIT" == "true" ]]; then
  START_TIME=$(date +%s)
  while true; do
    CI_STATUS=$(fetch_run_status)

    if [[ "$CI_STATUS" != "pending" && "$CI_STATUS" != "no_runs" ]]; then
      break
    fi

    ELAPSED=$(( $(date +%s) - START_TIME ))
    if [[ "$ELAPSED" -ge "$TIMEOUT" ]]; then
      CI_STATUS="timeout"
      break
    fi

    sleep 30
  done
else
  CI_STATUS=$(fetch_run_status)
fi

# --- Handle no runs case ---
if [[ "$CI_STATUS" == "no_runs" ]]; then
  jq -n \
    --arg status "unknown" \
    --arg pr "$PR" \
    --arg repo "$REPO" \
    --arg branch "$BRANCH" \
    --arg fetched_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{
      status: $status,
      pr_number: (if $pr == "" then null else ($pr | tonumber) end),
      repo: $repo,
      branch: $branch,
      run_id: null,
      failed_jobs: [],
      failure_summary: "No CI runs found",
      fetched_at: $fetched_at
    }'
  exit 2
fi

# --- Fetch run details ---
RUN_JSON=$(gh run list \
  --branch "$BRANCH" \
  --repo "$REPO" \
  -L 1 \
  --json databaseId,status,conclusion,name \
  2>/dev/null || echo "[]")

RUN_ID=$(echo "$RUN_JSON" | jq -r '.[0].databaseId')

# --- Fetch failed jobs if failing ---
FAILED_JOBS="[]"
FAILURE_SUMMARY=""

if [[ "$CI_STATUS" == "failing" ]]; then
  # Get all jobs for this run
  JOBS_JSON=$(gh run view "$RUN_ID" \
    --repo "$REPO" \
    --json jobs \
    2>/dev/null || echo '{"jobs":[]}')

  # Extract failed jobs
  FAILED_JOBS=$(echo "$JOBS_JSON" | jq '[
    .jobs[]
    | select(.conclusion == "failure")
    | {
        job_id: (.databaseId | tostring),
        job_name: .name,
        step: (
          [.steps[] | select(.conclusion == "failure") | .name]
          | if length > 0 then .[0] else "unknown step" end
        ),
        conclusion: .conclusion,
        log_excerpt: ""
      }
  ]')

  # Try to get log excerpts for each failed job (best-effort, truncated)
  FAILED_COUNT=$(echo "$FAILED_JOBS" | jq 'length')
  if [[ "$FAILED_COUNT" -gt 0 ]]; then
    # Get failed log output (truncated to avoid huge payloads)
    LOG_OUTPUT=$(gh run view "$RUN_ID" --repo "$REPO" --log-failed 2>/dev/null | tail -100 || echo "")

    if [[ -n "$LOG_OUTPUT" ]]; then
      # Escape for JSON embedding
      LOG_ESCAPED=$(echo "$LOG_OUTPUT" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()[:2000]))" 2>/dev/null || echo '""')
      # Attach log excerpt to the first failed job
      FAILED_JOBS=$(echo "$FAILED_JOBS" | jq --argjson log "$LOG_ESCAPED" '
        if length > 0 then .[0].log_excerpt = $log else . end
      ')
    fi

    # Build summary
    JOB_NAMES=$(echo "$FAILED_JOBS" | jq -r '[.[].job_name] | join(", ")')
    FAILURE_SUMMARY="$FAILED_COUNT job(s) failed: $JOB_NAMES"
  fi
fi

if [[ -z "$FAILURE_SUMMARY" && "$CI_STATUS" == "passing" ]]; then
  FAILURE_SUMMARY="All checks passing"
elif [[ -z "$FAILURE_SUMMARY" && "$CI_STATUS" == "pending" ]]; then
  FAILURE_SUMMARY="CI is still running"
elif [[ -z "$FAILURE_SUMMARY" ]]; then
  FAILURE_SUMMARY="Status: $CI_STATUS"
fi

# --- Output JSON ---
jq -n \
  --arg status "$CI_STATUS" \
  --arg pr "$PR" \
  --arg repo "$REPO" \
  --arg branch "$BRANCH" \
  --arg run_id "$RUN_ID" \
  --argjson failed_jobs "$FAILED_JOBS" \
  --arg failure_summary "$FAILURE_SUMMARY" \
  --arg fetched_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{
    status: $status,
    pr_number: (if $pr == "" then null else ($pr | tonumber) end),
    repo: $repo,
    branch: $branch,
    run_id: $run_id,
    failed_jobs: $failed_jobs,
    failure_summary: $failure_summary,
    fetched_at: $fetched_at
  }'
