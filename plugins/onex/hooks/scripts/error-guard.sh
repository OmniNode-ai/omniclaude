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

# Log directory for error-guard failures (created lazily on first error)
_ERROR_GUARD_LOG_DIR="${_ERROR_GUARD_LOG_DIR:-${TMPDIR:-/tmp}/omniclaude-error-guard}"

# Cache hostname once at source time (no subshell if HOSTNAME is set)
_ERROR_GUARD_HOST="${HOSTNAME:-$(hostname -s 2>/dev/null || echo unknown)}"

_omniclaude_error_guard_trap() {
    local exit_code=$?

    # Exit 0 means normal termination -- nothing to do
    if [[ $exit_code -eq 0 ]]; then
        return 0
    fi

    # --- 1. Drain stdin to prevent Claude Code from hanging on unread pipe ---
    # Use a timeout read loop to consume any remaining stdin without blocking.
    # The dd approach is faster but not universally available with timeout;
    # read -t 0.01 is POSIX-ish and safe.
    while IFS= read -r -t 0.01 _discard 2>/dev/null; do :; done || true

    # --- 2. Log the failure to a file ---
    mkdir -p "$_ERROR_GUARD_LOG_DIR" 2>/dev/null || true
    local log_file="${_ERROR_GUARD_LOG_DIR}/errors.log"
    {
        printf "[%s] HOOK FAILURE: %s exited with code %d\n" \
            "$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "unknown")" \
            "$_OMNICLAUDE_HOOK_NAME" \
            "$exit_code"
    } >> "$log_file" 2>/dev/null || true

    # --- 3. Send Slack alert (best-effort, no dependencies beyond curl) ---
    local webhook_url="${SLACK_WEBHOOK_URL:-}"
    if [[ -n "$webhook_url" ]] && command -v curl >/dev/null 2>&1; then
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
            # Simple JSON payload without jq (manual escaping)
            local msg="[error-guard][${_ERROR_GUARD_HOST}] Hook '${_OMNICLAUDE_HOOK_NAME}' crashed with exit code ${exit_code}. Swallowed to protect Claude Code."
            # Escape backslashes and double quotes for JSON
            msg="${msg//\\/\\\\}"
            msg="${msg//\"/\\\"}"

            curl -s -S --connect-timeout 1 --max-time 2 \
                -H 'Content-Type: application/json' \
                -d "{\"text\": \"${msg}\"}" \
                --url "$webhook_url" >/dev/null 2>&1 || true

            date -u +%s > "$rate_file" 2>/dev/null || true
        fi
    fi

    # --- 4. Exit 0 so Claude Code never sees the failure ---
    exit 0
}

# Install the EXIT trap. This fires on ANY shell exit (including `exit 1`).
trap '_omniclaude_error_guard_trap' EXIT
