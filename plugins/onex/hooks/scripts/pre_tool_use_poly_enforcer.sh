#!/bin/bash
# PreToolUse Polymorphic Agent Enforcer Hook
# Intercepts Task and Agent tool calls and blocks any that don't use
# an onex:-prefixed subagent_type. This ensures all automated workflows
# go through the polymorphic agent layer for ONEX capabilities,
# intelligence integration, and observability.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Ensure stable CWD before any processing.
cd "$HOME" 2>/dev/null || cd /tmp || true

# Portable Plugin Configuration
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
LOG_FILE="${LOG_FILE:-$HOME/.claude/hooks.log}"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Read stdin
TOOL_INFO=$(cat)
if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null); then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ERROR: invalid hook JSON; failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi

# Only intercept Task and Agent tool invocations
if [[ ! "$TOOL_NAME" =~ ^(Task|Agent)$ ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] Checking $TOOL_NAME for onex: subagent_type" >> "$LOG_FILE"

# Extract subagent_type from tool_input
SUBAGENT_TYPE=$(echo "$TOOL_INFO" | jq -r '.tool_input.subagent_type // ""' 2>/dev/null) || SUBAGENT_TYPE=""

# Allow if subagent_type starts with "onex:"
if [[ "$SUBAGENT_TYPE" == onex:* ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ALLOWED: $TOOL_NAME with subagent_type=$SUBAGENT_TYPE" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi

# Block: subagent_type is missing or does not have onex: prefix
if [[ -z "$SUBAGENT_TYPE" ]]; then
    BLOCK_DETAIL="subagent_type is missing"
else
    BLOCK_DETAIL="subagent_type=\"$SUBAGENT_TYPE\" does not have the required onex: prefix"
fi

BLOCK_REASON="$TOOL_NAME call blocked: $BLOCK_DETAIL. All Task/Agent calls must use subagent_type=\"onex:polymorphic-agent\" (or another onex:-prefixed type) to ensure ONEX capabilities, intelligence integration, and observability are active. Fix: set subagent_type=\"onex:polymorphic-agent\" in your $TOOL_NAME call."

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED: $TOOL_NAME ($BLOCK_DETAIL)" >> "$LOG_FILE"

# Output block decision JSON and exit 2 to deny the tool call.
# Clear the error-guard EXIT trap first -- exit 2 is an intentional block,
# not a crash. The error guard would swallow it and exit 0 instead.
jq -n --arg reason "$BLOCK_REASON" '{"decision": "block", "reason": $reason}'
trap - EXIT
exit 2
