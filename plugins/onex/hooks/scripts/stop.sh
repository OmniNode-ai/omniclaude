#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Stop Hook - Portable Plugin Version
# Response completion intelligence and summary banner

set -euo pipefail

# Ensure stable CWD before any Python invocation.
# The session CWD may be on an external drive that disconnects/remounts;
# Python's <frozen getpath> calls os.getcwd() during startup and crashes
# with "failed to make path absolute" if the CWD is unavailable.
cd "$HOME" 2>/dev/null || cd /tmp || true

# Portable Plugin Configuration
# Resolve absolute path of this script, handling relative invocation (e.g. ./stop.sh).
# Falls back to python3 if realpath is unavailable (non-GNU macOS without coreutils).
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${HOOKS_DIR}/logs/stop.log"
PERFORMANCE_TARGET_MS=30

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

# Load environment variables
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# Source shared functions (provides PYTHON_CMD, KAFKA_ENABLED, get_time_ms)
source "${HOOKS_DIR}/scripts/common.sh"

# Performance tracking
START_TIME=$(get_time_ms)

# Read Stop event JSON
STOP_INFO=$(cat)

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Stop hook triggered (plugin mode)" >> "$LOG_FILE"
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Stop JSON:" >> "$LOG_FILE"
echo "$STOP_INFO" | jq '.' >> "$LOG_FILE" 2>&1 || echo "$STOP_INFO" >> "$LOG_FILE"

# Extract session ID and status
SESSION_ID=$(echo "$STOP_INFO" | jq -r '.session_id // .sessionId // "unknown"')
COMPLETION_STATUS=$(echo "$STOP_INFO" | jq -r '.completion_status // .status // "complete"')
TOOLS_EXECUTED=$(echo "$STOP_INFO" | jq -r '.tools_executed // empty' 2>/dev/null)

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Session ID: $SESSION_ID" >> "$LOG_FILE"

# Emit Stop event to Kafka for pattern learning trigger (non-blocking)
if [[ "$KAFKA_ENABLED" == "true" ]] && command -v jq >/dev/null 2>&1; then
    (
        STOP_PAYLOAD=$(jq -n \
            --arg session_id "$SESSION_ID" \
            --arg completion_status "$COMPLETION_STATUS" \
            --arg event_type "Stop" \
            '{session_id: $session_id, completion_status: $completion_status, event_type: $event_type}' 2>/dev/null)
        if [[ -n "$STOP_PAYLOAD" ]] && [[ "$STOP_PAYLOAD" != "null" ]]; then
            emit_via_daemon "response.stopped" "$STOP_PAYLOAD" 100
        else
            log "WARNING: Failed to construct stop payload, skipping Kafka emission"
        fi
    ) &
fi

# If tools not in JSON, query database
if [[ -z "$TOOLS_EXECUTED" ]] || [[ "$TOOLS_EXECUTED" == "null" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Querying database for tools..." >> "$LOG_FILE"
    TOOLS_EXECUTED=$($PYTHON_CMD -c "
import sys
sys.path.insert(0, '${HOOKS_LIB}')
from correlation_manager import get_correlation_context
from hook_event_logger import get_logger
import json

corr_context = get_correlation_context()
if not corr_context:
    print('[]')
    sys.exit(0)

correlation_id = corr_context.get('correlation_id')
if not correlation_id:
    print('[]')
    sys.exit(0)

logger = get_logger()
try:
    conn = logger._get_connection()
    with conn.cursor() as cur:
        cur.execute('''
            SELECT DISTINCT payload->>'tool_name' as tool_name
            FROM hook_events
            WHERE source = 'PostToolUse'
            AND metadata->>'correlation_id' = %s
            ORDER BY created_at
        ''', (correlation_id,))
        tools = [row[0] for row in cur.fetchall() if row[0]]
        print(json.dumps(tools))
except Exception as e:
    print('[]', file=sys.stderr)
" 2>>"$LOG_FILE" || echo "[]")
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Tools executed: $TOOLS_EXECUTED" >> "$LOG_FILE"

# Log response completion
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Logging response completion..." >> "$LOG_FILE"

set +e
$PYTHON_CMD -c "
import sys
sys.path.insert(0, '${HOOKS_LIB}')
from response_intelligence import log_response_completion
import json

session_id = '$SESSION_ID'
completion_status = '$COMPLETION_STATUS'

try:
    tools_executed = json.loads('''$TOOLS_EXECUTED''')
    if not isinstance(tools_executed, list):
        tools_executed = []
except:
    tools_executed = []

if completion_status in ['interrupted', 'cancelled', 'error']:
    completion_status = 'interrupted'
else:
    completion_status = 'complete'

event_id = log_response_completion(
    session_id=session_id,
    tools_executed=tools_executed,
    completion_status=completion_status,
    metadata={'hook_type': 'Stop'}
)

if event_id:
    print(f'Response completion logged: {event_id}', file=sys.stderr)
" 2>>"$LOG_FILE"
set -e

# Display agent summary banner
if [[ -f "${HOOKS_LIB}/agent_summary_banner.py" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Displaying summary banner..." >> "$LOG_FILE"
    $PYTHON_CMD -c "
import sys
sys.path.insert(0, '${HOOKS_LIB}')
from agent_summary_banner import display_summary_banner
import json

try:
    tools_executed = json.loads('''$TOOLS_EXECUTED''')
    if not isinstance(tools_executed, list):
        tools_executed = []
except:
    tools_executed = []

display_summary_banner(
    tools_executed=tools_executed,
    completion_status='$COMPLETION_STATUS'
)
" 2>>"$LOG_FILE"
fi

# Clear correlation state
if [[ -f "${HOOKS_LIB}/correlation_manager.py" ]]; then
    $PYTHON_CMD -c "
import sys
sys.path.insert(0, '${HOOKS_LIB}')
from correlation_manager import get_registry
get_registry().clear()
" 2>/dev/null
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Correlation state cleared" >> "$LOG_FILE"
fi

# Performance tracking
END_TIME=$(get_time_ms)
EXECUTION_TIME_MS=$((END_TIME - START_TIME))

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Stop hook completed in ${EXECUTION_TIME_MS}ms" >> "$LOG_FILE"

if [ $EXECUTION_TIME_MS -gt $PERFORMANCE_TARGET_MS ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Performance warning: ${EXECUTION_TIME_MS}ms (target: <${PERFORMANCE_TARGET_MS}ms)" >> "$LOG_FILE"
fi

# Pass through original output
echo "$STOP_INFO"
exit 0
