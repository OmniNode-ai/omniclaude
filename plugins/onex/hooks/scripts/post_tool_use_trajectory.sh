#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse PRM Trajectory Hook (OMN-10370)
# Appends each tool call to the PRM trajectory store, runs all 5 pattern
# detectors, and injects course-correction context when escalation fires.
# severity_level >= 1: additionalContext injected.
# severity_level == 3: exits 2 (hard stop).
#
# Event: PostToolUse | Matcher: .* | Ticket: OMN-10370
# name: "post_tool_use_trajectory"

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# --- Kill switches ---
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat; exit 0
fi
if [[ "${OMNICLAUDE_HOOK_PRM_TRAJECTORY:-1}" == "0" ]]; then
    cat; exit 0
fi

# --- Lite mode guard ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && { cat; exit 0; }; fi
unset _SCRIPT_DIR _MODE_SH

# Ensure stable CWD before any Python invocation.
cd "$HOME" 2>/dev/null || cd /tmp || true

# Portable plugin root resolution.
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"

# --- Log path ---
if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    echo "[$(date -u +%FT%TZ)] ERROR: ONEX_STATE_DIR unset; hook cannot write log." \
        >> /tmp/onex-hook-error.log
    cat; exit 0
fi
LOG_FILE="${ONEX_STATE_DIR}/hooks/logs/post-tool-use-trajectory.log"
mkdir -p "$(dirname "$LOG_FILE")"

# Source common utilities (provides PYTHON_CMD)
source "${HOOKS_DIR}/scripts/common.sh"

PROJECT_ROOT="${PLUGIN_ROOT}/../.."
export PYTHONPATH="${PROJECT_ROOT}/src:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

HOOK_EVENT=$(cat)
printf '%s\n' "$HOOK_EVENT"

# Run PRM trajectory hook in background — advisory, never blocks Claude Code UI.
# On severity_level == 3 the Python module would exit 2, but since we run in
# background (exit code lost) this is purely observational for now.
# TODO: promote to sync path once impact is measured (OMN-10370 follow-up).
(
    printf '%s\n' "$HOOK_EVENT" \
        | env -u PYTHONPATH \
              PYTHONPATH="${PROJECT_ROOT}/src:${PLUGIN_ROOT}/lib:${HOOKS_LIB}" \
              "$PYTHON_CMD" -m omniclaude.hooks.post_tool_use_trajectory \
              2>>"$LOG_FILE" || true
) &

exit 0
