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

# OMN-19381: named so its refusal row names it. This guard does not source
# error-guard.sh (its EXIT trap would rewrite this guard's bare `exit 2`), so it sources
# the refusal seam on its own, after common.sh.
_OMNICLAUDE_HOOK_NAME="${BASH_SOURCE[0]##*/}"

_OMNICLAUDE_CALLER_CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
# shellcheck source=../lib/repo_guard.sh
# OMN-20109: this script's directory, resolved once without a dirname exec.
_ONEX_HOOK_SELF_DIR="${BASH_SOURCE[0]%/*}"; [[ "${BASH_SOURCE[0]}" == */* ]] || _ONEX_HOOK_SELF_DIR=.; [[ -n "$_ONEX_HOOK_SELF_DIR" ]] || _ONEX_HOOK_SELF_DIR=/
. "${_ONEX_HOOK_SELF_DIR}/../lib/repo_guard.sh" 2>/dev/null || true
if declare -F is_omninode_repo >/dev/null 2>&1; then
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$_OMNICLAUDE_CALLER_CWD}" \
        is_omninode_repo || {
        cat >/dev/null
        trap - EXIT 2>/dev/null || true
        exit 0
    }
fi

# Lite mode guard [OMN-5398]
_SCRIPT_DIR="$(cd "${_ONEX_HOOK_SELF_DIR}" && pwd)"
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
# OMN-19381: hook_record_refusal, without error-guard.sh's EXIT trap.
# shellcheck source=../lib/hook_refusal.sh
source "${PLUGIN_ROOT}/hooks/lib/hook_refusal.sh" 2>/dev/null || true
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
# OMN-19381: the payload is read here, once, so the refusal recorder can
# read the lane from it; the decision core gets the same bytes on its stdin.
_OMNICLAUDE_HOOK_PAYLOAD="$(cat)"
set +e
REFUSAL_OUTPUT=$("$PYTHON_BIN" "$LIB_PY" < <(printf '%s\n' "$_OMNICLAUDE_HOOK_PAYLOAD") 2>&1)
rc=$?
set -e
[[ -z "$REFUSAL_OUTPUT" ]] || printf '%s\n' "$REFUSAL_OUTPUT" >&2
if [[ "$rc" -eq 2 ]]; then
    REFUSAL_DETAIL=$(printf '%s' "$REFUSAL_OUTPUT" | hook_refusal_detail)
    hook_record_refusal "Linear comment refused without an actor line" "$REFUSAL_DETAIL" 2>/dev/null || true
    exit 2
fi
exit 0
