#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# =============================================================================
# OmniClaude Hooks - Global Error Guard (OMN-3724)
# =============================================================================
# Sourced as the VERY FIRST thing in every hook script, BEFORE common.sh.
# Sets an EXIT trap that catches any non-zero exit code. On error:
#   1. Drains stdin (prevents Claude Code from hanging on unread pipe)
#   2. Sends a Slack alert (best-effort, no dependencies)
#   3. Logs the failure to a file
#   4. Exits 0 so Claude Code never sees the failure
#
# Why EXIT, not ERR:
#   An ERR trap only fires on command failures under `set -e`. An explicit
#   `exit 1` (like common.sh's hard-fail) does NOT trigger ERR -- it triggers
#   shell termination and the EXIT trap. Since common.sh calls `exit 1`
#   directly, only an EXIT trap catches it.
#
# Dependencies: curl (best-effort). No Python, no jq, no common.sh.
#
# Integration (add these lines at the top of every hook, after set -euo pipefail):
#   _OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
#   source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true
# =============================================================================

# The caller must set _OMNICLAUDE_HOOK_NAME before sourcing this file.
# Fall back to "unknown-hook" if not set.
_OMNICLAUDE_HOOK_NAME="${_OMNICLAUDE_HOOK_NAME:-unknown-hook}"

# Standalone hooks source error-guard before common.sh, and some never source
# common.sh at all. Load the bitmask gate here so ONEX_HOOKS_MASK checks are
# available before hook-specific behavior starts.
source "$(dirname "${BASH_SOURCE[0]}")/hook-gate.sh" 2>/dev/null || true

# Outcome-checked alert delivery (OMN-15600). Curl-only, no common.sh dependency.
# shellcheck source=./alert-channel.sh
source "$(dirname "${BASH_SOURCE[0]}")/alert-channel.sh" 2>/dev/null || true

# Log directory for error-guard failures (created lazily on first error)
_ERROR_GUARD_LOG_DIR="${_ERROR_GUARD_LOG_DIR:-${TMPDIR:-/tmp}/omniclaude-error-guard}"
mkdir -p "$_ERROR_GUARD_LOG_DIR" 2>/dev/null || true

# Structured log file — one file per hook, appended to
_ERROR_GUARD_LOG_FILE="${_ERROR_GUARD_LOG_DIR}/${_OMNICLAUDE_HOOK_NAME}.log"

# Cache hostname once at source time (no subshell if HOSTNAME is set)
_ERROR_GUARD_HOST="${HOSTNAME:-$(hostname -s 2>/dev/null || echo unknown)}"

# --- Logger function ---
# Usage: _log "message" or _log "ERROR" "message"
# Writes to per-hook log file. Does NOT touch stdout/stderr.
_log() {
    local level="INFO"
    local msg="$1"
    if [[ $# -ge 2 ]]; then
        level="$1"
        msg="$2"
    fi
    printf "[%s] [%s] [%s] %s\n" \
        "$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "?")" \
        "$_OMNICLAUDE_HOOK_NAME" \
        "$level" \
        "$msg" \
        >> "$_ERROR_GUARD_LOG_FILE" 2>/dev/null || true
}

# Opt-in verbose mode: emit hook status to stderr when OMNICLAUDE_HOOK_VERBOSE=1
_hook_status() {
    if [[ "${OMNICLAUDE_HOOK_VERBOSE:-0}" == "1" ]]; then
        local status="$1"
        local detail="${2:-}"
        local elapsed="${3:-?}"
        if [[ -n "$detail" ]]; then
            echo "[$_OMNICLAUDE_HOOK_NAME] $status: $detail (${elapsed}ms)" >&2 || true
        else
            echo "[$_OMNICLAUDE_HOOK_NAME] $status (${elapsed}ms)" >&2 || true
        fi
    fi
}

# =============================================================================
# Refusal Recorder (OMN-18946)
# =============================================================================
# Give a refusal a durable, aggregated home. A guard that refuses a tool call
# writes its reason to the operator's terminal, which is gone at the end of
# the turn, and to a per-hook log file under a temporary directory that
# nothing reads. Neither is aggregated, so a guard refusing the same correct
# command forty times in a night produces forty invisible events and the
# morning friction sweep finds nothing.
#
# WHY IT LIVES HERE. error-guard.sh is sourced as the VERY FIRST thing in
# every hook, before common.sh and without depending on it, so this function
# is in scope on every refusal path in the tree including the hooks that
# never source common.sh at all. It could not live in common.sh for that
# reason.
#
# WHY NOT THE EXIT TRAP. The obvious seam would be the EXIT trap below, which
# already sees every non-zero exit. It cannot serve: a deny path runs
# `trap - EXIT` before `exit 2` precisely so the trap does not swallow the
# deny, and 48 of the 52 scripts carrying a deny do exactly that. The trap
# never fires on a refusal. Each deny site therefore calls this explicitly,
# and tests/hooks/test_refusal_rows_omn18946.py is the ratchet that fails when
# a registered hook grows a deny path that does not.
#
# Backgrounded and disowned like emit_to_journal: the operator's refusal
# message must never wait on a ledger lock. Fail-open by construction — every
# failure inside the recorder is swallowed there, and this function returns 0
# whatever happens, because a recorder that could break a guard would be
# worse than the gap it fills.
#
# Usage: hook_record_refusal <reason> [detail]
#
#   reason   the refusal CLASS. Every guard already computes one for its own
#            log line, so call sites pass that rather than inventing a token.
#            The recorder NORMALISES it into the dedupe key: lowercased,
#            slugified, with path-like and digit-heavy segments dropped. That
#            normalisation is what bounds cardinality — a raw reason carrying
#            an interpolated file path would make every refusal unique and
#            defeat the rate limit entirely, which is the failure mode that
#            would turn this from a fix into a second flood.
#   detail   the refusal's first line. Redacted and truncated by the recorder,
#            so it is safe to pass the exact message the operator sees.
#
# The guard is always $_OMNICLAUDE_HOOK_NAME, which every hook sets before
# sourcing this file. Taking it as an argument would let two call sites in one
# script disagree about which guard they belong to.

hook_record_refusal() {
    local guard="${_OMNICLAUDE_HOOK_NAME:-unknown-hook}"
    local reason="${1:-unspecified}"
    local detail="${2:-}"

    local lib_dir="${HOOKS_LIB:-}"
    if [[ -z "$lib_dir" ]]; then
        lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" 2>/dev/null && pwd)" || lib_dir=""
    fi
    local recorder="${lib_dir}/hook_refusal_recorder.py"
    [[ -f "$recorder" ]] || return 0

    local py="${PYTHON_CMD:-}"
    if [[ -z "$py" ]]; then
        if [[ -n "${ONEX_REGISTRY_ROOT:-}" && -x "${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3" ]]; then
            py="${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3"
        elif command -v python3 >/dev/null 2>&1; then
            py="python3"
        else
            return 0
        fi
    fi

    # The lane is resolved against the directory the HOOK fired in, not this
    # backgrounded process's cwd — the same correction OMN-18609 made for
    # emit_to_journal, for the same reason.
    local cwd="${CLAUDE_PROJECT_DIR:-$PWD}"

    (
        "$py" "$recorder" \
            --guard "$guard" \
            --reason "$reason" \
            --detail "$detail" \
            --cwd "$cwd" \
            --transcript-path "${TRANSCRIPT_PATH:-}" \
            --session-id "${SESSION_ID:-}" \
            --agent-id "${AGENT_ID:-}" \
            >>"${LOG_FILE:-/dev/null}" 2>&1
    ) &
    disown 2>/dev/null || true
    return 0
}


# --- ERR trap ---
# Captures the failing command and line number BEFORE the EXIT trap fires.
# Stores in a variable that the EXIT trap can read.
_ERROR_GUARD_LAST_ERR=""
_omniclaude_error_guard_err_trap() {
    _ERROR_GUARD_LAST_ERR="line ${BASH_LINENO[0]} in ${BASH_SOURCE[1]:-unknown}: $(HISTTIMEFORMAT= history 1 2>/dev/null | sed 's/^ *[0-9]* *//' || echo '?')"
}
trap '_omniclaude_error_guard_err_trap' ERR

_omniclaude_error_guard_trap() {
    local exit_code=$?

    # Exit 0 means normal termination -- nothing to do
    if [[ $exit_code -eq 0 ]]; then
        return 0
    fi

    # --- 1. Drain stdin to prevent Claude Code from hanging on unread pipe ---
    while IFS= read -r -t 0.01 _discard 2>/dev/null; do :; done || true

    # --- 2. Log the failure with context ---
    local log_file="${_ERROR_GUARD_LOG_DIR}/errors.log"
    {
        printf "[%s] HOOK FAILURE: %s exited with code %d\n" \
            "$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "unknown")" \
            "$_OMNICLAUDE_HOOK_NAME" \
            "$exit_code"
        if [[ -n "${_ERROR_GUARD_LAST_ERR:-}" ]]; then
            printf "  at: %s\n" "$_ERROR_GUARD_LAST_ERR"
        fi
    } >> "$log_file" 2>/dev/null || true
    # Also log to per-hook file
    _log "ERROR" "exit code $exit_code${_ERROR_GUARD_LAST_ERR:+ at $_ERROR_GUARD_LAST_ERR}"

    # --- 3. Send Slack alert (outcome-checked; a dead channel is recorded, not
    #        discarded — OMN-15600). Never changes this trap's exit 0.
    #        SLACK_WEBHOOK_URL is retired; the bot token is the sole channel. ---
    local _alert_configured=0
    if [[ -n "${SLACK_BOT_TOKEN:-}" ]] && [[ -n "${SLACK_CHANNEL_ID:-}" ]]; then
        _alert_configured=1
    fi
    if [[ "$_alert_configured" -eq 1 ]]; then
        # Rate limiting: one alert per hook per 5 minutes
        local rate_dir="${_ERROR_GUARD_LOG_DIR}/rate"
        mkdir -p "$rate_dir" 2>/dev/null || true
        # Sanitize hook name for safe filename
        local safe_name
        safe_name=$(printf '%s' "$_OMNICLAUDE_HOOK_NAME" | tr -cd 'a-zA-Z0-9_-')
        [[ -z "$safe_name" ]] && safe_name="unknown"
        local rate_file="${rate_dir}/${safe_name}.last"
        local should_send=true

        if [[ -f "$rate_file" ]]; then
            local last_sent
            last_sent=$(cat "$rate_file" 2>/dev/null) || last_sent=0
            [[ "$last_sent" =~ ^[0-9]+$ ]] || last_sent=0
            local now
            now=$(date -u +%s 2>/dev/null) || now=0
            if (( now - last_sent < 300 )); then
                should_send=false
            fi
        fi

        if [[ "$should_send" == "true" ]]; then
            local msg="[error-guard][${_ERROR_GUARD_HOST}] Hook '${_OMNICLAUDE_HOOK_NAME}' crashed with exit code ${exit_code}. Swallowed to protect Claude Code."

            # Record the attempt regardless of outcome so a dead channel does
            # not cost a curl on every crash; alert_channel_send records the
            # delivery failure durably and raises a local notification.
            date -u +%s > "$rate_file" 2>/dev/null || true

            if ! declare -F alert_channel_send >/dev/null 2>&1; then
                # alert-channel.sh failed to source — that is itself a broken
                # alerting path and must not pass as a successful send.
                _log "ERROR" "alert-channel.sh unavailable; hook-crash alert not delivered"
            else
                alert_channel_send "error_guard_${safe_name}" "$msg" || \
                    _log "ERROR" "hook-crash alert delivery failed (see alert delivery log)"
            fi
        fi
    fi

    # --- 4. Emit structured hook health error to Kafka (wire-missing-producers) ---
    # Uses PYTHON_CMD and HOOKS_LIB if already set (common.sh was sourced before trap fired).
    # Falls back to hook_error_emitter directly if available. Fire-and-forget.
    (
        _eg_python="${PYTHON_CMD:-}"
        _eg_hooks_lib="${HOOKS_LIB:-}"

        # Resolve Python if not already set by common.sh
        if [[ -z "$_eg_python" ]]; then
            # Try ONEX_REGISTRY_ROOT-based venv first, then system python3
            if [[ -n "${ONEX_REGISTRY_ROOT:-}" && -x "${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3" ]]; then
                _eg_python="${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3"
            elif command -v python3 >/dev/null 2>&1; then
                _eg_python="python3"
            fi
        fi

        # Resolve hooks lib if not already set by common.sh
        if [[ -z "$_eg_hooks_lib" ]]; then
            _eg_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
            _eg_hooks_lib="${_eg_script_dir}/../lib"
        fi

        [[ -z "$_eg_python" ]] && exit 0
        [[ ! -f "${_eg_hooks_lib}/hook_error_emitter.py" ]] && exit 0

        # Write error message to temp file (SECURITY: avoid shell interpolation into python -c)
        _eg_tmp=$(mktemp "/tmp/omniclaude-hook-err-XXXXXX" 2>/dev/null) || exit 0
        printf '%s' "Hook '${_OMNICLAUDE_HOOK_NAME}' crashed with exit code ${exit_code}${_ERROR_GUARD_LAST_ERR:+: ${_ERROR_GUARD_LAST_ERR}}" > "$_eg_tmp"

        "$_eg_python" -m plugins.onex.hooks.lib.hook_error_emitter \
            --hook-name "${_OMNICLAUDE_HOOK_NAME:-unknown}" \
            --error-file "$_eg_tmp" \
            --session-id "${SESSION_ID:-unknown}" \
            --python-version "$("$_eg_python" --version 2>&1)" \
            2>/dev/null || true

        rm -f "$_eg_tmp" 2>/dev/null || true
    ) >/dev/null 2>&1 &

    # --- 5. Exit 0 so Claude Code never sees the failure ---
    exit 0
}

# Install the EXIT trap. This fires on ANY shell exit (including `exit 1`).
trap '_omniclaude_error_guard_trap' EXIT
