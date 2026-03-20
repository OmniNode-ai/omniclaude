#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Context Scope Auditor — PreToolUse hook (OMN-5237)
#
# Runs AFTER the poly enforcer for every tool call within an active task.
# Audits tool scope and context budget constraints declared in the task contract.
#
# Delegates to omniclaude.hooks.handlers.context_scope_auditor via Python.
#
# Exit codes:
#   0 — allow the tool call
#   2 — block the tool call (STRICT/PARANOID mode violations only)

set -eo pipefail

_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"

# --- Lite mode guard [OMN-5398] ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _SCRIPT_DIR _MODE_SH

# Resolve plugin root
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR

source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { echo "ONEX_STATE_DIR not set" >&2; exit 1; }
LOG_FILE="${ONEX_HOOK_LOG}"
mkdir -p "$(dirname "$LOG_FILE")"

# Read stdin
INPUT=$(cat)

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] Running context scope audit" >> "$LOG_FILE"

# Invoke the Python handler.
# The handler reads the hook JSON from stdin, audits it, and either:
#   - Prints the original JSON and exits 0 (allow)
#   - Prints a block decision JSON and exits 2 (block)
PYTHON_CMD="${PYTHON_CMD:-python3}"

EXIT_CODE=0
RESULT=$(echo "$INPUT" | PYTHONPATH="${PLUGIN_ROOT}/../../src:${PYTHONPATH:-}" \
    "$PYTHON_CMD" -m omniclaude.hooks.handlers.context_scope_auditor 2>>"$LOG_FILE") \
    || EXIT_CODE=$?

if [[ $EXIT_CODE -eq 2 ]]; then
    echo "$RESULT"
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED by context scope auditor" >> "$LOG_FILE"
    exit 2
fi

# Pass through (allow)
echo "$RESULT"
exit 0
