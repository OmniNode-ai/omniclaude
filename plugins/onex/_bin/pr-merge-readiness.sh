#!/usr/bin/env bash
# pr-merge-readiness.sh -- STANDALONE backend for pr-review and auto-merge
#
# Fetches PR merge readiness state: mergeable status, CI checks, review
# decision, and unresolved comments. Skills call this when ONEX_TIER != FULL_ONEX.
#
# FULL_ONEX equivalent: node_git_effect.pr_view() / node_git_effect.pr_merge()
#
# Usage:
#   pr-merge-readiness.sh --pr <number> --repo <org/repo> [--verbose]
#
# Output: JSON object to stdout with fields:
#   { "pr": N, "repo": "...", "ready": true|false, "mergeable": "...",
#     "ci_status": "passing|failing|pending", "review_decision": "...",
#     "merge_state_status": "...", "unresolved_threads": N, "blockers": [...] }
set -euo pipefail

PR=""
REPO=""
VERBOSE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pr)       PR="$2";       shift 2 ;;
    --repo)     REPO="$2";     shift 2 ;;
    --verbose)  VERBOSE=true;  shift   ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$PR" || -z "$REPO" ]]; then
  echo "Error: --pr and --repo are required" >&2
  exit 1
fi

# Fetch comprehensive PR state
PR_JSON=$(gh pr view "$PR" --repo "$REPO" --json \
  number,title,mergeable,mergeStateStatus,reviewDecision,\
statusCheckRollup,headRefName,baseRefName,isDraft,\
reviewRequests,latestReviews 2>&1) || {
  echo "Error: gh pr view failed: $PR_JSON" >&2
  exit 1
}

# Extract fields
MERGEABLE=$(echo "$PR_JSON" | jq -r '.mergeable')
MERGE_STATE=$(echo "$PR_JSON" | jq -r '.mergeStateStatus')
REVIEW_DECISION=$(echo "$PR_JSON" | jq -r '.reviewDecision // "NONE"')
IS_DRAFT=$(echo "$PR_JSON" | jq -r '.isDraft')

# Compute CI status from statusCheckRollup
CI_STATUS=$(echo "$PR_JSON" | jq -r '
  .statusCheckRollup as $checks |
  if ($checks | length) == 0 then "passing"
  elif [$checks[] | select(.conclusion == "FAILURE" or .conclusion == "TIMED_OUT")] | length > 0 then "failing"
  elif [$checks[] | select(.state == "PENDING" or .state == "QUEUED" or .state == "IN_PROGRESS")] | length > 0 then "pending"
  else "passing"
  end
')

# Count unresolved review threads (requires separate API call)
UNRESOLVED=0
THREAD_JSON=$(gh api "repos/${REPO}/pulls/${PR}/reviews" 2>/dev/null || echo "[]")
CHANGES_REQUESTED=$(echo "$THREAD_JSON" | jq '[.[] | select(.state == "CHANGES_REQUESTED")] | length')

# Build blockers list
BLOCKERS=$(jq -n \
  --arg mergeable "$MERGEABLE" \
  --arg ci "$CI_STATUS" \
  --arg review "$REVIEW_DECISION" \
  --arg draft "$IS_DRAFT" \
  --arg merge_state "$MERGE_STATE" \
  --argjson changes_requested "$CHANGES_REQUESTED" \
  '[
    (if $draft == "true" then "PR is a draft" else empty end),
    (if $mergeable == "CONFLICTING" then "Merge conflicts detected" else empty end),
    (if $ci == "failing" then "CI checks failing" else empty end),
    (if $ci == "pending" then "CI checks still running" else empty end),
    (if $review == "CHANGES_REQUESTED" then "Changes requested in review" else empty end),
    (if $changes_requested > 0 then "Unresolved review threads" else empty end),
    (if $merge_state == "DIRTY" then "Branch is dirty (merge conflicts)" else empty end),
    (if $merge_state == "BLOCKED" then "Merge blocked by branch protection" else empty end)
  ]')

# Determine overall readiness
READY=$(jq -n \
  --arg mergeable "$MERGEABLE" \
  --arg ci "$CI_STATUS" \
  --arg review "$REVIEW_DECISION" \
  --arg draft "$IS_DRAFT" \
  --arg merge_state "$MERGE_STATE" \
  'if $draft == "true" then false
   elif $mergeable != "MERGEABLE" then false
   elif $ci != "passing" then false
   elif $review == "CHANGES_REQUESTED" then false
   elif $merge_state == "DIRTY" or $merge_state == "BLOCKED" then false
   else true
   end')

# Output structured JSON
jq -n \
  --argjson pr "$PR" \
  --arg repo "$REPO" \
  --argjson ready "$READY" \
  --arg mergeable "$MERGEABLE" \
  --arg ci_status "$CI_STATUS" \
  --arg review_decision "$REVIEW_DECISION" \
  --arg merge_state_status "$MERGE_STATE" \
  --argjson unresolved_threads "$CHANGES_REQUESTED" \
  --argjson blockers "$BLOCKERS" \
  '{
    pr: $pr,
    repo: $repo,
    ready: $ready,
    mergeable: $mergeable,
    ci_status: $ci_status,
    review_decision: $review_decision,
    merge_state_status: $merge_state_status,
    unresolved_threads: $unresolved_threads,
    blockers: $blockers
  }'
