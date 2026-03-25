#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Auto Hostile Review Hook
# After gh pr create, automatically dispatches /onex:hostile_reviewer
# against the newly created PR. Fire-and-forget, non-blocking.
#
# Event:   PostToolUse
# Matcher: Bash
# Ticket:  OMN-6536

set -euo pipefail

# -----------------------------------------------------------------------
# Kill switches
# -----------------------------------------------------------------------
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat  # drain stdin
    exit 0
fi
if [[ "${OMNICLAUDE_HOOK_AUTO_HOSTILE_REVIEW:-1}" == "0" ]]; then
    cat  # drain stdin
    exit 0
fi

# -----------------------------------------------------------------------
# Read stdin (Claude Code PostToolUse JSON)
# -----------------------------------------------------------------------
TOOL_INFO=$(cat)

# Guard: jq is required
if ! command -v jq >/dev/null 2>&1; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Extract the Bash command from tool input
TOOL_CMD=$(printf '%s' "$TOOL_INFO" | jq -r '.tool_input.command // ""' 2>/dev/null) || TOOL_CMD=""

# -----------------------------------------------------------------------
# Gate: only fire when the command contains "gh pr create"
# -----------------------------------------------------------------------
if [[ "$TOOL_CMD" != *"gh pr create"* ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# -----------------------------------------------------------------------
# Extract PR URL from tool response (best-effort)
# -----------------------------------------------------------------------
TOOL_RESPONSE=$(printf '%s' "$TOOL_INFO" | jq -r '.tool_response.stdout // .tool_response // ""' 2>/dev/null) || TOOL_RESPONSE=""

# Try to extract PR URL from the response
PR_URL=""
if echo "$TOOL_RESPONSE" | grep -qoE 'https://github\.com/[^[:space:]]+/pull/[0-9]+'; then
    PR_URL=$(echo "$TOOL_RESPONSE" | grep -oE 'https://github\.com/[^[:space:]]+/pull/[0-9]+' | head -1)
fi

# -----------------------------------------------------------------------
# Inject advisory to dispatch hostile reviewer
# -----------------------------------------------------------------------
if [[ -n "$PR_URL" ]]; then
    ADVISORY="[Auto Review] A PR was just created at ${PR_URL}. Dispatch /onex:hostile_reviewer against this PR to catch scope creep, bugs, and convention violations before merge."
else
    ADVISORY="[Auto Review] A PR was just created. Dispatch /onex:hostile_reviewer against the new PR to catch scope creep, bugs, and convention violations before merge."
fi

# Log the event
LOG_DIR="${HOME}/.claude/auto-hostile-review-events"
mkdir -p "$LOG_DIR" 2>/dev/null || true
printf '{"timestamp":"%s","event":"pr_created","pr_url":"%s","command":"%s"}\n' \
    "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    "${PR_URL:-unknown}" \
    "$(printf '%s' "$TOOL_CMD" | head -c 200 | tr '"' "'")" \
    >> "$LOG_DIR/events.jsonl" 2>/dev/null || true

# Inject the advisory into the output
MODIFIED=$(printf '%s' "$TOOL_INFO" | jq \
    --arg advisory "$ADVISORY" \
    '.hookSpecificOutput = (.hookSpecificOutput // {}) |
     .hookSpecificOutput.additionalContext = (
       ((.hookSpecificOutput.additionalContext // "") + "\n\n" + $advisory)
       | ltrimstr("\n\n")
     )' 2>/dev/null)

if [[ -n "$MODIFIED" && "$MODIFIED" != "null" ]]; then
    printf '%s\n' "$MODIFIED"
else
    printf '%s\n' "$TOOL_INFO"
fi

exit 0
