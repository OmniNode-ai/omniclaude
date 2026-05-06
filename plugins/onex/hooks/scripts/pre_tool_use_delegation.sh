#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Delegation Hook (OMN-10607)
#
# Intercepts Agent/Task tool calls and routes them through the delegation
# pipeline (SensitivityGate → TaskClassifier). When a task is delegatable,
# blocks the tool (exit 2) and emits a delegation result via stderr.
# Falls through to exit 0 on non-delegatable, error, or disabled.
#
# Flow:
#   1. Read tool_name + tool_input from stdin JSON
#   2. Only act on Agent|Task tool calls; exit 0 for everything else
#   3. Run delegation_hook_runner.py with tool_input JSON on stdin
#   4. If result starts with "DELEGATED:": exit 2, stderr = result
#   5. Otherwise: exit 0, original tool proceeds
#
# Hook registration: hooks.json PreToolUse, matcher "^(Agent|Task)$"
# Ticket: OMN-10607

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"

# Resolve paths before cd $HOME
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/error-guard.sh" 2>/dev/null || true
if ! onex_hook_gate PRE_TOOL_USE_DELEGATION; then
    cat
    exit 0
fi

cd "$HOME" 2>/dev/null || cd /tmp || true

# Kill switch
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat
    exit 0
fi
if [[ "${PRE_TOOL_DELEGATION_DISABLED:-0}" == "1" ]]; then
    cat
    exit 0
fi

# Lite mode guard [OMN-5398]
_MODE_SH="${SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    source "$_MODE_SH"
    if [[ "$(omniclaude_mode)" == "lite" ]]; then
        cat
        exit 0
    fi
fi
unset _MODE_SH

source "${SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${ONEX_STATE_DIR:-/tmp}/hooks/logs/pre-tool-delegation.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

TIMESTAMP="$(date -u +%FT%TZ)"

# Guard: jq required
if ! command -v jq >/dev/null 2>&1; then
    cat
    exit 0
fi

TOOL_INFO=$(cat)

TOOL_NAME=$(printf '%s\n' "$TOOL_INFO" | jq -r '.tool_name // ""' 2>/dev/null) || TOOL_NAME=""

# Only intercept Agent and Task tool calls
if [[ "$TOOL_NAME" != "Agent" && "$TOOL_NAME" != "Task" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
HOOKS_LIB="${PLUGIN_ROOT}/hooks/lib"
RUNNER="${HOOKS_LIB}/delegation_hook_runner.py"

# Resolve Python (same chain as common.sh, without sourcing it to avoid side effects)
PYTHON_CMD=""
if [[ -n "${PLUGIN_PYTHON_BIN:-}" && -f "${PLUGIN_PYTHON_BIN}" && -x "${PLUGIN_PYTHON_BIN}" ]]; then
    PYTHON_CMD="${PLUGIN_PYTHON_BIN}"
elif [[ -n "${CLAUDE_PLUGIN_DATA:-}" && -x "${CLAUDE_PLUGIN_DATA}/.venv/bin/python3" ]]; then
    PYTHON_CMD="${CLAUDE_PLUGIN_DATA}/.venv/bin/python3"
else
    _repo_root="$(cd "${PLUGIN_ROOT}/../.." 2>/dev/null && pwd)" || _repo_root=""
    if [[ -n "$_repo_root" && -x "${_repo_root}/.venv/bin/python3" ]]; then
        PYTHON_CMD="${_repo_root}/.venv/bin/python3"
    elif [[ -n "${ONEX_REGISTRY_ROOT:-}" && -x "${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3" ]]; then
        PYTHON_CMD="${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3"
    fi
    unset _repo_root
fi

if [[ -z "$PYTHON_CMD" ]]; then
    echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] WARN: no Python found, passing through" >> "$LOG_FILE" 2>/dev/null || true
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

if [[ ! -f "$RUNNER" ]]; then
    echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] WARN: runner not found at ${RUNNER}, passing through" >> "$LOG_FILE" 2>/dev/null || true
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Run the delegation runner with tool input on stdin; 5s timeout
set +e
DELEGATION_RESULT=$(printf '%s\n' "$TOOL_INFO" | \
    timeout 5 env -u PYTHONPATH "$PYTHON_CMD" "$RUNNER" 2>>"$LOG_FILE")
RUNNER_EXIT=$?
set -e

if [[ $RUNNER_EXIT -ne 0 ]]; then
    echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] WARN: runner exited ${RUNNER_EXIT}, passing through" >> "$LOG_FILE" 2>/dev/null || true
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Check if delegation was approved
if [[ "$DELEGATION_RESULT" == DELEGATED:* ]]; then
    AGENT_NAME=$(printf '%s\n' "$TOOL_INFO" | jq -r '.tool_input.name // .tool_input.subagent_type // "(unnamed)"' 2>/dev/null) || AGENT_NAME="(unnamed)"
    echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] BLOCK tool=${TOOL_NAME} agent=${AGENT_NAME} result=${DELEGATION_RESULT}" >> "$LOG_FILE" 2>/dev/null || true
    printf '%s\n' "$TOOL_INFO"
    echo "DELEGATION RESULT: ${DELEGATION_RESULT}" >&2
    exit 2
fi

# Not delegatable — pass through
echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] PASS tool=${TOOL_NAME} result=${DELEGATION_RESULT}" >> "$LOG_FILE" 2>/dev/null || true
printf '%s\n' "$TOOL_INFO"
exit 0
