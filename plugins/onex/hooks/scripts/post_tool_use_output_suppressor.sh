#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Output Suppressor Hook [OMN-6733]
# Reduces Claude context token usage by suppressing verbose output from
# skill-related commands (pytest, mypy, ruff, pre-commit, etc.)
#
# Budget: <50ms (Python does the detection; most invocations are passthrough)
# Safety: Always exits 0. Errors pass through unchanged.

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
LOG_FILE="${HOOKS_DIR}/logs/output-suppressor.log"

# Detect project root
PROJECT_ROOT="${PLUGIN_ROOT}/../.."
if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"
fi

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Source common.sh for PYTHON_CMD
source "${HOOKS_DIR}/scripts/common.sh"

SUPPRESSOR="${HOOKS_LIB}/skill_output_suppressor.py"
if [[ ! -f "$SUPPRESSOR" ]]; then
    cat  # pass through unchanged
    exit 0
fi

# Read stdin, pipe through suppressor, output result
TOOL_INFO=$(cat)

# Quick check: only process Bash tool calls (avoid Python startup for non-Bash)
TOOL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_name // ""' 2>/dev/null) || TOOL_NAME=""
if [[ "$TOOL_NAME" != "Bash" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Run suppressor
RESULT=$(printf '%s' "$TOOL_INFO" | "$PYTHON_CMD" "$SUPPRESSOR" 2>>"$LOG_FILE") || {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Suppressor failed, passing through" >> "$LOG_FILE"
    printf '%s\n' "$TOOL_INFO"
    exit 0
}

printf '%s\n' "$RESULT"
exit 0
