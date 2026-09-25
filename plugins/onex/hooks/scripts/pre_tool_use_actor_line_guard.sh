#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Actor-line guard for agent-posted Linear comments [OMN-13856, ruling
# docs/tracking/ROLLING_WORK_LEDGER.md:4344 item (4)]. PreToolUse hook on
# mcp__linear-server__{save_comment,save_diff_comment}.
#
# Blocks a comment/diff-comment write whose body does not open with a
# well-formed actor line ("actor: <lane or agent> (<model>)"). See
# actor_line_guard.py's module docstring for the exact shape and for which
# comment-posting paths this guard does NOT cover.
#
# Security-class guard, same posture as the SubagentStop secret-leak guards
# and the credential-rotation guard: does NOT participate in
# ONEX_HOOKS_MASK -- a stale saved mask literal must never silently disable
# an attribution control. Only lite mode / non-OmniNode repo short-circuit it.
#
# Exit codes:
#   0 — allow the tool call
#   2 — block the tool call (JSON decision on stderr)

set -eo pipefail

_OMNICLAUDE_CALLER_CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
# shellcheck source=../lib/repo_guard.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib/repo_guard.sh" 2>/dev/null || true
if declare -F is_omninode_repo >/dev/null 2>&1; then
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$_OMNICLAUDE_CALLER_CWD}" \
        is_omninode_repo || {
        cat >/dev/null
        trap - EXIT 2>/dev/null || true
        exit 0
    }
fi

# Lite mode guard [OMN-5398]
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    source "$_MODE_SH"
    [[ "$(omniclaude_mode)" == "lite" ]] && exit 0
fi

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
LIB_PY="${PLUGIN_ROOT}/hooks/lib/actor_line_guard.py"

# common.sh provides PYTHON_CMD resolution and shared helpers used by all hooks
# that invoke Python. Sourced here to satisfy the hooks-source-common invariant.
# shellcheck source=/dev/null
source "${PLUGIN_ROOT}/hooks/scripts/common.sh"
unset _SCRIPT_DIR _MODE_SH

if [[ ! -f "$LIB_PY" ]]; then
    # Library missing — fail open so we never block on our own bug.
    cat >/dev/null
    exit 0
fi

PYTHON_BIN="${PYTHON_CMD:-python3}"
# Only exit code 2 (blocking decision) should propagate. Any other non-zero
# exit is a Python runtime error in the hook itself — fail open to avoid
# blocking legitimate tool calls on a hook bug (never blocks on our own defect).
set +e
"$PYTHON_BIN" "$LIB_PY"
rc=$?
set -e
if [[ "$rc" -eq 2 ]]; then
    hook_record_refusal "Linear comment refused without an actor line" "an agent-posted Linear comment was refused by the actor-line guard" 2>/dev/null || true
    exit 2
fi
exit 0
