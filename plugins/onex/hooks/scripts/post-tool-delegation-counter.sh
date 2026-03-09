#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse: Delegation Counter
#
# Tracks write/modify-tool calls per turn. After BLOCK_THRESHOLD write/edit/bash
# calls without an Agent spawn, exits 2 (hard-block) to prevent inline execution.
# Read-only tools are tracked separately and never trigger a block.
#
# Write/modify tools counted (trigger block): Write, Edit, Bash, MultiEdit
# Read-only tools counted (advisory only, never block): Read, Glob, Grep, WebFetch, WebSearch
# Delegation detected: Task tool (what Agent() maps to at hook level)
# Advisory warning fires once per turn at WARN_THRESHOLD (WARNED_FILE prevents spamming)
# Hard block fires on every write/modify call above BLOCK_THRESHOLD (no delegation)
#
# State files (keyed by session ID, reset by UserPromptSubmit hook):
#   /tmp/omniclaude-write-count-{session}  — integer count of write/modify tools
#   /tmp/omniclaude-read-count-{session}   — integer count of read-only tools
#   /tmp/omniclaude-delegated-{session}    — touch file: agent was spawned
#   /tmp/omniclaude-warned-{session}       — touch file: advisory warning already sent

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

WRITE_COUNTER_FILE="/tmp/omniclaude-write-count-${SESSION_ID}"
READ_COUNTER_FILE="/tmp/omniclaude-read-count-${SESSION_ID}"
DELEGATED_FILE="/tmp/omniclaude-delegated-${SESSION_ID}"
WARNED_FILE="/tmp/omniclaude-warned-${SESSION_ID}"

# Task = Agent() was called — mark delegated, reset write counter, pass through
if [[ "$TOOL_NAME" == "Task" ]]; then
    touch "$DELEGATED_FILE" 2>/dev/null || true
    echo "0" > "$WRITE_COUNTER_FILE" 2>/dev/null || true
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Meta/conversational tools — skip counting entirely
case "$TOOL_NAME" in
    Agent|AskUserQuestion|ExitPlanMode|EnterPlanMode|EnterWorktree|TeamCreate|TeamDelete|SendMessage|TaskCreate|TaskUpdate|TaskGet|TaskList)
        printf '%s\n' "$TOOL_INFO"
        exit 0
        ;;
esac

# Classify tool: write/modify vs read-only
IS_WRITE_TOOL=0
case "$TOOL_NAME" in
    Write|Edit|MultiEdit|Bash)
        IS_WRITE_TOOL=1
        ;;
    Read|Glob|Grep|WebFetch|WebSearch)
        IS_WRITE_TOOL=0
        ;;
esac

WARN_THRESHOLD=3    # advisory warning fires at this many write calls
BLOCK_THRESHOLD=5   # hard block fires at this many write calls (no delegation)

if [[ "$IS_WRITE_TOOL" -eq 1 ]]; then
    # Write/modify tool — increment write counter
    WRITE_COUNT=0
    if [[ -f "$WRITE_COUNTER_FILE" ]]; then
        WRITE_COUNT=$(cat "$WRITE_COUNTER_FILE" 2>/dev/null || echo "0")
        [[ "$WRITE_COUNT" =~ ^[0-9]+$ ]] || WRITE_COUNT=0
    fi
    WRITE_COUNT=$((WRITE_COUNT + 1))
    echo "$WRITE_COUNT" > "$WRITE_COUNTER_FILE" 2>/dev/null || true

    # If delegation already happened, allow write tools freely
    if [[ -f "$DELEGATED_FILE" ]]; then
        printf '%s\n' "$TOOL_INFO"
        exit 0
    fi

    # Hard block: write tools above BLOCK_THRESHOLD without any delegation
    if [[ "$WRITE_COUNT" -gt "$BLOCK_THRESHOLD" ]]; then
        jq -n \
            --argjson count "$WRITE_COUNT" \
            --arg tool "$TOOL_NAME" \
            --argjson threshold "$BLOCK_THRESHOLD" \
            '{
                hookSpecificOutput: {
                    additionalContext: ("DELEGATION ENFORCER [HARD BLOCK]: " + ($count | tostring) + " write/modify tool calls (" + $tool + " just now) without dispatching to a polymorphic agent. This tool call is BLOCKED. You MUST dispatch to onex:polymorphic-agent before continuing. Pattern: Agent(subagent_type=\"onex:polymorphic-agent\", description=\"...\", prompt=\"...\"). Inline work above the threshold is not permitted.")
                }
            }'
        exit 2
    fi

    # Advisory warning: fire once at WARN_THRESHOLD
    if [[ "$WRITE_COUNT" -ge "$WARN_THRESHOLD" ]] && [[ ! -f "$WARNED_FILE" ]]; then
        touch "$WARNED_FILE" 2>/dev/null || true
        jq -n \
            --argjson count "$WRITE_COUNT" \
            --arg tool "$TOOL_NAME" \
            --argjson block_threshold "$BLOCK_THRESHOLD" \
            '{
                hookSpecificOutput: {
                    additionalContext: ("DELEGATION ENFORCER [WARNING]: " + ($count | tostring) + " write tool calls (" + $tool + " just now) without delegating. Hard block fires at " + ($block_threshold | tostring) + ". STOP and dispatch: Agent(subagent_type=\"onex:polymorphic-agent\", description=\"...\", prompt=\"...\"). Continuing inline fills the context window.")
                }
            }'
    fi

    printf '%s\n' "$TOOL_INFO"
    exit 0

else
    # Read-only tool — increment read counter (advisory tracking only, never blocks)
    READ_COUNT=0
    if [[ -f "$READ_COUNTER_FILE" ]]; then
        READ_COUNT=$(cat "$READ_COUNTER_FILE" 2>/dev/null || echo "0")
        [[ "$READ_COUNT" =~ ^[0-9]+$ ]] || READ_COUNT=0
    fi
    READ_COUNT=$((READ_COUNT + 1))
    echo "$READ_COUNT" > "$READ_COUNTER_FILE" 2>/dev/null || true

    printf '%s\n' "$TOOL_INFO"
    exit 0
fi
