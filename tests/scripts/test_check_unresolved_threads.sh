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

# --- OMN-16823 agreement-plus-deferral concession class -----------------------
# CodeRabbit routinely concedes a finding without using any of the pre-OMN-16823
# phrasings ("you're right" / "I apologize" / "understood ... reasonable"). The
# live shape that blocked omnibase_core#1604 was an *agreement* token plus an
# explicit *deferral* to a ticket. Fixtures below are the verbatim bodies of
# that PR's `src/omnibase_core/models/cli/model_cli_user_config_logging.py`
# thread (thread 2 of 3), fetched via
#   gh api graphql -f query='{repository(owner:"OmniNode-ai",name:"omnibase_core"){pullRequest(number:1604){reviewThreads(first:50){nodes{...}}}}}'
#
# The widened class is deliberately a CONJUNCTION (agreement AND deferral AND
# no negation/escalation marker, all in the *salient* body with <details> and
# HTML-comment blocks stripped) on top of the pre-existing human-rebuttal
# precondition. Cases L-R below are the permanent negative controls that keep it
# from degrading into "any CodeRabbit reply clears the thread".
#
# This is a DETECTION change only. Nothing here resolves a thread —
# `pr_review_bot` remains the sole resolver of CodeRabbit threads.

CR_1604_FINDING='<!-- coderabbit --> _Data Integrity  Integration_ | _Minor_ | _Quick win_\n\n**Use an Enum for `logging.level` without changing the YAML contract.**\n\n`normalize_user_config()` accepts unsupported values such as `INF0` because `ModelCliUserConfigLogging.level` is `str`.\n\n<!-- cr-comment:v1:48af85e4011b142ed22fd006 -->'
CR_1604_HUMAN='Declining this one, with the evidence. `EnumLogLevel` members are lowercase (`INFO = info`) and this config on-disk contract is uppercase, so typing the field as `EnumLogLevel` would silently rewrite every `~/.onex/config.yaml` in the fleet. Recorded on OMN-16037 as a follow-up rather than dropped.'
# Verbatim CodeRabbit concession from omnibase_core#1604, including the trailing
# `<details>Learnings added</details>` block the real reply carries.
CR_1604_CONCESSION='`@jonahgabriel`, agreed that `EnumLogLevel` cannot represent this YAML contract. Its lowercase values would cause an unintended serialized-value migration.\n\nThe finding requested a separate uppercase-valued enum, not reuse of `EnumLogLevel`. However, deferring the validation design to OMN-16037 is reasonable because the current PR must avoid silent rewrites of existing configuration files.\n\n---\n\n<details>\n<summary>Learnings added</summary>\n\nLearnt from: jonahgabriel\nRepo: OmniNode-ai/omnibase_core PR: 1604\n\n</details>\n\n<!-- This is an auto-generated reply by CodeRabbit -->'

# Emits a one-thread page whose CR reply body is $1.
cr_1604_thread_with_reply() {
  printf '{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[{"isResolved":false,"isOutdated":false,"comments":{"totalCount":3,"nodes":[{"body":"%s","author":{"login":"coderabbitai","__typename":"Bot"}},{"body":"%s","author":{"login":"jonahgabriel","__typename":"User"}},{"body":"%s","author":{"login":"coderabbitai","__typename":"Bot"}}]}}],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}' \
    "$CR_1604_FINDING" "$CR_1604_HUMAN" "$1"
}

# Case K (POSITIVE, the ticket's live shape): verbatim #1604 concession
# -> BLOCKING=0 and a cr_concession_ack line naming the new class.
CASE_K="$(cr_1604_thread_with_reply "$CR_1604_CONCESSION")"
COUNT=$(echo "$CASE_K" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 0 ] && echo "PASS: Case K blocking=0 for the verbatim omnibase_core#1604 agreement-plus-deferral concession" || { echo "FAIL Case K: expected 0 got $COUNT"; exit 1; }
ACK=$(echo "$CASE_K" | jq -rs "$CONCESSION_JQ")
echo "$ACK" | grep -q "class=agreement_deferral" && echo "PASS: Case K concession ack names class=agreement_deferral" || { echo "FAIL Case K: no class=agreement_deferral ack; got: $ACK"; exit 1; }

# Case L (NEGATIVE CONTROL, permanent): the same finding with no reply at all
# -> still BLOCKING=1. An unanswered CodeRabbit finding is never conceded.
CASE_L=$(printf '{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[{"isResolved":false,"isOutdated":false,"comments":{"totalCount":1,"nodes":[{"body":"%s","author":{"login":"coderabbitai","__typename":"Bot"}}]}}],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}' "$CR_1604_FINDING")
COUNT=$(echo "$CASE_L" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case L blocking=1 for an unanswered CodeRabbit finding" || { echo "FAIL Case L: expected 1 got $COUNT"; exit 1; }

# Case M (NEGATIVE CONTROL, permanent): CodeRabbit replies re-stating and
# escalating, reusing the whole deferral vocabulary while REJECTING it
# -> still BLOCKING=1. This is the case a bare keyword search gets wrong.
CASE_M="$(cr_1604_thread_with_reply 'I disagree that deferring the validation design to OMN-16037 is reasonable. The separate uppercase-valued enum should be added in this PR before merge; leaving the field as `str` keeps the defect live in a release.')"
COUNT=$(echo "$CASE_M" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case M blocking=1 when CodeRabbit escalates while using deferral vocabulary" || { echo "FAIL Case M: expected 1 got $COUNT"; exit 1; }

# Case N (NEGATIVE CONTROL, permanent): explicit negated agreement over the
# exact deferral sentence -> still BLOCKING=1.
CASE_N="$(cr_1604_thread_with_reply 'I do not agree that deferring the validation design to OMN-16037 is reasonable; the uppercase enum belongs in this PR.')"
COUNT=$(echo "$CASE_N" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case N blocking=1 for a negated agreement (do not agree ... is reasonable)" || { echo "FAIL Case N: expected 1 got $COUNT"; exit 1; }

# Case O (NEGATIVE CONTROL, permanent): partial agreement with NO deferral —
# CodeRabbit grants a sub-point and keeps the finding -> still BLOCKING=1.
CASE_O="$(cr_1604_thread_with_reply 'Agreed that the `EnumLogLevel` members are lowercase. The finding still stands: a separate uppercase-valued enum is required in this PR.')"
COUNT=$(echo "$CASE_O" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case O blocking=1 for agreement on a sub-point with the finding kept" || { echo "FAIL Case O: expected 1 got $COUNT"; exit 1; }

# Case P (NEGATIVE CONTROL, permanent): the concession vocabulary appears ONLY
# inside the auto-generated `<details>Learnings</details>` block while the
# visible reply keeps the finding -> still BLOCKING=1. Proves the match runs on
# the salient body, not on CodeRabbit boilerplate.
CASE_P="$(cr_1604_thread_with_reply 'The finding stands. A separate uppercase-valued enum is required in this PR.\n\n<details>\n<summary>Learnings used</summary>\n\nLearnt from: jonahgabriel — agreed that `EnumLogLevel` cannot represent this YAML contract, and deferring the validation design to OMN-16037 is reasonable.\n\n</details>')"
COUNT=$(echo "$CASE_P" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case P blocking=1 when concession vocabulary only appears inside a details block" || { echo "FAIL Case P: expected 1 got $COUNT"; exit 1; }

# Case Q (NEGATIVE CONTROL, permanent): the human-rebuttal precondition still
# holds for the new class — a bot-only exchange ending in a textbook
# agreement-plus-deferral reply is NOT a concession to a human -> BLOCKING=1.
CASE_Q=$(printf '{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[{"isResolved":false,"isOutdated":false,"comments":{"totalCount":3,"nodes":[{"body":"%s","author":{"login":"coderabbitai","__typename":"Bot"}},{"body":"auto-fix applied","author":{"login":"renovate","__typename":"Bot"}},{"body":"%s","author":{"login":"coderabbitai","__typename":"Bot"}}]}}],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}' "$CR_1604_FINDING" "$CR_1604_CONCESSION")
COUNT=$(echo "$CASE_Q" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case Q blocking=1 — agreement-plus-deferral without a human rebuttal is not a concession" || { echo "FAIL Case Q: expected 1 got $COUNT"; exit 1; }

# Case R (NEGATIVE CONTROL, permanent): the truncation guard still wins over the
# new class — a partially-fetched thread stays blocking even with a textbook
# concession in the fetched slice.
CASE_R=$(printf '{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[{"isResolved":false,"isOutdated":false,"comments":{"totalCount":60,"nodes":[{"body":"%s","author":{"login":"coderabbitai","__typename":"Bot"}},{"body":"%s","author":{"login":"jonahgabriel","__typename":"User"}},{"body":"%s","author":{"login":"coderabbitai","__typename":"Bot"}}]}}],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}' "$CR_1604_FINDING" "$CR_1604_HUMAN" "$CR_1604_CONCESSION")
COUNT=$(echo "$CASE_R" | jq -s "$BLOCKING_JQ")
[ "$COUNT" -eq 1 ] && echo "PASS: Case R blocking=1 — truncated thread stays conservative despite a concession in the fetched slice" || { echo "FAIL Case R: expected 1 got $COUNT"; exit 1; }

# Guard: the script must never gain a resolve path. `pr_review_bot` is the sole
# resolver of CodeRabbit threads; this gate only counts.
if grep -qE 'resolveReviewThread|unresolveReviewThread|--resolve\b' "$SCRIPT"; then
  echo "FAIL: check-unresolved-threads.sh must not resolve threads (pr_review_bot is the sole resolver)"; exit 1
fi
echo "PASS: no thread-resolution mutation present in the gate script"

echo "ALL TESTS PASSED"
