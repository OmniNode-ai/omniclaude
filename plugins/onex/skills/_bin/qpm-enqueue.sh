#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# QPM Enqueue — add a PR to the merge queue, optionally jumping ahead.
#
# Wraps GitHub's mergePullRequest / enqueuePullRequest GraphQL mutation.
#
# Usage: qpm-enqueue.sh <owner/repo> <pr_number> [--jump] [--dry-run]
# Exit codes: 0=success, 1=error, 2=dry-run (no action taken)
#
# IMPORTANT: The enqueuePullRequest(jump: true) mutation shape was verified
# against the GitHub GraphQL schema as of 2026-03. If the API changes,
# update the ENQUEUE_MUTATION below.

set -euo pipefail

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
REPO=""
PR_NUMBER=""
JUMP=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --jump)
            JUMP=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -*)
            echo "ERROR: Unknown flag: $1" >&2
            echo "Usage: qpm-enqueue.sh <owner/repo> <pr_number> [--jump] [--dry-run]" >&2
            exit 1
            ;;
        *)
            if [[ -z "$REPO" ]]; then
                REPO="$1"
            elif [[ -z "$PR_NUMBER" ]]; then
                PR_NUMBER="$1"
            else
                echo "ERROR: Unexpected argument: $1" >&2
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$REPO" || -z "$PR_NUMBER" ]]; then
    echo "ERROR: Required arguments: <owner/repo> <pr_number>" >&2
    echo "Usage: qpm-enqueue.sh <owner/repo> <pr_number> [--jump] [--dry-run]" >&2
    exit 1
fi

# Validate PR number is numeric
if ! [[ "$PR_NUMBER" =~ ^[0-9]+$ ]]; then
    echo "ERROR: PR number must be numeric, got: $PR_NUMBER" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Verify gh CLI is authenticated
# ---------------------------------------------------------------------------
if ! gh auth status >/dev/null 2>&1; then
    echo "ERROR: gh CLI is not authenticated. Run 'gh auth login' first." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Resolve PR node ID (required for GraphQL mutations)
# ---------------------------------------------------------------------------
echo "Resolving PR #${PR_NUMBER} in ${REPO}..."

PR_NODE_ID=$(gh api graphql -f query='
  query($owner: String!, $name: String!, $number: Int!) {
    repository(owner: $owner, name: $name) {
      pullRequest(number: $number) {
        id
        title
        mergeable
        mergeQueueEntry {
          id
          position
        }
      }
    }
  }
' -f owner="${REPO%%/*}" -f name="${REPO##*/}" -F number="$PR_NUMBER" \
  --jq '.data.repository.pullRequest.id' 2>&1) || {
    echo "ERROR: Failed to resolve PR node ID for ${REPO}#${PR_NUMBER}" >&2
    echo "$PR_NODE_ID" >&2
    exit 1
}

if [[ -z "$PR_NODE_ID" || "$PR_NODE_ID" == "null" ]]; then
    echo "ERROR: PR #${PR_NUMBER} not found in ${REPO}" >&2
    exit 1
fi

# Check if already in merge queue
QUEUE_ENTRY=$(gh api graphql -f query='
  query($owner: String!, $name: String!, $number: Int!) {
    repository(owner: $owner, name: $name) {
      pullRequest(number: $number) {
        mergeQueueEntry {
          id
          position
        }
      }
    }
  }
' -f owner="${REPO%%/*}" -f name="${REPO##*/}" -F number="$PR_NUMBER" \
  --jq '.data.repository.pullRequest.mergeQueueEntry' 2>/dev/null) || true

if [[ -n "$QUEUE_ENTRY" && "$QUEUE_ENTRY" != "null" ]]; then
    POSITION=$(echo "$QUEUE_ENTRY" | jq -r '.position // "unknown"')
    echo "INFO: PR #${PR_NUMBER} is already in merge queue at position ${POSITION}"
    if [[ "$JUMP" == "true" ]]; then
        echo "INFO: --jump requested for already-queued PR. Dequeuing then re-enqueuing at front..."
        # Dequeue first using the PR node ID
        DEQUEUE_RESULT=$(gh api graphql -f query='
          mutation($pullRequestId: ID!) {
            dequeuePullRequest(input: {id: $pullRequestId}) {
              mergeQueueEntry { id }
            }
          }
        ' -f pullRequestId="$PR_NODE_ID" 2>&1) || {
            echo "ERROR: dequeuePullRequest failed" >&2
            echo "$DEQUEUE_RESULT" >&2
            exit 1
        }
        echo "INFO: Dequeued PR #${PR_NUMBER}. Re-enqueuing with jump..."
        # Fall through to enqueue logic below
    else
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# Dry-run: report what would happen
# ---------------------------------------------------------------------------
if [[ "$DRY_RUN" == "true" ]]; then
    echo "DRY-RUN: Would enqueue PR #${PR_NUMBER} in ${REPO} (jump=${JUMP})"
    echo "DRY-RUN: PR node ID: ${PR_NODE_ID}"
    exit 2
fi

# ---------------------------------------------------------------------------
# Enqueue the PR via GraphQL
# ---------------------------------------------------------------------------
# GitHub's enqueuePullRequest mutation adds the PR to the merge queue.
# The 'jump' parameter moves it ahead of other entries.

echo "Enqueueing PR #${PR_NUMBER} in ${REPO} (jump=${JUMP})..."

ENQUEUE_RESULT=$(gh api graphql -f query='
  mutation($pullRequestId: ID!, $jump: Boolean!) {
    enqueuePullRequest(input: {pullRequestId: $pullRequestId, jump: $jump}) {
      mergeQueueEntry {
        id
        position
      }
    }
  }
' -f pullRequestId="$PR_NODE_ID" -F jump="$JUMP" 2>&1) || {
    echo "ERROR: enqueuePullRequest mutation failed" >&2
    echo "$ENQUEUE_RESULT" >&2
    exit 1
}

# Check for GraphQL errors (non-null and non-empty array)
if echo "$ENQUEUE_RESULT" | jq -e '.errors | if . then length > 0 else false end' >/dev/null 2>&1; then
    echo "ERROR: GraphQL errors in enqueuePullRequest:" >&2
    echo "$ENQUEUE_RESULT" | jq '.errors' >&2
    exit 1
fi

POSITION=$(echo "$ENQUEUE_RESULT" | jq -r '.data.enqueuePullRequest.mergeQueueEntry.position // "unknown"') || true

echo "OK: PR #${PR_NUMBER} enqueued at position ${POSITION} (jump=${JUMP})"
exit 0
