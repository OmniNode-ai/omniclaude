#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# UserPromptSubmit hook — Session phase enforcement injection [OMN-11282].
#
# Reads .onex_state/session/phase_state.yaml written by node_session_phase_reducer
# and injects a hard directive into Claude's context when a phase transition or
# halt is required. No-op when the state file is absent (non-session contexts).
#
# Exit codes:
#   0 — always (hooks must never block on missing state; only advise)

set -eo pipefail

# Lite mode guard [OMN-5398]
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    # shellcheck source=../../lib/mode.sh
    # shellcheck disable=SC1091
    source "$_MODE_SH"
    if [[ "$(omniclaude_mode)" == "lite" ]]; then
        cat >/dev/null
        exit 0
    fi
fi
unset _MODE_SH

# Drain stdin (required by hook protocol; we don't use prompt contents)
cat >/dev/null

# Resolve the state file path
if [[ -n "${ONEX_STATE_DIR:-}" ]]; then
    STATE_FILE="${ONEX_STATE_DIR}/session/phase_state.yaml"
else
    # Fall back to cwd-relative path (worktree context)
    STATE_FILE=".onex_state/session/phase_state.yaml"
fi

# No state file → silent no-op (non-session contexts are normal)
if [[ ! -f "$STATE_FILE" ]]; then
    exit 0
fi

# Resolve Python interpreter (prefer plugin venv, fall back to system python3)
PYTHON_BIN=""
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
_VENV="${PLUGIN_ROOT}/lib/.venv/bin/python"
if [[ -x "${_VENV}" ]]; then
    PYTHON_BIN="${_VENV}"
elif [[ -n "${PLUGIN_PYTHON_BIN:-}" && -x "${PLUGIN_PYTHON_BIN}" ]]; then
    PYTHON_BIN="${PLUGIN_PYTHON_BIN}"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
fi
unset _VENV

if [[ -z "$PYTHON_BIN" ]]; then
    # No Python available — pass through silently (hook must not block)
    exit 0
fi

# Invoke the Python hook logic
DIRECTIVE="$("$PYTHON_BIN" - "$STATE_FILE" <<'PYEOF' 2>/dev/null
import sys
import yaml

state_file = sys.argv[1]
try:
    with open(state_file) as fh:
        state = yaml.safe_load(fh)
    if not isinstance(state, dict):
        sys.exit(0)
except Exception:
    sys.exit(0)

evaluation = state.get("last_evaluation", "no_action")
current_phase = state.get("current_phase", "unknown")

if evaluation == "transition_required":
    next_phase = state.get("next_phase") or "next"
    print(
        f"[PHASE ENFORCEMENT] Phase '{current_phase}' budget exhausted. "
        f"Transition to '{next_phase}' required. "
        "Stop current work and dispatch next phase workers."
    )
elif evaluation == "halt_required":
    reason = state.get("halt_reason") or "unspecified"
    print(
        f"[SESSION HALT] Halt condition triggered: {reason}. "
        "Stop all work immediately."
    )
elif evaluation == "budget_warning":
    pct = state.get("budget_elapsed_pct", 0)
    print(
        f"[PHASE WARNING] Phase '{current_phase}' at {pct}% of time budget. "
        "Plan to transition soon."
    )
PYEOF
)" || true

# No directive → silent no-op
if [[ -z "$DIRECTIVE" ]]; then
    exit 0
fi

# Emit the directive as additionalContext per Claude Code hook protocol
if command -v jq >/dev/null 2>&1; then
    jq -n --arg ctx "$DIRECTIVE" \
        '{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": $ctx}}'
else
    ESCAPED_CTX="$("$PYTHON_BIN" -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$DIRECTIVE")"
    printf '{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": %s}}\n' \
        "$ESCAPED_CTX"
fi

exit 0
