#!/bin/bash
# SessionEnd Hook - Portable Plugin Version
# Captures session completion and aggregate statistics
# Performance target: <50ms execution time

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

# Call session intelligence module (async, non-blocking)
(
    $PYTHON_CMD "${HOOKS_LIB}/session_intelligence.py" \
        --mode end \
        --session-id "${SESSION_ID}" \
        --metadata "{\"hook_duration_ms\": ${SESSION_DURATION}}" \
        >> "$LOG_FILE" 2>&1 || { rc=$?; log "Session end logging failed (exit=$rc)"; }
) &

# Emit session.ended event to Kafka (async, non-blocking)
# Uses emit_client_wrapper with daemon fan-out (OMN-1632)
if [[ "$KAFKA_ENABLED" == "true" ]]; then
    (
        # Convert duration from ms to seconds (using Python instead of bc for reliability)
        DURATION_SECONDS=""
        if [[ -n "$SESSION_DURATION" && "$SESSION_DURATION" != "0" ]]; then
            DURATION_SECONDS=$($PYTHON_CMD -c "import sys; print(f'{float(sys.argv[1])/1000:.3f}')" "$SESSION_DURATION" 2>/dev/null || echo "")
        fi

        # Build JSON payload for emit daemon
        SESSION_PAYLOAD=$(jq -n \
            --arg session_id "$SESSION_ID" \
            --arg reason "$SESSION_REASON" \
            --arg duration_seconds "${DURATION_SECONDS:-}" \
            '{
                session_id: $session_id,
                reason: $reason,
                duration_seconds: (if $duration_seconds == "" then null else ($duration_seconds | tonumber) end)
            }' 2>/dev/null)

        # Validate payload was constructed successfully
        if [[ -z "$SESSION_PAYLOAD" || "$SESSION_PAYLOAD" == "null" ]]; then
            log "WARNING: Failed to construct session payload (jq failed), skipping emission"
        else
            emit_via_daemon "session.ended" "$SESSION_PAYLOAD" 100
        fi
    ) &

    # Emit session.outcome event for feedback loop (OMN-1735, FEEDBACK-008)
    # Uses ClaudeCodeSessionOutcome enum values: success, failed, abandoned, unknown
    # Starting with "unknown" as default - heuristics can be added later
    (
        # Build session.outcome payload
        OUTCOME="unknown"

        OUTCOME_PAYLOAD=$(jq -n \
            --arg session_id "$SESSION_ID" \
            --arg outcome "$OUTCOME" \
            '{
                session_id: $session_id,
                outcome: $outcome
            }' 2>/dev/null)

        # Validate payload was constructed successfully
        if [[ -z "$OUTCOME_PAYLOAD" || "$OUTCOME_PAYLOAD" == "null" ]]; then
            log "WARNING: Failed to construct outcome payload (jq failed), skipping emission"
        else
            emit_via_daemon "session.outcome" "$OUTCOME_PAYLOAD" 100
        fi
    ) &

    log "Session event emission started via emit daemon"
else
    log "Kafka emission skipped (KAFKA_ENABLED=$KAFKA_ENABLED)"
fi

# Clean up correlation state
if [[ -f "${HOOKS_LIB}/correlation_manager.py" ]]; then
    $PYTHON_CMD -c "
import sys
sys.path.insert(0, '${HOOKS_LIB}')
from correlation_manager import get_registry
get_registry().clear()
" 2>/dev/null || true
fi

log "SessionEnd hook completed"

# Output unchanged
echo "$INPUT"
exit 0
