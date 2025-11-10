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

    python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from action_logging_helpers import log_error
log_error(
    error_type='$error_type',
    error_message='''$error_message''',
    error_context=$error_context,
    duration_ms=${duration_ms:-None}
)
" 2>/dev/null || echo "[Warning] Failed to log error: $error_type" >&2
}

# Log success event
# Args: success_type, success_message, success_context_json, [duration_ms], [quality_score]
log_success() {
    local success_type="${1:-TaskCompleted}"
    local success_message="${2:-}"
    local success_context="${3:-{}}"
    local duration_ms="${4:-}"
    local quality_score="${5:-}"

    python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from action_logging_helpers import log_success
log_success(
    success_type='$success_type',
    success_message='''$success_message''',
    success_context=$success_context,
    duration_ms=${duration_ms:-None},
    quality_score=${quality_score:-None}
)
" 2>/dev/null || echo "[Warning] Failed to log success: $success_type" >&2
}

# Log tool call event
# Args: tool_name, tool_parameters_json, tool_result_json, [duration_ms]
log_tool_call() {
    local tool_name="${1}"
    local tool_parameters="${2:-{}}"
    local tool_result="${3:-{}}"
    local duration_ms="${4:-}"

    python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from action_logging_helpers import log_tool_call
log_tool_call(
    tool_name='$tool_name',
    tool_parameters=$tool_parameters,
    tool_result=$tool_result,
    duration_ms=${duration_ms:-None}
)
" 2>/dev/null || echo "[Warning] Failed to log tool call: $tool_name" >&2
}

# Log decision event
# Args: decision_type, decision_details_json, [duration_ms]
log_decision() {
    local decision_type="${1}"
    local decision_details="${2:-{}}"
    local duration_ms="${3:-}"

    python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from action_logging_helpers import log_decision
log_decision(
    decision_type='$decision_type',
    decision_details=$decision_details,
    duration_ms=${duration_ms:-None}
)
" 2>/dev/null || echo "[Warning] Failed to log decision: $decision_type" >&2
}

# If sourced, export functions
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    export -f log_error
    export -f log_success
    export -f log_tool_call
    export -f log_decision
fi
