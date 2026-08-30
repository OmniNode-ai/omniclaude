#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# SessionStart workspace-sync line (OMN-17190)
# ============================================
#
# Prints ONE line at session start:
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
# Contract
# --------
#   Reads:   $ONEX_HOOKS_STATE_DIR/workspace-reconcile.status  (only)
#   Writes:  stdout only.
#   Blocks:  never. Exit 0 on every path, including a missing status file.
#
# Why it reads a file instead of computing the answer
# ---------------------------------------------------
# Deriving this live means `git rev-parse` per clone plus a `uv sync --check`
# per venv -- seconds, measured, on a path contracted to be fast. So the tick
# (workspace_reconcile_tick.sh) does the work on its own schedule and leaves a
# one-line verdict; this hook prints it. The cost here is one `cat`.
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

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || _SCRIPT_DIR="."

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

_STATE_DIR="${ONEX_HOOKS_STATE_DIR:-${HOME}/.onex_state/hooks}"
_STATUS="${_STATE_DIR}/workspace-reconcile.status"

if [[ ! -r "$_STATUS" ]]; then
    # Honest unknown. Never render "no data" as "in sync" -- that is the exact
    # substitution this hook exists to prevent.
    say "UNKNOWN: no reconcile tick has run yet on this host."
    say "  The tick (workspace_reconcile_tick.sh) writes its verdict here:"
    say "    $_STATUS"
    say "  To settle it now:"
    say "    bash \$OMNI_HOME/omnibase_infra/scripts/reconcile-workspace-venvs.sh --check"
    exit 0
fi

_line="$(head -n1 "$_STATUS" 2>/dev/null)"
[[ -n "$_line" ]] || exit 0

# Age from the file's own mtime -- the tick rewrites the file every run, so
# mtime is the verdict's age by construction and needs no parsing.
_mtime="$(date -u -r "$_STATUS" +%s 2>/dev/null || stat -c %Y "$_STATUS" 2>/dev/null || echo "")"
if [[ -n "$_mtime" ]]; then
    _age_min=$(( ( $(date -u +%s) - _mtime ) / 60 ))
    (( _age_min < 0 )) && _age_min=0
    if (( _age_min > _STALE_MINUTES )); then
        say "$_line"
        say "  (verdict is ${_age_min}m old — older than ${_STALE_MINUTES}m, so treat it as unproven)"
        exit 0
    fi
    say "$_line (checked ${_age_min}m ago)"
    exit 0
fi

# No readable mtime: age unknown, which must never render as fresh.
say "$_line"
say "  (verdict age UNKNOWN — treat it as unproven)"
exit 0
