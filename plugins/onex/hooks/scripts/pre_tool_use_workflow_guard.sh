#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Workflow Guard Hook (OMN-6231)
# Enforces triage-first and ticket-first workflow preconditions:
#
#   1. Triage-first: warns if an epic creation (mcp__linear-server__save_issue
#      without parentId) is attempted without a .onex_state/triage_complete
#      marker file.
#
#   2. Ticket-first: warns if a git commit (Bash: git commit) is attempted
#      without an OMN-\d+ pattern in the branch name or commit message.
#
# Both checks are WARN-only (exit 1 → pass-through). They block obvious
# bypasses but do not hard-block because proxy signals have false positives.
#
# Hook registration: hooks.json PreToolUse, matchers:
#   "^mcp__linear-server__save_issue$" and "Bash"

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Capture original working directory before CWD normalization
_ORIGINAL_PWD="${PWD}"

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

# Only intercept relevant tools
if [[ ! "$TOOL_NAME" =~ ^(mcp__linear-server__save_issue|Bash)$ ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] Checking $TOOL_NAME for workflow preconditions" >> "$LOG_FILE"

# Locate Python
source "${HOOKS_DIR}/scripts/common.sh"

# Run Python guard
set +e
GUARD_OUTPUT=$(echo "$TOOL_INFO" | \
    CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" \
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$_ORIGINAL_PWD}" \
    $PYTHON_CMD -m omniclaude.hooks.pre_tool_use_workflow_guard 2>>"$LOG_FILE")
GUARD_EXIT=$?
set -e

if [[ $GUARD_EXIT -eq 2 ]]; then
    # Hard block (guard may escalate in future)
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED $TOOL_NAME: workflow precondition failed" >> "$LOG_FILE"
    printf '\a' >&2
    echo "$GUARD_OUTPUT"
    trap - EXIT
    exit 2
elif [[ $GUARD_EXIT -eq 1 ]]; then
    # Warn — log advisory, pass through
    ADVISORY=$(echo "$GUARD_OUTPUT" | jq -r '.reason // ""' 2>/dev/null) || ADVISORY="$GUARD_OUTPUT"
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ADVISORY for $TOOL_NAME: $ADVISORY" >> "$LOG_FILE"
    echo "$ADVISORY" >&2
    echo "$TOOL_INFO"
    exit 0
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ALLOWED $TOOL_NAME" >> "$LOG_FILE"
    echo "$GUARD_OUTPUT"
    exit 0
fi
