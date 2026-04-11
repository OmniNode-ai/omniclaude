#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Dispatch-Mode Guardrail Hook (OMN-7257)
# Advisory hook that fires when the Agent tool is invoked and surfaces a
# warning when multi-scope signals suggest TeamCreate would be more
# appropriate than a single Agent dispatch.
#
# Signals (any one fires the advisory):
#   - 3+ Linear ticket IDs in the prompt
#   - An explicit epic reference
#   - 2+ distinct repo names from the OmniNode registry
#
# Tier: warn only (exit 1). The hook never blocks the tool call.
#
# Kill switch: set DISPATCH_MODE_GUARDRAIL_DISABLED=1 to silence.
# Hook registration: hooks.json PreToolUse, matcher "^Agent$"

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Kill switch — fail open when disabled
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat
    exit 0
fi
if [[ "${DISPATCH_MODE_GUARDRAIL_DISABLED:-0}" == "1" ]]; then
    cat
    exit 0
fi

# Ensure stable CWD before any Python invocation
cd "$HOME" 2>/dev/null || cd /tmp || true

# Portable plugin root resolution
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { echo "FATAL: ONEX_STATE_DIR not set" >&2; exit 1; }
LOG_FILE="${LOG_FILE:-${ONEX_HOOK_LOG}}"

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Read stdin
TOOL_INFO=$(cat)

# Parse tool name — fail open on bad JSON
TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null) || {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ERROR: invalid hook JSON; failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
}

# Only intercept the Agent tool
if [[ "$TOOL_NAME" != "Agent" ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] Evaluating Agent dispatch for multi-scope signals" >> "$LOG_FILE"

# Locate Python
source "${HOOKS_DIR}/scripts/common.sh"

# Run Python guard (advisory-only — never exits 2)
set +e
GUARD_OUTPUT=$(echo "$TOOL_INFO" | \
    CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" \
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}" \
    $PYTHON_CMD -m omniclaude.hooks.pre_tool_use_dispatch_mode_guardrail 2>>"$LOG_FILE")
GUARD_EXIT=$?
set -e

if [[ $GUARD_EXIT -eq 1 ]]; then
    ADVISORY=$(echo "$GUARD_OUTPUT" | jq -r '.reason // ""' 2>/dev/null) || ADVISORY="$GUARD_OUTPUT"
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ADVISORY: $ADVISORY" >> "$LOG_FILE"
    echo "$ADVISORY" >&2
    echo "$TOOL_INFO"
    exit 0
fi

# Pass-through (exit 0 or anything else — fail open)
echo "$TOOL_INFO"
exit 0
