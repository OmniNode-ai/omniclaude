#!/bin/bash
# PreToolUse hook for quality enforcement with correlation ID tracking
# Intercepts Write/Edit/MultiEdit operations for quality validation
#
# This hook is called before Write, Edit, and MultiEdit tool executions.
# It reads tool information from stdin (JSON), validates it against quality
# standards, and can modify or pass through the tool call.
#
# Exit Codes:
#   0 - Success (output modified or original tool call)
#   2 - Blocked tool execution (violations detected)
#   Other - Error (pass through original with logging)

set -euo pipefail

# Configuration
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$HOOK_DIR/quality_enforcer.py"
LOG_FILE="$HOOK_DIR/logs/quality_enforcer.log"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# ============================================================================
# CORRELATION ID TRACKING
# ============================================================================

# Generate or reuse correlation ID for request tracing
if [ -z "${CORRELATION_ID:-}" ]; then
    CORRELATION_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
fi
export CORRELATION_ID

# Generate root_id if not exists (represents the top-level operation)
if [ -z "${ROOT_ID:-}" ]; then
    ROOT_ID="$CORRELATION_ID"
fi
export ROOT_ID

# Parent ID optional (for hierarchical operation tracking)
export PARENT_ID="${PARENT_ID:-}"

# Session ID (use existing or generate new session identifier)
if [ -z "${SESSION_ID:-}" ]; then
    SESSION_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
fi
export SESSION_ID

# Log correlation context to stderr for debugging (doesn't interfere with stdout)
echo "[TRACE] Quality Hook - Correlation: $CORRELATION_ID, Root: $ROOT_ID, Session: $SESSION_ID" >&2

# ============================================================================
# TOOL INTERCEPTION & VALIDATION
# ============================================================================

# Extract tool information from stdin
TOOL_INFO=$(cat)
TOOL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_name // "unknown"')

# Log invocation with timestamp and correlation context
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [CID:${CORRELATION_ID:0:8}] Hook invoked for tool: $TOOL_NAME" >> "$LOG_FILE"

# Only intercept Write/Edit/MultiEdit operations
# All other tools are passed through immediately
if [[ ! "$TOOL_NAME" =~ ^(Write|Edit|MultiEdit)$ ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Check if Python script exists
if [[ ! -f "$PYTHON_SCRIPT" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [CID:${CORRELATION_ID:0:8}] WARNING: quality_enforcer.py not found, passing through" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi

# ============================================================================
# PYTHON QUALITY ENFORCER EXECUTION
# ============================================================================

# Run Python quality enforcer with correlation ID context
# Let stderr pass through to Claude Code so warnings are visible
# (stderr contains user-facing warnings, stdout contains JSON result)
# Temporarily disable exit-on-error to capture Python exit code
set +e
RESULT=$(echo "$TOOL_INFO" | \
    CORRELATION_ID="$CORRELATION_ID" \
    ROOT_ID="$ROOT_ID" \
    PARENT_ID="$PARENT_ID" \
    SESSION_ID="$SESSION_ID" \
    python3 "$PYTHON_SCRIPT")
EXIT_CODE=$?
set -e

# ============================================================================
# DATABASE EVENT LOGGING WITH CORRELATION CONTEXT
# ============================================================================

# Log PreToolUse event to database with full correlation context and enhanced metadata (async, non-blocking)
if [[ -f "$HOOK_DIR/lib/hook_event_logger.py" ]]; then
    (
        python3 -c "
import sys
sys.path.insert(0, '$HOOK_DIR/lib')
from hook_event_logger import log_pretooluse
from correlation_manager import get_correlation_context
import json

# Get tool info
tool_info = json.loads('''$TOOL_INFO''')
tool_name = tool_info.get('tool_name', 'unknown')
tool_input = tool_info.get('tool_input', {})

# Get correlation context from UserPromptSubmit
corr_context = get_correlation_context()
correlation_id = corr_context.get('correlation_id') if corr_context else None

# Use UserPromptSubmit correlation ID if available, otherwise use local one
final_corr_id = correlation_id or '$CORRELATION_ID'

# Extract enhanced metadata from result if available (from quality enforcer)
result_str = '''$RESULT'''
enhanced_metadata = {}
try:
    if result_str:
        result_json = json.loads(result_str)
        # Check if enforcer added enhanced metadata
        if 'enhanced_metadata' in result_json:
            enhanced_metadata = result_json['enhanced_metadata']
except:
    pass

# Enhanced quality check result with decision intelligence
quality_check = {
    'hook_correlation_id': '$CORRELATION_ID',
    'user_correlation_id': correlation_id,
    'agent_name': corr_context.get('agent_name') if corr_context else None,
    'agent_domain': corr_context.get('agent_domain') if corr_context else None,
    'prompt_preview': corr_context.get('prompt_preview') if corr_context else None,
    'session_id': '$SESSION_ID',
    'root_id': '$ROOT_ID',
    'enhanced_metadata': enhanced_metadata
}

log_pretooluse(
    tool_name=tool_name,
    tool_input=tool_input,
    correlation_id=final_corr_id,
    quality_check_result=quality_check
)
" 2>/dev/null
    ) &
fi

# ============================================================================
# EXIT CODE HANDLING
# ============================================================================

# Handle different exit codes
if [ $EXIT_CODE -eq 0 ]; then
    # Success - output modified tool call or original
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [CID:${CORRELATION_ID:0:8}] Quality check passed for $TOOL_NAME" >> "$LOG_FILE"
    echo "$RESULT"
elif [ $EXIT_CODE -eq 1 ]; then
    # Blocked due to violations - output hookSpecificOutput JSON and exit with code 2
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [CID:${CORRELATION_ID:0:8}] Quality check BLOCKED for $TOOL_NAME (violations detected)" >> "$LOG_FILE"
    echo "$RESULT"
    exit 2  # Exit code 2 tells Claude Code to block the tool execution
else
    # Other error - log and pass through original
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [CID:${CORRELATION_ID:0:8}] ERROR: Quality enforcer failed with code $EXIT_CODE for $TOOL_NAME" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi
