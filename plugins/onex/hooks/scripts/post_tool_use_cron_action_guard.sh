#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Cron-loop action enforcement guard — PostToolUse on CronCreate.
#
# (1) Warns when a cron loop appears passive (status-only prompt, no action
#     keywords). Uses both-side keyword logic to avoid false positives on
#     skill names like /onex:system_status.
# (2) Tracks the 3 mandatory session bootstrap crons from CLAUDE.md
#     §Session Bootstrap and writes .onex_state/session/cron_bootstrap.flag
#     once all 3 have been created. [OMN-8845]
#
# Exit codes:
#   0 — always (advisory only; never blocks cron creation)

set -eo pipefail

# Lite mode guard [OMN-5398]
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    source "$_MODE_SH"
    [[ "$(omniclaude_mode)" == "lite" ]] && exit 0
fi

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
LIB_PY="${PLUGIN_ROOT}/hooks/lib/cron_action_guard.py"

# Capture ONEX_STATE_DIR before common.sh can override it via ~/.omnibase/.env
_BOOTSTRAP_STATE_DIR="${ONEX_STATE_DIR:-}"

# common.sh provides PYTHON_CMD resolution and shared helpers.
# shellcheck source=/dev/null
source "${PLUGIN_ROOT}/hooks/scripts/common.sh"
unset _SCRIPT_DIR _MODE_SH

# Buffer stdin once so both the Python lib and the bootstrap check can use it.
STDIN_DATA="$(cat)"

if [[ ! -f "$LIB_PY" ]]; then
    # Library missing — pass through without blocking
    :
else
    PYTHON_BIN="${PYTHON_CMD:-python3}"
    echo "$STDIN_DATA" | "$PYTHON_BIN" "$LIB_PY"
fi

# --- Session bootstrap flag tracking [OMN-8845] ---
# When all 3 mandatory crons from CLAUDE.md §Session Bootstrap have been
# created in this session, write the bootstrap flag so Stop/UserPromptSubmit
# hooks can gate on it.
if [[ -n "${_BOOTSTRAP_STATE_DIR:-}" ]] && command -v jq >/dev/null 2>&1; then
    BOOTSTRAP_FLAG="${_BOOTSTRAP_STATE_DIR}/session/cron_bootstrap.flag"
    SEEN_DIR="${_BOOTSTRAP_STATE_DIR}/session/cron_bootstrap_seen"
    mkdir -p "$SEEN_DIR"

    PROMPT="$(echo "$STDIN_DATA" | jq -r '.tool_input.prompt // empty' 2>/dev/null || true)"

    if [[ -n "$PROMPT" ]]; then
        if echo "$PROMPT" | grep -q "Overseer tick"; then
            touch "${SEEN_DIR}/overseer"
        fi
        if echo "$PROMPT" | grep -q "Merge sweep"; then
            touch "${SEEN_DIR}/merge_sweep"
        fi
        if echo "$PROMPT" | grep -q "Dispatch haiku health worker"; then
            touch "${SEEN_DIR}/health_check"
        fi

        if [[ -f "${SEEN_DIR}/overseer" ]] && \
           [[ -f "${SEEN_DIR}/merge_sweep" ]] && \
           [[ -f "${SEEN_DIR}/health_check" ]]; then
            mkdir -p "$(dirname "$BOOTSTRAP_FLAG")"
            date -u +"%Y-%m-%dT%H:%M:%SZ" > "$BOOTSTRAP_FLAG"
        fi
    fi
fi

exit 0
