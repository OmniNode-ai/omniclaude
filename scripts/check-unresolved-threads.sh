#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Usage: check-unresolved-threads.sh <owner> <repo> <pr_number>
# Prints the count of unresolved review threads as an integer.
set -euo pipefail

OWNER="${1:?owner required}"
REPO="${2:?repo required}"
PR_NUMBER="${3:?pr_number required}"

QUERY='query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100) {
        nodes {
          isResolved
        }
      }
    }
  }
}'

COUNT=$(gh api graphql \
  -f query="$QUERY" \
  -F owner="$OWNER" \
  -F repo="$REPO" \
  -F pr="$PR_NUMBER" \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)] | length')

echo "$COUNT"
