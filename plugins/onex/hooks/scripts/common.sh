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

# Detect if native millisecond timing is available (GNU date supports %N)
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
    export KAFKA_BROKERS="${KAFKA_BROKERS:-${KAFKA_BOOTSTRAP_SERVERS:-}}"
fi
export KAFKA_ENABLED
