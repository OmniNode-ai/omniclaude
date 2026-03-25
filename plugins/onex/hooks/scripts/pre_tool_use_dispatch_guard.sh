#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Dispatch Guard Hook (OMN-6230)
# Blocks hardcoded connection URLs / credentials before any file is written,
# and surfaces advisory warnings for direct ONEX node implementation writes
# that bypass polymorphic-agent dispatch.
#
# Enforcement tiers:
#   Hard block (exit 2): hardcoded PostgreSQL/Redis URLs, private-IP LLM
#                        endpoints, inline password= / api_key= assignments.
#   Warn (exit 1):       direct Write/Edit to ONEX node implementation files
#                        (e.g. *_effect.py, *_compute.py) under src/ dirs.
#   Pass-through (exit 0): everything else.
#
# Hook registration: hooks.json PreToolUse, matcher "^(Edit|Write|Bash)$"

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

# Only intercept tools that write content
if [[ ! "$TOOL_NAME" =~ ^(Edit|Write|Bash)$ ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] Checking $TOOL_NAME for dispatch violations" >> "$LOG_FILE"

# Locate Python
source "${HOOKS_DIR}/scripts/common.sh" 2>/dev/null || true
PYTHON_CMD="${PYTHON_CMD:-python3}"

# Run Python guard
set +e
GUARD_OUTPUT=$(echo "$TOOL_INFO" | \
    CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" \
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}" \
    $PYTHON_CMD -m omniclaude.hooks.pre_tool_use_dispatch_guard 2>>"$LOG_FILE")
GUARD_EXIT=$?
set -e

if [[ $GUARD_EXIT -eq 2 ]]; then
    # Hard block
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED $TOOL_NAME: dispatch violation" >> "$LOG_FILE"
    printf '\a' >&2
    echo "$GUARD_OUTPUT"
    trap - EXIT
    exit 2
elif [[ $GUARD_EXIT -eq 1 ]]; then
    # Warn — log advisory, pass through the original tool call
    ADVISORY=$(echo "$GUARD_OUTPUT" | jq -r '.reason // ""' 2>/dev/null) || ADVISORY="$GUARD_OUTPUT"
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ADVISORY for $TOOL_NAME: $ADVISORY" >> "$LOG_FILE"
    # Print advisory as a JSON block decision with decision="warn" (non-blocking)
    # Claude Code does not have a native "warn" decision — we output the advisory
    # to stderr so it appears in hooks.log, then pass through the original JSON.
    echo "$ADVISORY" >&2
    echo "$TOOL_INFO"
    exit 0
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ALLOWED $TOOL_NAME" >> "$LOG_FILE"
    echo "$GUARD_OUTPUT"
    exit 0
fi
