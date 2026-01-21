#!/bin/bash
# PostToolUse Quality Enforcement Hook - Portable Plugin Version
# Auto-fixes naming convention violations after files are written

set -euo pipefail

# Portable Plugin Configuration
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${HOOKS_DIR}/logs/post-tool-use.log"

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

# Kafka configuration (no fallback - must be set in .env)
KAFKA_ENABLED="false"
if [[ -n "${KAFKA_BOOTSTRAP_SERVERS:-}" ]]; then
    KAFKA_ENABLED="true"
    export KAFKA_BROKERS="${KAFKA_BROKERS:-${KAFKA_BOOTSTRAP_SERVERS:-}}"
fi

# Get tool info from stdin
TOOL_INFO=$(cat)

# Debug: Save JSON structure
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] PostToolUse JSON:" >> "$LOG_FILE"
echo "$TOOL_INFO" | jq '.' >> "$LOG_FILE" 2>&1 || echo "$TOOL_INFO" >> "$LOG_FILE"

# Extract tool name
TOOL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_name // "unknown"')
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] PostToolUse hook triggered for $TOOL_NAME (plugin mode)" >> "$LOG_FILE"

# For Write/Edit tools, apply auto-fixes
if [ "$TOOL_NAME" = "Write" ] || [ "$TOOL_NAME" = "Edit" ]; then
    FILE_PATH=$(echo "$TOOL_INFO" | jq -r '.tool_input.file_path // .tool_response.filePath // empty')

    if [ -n "$FILE_PATH" ]; then
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] File affected: $FILE_PATH" >> "$LOG_FILE"

        # Run Python enforcer if available
        ENFORCER_SCRIPT="${HOOKS_DIR}/scripts/post_tool_use_enforcer.py"
        if [[ -f "$ENFORCER_SCRIPT" ]]; then
            set +e
            python3 "$ENFORCER_SCRIPT" "$FILE_PATH" 2>> "$LOG_FILE"
            EXIT_CODE=$?
            set -e

            if [ $EXIT_CODE -eq 0 ]; then
                echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Auto-fix completed successfully" >> "$LOG_FILE"
            else
                echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Auto-fix failed with code $EXIT_CODE" >> "$LOG_FILE"
            fi
        fi
    fi
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Tool $TOOL_NAME not applicable for auto-fix" >> "$LOG_FILE"
fi

# Enhanced metrics collection (async, non-blocking)
if [[ -f "${HOOKS_LIB}/hook_event_logger.py" && -f "${HOOKS_LIB}/post_tool_metrics.py" ]]; then
    ENABLE_DB_LOGGING="${ENABLE_HOOK_DATABASE_LOGGING:-false}"

    if [[ "$ENABLE_DB_LOGGING" == "true" ]]; then
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Database logging enabled" >> "$LOG_FILE"
        (
            export TOOL_INFO HOOKS_LIB LOG_FILE
            python3 << 'EOF' 2>>"${LOG_FILE}"
import sys
import os
import json

sys.path.insert(0, os.environ['HOOKS_LIB'])
from hook_event_logger import HookEventLogger
from post_tool_metrics import collect_post_tool_metrics
from correlation_manager import get_correlation_context

tool_info = json.loads(os.environ['TOOL_INFO'])
tool_name = tool_info.get('tool_name', 'unknown')
file_path = tool_info.get('tool_input', {}).get('file_path', None)
tool_output = tool_info.get('tool_response', None)

try:
    enhanced_metadata = collect_post_tool_metrics(tool_info)
except Exception as e:
    enhanced_metadata = {
        'success_classification': 'unknown',
        'quality_metrics': {'quality_score': 0.0},
        'performance_metrics': {'execution_time_ms': 0},
        'execution_analysis': {'deviation_from_expected': 'none'}
    }

corr_context = get_correlation_context()

logger = HookEventLogger()
logger.log_event(
    source='PostToolUse',
    action='tool_completion',
    resource='tool',
    resource_id=tool_name,
    payload={
        'tool_name': tool_name,
        'tool_output': tool_output,
        'file_path': file_path,
        'enhanced_metadata': enhanced_metadata,
    },
    metadata={
        'hook_type': 'PostToolUse',
        'correlation_id': corr_context.get('correlation_id') if corr_context else None,
        'agent_name': corr_context.get('agent_name') if corr_context else None,
        **enhanced_metadata
    }
)
EOF
        ) &
    fi
fi

# Error detection and logging
TOOL_ERROR=$(echo "$TOOL_INFO" | jq -r '.tool_response.error // .error // empty' 2>/dev/null)
if [[ -n "$TOOL_ERROR" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Tool error detected: $TOOL_ERROR" >> "$LOG_FILE"
fi

# Emit tool.executed event to Kafka (async, non-blocking)
# Uses omniclaude-emit CLI with 250ms hard timeout
SESSION_ID=$(echo "$TOOL_INFO" | jq -r '.sessionId // .session_id // ""' 2>/dev/null || echo "")
# Pre-generate UUID fallback if SESSION_ID not provided (avoid inline Python in async subshell)
if [[ -z "$SESSION_ID" ]]; then
    SESSION_ID=$(uuidgen 2>/dev/null | tr '[:upper:]' '[:lower:]' || python3 -c 'import uuid; print(uuid.uuid4())')
fi
TOOL_SUCCESS="true"
if [[ -n "$TOOL_ERROR" ]]; then
    TOOL_SUCCESS="false"
fi

# Extract duration if available
DURATION_MS=$(echo "$TOOL_INFO" | jq -r '.duration_ms // .durationMs // ""' 2>/dev/null || echo "")

if [[ "$KAFKA_ENABLED" == "true" ]]; then
    (
        TOOL_SUMMARY="${TOOL_NAME} on ${FILE_PATH:-unknown}"
        TOOL_SUMMARY="${TOOL_SUMMARY:0:500}"

        python3 -m omniclaude.hooks.cli_emit tool-executed \
            --session-id "$SESSION_ID" \
            --tool-name "$TOOL_NAME" \
            $([ "$TOOL_SUCCESS" = "true" ] && echo "--success" || echo "--failure") \
            ${DURATION_MS:+--duration-ms "$DURATION_MS"} \
            --summary "$TOOL_SUMMARY" \
            >> "$LOG_FILE" 2>&1 || true
    ) &
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Tool event emission started" >> "$LOG_FILE"
fi

# Always pass through original output
printf '%s\n' "$TOOL_INFO"
exit 0
