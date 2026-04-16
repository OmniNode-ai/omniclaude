#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Idle Notification Rate Limiter (OMN-8924)
#
# Drops idle_notification SendMessage calls to at most 1 per 60s per agent_id.
# Non-idle messages always pass. Excess idle_notifications are blocked via
# permissionDenied (exit 2) to prevent Claude from sending them downstream.
#
# Pass conditions (exit 0, tool_input forwarded):
#   - tool_name is not SendMessage
#   - message type is not "idle_notification"
#   - First idle_notification in the 60s window for this agent_id
#   - IDLE_RATELIMIT_DISABLED=1 kill switch
#   - onex-paths.sh fails (fail-open: infra/config failures must not block tool use)
#
# Drop condition (exit 2, permissionDenied returned):
#   - Subsequent idle_notification within the 60s window for this agent_id
#
# Hook registration: hooks.json PreToolUse, matcher "^SendMessage$"
# Ticket: OMN-8924

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

cd "$HOME" 2>/dev/null || cd /tmp || true

_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
if ! source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh"; then
    echo "FATAL: ONEX_STATE_DIR not set" >&2
    cat
    exit 0
fi
LOG_FILE="${ONEX_HOOK_LOG}"

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Safe logging helper - never blocks on write failures
safe_log() {
    local msg="$1"
    printf '%s\n' "$msg" >>"$LOG_FILE" 2>/dev/null || true
}

# Kill switch
if [[ "${IDLE_RATELIMIT_DISABLED:-0}" == "1" ]]; then
    cat
    exit 0
fi

TOOL_INFO=$(cat)

# Fast path: only care about SendMessage
TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null) || {
    echo "$TOOL_INFO"
    exit 0
}

if [[ "$TOOL_NAME" != "SendMessage" ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Check if this is an idle_notification message
MSG_TYPE=$(echo "$TOOL_INFO" | jq -er '.tool_input.message.type // empty' 2>/dev/null) || MSG_TYPE=""

if [[ "$MSG_TYPE" != "idle_notification" ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Locate Python
if ! source "${HOOKS_DIR}/scripts/common.sh"; then
    # Infra/config failure: fail open
    echo "$TOOL_INFO"
    exit 0
fi
if [[ -z "${PYTHON_CMD:-}" ]]; then
    echo "FATAL: no valid Python interpreter found" >&2
    exit 1
fi

AGENT_ID="${CLAUDE_AGENT_ID:-unknown}"

set +e
ALLOW=$(echo "$AGENT_ID" | \
    $PYTHON_CMD -c "
import sys
import os
sys.path.insert(0, '${HOOKS_LIB}')
from idle_ratelimit import should_allow_idle_notification
agent_id = sys.stdin.read().strip()
result = should_allow_idle_notification(agent_id)
print('1' if result else '0')
" 2>>"$LOG_FILE")
EXIT_CODE=$?
set -e

if [[ $EXIT_CODE -ne 0 ]] || [[ -z "$ALLOW" ]]; then
    # Fail open on error
    safe_log "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ratelimit check failed (exit=$EXIT_CODE); failing open"
    echo "$TOOL_INFO"
    exit 0
fi

if [[ "$ALLOW" == "1" ]]; then
    safe_log "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] idle_notification ALLOWED for agent=${AGENT_ID}"
    echo "$TOOL_INFO"
    exit 0
fi

# Drop: return permissionDenied to suppress the notification
safe_log "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] idle_notification DROPPED (rate limit) for agent=${AGENT_ID}"
printf '{"type":"permissionDenied","message":"idle_notification rate limited (1 per 60s per agent)"}'
exit 2
