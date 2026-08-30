#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Changeset Guard Hook
# After a git commit, records the changeset size to a local JSONL series when
# more than 15 files changed.
#
# OMN-17207: revived from the OMN-13244 unregister as DURABLE LOCAL CAPTURE ONLY.
# The original also injected an advisory warning into the model's context on
# every oversized commit; that half is deliberately NOT revived --
# per-turn context injection is precisely the token cost OMN-13244 removed. The
# JSONL side-write is kept because it was the ONLY durable machine-readable
# output the entire pre-OMN-13244 hook surface ever produced (2,703 lines over
# 56 days), and this preserves continuity of that series.
#
# Local disk only. Nothing here reaches the bus: that stays gated behind
# OMN-17209.
#
# Event:   PostToolUse
# Matcher: Bash
# Ticket:  OMN-6524

set -euo pipefail

# -----------------------------------------------------------------------
# Kill switches
# -----------------------------------------------------------------------
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat  # drain stdin
    exit 0
fi
source "$(dirname "${BASH_SOURCE[0]}")/hook-gate.sh" 2>/dev/null || true
onex_hook_gate CHANGESET_GUARD_POST || exit 0

# -----------------------------------------------------------------------
# Read stdin (Claude Code PostToolUse JSON)
# -----------------------------------------------------------------------
TOOL_INFO=$(cat)

# Guard: jq is required
if ! command -v jq >/dev/null 2>&1; then
    exit 0
fi

# Extract the Bash command from tool input
TOOL_CMD=$(printf '%s' "$TOOL_INFO" | jq -r '.tool_input.command // ""' 2>/dev/null) || TOOL_CMD=""

# -----------------------------------------------------------------------
# Gate: only fire when the command contains "git commit"
# -----------------------------------------------------------------------
if [[ "$TOOL_CMD" != *"git commit"* ]]; then
    exit 0
fi

# -----------------------------------------------------------------------
# Check changeset size via git diff --stat
# -----------------------------------------------------------------------
# Try to get the file count from the last commit
FILE_COUNT=0
if command -v git >/dev/null 2>&1; then
    # Try to count files changed in the most recent commit
    FILE_COUNT=$(git diff --stat HEAD~1 HEAD 2>/dev/null | tail -1 | grep -oE '^[[:space:]]*[0-9]+' | tr -d '[:space:]') || FILE_COUNT=0
fi

# Threshold: warn if more than 15 files changed
THRESHOLD=15
if [[ "$FILE_COUNT" -le "$THRESHOLD" ]] 2>/dev/null; then
    exit 0
fi

# -----------------------------------------------------------------------
# Record the event for data-driven escalation decisions (local JSONL only).
# -----------------------------------------------------------------------
LOG_DIR="${HOME}/.claude/changeset-guard-events"
mkdir -p "$LOG_DIR" 2>/dev/null || true
printf '{"timestamp":"%s","event":"large_changeset","file_count":%d,"threshold":%d}\n' \
    "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    "$FILE_COUNT" \
    "$THRESHOLD" \
    >> "$LOG_DIR/events.jsonl" 2>/dev/null || true

# Emit NOTHING on stdout. The advisory injection this hook used to write is the
# context-injection class OMN-13244 disabled; and echoing $TOOL_INFO back would
# re-emit the raw tool_response that the OMN-16277 secret-redaction guard masks
# on this same Bash matcher.
exit 0
