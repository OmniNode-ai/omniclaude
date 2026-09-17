#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Team Lifecycle Observability Hook (OMN-7022)
# Advisory-only hook that emits team lifecycle events to Kafka when
# TeamCreate, Agent, TaskCreate, TaskUpdate, or SendMessage tools fire.
#
# Event contract:
#   TeamCreate                      → team.task.assigned
#   Agent (with team_name)          → team.task.assigned
#   TaskCreate                      → team.task.assigned
#   TaskUpdate (status=completed)   → team.task.completed
#   TaskUpdate (status=in_progress) → team.task.progress
#   SendMessage                     → (no event — too chatty)
#
# Dedup: repeated TaskUpdate with same task_id+status emits at most once.
# Degraded-health: after 3 consecutive emit failures, writes marker file.
#
# Event:   PostToolUse
# Matcher: ^(TeamCreate|Agent|SendMessage|TaskCreate|TaskUpdate)$
# Ticket:  OMN-7022

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# --- Kill switches ---
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat  # drain stdin
    exit 0
fi
onex_hook_gate TEAM_OBSERVABILITY || exit 0

# --- Lite mode guard [OMN-5398] ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _SCRIPT_DIR _MODE_SH

# Ensure stable CWD before any Python invocation.
cd "$HOME" 2>/dev/null || cd /tmp || true

# --- Portable plugin root resolution ---
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"

# --- Log path: ONEX_STATE_DIR/hooks/logs/ [OMN-8429] ---
if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    echo "[$(date -u +%FT%TZ)] ERROR: ONEX_STATE_DIR unset; ONEX_REGISTRY_ROOT may be unset. Hook cannot write log." \
        >> /tmp/onex-hook-error.log
    cat
    exit 0
fi
LOG_FILE="${ONEX_STATE_DIR}/hooks/logs/team-observability.log"

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Guard: jq is required
if ! command -v jq >/dev/null 2>&1; then
    cat  # drain stdin
    exit 0
fi

# Source shared functions (provides PYTHON_CMD, emit_via_daemon)
source "${HOOKS_DIR}/scripts/common.sh"

# --- Read stdin ---
HOOK_EVENT=$(cat)

if ! printf '%s\n' "$HOOK_EVENT" | jq -e . >/dev/null 2>>"$LOG_FILE"; then
    printf '%s\n' "$HOOK_EVENT"
    exit 0
fi

TOOL_NAME=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_name // "unknown"' 2>/dev/null) || TOOL_NAME="unknown"

# --- Dedup state directory ---
DEDUP_DIR="${ONEX_STATE_DIR}/hooks/logs/team-observability-dedup"
mkdir -p "$DEDUP_DIR" 2>/dev/null || true

# OMN-18471 AC5: the failure counters that lived here are GONE with the
# socket they counted. They tracked emit_via_daemon exit status against
# ~/.claude/emit.sock, absent since 2026-06-08, so from that date they
# counted a fixed failure rather than a signal. Delivery liveness for the
# whole hook edge is now one surface -- hook_emit_health.py, which reads
# journal backlog depth and the drainer's last confirmed publish.

# --- Extract common fields ---
SESSION_ID="${CLAUDE_CODE_SESSION_ID:-$(printf '%s\n' "$HOOK_EVENT" | jq -r '.session_id // "unknown"' 2>/dev/null)}"
CORRELATION_ID="${ONEX_CORRELATION_ID:-}"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
DISPATCH_SURFACE="${ONEX_DISPATCH_SURFACE:-claude-code}"
AGENT_MODEL="${CLAUDE_MODEL:-unknown}"

# --- Emit helper (background, advisory) ---
_emit_team_event() {
    local event_type="$1"
    local payload="$2"

    # OMN-18471 AC5: re-homed onto the journal with the rest of the edge. This
    # is the one call site that passed a VARIABLE rather than a literal class
    # name, which is why the lane-contract gate could never resolve it and
    # says so in its own comment. The append is fire-and-forget and cannot
    # fail the way a socket write could, so the failure counters it used to
    # drive are gone with the socket.
    emit_to_journal "$event_type" "$payload" "${CORRELATION_ID:-}"
}

# --- Tool-specific event mapping ---
case "$TOOL_NAME" in
    TeamCreate)
        TEAM_NAME=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_input.team_name // .tool_response.team_name // "unknown"' 2>/dev/null) || TEAM_NAME="unknown"
        PAYLOAD=$(jq -n \
            --arg team_name "$TEAM_NAME" \
            --arg session_id "$SESSION_ID" \
            --arg correlation_id "$CORRELATION_ID" \
            --arg dispatch_surface "$DISPATCH_SURFACE" \
            --arg agent_model "$AGENT_MODEL" \
            --arg timestamp "$TIMESTAMP" \
            --arg source_tool "TeamCreate" \
            '{team_name: $team_name, session_id: $session_id, correlation_id: $correlation_id, dispatch_surface: $dispatch_surface, agent_model: $agent_model, timestamp: $timestamp, source_tool: $source_tool}')
        ( _emit_team_event "team.task.assigned" "$PAYLOAD" ) &
        ;;

    Agent)
        AGENT_NAME=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_input.agent_name // .tool_input.name // "unknown"' 2>/dev/null) || AGENT_NAME="unknown"
        TEAM_NAME=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_input.team_name // ""' 2>/dev/null) || TEAM_NAME=""
        TASK_ID=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_input.task_id // ""' 2>/dev/null) || TASK_ID=""
        PAYLOAD=$(jq -n \
            --arg agent_name "$AGENT_NAME" \
            --arg team_name "$TEAM_NAME" \
            --arg task_id "$TASK_ID" \
            --arg session_id "$SESSION_ID" \
            --arg correlation_id "$CORRELATION_ID" \
            --arg dispatch_surface "$DISPATCH_SURFACE" \
            --arg agent_model "$AGENT_MODEL" \
            --arg timestamp "$TIMESTAMP" \
            --arg source_tool "Agent" \
            '{agent_name: $agent_name, team_name: $team_name, task_id: $task_id, session_id: $session_id, correlation_id: $correlation_id, dispatch_surface: $dispatch_surface, agent_model: $agent_model, timestamp: $timestamp, source_tool: $source_tool}')
        ( _emit_team_event "team.task.assigned" "$PAYLOAD" ) &
        ;;

    TaskCreate)
        TASK_ID=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_response.task_id // .tool_input.task_id // ""' 2>/dev/null) || TASK_ID=""
        TASK_DESC=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_input.description // ""' 2>/dev/null) || TASK_DESC=""
        PAYLOAD=$(jq -n \
            --arg task_id "$TASK_ID" \
            --arg description "$TASK_DESC" \
            --arg session_id "$SESSION_ID" \
            --arg correlation_id "$CORRELATION_ID" \
            --arg dispatch_surface "$DISPATCH_SURFACE" \
            --arg agent_model "$AGENT_MODEL" \
            --arg timestamp "$TIMESTAMP" \
            --arg source_tool "TaskCreate" \
            '{task_id: $task_id, description: $description, session_id: $session_id, correlation_id: $correlation_id, dispatch_surface: $dispatch_surface, agent_model: $agent_model, timestamp: $timestamp, source_tool: $source_tool}')
        ( _emit_team_event "team.task.assigned" "$PAYLOAD" ) &
        ;;

    TaskUpdate)
        TASK_ID=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_input.task_id // ""' 2>/dev/null) || TASK_ID=""
        STATUS=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_input.status // ""' 2>/dev/null) || STATUS=""

        # Dedup: skip if same task_id+status was already emitted this session
        if [[ -n "$TASK_ID" && -n "$STATUS" ]]; then
            DEDUP_KEY="${TASK_ID}_${STATUS}"
            DEDUP_FILE="${DEDUP_DIR}/${DEDUP_KEY}"
            if [[ -f "$DEDUP_FILE" ]]; then
                echo "[${TIMESTAMP}] team-observability: dedup skip task_id=${TASK_ID} status=${STATUS}" >> "$LOG_FILE" 2>/dev/null || true
                printf '%s\n' "$HOOK_EVENT"
                exit 0
            fi
            echo "$TIMESTAMP" > "$DEDUP_FILE" 2>/dev/null || true
        fi

        case "$STATUS" in
            completed)
                VERIFICATION=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_input.verification_verdict // ""' 2>/dev/null) || VERIFICATION=""
                EVIDENCE_PATH=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_input.evidence_path // ""' 2>/dev/null) || EVIDENCE_PATH=""
                PAYLOAD=$(jq -n \
                    --arg task_id "$TASK_ID" \
                    --arg verification_verdict "$VERIFICATION" \
                    --arg evidence_path "$EVIDENCE_PATH" \
                    --arg session_id "$SESSION_ID" \
                    --arg correlation_id "$CORRELATION_ID" \
                    --arg dispatch_surface "$DISPATCH_SURFACE" \
                    --arg agent_model "$AGENT_MODEL" \
                    --arg timestamp "$TIMESTAMP" \
                    --arg source_tool "TaskUpdate" \
                    '{task_id: $task_id, verification_verdict: $verification_verdict, evidence_path: $evidence_path, session_id: $session_id, correlation_id: $correlation_id, dispatch_surface: $dispatch_surface, agent_model: $agent_model, timestamp: $timestamp, source_tool: $source_tool}')
                ( _emit_team_event "team.task.completed" "$PAYLOAD" ) &
                ;;
            in_progress)
                PHASE=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_input.phase // ""' 2>/dev/null) || PHASE=""
                MESSAGE=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_input.message // ""' 2>/dev/null) || MESSAGE=""
                PAYLOAD=$(jq -n \
                    --arg task_id "$TASK_ID" \
                    --arg phase "$PHASE" \
                    --arg message "$MESSAGE" \
                    --arg session_id "$SESSION_ID" \
                    --arg correlation_id "$CORRELATION_ID" \
                    --arg dispatch_surface "$DISPATCH_SURFACE" \
                    --arg agent_model "$AGENT_MODEL" \
                    --arg timestamp "$TIMESTAMP" \
                    --arg source_tool "TaskUpdate" \
                    '{task_id: $task_id, phase: $phase, message: $message, session_id: $session_id, correlation_id: $correlation_id, dispatch_surface: $dispatch_surface, agent_model: $agent_model, timestamp: $timestamp, source_tool: $source_tool}')
                ( _emit_team_event "team.task.progress" "$PAYLOAD" ) &
                ;;
            *)
                # Other statuses: no event
                ;;
        esac
        ;;

    SendMessage)
        # No event — too chatty per design contract
        ;;

    *)
        # Unknown tool — should not reach here given matcher, but be safe
        ;;
esac

# Always pass through original tool info (advisory hook)
printf '%s\n' "$HOOK_EVENT"
exit 0
