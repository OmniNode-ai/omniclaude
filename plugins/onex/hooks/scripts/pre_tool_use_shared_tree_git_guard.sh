#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Shared-Tree Git Admission Gate (OMN-18798)
# =======================================================
# Refuses a Bash command that moves the SHARED registry clone at $OMNI_HOME out
# from under the lanes working in it -- `git reset`, a non-path-scoped
# `git checkout`, `git checkout -b`/`-B`, `git switch`, `git clean`,
# `git rebase`, a `git merge` outside the two sanctioned shapes, a
# `git branch` creation or a delete/rename whose target is the checked-out
# branch, a FORCE `git push`,
# and a path-scoped `git checkout` naming the append-only ledger -- when the
# command's effective git root (its `-C
# <path>` argument, or its own cwd) IS that registry clone.
#
# The last two arms are an OMN-18798 follow-up, added after the first
# revision was measured live against the real shared clone and found to
# admit both. A force push is the only refused verb whose damage is to
# history that is ALREADY committed and pushed rather than to the tree's
# uncommitted state; the ledger checkout is refused because Operating Rule
# 17's restore returns a file to HEAD rather than to the working tree, which
# on that one path discards peer lanes' appended rows silently.
#
# Why a hook and not a validator
# -------------------------------
# The registry clone at $OMNI_HOME is the ONE repo where many concurrent lanes commit into
# the same working tree; code repos use per-ticket worktrees and do not have
# this problem. Two measured failure classes, neither of which any gate
# could see:
#
#   * DESTRUCTION. `git reflog` recorded 20 `reset: moving to origin/main`
#     entries in that clone on 2026-09-18 alone. They twice re-orphaned a
#     staged 1.9 MB ledger-roll archive of 1,258 append-only coordination
#     rows -- untracked on one disk, in no commit, on no branch, on no
#     remote, for 2h22m -- and twice dropped a peer lane's unpushed commit
#     from local main.
#   * STRANDING, quieter and destroying nothing. A feature branch checked
#     out in the shared clone makes commit_lock.py refuse EVERY other lane's
#     ledger commit, exit 78, STRANDED CLONE, for as long as it stays
#     checked out. Three rows appended at 01:24Z reached a committed copy at
#     11:17Z. The only signal is an exit code on somebody else's terminal.
#
# Both are commands typed in a session, so no pre-commit hook and no repo CI
# job ever sees one; the tool seam is the only place they are observable
# before the collision happens. Operating Rule 19 states the prohibition and
# was doctrine-only until this guard -- it held exactly as long as each lane
# remembered it, which the reflog shows was not long.
#
# Same primitive, same structure, as pre_tool_use_git_stash_guard.sh
# (OMN-17334) and pre_tool_use_credential_rotation_guard.sh (OMN-17957):
# contract-declared vocabulary in a policy JSON, a standard-library-only
# Python decision core, a thin fail-closed shell wrapper.
#
# What this refuses, and what it deliberately does not
# ------------------------------------------------------
# Scope is narrow on purpose: the guard fires ONLY when the effective git
# root is the registry clone ITSELF. A worktree under omni_worktrees/ has
# its own .git file and so its own root; a code-repo canonical clone under
# $OMNI_HOME has root $OMNI_HOME/<repo>, not $OMNI_HOME. Neither is matched,
# and both already carry the OMN-7018/OMN-14330 worktree guard.
#
# Inside the registry clone, everything that is not a declared refused shape
# passes untouched: `git fetch`, `git pull --ff-only`, an ordinary
# `git push` or `git push origin main:refs/heads/<branch>`, the Operating
# Rule 17 path-scoped restore recipe (`git checkout <ref> -- <path>`) on
# every path but the ledger, and every read -- status, log, diff,
# show, rev-parse, reflog, worktree list.
#
# TWO merge shapes are allowed: `git merge --ff-only origin/main`, and the
# ruled ledger publish loop `git merge --no-edit origin/main` ON `main`.
# The second is a non-fast-forward merge and an earlier revision of this
# guard refused it, which would have broken the only working publish path
# the moment the hook went live. Operator ruling, 2026-09-19: the
# fast-forward step lost the race against concurrent appends eight cycles
# running. The BRANCH precondition is the control -- the 14:52:55Z loss was
# this same verb against this same target, run on a feature branch checked
# out in the shared clone. There is deliberately NO escape
# consent citation and no exempt marker: each refused verb has a sanctioned
# alternative reaching the same outcome without touching state a peer lane
# owns, so there is nothing a legitimate use needs that this guard blocks.
#
# Fail-open / fail-closed boundary, stated deliberately
# ------------------------------------------------------
#   * A command mentioning neither `git` nor any refused verb never invokes
#     Python at all. The greps below are a cheap OVER-matcher that decides
#     nothing; they fire on any command mentioning the words, quoted prose
#     included. A bug in this guard can never brick unrelated Bash traffic.
#   * A payload that DOES carry the vocabulary and cannot then be evaluated
#     -- unparseable hook JSON, a missing decision core, an unresolvable
#     interpreter, an unreadable policy -- is BLOCKED. An unverifiable
#     shared-tree mutation is refused, never assumed safe.
#   * An UNTOKENISABLE command is refused only when its raw text plainly
#     names git together with a refused verb as whole words. An unbalanced
#     quote in a command with nothing to do with git is not this guard's
#     business.
#   * shared_tree_git_guard.py is the authority, not the greps. It tokenises
#     each shell segment and matches by program plus tokens, so a comment or
#     a grep that merely mentions "git reset" trips the pre-filter and is
#     then ALLOWED.
#
# Gating: the SCOPE_GATE bit is BORROWED, the same pattern
# pre_tool_use_git_stash_guard.sh uses for SWEEP_PREFLIGHT and
# pre_tool_use_credential_rotation_guard.sh uses for
# PRE_TOOL_AUTHORIZATION_SHIM. hook_bits.sh is GENERATED from omnibase_core's
# hook_activations.yaml, so minting a dedicated bit is a cross-repo change
# this guard does not need. SCOPE_GATE is the cleanest borrow available: it
# is bit_defined in hook_bits.sh, it is set in HOOK_BITS_DEFAULT_MASK, its
# namesake script (pre_tool_use_scope_gate.sh) is on disk and UNREGISTERED
# in hooks.json, and no registered script gates on it -- so
# `onex hooks disable SCOPE_GATE` disables exactly this guard and nothing
# else that is live. tests/hooks/test_shared_tree_git_guard.py pins the
# borrow: registering the namesake would silently share one switch between
# two independent controls, and must turn that test red first.
#   Disable with: onex hooks disable SCOPE_GATE
#
# A disabled run is LOGGED, not silent, matching every other guard in this
# family (OMN-13244 history: a hook going dark with no repo-visible signal
# for months).
#
# Registration is ordered AFTER pre_tool_use_git_stash_guard.sh on the Bash
# matcher: that guard only ever inspects stash shapes and this one never
# does, so the two can never contend for the same call.

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
    || python3 -c "import os,sys; p=os.path.realpath(sys.argv[1]); print(p) if os.path.exists(p) else sys.exit(1)" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
GUARD_PY="${SCRIPT_DIR}/../lib/shared_tree_git_guard.py"
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
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

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

# Cheap OVER-matching pre-filter. It decides nothing: anything it lets
# through is decided by shared_tree_git_guard.py, which tokenises the
# command. A payload naming neither `git` nor any refused verb cannot be a
# refused shape, so it never pays for an interpreter start.
if ! printf '%s' "$TOOL_INFO" | grep -Eqi 'git'; then
    _hook_status "PASS" "no git vocabulary" "0" 2>/dev/null || true
    exit 0
fi
if ! printf '%s' "$TOOL_INFO" | grep -Eqi 'reset|checkout|switch|clean|rebase|branch|merge|push'; then
    _hook_status "PASS" "no refused git verb" "0" 2>/dev/null || true
    exit 0
fi

if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null); then
    _block "unparseable hook JSON naming a refused git verb" \
        "BLOCKED: the PreToolUse payload for this Bash call names git together with a verb refused in the shared registry clone at $OMNI_HOME, but is not readable JSON, so the guard cannot tell whether it moves the tree every other lane is working in (OMN-18798, Operating Rule 19). An unverifiable shared-tree mutation is refused, never assumed safe. To disable this guard: onex hooks disable SCOPE_GATE"
fi

if [[ "$TOOL_NAME" != "Bash" ]]; then
    _hook_status "PASS" "not a Bash call ($TOOL_NAME)" "0" 2>/dev/null || true
    exit 0
fi

if [[ ! -f "$GUARD_PY" ]]; then
    _block "decision core missing" \
        "BLOCKED: the OMN-18798 shared-tree git admission gate is missing at ${GUARD_PY}, so this command cannot be checked for a mutation of the shared registry clone at $OMNI_HOME. Repair the plugin install, or disable the guard deliberately: onex hooks disable SCOPE_GATE"
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

set +e
GUARD_OUT=$(printf '%s' "$TOOL_INFO" | env -u PYTHONPATH OMNI_HOME="${OMNI_HOME:-}" ONEX_REGISTRY_ROOT="${ONEX_REGISTRY_ROOT:-}" "$GUARD_PYTHON" "$GUARD_PY" 2>&1)
GUARD_RC=$?
set -e

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
