#!/bin/bash
# =============================================================================
# OmniClaude Hooks - Shared Shell Functions
# =============================================================================
# Common utility functions for all hook scripts.
# Source this file at the top of hook scripts after setting PLUGIN_ROOT.
#
# Usage:
#   source "${HOOKS_DIR}/scripts/common.sh"
#
# Requires (must be set before sourcing):
#   - PLUGIN_ROOT: Path to the plugin root directory
#   - PROJECT_ROOT: Path to project root (used for .env loading, not for Python)
#
# Exports after sourcing:
#   - PYTHON_CMD: Resolved Python interpreter (hard fails if not found)
#   - KAFKA_ENABLED: "true" or "false"
# =============================================================================

# =============================================================================
# Python Environment Detection
# =============================================================================
# Strict priority chain with NO fallbacks. If no valid Python is found,
# hooks refuse to run. This prevents silent degradation where hooks run
# against the wrong interpreter with missing dependencies.
#
# Priority:
#   1. PLUGIN_PYTHON_BIN env var (explicit override / escape hatch)
#   2. Plugin-bundled venv at PLUGIN_ROOT/lib/.venv (marketplace runtime)
#   3. OMNICLAUDE_PROJECT_ROOT/.venv (explicit dev mode, no heuristics)
#   4. Hard failure with actionable error message

find_python() {
    # 1. Explicit override (escape hatch for custom environments)
    if [[ -n "${PLUGIN_PYTHON_BIN:-}" && -f "${PLUGIN_PYTHON_BIN}" && -x "${PLUGIN_PYTHON_BIN}" ]]; then
        echo "${PLUGIN_PYTHON_BIN}"
        return
    fi

    # 2. Plugin-bundled venv (marketplace runtime — created by deploy.sh)
    if [[ -f "${PLUGIN_ROOT}/lib/.venv/bin/python3" && -x "${PLUGIN_ROOT}/lib/.venv/bin/python3" ]]; then
        echo "${PLUGIN_ROOT}/lib/.venv/bin/python3"
        return
    fi

    # 3. Explicit dev-mode project venv (no heuristics, no CWD probing)
    if [[ -n "${OMNICLAUDE_PROJECT_ROOT:-}" && -f "${OMNICLAUDE_PROJECT_ROOT}/.venv/bin/python3" && -x "${OMNICLAUDE_PROJECT_ROOT}/.venv/bin/python3" ]]; then
        echo "${OMNICLAUDE_PROJECT_ROOT}/.venv/bin/python3"
        return
    fi

    # No fallback: return empty to trigger hard failure
    echo ""
}

# Resolve Python — hard fail if not found
# NOTE: This exit 1 intentionally violates the "hooks exit 0" invariant (CLAUDE.md).
# Rationale: running hooks against the wrong Python produces non-reproducible bugs
# that are far worse than a visible, actionable error. See OMN-2051.
PYTHON_CMD="$(find_python)"
if [[ -z "${PYTHON_CMD}" ]]; then
    echo "ERROR: No valid Python found for ONEX hooks." 1>&2
    echo "  Expected one of:" 1>&2
    echo "    - PLUGIN_PYTHON_BIN=/path/to/python3" 1>&2
    echo "    - ${PLUGIN_ROOT}/lib/.venv/bin/python3 (deploy the plugin)" 1>&2
    echo "    - OMNICLAUDE_PROJECT_ROOT=/path/to/repo with .venv (dev mode)" 1>&2
    exit 1
fi
export PYTHON_CMD

# Log resolved interpreter for debugging (only if LOG_FILE is available)
# Uses inline printf instead of log() which is defined later in this file
if [[ -n "${LOG_FILE:-}" ]]; then
    printf "[%s] Resolved python: %s\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "${PYTHON_CMD}" >> "$LOG_FILE"
fi

# =============================================================================
# Boolean Normalization
# =============================================================================
# Normalizes various boolean representations to "true" or "false".
# Accepts: true, 1, yes (case-insensitive) -> "true"
# Everything else -> "false"

_normalize_bool() {
    # Use tr for lowercase conversion (compatible with bash 3.2 on macOS)
    local val
    val=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$val" in
        true|1|yes) echo "true" ;;
        *) echo "false" ;;
    esac
}

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
# Environment File Loading
# =============================================================================
# Source project .env file if present to pick up KAFKA_BOOTSTRAP_SERVERS and
# other configuration. This enables hooks to use project-specific settings.
#
# Order of precedence:
# 1. Project .env file (highest priority - overrides existing env vars)
# 2. Already-set environment variables
# 3. Default values (lowest priority)
#
# SECURITY NOTE: Using `set -a` exports ALL variables from .env to the environment.
# This means secrets in .env (API keys, passwords, tokens) will be visible to ALL
# subprocesses spawned by hooks. This is standard shell behavior for local dev
# environments but be aware of the implications for sensitive credentials.

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    # Source .env - note this WILL override already-set variables
    # Using set -a to export all variables, then set +a to stop
    set -a
    # shellcheck disable=SC1091
    # Note: We use 2>/dev/null because .env files may contain comments or blank
    # lines that produce benign warnings. Syntax errors are rare in .env files.
    if ! source "${PROJECT_ROOT}/.env" 2>/dev/null; then
        # Only log if LOG_FILE is set (caller script responsibility)
        if [[ -n "${LOG_FILE:-}" ]]; then
            log "WARN: Failed to source ${PROJECT_ROOT}/.env - check file syntax"
        fi
    fi
    set +a
fi

# =============================================================================
# Kafka Configuration
# =============================================================================
# Kafka is REQUIRED for OmniClaude intelligence gathering.
# The entire architecture is event-driven via Kafka - without it, hooks have no purpose.
# Set KAFKA_BOOTSTRAP_SERVERS in .env (e.g., KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092).
# SessionStart hook will fail fast if Kafka is not configured.

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

    "$PYTHON_CMD" "${HOOKS_LIB}/emit_client_wrapper.py" emit \
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
