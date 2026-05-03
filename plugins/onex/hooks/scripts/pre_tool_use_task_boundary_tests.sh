#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# PreToolUse Task-Boundary Tests Hook [OMN-7261]
# Intercepts git commit / gh pr create and runs targeted tests first.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

_OMNICLAUDE_CALLER_CWD="${CLAUDE_PROJECT_DIR:-$PWD}"

# shellcheck source=../lib/repo_guard.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib/repo_guard.sh" 2>/dev/null || true
if declare -F is_omninode_repo >/dev/null 2>&1; then
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$_OMNICLAUDE_CALLER_CWD}" \
        is_omninode_repo || {
        _OMNICLAUDE_PASSTHROUGH=$(cat)
        echo "$_OMNICLAUDE_PASSTHROUGH"
        trap - EXIT 2>/dev/null || true
        exit 0
    }
fi

cd "$HOME" 2>/dev/null || cd /tmp || true

_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
TOOL_INFO=$(cat)
source "${SCRIPT_DIR}/onex-paths.sh" || {
    echo "ONEX_STATE_DIR not set" >&2
    echo "$TOOL_INFO"
    exit 0
}
unset SCRIPT_DIR
LOG_FILE="${ONEX_HOOK_LOG}"

HOOK_BITS_PATH="${HOOKS_LIB}/hook_bits.sh"
if [[ -f "$HOOK_BITS_PATH" ]]; then
    # shellcheck source=../lib/hook_bits.sh
    source "$HOOK_BITS_PATH"
    TASK_BOUNDARY_BIT="$(hook_bits_bit_for_name TASK_BOUNDARY_TESTS 2>/dev/null || true)"
    if [[ -n "$TASK_BOUNDARY_BIT" ]]; then
        if [[ -z "${ONEX_HOOKS_MASK:-}" ]]; then
            echo "$TOOL_INFO"
            exit 0
        fi
        TASK_BOUNDARY_MASK="$(hook_bits_parse_mask "$ONEX_HOOKS_MASK")"
        if ! hook_bits_is_enabled "$TASK_BOUNDARY_MASK" "$TASK_BOUNDARY_BIT"; then
            echo "$TOOL_INFO"
            exit 0
        fi
    fi
fi
unset HOOK_BITS_PATH TASK_BOUNDARY_BIT TASK_BOUNDARY_MASK

PROJECT_ROOT="${PLUGIN_ROOT}/../.."
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"
elif [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"
else
    PROJECT_ROOT="$(pwd)"
fi

mkdir -p "$(dirname "$LOG_FILE")"

export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

source "${HOOKS_DIR}/scripts/common.sh"
if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>>"$LOG_FILE"); then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: invalid hook JSON; failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi

if [[ "$TOOL_NAME" != "Bash" ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

COMMAND=$(echo "$TOOL_INFO" | jq -r '.tool_input.command // empty' 2>/dev/null)
if [[ -z "$COMMAND" ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

if ! echo "$COMMAND" | grep -qE '(^|\s|&&|\|\||;)git\s+commit(\s|$)'; then
    if ! echo "$COMMAND" | grep -qE '(^|\s|&&|\||;)gh\s+pr\s+create(\s|$)'; then
        echo "$TOOL_INFO"
        exit 0
    fi
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Task-boundary tests triggered" >> "$LOG_FILE"

set +e
RESULT=$(echo "$TOOL_INFO" | \
    env -u PYTHONPATH "$PYTHON_CMD" "${HOOKS_LIB}/task_boundary_tests.py" 2>>"$LOG_FILE")
EXIT_CODE=$?
set -e

if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Task-boundary tests PASSED" >> "$LOG_FILE"
    echo "$RESULT"
elif [ $EXIT_CODE -eq 2 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Task-boundary tests BLOCKED" >> "$LOG_FILE"
    echo "$RESULT"
    exit 2
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: Task-boundary tests failed with code $EXIT_CODE, failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi
