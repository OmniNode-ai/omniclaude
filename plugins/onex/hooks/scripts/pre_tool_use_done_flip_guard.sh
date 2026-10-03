#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Done-flip bound-receipt guard [OMN-13856, OMN-20368]. PreToolUse hook on
# mcp__linear-server__{save,update}_issue.
#
# A Linear ticket reaches Done only when its OCC contract binds every
# acceptance criterion to a PASS receipt taken against the current contract
# entry, and an acceptance box is ticked only under the same receipt. The
# decision lives in done_flip_guard.py.
#
# FAIL CLOSED (OMN-20368). Before this ticket the wrapper let a call through
# when the cwd was not an omninode repo, when mode.sh said lite, when the hooks
# mask was set, when the decision library was missing, and when the library
# crashed. A Linear ticket is global state, so none of those says anything
# about whether a Done is earned; each one is now a refusal or is gone. There
# is no skip token and no environment bypass.
#
# Exit codes:
#   0 — allow the tool call
#   2 — block the tool call (JSON decision on stderr)

set -eo pipefail

# OMN-19381: named so its refusal row names it. This guard does not source
# error-guard.sh (its EXIT trap would rewrite this guard's bare `exit 2`), so it
# sources the refusal seam on its own, after common.sh.
_OMNICLAUDE_HOOK_NAME="${BASH_SOURCE[0]##*/}"

# OMN-20109: this script's directory, resolved once without a dirname exec.
_ONEX_HOOK_SELF_DIR="${BASH_SOURCE[0]%/*}"; [[ "${BASH_SOURCE[0]}" == */* ]] || _ONEX_HOOK_SELF_DIR=.; [[ -n "$_ONEX_HOOK_SELF_DIR" ]] || _ONEX_HOOK_SELF_DIR=/
_SCRIPT_DIR="$(cd "${_ONEX_HOOK_SELF_DIR}" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
LIB_PY="${PLUGIN_ROOT}/hooks/lib/done_flip_guard.py"
unset _SCRIPT_DIR

_done_flip_refuse() {
    # $1: reason. Refuse the Linear write, loudly, in the hook's JSON shape.
    printf '{"decision": "block", "reason": "[OMN-20368 done-flip bound-receipt gate] %s"}\n' "$1" >&2
    exit 2
}

# The payload is read once, so the refusal recorder can read the lane from it
# and the decision core gets the same bytes on its stdin (OMN-19381).
_OMNICLAUDE_HOOK_PAYLOAD="$(cat)"

# common.sh provides PYTHON_CMD resolution. A failure to source it is a
# refusal, not an allow: without an interpreter nothing can be decided.
# shellcheck source=/dev/null
source "${PLUGIN_ROOT}/hooks/scripts/common.sh" \
    || _done_flip_refuse "guard_error: common.sh could not be sourced, so no interpreter is resolved"
# OMN-19381: hook_record_refusal, without error-guard.sh's EXIT trap.
# shellcheck source=../lib/hook_refusal.sh
source "${PLUGIN_ROOT}/hooks/lib/hook_refusal.sh" 2>/dev/null || true

[[ -f "$LIB_PY" ]] || _done_flip_refuse "guard_error: decision library ${LIB_PY} is missing"

PYTHON_BIN="${PYTHON_CMD:-}"
[[ -n "$PYTHON_BIN" ]] || _done_flip_refuse "guard_error: no Python interpreter resolved for the guard"

set +e
"$PYTHON_BIN" "$LIB_PY" < <(printf '%s\n' "$_OMNICLAUDE_HOOK_PAYLOAD")
rc=$?
set -e
if [[ "$rc" -eq 0 ]]; then
    exit 0
fi
if [[ "$rc" -eq 2 ]]; then
    # OMN-18946: see hook_record_refusal in error-guard.sh.
    hook_record_refusal "done flip refused without a bound dod receipt" "a Done transition or acceptance-box tick was refused by the bound-receipt guard" 2>/dev/null || true
    exit 2
fi
# Any other exit is the guard failing to decide. That refuses (OMN-20368).
_done_flip_refuse "guard_error: done_flip_guard.py exited ${rc} without a decision"
