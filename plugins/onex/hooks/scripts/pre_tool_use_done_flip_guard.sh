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
_DONE_FLIP_DECIDED=0
_done_flip_exit() {
    local status=$?
    if [[ "$_DONE_FLIP_DECIDED" -eq 0 && "$status" -ne 2 ]]; then
        printf '{"decision":"block","reason":"[OMN-20368] guard_error: hook exited %s before a decision"}\n' "$status" >&2
        exit 2
    fi
}
trap _done_flip_exit EXIT
_OMNICLAUDE_HOOK_NAME="${BASH_SOURCE[0]##*/}"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${BASH_SOURCE[0]%/*}/../.." && pwd)}"
LIB_PY="${PLUGIN_ROOT}/hooks/lib/done_flip_guard.py"
_OMNICLAUDE_HOOK_PAYLOAD="$(cat)"
source "${PLUGIN_ROOT}/hooks/scripts/common.sh" || exit 1
source "${PLUGIN_ROOT}/hooks/lib/hook_refusal.sh" 2>/dev/null || true
[[ -f "$LIB_PY" && -n "${PYTHON_CMD:-}" ]] || exit 1
set +e
REFUSAL_OUTPUT=$("$PYTHON_CMD" "$LIB_PY" < <(printf '%s\n' "$_OMNICLAUDE_HOOK_PAYLOAD") 2>&1)
rc=$?
set -e
[[ -z "$REFUSAL_OUTPUT" ]] || printf '%s\n' "$REFUSAL_OUTPUT" >&2
if [[ "$rc" -eq 2 ]]; then
    REFUSAL_DETAIL=$(printf '%s' "$REFUSAL_OUTPUT" | hook_refusal_detail)
    hook_record_refusal "done flip refused without a bound dod receipt" "$REFUSAL_DETAIL" 2>/dev/null || true
fi
[[ "$rc" -eq 0 ]] || exit "$rc"
_DONE_FLIP_DECIDED=1
exit 0
