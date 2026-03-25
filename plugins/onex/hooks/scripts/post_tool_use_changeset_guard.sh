#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Changeset Guard Hook
# After a git commit, checks the changeset size and warns if >15 files changed.
# Warning-only Phase 1 — does not block, only injects advisory context.
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
if [[ "${OMNICLAUDE_HOOK_CHANGESET_GUARD:-1}" == "0" ]]; then
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
# Gate: only fire when the command contains "git commit"
# -----------------------------------------------------------------------
if [[ "$TOOL_CMD" != *"git commit"* ]]; then
    printf '%s\n' "$TOOL_INFO"
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
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# -----------------------------------------------------------------------
# Emit warning via hookSpecificOutput
# -----------------------------------------------------------------------
WARNING="[Changeset Guard] WARNING: Large changeset ($FILE_COUNT files changed in last commit). Consider splitting into focused commits. Large changesets are harder to review, more likely to contain scope creep, and riskier to revert."

# Log the event for data-driven escalation decisions
LOG_DIR="${HOME}/.claude/changeset-guard-events"
mkdir -p "$LOG_DIR" 2>/dev/null || true
printf '{"timestamp":"%s","event":"large_changeset","file_count":%d,"threshold":%d}\n' \
    "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    "$FILE_COUNT" \
    "$THRESHOLD" \
    >> "$LOG_DIR/events.jsonl" 2>/dev/null || true

# Inject the warning into the output
MODIFIED=$(printf '%s' "$TOOL_INFO" | jq \
    --arg warning "$WARNING" \
    '.hookSpecificOutput = (.hookSpecificOutput // {}) |
     .hookSpecificOutput.additionalContext = (
       ((.hookSpecificOutput.additionalContext // "") + "\n\n" + $warning)
       | ltrimstr("\n\n")
     )' 2>/dev/null)

if [[ -n "$MODIFIED" && "$MODIFIED" != "null" ]]; then
    printf '%s\n' "$MODIFIED"
else
    printf '%s\n' "$TOOL_INFO"
fi

exit 0
