#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PostToolUse Cost Accounting Hook (OMN-10619)
#
# Fires after Agent/Task tool calls to:
#   1. Read any pending delegation result written by the PreToolUse model router
#   2. Record cost accounting data to SQLite (actual vs Opus baseline)
#   3. If a delegation result is pending, inject it as hookSpecificOutput.additionalContext
#      using the proven OMN-10606 injection mechanism (PostToolUse exit 0 + JSON)
#
# Savings provenance:
#   - All savings are counterfactual estimates labeled with baseline_model and
#     pricing_manifest_version
#   - token_provenance: MEASURED when usage data is available, ESTIMATED otherwise
#   - Local model cost: $0.00 with savings_method: zero_marginal_api_cost
#
# Event:        PostToolUse
# Matcher:      ^(Agent|Task|TaskCreate|TaskUpdate)$
# hookEventName: PostToolUse  (emitted by cost_accounting.py via hookSpecificOutput)
# Ticket:  OMN-10619

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true
onex_hook_gate COST_ACCOUNTING || exit 0

# --- Global kill switch ---
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat
    exit 0
fi

# --- Lite mode guard (OMN-5398) ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    source "$_MODE_SH"
    [[ "$(omniclaude_mode)" == "lite" ]] && exit 0
fi
unset _SCRIPT_DIR _MODE_SH

# Ensure stable CWD before any Python invocation.
cd "$HOME" 2>/dev/null || cd /tmp || true

# Portable plugin root resolution.
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"

# --- Log path [OMN-8429] ---
if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    echo "[$(date -u +%FT%TZ)] ERROR: ONEX_STATE_DIR unset; cost-accounting hook cannot write log." \
        >> /tmp/onex-hook-error.log
    cat
    exit 0
fi
LOG_FILE="${ONEX_STATE_DIR}/hooks/logs/cost-accounting.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

_log() { echo "[$(date -u +%FT%TZ)] $*" >> "$LOG_FILE" 2>/dev/null || true; }

# Guard: jq is required
if ! command -v jq >/dev/null 2>&1; then
    _log "SKIP: jq not found"
    cat
    exit 0
fi

# --- Read hook event ---
HOOK_EVENT="$(cat)"

if ! printf '%s\n' "$HOOK_EVENT" | jq -e . >/dev/null 2>>"$LOG_FILE"; then
    _log "SKIP: malformed JSON on stdin"
    printf '%s\n' "$HOOK_EVENT"
    exit 0
fi

TOOL_NAME="$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_name // ""')"

# Only act on Agent/Task calls
if [[ "$TOOL_NAME" != "Agent" && "$TOOL_NAME" != "Task" && \
      "$TOOL_NAME" != "TaskCreate" && "$TOOL_NAME" != "TaskUpdate" ]]; then
    printf '%s\n' "$HOOK_EVENT"
    exit 0
fi

# --- Resolve Python ---
PYTHON_BIN="${PLUGIN_PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
    if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
        _VENV_PYTHON="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
        if [[ -x "$_VENV_PYTHON" ]]; then
            PYTHON_BIN="$_VENV_PYTHON"
        fi
        unset _VENV_PYTHON
    fi
fi
if [[ -z "$PYTHON_BIN" ]]; then
    PYTHON_BIN="python3"
fi

# Repo root for PYTHONPATH (cost_accounting lives at plugins/onex/hooks/lib/)
REPO_ROOT="$(cd "${HOOKS_LIB}/../../../.." && pwd)"

# --- Run cost accounting module ---
# The module reads stdin (hook event), records cost data, and prints
# hookSpecificOutput JSON only when a delegation result needs injection.
set +e
INJECTION_OUTPUT="$(
    PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" \
    "$PYTHON_BIN" -m plugins.onex.hooks.lib.cost_accounting \
    <<< "$HOOK_EVENT" 2>>"$LOG_FILE"
)"
PYTHON_EXIT=$?
set -e

if [[ $PYTHON_EXIT -ne 0 ]]; then
    _log "WARN: cost_accounting exited $PYTHON_EXIT; passing through"
    printf '%s\n' "$HOOK_EVENT"
    exit 0
fi

# If Python module emitted hookSpecificOutput, output it (delegation injection).
# Otherwise pass through the original event silently.
if [[ -n "$INJECTION_OUTPUT" ]]; then
    _log "INFO: injecting delegation result for tool=$TOOL_NAME"
    printf '%s\n' "$INJECTION_OUTPUT"
else
    _log "INFO: recorded cost for tool=$TOOL_NAME (no injection)"
    printf '%s\n' "$HOOK_EVENT"
fi

exit 0
