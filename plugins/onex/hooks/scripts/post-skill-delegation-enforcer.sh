#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Skill Delegation Enforcer
#
# Fires after every Skill tool invocation and injects a mandatory delegation
# reminder into Claude's context. This prevents the main context from being
# consumed by long-running workflow skills.
#
# Output format: hookSpecificOutput.additionalContext → injected as system-reminder

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true
# shellcheck source=hook-runtime-client.sh
source "$(dirname "${BASH_SOURCE[0]}")/hook-runtime-client.sh" 2>/dev/null || true

# --- Lite mode guard [OMN-5398] ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _SCRIPT_DIR _MODE_SH

cd "$HOME" 2>/dev/null || cd /tmp || true

# Guard: jq required
if ! command -v jq >/dev/null 2>&1; then
    cat  # drain stdin
    exit 0
fi

# Read stdin
TOOL_INFO=$(cat)

# Extract tool name (safety check — matcher should ensure this is always "Skill")
TOOL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_name // "unknown"' 2>/dev/null) || TOOL_NAME="unknown"
if [[ "$TOOL_NAME" != "Skill" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Extract skill name and session ID
SKILL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_input.skill // .tool_input.name // "unknown"' 2>/dev/null) || SKILL_NAME="unknown"
SESSION_ID=$(echo "$TOOL_INFO" | jq -r '.session_id // .sessionId // ""' 2>/dev/null) || SESSION_ID=""

# Notify daemon that a skill was loaded (tightens thresholds) [OMN-5308]
if [[ -n "$SESSION_ID" ]]; then
    _hrt_request "{\"action\":\"set_skill_loaded\",\"session_id\":\"${SESSION_ID}\",\"payload\":{}}" > /dev/null 2>&1 || true
fi

# Output delegation enforcement reminder as hookSpecificOutput
# Claude Code injects this as a <system-reminder> in the next turn
jq -n \
    --arg skill_name "$SKILL_NAME" \
    '{
        hookSpecificOutput: {
            additionalContext: ("⛔ DELEGATION ENFORCER — skill [" + $skill_name + "] loaded.\n\nYou MUST delegate this work to a subagent. Your FIRST and ONLY action must be:\n\n  Agent(subagent_type=\"onex:polymorphic-agent\", prompt=\"<full skill prompt here>\", description=\"<5-word description>\")\n\nDo NOT read files, run bash, make plans, or execute any steps yourself.\nDo NOT summarize the skill and then do the work inline.\nDo NOT narrate what you are about to do — just spawn the agent.\n\nException: informational skills (e.g. onex:using-superpowers, onex:onex-status) that only return information without doing work may be handled inline.")
        }
    }'

# Set skill-loaded flag for delegation counter (tighter thresholds until delegation occurs)
SESSION_ID=$(echo "$TOOL_INFO" | jq -r '.session_id // .sessionId // ""' 2>/dev/null) || SESSION_ID=""
if [[ -n "$SESSION_ID" ]]; then
    touch "/tmp/omniclaude-skill-loaded-${SESSION_ID}" 2>/dev/null || true
fi

exit 0
