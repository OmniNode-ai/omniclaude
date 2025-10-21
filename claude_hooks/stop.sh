#!/bin/bash

# Stop Hook - Response Completion Intelligence
# Captures response completion, multi-tool coordination, and performance metrics
#
# Exit Codes:
#   0 - Success (intelligence captured)
#   1 - Error during processing

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_LIB="${SCRIPT_DIR}/lib"
LOG_FILE="${SCRIPT_DIR}/logs/stop.log"
PERFORMANCE_TARGET_MS=30

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Performance tracking (use Python for cross-platform millisecond precision)
START_TIME=$(python3 -c "import time; print(int(time.time() * 1000))")

# Read Stop event JSON from stdin
STOP_INFO=$(cat)

# Log hook trigger
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Stop hook triggered" >> "$LOG_FILE"

# Debug: Save full JSON
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Stop JSON:" >> "$LOG_FILE"
echo "$STOP_INFO" | jq '.' >> "$LOG_FILE" 2>&1 || echo "$STOP_INFO" >> "$LOG_FILE"

# Extract session ID
SESSION_ID=$(echo "$STOP_INFO" | jq -r '.session_id // .sessionId // "unknown"')
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Session ID: $SESSION_ID" >> "$LOG_FILE"

# Extract completion status (if provided)
COMPLETION_STATUS=$(echo "$STOP_INFO" | jq -r '.completion_status // .status // "complete"')

# Extract tools executed (if provided in JSON)
TOOLS_EXECUTED=$(echo "$STOP_INFO" | jq -r '.tools_executed // empty' 2>/dev/null)

# If tools not in JSON, query database for tools executed in this session
if [[ -z "$TOOLS_EXECUTED" ]] || [[ "$TOOLS_EXECUTED" == "null" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Tools not in JSON, querying database..." >> "$LOG_FILE"

    # Query database for tools executed (via correlation ID)
    TOOLS_EXECUTED=$(python3 -c "
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

# Query database for tools executed in this correlation
logger = get_logger()
try:
    conn = logger._get_connection()
    with conn.cursor() as cur:
        # Get all PostToolUse events for this correlation
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
    print(f'Error querying tools: {e}', file=sys.stderr)
" 2>>"$LOG_FILE")
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Tools executed: $TOOLS_EXECUTED" >> "$LOG_FILE"

# Call Python module to log response completion
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Logging response completion..." >> "$LOG_FILE"

set +e
python3 -c "
import sys
sys.path.insert(0, '${HOOKS_LIB}')
from response_intelligence import log_response_completion
import json

session_id = '$SESSION_ID'
completion_status = '$COMPLETION_STATUS'

# Parse tools executed
try:
    tools_executed = json.loads('''$TOOLS_EXECUTED''')
    if not isinstance(tools_executed, list):
        tools_executed = []
except:
    tools_executed = []

# Detect interruption from status
if completion_status in ['interrupted', 'cancelled', 'error']:
    completion_status = 'interrupted'
elif completion_status == 'complete':
    completion_status = 'complete'
else:
    # Default to complete if unknown status
    completion_status = 'complete'

# Log response completion
event_id = log_response_completion(
    session_id=session_id,
    tools_executed=tools_executed,
    completion_status=completion_status,
    metadata={
        'hook_type': 'Stop',
        'interruption_point': 'unknown' if completion_status == 'interrupted' else None
    }
)

if event_id:
    print(f'✓ Response completion logged: {event_id}', file=sys.stderr)
else:
    print('⚠️  Failed to log response completion', file=sys.stderr)
" 2>>"$LOG_FILE"
EXIT_CODE=$?
set -e

if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Response completion logged successfully" >> "$LOG_FILE"
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Response completion logging failed with code $EXIT_CODE" >> "$LOG_FILE"
fi

# Calculate execution time (use Python for cross-platform millisecond precision)
END_TIME=$(python3 -c "import time; print(int(time.time() * 1000))")
EXECUTION_TIME_MS=$((END_TIME - START_TIME))

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Stop hook completed in ${EXECUTION_TIME_MS}ms" >> "$LOG_FILE"

# Warn if exceeding performance target
if [ $EXECUTION_TIME_MS -gt $PERFORMANCE_TARGET_MS ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ⚠️  Performance warning: ${EXECUTION_TIME_MS}ms (target: <${PERFORMANCE_TARGET_MS}ms)" >> "$LOG_FILE"
fi

# ============================================================================
# AGENT EXECUTION SUMMARY BANNER
# ============================================================================

# Display agent execution summary banner
if [[ -f "${HOOKS_LIB}/agent_summary_banner.py" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Displaying agent execution summary..." >> "$LOG_FILE"

    python3 -c "
import sys
sys.path.insert(0, '${HOOKS_LIB}')
from agent_summary_banner import display_summary_banner
import json

# Parse tools executed
try:
    tools_executed = json.loads('''$TOOLS_EXECUTED''')
    if not isinstance(tools_executed, list):
        tools_executed = []
except:
    tools_executed = []

# Display summary banner
display_summary_banner(
    tools_executed=tools_executed,
    completion_status='$COMPLETION_STATUS'
)
" 2>>"$LOG_FILE"

    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Agent summary banner displayed" >> "$LOG_FILE"
fi

# ============================================================================
# CORRELATION CLEANUP
# ============================================================================

# Clear correlation state after response completion
if [[ -f "${HOOKS_LIB}/correlation_manager.py" ]]; then
    python3 -c "
import sys
sys.path.insert(0, '${HOOKS_LIB}')
from correlation_manager import get_manager

# Clear correlation state
get_manager().clear()
" 2>/dev/null
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Correlation state cleared" >> "$LOG_FILE"
fi

# Always pass through original output
echo "$STOP_INFO"
exit 0
