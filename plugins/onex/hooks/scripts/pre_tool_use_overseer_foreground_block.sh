#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Overseer Foreground Block (OMN-8376)
#
# When .onex_state/overseer-active.flag exists, foreground Bash/Edit/Write
# tools targeting repo paths under $OMNI_HOME are BLOCKED so the lead agent
# cannot drift into manual fixes while an overseer contract is driving.
#
# Pattern mirrors pre_tool_use_bash_guard.sh (OMN-7018 worktree enforcement).
# Read-only tools (Read, Grep, Glob, TaskList, SendMessage) are not routed
# here via the hooks.json matcher and remain allowed unconditionally.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Ensure stable CWD before any Python invocation.
cd "$HOME" 2>/dev/null || cd /tmp || true

_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { echo "FATAL: ONEX_STATE_DIR not set" >&2; exit 1; }
LOG_FILE="${ONEX_HOOK_LOG}"

mkdir -p "$(dirname "$LOG_FILE")"

# Read stdin
TOOL_INFO=$(cat)

# Fast path: if the flag file doesn't exist, skip everything. This keeps the
# hook below the 100ms budget when no overseer is active (the common case).
FLAG_PATH="${ONEX_STATE_DIR}/overseer-active.flag"
if [[ ! -f "$FLAG_PATH" ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Parse tool name — fail open on bad JSON
TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null) || {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ERROR: invalid hook JSON; failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
}

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] overseer flag present, checking $TOOL_NAME" >> "$LOG_FILE"

# Locate Python
source "${HOOKS_DIR}/scripts/common.sh"

# Run Python guard
set +e
RESULT=$(echo "$TOOL_INFO" | \
    $PYTHON_CMD "${HOOKS_LIB}/overseer_foreground_block.py" 2>>"$LOG_FILE")
EXIT_CODE=$?
set -e

if [[ $EXIT_CODE -eq 2 ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED $TOOL_NAME: overseer active" >> "$LOG_FILE"
    printf '\a' >&2
    echo "$RESULT"
    trap - EXIT
    exit 2
elif [[ $EXIT_CODE -eq 0 ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ALLOWED $TOOL_NAME (flag present but not targeting repo)" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ERROR: guard failed with code $EXIT_CODE, failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi
