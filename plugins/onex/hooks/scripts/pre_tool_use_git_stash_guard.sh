#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Git-Stash Worktree Admission Gate (OMN-17334)
# ==========================================================
# Refuses a Bash command that mutates the git stash (push/pop/apply/drop/
# save/clear/store/branch, or a bare `git stash`) when the command's cwd or
# `-C <path>` target resolves to a git WORKTREE (`.git` is a file pointing at
# the parent clone's real git directory) or a canonical clone directly under
# $OMNI_HOME, shared by every concurrent lane.
#
# Why a hook and not a validator
# -------------------------------
# git's stash is ONE repo-wide stack. A worktree shares it with the parent
# clone and every sibling worktree; a canonical clone directly under
# $OMNI_HOME shares it with every lane working directly in that tree. The push/pop idiom lanes
# reach for to prove a test is RED-without-the-fix is unsafe by construction:
# a scoped `git stash push -- <path>` on a tree with no changes to that path
# silently creates NO entry and still exits 0, so the paired `git stash pop`
# pops whatever is at stash@{0} -- another lane's work. Measured six times by
# 2026-09-16 across omnibase_infra and omnimarket (rolling work ledger,
# existing=OMN-17334 rows on 2026-09-15T03:10Z, 2026-09-15T23:23Z and
# 2026-09-16T01:38Z), twice destroying a peer lane's uncommitted work
# outright. A stash mutation is a command typed in a session, so no
# pre-commit hook and no repo CI job ever sees it; the tool seam is the only
# place it is observable before the collision happens. Same argument, same
# primitive, as pre_tool_use_credential_rotation_guard.sh (OMN-17957), which
# this guard is patterned on: contract-declared vocabulary in a policy JSON,
# a standard-library-only Python decision core, a thin fail-closed shell
# wrapper.
#
# What this refuses, and what it deliberately does not
# --------------------------------------------------------
# Reads (`git stash list`, `git stash show`) are never gated -- they are not
# allowlisted, they simply never match the mutating-subcommand vocabulary
# declared in git_stash_guard_policy.json. A stash mutation in an ordinary
# git clone that is neither a worktree nor a canonical clone under
# $OMNI_HOME is outside both conditions and is never gated either: that
# lane owns the whole stash stack alone. There is deliberately NO escape
# consent citation, no wildcard shape, no exempt marker -- because the safe,
# non-destructive alternative already recorded in the rolling ledger
# (`git checkout origin/dev -- <path>` then `git checkout HEAD -- <path>`,
# scoped to named paths) never touches the shared stash ref at all, so there
# is nothing a legitimate use of the gated idiom needs that this guard would
# be blocking.
#
# The shared-tree half of this hazard -- two concurrent lanes racing
# push/pop inside the SAME canonical clone, as opposed to a worktree sharing
# its parent's stash -- is tracked separately as OMN-18433 and is
# deliberately untouched by this guard.
#
# Fail-open / fail-closed boundary, stated deliberately
# -----------------------------------------------------
#   * A command carrying no `stash` token never invokes Python at all. The
#     grep below is a cheap OVER-matcher that decides nothing; it fires on
#     any command mentioning the word "stash", including quoted text that
#     merely names it. A bug in this guard can never brick unrelated Bash
#     traffic.
#   * A payload that DOES mention `stash` and cannot then be evaluated --
#     unparseable hook JSON, a missing decision core, an unresolvable
#     interpreter, an unreadable policy, an untokenisable command -- is
#     BLOCKED. An unverifiable stash mutation is refused, never assumed safe.
#   * git_stash_guard.py is the authority, not the grep. It tokenises each
#     shell segment and matches by program plus tokens, so a comment or a
#     grep that merely mentions "git stash pop" trips the pre-filter and is
#     then ALLOWED.
#
# Gating: the SWEEP_PREFLIGHT bit is BORROWED, the same pattern
# pre_tool_use_credential_rotation_guard.sh uses for
# PRE_TOOL_AUTHORIZATION_SHIM. A dedicated bit is unavailable -- all 60
# default-mask ordinals in hook_bits.sh are allocated -- so this reuses
# SWEEP_PREFLIGHT: it is `bit_defined: true` in hook_bits.sh (unlike
# SKILL_SUBSTITUTION_GUARD, which resolves to no case arm at all and so can
# never actually gate anything -- `hook_bits_bit_for_name` would return
# non-zero and `onex_hook_gate` would then return 0 unconditionally), its
# namesake script (pre_tool_use_sweep_preflight.sh) is on disk and
# UNREGISTERED, and no other registered script gates on it -- so
# `onex hooks disable SWEEP_PREFLIGHT` disables exactly this guard and
# nothing else that is live. tests/hooks/test_git_stash_guard.py pins the
# borrow: registering pre_tool_use_sweep_preflight.sh would silently share
# the switch between two independent controls, which is exactly why
# BASH_GUARD was not reused a third time for this guard.
#   Disable with: onex hooks disable SWEEP_PREFLIGHT
#
# A disabled run is LOGGED, not silent, matching every other guard in this
# family (OMN-13244 history: a hook going dark with no repo-visible signal
# for months).
#
# Registration follows the OMN-14330 worktree-guard carve-out precedent and
# is ordered AFTER pre_tool_use_credential_rotation_guard.sh on the Bash
# matcher: that guard only ever inspects credential-rotation shapes and never
# a stash shape, so the two never contend for the same call.

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

# error-guard.sh sources hook-gate.sh, which supplies onex_hook_gate without
# common.sh. common.sh is deliberately NOT sourced: its find_python()
# hard-fails with `exit 1` when no venv is present, and the error-guard EXIT
# trap would convert that into `exit 0` -- a silent fail-OPEN. The decision
# core is standard-library-only precisely so this guard can resolve an
# interpreter itself and refuse when it cannot.
# shellcheck source=./error-guard.sh
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Resolve this script's own location BEFORE any `cd`. BASH_SOURCE[0] may be
# relative, and resolving it afterwards lands in the wrong tree.
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
GUARD_PY="${SCRIPT_DIR}/../lib/git_stash_guard.py"
unset _SELF

# The TOOL_INFO payload (which carries `cwd`) must be captured BEFORE any
# `cd`, and OMNI_HOME must already be set in the caller's environment for the
# decision core to resolve a canonical-clone target -- neither depends on
# this script's own CWD, so the stability `cd` below is safe.
cd "$HOME" 2>/dev/null || cd /tmp || true

_CALLER_HOOK_LOG="${ONEX_HOOK_LOG:-}"
# shellcheck source=./onex-paths.sh
source "${SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${_CALLER_HOOK_LOG:-${ONEX_HOOK_LOG:-${HOME}/.claude/onex-hooks.log}}"
unset _CALLER_HOOK_LOG
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

_log() {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] git-stash-guard: $*" >> "$LOG_FILE" 2>/dev/null || true
}

if ! onex_hook_gate SWEEP_PREFLIGHT; then
    _log "DISABLED: SWEEP_PREFLIGHT is cleared in ONEX_HOOKS_MASK, so this command was not evaluated for a git-stash mutation. Re-enable with: onex hooks enable SWEEP_PREFLIGHT"
    cat >/dev/null
    exit 0
fi

_block() {
    _hook_status "BLOCKED" "$1" "0" 2>/dev/null || true
    _log "BLOCKED: $1"
    jq -n --arg reason "$2" '{"decision": "block", "reason": $reason}' 2>/dev/null \
        || printf '{"decision": "block", "reason": %s}\n' "$(printf '%s' "$2" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    trap - EXIT
    exit 2
}

TOOL_INFO=$(cat)

# Cheap OVER-matching pre-filter. It decides nothing: anything it lets
# through is decided by git_stash_guard.py, which tokenises the command. A
# command with no "stash" token cannot be any stash shape, so it never pays
# for an interpreter start.
if ! printf '%s' "$TOOL_INFO" | grep -Eqi 'stash'; then
    _hook_status "PASS" "no stash vocabulary" "0" 2>/dev/null || true
    exit 0
fi

if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null); then
    _block "unparseable hook JSON mentioning stash" \
        "BLOCKED: the PreToolUse payload for this Bash call mentions git stash but is not readable JSON, so the guard cannot tell whether it mutates the shared stash ref (OMN-17334). An unverifiable stash mutation is refused, never assumed safe. To disable this guard: onex hooks disable SWEEP_PREFLIGHT"
fi

if [[ "$TOOL_NAME" != "Bash" ]]; then
    _hook_status "PASS" "not a Bash call ($TOOL_NAME)" "0" 2>/dev/null || true
    exit 0
fi

if [[ ! -f "$GUARD_PY" ]]; then
    _block "decision core missing" \
        "BLOCKED: the OMN-17334 git-stash admission gate is missing at ${GUARD_PY}, so this command cannot be checked for a stash mutation. Repair the plugin install, or disable the guard deliberately: onex hooks disable SWEEP_PREFLIGHT"
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
        "BLOCKED: no Python interpreter could be resolved to run the OMN-17334 git-stash admission gate, so this command cannot be checked. Repair the plugin install, or disable the guard deliberately: onex hooks disable SWEEP_PREFLIGHT"
fi

set +e
GUARD_OUT=$(printf '%s' "$TOOL_INFO" | env -u PYTHONPATH OMNI_HOME="${OMNI_HOME:-}" "$GUARD_PYTHON" "$GUARD_PY" 2>&1)
GUARD_RC=$?
set -e

if [[ $GUARD_RC -eq 0 ]]; then
    GUARD_NOTES=$(printf '%s' "$GUARD_OUT" | tail -n 1 \
        | jq -r 'select(type == "object") | .notes // [] | join(" | ")' 2>/dev/null || true)
    if [[ -n "$GUARD_NOTES" ]]; then
        _log "$GUARD_NOTES"
    fi
    _hook_status "PASS" "no unauthorised git-stash mutation in this command" "0" 2>/dev/null || true
    exit 0
fi

if [[ $GUARD_RC -eq 2 ]]; then
    REASON=$(printf '%s' "$GUARD_OUT" | jq -r '.reason // empty' 2>/dev/null || true)
    if [[ -z "$REASON" ]]; then
        REASON="BLOCKED: this command mutates the shared git stash ref while its target is a worktree or a canonical clone under OMNI_HOME (OMN-17334), and the guard's own detail payload was unreadable."
    fi
    _block "unauthorised git-stash mutation" "$REASON"
fi

_block "guard evaluation failed (rc=${GUARD_RC})" \
    "BLOCKED: the OMN-17334 git-stash admission gate could not evaluate this Bash command (exit ${GUARD_RC}), so whether it mutates the shared stash ref is unknown and the command is refused. Detail: $(printf '%s' "$GUARD_OUT" | head -c 400). To disable this guard deliberately: onex hooks disable SWEEP_PREFLIGHT"
