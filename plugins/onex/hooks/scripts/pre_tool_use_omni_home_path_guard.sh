#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Doubled registry-root path admission gate (OMN-18607).
#
# $OMNI_HOME IS the omni_home repository root on this fleet. A lane that read
# the old `$OMNI_HOME/CLAUDE.md:169` ("Run from $OMNI_HOME/omni_home (repo
# root)", removed in omni_home#365) created a stray untracked
# $OMNI_HOME/omni_home/ directory, and two lanes wrote scratch output into it
# over three weeks before anyone noticed. It was never git-added, so no
# repo-scoped CI gate could see it. Removing the wrong instruction does not
# stop the next lane typing the doubled segment from stale memory.
#
# This wrapper decides nothing. It pre-filters on the segment name, then hands
# the payload to lib/omni_home_doubled_path_guard.py, which anchors every
# path-shaped word in the call at the resolved $OMNI_HOME and refuses only what
# lands inside $OMNI_HOME/omni_home. Patterned on the OMN-18750 prose guard.
#
# It covers the Bash command line (sourced by pre_tool_use_bash_guards.sh, so
# it starts no process of its own on a Bash call) and the target path of
# Write / Edit / MultiEdit / NotebookEdit (its own registration).
#
# Gate bit: BASH_GUARD (a PreToolUse admission gate in the Bash guard family;
#           it does not mint a new bit).
#   Disable with: onex hooks disable BASH_GUARD

set -euo pipefail

# OMN-19381: named before error-guard.sh is sourced, or every refusal row and
# the per-hook log say unknown-hook.
_OMNICLAUDE_HOOK_NAME="${BASH_SOURCE[0]##*/}"

# error-guard.sh sources hook-gate.sh, which supplies onex_hook_gate and
# _hook_status without common.sh. common.sh is deliberately NOT sourced: its
# find_python() hard-fails with `exit 1` when no venv is present, and the
# error-guard EXIT trap would convert that into `exit 0` -- a silent
# fail-OPEN. The decision core is standard-library-only precisely so this
# guard can resolve an interpreter itself and refuse when it cannot.
#
# Sourcing this is load-bearing, not cosmetic: without onex_hook_gate in
# scope, `if ! onex_hook_gate BASH_GUARD` takes the DISABLED branch on a
# command-not-found, and the guard no-ops on every call while reporting
# nothing -- the exact hook shape OMN-18750 exists to stop shipping.
# shellcheck source=./error-guard.sh
# OMN-20109: this script's directory, resolved once without a dirname exec.
_ONEX_HOOK_SELF_DIR="${BASH_SOURCE[0]%/*}"; [[ "${BASH_SOURCE[0]}" == */* ]] || _ONEX_HOOK_SELF_DIR=.; [[ -n "$_ONEX_HOOK_SELF_DIR" ]] || _ONEX_HOOK_SELF_DIR=/
source "${_ONEX_HOOK_SELF_DIR}/error-guard.sh" 2>/dev/null || true

# Resolve this script's own directory BEFORE any cd: BASH_SOURCE may be
# relative, and resolving it afterwards lands in the wrong tree.
if [[ -L "${BASH_SOURCE[0]}" ]]; then
    _SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
        || python3 -c "import os,sys; p=os.path.realpath(sys.argv[1]); print(p) if os.path.exists(p) else sys.exit(1)" "${BASH_SOURCE[0]}")"
    SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
else
    # OMN-20109: not a symlink, so realpath() of this script is its physical
    # directory plus its name; cd -P resolves that without a realpath exec.
    SCRIPT_DIR="$(CDPATH='' cd -P -- "${_ONEX_HOOK_SELF_DIR}" && pwd -P)"
fi
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
GUARD_PY="${SCRIPT_DIR}/../lib/omni_home_doubled_path_guard.py"
unset _SELF

# The decision depends on the command text alone, never on this script's CWD,
# so a stability cd is safe.
cd "$HOME" 2>/dev/null || cd /tmp || true

_CALLER_HOOK_LOG="${ONEX_HOOK_LOG:-}"
# shellcheck source=./onex-paths.sh
source "${SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${_CALLER_HOOK_LOG:-${ONEX_HOOK_LOG:-${HOME}/.claude/onex-hooks.log}}"
unset _CALLER_HOOK_LOG
[[ -d "${LOG_FILE%/*}" ]] || mkdir -p "${LOG_FILE%/*}" 2>/dev/null || true

_log() {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] omni-home-path-guard: $*" >> "$LOG_FILE" 2>/dev/null || true
}

if ! onex_hook_gate BASH_GUARD; then
    _log "DISABLED: BASH_GUARD is cleared in ONEX_HOOKS_MASK, so this call was not evaluated for a path doubled onto \$OMNI_HOME. Re-enable with: onex hooks enable BASH_GUARD"
    cat >/dev/null
    exit 0
fi

_block() {
    # OMN-18946: a refusal reaches an aggregated surface, not only this
    # turn's terminal and a log nobody reads. Backgrounded and fail-open.
    hook_record_refusal "$1" "$2" 2>/dev/null || true
    _hook_status "BLOCKED" "$1" "0" 2>/dev/null || true
    _log "BLOCKED: $1"
    jq -n --arg reason "$2" '{"decision": "block", "reason": $reason}' 2>/dev/null \
        || printf '{"decision": "block", "reason": %s}\n' "$(printf '%s' "$2" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    trap - EXIT
    exit 2
}

TOOL_INFO=$(cat)
# OMN-19381: the payload the refusal recorder reads the lane from.
_OMNICLAUDE_HOOK_PAYLOAD="$TOOL_INFO"

# Cheap OVER-matching pre-filter. It decides nothing; the decision core
# anchors every candidate at the resolved $OMNI_HOME. It matches only the
# DOUBLED spelling -- the two literal $OMNI_HOME forms, the expanded root
# followed by the segment, and the segment twice over -- because a bare
# `omni_home` appears in the payload of every call whose working directory
# sits inside the registry clone, and that would pay for an interpreter start
# on calls that cannot be refused (tests/hooks_system/test_bash_guards_
# differential.py::test_at_most_one_interpreter_per_call measures it).
_OHP_MATCH=0
case "$TOOL_INFO" in
    *'$OMNI_HOME/omni_home'*|*'${OMNI_HOME}/omni_home'*|*omni_home/omni_home*) _OHP_MATCH=1 ;;
esac
if [[ $_OHP_MATCH -eq 0 && -n "${OMNI_HOME:-}" ]]; then
    case "$TOOL_INFO" in
        *"${OMNI_HOME}/omni_home"*) _OHP_MATCH=1 ;;
    esac
fi
if [[ $_OHP_MATCH -eq 0 ]]; then
    _hook_status "PASS" "no doubled omni_home segment in payload" "0" 2>/dev/null || true
    exit 0
fi

if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null); then
    _block "unparseable hook JSON naming omni_home" \
        "BLOCKED: the PreToolUse payload for this call names omni_home but is not readable JSON, so the guard cannot tell whether it targets a path doubled onto \$OMNI_HOME (OMN-18607). An unverifiable payload is refused, never assumed safe. To disable this guard: onex hooks disable BASH_GUARD"
fi

case "$TOOL_NAME" in
    Bash|Write|Edit|MultiEdit|NotebookEdit) : ;;
    *)
        _hook_status "PASS" "tool carries no path this guard reads ($TOOL_NAME)" "0" 2>/dev/null || true
        exit 0
        ;;
esac

if [[ ! -f "$GUARD_PY" ]]; then
    _block "decision core missing" \
        "BLOCKED: the OMN-18607 doubled-root admission gate is missing at ${GUARD_PY}, so this call's paths cannot be judged. Repair the plugin install, or disable the guard deliberately: onex hooks disable BASH_GUARD"
fi

_resolve_python() {
    if [[ -n "${PLUGIN_PYTHON_BIN:-}" && -x "${PLUGIN_PYTHON_BIN}" ]]; then
        echo "${PLUGIN_PYTHON_BIN}"
        return 0
    fi
    if [[ -n "${CLAUDE_PLUGIN_DATA:-}" && -x "${CLAUDE_PLUGIN_DATA}/.venv/bin/python3" ]]; then
        echo "${CLAUDE_PLUGIN_DATA}/.venv/bin/python3"
        return 0
    fi
    local repo_venv
    repo_venv="$(cd "${PLUGIN_ROOT}/../.." 2>/dev/null && pwd)/.venv/bin/python3"
    if [[ -x "$repo_venv" ]]; then
        echo "$repo_venv"
        return 0
    fi
    local brew_py
    for brew_py in /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13; do  # public-skill-ok: canonical brew interpreter path, CLAUDE.md rule 11 precedent
        if [[ -x "$brew_py" ]]; then
            echo "$brew_py"
            return 0
        fi
    done
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return 0
    fi
    return 1
}

if ! GUARD_PYTHON="$(_resolve_python)"; then
    _block "no python interpreter" \
        "BLOCKED: no Python interpreter could be resolved to run the OMN-18607 doubled-root admission gate, so this call cannot be checked. Repair the plugin install, or disable the guard deliberately: onex hooks disable BASH_GUARD"
fi

# OMN-20118: the decision core runs through onex_guard_core, which runs it in its
# own interpreter when this script runs on its own, and in the one shared
# interpreter when pre_tool_use_bash_guards.sh runs it. A missing runner is
# refused like a missing decision core.
source "${SCRIPT_DIR}/../lib/bash_guard_core.sh" 2>/dev/null || true
if ! declare -F onex_guard_core >/dev/null 2>&1; then
    _block "decision core runner missing" \
        "BLOCKED: the OMN-18607 doubled-root admission gate cannot run its decision core: lib/bash_guard_core.sh is missing beside ${GUARD_PY}. Repair the plugin install, or disable the guard deliberately: onex hooks disable BASH_GUARD"
fi
onex_guard_core --stdin "$TOOL_INFO" --stderr merge --unset PYTHONPATH -- \
    "$GUARD_PYTHON" "$GUARD_PY"
GUARD_OUT="$ONEX_GUARD_OUT"
GUARD_RC="$ONEX_GUARD_RC"

if [[ $GUARD_RC -eq 0 ]]; then
    GUARD_NOTES=$(printf '%s' "$GUARD_OUT" | tail -n 1 \
        | jq -r 'select(type == "object") | .notes // [] | join(" | ")' 2>/dev/null || true)
    if [[ -n "$GUARD_NOTES" ]]; then
        _log "$GUARD_NOTES"
    fi
    _hook_status "PASS" "no path doubled onto \$OMNI_HOME in this call" "0" 2>/dev/null || true
    exit 0
fi

if [[ $GUARD_RC -eq 2 ]]; then
    REASON=$(printf '%s' "$GUARD_OUT" | jq -r '.reason // empty' 2>/dev/null || true)
    if [[ -z "$REASON" ]]; then
        REASON="BLOCKED: this call targets a path doubled onto \$OMNI_HOME, which is already the omni_home repo root (OMN-18607), and the guard's own detail payload was unreadable."
    fi
    _block "path doubled onto \$OMNI_HOME" "$REASON"
fi

_block "guard evaluation failed (rc=${GUARD_RC})" \
    "BLOCKED: the OMN-18607 doubled-root admission gate could not evaluate this call (exit ${GUARD_RC}), so whether it writes into a path doubled onto \$OMNI_HOME is unknown and the call is refused. Detail: $(printf '%s' "$GUARD_OUT" | head -c 400). To disable this guard deliberately: onex hooks disable BASH_GUARD"
