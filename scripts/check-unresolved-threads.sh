#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Usage: check-unresolved-threads.sh <owner> <repo> <pr_number>
# Prints the count of unresolved CodeRabbit review threads as an integer.
# A thread is counted if: isResolved=false AND the first comment body matches
# CodeRabbit authorship patterns (coderabbitai bot or CR signature lines).
# Threads where a human rebuttal exists AND CR's last reply is a concession
# (you're right / apologize / correct behavior / retract) are excluded from
# the count and logged to stderr as cr_concession_ack lines.
set -euo pipefail

OWNER="${1:?owner required}"
REPO="${2:?repo required}"
PR_NUMBER="${3:?pr_number required}"

QUERY='query($owner: String!, $repo: String!, $pr: Int!, $endCursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100, after: $endCursor) {
        nodes {
          isResolved
          comments(first: 50) {
            nodes {
              body
              author {
                login
              }
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}'

# Threads to exclude (CR conceded after human rebuttal). Emits audit lines to stderr.
CONCESSION_JQ='[
  .[].data.repository.pullRequest.reviewThreads.nodes[]
  | select(.isResolved == false)
  | select(
      .comments.nodes[0] != null and (
        ((.comments.nodes[0].author.login // "") | test("coderabbitai"; "i")) or
        ((.comments.nodes[0].body // "") | test("_\\*\\*coderabbit|<!--\\s*coderabbit|coderabbit\\.ai|\\*\\*coderabbit"; "i"))
      )
    )
  | select(
      ([.comments.nodes[1:][] | select((.author.login // "") | test("coderabbitai"; "i") | not)] | length > 0)
      and
      ([.comments.nodes[] | select((.author.login // "") | test("coderabbitai"; "i"))] | last // {} | .body // "" | test("you.?re right|apolog(y|ize|ise)|correct behavior|i.?ll retract|you.?re correct"; "i"))
    )
  | "cr_concession_ack path=\(.comments.nodes[0].body[:40] // "unknown" | gsub("\\n";" ")) line=\([.comments.nodes[] | select((.author.login // "") | test("coderabbitai"; "i"))] | last // {} | .body // "" | .[:80] | gsub("\\n";" "))"
][]'

# Threads still blocking (CR thread without a concession-after-rebuttal pattern).
BLOCKING_JQ='[
  .[].data.repository.pullRequest.reviewThreads.nodes[]
  | select(.isResolved == false)
  | select(
      .comments.nodes[0] != null and (
        ((.comments.nodes[0].author.login // "") | test("coderabbitai"; "i")) or
        ((.comments.nodes[0].body // "") | test("_\\*\\*coderabbit|<!--\\s*coderabbit|coderabbit\\.ai|\\*\\*coderabbit"; "i"))
      )
    )
  | select(
      (
        ([.comments.nodes[1:][] | select((.author.login // "") | test("coderabbitai"; "i") | not)] | length > 0)
        and
        ([.comments.nodes[] | select((.author.login // "") | test("coderabbitai"; "i"))] | last // {} | .body // "" | test("you.?re right|apolog(y|ize|ise)|correct behavior|i.?ll retract|you.?re correct"; "i"))
      ) | not
    )
] | length'

RAW=$(gh api graphql --paginate \
  -f query="$QUERY" \
  -F owner="$OWNER" \
  -F repo="$REPO" \
  -F pr="$PR_NUMBER")

# Emit concession acks to stderr so CI logs are auditable
echo "$RAW" | jq -rs "$CONCESSION_JQ" >&2

COUNT=$(echo "$RAW" | jq -s "$BLOCKING_JQ")
echo "$COUNT"
