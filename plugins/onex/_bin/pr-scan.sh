#!/usr/bin/env bash
# pr-scan.sh -- STANDALONE backend for merge-sweep / integration-gate PR scanning
#
# Replaces raw `gh pr list` calls with structured JSON output and consistent
# field selection. Skills call this when ONEX_TIER != FULL_ONEX.
#
# FULL_ONEX equivalent: node_git_effect.pr_list()
#
# Usage:
#   pr-scan.sh --repo <org/repo> [--state open] [--limit 100] [--author <login>]
#              [--label <label>] [--since <ISO8601>] [--json-fields <fields>]
#
# Output: JSON array of PR objects to stdout.
# Errors: exit 1 with message to stderr.
set -euo pipefail

REPO=""
STATE="open"
LIMIT="100"
AUTHOR=""
LABEL=""
SINCE=""
JSON_FIELDS="number,title,mergeable,statusCheckRollup,reviewDecision,headRefName,baseRefName,baseRepository,headRepository,headRefOid,author,labels,updatedAt,isDraft"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)         REPO="$2";         shift 2 ;;
    --state)        STATE="$2";        shift 2 ;;
    --limit)        LIMIT="$2";        shift 2 ;;
    --author)       AUTHOR="$2";       shift 2 ;;
    --label)        LABEL="$2";        shift 2 ;;
    --since)        SINCE="$2";        shift 2 ;;
    --json-fields)  JSON_FIELDS="$2";  shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$REPO" ]]; then
  echo "Error: --repo is required" >&2
  exit 1
fi

# Build gh pr list command
CMD=(gh pr list --repo "$REPO" --state "$STATE" --json "$JSON_FIELDS" --limit "$LIMIT")

if [[ -n "$AUTHOR" ]]; then
  CMD+=(--author "$AUTHOR")
fi

if [[ -n "$LABEL" ]]; then
  CMD+=(--label "$LABEL")
fi

# Execute and optionally filter by --since date
OUTPUT=$("${CMD[@]}" 2>&1) || {
  echo "Error: gh pr list failed for $REPO: $OUTPUT" >&2
  exit 1
}

if [[ -n "$SINCE" ]]; then
  # Filter PRs updated after the --since date using jq
  echo "$OUTPUT" | jq --arg since "$SINCE" '[.[] | select(.updatedAt >= $since)]'
else
  echo "$OUTPUT"
fi
