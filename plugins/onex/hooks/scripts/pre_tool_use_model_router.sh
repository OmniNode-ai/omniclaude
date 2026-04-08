#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Model Router Hook (OMN-7810)
# Advisory-mode hook that classifies tool calls by complexity and suggests
# delegation to cheaper models for simple implementation tasks.
#
# Enforcement tiers:
#   Advisory (exit 0 + stderr): task is simple, suggest delegation
#   Pass-through (exit 0): task is complex enough for Opus, or orchestration tool
#   Block (exit 2): enforce mode only — redirects to delegation pipeline
#
# Hook registration: hooks.json PreToolUse, matcher "^(Bash|Read|Edit|Write|Grep|Glob)$"

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Ensure stable CWD
cd "$HOME" 2>/dev/null || cd /tmp || true

# Portable Plugin Configuration
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { echo "FATAL: ONEX_STATE_DIR not set" >&2; exit 1; }
LOG_FILE="${LOG_FILE:-${ONEX_HOOK_LOG}}"

mkdir -p "$(dirname "$LOG_FILE")"

# Read stdin
TOOL_INFO=$(cat)

# Parse tool name — fail open on bad JSON
TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null) || {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ERROR: invalid hook JSON; failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
}

# Only intercept implementation tools
if [[ ! "$TOOL_NAME" =~ ^(Bash|Read|Edit|Write|Grep|Glob)$ ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Locate Python
source "${HOOKS_DIR}/scripts/common.sh"

# Run Python model router
set +e
ROUTER_OUTPUT=$(echo "$TOOL_INFO" | \
    CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" \
    $PYTHON_CMD "${HOOKS_DIR}/lib/model_router_hook.py" 2>>"$LOG_FILE")
ROUTER_EXIT=$?
set -e

if [[ $ROUTER_EXIT -eq 2 ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED $TOOL_NAME: delegation required" >> "$LOG_FILE"
    echo "$ROUTER_OUTPUT"
    trap - EXIT
    exit 2
elif [[ $ROUTER_EXIT -ne 0 ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ERROR: model router failed with code $ROUTER_EXIT, failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ALLOWED $TOOL_NAME" >> "$LOG_FILE"
    echo "$ROUTER_OUTPUT"
    exit 0
fi
