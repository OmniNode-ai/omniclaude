#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# =============================================================================
# Refusal Recorder seam (OMN-18946, OMN-19381)
# =============================================================================
# Give a refusal a durable, aggregated home. A guard that refuses a tool call
# writes its reason to the operator's terminal, which is gone at the end of
# the turn, and to a per-hook log file under a temporary directory that
# nothing reads. Neither is aggregated, so a guard refusing the same correct
# command forty times in a night produces forty invisible events and the
# morning friction sweep finds nothing.
#
# WHERE IT IS SOURCED. error-guard.sh sources this file, so every hook that
# sources error-guard.sh first has the function in scope, including the hooks
# that never source common.sh. A guard that must NOT source error-guard.sh --
# its EXIT trap turns an `exit 2` that is not preceded by `trap - EXIT` into
# `exit 0`, which would turn the refusal into an allow -- sources this file
# directly instead (OMN-19381). Before that, six registered guards called this
# function without it in scope, and `2>/dev/null || true` silenced the
# command-not-found: their refusals were recorded nowhere.
#
# WHY NOT THE EXIT TRAP. The obvious seam would be error-guard.sh's EXIT trap,
# which already sees every non-zero exit. It cannot serve: a deny path runs
# `trap - EXIT` before `exit 2` precisely so the trap does not swallow the
# deny. The trap never fires on a refusal. Each deny site therefore calls this
# explicitly, and tests/hooks/test_refusal_rows_omn18946.py is the ratchet
# that fails when a registered hook grows a deny path that does not.
#
# THE PAYLOAD (OMN-19381). The facts that name a lane -- the transcript path
# and agent id that locate the harness's sidecar, the cwd, the paths the tool
# call names -- are in the hook's own stdin payload, which the guard has
# already read. The caller exposes it as _OMNICLAUDE_HOOK_PAYLOAD (TOOL_INFO
# and STDIN_JSON, the names the guards already used, are read as fallbacks).
# It reaches the recorder on its STDIN, never on argv: a Workflow payload
# carries the whole script, and argv is size-capped and readable by every
# process on the machine. The environment operands stay as fallbacks.
#
# Backgrounded and disowned like emit_to_journal: the operator's refusal
# message must never wait on a ledger lock. The subshell's own stdout and
# stderr are redirected, not only the recorder's: the Bash-guard entrypoint
# captures each guard's output with $(...), and a background job still
# holding that pipe would make the capture wait for the recorder. Fail-open
# by construction -- this function returns 0 whatever happens.
#
# Usage: hook_record_refusal <reason> [detail]
#
#   reason   the refusal CLASS. The recorder normalises it into the dedupe
#            key: lowercased, slugified, path-like and digit-heavy segments
#            dropped, so an interpolated path cannot make every refusal unique.
#   detail   the refusal's first line. Redacted and truncated by the recorder.
#
# The guard is always $_OMNICLAUDE_HOOK_NAME, which every recording hook sets
# before sourcing this file (pinned by tests/hooks/test_refusal_row_lane_omn19381.py).

# This file's directory, made absolute NOW: several guards `cd "$HOME"` after
# sourcing, and a relative path resolved at call time would then miss the
# recorder. No exec and no fork (OMN-20109).
_ONEX_HOOK_REFUSAL_LIB="${BASH_SOURCE[0]%/*}"
[[ "${BASH_SOURCE[0]}" == */* ]] || _ONEX_HOOK_REFUSAL_LIB=.
[[ "$_ONEX_HOOK_REFUSAL_LIB" == /* ]] || _ONEX_HOOK_REFUSAL_LIB="${PWD}/${_ONEX_HOOK_REFUSAL_LIB}"

hook_record_refusal() {
    local guard="${_OMNICLAUDE_HOOK_NAME:-unknown-hook}"
    local reason="${1:-unspecified}"
    local detail="${2:-}"
    local payload="${_OMNICLAUDE_HOOK_PAYLOAD:-${TOOL_INFO:-${STDIN_JSON:-}}}"

    local lib_dir="${HOOKS_LIB:-$_ONEX_HOOK_REFUSAL_LIB}"
    local recorder="${lib_dir}/hook_refusal_recorder.py"
    [[ -f "$recorder" ]] || return 0

    local py="${PYTHON_CMD:-}"
    if [[ -z "$py" ]]; then
        if [[ -n "${ONEX_REGISTRY_ROOT:-}" && -x "${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3" ]]; then
            py="${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3"
        elif command -v python3 >/dev/null 2>&1; then
            py="python3"
        else
            return 0
        fi
    fi

    # The fallback cwd when the payload carries none: the directory the HOOK
    # fired in, not this backgrounded process's -- the OMN-18609 correction.
    local cwd="${CLAUDE_PROJECT_DIR:-$PWD}"

    (
        "$py" "$recorder" \
            --guard "$guard" \
            --reason "$reason" \
            --detail "$detail" \
            --cwd "$cwd" \
            --transcript-path "${TRANSCRIPT_PATH:-}" \
            --session-id "${SESSION_ID:-}" \
            --agent-id "${AGENT_ID:-}" \
            --payload-stdin \
            < <(printf '%s\n' "$payload")
    ) >>"${LOG_FILE:-/dev/null}" 2>&1 </dev/null &
    disown 2>/dev/null || true
    return 0
}
