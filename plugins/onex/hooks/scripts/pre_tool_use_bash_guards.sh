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
#               payload on its stdin, exactly as its own process ran it. The
#               seven run concurrently, as the seven registered hooks did. A guard
#               that allows, refuses or is disabled before it needs Python ends
#               there with its own result. A guard that needs its decision core
#               writes a request (lib/bash_guard_core.sh) and ends.
#   2. run      One interpreter (lib/bash_guard_cores.py) runs every request, each
#               core as a function, each with the argv, stdin, working
#               directory and full environment its guard would have given it.
#   3. replay   Each guard that asked is sourced again, concurrently; its core call
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

# --- Lane GitHub read check (OMN-20916) ----------------------------------------
# RULING 2026-10-10T18:17:36Z: lanes must not be able to read GitHub at all. The gh
# shim refuses a lane's gh reads; omniclaude's node_lane_github_read_guard_effect
# refuses the three paths around it: a GitHub MCP read tool, a direct call to
# api.github.com, and the real gh binary run by its path. Who is a lane, what is a
# read and the refusal text are all the node's; this block only decides whether
# the call could be one of the three, without an exec, and hands it over.
#
# This entrypoint is also registered on the GitHub MCP tools (its matcher is
# ^(Bash|mcp__.*[Gg]it[Hh]ub.*)$). A GitHub MCP call runs this check alone and
# never the seven Bash guards below, which judge Bash commands only.
#
# Fail-closed: a call that trips the pre-filter and cannot be judged (no
# interpreter, the node not importable, an unreadable payload) is refused, as every
# guard here refuses a call it cannot evaluate. A Bash command naming none of
# api.github.com or a /gh path starts no interpreter.
#
# Every refusal here writes one class=refusal row through the refusal recorder
# (OMN-21020). The node checks run ahead of the seven guards, so none of their
# hook_record_refusal calls can see them; the recording is the recorder's seam,
# called from a subshell so the guard name and the payload stay out of this
# shell's scope. $1 hook name, $2 reason class, $3 the refusal's text (its first
# line becomes the detail).
_obg_record_refusal() {
    # shellcheck source=../lib/hook_refusal.sh
    _OMNICLAUDE_HOOK_NAME="$1" _OMNICLAUDE_HOOK_PAYLOAD="$_OBG_INPUT" bash -c 'source "$1/hook_refusal.sh" && hook_record_refusal "$2" "$3"' _ "$_OBG_LIB" "$2" "${3%%$'\n'*}" || true
}

# One node check: `python -m` the node's runtime module ($2) on the payload. Exit 0
# passes; exit 2 prints the node's block JSON and refuses; anything else refuses
# fail-closed. $1 hook name, $3 the check's name for the could-not-judge text, $4
# that refusal's class. A node refusal's class is the bypass path the node judged,
# named by its own text.
_obg_node_check() {
    local out rc reason class why
    out="$(
        # The session mode goes to the node, which refuses nothing in lite mode (a
        # non-OmniNode install). This entrypoint itself never exits on it.
        _OBG_MODE="full"
        # shellcheck source=/dev/null
        [[ -f "${_OBG_SCRIPTS}/../../lib/mode.sh" ]] && source "${_OBG_SCRIPTS}/../../lib/mode.sh" && _OBG_MODE="$(omniclaude_mode)"
        cd "$HOME" 2>/dev/null || cd /tmp || true
        # shellcheck source=common.sh
        source "${_OBG_SCRIPTS}/common.sh" >/dev/null 2>&1 || exit 1
        unset PYTHONPATH
        printf '%s\n' "$_OBG_INPUT" | "${PYTHON_CMD:-python3}" -m "$2" \
            --cwd "$_OBG_CALLER_CWD" --mode "$_OBG_MODE" 2>&1
    )"
    rc=$?
    [[ $rc -eq 0 ]] && return 0
    if [[ $rc -eq 2 ]]; then
        printf '%s\n' "$out"
        reason="$(printf '%s\n' "$out" | jq -r '.reason // empty' 2>/dev/null || true)"
        [[ -n "$reason" ]] && printf '%s\n' "$reason" >&2
        case "$1:$reason" in
            *dev_runtime*) class="dev-runtime-mutation" ;;
            *"GitHub MCP tool"*) class="lane-github-read-mcp-tool" ;;
            *"direct call to the GitHub API"*) class="lane-github-read-raw-api" ;;
            *) class="lane-github-read-real-gh" ;;
        esac
        _obg_record_refusal "$1" "$class" "$reason"
        exit 2
    fi
    why="BLOCKED: the $3 check could not judge this call (exit ${rc})"
    _obg_record_refusal "$1" "$4" "$why"
    jq -nc --arg r "${why}. A call it cannot judge is refused, never assumed safe. Detail: ${out:0:400}" '{"decision": "block", "reason": $r}' 2>/dev/null \
        || printf '{"decision": "block", "reason": "%s."}\n' "$why"
    printf '%s\n' "${why}. Detail: ${out:0:400}" >&2
    exit 2
}

_OBG_TOOL=""
[[ "$_OBG_INPUT" =~ \"tool_name\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]] && _OBG_TOOL="${BASH_REMATCH[1]}"
_obg_lane_read=0
if [[ "$_OBG_TOOL" == mcp__* ]]; then
    _obg_lane_read=1
elif [[ "$_OBG_INPUT" =~ [Aa][Pp][Ii]\.[Gg][Ii][Tt][Hh][Uu][Bb]\.[Cc][Oo][Mm] \
        || "$_OBG_INPUT" =~ [Uu][Pp][Ll][Oo][Aa][Dd][Ss]\.[Gg][Ii][Tt][Hh][Uu][Bb]\.[Cc][Oo][Mm] \
        || "$_OBG_INPUT" =~ /gh([^A-Za-z0-9_.-]|$) ]]; then
    _obg_lane_read=1
fi
_OBG_CALLER_CWD="$PWD"
if [[ $_obg_lane_read -eq 1 ]]; then
    _obg_node_check pre_tool_use_lane_github_read_guard omniclaude.nodes.node_lane_github_read_guard_effect.runtime_lane_github_read \
        "OMN-20916 lane GitHub read" lane-github-read-check-could-not-judge
fi
# A GitHub MCP call is not a Bash command: the seven guards below never see it.
[[ "$_OBG_TOOL" == mcp__* ]] && exit 0

# --- Dev runtime mutation check (OMN-21795) ------------------------------------
# Operator, 2026-10-31: dev runtime containers are recreated only by a deployment
# or under a grant. omnimarket's node_dev_runtime_mutation_guard_effect refuses a
# docker or docker compose command that would recreate, remove, stop or restart a
# container of a protected compose project (declared in its contract, extended by
# its deployment overlay) unless a live grant row on the ledger names the project.
# This block only decides, without an exec, whether the command names docker and a
# lifecycle verb; every other command starts no interpreter. Fail-closed as above.
_OBG_DOCKER_VERB='(^|[^A-Za-z0-9_-])(up|down|rm|restart|stop|kill|start|create|pause|unpause|rename|update|scale)([^A-Za-z0-9_-]|$)'
if [[ "$_OBG_TOOL" == "Bash" && "$_OBG_INPUT" == *docker* && "$_OBG_INPUT" =~ $_OBG_DOCKER_VERB ]]; then
    _obg_node_check pre_tool_use_dev_runtime_mutation_guard omnimarket.nodes.node_dev_runtime_mutation_guard_effect.runtime_dev_runtime_mutation \
        "OMN-21795 dev runtime mutation" dev-runtime-mutation-check-could-not-judge
fi

# shellcheck source=../lib/bash_guard_core.sh
source "${_OBG_LIB}/bash_guard_core.sh"

# The guards' shared log directory (onex-paths.sh's ONEX_LOG_DIR), made once
# before they start concurrently. Otherwise every guard that looks before the
# first one creates it races to mkdir it too, and how many do depends on how
# slow the machine is: more execs per call on a loaded runner.
# A user outside our workspace has neither OMNI_HOME nor ONEX_STATE_DIR: the state
# directory is then the per-user XDG one, the same order onex-paths.sh uses
# (OMN-16632). Exported so the guards sourced below resolve the same directory.
if [[ -z "${ONEX_STATE_DIR:-}" && -z "${OMNI_HOME:-}" ]]; then
    if [[ "${XDG_STATE_HOME:-}" == /* ]]; then
        export ONEX_STATE_DIR="${XDG_STATE_HOME}/omniclaude"
        export ONEX_STATE_DIR_DEFAULTED=1
    elif [[ "${HOME:-}" == /* ]]; then
        export ONEX_STATE_DIR="${HOME}/.local/state/omniclaude"
        export ONEX_STATE_DIR_DEFAULTED=1
    fi
fi
if [[ ( -z "${ONEX_STATE_DIR:-}" && "${OMNI_HOME:-}" != /* ) ||
      ( -n "${ONEX_STATE_DIR:-}" && "$ONEX_STATE_DIR" != /* ) ]]; then
    printf '%s\n' 'onex-paths: set an absolute OMNI_HOME or ONEX_STATE_DIR for the refusal log' >&2
    printf '%s\n' '{"decision":"block","reason":"OMN-18983: refusal log path is unresolved; set an absolute OMNI_HOME or ONEX_STATE_DIR"}'
    exit 2
fi
_OBG_LOG_DIR="${ONEX_STATE_DIR:-${OMNI_HOME}/.onex_state}/hooks/logs"
[[ -d "$_OBG_LOG_DIR" ]] || mkdir -p "$_OBG_LOG_DIR" 2>/dev/null || true

ONEX_BASH_GUARDS_REQ="${TMPDIR:-/tmp}"
ONEX_BASH_GUARDS_REQ="${ONEX_BASH_GUARDS_REQ%/}/onex-bash-guards.$$.${RANDOM}${RANDOM}"

_obg_job() {
    # $1 slot, $2 phase. Runs the guard script as its own process ran it: a
    # subshell, the payload on stdin, the caller's working directory and
    # environment. Prints the guard's exit status, a NUL, then its stdout.
    ONEX_BASH_GUARDS_SLOT="$1"
    ONEX_BASH_GUARDS_PHASE="$2"
    local _obg_out _obg_rc
    _obg_out="$(source "${_OBG_GUARDS[$1]}" < <(printf '%s\n' "$_OBG_INPUT"))"
    _obg_rc=$?
    printf '%s\0%s' "$_obg_rc" "$_obg_out"
}

_obg_run_guards() {
    # $1 phase, then the slots. The guards run CONCURRENTLY, as the seven
    # registered hooks did: each is a process substitution on its own file
    # descriptor (3, 4, ...; no temporary file, so an unwritable TMPDIR cannot
    # lose a result), and the results are read back in slot order into
    # _OBG_RC_<slot> and _OBG_OUT_<slot>. A job whose status cannot be read
    # (it died) reads as 70, which no guard's caller treats as an allow.
    local _obg_phase="$1" _obg_fd=3 _obg_slot _obg_r _obg_o
    shift
    for _obg_slot in "$@"; do
        eval "exec ${_obg_fd}< <(_obg_job \"\$_obg_slot\" \"\$_obg_phase\")"
        _obg_fd=$((_obg_fd + 1))
    done
    _obg_fd=3
    for _obg_slot in "$@"; do
        _obg_r=""
        _obg_o=""
        IFS= read -r -d '' _obg_r <&"$_obg_fd" || true
        IFS= read -r -d '' _obg_o <&"$_obg_fd" || true
        eval "exec ${_obg_fd}<&-"
        [[ "$_obg_r" =~ ^[0-9]+$ ]] || _obg_r=70
        printf -v "_OBG_RC_${_obg_slot}" '%s' "$_obg_r"
        printf -v "_OBG_OUT_${_obg_slot}" '%s' "$_obg_o"
        _obg_fd=$((_obg_fd + 1))
    done
}

# --- Pass 1: collect ---------------------------------------------------------
_OBG_NEED=()
_OBG_ALL=()
_obg_i=0
while [[ $_obg_i -lt ${#_OBG_GUARDS[@]} ]]; do
    _OBG_ALL+=("$_obg_i")
    _obg_i=$((_obg_i + 1))
done
_obg_run_guards collect "${_OBG_ALL[@]}"
for _obg_i in "${_OBG_ALL[@]}"; do
    _obg_rc_var="_OBG_RC_${_obg_i}"
    _obg_out_var="_OBG_OUT_${_obg_i}"
    _OBG_RC="${!_obg_rc_var}"
    _OBG_OUT="${!_obg_out_var}"
    if [[ $_OBG_RC -eq $ONEX_BASH_GUARDS_COLLECTED ]]; then
        # Asked for its core. A request that could not be written (TMPDIR full
        # or unwritable) is still a guard that needs its core: the run pass
        # reports it unreadable, and the replay refuses fail-closed, rather
        # than letting exit 99 through as a non-blocking hook error.
        _OBG_NEED+=("$_obg_i")
    else
        printf -v "_OBG_FINAL_RC_${_obg_i}" '%s' "$_OBG_RC"
        printf -v "_OBG_FINAL_OUT_${_obg_i}" '%s' "$_OBG_OUT"
    fi
done

# --- Pass 2: one interpreter for every decision core ---------------------------
if [[ ${#_OBG_NEED[@]} -gt 0 ]]; then
    # The interpreter the first readable request's guard resolved for its core:
    # every guard resolves one the same way it always did, and the request
    # records it as argv[0].
    # Fields: magic, stderr mode, cwd, has-stdin, stdin, argc, argv[0].
    _OBG_PY=""
    for _obg_i in "${_OBG_NEED[@]}"; do
        [[ -f "${ONEX_BASH_GUARDS_REQ}.${_obg_i}.req" ]] || continue
        {
            IFS= read -r -d '' _obg_f; IFS= read -r -d '' _obg_f; IFS= read -r -d '' _obg_f
            IFS= read -r -d '' _obg_f; IFS= read -r -d '' _obg_f; IFS= read -r -d '' _obg_f
            IFS= read -r -d '' _OBG_PY
        } < "${ONEX_BASH_GUARDS_REQ}.${_obg_i}.req" || true
        [[ -n "$_OBG_PY" ]] && break
    done
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
    _obg_run_guards replay "${_OBG_NEED[@]}"
    for _obg_i in "${_OBG_NEED[@]}"; do
        _obg_rc_var="_OBG_RC_${_obg_i}"
        _obg_out_var="_OBG_OUT_${_obg_i}"
        printf -v "_OBG_FINAL_RC_${_obg_i}" '%s' "${!_obg_rc_var}"
        printf -v "_OBG_FINAL_OUT_${_obg_i}" '%s' "${!_obg_out_var}"
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
        < <(printf '%s\n' "${_obg_args[@]}") 2>/dev/null \
        || printf '{"decision": "block", "reason": "BLOCKED: %s Bash guards refused this command (OMN-20118); their reasons could not be combined."}\n' "${#_OBG_BLOCKS[@]}"
    exit 2
fi
if [[ $_OBG_OTHER_RC -ne 0 ]]; then
    [[ -n "$_OBG_OTHER_OUT" ]] && printf '%s\n' "$_OBG_OTHER_OUT"
    exit "$_OBG_OTHER_RC"
fi
exit 0
