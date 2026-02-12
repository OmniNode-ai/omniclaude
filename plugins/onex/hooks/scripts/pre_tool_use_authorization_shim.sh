#!/bin/bash
# PreToolUse Authorization Gate Hook - Portable Plugin Version
# Intercepts Edit/Write operations for authorization validation

set -euo pipefail

# Portable Plugin Configuration
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${HOOKS_DIR}/logs/authorization.log"

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

# Source shared functions (provides PYTHON_CMD, KAFKA_ENABLED)
source "${HOOKS_DIR}/scripts/common.sh"

# Read stdin
TOOL_INFO=$(cat)
TOOL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_name // "unknown"')

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Authorization hook invoked for tool: $TOOL_NAME" >> "$LOG_FILE"

# Only intercept Edit/Write operations
if [[ ! "$TOOL_NAME" =~ ^(Edit|Write)$ ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Extract session ID from tool info, fall back to uuidgen
SESSION_ID=$(echo "$TOOL_INFO" | jq -r '.session_id // .sessionId // ""')
if [[ -z "$SESSION_ID" ]]; then
    SESSION_ID=$(uuidgen 2>/dev/null | tr '[:upper:]' '[:lower:]' || $PYTHON_CMD -c 'import uuid; print(str(uuid.uuid4()))')
fi
export SESSION_ID

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Checking authorization for $TOOL_NAME (session: ${SESSION_ID:0:8}...)" >> "$LOG_FILE"

# Run Python authorization adapter
set +e
RESULT=$(echo "$TOOL_INFO" | \
    SESSION_ID="$SESSION_ID" \
    $PYTHON_CMD "${HOOKS_LIB}/auth_gate_adapter.py" 2>>"$LOG_FILE")
EXIT_CODE=$?
set -e

# Handle exit codes
if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Authorization ALLOWED for $TOOL_NAME (session: ${SESSION_ID:0:8}...)" >> "$LOG_FILE"
    echo "$RESULT"
elif [ $EXIT_CODE -eq 1 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Authorization DENIED for $TOOL_NAME (session: ${SESSION_ID:0:8}...)" >> "$LOG_FILE"
    echo "$RESULT"
    exit 2
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: Authorization adapter failed with code $EXIT_CODE, failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi
