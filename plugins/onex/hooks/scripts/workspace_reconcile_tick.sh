#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Workspace reconcile tick (OMN-17190, delegating since OMN-17311)
#
# Keeps the canonical clones and the locally-installed venvs tracking `dev`,
# automatically, without anyone typing a command.
#
# Operator direction, 2026-08-30: "Why is anything hand built? ... We need a
# process that either (1) disconnects the local installation from the canonical
# clones, or (2) automatically pulls the clones whenever a PR is merged and
# refreshes the venv." Option 2 was chosen -- dev-tip dogfooding is the point,
# so the install tracks the clones and this tick is what closes the gap.
#
# What it does, at most once every ONEX_RECONCILE_TICK_SECONDS (default 600):
#   1. bootstrap the omnibase_infra clone IF neither reconciler path is available
#   2. run onex-host-reconcile from the omnibase_internal clone's .venv
#      (legacy reconcile-host.sh is a transitional fallback)
#   3. write a receipt line and the one-line status the SessionStart hook reads
#
# This hook owns THROTTLING, DETACHMENT and the STATUS LINE. It owns no repair
# logic and no verdict logic (OMN-17311).
#
# What it used to do, and why that had to stop
# --------------------------------------------
# Until OMN-17311 this file carried its own clone loop: fetch, `git pull
# --ff-only`, then write `status=PULLED` on THE PULL'S EXIT CODE. That is the
# OMN-17307 defect sitting in the scheduler. A `.201` clone with
# `core.bare=true` and a working tree fetches cleanly forever while every
# checkout fails with exit 128 (OMN-17291); nothing here ever re-read HEAD, so
# a loop shaped like this one would have called that clone healthy for as long
# as it existed. And the Mac having its own implementation meant the two hosts
# were reconciled by different code, so a fix on one was not a fix on the other.
#
# There is now ONE reconciler, `onex-host-reconcile`, run identically here and
# from `.201`'s cron unit. It proves every surface moved by reading it back.
# The legacy `omnibase_infra/scripts/reconcile-host.sh` is a transitional fallback.
#
# Why a PostToolUse tick and not a scheduler
# ------------------------------------------
# There is no long-running omniclaude daemon with a scheduler to hang this off:
# measured 2026-08-30 under OMN-17173, every `omniclaude` process is an
# ephemeral per-hook subprocess of an active session (longest observed lifetime
# 12s). `CronCreate` is session-scoped and in-memory, so it dies with the REPL.
#
# launchd is a genuine alternative and the note that it "does not fire on this
# Mac" is SUPERSEDED -- the same OMN-17173 measurement proved a fresh agent
# firing, and the ticks that looked dead had been `bootout`'d while the machine
# stayed up. It is not used here for a different reason: a launchd agent
# reconciles a venv on a wall clock, including while a session is mid-dispatch
# through that exact venv, and it needs a per-host install step that a plugin
# update does not carry. A throttled PostToolUse hook needs no install, ships
# with the plugin, and fires whenever a session is doing work -- which is
# precisely when a stale venv would hurt. It costs one stamp-file read when the
# interval has not elapsed. `hook_idle_notification_ratelimit.sh` uses the same
# stamp-throttle shape.
#
# The trade this accepts, stated rather than hidden: with no session running,
# nothing reconciles. That is covered on the other side -- the SessionStart line
# below surfaces the verdict before any work is planned, and the `onex` CLI
# guard self-heals at the point of dispatch (OMN-17190, workspace_reconcile.py).
# If session-coupled firing ever proves insufficient, the fix is a launchd
# `StartInterval` agent driving this same script, not a second implementation.
#
# Never blocks, never fails a tool call
# -------------------------------------
# Exit 0 on every path. The reconcile itself runs DETACHED, so the tool call
# that triggered the tick never waits on a `uv sync`. A tick can therefore
# never make the session slower or refuse anything -- the enforcement surface
# is the `onex` CLI guard, which refuses at the point where a stale venv would
# actually produce bad results.
#
# Never pulls into a dirty clone (now the delegate's guarantee, not this file's)
# ----------------------------------------------------------------------------
# A dirty canonical clone is reported, never touched. Pulling would either fail
# noisily mid-tick or, worse, succeed and entangle someone's uncommitted work
# with a fast-forward they did not ask for. Committing directly in a canonical
# clone is already a policy violation (CLAUDE.md: all work happens in
# worktrees), so a dirty clone is a thing to surface, not a thing to resolve
# automatically.
#
# INTERIM BY DESIGN. The successor named on OMN-17190 is a runtime-driven
# NodeEffect that publishes its receipt to the bus instead of appending to a
# local log. The receipt line below is already shaped as that event's payload.

set -u

# OMN-20109: this script's directory, resolved once without a dirname exec.
_ONEX_HOOK_SELF_DIR="${BASH_SOURCE[0]%/*}"; [[ "${BASH_SOURCE[0]}" == */* ]] || _ONEX_HOOK_SELF_DIR=.; [[ -n "$_ONEX_HOOK_SELF_DIR" ]] || _ONEX_HOOK_SELF_DIR=/
_SCRIPT_DIR="$(cd "${_ONEX_HOOK_SELF_DIR}" 2>/dev/null && pwd)" || _SCRIPT_DIR="."

# SessionStart/PostToolUse deliver a JSON payload on stdin. Nothing here needs
# it, but an unread stdin can hand the caller an EPIPE, so drain it.
cat >/dev/null 2>&1 || true

# Lite mode: an external contributor using this plugin in an unrelated repo has
# no canonical registry and must never have their clones touched.
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    # shellcheck disable=SC1090
    source "$_MODE_SH" 2>/dev/null || true
    if declare -F omniclaude_mode >/dev/null 2>&1 && [[ "$(omniclaude_mode)" == "lite" ]]; then
        exit 0
    fi
fi

# shellcheck source=onex-paths.sh
source "${_SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Config -- fail SILENT, not fast (CLAUDE.md rule 8 applies to the reconciler,
# which does fail fast; a hook that hard-failed on an unset variable would
# print noise into every single tool call on a machine that simply has no
# canonical registry).
# ---------------------------------------------------------------------------
if [[ -z "${OMNI_HOME:-}" || ! -d "${OMNI_HOME}" ]]; then
    exit 0
fi

_STATE_DIR="${ONEX_HOOKS_STATE_DIR:-${HOME}/.onex_state/hooks}"
_STAMP="${_STATE_DIR}/workspace-reconcile.stamp"
_STATUS="${_STATE_DIR}/workspace-reconcile.status"
_RECEIPTS="${ONEX_LOG_DIR:-${HOME}/.onex_state/logs}/workspace-reconcile.log"
_INTERVAL="${ONEX_RECONCILE_TICK_SECONDS:-600}"

[[ -d "$_STATE_DIR" && -d "${_RECEIPTS%/*}" ]] \
    || mkdir -p "$_STATE_DIR" "${_RECEIPTS%/*}" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Throttle
# ---------------------------------------------------------------------------
# OMN-20109: no date exec on the throttle path; bash 3.2 (macOS) lacks %(...)T.
_ONEX_PRINTF_T=0
(( BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 2) )) && _ONEX_PRINTF_T=1
if (( _ONEX_PRINTF_T )); then printf -v _now '%(%s)T' -1; else _now="$(date -u +%s)"; fi
_last=0
if [[ -f "$_STAMP" ]]; then
    _last="$(cat "$_STAMP" 2>/dev/null || echo 0)"
    [[ "$_last" =~ ^[0-9]+$ ]] || _last=0
fi

if (( _now - _last < _INTERVAL )); then
    exit 0
fi

# Claim the interval BEFORE doing any work. Hooks fire concurrently (several
# tool calls can be in flight at once), and a stamp written after the reconcile
# would let every one of them start its own `uv sync` against the same venv --
# which uv serialises on an exclusive flock, turning a stampede into a pile-up
# of processes each waiting on the last (the OMN-15590 stall shape).
printf '%s\n' "$_now" > "$_STAMP" 2>/dev/null || exit 0

# ---------------------------------------------------------------------------
# The tick body, run detached so no tool call ever waits on it
# ---------------------------------------------------------------------------
# Where `onex-host-reconcile` lives (OMN-17427). It is a console script of the
# omnibase_internal project, not of omnibase_infra and not of the dispatch venv:
# `reconcile-workspace-venvs.sh` builds the dispatch venv from the runtime
# siblings and has never installed omnibase_internal into it, so the path this
# tick used to look at ($ONEX_DISPATCH_VENV/bin/onex-host-reconcile) held nothing
# on any host and the session line printed "DRIFT: no workspace reconciler" for
# as long as it stayed that way.
#
# The command is installed where every omnibase_internal command already is: the
# project's own `.venv`, kept current by its `onex-internal-clone-sync` timer
# (systemd on a lab host, launchd on the Mac; both run `uv sync --frozen`, which
# installs every console script the project declares). This resolves THAT file.
# It runs no `uv` itself -- the console script's shebang is the project venv's
# interpreter, so the tick still starts no interpreter of its own.
#
# Which clone: OMNIBASE_INTERNAL_HOME when set (the same declaration the timer
# and the ledger writer honour), else the sibling of OMNI_HOME as written, then
# the sibling of its resolved target. A symlinked OMNI_HOME can put a stale
# second copy beside the link (h201: ~/Code/omnibase_internal beside the link,
# /data/omninode/omnibase_internal beside the target), so the answer is the
# first candidate that actually holds an executable command, not the first
# directory. Sets _RECONCILER (the path, or empty) and _RECONCILER_TRIED (every
# path it looked at, for the ABSENT line); runs in the caller's shell, not a
# command substitution, so both survive the call.
_resolve_host_reconcile() {
    local -a homes=()
    local home resolved
    if [[ -n "${OMNIBASE_INTERNAL_HOME:-}" ]]; then
        homes+=("${OMNIBASE_INTERNAL_HOME%/}")
    else
        # Lexical parents, not `/..`: the kernel resolves `link/..` through the
        # symlink, which would make the "as written" candidate the resolved one.
        home="${OMNI_HOME%/}"
        homes+=("${home%/*}/omnibase_internal")
        resolved="$(cd "$OMNI_HOME" 2>/dev/null && pwd -P)"
        [[ -n "$resolved" && "$resolved" != "$home" ]] && homes+=("${resolved%/*}/omnibase_internal")
    fi
    _RECONCILER=""
    _RECONCILER_TRIED=""
    for home in "${homes[@]}"; do
        _RECONCILER_TRIED+="${_RECONCILER_TRIED:+ }${home}/.venv/bin/onex-host-reconcile"
        if [[ -x "${home}/.venv/bin/onex-host-reconcile" ]]; then
            _RECONCILER="${home}/.venv/bin/onex-host-reconcile"
            return 0
        fi
    done
    return 1
}

_run_tick() {
    local ts canonical legacy bootstrap_note="" verdict rc
    if (( _ONEX_PRINTF_T )); then TZ=UTC printf -v ts '%(%Y-%m-%dT%H:%M:%SZ)T' -1; else ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; fi

    _resolve_host_reconcile || true
    canonical="$_RECONCILER"
    legacy="$OMNI_HOME/omnibase_infra/scripts/reconcile-host.sh"

    # ---- bootstrap: how the reconciler itself gets here --------------------
    # The tick no longer pulls the clones. That leaves exactly one ordering
    # problem: on a host whose omnibase_infra clone predates OMN-17307, the
    # reconciler does not exist yet, and nothing else advances the clone that
    # would deliver it. So the ONE repo the tick still advances by itself is
    # omnibase_infra, and only while both reconciler paths are absent.
    #
    # It is verified by content like everything else -- HEAD is re-read after
    # the pull and compared to origin/dev. A bootstrap that reports success on
    # `git pull`'s exit status would be the OMN-17307 defect reintroduced in the
    # one place nobody would look for it.
    if [[ -z "$canonical" && ! -f "$legacy" ]]; then
        local infra="$OMNI_HOME/omnibase_infra" head_before head_after target
        if [[ -d "$infra/.git" ]]; then
            head_before="$(git -C "$infra" rev-parse HEAD 2>/dev/null)"
            git -C "$infra" fetch --quiet --prune origin dev 2>/dev/null
            target="$(git -C "$infra" rev-parse origin/dev 2>/dev/null)"
            if [[ -z "$(git -C "$infra" status --porcelain 2>/dev/null)" ]]; then
                git -C "$infra" pull --ff-only --quiet origin dev 2>/dev/null
            fi
            head_after="$(git -C "$infra" rev-parse HEAD 2>/dev/null)"
            if [[ -n "$head_after" && "$head_after" == "$target" ]]; then
                bootstrap_note="bootstrap=omnibase_infra ${head_before:0:12}->${head_after:0:12}"
            else
                bootstrap_note="bootstrap=FAILED omnibase_infra head=${head_after:0:12} target=${target:0:12}"
            fi
            printf '%s %s\n' "$ts" "$bootstrap_note" >> "$_RECEIPTS"
        fi
    fi

    # ---- delegate ----------------------------------------------------------
    # One reconciler, every machine (OMN-17307). This hook owns throttling,
    # detachment and the SessionStart line; it owns no repair logic and no
    # verdict logic. The previous version of this function fetched, pulled
    # --ff-only and wrote `status=PULLED` on the PULL'S EXIT CODE -- the exact
    # defect OMN-17307 exists to end, sitting in the scheduler. It also had no
    # idea that a clone with core.bare=true fetches cleanly forever while every
    # checkout fails (OMN-17291), because nothing here ever re-read HEAD.
    if [[ -n "$canonical" ]]; then
        "$canonical" --omni-home "$OMNI_HOME" >>"$_RECEIPTS" 2>&1
    elif [[ -f "$legacy" ]]; then
        # Drop this fallback once omnibase_infra deletes the script and every
        # host has the command.
        bash "$legacy" --omni-home "$OMNI_HOME" >>"$_RECEIPTS" 2>&1
    else
        printf '%s tick=complete reconciler=ABSENT tried=%s %s\n' \
            "$ts" "$_RECONCILER_TRIED" "$bootstrap_note" >> "$_RECEIPTS"
        printf 'DRIFT: no workspace reconciler: onex-host-reconcile is not installed in the omnibase_internal clone (tried %s) as of %s\n' \
            "$_RECONCILER_TRIED" "$ts" > "$_STATUS"
        return 0
    fi
    rc=$?

    # 4 is DECLINED (OMN-18608): the reconciler did nothing because a live peer
    # holds the lock. It used to return 0 for that, and this table then wrote
    # `verdict="in sync"` on a run that reconciled nothing -- which is what made
    # the 2026-09-17 outage invisible for 35 minutes in the very log meant to
    # reveal it. Still no verdict logic here (OMN-17311): the reconciler decides,
    # this only names what it decided.
    case "$rc" in
        0) verdict="in sync" ;;
        2) verdict="FAILED" ;;
        4) verdict="declined (another holder is reconciling)" ;;
        *) verdict="INDETERMINATE (exit $rc)" ;;
    esac

    printf '%s tick=complete reconciler_exit=%s verdict="%s" %s\n' \
        "$ts" "$rc" "$verdict" "$bootstrap_note" >> "$_RECEIPTS"

    # ---- one-line status for the SessionStart hook ------------------------
    # A file, not a computation: SessionStart is contracted to be fast, and
    # re-deriving this there would mean a git fetch on every session open.
    #
    # A DECLINE LEAVES THIS FILE ALONE, and that is the point rather than an
    # omission. Several hook ticks fire at once by design, so most declines are
    # healthy -- a peer is reconciling right now. Writing "in sync" would be the
    # lie this change removes; writing DRIFT would raise an alarm on the normal
    # case, and a status surface that cries wolf on every tick is one nobody
    # reads, which is how the real failure went unnoticed. So the last verdict
    # actually earned by a run that did work stays, and the decline is recorded
    # in the receipt log above where it belongs.
    if [[ "$rc" -eq 0 ]]; then
        printf 'clones/venv: in sync as of %s\n' "$ts" > "$_STATUS"
    elif [[ "$rc" -ne 4 ]]; then
        printf 'DRIFT: reconcile %s as of %s — see %s\n' "$verdict" "$ts" "$_RECEIPTS" > "$_STATUS"
    fi
}

# Detached: the triggering tool call must not wait on a git fetch or a uv sync.
( _run_tick >/dev/null 2>&1 & ) >/dev/null 2>&1

exit 0
