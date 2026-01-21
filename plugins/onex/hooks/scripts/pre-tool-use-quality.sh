#!/bin/bash
# PreToolUse Quality Enforcement Hook - Portable Plugin Version
# Intercepts Write/Edit/MultiEdit operations for quality validation

set -euo pipefail

# Portable Plugin Configuration
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${HOOKS_DIR}/logs/quality_enforcer.log"

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

# Source shared functions (provides PYTHON_CMD)
# Note: common.sh also exports KAFKA_ENABLED, but PreToolUse hooks do not emit
# Kafka events - there is no tool.pre_executed schema defined. This is intentional:
# pre-execution validation is synchronous and blocking, while Kafka events are
# designed for async observability of completed actions.
source "${HOOKS_DIR}/scripts/common.sh"

# Generate or reuse correlation ID
if [ -z "${CORRELATION_ID:-}" ]; then
    CORRELATION_ID=$(uuidgen 2>/dev/null | tr '[:upper:]' '[:lower:]' || $PYTHON_CMD -c 'import uuid; print(str(uuid.uuid4()))')
fi
export CORRELATION_ID

if [ -z "${ROOT_ID:-}" ]; then
    ROOT_ID="$CORRELATION_ID"
fi
export ROOT_ID

if [ -z "${SESSION_ID:-}" ]; then
    SESSION_ID=$(uuidgen 2>/dev/null | tr '[:upper:]' '[:lower:]' || $PYTHON_CMD -c 'import uuid; print(str(uuid.uuid4()))')
fi
export SESSION_ID

echo "[TRACE] Quality Hook - Correlation: $CORRELATION_ID, Root: $ROOT_ID, Session: $SESSION_ID" >&2

# Extract tool information
TOOL_INFO=$(cat)
TOOL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_name // "unknown"')

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [CID:${CORRELATION_ID:0:8}] Hook invoked for tool: $TOOL_NAME (plugin mode)" >> "$LOG_FILE"

# Only intercept Write/Edit/MultiEdit operations
if [[ ! "$TOOL_NAME" =~ ^(Write|Edit|MultiEdit)$ ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Check for quality enforcer script
QUALITY_SCRIPT="${HOOKS_DIR}/scripts/quality_enforcer.py"
if [[ ! -f "$QUALITY_SCRIPT" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [CID:${CORRELATION_ID:0:8}] quality_enforcer.py not found, passing through" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi

# Run Python quality enforcer
set +e
RESULT=$(echo "$TOOL_INFO" | \
    CORRELATION_ID="$CORRELATION_ID" \
    ROOT_ID="$ROOT_ID" \
    SESSION_ID="$SESSION_ID" \
    $PYTHON_CMD "$QUALITY_SCRIPT")
EXIT_CODE=$?
set -e

# Database event logging (async, non-blocking)
if [[ -f "${HOOKS_LIB}/hook_event_logger.py" ]]; then
    (
        $PYTHON_CMD -c "
import sys
sys.path.insert(0, '${HOOKS_LIB}')
from hook_event_logger import log_pretooluse
from correlation_manager import get_correlation_context
import json

tool_info = json.loads('''$TOOL_INFO''')
tool_name = tool_info.get('tool_name', 'unknown')
tool_input = tool_info.get('tool_input', {})

corr_context = get_correlation_context()
correlation_id = corr_context.get('correlation_id') if corr_context else None
final_corr_id = correlation_id or '$CORRELATION_ID'

log_pretooluse(
    tool_name=tool_name,
    tool_input=tool_input,
    correlation_id=final_corr_id,
    quality_check_result={
        'hook_correlation_id': '$CORRELATION_ID',
        'user_correlation_id': correlation_id,
        'agent_name': corr_context.get('agent_name') if corr_context else None,
        'session_id': '$SESSION_ID',
        'root_id': '$ROOT_ID'
    }
)
" 2>/dev/null
    ) &
fi

# Handle exit codes
if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [CID:${CORRELATION_ID:0:8}] Quality check passed for $TOOL_NAME" >> "$LOG_FILE"
    echo "$RESULT"
elif [ $EXIT_CODE -eq 1 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [CID:${CORRELATION_ID:0:8}] Quality check BLOCKED for $TOOL_NAME" >> "$LOG_FILE"
    echo "$RESULT"
    exit 2
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [CID:${CORRELATION_ID:0:8}] ERROR: Quality enforcer failed with code $EXIT_CODE" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi
