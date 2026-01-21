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

# Source shared functions (provides PYTHON_CMD, KAFKA_ENABLED, get_time_ms)
source "${HOOKS_DIR}/scripts/common.sh"

export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

# Load environment variables
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# Read stdin
INPUT=$(cat)

echo "[$(date '+%Y-%m-%d %H:%M:%S')] SessionEnd hook triggered (plugin mode)" >> "$LOG_FILE"

# Extract session metadata
SESSION_ID=$(echo "$INPUT" | jq -r '.sessionId // ""' 2>/dev/null || echo "")
SESSION_DURATION=$(echo "$INPUT" | jq -r '.durationMs // 0' 2>/dev/null || echo "0")

if [[ -n "$SESSION_ID" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Session ID: $SESSION_ID" >> "$LOG_FILE"
fi
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Duration: ${SESSION_DURATION}ms" >> "$LOG_FILE"

# Call session intelligence module (async, non-blocking)
(
    $PYTHON_CMD "${HOOKS_LIB}/session_intelligence.py" \
        --mode end \
        --session-id "${SESSION_ID}" \
        --metadata "{\"hook_duration_ms\": ${SESSION_DURATION}}" \
        >> "$LOG_FILE" 2>&1 || echo "[$(date '+%Y-%m-%d %H:%M:%S')] Session end logging failed" >> "$LOG_FILE"
) &

# Emit session.ended event to Kafka (async, non-blocking)
# Uses omniclaude-emit CLI with 250ms hard timeout
if [[ "$KAFKA_ENABLED" == "true" ]]; then
    (
        # Convert duration from ms to seconds (using Python instead of bc for reliability)
        DURATION_SECONDS=""
        if [[ -n "$SESSION_DURATION" && "$SESSION_DURATION" != "0" ]]; then
            DURATION_SECONDS=$($PYTHON_CMD -c "import sys; print(f'{float(sys.argv[1])/1000:.3f}')" "$SESSION_DURATION" 2>/dev/null || echo "")
        fi

        $PYTHON_CMD -m omniclaude.hooks.cli_emit session-ended \
            --session-id "$SESSION_ID" \
            --reason "other" \
            ${DURATION_SECONDS:+--duration "$DURATION_SECONDS"} \
            >> "$LOG_FILE" 2>&1 || true
    ) &
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Session event emission started" >> "$LOG_FILE"
fi

# Clean up correlation state
if [[ -f "${HOOKS_LIB}/correlation_manager.py" ]]; then
    $PYTHON_CMD -c "
import sys
sys.path.insert(0, '${HOOKS_LIB}')
from correlation_manager import get_manager
get_manager().clear()
" 2>/dev/null || true
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] SessionEnd hook completed" >> "$LOG_FILE"

# Output unchanged
echo "$INPUT"
exit 0
