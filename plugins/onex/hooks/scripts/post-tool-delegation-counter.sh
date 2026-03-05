#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse: Delegation Counter
#
# Tracks work-tool calls per turn. After THRESHOLD calls without an Agent
# spawn, injects a single mid-execution warning into Claude's context.
#
# Work tools counted: Read, Write, Edit, Bash, Glob, Grep, WebFetch, WebSearch
# Delegation detected: Task tool (what Agent() maps to at hook level)
# Warning fires once per turn (WARNED_FILE prevents spamming)
#
# State files (keyed by session ID, reset by UserPromptSubmit hook):
#   /tmp/omniclaude-work-count-{session}   — integer count
#   /tmp/omniclaude-delegated-{session}    — touch file: agent was spawned
#   /tmp/omniclaude-warned-{session}       — touch file: warning already sent

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true
cd "$HOME" 2>/dev/null || cd /tmp || true

if ! command -v jq >/dev/null 2>&1; then
    cat
    exit 0
fi

TOOL_INFO=$(cat)
TOOL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_name // "unknown"' 2>/dev/null) || TOOL_NAME="unknown"
SESSION_ID=$(echo "$TOOL_INFO" | jq -r '.session_id // .sessionId // ""' 2>/dev/null) || SESSION_ID=""

# If session ID unavailable, pass through silently
if [[ -z "$SESSION_ID" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

COUNTER_FILE="/tmp/omniclaude-work-count-${SESSION_ID}"
DELEGATED_FILE="/tmp/omniclaude-delegated-${SESSION_ID}"
WARNED_FILE="/tmp/omniclaude-warned-${SESSION_ID}"

# Task = Agent() was called — mark delegated, no warning needed
if [[ "$TOOL_NAME" == "Task" ]]; then
    touch "$DELEGATED_FILE" 2>/dev/null || true
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Non-work tools (meta/conversational) — skip counting
case "$TOOL_NAME" in
    Agent|AskUserQuestion|ExitPlanMode|EnterPlanMode|EnterWorktree|TeamCreate|TeamDelete|SendMessage|TaskCreate|TaskUpdate|TaskGet|TaskList)
        printf '%s\n' "$TOOL_INFO"
        exit 0
        ;;
esac

# Work tool — increment counter
CURRENT_COUNT=0
if [[ -f "$COUNTER_FILE" ]]; then
    CURRENT_COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo "0")
    [[ "$CURRENT_COUNT" =~ ^[0-9]+$ ]] || CURRENT_COUNT=0
fi
CURRENT_COUNT=$((CURRENT_COUNT + 1))
echo "$CURRENT_COUNT" > "$COUNTER_FILE" 2>/dev/null || true

THRESHOLD=3

# No warning if: not over threshold, already delegated, or already warned this turn
if [[ "$CURRENT_COUNT" -lt "$THRESHOLD" ]] || [[ -f "$DELEGATED_FILE" ]] || [[ -f "$WARNED_FILE" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Inject warning — fires exactly once per turn at threshold
touch "$WARNED_FILE" 2>/dev/null || true

jq -n \
    --argjson count "$CURRENT_COUNT" \
    --arg tool "$TOOL_NAME" \
    '{
        hookSpecificOutput: {
            additionalContext: ("DELEGATION ENFORCER: " + ($count | tostring) + " work tool calls (" + $tool + " just now) without delegating. STOP. Choose one: multiple independent subtasks -> Skill(onex:parallel-solve) | single workflow -> Agent(subagent_type=onex:polymorphic-agent). Continuing inline fills the context window.")
        }
    }'

exit 0
