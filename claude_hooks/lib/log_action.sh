#!/bin/bash
# Convenient bash wrapper for action logging
# Wraps action_logging_helpers.py for use in shell scripts and hooks
#
# Usage:
#   source log_action.sh
#
#   # Log error
#   log_error "ToolExecutionError" "Read tool failed" '{"file_path": "/path/to/file.py"}'
#
#   # Log success
#   log_success "TaskCompleted" "Code generation completed" '{"files_created": 5}'
#
#   # Log tool call
#   log_tool_call "Read" '{"file_path": "/path/to/file.py"}' '{"line_count": 100}' 45
#
#   # Log decision
#   log_decision "agent_selected" '{"agent": "polymorphic-agent", "confidence": 0.95}'

# Get script directory (handles symlinks correctly)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Log error event
# Args: error_type, error_message, error_context_json, [duration_ms]
log_error() {
    local error_type="${1:-UnknownError}"
    local error_message="${2:-}"
    local error_context="${3:-{}}"
    local duration_ms="${4:-}"

    # Export variables to avoid shell injection
    export LOG_ERROR_TYPE="$error_type"
    export LOG_ERROR_MESSAGE="$error_message"
    export LOG_ERROR_CONTEXT="$error_context"
    export LOG_DURATION_MS="$duration_ms"
    export LOG_SCRIPT_DIR="$SCRIPT_DIR"

    python3 << 'EOF' 2>/dev/null || echo "[Warning] Failed to log error: $error_type" >&2
import sys
import os
import json
sys.path.insert(0, os.environ['LOG_SCRIPT_DIR'])
from action_logging_helpers import log_error
log_error(
    error_type=os.environ['LOG_ERROR_TYPE'],
    error_message=os.environ['LOG_ERROR_MESSAGE'],
    error_context=json.loads(os.environ['LOG_ERROR_CONTEXT']),
    duration_ms=int(os.environ['LOG_DURATION_MS']) if os.environ.get('LOG_DURATION_MS') else None
)
EOF
}

# Log success event
# Args: success_type, success_message, success_context_json, [duration_ms], [quality_score]
log_success() {
    local success_type="${1:-TaskCompleted}"
    local success_message="${2:-}"
    local success_context="${3:-{}}"
    local duration_ms="${4:-}"
    local quality_score="${5:-}"

    # Export variables to avoid shell injection
    export LOG_SUCCESS_TYPE="$success_type"
    export LOG_SUCCESS_MESSAGE="$success_message"
    export LOG_SUCCESS_CONTEXT="$success_context"
    export LOG_DURATION_MS="$duration_ms"
    export LOG_QUALITY_SCORE="$quality_score"
    export LOG_SCRIPT_DIR="$SCRIPT_DIR"

    python3 << 'EOF' 2>/dev/null || echo "[Warning] Failed to log success: $success_type" >&2
import sys
import os
import json
sys.path.insert(0, os.environ['LOG_SCRIPT_DIR'])
from action_logging_helpers import log_success
log_success(
    success_type=os.environ['LOG_SUCCESS_TYPE'],
    success_message=os.environ['LOG_SUCCESS_MESSAGE'],
    success_context=json.loads(os.environ['LOG_SUCCESS_CONTEXT']),
    duration_ms=int(os.environ['LOG_DURATION_MS']) if os.environ.get('LOG_DURATION_MS') else None,
    quality_score=float(os.environ['LOG_QUALITY_SCORE']) if os.environ.get('LOG_QUALITY_SCORE') else None
)
EOF
}

# Log tool call event
# Args: tool_name, tool_parameters_json, tool_result_json, [duration_ms]
log_tool_call() {
    local tool_name="${1}"
    local tool_parameters="${2:-{}}"
    local tool_result="${3:-{}}"
    local duration_ms="${4:-}"

    # Export variables to avoid shell injection
    export LOG_TOOL_NAME="$tool_name"
    export LOG_TOOL_PARAMETERS="$tool_parameters"
    export LOG_TOOL_RESULT="$tool_result"
    export LOG_DURATION_MS="$duration_ms"
    export LOG_SCRIPT_DIR="$SCRIPT_DIR"

    python3 << 'EOF' 2>/dev/null || echo "[Warning] Failed to log tool call: $tool_name" >&2
import sys
import os
import json
sys.path.insert(0, os.environ['LOG_SCRIPT_DIR'])
from action_logging_helpers import log_tool_call
log_tool_call(
    tool_name=os.environ['LOG_TOOL_NAME'],
    tool_parameters=json.loads(os.environ['LOG_TOOL_PARAMETERS']),
    tool_result=json.loads(os.environ['LOG_TOOL_RESULT']),
    duration_ms=int(os.environ['LOG_DURATION_MS']) if os.environ.get('LOG_DURATION_MS') else None
)
EOF
}

# Log decision event
# Args: decision_type, decision_details_json, [duration_ms]
log_decision() {
    local decision_type="${1}"
    local decision_details="${2:-{}}"
    local duration_ms="${3:-}"

    # Export variables to avoid shell injection
    export LOG_DECISION_TYPE="$decision_type"
    export LOG_DECISION_DETAILS="$decision_details"
    export LOG_DURATION_MS="$duration_ms"
    export LOG_SCRIPT_DIR="$SCRIPT_DIR"

    python3 << 'EOF' 2>/dev/null || echo "[Warning] Failed to log decision: $decision_type" >&2
import sys
import os
import json
sys.path.insert(0, os.environ['LOG_SCRIPT_DIR'])
from action_logging_helpers import log_decision
log_decision(
    decision_type=os.environ['LOG_DECISION_TYPE'],
    decision_details=json.loads(os.environ['LOG_DECISION_DETAILS']),
    duration_ms=int(os.environ['LOG_DURATION_MS']) if os.environ.get('LOG_DURATION_MS') else None
)
EOF
}

# If sourced, export functions
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    export -f log_error
    export -f log_success
    export -f log_tool_call
    export -f log_decision
fi
