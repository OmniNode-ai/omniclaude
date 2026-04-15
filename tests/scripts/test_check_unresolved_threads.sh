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

echo "ALL TESTS PASSED"
