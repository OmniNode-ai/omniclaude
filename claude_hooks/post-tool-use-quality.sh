#!/bin/bash

# PostToolUse Quality Enforcement Hook
# Auto-fixes naming convention violations after files are written

# Exit Codes:
#   0 - Success (corrections applied or no violations)
#   1 - Error during processing

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/post_tool_use_enforcer.py"
LOG_FILE="${SCRIPT_DIR}/logs/post-tool-use.log"

# Kafka/Redpanda configuration (moved to 192.168.86.200)
export KAFKA_BROKERS="${KAFKA_BROKERS:-192.168.86.200:29102}"

# Database credentials for hook event logging (required from .env)
# Set POSTGRES_PASSWORD in your .env file or environment
# Note: Using POSTGRES_PASSWORD directly (no alias)

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Get tool info from stdin
TOOL_INFO=$(cat)

# Debug: Save full JSON to inspect structure
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] PostToolUse JSON:" >> "$LOG_FILE"
echo "$TOOL_INFO" | jq '.' >> "$LOG_FILE" 2>&1 || echo "$TOOL_INFO" >> "$LOG_FILE"

# Extract tool name for logging (PostToolUse uses .tool_name, not .toolUseInfo.toolName)
TOOL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_name // "unknown"')

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] PostToolUse hook triggered for $TOOL_NAME" >> "$LOG_FILE"

# For Write/Edit tools, apply auto-fixes
if [ "$TOOL_NAME" = "Write" ] || [ "$TOOL_NAME" = "Edit" ]; then
    # Extract file path from JSON (PostToolUse provides file paths in the JSON, not env var)
    FILE_PATH=$(echo "$TOOL_INFO" | jq -r '.tool_input.file_path // .tool_response.filePath // empty')

    if [ -n "$FILE_PATH" ]; then
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] File affected: $FILE_PATH" >> "$LOG_FILE"

        # Run Python enforcer to apply fixes
        set +e
        python3 "$PYTHON_SCRIPT" "$FILE_PATH" 2>> "$LOG_FILE"
        EXIT_CODE=$?
        set -e

        if [ $EXIT_CODE -eq 0 ]; then
            echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Auto-fix completed successfully" >> "$LOG_FILE"
        else
            echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Auto-fix failed with code $EXIT_CODE" >> "$LOG_FILE"
        fi
    else
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] No file path found in JSON" >> "$LOG_FILE"
    fi
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Tool $TOOL_NAME not applicable for auto-fix" >> "$LOG_FILE"
fi

# ============================================================================
# ENHANCED METRICS COLLECTION & DATABASE LOGGING
# ============================================================================

# Collect enhanced metrics and log to database (async, non-blocking)
if [[ -f "${SCRIPT_DIR}/lib/hook_event_logger.py" && -f "${SCRIPT_DIR}/lib/post_tool_metrics.py" ]]; then
    (
        python3 -c "
import sys
sys.path.insert(0, '${SCRIPT_DIR}/lib')
from hook_event_logger import HookEventLogger
from post_tool_metrics import collect_post_tool_metrics
from correlation_manager import get_correlation_context
import json

# Get tool info
tool_info = json.loads('''$TOOL_INFO''')
tool_name = tool_info.get('tool_name', 'unknown')
file_path = tool_info.get('tool_input', {}).get('file_path', None)
tool_output = tool_info.get('tool_response', None)

# Collect enhanced metrics (fast, rule-based)
try:
    enhanced_metadata = collect_post_tool_metrics(tool_info)
except Exception as e:
    enhanced_metadata = {
        'success_classification': 'unknown',
        'quality_metrics': {'quality_score': 0.0},
        'performance_metrics': {'execution_time_ms': 0},
        'execution_analysis': {'deviation_from_expected': 'none'}
    }
    print(f'[Warning] Metrics collection failed: {e}', file=sys.stderr)

# Get correlation context
corr_context = get_correlation_context()

# Log enhanced event to database
logger = HookEventLogger()
event_id = logger.log_event(
    source='PostToolUse',
    action='tool_completion',
    resource='tool',
    resource_id=tool_name,
    payload={
        'tool_name': tool_name,
        'tool_output': tool_output,
        'file_path': file_path,
        'enhanced_metadata': enhanced_metadata,
        'auto_fix_applied': False,
        'auto_fix_details': None
    },
    metadata={
        'hook_type': 'PostToolUse',
        'correlation_id': corr_context.get('correlation_id') if corr_context else None,
        'agent_name': corr_context.get('agent_name') if corr_context else None,
        'agent_domain': corr_context.get('agent_domain') if corr_context else None,
        **enhanced_metadata
    }
)

# Report metrics to log
if enhanced_metadata:
    success = enhanced_metadata.get('success_classification', 'unknown')
    quality_score = enhanced_metadata.get('quality_metrics', {}).get('quality_score', 0.0)
    exec_time = enhanced_metadata.get('performance_metrics', {}).get('execution_time_ms', 0)
    print(f'[PostToolUse] Success: {success}, Quality: {quality_score:.2f}, Time: {exec_time:.2f}ms', file=sys.stderr)
" 2>/dev/null
    ) &
fi

# ============================================================================
# TOOL EXECUTION LOGGING TO agent_actions TABLE VIA KAFKA
# ============================================================================

# Extract correlation context for Kafka logging
if [[ -f "${SCRIPT_DIR}/lib/correlation_manager.py" ]]; then
    CORRELATION_DATA=$(python3 -c "
import sys
sys.path.insert(0, '${SCRIPT_DIR}/lib')
from correlation_manager import get_correlation_context
import json

corr_context = get_correlation_context()
if corr_context:
    print(json.dumps({
        'correlation_id': corr_context.get('correlation_id', ''),
        'agent_name': corr_context.get('agent_name', 'polymorphic-agent'),
        'project_path': corr_context.get('project_path', ''),
        'project_name': corr_context.get('project_name', '')
    }))
" 2>/dev/null)

    if [[ -n "$CORRELATION_DATA" ]]; then
        CORRELATION_ID=$(echo "$CORRELATION_DATA" | jq -r '.correlation_id // empty')
        AGENT_NAME=$(echo "$CORRELATION_DATA" | jq -r '.agent_name // "polymorphic-agent"')
        PROJECT_PATH=$(echo "$CORRELATION_DATA" | jq -r '.project_path // empty')
        PROJECT_NAME=$(echo "$CORRELATION_DATA" | jq -r '.project_name // empty')

        # Log tool execution to agent_actions table via Kafka (non-blocking)
        if [[ -n "$CORRELATION_ID" ]]; then
            (
                # Extract execution time if available
                DURATION_MS=$(echo "$TOOL_INFO" | jq -r '.execution_time_ms // 0' 2>/dev/null || echo "0")

                # Build enhanced details JSON with file operation information for traceability
                DETAILS=$(echo "$TOOL_INFO" | jq -c '
                    .tool_input as $input |
                    {
                        file_path: $input.file_path,
                        content: $input.content,
                        content_before: (if $input.old_string then $input.old_string else null end),
                        content_after: (if $input.new_string then $input.new_string else $input.content end),
                        line_range: (if ($input.offset and $input.limit) then {start: $input.offset, end: ($input.offset + $input.limit)} else null end),
                        old_string: $input.old_string,
                        new_string: $input.new_string,
                        offset: $input.offset,
                        limit: $input.limit,
                        pattern: $input.pattern,
                        glob_pattern: $input.pattern,
                        tool_input: $input
                    }
                ' 2>/dev/null || echo '{"tool_input": {}}')

                # Publish to Kafka via log-agent-action skill
                python3 "${SCRIPT_DIR}/../skills/agent-tracking/log-agent-action/execute_kafka.py" \
                    --agent "$AGENT_NAME" \
                    --action-type "tool_call" \
                    --action-name "$TOOL_NAME" \
                    --details "$DETAILS" \
                    --correlation-id "$CORRELATION_ID" \
                    --duration-ms "$DURATION_MS" \
                    --debug-mode \
                    ${PROJECT_PATH:+--project-path "$PROJECT_PATH"} \
                    ${PROJECT_NAME:+--project-name "$PROJECT_NAME"} \
                    2>>"$LOG_FILE"

                echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Published tool_call event to Kafka (action: $TOOL_NAME, correlation: $CORRELATION_ID)" >> "$LOG_FILE"
            ) &
        else
            echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Skipping Kafka logging: no correlation_id available" >> "$LOG_FILE"
        fi
    fi
fi

# Always pass through original output (PostToolUse doesn't modify it)
# Use printf instead of echo for better reliability with large outputs
printf '%s\n' "$TOOL_INFO"
exit 0
