#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# test_injection_probe.sh — OMN-10606 injection mechanism probe
#
# Exercises the recommended PostToolUse result-injection path:
#   - Reads HOOK_EVENT from stdin
#   - Checks for a pending delegation result file
#   - Injects it as hookSpecificOutput.additionalContext (exit 0)
#
# To test manually:
#   echo '{"tool_name":"Bash","tool_input":{"command":"ls"},"tool_response":{"stdout":""}}' \
#     | ONEX_STATE_DIR=/tmp/onex_probe_test \
#       bash test_injection_probe.sh
#
# Expected output when result file present:
#   {"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"<result>"}}
#
# Expected output when no result file:
#   (empty — exits 0 silently)
#
# Exit codes:
#   0 — always (never blocks)

HOOK_EVENT=$(cat) || HOOK_EVENT=""

TOOL_NAME=$(echo "$HOOK_EVENT" | jq -r '.tool_name // ""' 2>/dev/null) || TOOL_NAME=""

# Only act on delegation-related tools
if [[ "$TOOL_NAME" != "Bash" && "$TOOL_NAME" != "Agent" && "$TOOL_NAME" != "Task" ]]; then
    exit 0
fi

if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    exit 0
fi

RESULT_FILE="${ONEX_STATE_DIR}/delegation/pending_result.json"

if [[ ! -f "$RESULT_FILE" ]]; then
    exit 0
fi

RESULT=$(cat "$RESULT_FILE" 2>/dev/null) || exit 0
rm -f "$RESULT_FILE" 2>/dev/null || true

# Inject the delegation result as additionalContext using the proven pattern
# (same as user_prompt_bootstrap_injector.sh and user_prompt_structured_handoff_nudge.sh)
jq -n --arg ctx "$RESULT" '{
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": $ctx
    }
}' 2>/dev/null || true

exit 0
