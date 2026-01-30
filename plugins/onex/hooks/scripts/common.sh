#!/bin/bash
# =============================================================================
# OmniClaude Hooks - Shared Shell Functions
# =============================================================================
# Common utility functions for all hook scripts.
# Source this file at the top of hook scripts after setting PLUGIN_ROOT and PROJECT_ROOT.
#
# Usage:
#   source "${HOOKS_DIR}/scripts/common.sh"
#
# Requires (must be set before sourcing):
#   - PLUGIN_ROOT: Path to the plugin root directory
#   - PROJECT_ROOT: Path to the project root directory
#   - PYTHON_CMD will be exported after sourcing
#   - KAFKA_ENABLED will be exported after sourcing (true/false)
# =============================================================================

# =============================================================================
# Python Environment Detection
# =============================================================================
# Priority: Poetry venv > Plugin venv > Project venv > System Python
#
# This function finds the appropriate Python interpreter to use, preferring
# virtual environments over system Python to ensure dependencies are available.

find_python() {
    # Check for Poetry venv via pyproject.toml
    if command -v poetry >/dev/null 2>&1 && [[ -f "${PROJECT_ROOT}/pyproject.toml" ]]; then
        POETRY_VENV="$(poetry env info --path 2>/dev/null || true)"
        if [[ -n "$POETRY_VENV" && -f "$POETRY_VENV/bin/python3" ]]; then
            echo "$POETRY_VENV/bin/python3"
            return
        fi
    fi

    # Check for plugin-local venv
    if [[ -f "${PLUGIN_ROOT}/lib/.venv/bin/python3" ]]; then
        echo "${PLUGIN_ROOT}/lib/.venv/bin/python3"
        return
    fi

    # Check for project venv
    if [[ -f "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
        echo "${PROJECT_ROOT}/.venv/bin/python3"
        return
    fi

    # Fallback to system Python
    echo "python3"
}

# Export PYTHON_CMD for use in scripts
PYTHON_CMD="$(find_python)"
export PYTHON_CMD

# =============================================================================
# Timing Functions
# =============================================================================
# Get current time in milliseconds.
# Uses native bash date if available (GNU date supports %N), falls back to Python.
# macOS date doesn't support %N, so we detect and fall back appropriately.

# Detect if native millisecond timing is available (GNU date supports %N).
# IMPORTANT: This check runs ONCE at script load time and caches the result.
# We intentionally cache rather than checking per-call because:
#   1. Performance: Avoid subprocess overhead on every timing call
#   2. Consistency: All timestamps in a session use the same method
#   3. Reliability: No race conditions from method changing mid-execution
if date +%s%3N 2>/dev/null | grep -qE '^[0-9]+$'; then
    _USE_NATIVE_TIME=true
else
    _USE_NATIVE_TIME=false
fi

get_time_ms() {
    if [[ "$_USE_NATIVE_TIME" == "true" ]]; then
        date +%s%3N
    else
        $PYTHON_CMD -c "import time; print(int(time.time() * 1000))"
    fi
}

# =============================================================================
# Kafka Configuration
# =============================================================================
# Kafka emission is optional and disabled by default.
# Set KAFKA_BOOTSTRAP_SERVERS in .env to enable.
# No fallback - must be explicitly configured.

KAFKA_ENABLED="false"
if [[ -n "${KAFKA_BOOTSTRAP_SERVERS:-}" ]]; then
    KAFKA_ENABLED="true"
    # Export KAFKA_BROKERS for legacy compatibility with Python scripts
    # that use shared_lib/kafka_config.py's get_kafka_bootstrap_servers()
    # fallback chain: KAFKA_BOOTSTRAP_SERVERS -> KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS -> KAFKA_BROKERS
    export KAFKA_BROKERS="${KAFKA_BROKERS:-${KAFKA_BOOTSTRAP_SERVERS:-}}"
fi
export KAFKA_ENABLED

# =============================================================================
# Emit Daemon Helper (OMN-1631, OMN-1632)
# =============================================================================
# Emit event via emit daemon for fast, non-blocking Kafka emission.
# Single call - daemon handles fan-out to multiple topics.
#
# Requires (must be set before calling):
#   - PYTHON_CMD: Path to Python interpreter (provided by common.sh)
#   - HOOKS_LIB: Path to hooks lib directory (set by caller script)
#   - LOG_FILE: Path to log file (set by caller script)
#
# Usage: emit_via_daemon <event_type> <payload_json> [timeout_ms]
# Returns: 0 on success, 1 on failure (non-fatal)

emit_via_daemon() {
    local event_type="$1"
    local payload="$2"
    local timeout_ms="${3:-50}"

    $PYTHON_CMD "${HOOKS_LIB}/emit_client_wrapper.py" emit \
        --event-type "$event_type" \
        --payload "$payload" \
        --timeout "$timeout_ms" \
        >> "$LOG_FILE" 2>&1 || {
            echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Emit daemon failed for ${event_type} (non-fatal)" >> "$LOG_FILE"
            return 1
        }
}

# =============================================================================
# Logging Helper
# =============================================================================
# Simple timestamped logging to a file.
#
# Requires (must be set before calling):
#   - LOG_FILE: Path to log file (set by caller script)
#
# Usage: log "message to log"

log() {
    printf "[%s] %s\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$*" >> "$LOG_FILE"
}
