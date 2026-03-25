#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PreToolUse Scope Gate Hook
# Fires before Edit and Write tool calls. Reads the scope manifest
# (produced by /onex:scope_check) and blocks edits to files outside
# the declared scope. If no scope manifest exists, passes through
# (does not block ad-hoc work).
#
# Event:   PreToolUse
# Matcher: ^(Edit|Write)$
# Ticket:  OMN-6522

set -euo pipefail

# -----------------------------------------------------------------------
# Kill switches
# -----------------------------------------------------------------------
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat  # drain stdin
    exit 0
fi
if [[ "${OMNICLAUDE_HOOK_SCOPE_GATE:-1}" == "0" ]]; then
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

# -----------------------------------------------------------------------
# Check for scope manifest
# -----------------------------------------------------------------------
SCOPE_MANIFEST="${HOME}/.claude/scope-manifest.json"
if [[ ! -f "$SCOPE_MANIFEST" ]]; then
    # No scope manifest — ad-hoc session, pass through
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Validate manifest is valid JSON
if ! jq empty "$SCOPE_MANIFEST" 2>/dev/null; then
    # Invalid manifest — fail open
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# -----------------------------------------------------------------------
# Extract the target file path from the tool input
# -----------------------------------------------------------------------
TARGET_FILE=$(printf '%s' "$TOOL_INFO" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null) || TARGET_FILE=""

if [[ -z "$TARGET_FILE" ]]; then
    # No file path in tool input — pass through
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Normalize: strip leading ./ and make relative if possible
TARGET_FILE="${TARGET_FILE#./}"

# -----------------------------------------------------------------------
# Check if the target file is in scope
# -----------------------------------------------------------------------
IN_SCOPE=false

# Check against explicit files
if printf '%s' "$(jq -r '.files[]? // empty' "$SCOPE_MANIFEST" 2>/dev/null)" | grep -qF "$TARGET_FILE"; then
    IN_SCOPE=true
fi

# Check against directories (prefix match)
if [[ "$IN_SCOPE" == "false" ]]; then
    while IFS= read -r dir; do
        [[ -z "$dir" ]] && continue
        if [[ "$TARGET_FILE" == "$dir"* ]]; then
            IN_SCOPE=true
            break
        fi
    done < <(jq -r '.directories[]? // empty' "$SCOPE_MANIFEST" 2>/dev/null)
fi

# Check against adjacent files (warn, don't block)
IS_ADJACENT=false
if [[ "$IN_SCOPE" == "false" ]]; then
    if printf '%s' "$(jq -r '.adjacent_files[]? // empty' "$SCOPE_MANIFEST" 2>/dev/null)" | grep -qF "$TARGET_FILE"; then
        IS_ADJACENT=true
    fi
fi

# -----------------------------------------------------------------------
# Decision: pass, warn, or block
# -----------------------------------------------------------------------
if [[ "$IN_SCOPE" == "true" ]]; then
    # File is in scope — pass through
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

if [[ "$IS_ADJACENT" == "true" ]]; then
    # Adjacent file — warn but don't block
    WARNING="[Scope Gate] WARNING: '$TARGET_FILE' is an adjacent support file, not in the primary scope. Verify this edit is necessary for the current task."

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

    # Log the warning event
    LOG_DIR="${HOME}/.claude/scope-gate-events"
    mkdir -p "$LOG_DIR" 2>/dev/null || true
    printf '{"timestamp":"%s","event":"adjacent_warn","file":"%s"}\n' \
        "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
        "$(printf '%s' "$TARGET_FILE" | head -c 200)" \
        >> "$LOG_DIR/events.jsonl" 2>/dev/null || true

    exit 0
fi

# Out of scope — block the edit
BLOCK_MSG="SCOPE VIOLATION: '$TARGET_FILE' is not in the declared scope. Re-read your plan before proceeding. Use /onex:scope_check to update the scope manifest if this file should be included."

# Log the block event
LOG_DIR="${HOME}/.claude/scope-gate-events"
mkdir -p "$LOG_DIR" 2>/dev/null || true
printf '{"timestamp":"%s","event":"scope_block","file":"%s"}\n' \
    "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    "$(printf '%s' "$TARGET_FILE" | head -c 200)" \
    >> "$LOG_DIR/events.jsonl" 2>/dev/null || true

# Return a block response
printf '%s' "$TOOL_INFO" | jq \
    --arg msg "$BLOCK_MSG" \
    '{
      "decision": "block",
      "reason": $msg
    }' 2>/dev/null || printf '{"decision":"block","reason":"%s"}' "$BLOCK_MSG"

exit 2
