#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# UserPromptSubmit: Delegation Rule Injector
#
# On every user prompt:
#   1. Resets per-turn work-tool counter and state flags
#   2. Injects a hard delegation rule into Claude's context

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true
cd "$HOME" 2>/dev/null || cd /tmp || true

if ! command -v jq >/dev/null 2>&1; then
    cat  # drain stdin
    exit 0
fi

TOOL_INFO=$(cat)
SESSION_ID=$(echo "$TOOL_INFO" | jq -r '.sessionId // .session_id // ""' 2>/dev/null) || SESSION_ID=""

# Reset per-turn delegation state
if [[ -n "$SESSION_ID" ]]; then
    echo "0" > "/tmp/omniclaude-work-count-${SESSION_ID}" 2>/dev/null || true
    rm -f "/tmp/omniclaude-delegated-${SESSION_ID}" "/tmp/omniclaude-warned-${SESSION_ID}" 2>/dev/null || true
fi

# Build the rule text via a variable to avoid jq escaping issues
RULE_TEXT="DELEGATION RULE: For any task requiring more than 2 tool calls, delegate as your FIRST action — before any reads, writes, or bash calls:
• Multiple independent subtasks (check N repos, run N tests, scan N files) → Skill('onex:parallel-solve')
• Single coherent task or workflow → Agent(subagent_type='onex:polymorphic-agent', prompt='...', description='...')
Conversational responses are exempt."

jq -n --arg msg "$RULE_TEXT" '{
    hookSpecificOutput: {
        additionalContext: $msg
    }
}'

exit 0
