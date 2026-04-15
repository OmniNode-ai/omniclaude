#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Agent Tool Gate (OMN-8842)
#
# Reads the active agent from correlation state, loads its YAML, and blocks
# any tool listed in disallowedTools. This prevents background worker agents
# from calling cron/scheduling tools (thundering herd prevention).
#
# Exit 2 = hard block with clear message.
# Exit 0 = pass through (fail-open: no active agent, YAML unresolvable, etc.)

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
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { echo "FATAL: ONEX_STATE_DIR not set" >&2; exit 1; }
LOG_FILE="${ONEX_HOOK_LOG}"

mkdir -p "$(dirname "$LOG_FILE")"

TOOL_INFO=$(cat)

TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null) || {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ERROR: invalid hook JSON; failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
}

source "${HOOKS_DIR}/scripts/common.sh"

set +e
RESULT=$(echo "$TOOL_INFO" | \
    $PYTHON_CMD "${HOOKS_LIB}/agent_tool_gate.py" 2>>"$LOG_FILE")
EXIT_CODE=$?
set -e

if [[ $EXIT_CODE -eq 2 ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED $TOOL_NAME: disallowedTools rule fired" >> "$LOG_FILE"
    printf '\a' >&2
    echo "$RESULT"
    trap - EXIT
    exit 2
elif [[ $EXIT_CODE -eq 0 ]]; then
    if [[ -n "$RESULT" ]] && [[ "$RESULT" != "{}" ]]; then
        echo "$RESULT"
    else
        echo "$TOOL_INFO"
    fi
    exit 0
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ERROR: gate failed code $EXIT_CODE, failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi
