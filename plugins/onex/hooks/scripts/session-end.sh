#!/bin/bash
# SessionEnd Hook - Portable Plugin Version
# Captures session completion and aggregate statistics
# Also logs active ticket for audit/observability (OMN-1830)
# Performance target: <50ms execution time
# NOTE: This hook is audit-only - NO context injection, NO contract mutation

set -euo pipefail

# Portable Plugin Configuration
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${HOOKS_DIR}/logs/hook-session-end.log"

# Detect project root
PROJECT_ROOT="${PLUGIN_ROOT}/../.."
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"
elif [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"
else
    PROJECT_ROOT="$(pwd)"
fi

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

# Load environment variables (before common.sh so KAFKA_BOOTSTRAP_SERVERS is available)
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# Source shared functions (provides PYTHON_CMD, KAFKA_ENABLED, get_time_ms, log)
source "${HOOKS_DIR}/scripts/common.sh"

# Read stdin
INPUT=$(cat)

log "SessionEnd hook triggered (plugin mode)"

# Extract session metadata
SESSION_ID=$(echo "$INPUT" | jq -r '.sessionId // ""' 2>/dev/null || echo "")
SESSION_DURATION=$(echo "$INPUT" | jq -r '.durationMs // 0' 2>/dev/null || echo "0")
SESSION_REASON=$(echo "$INPUT" | jq -r '.reason // "other"' 2>/dev/null || echo "other")

# Extract tool call count from session payload (if available)
TOOL_CALLS_COMPLETED=$(echo "$INPUT" | jq -r '.numTurns // 0' 2>/dev/null || echo "0")

# Validate reason is one of the allowed values
case "$SESSION_REASON" in
    clear|logout|prompt_input_exit|other) ;;
    *) SESSION_REASON="other" ;;
esac

if [[ -n "$SESSION_ID" ]]; then
    log "Session ID: $SESSION_ID"
fi
log "Duration: ${SESSION_DURATION}ms"
log "Reason: $SESSION_REASON"

# -----------------------------
# Active Ticket Detection (OMN-1830)
# -----------------------------
# Check for active ticket (for audit logging only - NO context injection, NO mutation)
TICKET_INJECTION_ENABLED="${OMNICLAUDE_TICKET_INJECTION_ENABLED:-true}"
TICKET_INJECTION_ENABLED=$(_normalize_bool "$TICKET_INJECTION_ENABLED")
ACTIVE_TICKET=""

if [[ "${TICKET_INJECTION_ENABLED}" == "true" ]] && [[ -f "${HOOKS_LIB}/ticket_context_injector.py" ]]; then
    # Use CLI interface for consistency with session-start.sh (OMN-1830)
    TICKET_OUTPUT=$(echo '{}' | "$PYTHON_CMD" "${HOOKS_LIB}/ticket_context_injector.py" 2>>"$LOG_FILE") || TICKET_OUTPUT='{}'
    ACTIVE_TICKET=$(echo "$TICKET_OUTPUT" | jq -r '.ticket_id // empty' 2>/dev/null) || ACTIVE_TICKET=""

    if [[ -n "$ACTIVE_TICKET" ]]; then
        log "Session ended with active ticket: $ACTIVE_TICKET"
    else
        log "Session ended with no active ticket"
    fi
elif [[ "${TICKET_INJECTION_ENABLED}" != "true" ]]; then
    log "Active ticket detection disabled (TICKET_INJECTION_ENABLED=false)"
else
    log "Ticket context injector not found, skipping active ticket detection"
fi

# Call session intelligence module (async, non-blocking)
(
    $PYTHON_CMD "${HOOKS_LIB}/session_intelligence.py" \
        --mode end \
        --session-id "${SESSION_ID}" \
        --metadata "{\"hook_duration_ms\": ${SESSION_DURATION}}" \
        >> "$LOG_FILE" 2>&1 || { rc=$?; log "Session end logging failed (exit=$rc)"; }
) &

# Convert duration from ms to seconds once (used by all subshells below)
DURATION_SECONDS="0"
if [[ -n "$SESSION_DURATION" && "$SESSION_DURATION" != "0" ]]; then
    DURATION_SECONDS=$($PYTHON_CMD -c "import sys; print(f'{float(sys.argv[1])/1000:.3f}')" "$SESSION_DURATION" 2>/dev/null || echo "0")
fi

# ===================================================================
# PHASE 1 PLUMBING (OMN-1892): Outcome derivation inputs are
# partially hardcoded. Current state:
#   - exit_code=0: Always 0 (hooks must never exit non-zero per CLAUDE.md)
#   - session_output: Uses session reason (clear/logout/prompt_input_exit/
#     other), NOT captured stdout. Outcome will not resolve to FAILED
#     until session_output carries error markers (Error:, Exception:, etc.)
#   - tool_calls_completed: Extracted from numTurns (best-effort);
#     may still be 0 if field is absent from SessionEnd payload.
#     SUCCESS requires tool_calls > 0 AND completion markers.
# Result: Outcome currently resolves to abandoned or unknown only.
# Future tickets:
#   - tool_calls_completed: Wire from session aggregation service
#   - session_output: Wire from captured session output/stdout
# ===================================================================
# Derive session outcome ONCE (OMN-1892)
# Used by both session.outcome emission and feedback guardrail check.
# Pure Python with no I/O -- synchronous cost is negligible (<5ms).
# Falls back to "unknown" if Python call fails (graceful degradation).
DERIVED_OUTCOME=$(HOOKS_LIB="$HOOKS_LIB" SESSION_REASON="$SESSION_REASON" DURATION_SECONDS="$DURATION_SECONDS" TOOL_CALLS_COMPLETED="$TOOL_CALLS_COMPLETED" \
    "$PYTHON_CMD" -c "
import os, sys
sys.path.insert(0, os.environ['HOOKS_LIB'])
from session_outcome import derive_session_outcome
session_reason = os.environ.get('SESSION_REASON', 'other')
duration_str = os.environ.get('DURATION_SECONDS', '0')
tool_calls_str = os.environ.get('TOOL_CALLS_COMPLETED', '0')
result = derive_session_outcome(
    exit_code=0,
    session_output=session_reason,
    tool_calls_completed=int(tool_calls_str) if tool_calls_str.isdigit() else 0,
    duration_seconds=float(duration_str if duration_str else '0'),
)
print(result.outcome)
" 2>>"$LOG_FILE") || DERIVED_OUTCOME="unknown"

log "Session outcome derived: ${DERIVED_OUTCOME}"

# Emit session.ended event to Kafka (async, non-blocking)
# Uses emit_client_wrapper with daemon fan-out (OMN-1632)
if [[ "$KAFKA_ENABLED" == "true" ]]; then
    (
        # Build JSON payload for emit daemon (includes active_ticket for OMN-1830)
        # DURATION_SECONDS pre-computed in main shell; map "0" to null (no duration info)
        SESSION_PAYLOAD=$(jq -n \
            --arg session_id "$SESSION_ID" \
            --arg reason "$SESSION_REASON" \
            --arg duration_seconds "$DURATION_SECONDS" \
            --arg active_ticket "$ACTIVE_TICKET" \
            '{
                session_id: $session_id,
                reason: $reason,
                duration_seconds: (if $duration_seconds == "0" then null else ($duration_seconds | tonumber) end),
                active_ticket: (if $active_ticket == "" then null else $active_ticket end)
            }' 2>/dev/null)

        # Validate payload was constructed successfully
        if [[ -z "$SESSION_PAYLOAD" || "$SESSION_PAYLOAD" == "null" ]]; then
            log "WARNING: Failed to construct session payload (jq failed), skipping emission"
        else
            emit_via_daemon "session.ended" "$SESSION_PAYLOAD" 100
        fi
    ) &

    # Emit session.outcome event for feedback loop (OMN-1735, OMN-1892)
    # Uses ClaudeCodeSessionOutcome enum values: success, failed, abandoned, unknown
    # Outcome was derived synchronously above; subshell uses pre-computed DERIVED_OUTCOME.
    (
        # Validate SESSION_ID before constructing payload
        if [[ -z "$SESSION_ID" ]]; then
            log "WARNING: SESSION_ID is empty, skipping session.outcome emission"
            exit 0  # Exit the subshell cleanly
        fi

        # Validate UUID format (8-4-4-4-12 structure, case-insensitive)
        if [[ ! "$SESSION_ID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
            log "WARNING: SESSION_ID '$SESSION_ID' is not valid UUID format, skipping session.outcome emission"
            exit 0
        fi

        EMITTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

        OUTCOME_PAYLOAD=$(jq -n \
            --arg session_id "$SESSION_ID" \
            --arg outcome "$DERIVED_OUTCOME" \
            --arg emitted_at "$EMITTED_AT" \
            --arg active_ticket "$ACTIVE_TICKET" \
            '{
                session_id: $session_id,
                outcome: $outcome,
                emitted_at: $emitted_at,
                active_ticket: (if $active_ticket == "" then null else $active_ticket end)
            }' 2>/dev/null)

        # Validate payload was constructed successfully
        if [[ -z "$OUTCOME_PAYLOAD" || "$OUTCOME_PAYLOAD" == "null" ]]; then
            log "WARNING: Failed to construct outcome payload (jq failed), skipping emission"
        else
            emit_via_daemon "session.outcome" "$OUTCOME_PAYLOAD" 100
        fi
    ) &

    # Feedback guardrail check (OMN-1892)
    # Evaluates whether routing feedback should be recorded.
    # Runs in a backgrounded subshell to stay within 50ms sync budget.
    # Uses pre-computed DERIVED_OUTCOME from main shell.
    (
        # Validate SESSION_ID before constructing payload
        if [[ -z "$SESSION_ID" ]]; then
            log "WARNING: SESSION_ID is empty, skipping routing feedback evaluation"
            exit 0  # Exit the subshell cleanly
        fi

        # Validate UUID format (8-4-4-4-12 structure, case-insensitive)
        if [[ ! "$SESSION_ID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
            log "WARNING: SESSION_ID '$SESSION_ID' is not valid UUID format, skipping routing feedback evaluation"
            exit 0
        fi

        # Evaluate guardrails using pre-computed DERIVED_OUTCOME
        # ===================================================================
        # PHASE 1 PLUMBING (OMN-1892): Guardrail logic is wired but inputs
        # are hardcoded. Feedback will always be skipped (NO_INJECTION).
        # Future tickets to wire real values:
        #   - injection_occurred: Read from session injection marker
        #   - utilization_score: Read from PostToolUse utilization metrics
        #   - agent_match_score: Read from UserPromptSubmit routing decision
        # ===================================================================
        FEEDBACK_RESULT=$(HOOKS_LIB="$HOOKS_LIB" DERIVED_OUTCOME="$DERIVED_OUTCOME" \
            "$PYTHON_CMD" -c "
import os, sys, json
sys.path.insert(0, os.environ['HOOKS_LIB'])
from feedback_guardrails import should_reinforce_routing
result = should_reinforce_routing(
    injection_occurred=False,
    utilization_score=0.0,
    agent_match_score=0.0,
    session_outcome=os.environ['DERIVED_OUTCOME'],
)
print(json.dumps({
    'should_reinforce': result.should_reinforce,
    'skip_reason': result.skip_reason,
}))
" 2>>"$LOG_FILE") || FEEDBACK_RESULT='{"should_reinforce":false,"skip_reason":"PYTHON_ERROR"}'

        SHOULD_REINFORCE=$(echo "$FEEDBACK_RESULT" | jq -r '.should_reinforce' 2>/dev/null) || SHOULD_REINFORCE="false"
        SKIP_REASON=$(echo "$FEEDBACK_RESULT" | jq -r '.skip_reason // empty' 2>/dev/null) || SKIP_REASON=""

        if [[ "$SHOULD_REINFORCE" == "true" ]] && [[ "$KAFKA_ENABLED" == "true" ]]; then
            if ! FEEDBACK_PAYLOAD=$(jq -n \
                --arg session_id "$SESSION_ID" \
                --arg outcome "$DERIVED_OUTCOME" \
                --arg emitted_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
                '{session_id: $session_id, outcome: $outcome, emitted_at: $emitted_at}' 2>/dev/null); then
                log "WARNING: Failed to construct routing.feedback payload (jq failed), skipping emission"
                exit 0
            fi

            if [[ -n "$FEEDBACK_PAYLOAD" && "$FEEDBACK_PAYLOAD" != "null" ]]; then
                emit_via_daemon "routing.feedback" "$FEEDBACK_PAYLOAD" 100
            fi
        elif [[ -n "$SKIP_REASON" ]] && [[ "$KAFKA_ENABLED" == "true" ]]; then
            if ! SKIP_PAYLOAD=$(jq -n \
                --arg session_id "$SESSION_ID" \
                --arg skip_reason "$SKIP_REASON" \
                --arg emitted_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
                '{session_id: $session_id, skip_reason: $skip_reason, emitted_at: $emitted_at}' 2>/dev/null); then
                log "WARNING: Failed to construct routing.skipped payload (jq failed), skipping emission"
                exit 0
            fi

            if [[ -n "$SKIP_PAYLOAD" && "$SKIP_PAYLOAD" != "null" ]]; then
                emit_via_daemon "routing.skipped" "$SKIP_PAYLOAD" 100
            fi
        fi

        log "Feedback guardrail: should_reinforce=$SHOULD_REINFORCE skip_reason=$SKIP_REASON"
    ) &

    log "Session event emission started via emit daemon"
else
    log "Kafka emission skipped (KAFKA_ENABLED=$KAFKA_ENABLED)"
fi

# Flush and stop the publisher (OMN-1944)
# Give events a brief window (0.5s) to flush, then send stop signal.
# This runs in a background subshell to avoid blocking session-end.
# Known limitation: if emit subshells above take >0.5s (e.g. socket latency),
# events may not be enqueued before SIGTERM arrives and will be dropped.
# Acceptable per CLAUDE.md failure modes (data loss OK, UI freeze is not).
# Override via PUBLISHER_DRAIN_DELAY_SECONDS if needed.
(
    # Brief pause to allow async emit subshells above to complete
    sleep "${PUBLISHER_DRAIN_DELAY_SECONDS:-0.5}"

    # Stop publisher via __main__.py stop command (sends SIGTERM to PID)
    "$PYTHON_CMD" -m omniclaude.publisher stop >> "$LOG_FILE" 2>&1 || {
        # Fallback: try legacy daemon stop
        "$PYTHON_CMD" -m omnibase_infra.runtime.emit_daemon.cli stop >> "$LOG_FILE" 2>&1 || true
    }
    log "Publisher stop signal sent"
) &

# Clean up correlation state
if [[ -f "${HOOKS_LIB}/correlation_manager.py" ]]; then
    HOOKS_LIB="$HOOKS_LIB" $PYTHON_CMD -c "
import os, sys
sys.path.insert(0, os.environ['HOOKS_LIB'])
from correlation_manager import get_registry
get_registry().clear()
" 2>/dev/null || true
fi

# -----------------------------
# Clear session injection marker (OMN-1675)
# -----------------------------
if [[ -f "${HOOKS_LIB}/session_marker.py" ]] && [[ -n "${SESSION_ID}" ]]; then
    $PYTHON_CMD "${HOOKS_LIB}/session_marker.py" clear --session-id "${SESSION_ID}" 2>>"$LOG_FILE" || true
    log "Cleared session injection marker"
fi

log "SessionEnd hook completed"

# Output unchanged
echo "$INPUT"
exit 0
