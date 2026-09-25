#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Pull-Request Body Stamp-Preservation Gate (OMN-18335)
# =================================================================
# Refuses a Bash command that REPLACES a pull request's description when the
# replacement text omits a change-control evidence-source line the live
# description currently carries, and prints the dropped line verbatim so the
# remedy is one paste.
#
# Why a hook and not a validator
# ------------------------------
# The mechanical-closeout plan of record measured it: a pull-request
# description is a surface a lane overwrites wholesale, with no
# compare-and-swap, and it silently lost the evidence-source line on four of
# the last five misses -- twice after the pull request had already merged. One
# lost line makes every downstream reader conclude no evidence exists.
#
# By the time any CI job reads the body, the line is already gone, so a
# repository gate can only observe the loss after the fact. The tool seam is
# the only place it is observable BEFORE it happens. That is the same argument,
# and the same primitive, as pre_tool_use_credential_rotation_guard.sh
# (OMN-17957), pre_tool_use_agent_model_guard.sh (OMN-17499) and
# pre_tool_use_ticket_creation_gate.sh (OMN-17942): it REFUSES the tool call.
#
# The sibling ticket (OMN-18334) repairs the loss after the fact by
# re-asserting the line. The two are deliberately independent and neither
# claims the other's coverage: this one cannot see an edit made in the web
# interface or by another session, and that one cannot help where no workflow
# run follows the edit at all.
#
# Reads are never gated -- and they are not allowlisted either, they simply
# match no configured shape, because every shape names only body-REPLACING
# flags. `gh pr view --json body`, `gh pr list`, a bare `gh api` read, `gh pr
# comment --body` and `gh pr edit --add-label` are outside the vocabulary. The
# guard's own live read is `gh pr view --json body`, which is outside every
# shape, so it can never recurse into itself.
#
# Fail-open / fail-closed boundary, stated deliberately
# -----------------------------------------------------
#   * A command naming no body-replacing flag never invokes Python at all. The
#     grep below is a cheap OVER-matcher that decides nothing; it fires on any
#     command mentioning a body flag, including quoted text that merely names
#     one. A bug in this guard can never brick unrelated Bash traffic.
#   * A payload that DOES carry the vocabulary and cannot then be evaluated --
#     unparseable hook JSON, a missing decision core, an unresolvable
#     interpreter, an unreadable policy, an untokenisable command, an
#     unreadable replacement body, or a live read that FAILED -- is BLOCKED. A
#     read that failed is evidence of nothing and must never be converted into
#     evidence that there was no stamp (the workspace CLAUDE.md rule 16).
#   * pr_body_stamp_guard.py is the authority, not the grep. It tokenises each
#     shell segment and matches by program plus tokens, so `echo 'gh pr edit 42
#     --body ...'` trips the pre-filter and is then ALLOWED. Conflating the two
#     layers is the OMN-16983 defect that refused every `gh api` read on this
#     host.
#
# What this cannot do, stated rather than implied
# -----------------------------------------------
# It sees one seam: a Bash command in this session. An edit made in the web
# interface, by another session, or by a workflow is invisible to it. What it
# removes is the *silent* local case -- a replacement body composed in a
# session and sent without the line the live body carries.
#
# Gating: the BRANCH_PROTECTION_GUARD bit. A dedicated bit is unavailable --
# EnumHookBit lives in omnibase_core, all 60 default-mask ordinals are
# allocated (60-62 are the disabled-by-default trio, and
# knowledge-base-internal reference/hook-bitmask-bit-governance.md rule 7
# forbids ordinal 63 outright), so minting one is a cross-repo release chain
# plus an architecture review. Same constraint and same resolution
# pre_tool_use_credential_rotation_guard.sh recorded for
# PRE_TOOL_AUTHORIZATION_SHIM and pre_tool_use_pr_ownership_guard.sh recorded
# for BASH_GUARD.
#
# BRANCH_PROTECTION_GUARD is the faithful borrow and not an arbitrary one: its
# namesake pre_tool_use_branch_protection_guard.sh is a PreToolUse Bash-matcher
# guard over GitHub-mutating commands, it is on disk and UNREGISTERED under the
# OMN-13244 baseline, and no other registered script gates on it -- so `onex
# hooks disable BRANCH_PROTECTION_GUARD` disables exactly this guard and
# nothing else that is live. PRE_TOOL_AUTHORIZATION_SHIM and BASH_GUARD were
# NOT candidates: each is already borrowed by a live guard, and two independent
# controls behind one switch means disabling either silently disables both.
# tests/hooks/test_pr_body_stamp_guard.py pins the borrow: re-registering the
# namesake turns the suite red rather than quietly sharing the switch.
#   Disable with: onex hooks disable BRANCH_PROTECTION_GUARD
#
# A disabled run is LOGGED, not silent. The OMN-13244 history is a hook going
# dark with no repo-visible signal for months; a bare `|| exit 0` here would
# reproduce that one mask edit at a time.
#
# Registration is LAST on the PreToolUse Bash matcher, after
# pre_tool_use_credential_rotation_guard.sh: that guard never inspects a
# pull-request body and this one never inspects a credential shape, so the two
# never contend for the same call, and the cheaper pre-filter runs first.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"

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

# error-guard.sh also sources hook-gate.sh, which supplies onex_hook_gate
# without common.sh. common.sh is deliberately NOT sourced: its find_python()
# hard-fails with `exit 1` when no venv is present, and the error-guard EXIT
# trap would convert that into `exit 0` -- a silent fail-OPEN, which is the
# OMN-8928 shape this plugin's own canary harness exists to catch. The decision
# core is standard-library-only precisely so this guard can resolve an
# interpreter itself and refuse when it cannot.
# shellcheck source=./error-guard.sh
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Resolve this script's own location BEFORE any `cd`. BASH_SOURCE[0] may be
# relative, and resolving it afterwards lands in the wrong tree.
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; p=os.path.realpath(sys.argv[1]); print(p) if os.path.exists(p) else sys.exit(1)" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
GUARD_PY="${SCRIPT_DIR}/../lib/pr_body_stamp_guard.py"
unset _SELF

# Stable CWD before any Python invocation: the session CWD may live on an
# external volume that disconnects, and CPython aborts at startup when
# os.getcwd() fails. The caller's own directory still reaches the decision core
# -- it arrives in the hook payload's `cwd` field, which is what the live read
# uses to resolve a selector-less edit.
cd "$HOME" 2>/dev/null || cd /tmp || true

# onex-paths.sh EXPORTS ONEX_HOOK_LOG unconditionally, clobbering a value the
# caller set. Capture the caller's first and prefer it: an explicitly supplied
# log path is a deliberate instruction, and a harness that cannot redirect this
# log cannot assert that a disabled run leaves a trace -- which is the whole
# point of logging the disable rather than exiting silently.
_CALLER_HOOK_LOG="${ONEX_HOOK_LOG:-}"
# shellcheck source=./onex-paths.sh
source "${SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${_CALLER_HOOK_LOG:-${ONEX_HOOK_LOG:-${HOME}/.claude/onex-hooks.log}}"
unset _CALLER_HOOK_LOG
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

_log() {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] pr-body-stamp-guard: $*" >> "$LOG_FILE" 2>/dev/null || true
}

if ! onex_hook_gate BRANCH_PROTECTION_GUARD; then
    _log "DISABLED: BRANCH_PROTECTION_GUARD is cleared in ONEX_HOOKS_MASK, so this command was not evaluated for a dropped change-control evidence line. Re-enable with: onex hooks enable BRANCH_PROTECTION_GUARD"
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

# Cheap OVER-matching pre-filter. It decides nothing: anything it lets through
# is decided by pr_body_stamp_guard.py, which tokenises the command. Every
# body-replacing shape spells one of these, and a read never does -- `gh pr
# view --json body` and `--jq .body` carry none of them. `--input` is here
# because a REST PATCH whose JSON payload carries the body spells no other
# (OMN-19542: before it was added, that shape never reached the decision core).
if ! printf '%s' "$TOOL_INFO" | grep -Eq -- '--body|body-file|body=|--input'; then
    _hook_status "PASS" "no pull-request body-replacement vocabulary" "0" 2>/dev/null || true
    exit 0
fi

if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null); then
    _block "unparseable hook JSON carrying body-replacement vocabulary" \
        "BLOCKED: the PreToolUse payload for this Bash call names a pull-request body replacement but is not readable JSON, so the guard cannot tell whether it drops a change-control evidence line (OMN-18335). An unverifiable body replacement is refused, never assumed harmless. To disable this guard: onex hooks disable BRANCH_PROTECTION_GUARD"
fi

if [[ "$TOOL_NAME" != "Bash" ]]; then
    _hook_status "PASS" "not a Bash call ($TOOL_NAME)" "0" 2>/dev/null || true
    exit 0
fi

if [[ ! -f "$GUARD_PY" ]]; then
    _block "decision core missing" \
        "BLOCKED: the OMN-18335 pull-request body stamp-preservation gate is missing at ${GUARD_PY}, so this command cannot be checked for a dropped change-control evidence line. Repair the plugin install, or disable the guard deliberately: onex hooks disable BRANCH_PROTECTION_GUARD"
fi

# Interpreter resolution. The decision core imports only the standard library,
# so any CPython 3.11+ can run it; the chain still prefers the plugin's own
# interpreters so behaviour matches every other hook, and refuses rather than
# guessing when none exists.
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
    for brew_py in /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13; do  # public-skill-ok: the two CLAUDE.md-canonical interpreter paths, byte-identical to the sibling guard's resolver on this matcher
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
        "BLOCKED: no Python interpreter could be resolved to run the OMN-18335 pull-request body stamp-preservation gate, so this command cannot be checked. Repair the plugin install, or disable the guard deliberately: onex hooks disable BRANCH_PROTECTION_GUARD"
fi

set +e
GUARD_OUT=$(printf '%s' "$TOOL_INFO" | env -u PYTHONPATH "$GUARD_PYTHON" "$GUARD_PY" 2>&1)
GUARD_RC=$?
set -e

if [[ $GUARD_RC -eq 0 ]]; then
    _hook_status "PASS" "no change-control evidence line is lost by this command" "0" 2>/dev/null || true
    exit 0
fi

if [[ $GUARD_RC -eq 3 ]]; then
    REASON=$(printf '%s' "$GUARD_OUT" | jq -r '.reason // empty' 2>/dev/null || true)
    if [[ -z "$REASON" ]]; then
        REASON="BLOCKED: this command replaces a pull-request description with text that drops a change-control evidence line the live description carries (OMN-18335), and the guard's own detail payload was unreadable."
    fi
    _block "dropped change-control evidence line" "$REASON"
fi

_block "guard evaluation failed (rc=${GUARD_RC})" \
    "BLOCKED: the OMN-18335 pull-request body stamp-preservation gate could not evaluate this Bash command (exit ${GUARD_RC}), so whether it drops a change-control evidence line is unknown and the command is refused. Detail: $(printf '%s' "$GUARD_OUT" | head -c 400). To disable this guard deliberately: onex hooks disable BRANCH_PROTECTION_GUARD"
