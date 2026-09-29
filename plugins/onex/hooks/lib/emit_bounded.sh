#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Bounded, fail-loud hook emit (OMN-20110).
#
# On 2026-09-29 the operator Mac ran out of processes: every emitting hook
# forked its emitter into the background and disowned it, the emitters hung
# in a whole-journal directory scan, and ten thousand of them were orphaned
# to ppid 1 with nothing reporting it. Operator ruling, the same day: a hook
# may not fail silently; an emit that cannot complete stops the work and
# raises an alarm, and there is no alternate path.
#
# onex_emit_bounded runs one emit in the FOREGROUND through
# hook_emit_bounded.py, which gives it its own process group and a time
# budget (ONEX_HOOK_EMIT_BUDGET_S, default 30s), SIGKILLs the whole group on a
# miss, prints a blocking error naming the cause on stderr, raises one
# operator alarm per failure episode through alert-channel.sh, and exits 2.
#
# onex_emit_fail_exit is what a hook does next: exit 2, the blocking exit,
# so the tool call fails and the agent and operator see the cause. The one
# exception is a Stop or SubagentStop hook that is already re-running because
# of an earlier block (stop_hook_active true): blocking again would loop the
# agent forever on a failure it cannot fix, so it exits 1 (a hook error the
# harness shows) and the alarm that the first failure raised stands.
#
# There is deliberately no spool, no fail-open branch and no kill switch.
#
# Usage:
#   onex_emit_bounded <label> <cmd> [args...] || onex_emit_fail_exit "$INPUT"
#   printf '%s' "$INPUT" | onex_emit_bounded <label> <cmd> ... || onex_emit_fail_exit "$INPUT"
#
# Requires PYTHON_CMD. Uses HOOKS_LIB and LOG_FILE when set.

onex_emit_bounded() {
    local label="$1"
    shift
    local lib_dir="${HOOKS_LIB:-}"
    if [[ -z "$lib_dir" ]]; then
        lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || lib_dir=""
    fi
    local runner="${lib_dir}/hook_emit_bounded.py"
    if [[ -z "${PYTHON_CMD:-}" || ! -f "$runner" ]]; then
        echo "BLOCKED: hook emit '${label}' cannot run: PYTHON_CMD='${PYTHON_CMD:-}' runner='${runner}' (OMN-20110)" >&2
        return 2
    fi
    "$PYTHON_CMD" "$runner" --label "$label" --log "${LOG_FILE:-/dev/null}" -- "$@"
}

onex_emit_fail_exit() {
    local input="${1:-}"
    if [[ "$input" =~ \"stop_hook_active\"[[:space:]]*:[[:space:]]*true ]]; then
        exit 1
    fi
    exit 2
}
