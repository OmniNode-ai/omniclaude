#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse TDD Dispatch Gate (OMN-8846)
#
# Blocks Agent() and Task() dispatch unless ONEX_DISPATCH_TYPE is set to a
# recognized value and, for implementation dispatches, the prompt contains:
#   1. A "# failing-test:" reference, AND
#   2. A "dod_evidence:" block.
#
# Dispatch types:
#   research-only  → passes through, no TDD required
#   implementation → requires failing-test + dod_evidence in prompt
#   verification   → passes through, no TDD required
#   <unset/other>  → BLOCKED with instructions
#
# Hook registration: hooks.json PreToolUse, matcher "^(Agent|Task)$"

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

cd "$HOME" 2>/dev/null || cd /tmp || true

_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { echo "FATAL: ONEX_STATE_DIR not set" >&2; exit 1; }
LOG_FILE="${LOG_FILE:-${ONEX_HOOK_LOG}}"

mkdir -p "$(dirname "$LOG_FILE")"

TOOL_INFO=$(cat)

TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null) || {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ERROR: invalid hook JSON; failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
}

if [[ ! "$TOOL_NAME" =~ ^(Agent|Task)$ ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] Checking $TOOL_NAME for TDD clause (ONEX_DISPATCH_TYPE=${ONEX_DISPATCH_TYPE:-<unset>})" >> "$LOG_FILE"

source "${HOOKS_DIR}/scripts/common.sh"

set +e
GUARD_OUTPUT=$(echo "$TOOL_INFO" | \
    CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" \
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}" \
    $PYTHON_CMD -m omniclaude.hooks.pre_tool_use_tdd_dispatch_gate 2>>"$LOG_FILE")
GUARD_EXIT=$?
set -e

if [[ $GUARD_EXIT -eq 2 ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED $TOOL_NAME: TDD gate failed" >> "$LOG_FILE"
    printf '\a' >&2
    echo "$GUARD_OUTPUT"
    trap - EXIT
    exit 2
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ALLOWED $TOOL_NAME" >> "$LOG_FILE"
    echo "$GUARD_OUTPUT"
    exit 0
fi
