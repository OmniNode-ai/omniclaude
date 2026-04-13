#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Agent Dispatch Gate [OMN-8510]
#
# Hard-blocks any direct Agent() call that is not routed through
# /onex:dispatch_worker. Reads the session skill-context sentinel written by
# post-skill-delegation-enforcer.sh to determine the active skill.
#
# Pass conditions (exit 0):
#   - Active skill is "onex:dispatch_worker" or "dispatch_worker"
#   - Agent subagent_type is "agent-task-verifier" (verifier self-dispatch exempt)
#   - Kill switch AGENT_DISPATCH_GATE_DISABLED=1
#   - Lite mode
#   - Sentinel file unreadable (fail open)
#
# Block condition (exit 2):
#   - Agent tool called with any other skill context (or no skill context)
#
# Hook registration: hooks.json PreToolUse, matcher "^Agent$"
# Insert BEFORE existing pre_tool_use_dispatch_mode_guardrail.sh entry.
#
# Ticket: OMN-8510

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Kill switch — fail open when disabled
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat
    exit 0
fi
if [[ "${AGENT_DISPATCH_GATE_DISABLED:-0}" == "1" ]]; then
    cat
    exit 0
fi

# --- Lite mode guard [OMN-5398] ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _SCRIPT_DIR _MODE_SH

cd "$HOME" 2>/dev/null || cd /tmp || true

source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${ONEX_STATE_DIR:-/tmp}/hooks/logs/agent-dispatch-gate.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Guard: jq required
if ! command -v jq >/dev/null 2>&1; then
    cat
    exit 0
fi

TOOL_INFO=$(cat)

# Only intercept Agent tool (matcher should guarantee this, but double-check)
TOOL_NAME=$(printf '%s\n' "$TOOL_INFO" | jq -r '.tool_name // ""' 2>/dev/null) || TOOL_NAME=""
if [[ "$TOOL_NAME" != "Agent" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

TIMESTAMP="$(date -u +%FT%TZ)"

# Exempt: agent-task-verifier subagent_type (verifier is spawned by dispatch_worker itself)
SUBAGENT_TYPE=$(printf '%s\n' "$TOOL_INFO" | jq -r '.tool_input.subagent_type // ""' 2>/dev/null) || SUBAGENT_TYPE=""
if [[ "$SUBAGENT_TYPE" == "agent-task-verifier" ]]; then
    echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] PASS subagent_type=agent-task-verifier (exempt)" >> "$LOG_FILE" 2>/dev/null || true
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Read session skill-context sentinel
SESSION_ID=$(printf '%s\n' "$TOOL_INFO" | jq -r '.session_id // .sessionId // ""' 2>/dev/null) || SESSION_ID=""
CONTEXT_FILE="${ONEX_STATE_DIR:-/tmp}/hooks/skill-context/${SESSION_ID}.json"

ACTIVE_SKILL=""
if [[ -n "$SESSION_ID" && -f "$CONTEXT_FILE" ]]; then
    ACTIVE_SKILL=$(jq -r '.skill_name // ""' "$CONTEXT_FILE" 2>/dev/null) || ACTIVE_SKILL=""
fi

# Pass if active skill is dispatch_worker
if [[ "$ACTIVE_SKILL" == "onex:dispatch_worker" || "$ACTIVE_SKILL" == "dispatch_worker" ]]; then
    echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] PASS skill=${ACTIVE_SKILL}" >> "$LOG_FILE" 2>/dev/null || true
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Fail open if sentinel is unreadable (no session_id, missing file)
if [[ -z "$SESSION_ID" || ! -f "$CONTEXT_FILE" ]]; then
    echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] PASS (no sentinel — fail open) session_id=${SESSION_ID}" >> "$LOG_FILE" 2>/dev/null || true
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Block: direct Agent() call outside dispatch_worker context
AGENT_NAME=$(printf '%s\n' "$TOOL_INFO" | jq -r '.tool_input.name // "(unnamed)"' 2>/dev/null) || AGENT_NAME="(unnamed)"
echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] BLOCK agent=${AGENT_NAME} active_skill=${ACTIVE_SKILL}" >> "$LOG_FILE" 2>/dev/null || true

printf '%s\n' "$TOOL_INFO"
echo "BLOCKED: Direct Agent() calls are not permitted. Use /onex:dispatch_worker for all implementation dispatches. (active skill: ${ACTIVE_SKILL:-none})" >&2
exit 2
