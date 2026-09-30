#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# How a Bash PreToolUse guard runs its Python decision core (OMN-20118).
#
# Each of the seven Bash guards used to start its own interpreter for its
# decision core, as its own registered hook process. On the operator Mac an
# interpreter start costs 0.2 to 0.85 s idle and 5 to 8 s under contention,
# and it was the larger part of every tool call's hook wall time. The guards
# are now run by ONE registered entrypoint, pre_tool_use_bash_guards.sh, which
# sources each guard script in its own subshell and runs every decision core
# the call needs in ONE interpreter (lib/bash_guard_cores.py).
#
# A guard script calls onex_guard_core where it used to start Python, and reads
# ONEX_GUARD_OUT and ONEX_GUARD_RC afterwards. Everything else in the guard,
# its gate bit, its pre-filter, its fail-closed branches and its refusal text,
# is unchanged and still runs in the guard's own shell.
#
#   onex_guard_core [--stdin TEXT] [--stderr merge|append:FILE] [--cwd DIR] \
#       [--unset NAME]... [--set NAME=VALUE]... -- PYTHON SCRIPT [ARG...]
#
# --stdin    the text on the core's stdin; without it the core inherits stdin
# --stderr   merge: stderr joins the captured output (the old `2>&1`);
#            append:FILE: stderr is appended to FILE (the old `2>>FILE`)
# --cwd      the directory the core runs in (default: the current one)
# --unset / --set   the environment the core sees, relative to this shell's
#            exported environment (the old `env -u NAME NAME=VALUE`)
#
# Three modes, chosen by the entrypoint through ONEX_BASH_GUARDS_PHASE (a
# shell variable, never exported, so no core ever sees it):
#
#   unset    the guard script was run on its own: the core runs here, in its
#            own interpreter, exactly as before. The per-guard unit tests run
#            the scripts this way.
#   collect  the entrypoint's first pass: write the request (argv, stdin,
#            stderr mode, cwd and the full environment the core would see) to
#            ${ONEX_BASH_GUARDS_REQ}.${ONEX_BASH_GUARDS_SLOT}.req and end the
#            guard's subshell with ONEX_BASH_GUARDS_COLLECTED (99).
#   replay   the entrypoint's second pass, after the one interpreter ran every
#            request: ONEX_GUARD_OUT and ONEX_GUARD_RC are the recorded result.
#            A missing result (the interpreter did not start, or crashed) is a
#            non-zero exit carrying the entrypoint's diagnosis, so the guard
#            takes its own evaluation-failed branch and refuses: fail-closed,
#            with its own message, as when its own interpreter failed.
#
# Bash 3.2 compatible: this runs under /bin/bash on macOS.

ONEX_BASH_GUARDS_COLLECTED=99

onex_guard_core() {
    local _ogc_have_stdin=0 _ogc_stdin="" _ogc_stderr="merge" _ogc_cwd=""
    local -a _ogc_unset=() _ogc_set=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --stdin) _ogc_have_stdin=1; _ogc_stdin="$2"; shift 2 ;;
            --stderr) _ogc_stderr="$2"; shift 2 ;;
            --cwd) _ogc_cwd="$2"; shift 2 ;;
            --unset) _ogc_unset+=("$2"); shift 2 ;;
            --set) _ogc_set+=("$2"); shift 2 ;;
            --) shift; break ;;
            *) break ;;
        esac
    done
    ONEX_GUARD_OUT=""
    ONEX_GUARD_RC=0

    case "${ONEX_BASH_GUARDS_PHASE:-}" in
        collect)
            # A request that cannot be written must not trip the ERR/EXIT traps
            # (error-guard.sh turns an unexpected error into exit 0, an allow):
            # the entrypoint treats every collect exit as needing its core, and
            # a missing request replays as a failed core, which refuses.
            _onex_guard_core_collect "$@" 2>/dev/null || true
            trap - EXIT ERR 2>/dev/null || true
            exit "$ONEX_BASH_GUARDS_COLLECTED"
            ;;
        replay)
            local _ogc_rc_var="ONEX_BASH_GUARDS_RC_${ONEX_BASH_GUARDS_SLOT:-x}"
            local _ogc_out_var="ONEX_BASH_GUARDS_OUT_${ONEX_BASH_GUARDS_SLOT:-x}"
            if [[ -n "${!_ogc_rc_var:-}" ]]; then
                ONEX_GUARD_RC="${!_ogc_rc_var}"
                ONEX_GUARD_OUT="${!_ogc_out_var:-}"
            else
                ONEX_GUARD_RC=70
                ONEX_GUARD_OUT="${ONEX_BASH_GUARDS_FAILURE:-the shared Bash guard interpreter returned no result for this guard (OMN-20118)}"
            fi
            return 0
            ;;
    esac

    # Standalone: the decision core in its own interpreter, as before.
    local _ogc_rc=0
    ONEX_GUARD_OUT=$(
        if [[ -n "$_ogc_cwd" ]]; then cd "$_ogc_cwd" || exit 1; fi
        local _ogc_name
        for _ogc_name in ${_ogc_unset[@]+"${_ogc_unset[@]}"}; do unset "$_ogc_name"; done
        for _ogc_name in ${_ogc_set[@]+"${_ogc_set[@]}"}; do export "$_ogc_name"; done
        if [[ "$_ogc_stderr" == merge ]]; then
            exec 2>&1
        else
            exec 2>>"${_ogc_stderr#append:}"
        fi
        if [[ "$_ogc_have_stdin" -eq 1 ]]; then
            printf '%s' "$_ogc_stdin" | "$@"
        else
            "$@"
        fi
    ) || _ogc_rc=$?
    ONEX_GUARD_RC=$_ogc_rc
    return 0
}

# Write one request: NUL-separated fields, then NAME=VALUE environment entries
# to the end of the file. The environment is computed in a subshell with the
# guard's own unsets, sets and working directory applied, so it is exactly the
# environment the standalone core would have been started with.
_onex_guard_core_collect() {
    local _ogc_req="${ONEX_BASH_GUARDS_REQ:?}.${ONEX_BASH_GUARDS_SLOT:?}.req"
    (
        if [[ -n "$_ogc_cwd" ]]; then cd "$_ogc_cwd" || exit 1; fi
        _ogc_dir="$(pwd -P 2>/dev/null || pwd)"
        for _ogc_name in ${_ogc_unset[@]+"${_ogc_unset[@]}"}; do unset "$_ogc_name"; done
        for _ogc_name in ${_ogc_set[@]+"${_ogc_set[@]}"}; do export "$_ogc_name"; done
        printf '%s\0' "onex-bash-guard-request-v1" "$_ogc_stderr" "$_ogc_dir" \
            "$_ogc_have_stdin" "$_ogc_stdin" "$#" "$@"
        for _ogc_name in $(compgen -e); do
            printf '%s=%s\0' "$_ogc_name" "${!_ogc_name}"
        done
    ) >"$_ogc_req"
}
