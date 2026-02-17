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

# Load environment variables (before common.sh so KAFKA_BOOTSTRAP_SERVERS is available)
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# Source shared functions (provides PYTHON_CMD, KAFKA_ENABLED, get_time_ms)
source "${HOOKS_DIR}/scripts/common.sh"

export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

# Get tool info from stdin
TOOL_INFO=$(cat)
if ! echo "$TOOL_INFO" | jq -e . >/dev/null 2>>"$LOG_FILE"; then
    log "ERROR: Malformed JSON on stdin for PostToolUse"
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Debug: Save JSON structure
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] PostToolUse JSON:" >> "$LOG_FILE"
echo "$TOOL_INFO" | jq '.' >> "$LOG_FILE" 2>&1 || echo "$TOOL_INFO" >> "$LOG_FILE"

# Extract tool name
TOOL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_name // "unknown"')
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] PostToolUse hook triggered for $TOOL_NAME (plugin mode)" >> "$LOG_FILE"

# Extract session ID early — needed by pattern enforcement (line ~131) and Kafka emission
SESSION_ID=$(echo "$TOOL_INFO" | jq -r '.sessionId // .session_id // ""' 2>/dev/null || echo "")
if [[ -z "$SESSION_ID" ]]; then
    SESSION_ID=$(uuidgen 2>/dev/null | tr '[:upper:]' '[:lower:]' || "$PYTHON_CMD" -c 'import uuid; print(uuid.uuid4())')
fi

# -----------------------------------------------------------------------
# Pipeline Trace Logging — unified trace for Skill/Task/routing visibility
# tail -f ~/.claude/logs/pipeline-trace.log to see the full chain
# -----------------------------------------------------------------------
TRACE_LOG="$HOME/.claude/logs/pipeline-trace.log"
mkdir -p "$(dirname "$TRACE_LOG")" 2>/dev/null
TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

if [[ "$TOOL_NAME" == "Skill" ]]; then
    SKILL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_input.skill // .tool_input.name // "unknown"' 2>/dev/null)
    SKILL_ERROR=$(echo "$TOOL_INFO" | jq -r '.tool_response.error // ""' 2>/dev/null)
    if [[ -n "$SKILL_ERROR" ]]; then
        echo "[$TS] [PostToolUse] SKILL_LOAD_FAILED skill=$SKILL_NAME error=$SKILL_ERROR" >> "$TRACE_LOG"
    else
        echo "[$TS] [PostToolUse] SKILL_LOADED skill=$SKILL_NAME args=[REDACTED]" >> "$TRACE_LOG"
    fi
elif [[ "$TOOL_NAME" == "Task" ]]; then
    SUBAGENT_TYPE=$(echo "$TOOL_INFO" | jq -r '.tool_input.subagent_type // "unknown"' 2>/dev/null)
    TASK_MODEL=$(echo "$TOOL_INFO" | jq -r '.tool_input.model // "default"' 2>/dev/null)
    echo "[$TS] [PostToolUse] TASK_DISPATCHED subagent_type=$SUBAGENT_TYPE model=$TASK_MODEL description=[REDACTED]" >> "$TRACE_LOG"
elif [[ "$TOOL_NAME" == "Edit" || "$TOOL_NAME" == "Write" ]]; then
    EDIT_FILE=$(echo "$TOOL_INFO" | jq -r '.tool_input.file_path // "unknown"' 2>/dev/null)
    EDIT_FILE_SHORT="${EDIT_FILE##*/}"
    echo "[$TS] [PostToolUse] FILE_MODIFIED tool=$TOOL_NAME file=$EDIT_FILE_SHORT path=$EDIT_FILE" >> "$TRACE_LOG"
fi

# For Write/Edit tools, apply auto-fixes
if [ "$TOOL_NAME" = "Write" ] || [ "$TOOL_NAME" = "Edit" ]; then
    FILE_PATH=$(echo "$TOOL_INFO" | jq -r '.tool_input.file_path // .tool_response.filePath // empty')

    if [ -n "$FILE_PATH" ]; then
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] File affected: $FILE_PATH" >> "$LOG_FILE"

        # Run Python enforcer if available
        ENFORCER_SCRIPT="${HOOKS_DIR}/scripts/post_tool_use_enforcer.py"
        if [[ -f "$ENFORCER_SCRIPT" ]]; then
            set +e
            "$PYTHON_CMD" "$ENFORCER_SCRIPT" "$FILE_PATH" 2>> "$LOG_FILE"
            EXIT_CODE=$?
            set -e

            if [ $EXIT_CODE -eq 0 ]; then
                echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Auto-fix completed successfully" >> "$LOG_FILE"
            else
                echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Auto-fix failed with code $EXIT_CODE" >> "$LOG_FILE"
            fi
        fi

        # -----------------------------------------------------------------------
        # Pattern Enforcement Advisory (OMN-2263)
        # -----------------------------------------------------------------------
        # Queries pattern store for applicable patterns, checks session cooldown,
        # runs compliance check, outputs advisory JSON. Async, non-blocking.
        # Gated behind ENABLE_LOCAL_INFERENCE_PIPELINE + ENABLE_PATTERN_ENFORCEMENT.
        # 300ms budget. All failures silent.
        # -----------------------------------------------------------------------
        PATTERN_ENFORCEMENT_ENABLED=$(_normalize_bool "${ENABLE_PATTERN_ENFORCEMENT:-false}")
        INFERENCE_PIPELINE_ENABLED=$(_normalize_bool "${ENABLE_LOCAL_INFERENCE_PIPELINE:-false}")

        if [[ "$PATTERN_ENFORCEMENT_ENABLED" == "true" && "$INFERENCE_PIPELINE_ENABLED" == "true" ]]; then
            ENFORCEMENT_SCRIPT="${HOOKS_LIB}/pattern_enforcement.py"
            if [[ -f "$ENFORCEMENT_SCRIPT" ]]; then
                (
                    # Detect language from file extension
                    ENFORCE_LANGUAGE=""
                    case "${FILE_PATH##*.}" in
                        py) ENFORCE_LANGUAGE="python" ;;
                        js) ENFORCE_LANGUAGE="javascript" ;;
                        ts|tsx) ENFORCE_LANGUAGE="typescript" ;;
                        rs) ENFORCE_LANGUAGE="rust" ;;
                        go) ENFORCE_LANGUAGE="go" ;;
                        *) ENFORCE_LANGUAGE="" ;;
                    esac

                    # Build JSON input for enforcement script
                    ENFORCE_INPUT=$(jq -n \
                        --arg file_path "$FILE_PATH" \
                        --arg session_id "$SESSION_ID" \
                        --arg language "$ENFORCE_LANGUAGE" \
                        --arg content_preview "" \
                        '{
                            file_path: $file_path,
                            session_id: $session_id,
                            language: (if $language == "" then null else $language end),
                            content_preview: $content_preview
                        }'
                    )

                    if [[ -n "$ENFORCE_INPUT" && "$ENFORCE_INPUT" != "null" ]]; then
                        ENFORCE_RESULT=$(echo "$ENFORCE_INPUT" | "$PYTHON_CMD" "$ENFORCEMENT_SCRIPT" 2>>"$LOG_FILE")
                        if [[ -n "$ENFORCE_RESULT" ]]; then
                            ADVISORY_COUNT=$(echo "$ENFORCE_RESULT" | jq -r '.advisories | length' 2>/dev/null || echo "0")
                            echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Pattern enforcement: $ADVISORY_COUNT advisory(ies)" >> "$LOG_FILE"
                            if [[ "$ADVISORY_COUNT" -gt 0 ]]; then
                                echo "$ENFORCE_RESULT" | jq -c '.' >> "$LOG_FILE" 2>/dev/null
                            fi
                        fi
                    fi
                ) &
                echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Pattern enforcement started (async)" >> "$LOG_FILE"
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
            "$PYTHON_CMD" << 'EOF' 2>>"${LOG_FILE}"
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

        # Build JSON payload for tool.executed event
        # Use jq for proper JSON escaping of all fields
        PAYLOAD=$(jq -n \
            --arg session_id "$SESSION_ID" \
            --arg tool_name "$TOOL_NAME" \
            --argjson success "$([[ "$TOOL_SUCCESS" == "true" ]] && echo "true" || echo "false")" \
            --arg duration_ms "${DURATION_MS:-}" \
            --arg summary "$TOOL_SUMMARY" \
            '{
                session_id: $session_id,
                tool_name: $tool_name,
                success: $success,
                summary: $summary
            } + (if $duration_ms != "" then {duration_ms: ($duration_ms | tonumber)} else {} end)'
        )

        # Validate payload was constructed successfully
        if [[ -z "$PAYLOAD" || "$PAYLOAD" == "null" ]]; then
            echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] WARNING: Failed to construct tool payload (jq failed), skipping emission" >> "$LOG_FILE"
        else
            emit_via_daemon "tool.executed" "$PAYLOAD" 50
        fi
    ) &
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Tool event emission started" >> "$LOG_FILE"
fi

# -----------------------------------------------------------------------
# INTERIM: Code Content Capture for Pattern Learning (OMN-1702)
# -----------------------------------------------------------------------
# Captures tool execution content for omniintelligence pattern learning.
# This is an INTERIM solution emitting raw JSON until ModelToolExecutionContent
# is available in omnibase_core.
#
# Content Limits:
#   - Max content capture: 50KB (head -c 50000) - safety bound for large files
#   - Preview truncation: 2000 chars - sent to Kafka for pattern learning
#   - Full content is hashed but NOT sent to avoid oversized messages
#
# Will be migrated to use proper Pydantic model in OMN-1703.
# -----------------------------------------------------------------------
if [[ "$KAFKA_ENABLED" == "true" ]] && [[ "$TOOL_NAME" =~ ^(Read|Write|Edit)$ ]]; then
    (
        # Extract file path for Read tool (not extracted earlier for non-Write/Edit tools)
        # Note: This runs in a subshell, so FILE_PATH here won't affect outer scope
        if [[ "$TOOL_NAME" == "Read" ]]; then
            FILE_PATH=$(echo "$TOOL_INFO" | jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null)
        fi

        # Extract content from tool response (max 50KB for safety)
        # For Read: prefer .tool_response.content if structured, fallback to raw .tool_response
        # For Write/Edit: content is in tool_input
        if [[ "$TOOL_NAME" == "Read" ]]; then
            # Try structured content first, then fall back to raw response
            CONTENT=$(echo "$TOOL_INFO" | jq -r '.tool_response.content // .tool_response // ""' 2>/dev/null | head -c 50000)
        else
            CONTENT=$(echo "$TOOL_INFO" | jq -r '.tool_input.content // .tool_input.new_string // ""' 2>/dev/null | head -c 50000)
        fi

        if [[ -n "$CONTENT" ]] && [[ "$CONTENT" != "null" ]]; then
            CONTENT_LENGTH=${#CONTENT}
            CONTENT_PREVIEW="${CONTENT:0:2000}"

            # Compute SHA256 hash (use shasum on macOS, sha256sum on Linux)
            if command -v shasum >/dev/null 2>&1; then
                CONTENT_HASH="sha256:$(echo -n "$CONTENT" | shasum -a 256 | cut -d' ' -f1)"
            elif command -v sha256sum >/dev/null 2>&1; then
                CONTENT_HASH="sha256:$(echo -n "$CONTENT" | sha256sum | cut -d' ' -f1)"
            else
                CONTENT_HASH=""
            fi

            # Detect language from file extension
            LANGUAGE=""
            if [[ -n "$FILE_PATH" ]]; then
                case "${FILE_PATH##*.}" in
                    py) LANGUAGE="python" ;;
                    js) LANGUAGE="javascript" ;;
                    ts) LANGUAGE="typescript" ;;
                    tsx) LANGUAGE="typescript" ;;
                    jsx) LANGUAGE="javascript" ;;
                    rs) LANGUAGE="rust" ;;
                    go) LANGUAGE="go" ;;
                    java) LANGUAGE="java" ;;
                    rb) LANGUAGE="ruby" ;;
                    sh|bash) LANGUAGE="shell" ;;
                    yml|yaml) LANGUAGE="yaml" ;;
                    json) LANGUAGE="json" ;;
                    md) LANGUAGE="markdown" ;;
                    sql) LANGUAGE="sql" ;;
                    html) LANGUAGE="html" ;;
                    css) LANGUAGE="css" ;;
                    c|h) LANGUAGE="c" ;;
                    cpp|hpp|cc|cxx) LANGUAGE="cpp" ;;
                    *) LANGUAGE="unknown" ;;
                esac
            fi

            # Get correlation ID from context if available
            CORRELATION_ID_FILE="$PROJECT_ROOT/tmp/correlation_id"
            CORRELATION_ID=$(cat "$CORRELATION_ID_FILE" 2>/dev/null || true)

            # Determine success/failure flag using variable for clarity and robustness
            SUCCESS_FLAG="--success"
            [[ "$TOOL_SUCCESS" != "true" ]] && SUCCESS_FLAG="--failure"

            # Emit tool content event
            "$PYTHON_CMD" -m omniclaude.hooks.cli_emit tool-content \
                --session-id "$SESSION_ID" \
                --tool-name "$TOOL_NAME" \
                --tool-type "$TOOL_NAME" \
                ${FILE_PATH:+--file-path "$FILE_PATH"} \
                --content-preview "$CONTENT_PREVIEW" \
                --content-length "$CONTENT_LENGTH" \
                ${CONTENT_HASH:+--content-hash "$CONTENT_HASH"} \
                ${LANGUAGE:+--language "$LANGUAGE"} \
                "$SUCCESS_FLAG" \
                ${DURATION_MS:+--duration-ms "$DURATION_MS"} \
                ${CORRELATION_ID:+--correlation-id "$CORRELATION_ID"} \
                >> "$LOG_FILE" 2>&1 || { rc=$?; echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Tool content emit failed (exit=$rc, non-fatal)" >> "$LOG_FILE"; }
        fi
    ) &
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Tool content emission started for $TOOL_NAME" >> "$LOG_FILE"
fi

# Always pass through original output
printf '%s\n' "$TOOL_INFO"
exit 0
