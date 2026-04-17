#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Smoke test for check-unresolved-threads.sh jq filter logic.
# Pipes synthetic GraphQL JSON through the filter; asserts expected counts.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${SCRIPT_DIR}/../../scripts/check-unresolved-threads.sh"

grep -q "Usage: check-unresolved-threads.sh" "$SCRIPT" || { echo "FAIL: missing Usage comment"; exit 1; }

CR_JQ='[
  .[].data.repository.pullRequest.reviewThreads.nodes[]
  | select(.isResolved == false)
  | select(
      .comments.nodes[0] != null and (
        ((.comments.nodes[0].author.login // "") | test("coderabbitai"; "i")) or
        ((.comments.nodes[0].body // "") | test("_\\*\\*coderabbit|<!--\\s*coderabbit|coderabbit\\.ai|\\*\\*coderabbit"; "i"))
      )
    )
] | length'

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

# gh api graphql --paginate outputs one JSON object per page (not an array).
# jq -s collects them into [obj1, obj2, ...]. Mocks replicate that: one object per echo.

# Case 1: one unresolved CR thread, one resolved CR thread, one unresolved human thread -> expect 1
COUNT=$(echo '{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[{"isResolved":false,"comments":{"nodes":[{"body":"<!-- coderabbit: fix -->","author":{"login":"coderabbitai"}}]}},{"isResolved":true,"comments":{"nodes":[{"body":"resolved","author":{"login":"coderabbitai"}}]}},{"isResolved":false,"comments":{"nodes":[{"body":"human comment","author":{"login":"jonah"}}]}}],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}' \
  | jq -s "$CR_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: count=1 for one unresolved CR thread" || { echo "FAIL: expected 1 got $COUNT"; exit 1; }

# Case 2: all threads resolved -> expect 0
COUNT=$(echo '{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[{"isResolved":true,"comments":{"nodes":[{"body":"<!-- coderabbit: done -->","author":{"login":"coderabbitai"}}]}},{"isResolved":true,"comments":{"nodes":[{"body":"resolved","author":{"login":"coderabbitai"}}]}}],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}' \
  | jq -s "$CR_JQ")
[ "$COUNT" -eq 0 ] && echo "PASS: count=0 when all threads resolved" || { echo "FAIL: expected 0 got $COUNT"; exit 1; }

# Case A: CR + human rebuttal + CR concession -> BLOCKING=0, CONCESSION emits a line
CASE_A='{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[{"isResolved":false,"comments":{"nodes":[{"body":"<!-- coderabbit --> exit 1 on missing python3","author":{"login":"coderabbitai"}},{"body":"you are wrong - passthrough design","author":{"login":"jonah"}},{"body":"you'"'"'re right - I apologize, exit 0 is correct behavior","author":{"login":"coderabbitai"}}]}}],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}'
COUNT=$(echo "$CASE_A" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 0 ] && echo "PASS: Case A blocking=0 after CR concession" || { echo "FAIL Case A: expected 0 got $COUNT"; exit 1; }
ACK=$(echo "$CASE_A" | jq -rs "$CONCESSION_JQ")
echo "$ACK" | grep -q "^cr_concession_ack" && echo "PASS: Case A concession ack emitted" || { echo "FAIL Case A: no cr_concession_ack line; got: $ACK"; exit 1; }

# Case B: CR only (no rebuttal) -> BLOCKING=1
CASE_B='{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[{"isResolved":false,"comments":{"nodes":[{"body":"<!-- coderabbit --> missing null check","author":{"login":"coderabbitai"}}]}}],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}'
COUNT=$(echo "$CASE_B" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case B blocking=1 with CR only (no rebuttal)" || { echo "FAIL Case B: expected 1 got $COUNT"; exit 1; }

# Case C: rebuttal but CR non-concession reply -> BLOCKING=1
CASE_C='{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[{"isResolved":false,"comments":{"nodes":[{"body":"<!-- coderabbit --> missing null check","author":{"login":"coderabbitai"}},{"body":"intentional design","author":{"login":"jonah"}},{"body":"I will look into this further","author":{"login":"coderabbitai"}}]}}],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}'
COUNT=$(echo "$CASE_C" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case C blocking=1 without CR concession" || { echo "FAIL Case C: expected 1 got $COUNT"; exit 1; }

echo "ALL TESTS PASSED"
