#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Auto Hostile Review Hook
# After gh pr create, automatically dispatches /onex:hostile_reviewer
# against the newly created PR. Fire-and-forget, non-blocking.
#
# Sub-agent awareness [OMN-9268]: Task()-spawned sub-agents cannot call
# Agent()/Task() to spawn the fix-apply worker that --gate mode relies on.
# When the current session has a sub-agent marker at
# $ONEX_STATE_DIR/hooks/subagent-sessions/<session_id>.marker (written by
# subagent-start.sh per OMN-9140), the advisory switches to point at the
# review-only path (--gate-only) which runs fully inline.
#
# Event:   PostToolUse
# Matcher: Bash
# Ticket:  OMN-6536, OMN-9268

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
# Sub-agent detection [OMN-9268]
# -----------------------------------------------------------------------
# subagent-start.sh writes a per-session marker for every Task()-spawned
# worker. When that marker is present for the current session, emit a
# sub-agent-friendly advisory that points at --gate-only (review only,
# no Agent()/Task() spawn). Lead sessions fall through to the default
# --gate advisory which invokes the full review + fix-apply pipeline.
SESSION_ID=$(printf '%s' "$TOOL_INFO" | jq -r '.session_id // .sessionId // ""' 2>/dev/null) || SESSION_ID=""
IS_SUBAGENT=0
if [[ -n "$SESSION_ID" ]]; then
    _SA_MARKER_DIR="${ONEX_STATE_DIR:-${HOME}/.onex_state}/hooks/subagent-sessions"
    if [[ -f "${_SA_MARKER_DIR}/${SESSION_ID}.marker" ]]; then
        IS_SUBAGENT=1
    fi
    unset _SA_MARKER_DIR
fi

# -----------------------------------------------------------------------
# Inject advisory to dispatch hostile reviewer
# -----------------------------------------------------------------------
if [[ "$IS_SUBAGENT" -eq 1 ]]; then
    if [[ -n "$PR_URL" ]]; then
        ADVISORY="[Auto Review — REQUIRED] A PR was just created at ${PR_URL}. hostile_reviewer is a hard pre-merge gate [OMN-8702]. Sub-agents cannot spawn fix-apply workers; invoke the review-only path inline: /onex:hostile_reviewer --pr <N> --repo <owner/repo> --gate-only (or run uv run python plugins/onex/skills/hostile_reviewer/_lib/aggregate_reviews.py --pr <N> --repo <owner/repo>). Do not attempt sub-agent dispatch from this context."
    else
        ADVISORY="[Auto Review — REQUIRED] A PR was just created. hostile_reviewer is a hard pre-merge gate [OMN-8702]. Sub-agents cannot spawn fix-apply workers; invoke the review-only path inline: /onex:hostile_reviewer --pr <N> --repo <owner/repo> --gate-only (or run uv run python plugins/onex/skills/hostile_reviewer/_lib/aggregate_reviews.py --pr <N> --repo <owner/repo>). Do not attempt sub-agent dispatch from this context."
    fi
elif [[ -n "$PR_URL" ]]; then
    ADVISORY="[Auto Review — REQUIRED] A PR was just created at ${PR_URL}. hostile_reviewer is a hard pre-merge gate [OMN-8702]: gh pr merge will be blocked until hostile_reviewer passes. Dispatch now: /onex:hostile_reviewer --pr <N> --repo <owner/repo> --gate"
else
    ADVISORY="[Auto Review — REQUIRED] A PR was just created. hostile_reviewer is a hard pre-merge gate [OMN-8702]: gh pr merge will be blocked until hostile_reviewer passes. Dispatch: /onex:hostile_reviewer --pr <N> --repo <owner/repo> --gate"
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
     .hookSpecificOutput.hookEventName = "PostToolUse" |
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
