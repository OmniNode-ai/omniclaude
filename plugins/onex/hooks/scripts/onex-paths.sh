#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Shell path resolver for ONEX state directory.
# Source this file to export derived path variables.
#
# Requires an explicit ONEX_STATE_DIR or an absolute OMNI_HOME registry root.

if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    if [[ "${OMNI_HOME:-}" != /* ]]; then
        printf '%s\n' 'onex-paths: OMNI_HOME must name an absolute registry root when ONEX_STATE_DIR is unset' >&2
        return 1
    fi
    export ONEX_STATE_DIR="${OMNI_HOME}/.onex_state"
fi
if [[ "$ONEX_STATE_DIR" != /* ]]; then
    printf '%s\n' 'onex-paths: ONEX_STATE_DIR must be absolute' >&2
    return 1
fi

export ONEX_LOG_DIR="${ONEX_STATE_DIR}/logs"
export ONEX_HOOKS_STATE_DIR="${ONEX_STATE_DIR}/hooks"
export ONEX_PIPELINES_DIR="${ONEX_STATE_DIR}/pipelines"
export ONEX_SESSION_STATE_DIR="${ONEX_STATE_DIR}/sessions"
# The guard-sweep reads hooks/ (not the general logs/ partition).
export ONEX_HOOK_LOG="${ONEX_HOOKS_STATE_DIR}/logs/hooks.log"
export ONEX_HANDOFF_DIR="${ONEX_STATE_DIR}/handoff"
export ONEX_WORKTREES_DIR="${ONEX_STATE_DIR}/worktrees"

# --- Hook log rotation (OMN-19519) ---
# hooks.log is appended by every hook that sources this file, and it reached
# 436 MB on the operator Mac with nothing rotating it. The bound is the OMN-8429
# knob, ONEX_HOOK_LOG_MAX_MB (default 50); ONEX_HOOK_LOG_BACKUPS (default 3)
# numbered backups are kept, so one log never holds more than about 200 MB.
# The whole file moves to .1 on rotation, so nothing written before it is lost
# until it ages past the last backup.
#
# onex_rotate_log_if_over <file> [max_bytes] [backups]
#   Rotates <file> when it is over the bound. Always returns 0: a hook must
#   never fail because its log could not be rotated. A mkdir lock keeps two
#   hooks from rotating at once; a lock older than a minute belongs to a
#   rotator that died, and is broken.
onex_rotate_log_if_over() {
    local file="${1:-}"
    [[ -n "$file" && -f "$file" ]] || return 0
    local max_mb="${ONEX_HOOK_LOG_MAX_MB:-50}"
    [[ "$max_mb" =~ ^[0-9]+$ && "$max_mb" -gt 0 ]] || max_mb=50
    local max_bytes="${2:-}"
    if [[ -z "$max_bytes" ]]; then
        max_bytes=$(( max_mb * 1048576 ))
    fi
    local backups="${3:-${ONEX_HOOK_LOG_BACKUPS:-3}}"
    [[ "$max_bytes" =~ ^[0-9]+$ && "$max_bytes" -gt 0 ]] || return 0
    [[ "$backups" =~ ^[0-9]+$ && "$backups" -gt 0 ]] || backups=3

    local size
    size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)
    [[ "$size" =~ ^[0-9]+$ && "$size" -gt "$max_bytes" ]] || return 0

    local lock="${file}.rotate.lock"
    if ! mkdir "$lock" 2>/dev/null; then
        [[ -n "$(find "$lock" -maxdepth 0 -mmin +1 2>/dev/null)" ]] || return 0
        rmdir "$lock" 2>/dev/null || return 0
        mkdir "$lock" 2>/dev/null || return 0
    fi
    # Re-read under the lock: a rotator that just finished leaves a fresh file.
    size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)
    if [[ "$size" =~ ^[0-9]+$ && "$size" -gt "$max_bytes" ]]; then
        local i
        rm -f "${file}.${backups}" 2>/dev/null || true
        for (( i = backups - 1; i >= 1; i-- )); do
            if [[ -f "${file}.${i}" ]]; then
                mv -f "${file}.${i}" "${file}.$(( i + 1 ))" 2>/dev/null || true
            fi
        done
        mv -f "$file" "${file}.1" 2>/dev/null || true
    fi
    rmdir "$lock" 2>/dev/null || true
    return 0
}

# onex_maybe_rotate_log <file>
#   The per-hook call site. The size check forks stat, so it runs on one hook
#   invocation in sixteen: hooks fire several times a minute, so the bound is
#   still enforced within minutes, at a sixteenth of the cost.
onex_maybe_rotate_log() {
    # OMN-20109: the sixteenth invocation, counted in a file beside the log with
    # builtins only, not drawn from $RANDOM. A random draw made the check's stat
    # exec land in a different tool call each run, so one tool call's process
    # count varied on an unchanged tree. A fresh state directory starts at zero
    # and does not check until the sixteenth hook.
    local file="${1:-}" tick_file n=0
    [[ -n "$file" ]] || return 0
    tick_file="${file}.tick"
    [[ -r "$tick_file" ]] && { read -r n < "$tick_file" || true; }
    [[ "$n" =~ ^[0-9]+$ ]] || n=0
    n=$(( n + 1 ))
    if (( n >= 16 )); then
        n=0
        { printf '%s\n' "$n" > "$tick_file"; } 2>/dev/null || true
        onex_rotate_log_if_over "$file" || true
    else
        { printf '%s\n' "$n" > "$tick_file"; } 2>/dev/null || true
    fi
    return 0
}

onex_maybe_rotate_log "$ONEX_HOOK_LOG"
