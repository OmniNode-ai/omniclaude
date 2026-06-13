#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Output Suppressor Hook [OMN-6733, rewritten OMN-13095]
# Layer C backstop of the skill-output-suppression plan (epic OMN-13089):
# captures verbose matched Bash output to the content-addressed artifact
# store, then replaces the Claude-visible tool result via
# hookSpecificOutput.updatedToolOutput (object form — probe OMN-13090).
#
# Protocol (probe-verified, CLI 2.1.175):
#   - Passthrough emits NOTHING on stdout (plain stdout is debug-log-only).
#   - Suppression emits exactly ONE JSON object: the hookSpecificOutput
#     envelope (with "hookEventName": "PostToolUse") produced by
#     skill_output_suppressor.py.
#
# Budget: <100ms (Python does the detection; most invocations are passthrough)
# Safety: Always exits 0. On any failure the original output reaches Claude.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# --- Lite mode guard [OMN-5398] ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _SCRIPT_DIR _MODE_SH

# Ensure stable CWD
cd "$HOME" 2>/dev/null || cd /tmp || true

# Resolve paths
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"

# --- Log path: ONEX_STATE_DIR/hooks/logs/ [OMN-8429] ---
# Passthrough = NO stdout (OMN-13095): without ONEX_STATE_DIR we cannot log
# or derive the artifact store root, so exit silently — the model sees the
# original tool output unchanged.
if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    echo "[$(date -u +%FT%TZ)] ERROR: ONEX_STATE_DIR unset; suppressor passthrough." \
        >> /tmp/onex-hook-error.log
    exit 0
fi
LOG_FILE="${ONEX_STATE_DIR}/hooks/logs/output-suppressor.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Detect project root (required by common.sh)
PROJECT_ROOT="${PLUGIN_ROOT}/../.."
if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"
fi

# --- Artifact store root injection [OMN-13095, probe OMN-13090 Probe 4] ---
# Hook processes inherit ONEX_STATE_DIR but NOT ONEX_ARTIFACT_STORE_ROOT.
# The artifact store fails fast (KeyError) without it, so derive it here
# from the canonical state convention. No hardcoded absolute paths.
export ONEX_ARTIFACT_STORE_ROOT="${ONEX_ARTIFACT_STORE_ROOT:-${ONEX_STATE_DIR}/artifacts}"

# Source common.sh for PYTHON_CMD
source "${HOOKS_DIR}/scripts/common.sh"
onex_hook_gate POST_TOOL_OUTPUT_SUPPRESSOR || exit 0

SUPPRESSOR="${HOOKS_LIB}/skill_output_suppressor.py"
if [[ ! -f "$SUPPRESSOR" ]]; then
    # Passthrough: emit nothing.
    exit 0
fi

# Read stdin once.
TOOL_INFO=$(cat)

# Quick check: only process Bash tool calls (avoid Python startup for non-Bash)
TOOL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_name // ""' 2>/dev/null) || TOOL_NAME=""
if [[ "$TOOL_NAME" != "Bash" ]]; then
    exit 0
fi

# Run suppressor. Python prints either nothing (passthrough) or exactly one
# hookSpecificOutput JSON object (suppression). Its stderr goes to the log.
RESULT=$(printf '%s' "$TOOL_INFO" | "$PYTHON_CMD" "$SUPPRESSOR" 2>>"$LOG_FILE") || {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Suppressor failed, passthrough (no output)" >> "$LOG_FILE"
    exit 0
}

if [[ -n "$RESULT" ]]; then
    printf '%s\n' "$RESULT"
fi
exit 0
