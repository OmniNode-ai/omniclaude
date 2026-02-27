#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Ruff Auto-Fix Hook
# Runs ruff format + ruff check --fix on the specific .py file just edited.
# Standalone: does NOT source _bin/_common.sh or hooks/scripts/common.sh.
#
# Event:   PostToolUse
# Matcher: ^(Edit|Write)$
# Ticket:  OMN-2825

set -euo pipefail

# -----------------------------------------------------------------------
# Kill switches
# -----------------------------------------------------------------------
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat  # drain stdin
    exit 0
fi
if [[ "${OMNICLAUDE_HOOK_RUFF_FIX:-1}" == "0" ]]; then
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

# Pass through original output immediately -- all logic below is non-blocking
printf '%s\n' "$TOOL_INFO"

# -----------------------------------------------------------------------
# Gate: only .py files
# -----------------------------------------------------------------------
if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi
if [[ "$FILE_PATH" != *.py ]]; then
    exit 0
fi
if [[ ! -f "$FILE_PATH" ]]; then
    exit 0
fi

# -----------------------------------------------------------------------
# Gate: file size < 100 KB
# -----------------------------------------------------------------------
FILE_SIZE=0
if [[ "$(uname)" == "Darwin" ]]; then
    FILE_SIZE=$(stat -f%z "$FILE_PATH" 2>/dev/null || echo 0)
else
    FILE_SIZE=$(stat -c%s "$FILE_PATH" 2>/dev/null || echo 0)
fi
if [[ "$FILE_SIZE" -ge 102400 ]]; then
    exit 0
fi

# -----------------------------------------------------------------------
# Debounce: skip if same file was ruff-fixed within last 2 seconds
# -----------------------------------------------------------------------
DEBOUNCE_DIR="/tmp/omniclaude-ruff-debounce"
mkdir -p "$DEBOUNCE_DIR" 2>/dev/null || true

# Use a hash of the file path as the debounce key
DEBOUNCE_KEY=$(printf '%s' "$FILE_PATH" | shasum -a 256 2>/dev/null | cut -d' ' -f1)
if [[ -z "$DEBOUNCE_KEY" ]]; then
    DEBOUNCE_KEY=$(printf '%s' "$FILE_PATH" | sha256sum 2>/dev/null | cut -d' ' -f1)
fi
if [[ -z "$DEBOUNCE_KEY" ]]; then
    DEBOUNCE_KEY=$(printf '%s' "$FILE_PATH" | md5 2>/dev/null || printf '%s' "$FILE_PATH" | md5sum 2>/dev/null | cut -d' ' -f1)
fi
DEBOUNCE_FILE="${DEBOUNCE_DIR}/${DEBOUNCE_KEY}"

if [[ -f "$DEBOUNCE_FILE" ]]; then
    LAST_RUN=$(cat "$DEBOUNCE_FILE" 2>/dev/null || echo 0)
    NOW=$(date +%s)
    ELAPSED=$((NOW - LAST_RUN))
    if [[ "$ELAPSED" -lt 2 ]]; then
        exit 0
    fi
fi

# -----------------------------------------------------------------------
# Gate: check uv/ruff availability (cached per session via temp file)
# -----------------------------------------------------------------------
SESSION_CACHE_DIR="/tmp/omniclaude-ruff-session"
mkdir -p "$SESSION_CACHE_DIR" 2>/dev/null || true

# Cache key: session-level availability check
AVAIL_CACHE="${SESSION_CACHE_DIR}/tools-available"
WARN_CACHE="${SESSION_CACHE_DIR}/warned"

if [[ -f "$AVAIL_CACHE" ]]; then
    TOOLS_AVAILABLE=$(cat "$AVAIL_CACHE")
else
    TOOLS_AVAILABLE="unknown"
fi

if [[ "$TOOLS_AVAILABLE" == "unknown" ]]; then
    if command -v uv >/dev/null 2>&1 && uv run ruff --version >/dev/null 2>&1; then
        TOOLS_AVAILABLE="yes"
    else
        TOOLS_AVAILABLE="no"
    fi
    printf '%s' "$TOOLS_AVAILABLE" > "$AVAIL_CACHE" 2>/dev/null || true
fi

if [[ "$TOOLS_AVAILABLE" != "yes" ]]; then
    # Warn once per session
    if [[ ! -f "$WARN_CACHE" ]]; then
        echo "[omniclaude-ruff-hook] uv/ruff not available -- skipping auto-fix" >&2
        touch "$WARN_CACHE" 2>/dev/null || true
    fi
    exit 0
fi

# -----------------------------------------------------------------------
# Run ruff (background, non-blocking)
# -----------------------------------------------------------------------
(
    LOG_FILE="${HOME}/.claude/hooks.log"

    # Record debounce timestamp
    date +%s > "$DEBOUNCE_FILE" 2>/dev/null || true

    # ruff format (quiet, single file)
    if ! uv run ruff format "$FILE_PATH" 2>/dev/null; then
        if [[ ! -f "${SESSION_CACHE_DIR}/format-warned" ]]; then
            echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [ruff-hook] ruff format failed on $FILE_PATH" >> "$LOG_FILE" 2>/dev/null || true
            touch "${SESSION_CACHE_DIR}/format-warned" 2>/dev/null || true
        fi
    fi

    # ruff check --fix (quiet, single file)
    if ! uv run ruff check --fix --quiet "$FILE_PATH" 2>/dev/null; then
        if [[ ! -f "${SESSION_CACHE_DIR}/check-warned" ]]; then
            echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [ruff-hook] ruff check --fix failed on $FILE_PATH" >> "$LOG_FILE" 2>/dev/null || true
            touch "${SESSION_CACHE_DIR}/check-warned" 2>/dev/null || true
        fi
    fi
) &

exit 0
