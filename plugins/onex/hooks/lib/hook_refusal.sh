#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# =============================================================================
# Refusal Recorder seam (OMN-18946, OMN-19381)
# =============================================================================
# Give a refusal a durable, aggregated home. A guard that refuses a tool call
# writes its reason to the operator's terminal, which is gone at the end of
# the turn, and to a per-hook log file under a temporary directory that
# nothing reads. Neither is aggregated, so a guard refusing the same correct
# command forty times in a night produces forty invisible events and the
# morning friction sweep finds nothing.
#
# WHERE IT IS SOURCED. error-guard.sh sources this file, so every hook that
# sources error-guard.sh first has the function in scope, including the hooks
# that never source common.sh. A guard that must NOT source error-guard.sh --
# its EXIT trap turns an `exit 2` that is not preceded by `trap - EXIT` into
# `exit 0`, which would turn the refusal into an allow -- sources this file
# directly instead (OMN-19381). Before that, six registered guards called this
# function without it in scope, and `2>/dev/null || true` silenced the
# command-not-found: their refusals were recorded nowhere.
#
# WHY NOT THE EXIT TRAP. The obvious seam would be error-guard.sh's EXIT trap,
# which already sees every non-zero exit. It cannot serve: a deny path runs
# `trap - EXIT` before `exit 2` precisely so the trap does not swallow the
# deny. The trap never fires on a refusal. Each deny site therefore calls this
# explicitly, and tests/hooks/test_refusal_rows_omn18946.py is the ratchet
# that fails when a registered hook grows a deny path that does not.
#
# THE PAYLOAD (OMN-19381). The facts that name a lane -- the transcript path
# and agent id that locate the harness's sidecar, the cwd, the paths the tool
# call names -- are in the hook's own stdin payload, which the guard has
# already read. The caller exposes it as _OMNICLAUDE_HOOK_PAYLOAD (TOOL_INFO
# and STDIN_JSON, the names the guards already used, are read as fallbacks).
# It reaches the recorder on its STDIN, never on argv: a Workflow payload
# carries the whole script, and argv is size-capped and readable by every
# process on the machine. The environment operands stay as fallbacks.
#
# Backgrounded and disowned like emit_to_journal: the operator's refusal
# message must never wait on a ledger lock. The subshell's own stdout and
# stderr are redirected, not only the recorder's: the Bash-guard entrypoint
# captures each guard's output with $(...), and a background job still
# holding that pipe would make the capture wait for the recorder. Fail-open
# by construction -- this function returns 0 whatever happens.
#
# WHERE THE RECORDING LIVES (OMN-20685). omniclaude's node_hook_refusal_record_effect:
# this seam makes one process call into its handler module (`python -m`, with
# the plugin hook library named by --hooks-lib so the handler can import its
# siblings), and hook_refusal_detail asks the same module to extract a verdict's
# diagnostic. It replaced the standalone recorder and lane-resolver scripts.
#
# Usage: hook_record_refusal <reason> [detail]
#
#   reason   the refusal CLASS. The recorder normalises it into the dedupe
#            key: lowercased, slugified, path-like and digit-heavy segments
#            dropped, so an interpolated path cannot make every refusal unique.
#   detail   the refusal's first line. Redacted and truncated by the recorder.
#
# The guard is always $_OMNICLAUDE_HOOK_NAME, which every recording hook sets
# before sourcing this file (pinned by tests/hooks/test_refusal_row_lane_omn19381.py).

# This file's directory, made absolute NOW: several guards `cd "$HOME"` after
# sourcing, and a relative path resolved at call time would then miss the
# recorder. No exec and no fork (OMN-20109).
_ONEX_HOOK_REFUSAL_LIB="${BASH_SOURCE[0]%/*}"
[[ "${BASH_SOURCE[0]}" == */* ]] || _ONEX_HOOK_REFUSAL_LIB=.
[[ "$_ONEX_HOOK_REFUSAL_LIB" == /* ]] || _ONEX_HOOK_REFUSAL_LIB="${PWD}/${_ONEX_HOOK_REFUSAL_LIB}"

# The handler module of node_hook_refusal_record_effect, the one entry the guards call.
_ONEX_HOOK_REFUSAL_MODULE="omniclaude.nodes.node_hook_refusal_record_effect.handlers.handler_hook_refusal_record"

# The interpreter that runs the recorder: the plugin's own, never a bare system
# python3 that lacks omniclaude when a venv that has it exists (OMN-20883).
# Same order as common.sh's find_python(), minus the lite-mode system python.
_hook_refusal_python() {
    local candidate root
    root="${_ONEX_HOOK_REFUSAL_LIB}/../../../.."
    for candidate in \
        "${PYTHON_CMD:-}" \
        "${PLUGIN_PYTHON_BIN:-}" \
        "${CLAUDE_PLUGIN_DATA:+${CLAUDE_PLUGIN_DATA}/.venv/bin/python3}" \
        "${root}/.venv/bin/python3" \
        "${ONEX_REGISTRY_ROOT:+${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3}"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    command -v python3 2>/dev/null
}

# True when the recorder's stderr says its interpreter could not import it.
_hook_refusal_is_import_failure() {
    [[ "$1" == *"No module named"* \
        || "$1" == *"Error while finding module specification"* \
        || "$1" == *"is not importable by this interpreter"* ]]
}

# A FRICTION row written with the shell alone, for the one case the recorder
# cannot run (OMN-20883). No redactor is available here, so the refusal's own
# text is withheld; the guard, the lane variable and the cause are enough to
# find the refusal in hooks.log. The recorder's hourly rate limit is not
# available here, so this path writes one row per refusal: a broken recorder is
# the loud case, and a loud row is the point.
_hook_refusal_fallback_row() {
    local guard="$1" lane="" lane_source="unresolved" root project ledger row ts
    root="${OMNI_HOME:-${ONEX_REGISTRY_ROOT:-}}"
    [[ "$root" == /* ]] || return 0
    project="${OMNIBASE_INTERNAL_HOME:-${root%/*}/omnibase_internal}"
    ledger="${ONEX_LEDGER_PATH:-${root}/docs/tracking/ROLLING_WORK_LEDGER.md}"
    [[ -f "$project/pyproject.toml" && -f "$ledger" ]] || return 0
    lane="${ONEX_LANE:-${ONEX_LANE_ID:-${ONEX_AGENT_NAME:-${CLAUDE_AGENT_NAME:-}}}}"
    lane="$(printf '%s\n' "$lane" | sed -e 's/ROUTE:.*//' | sed -n '/[^[:space:]]/{p;q;}' \
        | tr -c 'A-Za-z0-9._:@/\n-' '-' | cut -c1-120)"
    if [[ -n "$lane" ]]; then lane_source="fallback-env"; else lane="unresolved"; fi
    guard="$(printf '%s' "$guard" | tr -c 'A-Za-z0-9._:@/-' '-' | cut -c1-120)"
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    row="${ts} | FRICTION | lane=${lane} | actor=hook | model=none | class=refusal | guard=${guard}"
    row+=" | reason=recorder-import-failure | lane_source=${lane_source} | dedupe=fallback-${guard}"
    row+=" | refusal_count=1 | suppressed_since_last_row=0"
    row+=' | detail="recorder interpreter cannot import its row module; refusal text withheld, see hooks.log"'
    row+=" | existing=OMN-20883 | cost=~1 lane-minute | This row exists because the hook refusal recorder could not run (OMN-20883)"
    uv run --quiet --project "$project" onex-ledger "$ledger" --append "$row" --timeout 120s || true
}

hook_record_refusal() {
    local guard="${_OMNICLAUDE_HOOK_NAME:-unknown-hook}"
    local reason="${1:-unspecified}"
    local detail="${2:-}"
    local payload="${_OMNICLAUDE_HOOK_PAYLOAD:-${TOOL_INFO:-${STDIN_JSON:-}}}"

    local lib_dir="${HOOKS_LIB:-$_ONEX_HOOK_REFUSAL_LIB}"

    local py
    py="$(_hook_refusal_python)" || return 0

    # The fallback cwd when the payload carries none: the directory the HOOK
    # fired in, not this backgrounded process's -- the OMN-18609 correction.
    local cwd="${CLAUDE_PROJECT_DIR:-$PWD}"

    (
        local err rc=0
        err="$(
            "$py" -P -m "$_ONEX_HOOK_REFUSAL_MODULE" \
                --hooks-lib "$lib_dir" \
                --guard "$guard" \
                --reason "$reason" \
                --detail "$detail" \
                --cwd "$cwd" \
                --transcript-path "${TRANSCRIPT_PATH:-}" \
                --session-id "${SESSION_ID:-}" \
                --agent-id "${AGENT_ID:-}" \
                --payload-stdin \
                < <(printf '%s\n' "$payload") 2>&1
        )" || rc=$?
        [[ -z "$err" ]] || printf '%s\n' "$err"
        # An interpreter that cannot import the row module records nothing
        # itself (OMN-20883): leave the refusal a row of its own.
        if [[ $rc -ne 0 ]] && _hook_refusal_is_import_failure "$err"; then
            _hook_refusal_fallback_row "$guard"
        fi
    ) >>"${LOG_FILE:-/dev/null}" 2>&1 </dev/null &
    disown 2>/dev/null || true
    return 0
}

# Decode ONLY the decision envelope, never the hook input. Keeps the missing
# evidence before the truncation limit and redacts before returning to shell.
hook_refusal_detail() {
    local py="${PYTHON_CMD:-python3}"
    "$py" -P -m "$_ONEX_HOOK_REFUSAL_MODULE" --hooks-lib "${HOOKS_LIB:-$_ONEX_HOOK_REFUSAL_LIB}" --extract-detail \
        || printf 'rule=diagnostic_unavailable exit=%s\n' "$?"
}
