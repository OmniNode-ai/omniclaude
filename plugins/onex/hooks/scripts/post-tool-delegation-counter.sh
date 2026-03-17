#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse: Delegation Counter
#
# Tracks write/modify and read-only tool calls per turn. After configurable
# thresholds without an Agent spawn, exits 2 (hard-block) to prevent inline
# execution. Thresholds are read from config.yaml via delegation-config.sh.
#
# Write/modify tools counted: Write, Edit, Bash (mutating), MultiEdit
# Read-only tools counted: Read, Glob, Grep, WebFetch, WebSearch, Bash (read-only)
# Delegation detected: Task tool (what Agent() maps to at hook level)
#
# Thresholds (from config.yaml delegation_enforcement section):
#   write_warn_threshold  — advisory warning (fires once per turn)
#   write_block_threshold — hard block (exit 2)
#   read_warn_threshold   — advisory warning for read-only tools
#   read_block_threshold  — hard block for read-only tools
#   total_block_threshold — hard block on combined read+write count
#   skill_loaded.*        — tighter thresholds when a Skill was loaded without delegation
#
# State files (keyed by session ID, reset by UserPromptSubmit hook):
#   /tmp/omniclaude-write-count-{session}   — integer count of write/modify tools
#   /tmp/omniclaude-read-count-{session}    — integer count of read-only tools
#   /tmp/omniclaude-delegated-{session}     — touch file: agent was spawned
#   /tmp/omniclaude-write-warned-{session}  — touch file: write warning already sent
#   /tmp/omniclaude-read-warned-{session}   — touch file: read warning already sent
#   /tmp/omniclaude-skill-loaded-{session}  — touch file: skill was loaded (set by post-skill-delegation-enforcer.sh)

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
# Resolve script dir before cd $HOME (relative paths break after cwd change)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/error-guard.sh" 2>/dev/null || true
# shellcheck source=hook-runtime-client.sh
source "${SCRIPT_DIR}/hook-runtime-client.sh" 2>/dev/null || true
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

# --- Source config reader (resilient — fallback to legacy defaults on any failure) ---
_DC_LOADED=0
if source "${SCRIPT_DIR}/delegation-config.sh" 2>/dev/null; then
    _DC_LOADED=1
fi

# --- Read thresholds from config ---
if [[ "$_DC_LOADED" -eq 1 ]]; then
    WRITE_WARN=$(_dc_read '.write_warn_threshold' '3') || WRITE_WARN=3
    WRITE_BLOCK=$(_dc_read '.write_block_threshold' '5') || WRITE_BLOCK=5
    READ_WARN=$(_dc_read '.read_warn_threshold' '-1') || READ_WARN=-1
    READ_BLOCK=$(_dc_read '.read_block_threshold' '-1') || READ_BLOCK=-1
    TOTAL_BLOCK=$(_dc_read '.total_block_threshold' '-1') || TOTAL_BLOCK=-1
else
    # Legacy defaults — no read enforcement
    WRITE_WARN=3
    WRITE_BLOCK=5
    READ_WARN=-1
    READ_BLOCK=-1
    TOTAL_BLOCK=-1
fi

# --- State files ---
WRITE_COUNTER_FILE="/tmp/omniclaude-write-count-${SESSION_ID}"
READ_COUNTER_FILE="/tmp/omniclaude-read-count-${SESSION_ID}"
DELEGATED_FILE="/tmp/omniclaude-delegated-${SESSION_ID}"
WRITE_WARNED_FILE="/tmp/omniclaude-write-warned-${SESSION_ID}"
READ_WARNED_FILE="/tmp/omniclaude-read-warned-${SESSION_ID}"
SKILL_LOADED_FILE="/tmp/omniclaude-skill-loaded-${SESSION_ID}"

# --- Skill-loaded override ---
# When a skill was loaded but no delegation happened, use tighter thresholds
if [[ -f "$SKILL_LOADED_FILE" ]] && [[ ! -f "$DELEGATED_FILE" ]] && [[ "$_DC_LOADED" -eq 1 ]]; then
    WRITE_BLOCK=$(_dc_read '.skill_loaded.write_block_threshold' "$WRITE_BLOCK") || true
    READ_BLOCK=$(_dc_read '.skill_loaded.read_block_threshold' "$READ_BLOCK") || true
    TOTAL_BLOCK=$(_dc_read '.skill_loaded.total_block_threshold' "$TOTAL_BLOCK") || true
fi

# --- Task = Agent() was called — notify daemon + mark delegated locally, pass through ---
if [[ "$TOOL_NAME" == "Task" ]]; then
    _hrt_request "{\"action\":\"mark_delegated\",\"session_id\":\"${SESSION_ID}\",\"payload\":{}}" > /dev/null 2>&1 || true
    touch "$DELEGATED_FILE" 2>/dev/null || true
    echo "0" > "$WRITE_COUNTER_FILE" 2>/dev/null || true
    echo "0" > "$READ_COUNTER_FILE" 2>/dev/null || true
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# --- Meta/conversational tools — skip counting entirely ---
case "$TOOL_NAME" in
    Agent|AskUserQuestion|ExitPlanMode|EnterPlanMode|EnterWorktree|TeamCreate|TeamDelete|SendMessage|TaskCreate|TaskUpdate|TaskGet|TaskList|TaskOutput|TaskStop)
        printf '%s\n' "$TOOL_INFO"
        exit 0
        ;;
esac

# --- Classify tool: write/modify vs read-only ---
IS_WRITE_TOOL=0
case "$TOOL_NAME" in
    Write|Edit|MultiEdit|Bash)
        IS_WRITE_TOOL=1
        ;;
    Read|Glob|Grep|WebFetch|WebSearch)
        IS_WRITE_TOOL=0
        ;;
esac

# For Bash: apply compound command guard FIRST, then read-only classification.
# Compound commands are never eligible for read-only classification regardless of prefix.
if [[ "$TOOL_NAME" == "Bash" && "$IS_WRITE_TOOL" -eq 1 ]]; then
    BASH_CMD=$(printf '%s' "$TOOL_INFO" | jq -r '.tool_input.command // ""' 2>/dev/null) || BASH_CMD=""

    # Compound command guard — check deny patterns from config
    IS_COMPOUND=0
    while IFS= read -r deny_pat; do
        [[ -z "$deny_pat" ]] && continue
        if printf '%s' "$BASH_CMD" | grep -qE "$deny_pat" 2>/dev/null; then
            IS_COMPOUND=1
            break
        fi
    done < <(_dc_read_array '.bash_compound_deny_patterns')

    # Only attempt read-only classification if not a compound command
    if [[ "$IS_COMPOUND" -eq 0 ]]; then
        while IFS= read -r ro_pat; do
            [[ -z "$ro_pat" ]] && continue
            if printf '%s' "$BASH_CMD" | grep -qE "$ro_pat" 2>/dev/null; then
                IS_WRITE_TOOL=0
                break
            fi
        done < <(_dc_read_array '.bash_readonly_patterns')
    fi
fi

# --- Daemon-first path [OMN-5308] ---
# Try the hook runtime daemon first. If the daemon is running and responds,
# use its decision directly (daemon owns all threshold state).
# Fall back to the shell-based enforcement below if daemon is unavailable.
if [[ -S "$HOOK_RUNTIME_SOCKET" ]]; then
    TOOL_INPUT_JSON=$(echo "$TOOL_INFO" | jq -c '.tool_input // {}' 2>/dev/null) || TOOL_INPUT_JSON="{}"
    DAEMON_RESPONSE=$(_hrt_request "{\"action\":\"classify_tool\",\"session_id\":\"${SESSION_ID}\",\"payload\":{\"tool_name\":\"${TOOL_NAME}\",\"tool_input\":${TOOL_INPUT_JSON}}}" 2>/dev/null) || DAEMON_RESPONSE=""
    if [[ -n "$DAEMON_RESPONSE" ]]; then
        DAEMON_DECISION=$(echo "$DAEMON_RESPONSE" | jq -r '.decision // "pass"' 2>/dev/null) || DAEMON_DECISION="pass"
        DAEMON_MESSAGE=$(echo "$DAEMON_RESPONSE" | jq -r '.message // empty' 2>/dev/null) || DAEMON_MESSAGE=""
        case "$DAEMON_DECISION" in
            block)
                jq -n --arg msg "${DAEMON_MESSAGE}" \
                    '{ hookSpecificOutput: { additionalContext: $msg } }'
                exit 2
                ;;
            warn)
                if [[ -n "$DAEMON_MESSAGE" ]]; then
                    jq -n --arg msg "${DAEMON_MESSAGE}" \
                        '{ hookSpecificOutput: { additionalContext: $msg } }'
                fi
                printf '%s\n' "$TOOL_INFO"
                exit 0
                ;;
            *)
                # pass or ack — allow through
                printf '%s\n' "$TOOL_INFO"
                exit 0
                ;;
        esac
    fi
fi
# --- End daemon-first path; fall through to shell-based enforcement ---

# --- Increment appropriate counter ---
if [[ "$IS_WRITE_TOOL" -eq 1 ]]; then
    # Write/modify tool — increment write counter
    WRITE_COUNT=0
    if [[ -f "$WRITE_COUNTER_FILE" ]]; then
        WRITE_COUNT=$(cat "$WRITE_COUNTER_FILE" 2>/dev/null || echo "0")
        [[ "$WRITE_COUNT" =~ ^[0-9]+$ ]] || WRITE_COUNT=0
    fi
    WRITE_COUNT=$((WRITE_COUNT + 1))
    echo "$WRITE_COUNT" > "$WRITE_COUNTER_FILE" 2>/dev/null || true

    # If delegation already happened, allow freely
    if [[ -f "$DELEGATED_FILE" ]]; then
        printf '%s\n' "$TOOL_INFO"
        exit 0
    fi

    # Read the current read count for total calculation
    READ_COUNT=0
    if [[ -f "$READ_COUNTER_FILE" ]]; then
        READ_COUNT=$(cat "$READ_COUNTER_FILE" 2>/dev/null || echo "0")
        [[ "$READ_COUNT" =~ ^[0-9]+$ ]] || READ_COUNT=0
    fi

    # Total block (read + write combined)
    TOTAL=$((WRITE_COUNT + READ_COUNT))
    if [[ "$TOTAL_BLOCK" -ne -1 ]] && [[ "$TOTAL" -gt "$TOTAL_BLOCK" ]]; then
        jq -n \
            --argjson count "$TOTAL" \
            --arg tool "$TOOL_NAME" \
            --argjson threshold "$TOTAL_BLOCK" \
            '{
                hookSpecificOutput: {
                    additionalContext: ("DELEGATION ENFORCER [HARD BLOCK]: " + ($count | tostring) + " total tool calls (" + $tool + " just now) without dispatching to a polymorphic agent. This tool call is BLOCKED. You MUST dispatch to onex:polymorphic-agent before continuing. Pattern: Agent(subagent_type=\"onex:polymorphic-agent\", description=\"...\", prompt=\"...\"). Inline work above the threshold is not permitted.")
                }
            }'
        exit 2
    fi

    # Write block
    if [[ "$WRITE_BLOCK" -ne -1 ]] && [[ "$WRITE_COUNT" -gt "$WRITE_BLOCK" ]]; then
        jq -n \
            --argjson count "$WRITE_COUNT" \
            --arg tool "$TOOL_NAME" \
            --argjson threshold "$WRITE_BLOCK" \
            '{
                hookSpecificOutput: {
                    additionalContext: ("DELEGATION ENFORCER [HARD BLOCK]: " + ($count | tostring) + " write/modify tool calls (" + $tool + " just now) without dispatching to a polymorphic agent. This tool call is BLOCKED. You MUST dispatch to onex:polymorphic-agent before continuing. Pattern: Agent(subagent_type=\"onex:polymorphic-agent\", description=\"...\", prompt=\"...\"). Inline work above the threshold is not permitted.")
                }
            }'
        exit 2
    fi

    # Write advisory warning: fire once
    if [[ "$WRITE_WARN" -ne -1 ]] && [[ "$WRITE_COUNT" -ge "$WRITE_WARN" ]] && [[ ! -f "$WRITE_WARNED_FILE" ]]; then
        touch "$WRITE_WARNED_FILE" 2>/dev/null || true
        jq -n \
            --argjson count "$WRITE_COUNT" \
            --arg tool "$TOOL_NAME" \
            --argjson block_threshold "$WRITE_BLOCK" \
            '{
                hookSpecificOutput: {
                    additionalContext: ("DELEGATION ENFORCER [WARNING]: " + ($count | tostring) + " write tool calls (" + $tool + " just now) without delegating. Hard block fires at " + ($block_threshold | tostring) + ". STOP and dispatch: Agent(subagent_type=\"onex:polymorphic-agent\", description=\"...\", prompt=\"...\"). Continuing inline fills the context window.")
                }
            }'
    fi

    printf '%s\n' "$TOOL_INFO"
    exit 0

else
    # Read-only tool — increment read counter
    READ_COUNT=0
    if [[ -f "$READ_COUNTER_FILE" ]]; then
        READ_COUNT=$(cat "$READ_COUNTER_FILE" 2>/dev/null || echo "0")
        [[ "$READ_COUNT" =~ ^[0-9]+$ ]] || READ_COUNT=0
    fi
    READ_COUNT=$((READ_COUNT + 1))
    echo "$READ_COUNT" > "$READ_COUNTER_FILE" 2>/dev/null || true

    # If delegation already happened, allow freely
    if [[ -f "$DELEGATED_FILE" ]]; then
        printf '%s\n' "$TOOL_INFO"
        exit 0
    fi

    # Read the current write count for total calculation
    WRITE_COUNT=0
    if [[ -f "$WRITE_COUNTER_FILE" ]]; then
        WRITE_COUNT=$(cat "$WRITE_COUNTER_FILE" 2>/dev/null || echo "0")
        [[ "$WRITE_COUNT" =~ ^[0-9]+$ ]] || WRITE_COUNT=0
    fi

    # Total block (read + write combined)
    TOTAL=$((WRITE_COUNT + READ_COUNT))
    if [[ "$TOTAL_BLOCK" -ne -1 ]] && [[ "$TOTAL" -gt "$TOTAL_BLOCK" ]]; then
        jq -n \
            --argjson count "$TOTAL" \
            --arg tool "$TOOL_NAME" \
            --argjson threshold "$TOTAL_BLOCK" \
            '{
                hookSpecificOutput: {
                    additionalContext: ("DELEGATION ENFORCER [HARD BLOCK]: " + ($count | tostring) + " total tool calls (" + $tool + " just now) without dispatching to a polymorphic agent. This tool call is BLOCKED. You MUST dispatch to onex:polymorphic-agent before continuing. Pattern: Agent(subagent_type=\"onex:polymorphic-agent\", description=\"...\", prompt=\"...\"). Inline work above the threshold is not permitted.")
                }
            }'
        exit 2
    fi

    # Read block
    if [[ "$READ_BLOCK" -ne -1 ]] && [[ "$READ_COUNT" -gt "$READ_BLOCK" ]]; then
        jq -n \
            --argjson count "$READ_COUNT" \
            --arg tool "$TOOL_NAME" \
            --argjson threshold "$READ_BLOCK" \
            '{
                hookSpecificOutput: {
                    additionalContext: ("DELEGATION ENFORCER [HARD BLOCK]: " + ($count | tostring) + " read-only tool calls (" + $tool + " just now) without dispatching to a polymorphic agent. This tool call is BLOCKED. You MUST dispatch to onex:polymorphic-agent before continuing. Pattern: Agent(subagent_type=\"onex:polymorphic-agent\", description=\"...\", prompt=\"...\"). Inline work above the threshold is not permitted.")
                }
            }'
        exit 2
    fi

    # Read advisory warning: fire once
    if [[ "$READ_WARN" -ne -1 ]] && [[ "$READ_COUNT" -ge "$READ_WARN" ]] && [[ ! -f "$READ_WARNED_FILE" ]]; then
        touch "$READ_WARNED_FILE" 2>/dev/null || true
        jq -n \
            --argjson count "$READ_COUNT" \
            --arg tool "$TOOL_NAME" \
            --argjson block_threshold "$READ_BLOCK" \
            '{
                hookSpecificOutput: {
                    additionalContext: ("DELEGATION ENFORCER [WARNING]: " + ($count | tostring) + " read-only tool calls (" + $tool + " just now) without delegating. Hard block fires at " + ($block_threshold | tostring) + ". STOP and dispatch: Agent(subagent_type=\"onex:polymorphic-agent\", description=\"...\", prompt=\"...\"). Continuing inline fills the context window.")
                }
            }'
    fi

    printf '%s\n' "$TOOL_INFO"
    exit 0
fi
