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

# Extract skill name for the message
SKILL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_input.skill // .tool_input.name // "unknown"' 2>/dev/null) || SKILL_NAME="unknown"

# Output delegation enforcement reminder as hookSpecificOutput
# Claude Code injects this as a <system-reminder> in the next turn
jq -n \
    --arg skill_name "$SKILL_NAME" \
    '{
        hookSpecificOutput: {
            additionalContext: ("⛔ DELEGATION ENFORCER — skill [" + $skill_name + "] loaded.\n\nYou MUST delegate this work to a subagent. Your FIRST and ONLY action must be:\n\n  Agent(subagent_type=\"onex:polymorphic-agent\", prompt=\"<full skill prompt here>\", description=\"<5-word description>\")\n\nDo NOT read files, run bash, make plans, or execute any steps yourself.\nDo NOT summarize the skill and then do the work inline.\nDo NOT narrate what you are about to do — just spawn the agent.\n\nException: informational skills (e.g. onex:using-superpowers, onex:onex-status) that only return information without doing work may be handled inline.")
        }
    }'

exit 0
