#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Smoke test for check-unresolved-threads.sh jq filter logic.
#
# Sources the jq filter *definitions* directly out of the real script (the
# portion before the live `gh api graphql` call) instead of hand-copying the
# filter text, so a future edit to the script is exercised by this test
# automatically rather than silently diverging from a stale copy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${SCRIPT_DIR}/../../scripts/check-unresolved-threads.sh"

grep -q "Usage: check-unresolved-threads.sh" "$SCRIPT" || { echo "FAIL: missing Usage comment"; exit 1; }

# Extract everything before the live `gh api graphql` call (marked by `RAW=""`)
# and source it with dummy positional args, so BLOCKING_JQ / SECRET_BLOCKING_JQ /
# CONCESSION_JQ / SECRET_EVIDENCE_ACK_JQ are the script's real, current values.
FILTER_EXTRACT="$(mktemp)"
trap 'rm -f "$FILTER_EXTRACT"' EXIT
awk '/^RAW=""/{exit} {print}' "$SCRIPT" > "$FILTER_EXTRACT"
# shellcheck disable=SC1090
source "$FILTER_EXTRACT" dummyowner dummyrepo 1

for required_var in BLOCKING_JQ CONCESSION_JQ SECRET_BLOCKING_JQ SECRET_EVIDENCE_ACK_JQ; do
  [ -n "${!required_var:-}" ] || { echo "FAIL: $required_var not defined by script extract"; exit 1; }
done

# gh api graphql --paginate outputs one JSON object per page (not an array).
# jq -s collects them into [obj1, obj2, ...]. Mocks replicate that: one object per echo.
# Most mock nodes include totalCount equal to the number of fetched nodes; Case E below
# intentionally tests the truncation path (totalCount > fetched) and is the sole exception.

# Case 1: one unresolved CR thread, one resolved CR thread, one unresolved human thread -> expect 1
COUNT=$(echo '{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"isResolved":false,"comments":{"totalCount":1,"nodes":[{"body":"<!-- coderabbit: fix -->","author":{"login":"coderabbitai","__typename":"Bot"}}]}},
  {"isResolved":true,"comments":{"totalCount":1,"nodes":[{"body":"resolved","author":{"login":"coderabbitai","__typename":"Bot"}}]}},
  {"isResolved":false,"comments":{"totalCount":1,"nodes":[{"body":"human comment","author":{"login":"jonah","__typename":"User"}}]}}
],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}' \
  | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: count=1 for one unresolved CR thread" || { echo "FAIL: expected 1 got $COUNT"; exit 1; }

# Case 2: all threads resolved -> expect 0
COUNT=$(echo '{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"isResolved":true,"comments":{"totalCount":1,"nodes":[{"body":"<!-- coderabbit: done -->","author":{"login":"coderabbitai","__typename":"Bot"}}]}},
  {"isResolved":true,"comments":{"totalCount":1,"nodes":[{"body":"resolved","author":{"login":"coderabbitai","__typename":"Bot"}}]}}
],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}' \
  | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 0 ] && echo "PASS: count=0 when all threads resolved" || { echo "FAIL: expected 0 got $COUNT"; exit 1; }

# Case A: CR + human rebuttal (__typename=User) + CR concession -> BLOCKING=0, CONCESSION emits line
CASE_A='{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"isResolved":false,"comments":{"totalCount":3,"nodes":[
    {"body":"<!-- coderabbit --> exit 1 on missing python3","author":{"login":"coderabbitai","__typename":"Bot"}},
    {"body":"you are wrong - passthrough design","author":{"login":"jonah","__typename":"User"}},
    {"body":"you'"'"'re right - I apologize, exit 0 is correct behavior","author":{"login":"coderabbitai","__typename":"Bot"}}
  ]}}
],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}'
COUNT=$(echo "$CASE_A" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 0 ] && echo "PASS: Case A blocking=0 after CR concession" || { echo "FAIL Case A: expected 0 got $COUNT"; exit 1; }
ACK=$(echo "$CASE_A" | jq -rs "$CONCESSION_JQ")
echo "$ACK" | grep -q "^cr_concession_ack" && echo "PASS: Case A concession ack emitted" || { echo "FAIL Case A: no cr_concession_ack line; got: $ACK"; exit 1; }

# Case B: CR only (no rebuttal) -> BLOCKING=1
CASE_B='{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"isResolved":false,"comments":{"totalCount":1,"nodes":[
    {"body":"<!-- coderabbit --> missing null check","author":{"login":"coderabbitai","__typename":"Bot"}}
  ]}}
],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}'
COUNT=$(echo "$CASE_B" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case B blocking=1 with CR only (no rebuttal)" || { echo "FAIL Case B: expected 1 got $COUNT"; exit 1; }

# Case C: rebuttal but CR non-concession reply -> BLOCKING=1
CASE_C='{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"isResolved":false,"comments":{"totalCount":3,"nodes":[
    {"body":"<!-- coderabbit --> missing null check","author":{"login":"coderabbitai","__typename":"Bot"}},
    {"body":"intentional design","author":{"login":"jonah","__typename":"User"}},
    {"body":"I will look into this further","author":{"login":"coderabbitai","__typename":"Bot"}}
  ]}}
],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}'
COUNT=$(echo "$CASE_C" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case C blocking=1 without CR concession" || { echo "FAIL Case C: expected 1 got $COUNT"; exit 1; }

# Case D: bot rebuttal (__typename=Bot, not coderabbitai) does NOT count as human rebuttal -> BLOCKING=1
CASE_D='{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"isResolved":false,"comments":{"totalCount":3,"nodes":[
    {"body":"<!-- coderabbit --> missing null check","author":{"login":"coderabbitai","__typename":"Bot"}},
    {"body":"auto-fix applied","author":{"login":"renovate","__typename":"Bot"}},
    {"body":"you'"'"'re right I apologize","author":{"login":"coderabbitai","__typename":"Bot"}}
  ]}}
],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}'
COUNT=$(echo "$CASE_D" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case D blocking=1 when only bot rebuttals (no human)" || { echo "FAIL Case D: expected 1 got $COUNT"; exit 1; }

# Case E: truncated comments (totalCount > fetched) -> conservative BLOCKING=1 even with concession text
CASE_E='{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"isResolved":false,"comments":{"totalCount":60,"nodes":[
    {"body":"<!-- coderabbit --> major finding","author":{"login":"coderabbitai","__typename":"Bot"}},
    {"body":"human rebuttal","author":{"login":"jonah","__typename":"User"}},
    {"body":"you'"'"'re right I apologize","author":{"login":"coderabbitai","__typename":"Bot"}}
  ]}}
],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}'
COUNT=$(echo "$CASE_E" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case E blocking=1 when comments truncated (totalCount=60 > fetched=3)" || { echo "FAIL Case E: expected 1 got $COUNT"; exit 1; }

# Case F: unresolved but outdated CR thread -> BLOCKING=0
CASE_F='{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"isResolved":false,"isOutdated":true,"comments":{"totalCount":1,"nodes":[
    {"body":"<!-- coderabbit --> stale finding","author":{"login":"coderabbitai","__typename":"Bot"}}
  ]}}
],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}'
COUNT=$(echo "$CASE_F" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 0 ] && echo "PASS: Case F blocking=0 for outdated CR thread" || { echo "FAIL Case F: expected 0 got $COUNT"; exit 1; }

# --- OMN-15061 secret-class escalation cases ---------------------------------
# Regression proof for the process hole documented in OMN-15061 / OMN-15058:
# CodeRabbit PR #22 (omniclaude, 2025-11-06) flagged a real, hardcoded Slack
# webhook URL as Critical. The thread auto-resolved (isResolved:true,
# isOutdated:true) the moment the diff swapped the literal for an env-var
# reference — coderabbitai[bot] itself resolved it, with zero human reply.
# The webhook was never actually rotated and stayed live/public for ~260 days.
# Fixture values below are SYNTHETIC (non-matching placeholders), never a real
# credential.

# Case G (RED-proof-of-fix / the incident shape): Critical, "hardcoded" +
# webhook, bot-resolved, zero human comments -> secret-class BLOCKING=1.
# Before the OMN-15061 fix, BLOCKING_JQ alone returns 0 for this exact shape
# (isResolved==true short-circuits it) -- that blindness is the ticket.
CASE_G='{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"isResolved":true,"isOutdated":true,"comments":{"totalCount":1,"nodes":[
    {"body":"_Potential issue_ | _Critical_ CRITICAL: Remove hardcoded Slack webhook URL immediately. This file contains a real credential.","author":{"login":"coderabbitai","__typename":"Bot"}}
  ]}}
],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}'
LEGACY_COUNT=$(echo "$CASE_G" | jq -s "$BLOCKING_JQ")
[ "$LEGACY_COUNT" -eq 0 ] && echo "PASS: Case G confirms BLOCKING_JQ alone is blind to bot-resolved secret-class threads (the OMN-15061 hole)" || { echo "FAIL Case G: expected legacy BLOCKING_JQ=0 got $LEGACY_COUNT"; exit 1; }
SECRET_COUNT=$(echo "$CASE_G" | jq -s "$SECRET_BLOCKING_JQ")
[ "$SECRET_COUNT" -eq 1 ] && echo "PASS: Case G SECRET_BLOCKING_JQ=1 -- bot-resolved CRITICAL hardcoded-webhook thread now blocks" || { echo "FAIL Case G: expected SECRET_BLOCKING_JQ=1 got $SECRET_COUNT"; exit 1; }

# Case H: same finding, but a human posted a rotation-evidence marker after
# actually revoking/rotating the credential -> secret-class BLOCKING=0
# (correctly exempted), and an audit ack line is emitted.
CASE_H='{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"isResolved":true,"isOutdated":true,"comments":{"totalCount":2,"nodes":[
    {"body":"_Potential issue_ | _Critical_ CRITICAL: Remove hardcoded Slack webhook URL immediately. This file contains a real credential.","author":{"login":"coderabbitai","__typename":"Bot"}},
    {"body":"rotation-evidence: OMN-15061 webhook revoked+regenerated in Slack admin console 2026-07-25","author":{"login":"jonah","__typename":"User"}}
  ]}}
],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}'
COUNT=$(echo "$CASE_H" | jq -s "$SECRET_BLOCKING_JQ")
[ "$COUNT" -eq 0 ] && echo "PASS: Case H blocking=0 once a human rotation-evidence marker is present" || { echo "FAIL Case H: expected 0 got $COUNT"; exit 1; }
ACK=$(echo "$CASE_H" | jq -rs "$SECRET_EVIDENCE_ACK_JQ")
echo "$ACK" | grep -q "^secret_rotation_evidence_ack" && echo "PASS: Case H rotation-evidence ack emitted" || { echo "FAIL Case H: no secret_rotation_evidence_ack line; got: $ACK"; exit 1; }

# Case I: CodeRabbit's own "Addressed in commit X" reply must NOT count as
# rotation evidence -- that is exactly the mechanism that let PR #22 slip
# through. Still BLOCKING=1.
CASE_I='{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"isResolved":true,"isOutdated":true,"comments":{"totalCount":2,"nodes":[
    {"body":"_Potential issue_ | _Critical_ CRITICAL: Remove hardcoded Slack webhook URL immediately. This file contains a real credential.","author":{"login":"coderabbitai","__typename":"Bot"}},
    {"body":"Addressed in commit 558ae72 (env-var indirection).","author":{"login":"coderabbitai","__typename":"Bot"}}
  ]}}
],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}'
COUNT=$(echo "$CASE_I" | jq -s "$SECRET_BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case I blocking=1 -- bot's own 'Addressed in commit' reply does not satisfy rotation-evidence" || { echo "FAIL Case I: expected 1 got $COUNT"; exit 1; }

# Case J: unrelated Critical finding (RCE/eval) with no "hardcoded" +
# credential-type match must NOT be caught by the secret-class filter
# (narrow-by-design; rotation doesn't apply to a code-fix-only vuln class).
CASE_J='{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"isResolved":true,"comments":{"totalCount":1,"nodes":[
    {"body":"_Security  Privacy_ | _Critical_ eval() on YAML-derived if: strings is an RCE vector.","author":{"login":"coderabbitai","__typename":"Bot"}}
  ]}}
],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}'
COUNT=$(echo "$CASE_J" | jq -s "$SECRET_BLOCKING_JQ")
[ "$COUNT" -eq 0 ] && echo "PASS: Case J blocking=0 -- unrelated Critical (RCE/eval) finding is not misclassified as secret-class" || { echo "FAIL Case J: expected 0 got $COUNT"; exit 1; }

echo "ALL TESTS PASSED"
