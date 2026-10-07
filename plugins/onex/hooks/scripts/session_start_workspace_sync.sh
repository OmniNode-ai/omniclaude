#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# SessionStart workspace-sync line (OMN-17190)
# ============================================
#
# Prints the workspace verdict and, when installed, the host-drift verdict:
#
#     [workspace-sync] clones/venv: in sync as of 2026-08-30T14:52:11Z
#     [workspace-sync] DRIFT: omnimarket not pulled (dirty or non-ff) as of ...
#
# Why this exists: drift in the canonical clones or the installed venvs used to
# become visible only when a dispatch failed -- mid-task, as a refusal, after
# the session had already committed to a plan. Surfacing it in the first line
# of a session makes it a thing you decide about, not a thing that ambushes you.
# Same failure class as the session goal being invisible until recalled
# (OMN-17168, session_start_goal_surface.sh).
#
# OMN-17427: lab hosts drifted from merged state for 36 hours with nothing
# paying attention. The scheduled check publishes bus events; this line is
# the operator-facing alert surface at session start. No Slack.
#
# Contract
# --------
#   Reads:   $ONEX_HOOKS_STATE_DIR/workspace-reconcile.status
#            $ONEX_HOOKS_STATE_DIR/host-drift.status (when present)
#   Writes:  stdout only.
#   Blocks:  never. Exit 0 on every path, including a missing status file.
#
# Why it reads a file instead of computing the answer
# ---------------------------------------------------
# Deriving this live means `git rev-parse` per clone plus a `uv sync --check`
# per venv -- seconds, measured, on a path contracted to be fast. So the tick
# (workspace_reconcile_tick.sh) does the work on its own schedule and leaves a
# one-line verdict; this hook prints it. Host drift likewise comes from the
# scheduled check_host_drift operation, every 15 minutes; its verdict becomes
# an ALERT after 35 minutes without a report. Reading it adds one bash read
# and one mtime probe, sharing the current clock with the workspace verdict.
#
# The obvious risk of reading a cached verdict is reporting a stale "in sync"
# as if it were current, so the age is ALWAYS printed and a verdict older than
# _STALE_MINUTES is labelled rather than trusted. An unknown age renders as
# stale, never as fresh.
#
# Interpreter: pure bash, no Python, no jq -- a hook with no interpreter cannot
# resolve to the wrong one (CLAUDE.md rule 11 / the OMN-16996 regression class).
#
# INTERIM BY DESIGN. When the OMN-17190 successor lands, the tick becomes a
# runtime NodeEffect and this hook reads the resulting projection instead of a
# status file; the print shape does not change.

set -u

_PREFIX="[workspace-sync]"
_STALE_MINUTES=30

say() { printf '%s %s\n' "$_PREFIX" "$*"; }

# SessionStart delivers a JSON payload on stdin; drain it so the caller never
# sees an EPIPE.
cat >/dev/null 2>&1 || true

# OMN-20109: this script's directory, resolved once without a dirname exec.
_ONEX_HOOK_SELF_DIR="${BASH_SOURCE[0]%/*}"; [[ "${BASH_SOURCE[0]}" == */* ]] || _ONEX_HOOK_SELF_DIR=.; [[ -n "$_ONEX_HOOK_SELF_DIR" ]] || _ONEX_HOOK_SELF_DIR=/
_SCRIPT_DIR="$(cd "${_ONEX_HOOK_SELF_DIR}" 2>/dev/null && pwd)" || _SCRIPT_DIR="."

# Lite mode: an external contributor has no canonical registry and must never
# see ONEX-specific output.
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    # shellcheck disable=SC1090
    source "$_MODE_SH" 2>/dev/null || true
    if declare -F omniclaude_mode >/dev/null 2>&1 && [[ "$(omniclaude_mode)" == "lite" ]]; then
        exit 0
    fi
fi

# A machine with no canonical registry has no clones to be out of sync with.
if [[ -z "${OMNI_HOME:-}" || ! -d "${OMNI_HOME}" ]]; then
    exit 0
fi

# shellcheck source=onex-paths.sh
source "${_SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true

# --------------------------------------------------------------------------- #
# The load path this hook is EXECUTING FROM (OMN-16497)
# --------------------------------------------------------------------------- #
#
# Everything below this block reads a verdict some other process cached. This
# block does not, and cannot: it answers "is the tree these hooks are loaded
# from current?", and a cached answer to that question was written BY code
# loaded from the same tree. If the tree is stale, so is the verdict about it,
# and so is the code that printed it. A stale surface cannot certify itself.
#
# Measured, 2026-09-14. $OMNI_HOME/omniclaude -- the symlink target of the
# plugin every live PreToolUse hook actually runs from -- carried
# core.bare=true and had not fast-forwarded since 2026-09-11, fifteen commits
# behind origin/dev. `git fetch` succeeds forever on a bare clone while no
# checkout ever lands, so refs advanced and working-tree files did not. Every
# guard merged in that window existed in git history and was dark on every
# running session, fleet-wide, for at least three days.
#
# This line said "clones/venv: in sync" throughout, and it was not lying: the
# reconciler it quotes (onex-host-reconcile, formerly omnibase_infra/scripts/reconcile-host.sh) checks
# core.bare through its clone-health verifier, but only over
# SIBLING_CLONE_MANIFEST -- omnibase_infra, omnibase_core, omnibase_spi,
# omnibase_compat, omnimarket. That is the runtime-image sibling set.
# `omniclaude` is not in it, so the one clone that decides whether any hook
# runs at all is the one clone nothing was looking at.
#
# Cost: two `git` calls against ONE repository, both local. No fetch -- see the
# honest limit on `behind` below.
_load_path_alarm() {
    local root bare behind upstream probe
    # Walk up for the enclosing `.git` in pure bash rather than asking git for
    # `--show-toplevel`. A repository configured core.bare=true HAS no work
    # tree by git's reckoning, so `--show-toplevel` fails there -- on exactly
    # the repository state this check exists to catch. Asking git would make
    # the probe silent in its most important case.
    root=""
    probe="$_SCRIPT_DIR"
    while [[ -n "$probe" && "$probe" != "/" ]]; do
        if [[ -e "$probe/.git" ]]; then
            root="$probe"
            break
        fi
        probe="${probe%/*}"
    done
    [[ -n "$root" ]] || return 0

    # A bare clone fetches cleanly and checks out nothing. This is the failure
    # that hides itself: refs move, files do not, and every "up to date" probe
    # that reads refs agrees.
    # Read .git/config in bash rather than forking `git config`. Two forks is
    # the whole budget of this block; one of them buys nothing that a six-line
    # INI read does not. A worktree carries a .git FILE and can never be bare,
    # so it skips straight to the behind check.
    bare=""
    if [[ -d "$root/.git" && -r "$root/.git/config" ]]; then
        local _section="" _line
        while IFS= read -r _line || [[ -n "$_line" ]]; do
            _line="${_line#"${_line%%[![:space:]]*}"}"
            case "$_line" in
                "["*) _section="$_line" ;;
                bare*=*)
                    if [[ "$_section" == "[core]"* ]]; then
                        bare="${_line#*=}"
                        bare="${bare//[[:space:]]/}"
                    fi
                    ;;
            esac
        done < "$root/.git/config"
    fi
    if [[ "$bare" == "true" ]]; then
        say "ALARM: the tree these hooks load from has core.bare=true, so no"
        say "  merged hook change has reached a running session since it was set."
        say "    tree:   $root"
        say "    repair: git -C \"$root\" config core.bare false && git -C \"$root\" reset --hard HEAD"
        say "  Then start a NEW session: updating files does not reload hooks.json."
        return 0
    fi

    # Behind its own upstream. Measured against the remote-tracking ref that is
    # already on disk -- this hook does not fetch, because SessionStart is a
    # sub-50ms contract and a network call there is a hang waiting for a bad
    # link. HONEST LIMIT, stated rather than left to be discovered: if nothing
    # has fetched recently, `behind` reads 0 and this check is silent. It
    # detects a clone that fetched and did not fast-forward, which is the
    # measured shape; it does not detect a clone nothing has fetched at all.
    # One process, not two: rev-list resolves @{u} itself and fails harmlessly
    # when the branch has no upstream. SessionStart is a sub-50ms contract, so
    # every avoidable fork here is spent budget.
    behind="$(git -C "$root" rev-list --count 'HEAD..@{u}' 2>/dev/null)" || return 0
    if [[ -n "$behind" && "$behind" != "0" ]]; then
        upstream="$(git -C "$root" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"
        say "ALARM: the tree these hooks load from is ${behind} commit(s) behind ${upstream:-its upstream}."
        say "  Merged is not deployed: those changes are dark on this session."
        say "    tree:   $root"
        say "    repair: git -C \"$root\" pull --ff-only"
        say "  Then start a NEW session: updating files does not reload hooks.json."
    fi

    # HALF-APPLIED (OMN-18358). The OMN-16497 reference-transaction guard used
    # to abort a refused branch switch AFTER git had already written the target
    # tree and index, leaving the clone on the TARGET tree with HEAD behind and
    # every changed path staged. git writes no reflog entry for an aborted
    # transaction, so the only visible trace was phantom staged paths in a clone
    # nobody was watching -- measured here 2026-09-14T07:0xZ as 420 staged, 0
    # worktree-modified, 0 untracked. The guard now restores the tree itself;
    # this is the backstop for the case it declines, and for a clone
    # half-applied before the fix reached this host.
    #
    # The signature is specific and cheap to test: the index differs from HEAD
    # while the worktree agrees with the index. An ordinary unstaged edit fails
    # the second half, which is what keeps this from firing on every session
    # where somebody is mid-edit. Two plumbing calls, both local, both silent.
    if ! git -C "$root" diff-index --quiet --cached HEAD -- 2>/dev/null &&
        git -C "$root" diff-files --quiet 2>/dev/null; then
        say "ALARM: the tree these hooks load from looks half-applied: its index"
        say "  differs from HEAD while the worktree matches the index. That is the"
        say "  shape a refused branch switch leaves behind, and git records it nowhere."
        say "    tree:   $root"
        say "    repair: \$OMNI_HOME/omniclaude/scripts/converge-canonical-clone.sh <repo> --execute"
        say "  Inspect before repairing: git -C \"$root\" diff --cached --stat"
    fi
    return 0
}

# Never let a probe of the load path break the line that reports it.
_load_path_alarm || true

# --------------------------------------------------------------------------- #
# A journal nothing drains (OMN-17427)
# --------------------------------------------------------------------------- #
#
# Every hook emit appends to the local journal and returns; the resident drainer
# is the only thing that publishes it. The drainer is installed by hand
# (scripts/install-hook-emit-drainer.sh, "the operator's deploy step") and no
# bring-up path runs that step, so a host that never had it run keeps hooking
# normally while nothing it records ever reaches the bus.
#
# Measured, 2026-10-07: h202 carried 38,653 pending records, the oldest from
# 2026-09-30, with no unit file on disk, while h201 -- where the installer had
# been run -- drained. Nothing on h202 said so: the journal is bounded, so it
# drops its oldest records rather than failing, and the emit path stays green.
#
# Absent the installed definition AND a record in the journal is the cheap,
# unambiguous half of that state: one stat on a healthy host, and a `find` that
# stops at the first record only on a host that is already wrong. It is not
# "the drainer is down" (that needs a process check this budget cannot pay for)
# and it does not read the installed unit's content; it only refuses to let the
# never-installed case be silent. Like the load-path alarm it sits above the
# session-intent gate: quiet buys no silence from a host losing its telemetry.
_drainer_alarm() {
    local label="ai.omninode.hook-emit-drainer" definition journal
    case "${OSTYPE:-}" in
        darwin*) definition="${HOME}/Library/LaunchAgents/${label}.plist" ;;
        *) definition="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user/${label}.service" ;;
    esac
    [[ -e "$definition" ]] && return 0

    if [[ -n "${ONEX_HOOK_EMIT_JOURNAL_DIR:-}" ]]; then
        journal="$ONEX_HOOK_EMIT_JOURNAL_DIR"
    elif [[ -n "${ONEX_STATE_DIR:-}" ]]; then
        journal="${ONEX_STATE_DIR}/hook_emit_journal"
    else
        journal="${HOME}/.onex_state/hook_emit_journal"
    fi
    [[ -d "$journal" ]] || return 0
    [[ -n "$(find "$journal" -maxdepth 1 -name '*.json' -print -quit 2>/dev/null)" ]] || return 0

    say "ALARM: hook events are journalled on this host and nothing publishes them."
    say "  The drainer is not installed (missing: ${definition}), so the journal"
    say "  only grows -- and drops its oldest records at its bound."
    say "    journal: $journal"
    say "    repair:  bash \"\$OMNI_HOME/omniclaude/scripts/install-hook-emit-drainer.sh\""
    say "  Then check it publishes: install-hook-emit-drainer.sh --status shows Pending falling."
    return 0
}
_drainer_alarm || true

# Session intent (OMN-18368): under `quiet` and `tick` this hook prints nothing
# further. The routine one-line verdict is status output, and a session opened
# to re-authenticate asked for none.
#
# THE ALARM ABOVE IS DELIBERATELY NOT SUPPRESSED, and it is the only exception
# in the whole session-start chain. It reports that the tree these hooks are
# loaded from is bare or behind its upstream, which means every guard merged
# since is dark on this session -- including whatever guard would have caught
# the next mistake. Silence is the failure mode that alarm exists to break, so
# an intent may not buy silence from it: a stale surface cannot certify itself,
# and a session that asked for quiet gets exactly that one blocker and nothing
# else. That is this step's stated falsifier, and it is why the intent gate sits
# BELOW the alarm rather than at the top of the file.
_INTENT_SH="${_SCRIPT_DIR}/../../lib/intent.sh"
if [[ -f "$_INTENT_SH" ]]; then
    # shellcheck disable=SC1090
    source "$_INTENT_SH" 2>/dev/null || true
    if declare -F omniclaude_session_intent_is_silent >/dev/null 2>&1 \
        && omniclaude_session_intent_is_silent; then
        exit 0
    fi
fi

_STATE_DIR="${ONEX_HOOKS_STATE_DIR:-${HOME}/.onex_state/hooks}"
_STATUS="${_STATE_DIR}/workspace-reconcile.status"
_now=""

# Called only below the same mode/intent gates as the workspace verdict.
_print_host_drift() {
    local status="${_STATE_DIR}/host-drift.status" line="" mtime age_min
    local _PREFIX="[host-drift]"
    [[ -f "$status" && -r "$status" ]] || return 0
    IFS= read -r line 2>/dev/null < "$status" || true
    [[ -n "$line" ]] || return 0

    # Same mtime semantics as the workspace block. Select the platform's stat
    # syntax directly so the added verdict costs only one mtime call.
    case "${OSTYPE:-}" in
        darwin*) mtime="$(stat -f %m "$status" 2>/dev/null)" ;;
        *) mtime="$(stat -c %Y "$status" 2>/dev/null)" ;;
    esac
    if [[ "$mtime" =~ ^[0-9]+$ ]]; then
        # Reuse the workspace clock; resolve it here only if that block had
        # no verdict/mtime and therefore never needed the current time.
        [[ -n "${_now:-}" ]] || _now="$(date -u +%s)"
        if [[ "$_now" =~ ^[0-9]+$ ]]; then
            age_min=$(( ( _now - mtime ) / 60 ))
            (( age_min < 0 )) && age_min=0
            if (( age_min > 35 )); then
                say "$line"
                say "  (host-drift verdict is ${age_min}m old — the drift check itself has stopped reporting; treat it as an ALERT)"
            else
                say "$line (checked ${age_min}m ago)"
            fi
            return 0
        fi
    fi
    say "$line"
    say "  (host-drift verdict age UNKNOWN — the drift check itself has stopped reporting; treat it as an ALERT)"
    return 0
}

if [[ ! -r "$_STATUS" ]]; then
    # Honest unknown. Never render "no data" as "in sync" -- that is the exact
    # substitution this hook exists to prevent.
    say "UNKNOWN: no reconcile tick has run yet on this host."
    say "  The tick (workspace_reconcile_tick.sh) writes its verdict here:"
    say "    $_STATUS"
    say "  To settle it now:"
    say "    bash \$OMNI_HOME/omnibase_infra/scripts/reconcile-workspace-venvs.sh --check"
    _print_host_drift
    exit 0
fi

_line="$(head -n1 "$_STATUS" 2>/dev/null)"
if [[ -z "$_line" ]]; then
    _print_host_drift
    exit 0
fi

# Age from the file's own mtime -- the tick rewrites the file every run, so
# mtime is the verdict's age by construction and needs no parsing.
_mtime="$(date -u -r "$_STATUS" +%s 2>/dev/null || stat -c %Y "$_STATUS" 2>/dev/null || echo "")"
if [[ -n "$_mtime" ]]; then
    _now="$(date -u +%s)"
    _age_min=$(( ( _now - _mtime ) / 60 ))
    (( _age_min < 0 )) && _age_min=0
    if (( _age_min > _STALE_MINUTES )); then
        say "$_line"
        say "  (verdict is ${_age_min}m old — older than ${_STALE_MINUTES}m, so treat it as unproven)"
        _print_host_drift
        exit 0
    fi
    say "$_line (checked ${_age_min}m ago)"
    _print_host_drift
    exit 0
fi

# No readable mtime: age unknown, which must never render as fresh.
say "$_line"
say "  (verdict age UNKNOWN — treat it as unproven)"
_print_host_drift
exit 0
