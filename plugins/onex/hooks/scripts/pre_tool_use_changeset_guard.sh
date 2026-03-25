#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PreToolUse Changeset Guard Hook
# Warns when broad staging commands (git add -A, git add .) are detected.
# Warning-only Phase 1 — does not block, only injects advisory context.
#
# Event:   PreToolUse
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
# Read stdin (Claude Code PreToolUse JSON)
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
# Gate: detect broad staging patterns
# -----------------------------------------------------------------------
BROAD_STAGING=false

# Match git add -A, git add --all, git add .
if echo "$TOOL_CMD" | grep -qE 'git\s+add\s+(-A|--all|\.)'; then
    BROAD_STAGING=true
fi

if [[ "$BROAD_STAGING" != "true" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# -----------------------------------------------------------------------
# Emit warning via hookSpecificOutput
# -----------------------------------------------------------------------
WARNING="[Changeset Guard] WARNING: Broad staging detected (git add -A / git add .). Prefer adding specific files by name to avoid committing secrets, unrelated changes, or large binaries. If intentional, proceed — this is a warning, not a block."

# Log the event for data-driven escalation decisions
LOG_DIR="${HOME}/.claude/changeset-guard-events"
mkdir -p "$LOG_DIR" 2>/dev/null || true
printf '{"timestamp":"%s","event":"broad_staging","command":"%s"}\n' \
    "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    "$(printf '%s' "$TOOL_CMD" | head -c 200 | tr '"' "'")" \
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
