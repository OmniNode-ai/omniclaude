#!/bin/bash
# SPDX-License-Identifier: MIT
# PreToolUse Sweep Pre-Flight Hook [OMN-7057]
# Validates infrastructure readiness before sweep/close-out operations.
# Checks: (1) gh auth status, (2) GitHub API rate limit, (3) Linear MCP process.
# Uses a 5-minute cache to avoid running full checks on every Bash invocation.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Stable CWD (same pattern as bash_guard)
cd "$HOME" 2>/dev/null || cd /tmp || true

# Resolve paths
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
LOG_FILE="${LOG_FILE:-$HOME/.claude/hooks.log}"

mkdir -p "$(dirname "$LOG_FILE")"

# Cache configuration
CACHE_DIR="${HOME}/.claude/hooks/.cache"
CACHE_FILE="${CACHE_DIR}/sweep-preflight.json"
CACHE_TTL_SECONDS=300  # 5 minutes
RATE_LIMIT_THRESHOLD=500

# Read stdin (required by hook protocol)
TOOL_INFO=$(cat)

# Only process Bash tool calls
TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null) || true
if [[ "$TOOL_NAME" != "Bash" ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Extract the command being run
COMMAND=$(echo "$TOOL_INFO" | jq -er '.tool_input.command // empty' 2>/dev/null) || true

# Only run pre-flight for commands that interact with GitHub or indicate sweep activity.
# This avoids running on every `ls`, `cat`, etc.
SWEEP_PATTERN='(gh |git push|merge.sweep|close.out|autopilot|pr.polish|pr.review)'
if ! echo "$COMMAND" | grep -qEi "$SWEEP_PATTERN"; then
    echo "$TOOL_INFO"
    exit 0
fi

# --- Cache check ---
# If cache exists and is fresh, use cached result
mkdir -p "$CACHE_DIR"
if [[ -f "$CACHE_FILE" ]]; then
    # Cross-platform mtime: Linux uses stat -c %Y, macOS uses stat -f %m
    FILE_MTIME=0
    if [[ "$(uname -s)" == "Darwin" ]]; then
        FILE_MTIME=$(stat -f %m "$CACHE_FILE" 2>/dev/null || echo 0)
    else
        FILE_MTIME=$(stat -c %Y "$CACHE_FILE" 2>/dev/null || echo 0)
    fi
    CACHE_AGE=$(( $(date +%s) - FILE_MTIME ))
    if [[ $CACHE_AGE -lt $CACHE_TTL_SECONDS ]]; then
        CACHED_STATUS=$(jq -er '.status // empty' "$CACHE_FILE" 2>/dev/null) || true
        if [[ "$CACHED_STATUS" == "pass" ]]; then
            echo "$TOOL_INFO"
            exit 0
        elif [[ "$CACHED_STATUS" == "block" ]]; then
            CACHED_REASON=$(jq -er '.reason // "Cached pre-flight failure"' "$CACHE_FILE" 2>/dev/null)
            echo "{\"decision\":\"block\",\"reason\":\"$CACHED_REASON\"}" >&2
            exit 2
        fi
    fi
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Sweep preflight: running infrastructure checks" >> "$LOG_FILE"

# --- Check 1: GitHub auth ---
GH_AUTH_OK=false
GH_AUTH_MSG=""
if command -v gh &>/dev/null; then
    if gh auth status &>/dev/null; then
        GH_AUTH_OK=true
    else
        GH_AUTH_MSG="GitHub auth expired — run 'gh auth login' to re-authenticate"
    fi
else
    GH_AUTH_MSG="gh CLI not found — install GitHub CLI for sweep operations"
fi

if [[ "$GH_AUTH_OK" == "false" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Sweep preflight BLOCKED: $GH_AUTH_MSG" >> "$LOG_FILE"
    printf '{"status":"block","reason":"%s","checked_at":"%s"}\n' "$GH_AUTH_MSG" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$CACHE_FILE"
    echo "{\"decision\":\"block\",\"reason\":\"Pre-flight check failed: $GH_AUTH_MSG\"}" >&2
    exit 2
fi

# --- Check 2: GitHub API rate limit ---
RATE_OK=false
RATE_MSG=""
RATE_REMAINING=0
if RATE_JSON=$(gh api /rate_limit 2>/dev/null); then
    RATE_REMAINING=$(echo "$RATE_JSON" | jq -r '.resources.core.remaining // 0' 2>/dev/null) || RATE_REMAINING=0
    RATE_LIMIT=$(echo "$RATE_JSON" | jq -r '.resources.core.limit // 0' 2>/dev/null) || RATE_LIMIT=0
    RATE_RESET=$(echo "$RATE_JSON" | jq -r '.resources.core.reset // 0' 2>/dev/null) || RATE_RESET=0

    if [[ $RATE_REMAINING -ge $RATE_LIMIT_THRESHOLD ]]; then
        RATE_OK=true
    else
        RESET_TIME=$(date -r "$RATE_RESET" +"%H:%M:%S" 2>/dev/null || echo "unknown")
        RATE_MSG="GitHub API rate limit low: ${RATE_REMAINING}/${RATE_LIMIT} remaining (resets at ${RESET_TIME}). Threshold: ${RATE_LIMIT_THRESHOLD}"
    fi
else
    # If we can't check rate limit but auth works, warn but don't block
    RATE_OK=true
    RATE_MSG="Could not check rate limit (API call failed), proceeding with caution"
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Sweep preflight WARNING: $RATE_MSG" >> "$LOG_FILE"
fi

if [[ "$RATE_OK" == "false" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Sweep preflight BLOCKED: $RATE_MSG" >> "$LOG_FILE"
    printf '{"status":"block","reason":"%s","rate_remaining":%d,"checked_at":"%s"}\n' \
        "$RATE_MSG" "$RATE_REMAINING" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$CACHE_FILE"
    echo "{\"decision\":\"block\",\"reason\":\"Pre-flight check failed: $RATE_MSG\"}" >&2
    exit 2
fi

# --- Check 3: Linear MCP process (advisory only — never blocks) ---
LINEAR_MCP_RUNNING=false
if pgrep -f "linear.*mcp\|mcp.*linear\|linear-server" &>/dev/null; then
    LINEAR_MCP_RUNNING=true
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Sweep preflight WARNING: Linear MCP server process not detected (advisory — not blocking)" >> "$LOG_FILE"
fi

# --- All checks passed — cache success ---
printf '{"status":"pass","gh_auth":true,"rate_remaining":%d,"linear_mcp":%s,"checked_at":"%s"}\n' \
    "$RATE_REMAINING" "$LINEAR_MCP_RUNNING" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$CACHE_FILE"

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Sweep preflight PASSED (rate: ${RATE_REMAINING} remaining, linear_mcp: ${LINEAR_MCP_RUNNING})" >> "$LOG_FILE"

# Pass through — allow the command
echo "$TOOL_INFO"
exit 0
