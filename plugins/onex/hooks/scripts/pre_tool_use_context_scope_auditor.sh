#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Context Scope Auditor — PreToolUse hook (OMN-5237)
#
# Runs AFTER the poly enforcer for every tool call within an active task.
# Audits tool scope and context budget constraints declared in the task contract.
#
# Delegates to omniclaude.hooks.handlers.context_scope_auditor via Python.
#
# Exit codes:
#   0 — allow the tool call
#   2 — block the tool call (STRICT/PARANOID mode violations only)

set -eo pipefail

_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"

# --- Lite mode guard [OMN-5398] ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _SCRIPT_DIR _MODE_SH

# Resolve plugin root
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR

source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { echo "ONEX_STATE_DIR not set" >&2; exit 1; }
LOG_FILE="${ONEX_HOOK_LOG}"
mkdir -p "$(dirname "$LOG_FILE")"

HOOKS_DIR="${PLUGIN_ROOT}/hooks"
source "${HOOKS_DIR}/scripts/common.sh"

export OMNICLAUDE_HOOK_CRITICALITY="advisory"

# Read stdin
INPUT=$(cat)

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] Running context scope audit" >> "$LOG_FILE"

# Invoke the Python handler.
# The handler reads the hook JSON from stdin, audits it, and either:
#   - Prints the original JSON and exits 0 (allow)
#   - Prints a block decision JSON and exits 2 (block)

cd "$HOME" 2>/dev/null || cd /tmp || true

EXIT_CODE=0
_stderr_tmp=$(mktemp)
RESULT=$(echo "$INPUT" \
    | "$PYTHON_CMD" -m omniclaude.hooks.handlers.context_scope_auditor 2>"$_stderr_tmp") \
    || EXIT_CODE=$?
# Append stderr to log file and check for degradation signals (OMN-6567)
cat "$_stderr_tmp" >> "$LOG_FILE" 2>/dev/null || true
if grep -qE "ModuleNotFoundError|ImportError|Traceback" "$_stderr_tmp" 2>/dev/null; then
    ( notify_hook_degraded "$_OMNICLAUDE_HOOK_NAME" "$(head -1 "$_stderr_tmp")" ) &
fi
rm -f "$_stderr_tmp"

# --- Error counter tracking [F32] ---
ERROR_COUNT_DIR="${HOME}/.onex_state/hooks/error-counts"
mkdir -p "$ERROR_COUNT_DIR"
ERROR_COUNT_FILE="${ERROR_COUNT_DIR}/${_OMNICLAUDE_HOOK_NAME}.count"

if [[ $EXIT_CODE -eq 2 ]]; then
    # Intentional block — reset error counter
    echo "0" > "$ERROR_COUNT_FILE" 2>/dev/null || true
    echo "$RESULT"
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED by context scope auditor" >> "$LOG_FILE"
    exit 2
elif [[ $EXIT_CODE -ne 0 ]]; then
    # Python handler crashed — fail-open but log distinctly [F33]
    CURRENT_COUNT=$(cat "$ERROR_COUNT_FILE" 2>/dev/null || echo "0")
    NEW_COUNT=$((CURRENT_COUNT + 1))
    echo "$NEW_COUNT" > "$ERROR_COUNT_FILE"
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] [HOOK_CRASH] Python handler exited $EXIT_CODE — allowing tool call (fail-open, consecutive=$NEW_COUNT)" >> "$LOG_FILE"
    if [[ $NEW_COUNT -ge 5 ]]; then
        mkdir -p "${HOME}/.onex_state/hooks"
        {
            echo "hook: $_OMNICLAUDE_HOOK_NAME"
            echo "consecutive_errors: $NEW_COUNT"
            echo "last_error_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
            echo "last_exit_code: $EXIT_CODE"
        } > "${HOME}/.onex_state/hooks/hook-health-degraded.flag"
    fi
    echo "$INPUT"  # pass through original input
    exit 0
fi

# Success — reset error counter
echo "0" > "$ERROR_COUNT_FILE" 2>/dev/null || true

# Pass through (allow)
echo "$RESULT"
exit 0
