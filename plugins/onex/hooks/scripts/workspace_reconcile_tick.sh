#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Workspace reconcile tick (OMN-17190)
# ===================================
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
#   1. `git fetch` each canonical clone
#   2. where the tracked branch moved and the tree is CLEAN, `git pull --ff-only`
#   3. if anything moved, run omnibase_infra/scripts/reconcile-workspace-venvs.sh
#   4. write a receipt line naming each repo, its old -> new SHA, and the venv
#      sync result, plus a one-line status the SessionStart hook reads
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
# Never pulls into a dirty clone
# ------------------------------
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

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || _SCRIPT_DIR="."

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

mkdir -p "$_STATE_DIR" "$(dirname "$_RECEIPTS")" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Throttle
# ---------------------------------------------------------------------------
_now="$(date -u +%s)"
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
_run_tick() {
    local ts moved=0 dirty_repos="" moved_repos="" repo dir branch local_sha remote_sha
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    for dir in "$OMNI_HOME"/*/; do
        [[ -d "${dir}.git" ]] || continue
        repo="$(basename "$dir")"

        branch="$(git -C "$dir" branch --show-current 2>/dev/null)"
        # Only the tracking branches are ours to advance. A canonical clone
        # parked on a feature branch is somebody's deliberate state.
        [[ "$branch" == "dev" || "$branch" == "main" ]] || continue

        git -C "$dir" fetch --quiet --prune origin "$branch" 2>/dev/null || continue

        local_sha="$(git -C "$dir" rev-parse HEAD 2>/dev/null)"
        remote_sha="$(git -C "$dir" rev-parse "origin/$branch" 2>/dev/null)"
        [[ -n "$local_sha" && -n "$remote_sha" ]] || continue
        [[ "$local_sha" != "$remote_sha" ]] || continue

        if [[ -n "$(git -C "$dir" status --porcelain 2>/dev/null)" ]]; then
            # Reported, never touched. See the header for why.
            printf '%s repo=%s branch=%s status=DIRTY head=%s remote=%s action=none\n' \
                "$ts" "$repo" "$branch" "${local_sha:0:12}" "${remote_sha:0:12}" \
                >> "$_RECEIPTS"
            dirty_repos="${dirty_repos}${repo} "
            continue
        fi

        if git -C "$dir" pull --ff-only --quiet origin "$branch" 2>/dev/null; then
            printf '%s repo=%s branch=%s status=PULLED old=%s new=%s\n' \
                "$ts" "$repo" "$branch" "${local_sha:0:12}" "${remote_sha:0:12}" \
                >> "$_RECEIPTS"
            moved=1
            moved_repos="${moved_repos}${repo} "
        else
            printf '%s repo=%s branch=%s status=NOT_FF head=%s remote=%s action=none\n' \
                "$ts" "$repo" "$branch" "${local_sha:0:12}" "${remote_sha:0:12}" \
                >> "$_RECEIPTS"
            dirty_repos="${dirty_repos}${repo}(not-ff) "
        fi
    done

    # ---- venv reconcile ---------------------------------------------------
    local reconciler venv_result="skipped"
    reconciler="$OMNI_HOME/omnibase_infra/scripts/reconcile-workspace-venvs.sh"

    if [[ "$moved" -eq 1 && -f "$reconciler" ]]; then
        if bash "$reconciler" --omni-home "$OMNI_HOME" >>"$_RECEIPTS" 2>&1; then
            venv_result="ok"
        else
            venv_result="FAILED"
        fi
    elif [[ -f "$reconciler" ]]; then
        # Nothing pulled, but the venv can still be behind -- another session's
        # pull-all, or a `uv sync` someone ran by hand, moves it independently.
        # --check is read-only and cheap, so a no-movement tick still notices.
        if bash "$reconciler" --check --omni-home "$OMNI_HOME" >/dev/null 2>&1; then
            venv_result="ok"
        else
            venv_result="drift"
            if bash "$reconciler" --omni-home "$OMNI_HOME" >>"$_RECEIPTS" 2>&1; then
                venv_result="ok"
            else
                venv_result="FAILED"
            fi
        fi
    fi

    printf '%s tick=complete pulled="%s" dirty="%s" venv=%s\n' \
        "$ts" "${moved_repos% }" "${dirty_repos% }" "$venv_result" >> "$_RECEIPTS"

    # ---- one-line status for the SessionStart hook ------------------------
    # A file, not a computation: SessionStart is contracted to be fast, and
    # re-deriving this there would mean a `uv` invocation on every session open.
    if [[ "$venv_result" == "FAILED" ]]; then
        printf 'DRIFT: venv reconcile FAILED as of %s — see %s\n' "$ts" "$_RECEIPTS" > "$_STATUS"
    elif [[ -n "$dirty_repos" ]]; then
        printf 'DRIFT: %s not pulled (dirty or non-ff) as of %s\n' "${dirty_repos% }" "$ts" > "$_STATUS"
    else
        printf 'clones/venv: in sync as of %s\n' "$ts" > "$_STATUS"
    fi
}

# Detached: the triggering tool call must not wait on a git fetch or a uv sync.
( _run_tick >/dev/null 2>&1 & ) >/dev/null 2>&1

exit 0
