#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Hook adapter for the existing Git effect node admission operation (OMN-20685).
set -euo pipefail
# OMN-20109: this script's directory, resolved once without a dirname exec.
_ONEX_HOOK_SELF_DIR="${BASH_SOURCE[0]%/*}"; [[ "${BASH_SOURCE[0]}" == */* ]] || _ONEX_HOOK_SELF_DIR=.; [[ -n "$_ONEX_HOOK_SELF_DIR" ]] || _ONEX_HOOK_SELF_DIR=/
_OMNICLAUDE_HOOK_NAME="${BASH_SOURCE[0]##*/}"

_OMNICLAUDE_CALLER_CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
# shellcheck source=../lib/repo_guard.sh
. "${_ONEX_HOOK_SELF_DIR}/../lib/repo_guard.sh" 2>/dev/null || true
if declare -F is_omninode_repo >/dev/null 2>&1; then
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$_OMNICLAUDE_CALLER_CWD}" \
        is_omninode_repo || {
        cat >/dev/null
        trap - EXIT 2>/dev/null || true
        exit 0
    }
fi

# error-guard.sh sources hook-gate.sh, which supplies onex_hook_gate without
# common.sh. common.sh is deliberately NOT sourced: its find_python()
# hard-fails with `exit 1` when no venv is present, and the error-guard EXIT
# trap would convert that into `exit 0` -- a silent fail-OPEN. The decision
# core is standard-library-only precisely so this guard can resolve an
# interpreter itself and refuse when it cannot.
# shellcheck source=./error-guard.sh
source "${_ONEX_HOOK_SELF_DIR}/error-guard.sh" 2>/dev/null || true

# Resolve this script's own location BEFORE any `cd`. BASH_SOURCE[0] may be
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
GUARD_MODULE="omniclaude.nodes.node_git_effect.handlers.handler_git_admission"
unset _SELF

# The TOOL_INFO payload (which carries `cwd`) must be captured BEFORE any
# `cd`, and OMNI_HOME must already be set in the caller's environment for the
# decision core to resolve the registry root by path -- neither depends on
# this script's own CWD, so the stability `cd` below is safe.
cd "$HOME" 2>/dev/null || cd /tmp || true

_CALLER_HOOK_LOG="${ONEX_HOOK_LOG:-}"
# shellcheck source=./onex-paths.sh
source "${SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${_CALLER_HOOK_LOG:-${ONEX_HOOK_LOG:-${HOME}/.claude/onex-hooks.log}}"
unset _CALLER_HOOK_LOG
[[ -d "${LOG_FILE%/*}" ]] || mkdir -p "${LOG_FILE%/*}" 2>/dev/null || true

_log() {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] shared-tree-git-guard: $*" >> "$LOG_FILE" 2>/dev/null || true
}

if ! onex_hook_gate SCOPE_GATE; then
    _log "DISABLED: SCOPE_GATE is cleared in ONEX_HOOKS_MASK, so this command was not evaluated for a shared-tree git mutation. Re-enable with: onex hooks enable SCOPE_GATE"
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

# Cheap OVER-matching pre-filter. It decides nothing: anything it lets
# through is decided by the Git effect node admission handler, which tokenises the
# command. A payload naming neither `git` nor any refused verb cannot be a
# refused shape, so it never pays for an interpreter start.
if ! printf '%s' "$TOOL_INFO" | grep -Eqi 'git|gh'; then
    _hook_status "PASS" "no git vocabulary" "0" 2>/dev/null || true
    exit 0
fi
# OMN-20495: the lane git-fetch arm. Fetch vocabulary alone reaches the core
# only with a lane marker in the environment or the payload (the command and
# the cwd), so an orchestrator's or operator's fetch starts no interpreter.
# Bash regex matching: this branch adds no process to any call.
_stg_fetch_vocab='fetch|pull|ls-remote|remote'
_stg_lane_marker='omni_worktrees|lab-run|ONEX_WORKTREES_ROOT'
if ! printf '%s' "$TOOL_INFO" | grep -Eqi 'reset|checkout|switch|clean|rebase|branch|merge|push|restore'; then
    if ! [[ "$TOOL_INFO" =~ $_stg_fetch_vocab ]] \
        || { [[ -z "${ONEX_LANE:-}${ONEX_LANE_ID:-}" ]] && ! [[ "$TOOL_INFO" =~ $_stg_lane_marker ]]; }; then
        _hook_status "PASS" "no refused git verb" "0" 2>/dev/null || true
        exit 0
    fi
fi

if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null); then
    _block "unparseable hook JSON naming a refused git verb" \
        "BLOCKED: the PreToolUse payload for this Bash call names git together with a verb refused in the shared registry clone at $OMNI_HOME, but is not readable JSON, so the guard cannot tell whether it moves the tree every other lane is working in (OMN-18798, Operating Rule 19). An unverifiable shared-tree mutation is refused, never assumed safe. To disable this guard: onex hooks disable SCOPE_GATE"
fi

if [[ "$TOOL_NAME" != "Bash" ]]; then
    _hook_status "PASS" "not a Bash call ($TOOL_NAME)" "0" 2>/dev/null || true
    exit 0
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
        "BLOCKED: no Python interpreter could be resolved to run the OMN-18798 shared-tree git admission gate, so this command cannot be checked. Repair the plugin install, or disable the guard deliberately: onex hooks disable SCOPE_GATE"
fi

# OMN-20118: the decision core runs through onex_guard_core, which runs it in its
# own interpreter when this script runs on its own, and in the one shared
# interpreter when pre_tool_use_bash_guards.sh runs it. A missing runner is
# refused like a missing decision core.
source "${SCRIPT_DIR}/../lib/bash_guard_core.sh" 2>/dev/null || true
if ! declare -F onex_guard_core >/dev/null 2>&1; then
    _block "decision core runner missing" \
        "BLOCKED: the OMN-18798 shared-tree git admission gate cannot run its decision core: lib/bash_guard_core.sh is missing beside ${GUARD_MODULE}. Repair the plugin install, or disable the guard deliberately: onex hooks disable SCOPE_GATE"
fi
onex_guard_core --stdin "$TOOL_INFO" --stderr merge --unset PYTHONPATH -- \
    "$GUARD_PYTHON" -m "$GUARD_MODULE" --clone-sync-engine "${SCRIPT_DIR}/../lib/canonical_clone_sync.py"
GUARD_OUT="$ONEX_GUARD_OUT"
GUARD_RC="$ONEX_GUARD_RC"

if [[ $GUARD_RC -eq 0 ]]; then
    GUARD_NOTES=$(printf '%s' "$GUARD_OUT" | tail -n 1 \
        | jq -r 'select(type == "object") | .notes // [] | join(" | ")' 2>/dev/null || true)
    if [[ -n "$GUARD_NOTES" ]]; then
        _log "$GUARD_NOTES"
    fi
    _hook_status "PASS" "no unauthorised shared-tree git mutation in this command" "0" 2>/dev/null || true
    exit 0
fi

if [[ $GUARD_RC -eq 2 ]]; then
    REASON=$(printf '%s' "$GUARD_OUT" | jq -r '.reason // empty' 2>/dev/null || true)
    if [[ -z "$REASON" ]]; then
        REASON="BLOCKED: this command moves the shared registry clone at $OMNI_HOME that every concurrent lane works in (OMN-18798, Operating Rule 19), and the guard's own detail payload was unreadable."
    fi
    _block "unauthorised shared-tree git mutation" "$REASON"
fi

_block "guard evaluation failed (rc=${GUARD_RC})" \
    "BLOCKED: the OMN-18798 shared-tree git admission gate could not evaluate this Bash command (exit ${GUARD_RC}), so whether it moves the shared registry clone at $OMNI_HOME is unknown and the command is refused. Detail: $(printf '%s' "$GUARD_OUT" | head -c 400). To disable this guard deliberately: onex hooks disable SCOPE_GATE"
