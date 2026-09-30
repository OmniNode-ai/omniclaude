#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Bash guards, one entrypoint, one interpreter (OMN-20118)
# ===================================================================
# The ONE registration on the PreToolUse Bash matcher for the seven Bash
# guards, in their former registration order:
#
#   pre_tool_use_worktree_guard.sh                  (OMN-14330, WORKTREE_GUARD)
#   pre_tool_use_pr_ownership_guard.sh              (OMN-16485, BASH_GUARD)
#   pre_tool_use_credential_rotation_guard.sh       (OMN-17957, PRE_TOOL_AUTHORIZATION_SHIM)
#   pre_tool_use_git_stash_guard.sh                 (OMN-17334, SWEEP_PREFLIGHT)
#   pre_tool_use_shared_tree_git_guard.sh           (OMN-18798, SCOPE_GATE)
#   pre_tool_use_pr_body_stamp_guard.sh             (OMN-18335, BRANCH_PROTECTION_GUARD)
#   pre_tool_use_prose_command_substitution_guard.sh (OMN-18750, BASH_GUARD)
#
# Why. Each was its own registered hook: seven bash processes per Bash tool
# call, and each guard whose pre-filter matched started its own Python
# interpreter. After OMN-20114 cut the per-call execs, interpreter starts were
# what was left of the wall time (0.2 to 0.85 s each on the operator Mac idle,
# 5 to 8 s under contention). Now a Bash call costs one bash process for all
# seven guards and at most ONE interpreter start, and a call that trips no
# pre-filter still starts none.
#
# How, in three passes, without changing any guard's decision:
#
#   1. collect  Each guard script is SOURCED in its own subshell, with the hook
#               payload on its stdin, exactly as its own process ran it. A guard
#               that allows, refuses or is disabled before it needs Python ends
#               there with its own result. A guard that needs its decision core
#               writes a request (lib/bash_guard_core.sh) and ends.
#   2. run      One interpreter (lib/bash_guard_cores.py) runs every request, each
#               core as a function, each with the argv, stdin, working
#               directory and full environment its guard would have given it.
#   3. replay   Each guard that asked is sourced again; this time its core call
#               returns the recorded result, and the guard's own
#               post-processing makes its decision and writes its own refusal.
#
# Fail-closed boundary. A guard whose request got no result (the interpreter
# could not be resolved or started, or died) sees its core exit non-zero with
# the diagnosis as output, and takes its own evaluation-failed branch: it
# refuses, fail-closed, with its own message, as it did when its own
# interpreter failed.
#
# Output. A refusal is exit 2 and the refusing guard's own JSON on stdout,
# byte for byte. When several guards refuse, one JSON carries every reason, in
# guard order. When no guard refuses, this prints nothing and exits 0 (two of
# the seven echoed the payload back on a pass, which Claude Code ignores). A
# guard's stderr reaches the harness unchanged.
#
# The per-guard scripts stay on disk and still run on their own (the per-guard
# unit tests run them that way). tests/hooks_system/test_bash_guards_differential.py
# proves every decision identical to the seven separate hooks.
#
# Bash 3.2 compatible: this runs under /bin/bash on macOS.

set -uo pipefail

_OBG_SELF_DIR="${BASH_SOURCE[0]%/*}"; [[ "${BASH_SOURCE[0]}" == */* ]] || _OBG_SELF_DIR=.; [[ -n "$_OBG_SELF_DIR" ]] || _OBG_SELF_DIR=/
_OBG_SCRIPTS="$(CDPATH='' cd -P -- "$_OBG_SELF_DIR" && pwd -P)"
_OBG_LIB="${_OBG_SCRIPTS}/../lib"
_OBG_GUARDS=(
    "${_OBG_SCRIPTS}/pre_tool_use_worktree_guard.sh"
    "${_OBG_SCRIPTS}/pre_tool_use_pr_ownership_guard.sh"
    "${_OBG_SCRIPTS}/pre_tool_use_credential_rotation_guard.sh"
    "${_OBG_SCRIPTS}/pre_tool_use_git_stash_guard.sh"
    "${_OBG_SCRIPTS}/pre_tool_use_shared_tree_git_guard.sh"
    "${_OBG_SCRIPTS}/pre_tool_use_pr_body_stamp_guard.sh"
    "${_OBG_SCRIPTS}/pre_tool_use_prose_command_substitution_guard.sh"
)

# The payload, read without an exec. $(cat) strips trailing newlines; so does this.
_OBG_INPUT=""
IFS= read -r -d '' _OBG_INPUT || true
while [[ "$_OBG_INPUT" == *$'\n' ]]; do _OBG_INPUT="${_OBG_INPUT%$'\n'}"; done

# shellcheck source=../lib/bash_guard_core.sh
source "${_OBG_LIB}/bash_guard_core.sh"

ONEX_BASH_GUARDS_REQ="${TMPDIR:-/tmp}"
ONEX_BASH_GUARDS_REQ="${ONEX_BASH_GUARDS_REQ%/}/onex-bash-guards.$$.${RANDOM}${RANDOM}"

_obg_run_guard() {
    # $1 slot. Runs the guard script as its own process ran it: a subshell,
    # the payload on stdin, the caller's working directory and environment.
    local _obg_script="${_OBG_GUARDS[$1]}"
    ONEX_BASH_GUARDS_SLOT="$1"
    _OBG_OUT="$(source "$_obg_script" <<<"$_OBG_INPUT")"
    _OBG_RC=$?
}

# --- Pass 1: collect ---------------------------------------------------------
_OBG_NEED=()
ONEX_BASH_GUARDS_PHASE=collect
_obg_i=0
while [[ $_obg_i -lt ${#_OBG_GUARDS[@]} ]]; do
    _obg_run_guard "$_obg_i"
    if [[ $_OBG_RC -eq $ONEX_BASH_GUARDS_COLLECTED && -f "${ONEX_BASH_GUARDS_REQ}.${_obg_i}.req" ]]; then
        _OBG_NEED+=("$_obg_i")
    else
        printf -v "_OBG_FINAL_RC_${_obg_i}" '%s' "$_OBG_RC"
        printf -v "_OBG_FINAL_OUT_${_obg_i}" '%s' "$_OBG_OUT"
    fi
    _obg_i=$((_obg_i + 1))
done

# --- Pass 2: one interpreter for every decision core ---------------------------
if [[ ${#_OBG_NEED[@]} -gt 0 ]]; then
    # The interpreter the first requesting guard resolved for its own core:
    # every guard resolves one the same way it always did, and the request
    # records it as argv[0].
    # Fields: magic, stderr mode, cwd, has-stdin, stdin, argc, argv[0].
    _OBG_PY=""
    {
        IFS= read -r -d '' _obg_f; IFS= read -r -d '' _obg_f; IFS= read -r -d '' _obg_f
        IFS= read -r -d '' _obg_f; IFS= read -r -d '' _obg_f; IFS= read -r -d '' _obg_f
        IFS= read -r -d '' _OBG_PY
    } < "${ONEX_BASH_GUARDS_REQ}.${_OBG_NEED[0]}.req" || true
    if [[ -z "$_OBG_PY" ]]; then
        ONEX_BASH_GUARDS_FAILURE="the shared Bash guard interpreter could not be resolved from the guard's request (OMN-20118)"
    else
        while IFS= read -r -d '' _obg_slot && IFS= read -r -d '' _obg_rc \
            && IFS= read -r -d '' _obg_out; do
            [[ "$_obg_slot" =~ ^[0-9]+$ ]] || continue
            printf -v "ONEX_BASH_GUARDS_RC_${_obg_slot}" '%s' "$_obg_rc"
            printf -v "ONEX_BASH_GUARDS_OUT_${_obg_slot}" '%s' "$_obg_out"
        done < <(
            cd "$HOME" 2>/dev/null || cd /tmp || true
            unset PYTHONPATH
            "$_OBG_PY" "${_OBG_LIB}/bash_guard_cores.py" "$ONEX_BASH_GUARDS_REQ" "${_OBG_NEED[@]}" 3>&1 1>&2
        )
        ONEX_BASH_GUARDS_FAILURE="the shared Bash guard interpreter ${_OBG_PY} returned no result for this guard (OMN-20118)"
    fi

    # --- Pass 3: replay ----------------------------------------------------------
    ONEX_BASH_GUARDS_PHASE=replay
    for _obg_i in "${_OBG_NEED[@]}"; do
        _obg_run_guard "$_obg_i"
        printf -v "_OBG_FINAL_RC_${_obg_i}" '%s' "$_OBG_RC"
        printf -v "_OBG_FINAL_OUT_${_obg_i}" '%s' "$_OBG_OUT"
    done

    # Whatever of a request is still on disk goes now: a request the
    # interpreter never read (it did not start), or a command file a refusing
    # guard left behind (its exit clears the trap that would remove it).
    for _obg_i in "${_OBG_NEED[@]}"; do
        if [[ -f "${ONEX_BASH_GUARDS_REQ}.${_obg_i}.req" || -f "${ONEX_BASH_GUARDS_REQ}.${_obg_i}.cmd" ]]; then
            rm -f "${ONEX_BASH_GUARDS_REQ}.${_obg_i}.req" "${ONEX_BASH_GUARDS_REQ}.${_obg_i}.cmd" 2>/dev/null || true
        fi
    done
fi
unset ONEX_BASH_GUARDS_PHASE

# --- The decision ------------------------------------------------------------
_OBG_BLOCKS=()
_OBG_OTHER_RC=0
_OBG_OTHER_OUT=""
_obg_i=0
while [[ $_obg_i -lt ${#_OBG_GUARDS[@]} ]]; do
    _obg_rc_var="_OBG_FINAL_RC_${_obg_i}"
    _obg_out_var="_OBG_FINAL_OUT_${_obg_i}"
    if [[ "${!_obg_rc_var}" -eq 2 ]]; then
        _OBG_BLOCKS+=("$_obg_i")
    elif [[ "${!_obg_rc_var}" -ne 0 && $_OBG_OTHER_RC -eq 0 ]]; then
        _OBG_OTHER_RC="${!_obg_rc_var}"
        _OBG_OTHER_OUT="${!_obg_out_var}"
    fi
    _obg_i=$((_obg_i + 1))
done

if [[ ${#_OBG_BLOCKS[@]} -eq 1 ]]; then
    _obg_out_var="_OBG_FINAL_OUT_${_OBG_BLOCKS[0]}"
    printf '%s\n' "${!_obg_out_var}"
    exit 2
fi
if [[ ${#_OBG_BLOCKS[@]} -gt 1 ]]; then
    # Several refusals: every reason, in guard order, in one block decision.
    _obg_args=()
    for _obg_i in "${_OBG_BLOCKS[@]}"; do
        _obg_out_var="_OBG_FINAL_OUT_${_obg_i}"
        _obg_args+=("${!_obg_out_var}")
    done
    jq -sc '{"decision": "block", "reason": ([.[] | (.reason // tostring)] | join("\n\n"))}' \
        <<<"$(printf '%s\n' "${_obg_args[@]}")" 2>/dev/null \
        || printf '{"decision": "block", "reason": "BLOCKED: %s Bash guards refused this command (OMN-20118); their reasons could not be combined."}\n' "${#_OBG_BLOCKS[@]}"
    exit 2
fi
if [[ $_OBG_OTHER_RC -ne 0 ]]; then
    [[ -n "$_OBG_OTHER_OUT" ]] && printf '%s\n' "$_OBG_OTHER_OUT"
    exit "$_OBG_OTHER_RC"
fi
exit 0
