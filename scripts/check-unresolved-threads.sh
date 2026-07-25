#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Usage: check-unresolved-threads.sh <owner> <repo> <pr_number>
# Prints the count of unresolved CodeRabbit review threads as an integer.
# A thread is counted if: isResolved=false, isOutdated=false, AND the first
# comment body matches CodeRabbit authorship patterns (coderabbitai bot or CR
# signature lines).
# Threads where a human rebuttal exists AND CR's last reply is a concession
# (you're right / apologize / correct behavior / retract / understood + defer/
# reasonable/pragmatic) are excluded from the count and logged to stderr as
# cr_concession_ack lines.
# Threads with more comments than fetched (totalCount > fetched) are skipped
# and counted as blocking (conservative: never wrongly exclude on partial data).
#
# SECRET-CLASS ESCALATION (OMN-15061): a CodeRabbit "Critical...hardcoded
# <webhook|api key|password|token|credential|private key>" finding is a
# distinct, higher-severity class than an ordinary review nit. GitHub/
# CodeRabbit auto-resolve a thread the instant the *visible diff* changes near
# the flagged range — that only proves the literal was swapped for an
# env-var/placeholder, never that the leaked value itself was rotated/revoked
# at its source (Slack, a cloud provider, etc). PR #22 in this repo
# (2025-11-08) is the forensic case: a real Slack webhook was flagged Critical,
# auto-resolved by coderabbitai[bot] itself with zero human reply, and stayed
# live and public for ~260 days.
#
# For this class, `isResolved == true` is NOT sufficient on its own. The
# thread additionally requires a durable, human-authored (never bot-authored)
# `rotation-evidence: <reason-or-ticket>` marker somewhere in the thread —
# mirrors the `# skip-token-allowed: <receipt-id>` escape-hatch pattern already
# used for the deploy-gate skip-token gate elsewhere in this workspace. No
# marker = still counted as blocking, regardless of isResolved/isOutdated.
# Ambiguous/ambiguously-classified findings are NOT exempted by this rule —
# only findings that fail to match the secret-class signature at all skip it.
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
          isOutdated
          comments(first: 50) {
            totalCount
            nodes {
              body
              author {
                login
                __typename
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

# A comment counts as a human rebuttal only if __typename != "Bot" (excludes
# Renovate, Dependabot, and other bots) and login != "coderabbitai".
HUMAN_REBUTTAL_FILTER='select(
  ((.author.__typename // "") != "Bot") and
  ((.author.login // "") | test("coderabbitai"; "i") | not)
)'

# Threads to exclude (CR conceded after human rebuttal). Emits audit lines to stderr.
# Skips threads where fetched comment count < totalCount (incomplete slice — treat as blocking).
CONCESSION_JQ='[
  .[].data.repository.pullRequest.reviewThreads.nodes[]
  | select(.isResolved == false)
  | select((.isOutdated // false) == false)
  | select(
      .comments.nodes[0] != null and (
        ((.comments.nodes[0].author.login // "") | test("coderabbitai"; "i")) or
        ((.comments.nodes[0].body // "") | test("_\\*\\*coderabbit|<!--\\s*coderabbit|coderabbit\\.ai|\\*\\*coderabbit"; "i"))
      )
    )
  | select(.comments.totalCount <= (.comments.nodes | length))
  | select(
      ([.comments.nodes[1:][] | '"$HUMAN_REBUTTAL_FILTER"'] | length > 0)
      and
      ([.comments.nodes[] | select((.author.login // "") | test("coderabbitai"; "i"))] | last // {} | .body // "" | test("you.?re right|apolog(y|ize|ise)|correct behavior|i.?ll retract|you.?re correct|understood(.|\\n){0,200}(reasonable|pragmatic|tradeoff|defer|pre-existing|intentional)|i.?ll defer"; "i"))
    )
  | "cr_concession_ack path=\(.comments.nodes[0].body[:40] // "unknown" | gsub("\\n";" ")) line=\([.comments.nodes[] | select((.author.login // "") | test("coderabbitai"; "i"))] | last // {} | .body // "" | .[:80] | gsub("\\n";" "))"
][]'

# Threads still blocking: CR thread without a concession-after-human-rebuttal pattern,
# OR threads where we could not fetch all comments (totalCount > fetched).
BLOCKING_JQ='[
  .[].data.repository.pullRequest.reviewThreads.nodes[]
  | select(.isResolved == false)
  | select((.isOutdated // false) == false)
  | select(
      .comments.nodes[0] != null and (
        ((.comments.nodes[0].author.login // "") | test("coderabbitai"; "i")) or
        ((.comments.nodes[0].body // "") | test("_\\*\\*coderabbit|<!--\\s*coderabbit|coderabbit\\.ai|\\*\\*coderabbit"; "i"))
      )
    )
  | select(
      (.comments.totalCount > (.comments.nodes | length))
      or
      (
        (
          ([.comments.nodes[1:][] | '"$HUMAN_REBUTTAL_FILTER"'] | length > 0)
          and
          ([.comments.nodes[] | select((.author.login // "") | test("coderabbitai"; "i"))] | last // {} | .body // "" | test("you.?re right|apolog(y|ize|ise)|correct behavior|i.?ll retract|you.?re correct|understood(.|\\n){0,200}(reasonable|pragmatic|tradeoff|defer|pre-existing|intentional)|i.?ll defer"; "i"))
        ) | not
      )
    )
] | length'

# Secret-class signature: a CodeRabbit finding tagged Critical AND naming
# "hardcoded" AND naming one of the common leaked-credential shapes. Narrow by
# design — this must not fire on unrelated Critical findings (RCE/eval,
# injection, etc.) that have no "rotate a secret" remediation step.
SECRET_KEYWORD_RE='hardcoded'
SECRET_TYPE_RE='webhook|api[ _-]?key|password|token|private[ _-]?key|credential'
SECRET_SEVERITY_RE='critical'

# Human-authored rotation-evidence marker, anywhere in the thread (not just
# the first comment). Mirrors the `# skip-token-allowed: <receipt-id>`
# escape-hatch convention used elsewhere in this workspace for gate bypasses:
# a structured, durable, non-bot-authored annotation is required — CodeRabbit
# itself declaring "Addressed in commit X" does NOT count, since that is
# exactly the mechanism that let PR #22's webhook go unrotated for ~260 days.
ROTATION_EVIDENCE_JQ='
  [.comments.nodes[] | '"$HUMAN_REBUTTAL_FILTER"' | (.body // "")]
  | any(test("rotation-evidence:\\s*\\S+"; "i"))
'

# Threads counted as blocking under the secret-class escalation: isResolved
# (by any actor, including the bot itself) but with no rotation-evidence
# marker. Deliberately does NOT re-select isResolved==false threads — those
# are already covered by BLOCKING_JQ above, so this stays additive and
# non-double-counting by construction.
SECRET_BLOCKING_JQ='[
  .[].data.repository.pullRequest.reviewThreads.nodes[]
  | select(.isResolved == true)
  | select(
      .comments.nodes[0] != null and (
        ((.comments.nodes[0].author.login // "") | test("coderabbitai"; "i")) or
        ((.comments.nodes[0].body // "") | test("_\\*\\*coderabbit|<!--\\s*coderabbit|coderabbit\\.ai|\\*\\*coderabbit"; "i"))
      )
    )
  | select(.comments.nodes[0].body // "" | test("'"$SECRET_KEYWORD_RE"'"; "i"))
  | select(.comments.nodes[0].body // "" | test("'"$SECRET_TYPE_RE"'"; "i"))
  | select(.comments.nodes[0].body // "" | test("'"$SECRET_SEVERITY_RE"'"; "i"))
  | select(
      (.comments.totalCount > (.comments.nodes | length))
      or
      (('"$ROTATION_EVIDENCE_JQ"') | not)
    )
] | length'

# Audit line for secret-class threads correctly exempted via rotation-evidence.
SECRET_EVIDENCE_ACK_JQ='[
  .[].data.repository.pullRequest.reviewThreads.nodes[]
  | select(.isResolved == true)
  | select(
      .comments.nodes[0] != null and (
        ((.comments.nodes[0].author.login // "") | test("coderabbitai"; "i")) or
        ((.comments.nodes[0].body // "") | test("_\\*\\*coderabbit|<!--\\s*coderabbit|coderabbit\\.ai|\\*\\*coderabbit"; "i"))
      )
    )
  | select(.comments.nodes[0].body // "" | test("'"$SECRET_KEYWORD_RE"'"; "i"))
  | select(.comments.nodes[0].body // "" | test("'"$SECRET_TYPE_RE"'"; "i"))
  | select(.comments.nodes[0].body // "" | test("'"$SECRET_SEVERITY_RE"'"; "i"))
  | select(.comments.totalCount <= (.comments.nodes | length))
  | select('"$ROTATION_EVIDENCE_JQ"')
  | "secret_rotation_evidence_ack path=\(.comments.nodes[0].body[:60] // "unknown" | gsub("\\n";" "))"
][]'

RAW=""
for attempt in 1 2 3; do
  if RAW=$(gh api graphql --paginate \
    -f query="$QUERY" \
    -F owner="$OWNER" \
    -F repo="$REPO" \
    -F pr="$PR_NUMBER"); then
    break
  fi
  if [ "$attempt" -eq 3 ]; then
    echo "failed to query review threads after ${attempt} attempts" >&2
    exit 1
  fi
  sleep $((attempt * 5))
done

# Emit concession acks to stderr so CI logs are auditable
echo "$RAW" | jq -rs "$CONCESSION_JQ" >&2
echo "$RAW" | jq -rs "$SECRET_EVIDENCE_ACK_JQ" >&2

BLOCKING_COUNT=$(echo "$RAW" | jq -s "$BLOCKING_JQ")
SECRET_BLOCKING_COUNT=$(echo "$RAW" | jq -s "$SECRET_BLOCKING_JQ")
if [ "$SECRET_BLOCKING_COUNT" -gt 0 ]; then
  echo "::error::${SECRET_BLOCKING_COUNT} CodeRabbit CRITICAL hardcoded-credential thread(s) resolved without a rotation-evidence marker. A code-diff swap (env-var indirection) is not proof the leaked value was rotated at its source. Post a human PR comment 'rotation-evidence: <ticket-or-reason>' on the thread only after the actual credential has been revoked/rotated out of band." >&2
fi

COUNT=$((BLOCKING_COUNT + SECRET_BLOCKING_COUNT))
echo "$COUNT"
