#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Test-Run Reminder Hook
# When an Edit or Write modifies a handler, projection, or test file,
# injects an advisory reminder to run relevant tests before committing.
# Advisory only — never blocks.
#
# Event:   PostToolUse
# Matcher: ^(Edit|Write)$
# Ticket:  OMN-7743

set -euo pipefail

# -----------------------------------------------------------------------
# Kill switches
# -----------------------------------------------------------------------
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat  # drain stdin
    exit 0
fi
if [[ "${OMNICLAUDE_HOOK_TEST_REMINDER:-1}" == "0" ]]; then
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

# Extract the file path from the tool input
FILE_PATH=$(printf '%s' "$TOOL_INFO" | jq -r '.tool_input.file_path // ""' 2>/dev/null) || FILE_PATH=""

# -----------------------------------------------------------------------
# Gate: only match handler/projection/test patterns
# -----------------------------------------------------------------------
if [[ -z "$FILE_PATH" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

MATCHED=false
case "$FILE_PATH" in
    */tests/*.py|*/tests/**/*.py)    MATCHED=true ;;
    *handler*.py)                     MATCHED=true ;;
    *projection*.py)                  MATCHED=true ;;
    *projector*.py)                   MATCHED=true ;;
    *effect*.py)                      MATCHED=true ;;
    *reducer*.py)                     MATCHED=true ;;
esac

if [[ "$MATCHED" != "true" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# -----------------------------------------------------------------------
# Deduplication: one reminder per unique file path per session
# -----------------------------------------------------------------------
DEDUP_DIR="/tmp/omniclaude-test-reminder"
mkdir -p "$DEDUP_DIR" 2>/dev/null || true

DEDUP_KEY=$(printf '%s' "$FILE_PATH" | shasum -a 256 2>/dev/null | cut -d' ' -f1)
if [[ -z "$DEDUP_KEY" ]]; then
    DEDUP_KEY=$(printf '%s' "$FILE_PATH" | sha256sum 2>/dev/null | cut -d' ' -f1)
fi
if [[ -z "$DEDUP_KEY" ]]; then
    DEDUP_KEY=$(printf '%s' "$FILE_PATH" | md5 2>/dev/null || printf '%s' "$FILE_PATH" | md5sum 2>/dev/null | cut -d' ' -f1)
fi
DEDUP_FILE="${DEDUP_DIR}/${DEDUP_KEY}"

if [[ -f "$DEDUP_FILE" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Mark as seen
touch "$DEDUP_FILE" 2>/dev/null || true

# -----------------------------------------------------------------------
# Extract filename for the reminder message
# -----------------------------------------------------------------------
FILENAME=$(basename "$FILE_PATH")
MODULE_NAME="${FILENAME%.py}"

# -----------------------------------------------------------------------
# Emit reminder via hookSpecificOutput
# -----------------------------------------------------------------------
REMINDER="[Test Reminder] You just edited ${FILENAME} which matches a handler/projection/test pattern. Run relevant tests (pytest tests/ -v -k ${MODULE_NAME}) before committing."

MODIFIED=$(printf '%s' "$TOOL_INFO" | jq \
    --arg reminder "$REMINDER" \
    '.hookSpecificOutput = (.hookSpecificOutput // {}) |
     .hookSpecificOutput.hookEventName = "PostToolUse" |
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
