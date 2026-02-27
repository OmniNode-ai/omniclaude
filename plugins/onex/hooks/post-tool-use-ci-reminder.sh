#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse CI Version Reminder Hook
# When a Bash tool call contains "git commit", emits a reminder to check
# that CI config versions match the repo's pyproject.toml / package.json.
# Standalone: does NOT source _bin/_common.sh or hooks/scripts/common.sh.
#
# Event:   PostToolUse
# Matcher: Bash
# Ticket:  OMN-2825

set -euo pipefail

# -----------------------------------------------------------------------
# Kill switches
# -----------------------------------------------------------------------
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat  # drain stdin
    exit 0
fi
if [[ "${OMNICLAUDE_HOOK_CI_REMINDER:-1}" == "0" ]]; then
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
# Note: avoid using BASH_COMMAND -- it is a reserved bash variable.
TOOL_CMD=$(printf '%s' "$TOOL_INFO" | jq -r '.tool_input.command // ""' 2>/dev/null) || TOOL_CMD=""

# -----------------------------------------------------------------------
# Gate: only fire when the command contains "git commit"
# -----------------------------------------------------------------------
if [[ "$TOOL_CMD" != *"git commit"* ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# -----------------------------------------------------------------------
# Emit reminder via hookSpecificOutput
# -----------------------------------------------------------------------
# Build a modified response that includes a CI version reminder in
# hookSpecificOutput.additionalContext. Claude Code merges this into
# the conversation context.
REMINDER="[CI Reminder] A commit was just created. Before pushing, verify that version strings in CI config (.github/workflows/*.yml) match the project's pyproject.toml / package.json. Check Python version, Node version, and any pinned dependency versions."

# Inject the reminder into the output
MODIFIED=$(printf '%s' "$TOOL_INFO" | jq \
    --arg reminder "$REMINDER" \
    '.hookSpecificOutput = (.hookSpecificOutput // {}) |
     .hookSpecificOutput.additionalContext = (
       ((.hookSpecificOutput.additionalContext // "") + "\n\n" + $reminder)
       | ltrimstr("\n\n")
     )' 2>/dev/null)

if [[ -n "$MODIFIED" && "$MODIFIED" != "null" ]]; then
    printf '%s\n' "$MODIFIED"
else
    # Fallback: pass through unmodified if jq transformation failed
    printf '%s\n' "$TOOL_INFO"
fi

exit 0
