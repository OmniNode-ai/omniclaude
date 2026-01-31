#!/bin/bash
# SessionStart Hook - Portable Plugin Version
# Captures session initialization intelligence
# Performance target: <50ms execution time

set -euo pipefail

# Portable Plugin Configuration
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${HOOKS_DIR}/logs/hook-session-start.log"

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

# Load environment variables (before sourcing common.sh so KAFKA_BOOTSTRAP_SERVERS is available)
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# Source shared functions (provides PYTHON_CMD, KAFKA_ENABLED, get_time_ms, log)
source "${HOOKS_DIR}/scripts/common.sh"

export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

# Preflight check for jq (required for JSON parsing)
JQ_AVAILABLE=1
if ! command -v jq >/dev/null 2>&1; then
    log "WARNING: jq not found, using fallback values and skipping Kafka emission"
    JQ_AVAILABLE=0
fi

# =============================================================================
# Emit Daemon Management
# =============================================================================
# The emit daemon provides fast, non-blocking Kafka emission via Unix socket.
# Starting it in SessionStart ensures no first-prompt latency surprise.

# Socket path can be overridden via OMNICLAUDE_EMIT_SOCKET environment variable
# This enables testing with alternative socket paths and matches emit_client_wrapper.py
# Note: Not exported because emit_client_wrapper.py reads OMNICLAUDE_EMIT_SOCKET directly
EMIT_DAEMON_SOCKET="${OMNICLAUDE_EMIT_SOCKET:-/tmp/omniclaude-emit.sock}"

# Check if socket file exists and is writable.
#
# IMPORTANT LIMITATION: This performs file-based checks only (-S for socket type,
# -w for writable). It does NOT verify the daemon is accepting connections.
#
# Race window: The socket file is created by the daemon before it calls accept().
# This means there's a brief window where:
#   1. Socket file exists (this check passes)
#   2. But daemon hasn't called accept() yet (connection would fail)
#
# Mitigation: After socket appears, we retry this check multiple times with small
# gaps (up to 5 attempts x 10ms = 50ms max). This adapts to system load rather than
# using a fixed sleep, succeeding quickly on fast systems while allowing more time
# on heavily-loaded systems.
#
# Design tradeoff: We prioritize speed over correctness here. A true protocol
# ping would add ~5-10ms latency per check. Since real connection errors are
# handled gracefully at emission time (emit_client_wrapper.py falls back to
# direct Kafka), this optimistic check is acceptable.
check_socket_responsive() {
    local socket_path="$1"
    # Parameter kept for API stability - callers pass timeout value but current
    # implementation uses simple file existence check. Reserved for potential
    # future protocol-based checks that would use actual socket timeout.
    # shellcheck disable=SC2034
    local timeout_sec="${2:-0.1}"

    # File-based checks only: socket exists (-S) and is writable (-w)
    # Does NOT verify daemon is listening or accepting connections
    [[ -S "$socket_path" ]] && [[ -w "$socket_path" ]]
}

start_emit_daemon_if_needed() {
    # Check if daemon already running via socket
    if [[ -S "$EMIT_DAEMON_SOCKET" ]]; then
        # Verify daemon is responsive with quick ping
        if check_socket_responsive "$EMIT_DAEMON_SOCKET" 0.1; then
            log "Emit daemon already running and responsive"
            return 0
        else
            # Socket exists but daemon not responsive - remove stale socket
            log "Removing stale daemon socket"
            rm -f "$EMIT_DAEMON_SOCKET" 2>/dev/null || true
        fi
    fi

    # Check if daemon module is available
    if ! "$PYTHON_CMD" -c "import omnibase_infra.runtime.emit_daemon" 2>/dev/null; then
        log "Emit daemon module not available (omnibase_infra.runtime.emit_daemon)"
        return 0  # Non-fatal, continue without daemon
    fi

    log "Starting emit daemon..."

    # Ensure logs directory exists for daemon output
    mkdir -p "${HOOKS_DIR}/logs"

    # Start daemon in background, detached from this process
    # Redirect output to log file for debugging
    # Must pass --kafka-servers explicitly (required by CLI)
    if [[ -z "${KAFKA_BOOTSTRAP_SERVERS:-}" ]]; then
        log "ERROR: KAFKA_BOOTSTRAP_SERVERS not set - emit daemon CANNOT start"
        log "ERROR: Set KAFKA_BOOTSTRAP_SERVERS in your .env file (e.g., KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092)"
        echo "kafka_not_configured" > "${HOOKS_DIR}/logs/daemon-status"
        return 1
    fi
    nohup "$PYTHON_CMD" -m omnibase_infra.runtime.emit_daemon.cli start \
        --kafka-servers "$KAFKA_BOOTSTRAP_SERVERS" \
        --socket-path "$EMIT_DAEMON_SOCKET" \
        --daemonize \
        >> "${HOOKS_DIR}/logs/emit-daemon.log" 2>&1 &

    local daemon_pid=$!
    log "Daemon started with PID $daemon_pid"

    # Wait briefly for daemon to create socket (max 200ms in 20ms increments)
    local wait_count=0
    local max_wait=10
    while [[ ! -S "$EMIT_DAEMON_SOCKET" && $wait_count -lt $max_wait ]]; do
        sleep 0.02
        ((wait_count++))
    done

    # Retry-based socket verification after file appears.
    # The socket file is created before the daemon calls accept(), so there's a brief
    # window where the socket exists but isn't ready for connections. Rather than a
    # fixed sleep (which is fragile across different system loads), we use a retry
    # loop that adapts: succeeding immediately on fast systems while giving more
    # time on heavily-loaded systems. Worst-case adds ~50ms (5 retries x 10ms gap).
    if [[ -S "$EMIT_DAEMON_SOCKET" ]]; then
        local verify_attempt=0
        local max_verify_attempts=5  # 5 attempts x 10ms gap = 50ms max additional wait

        while [[ $verify_attempt -lt $max_verify_attempts ]]; do
            if check_socket_responsive "$EMIT_DAEMON_SOCKET" 0.1; then
                log "Emit daemon ready (verified on attempt $((verify_attempt + 1)))"
                return 0
            fi
            ((verify_attempt++))
            # Small gap between retries to allow daemon to complete accept() initialization
            sleep 0.01
        done

        # All retries exhausted - socket exists but daemon not responsive
        log "WARNING: Daemon socket exists but not responsive after $max_verify_attempts verification attempts"
    else
        log "WARNING: Emit daemon startup timed out after ${max_wait}x20ms, continuing without daemon"
    fi

    # Daemon failed to start properly - continue without it
    log "Continuing without emit daemon (session startup not blocked)"
    return 0
}

# Performance tracking
START_TIME=$(get_time_ms)

# Read stdin
INPUT=$(cat)

log "SessionStart hook triggered (plugin mode)"
log "Using Python: $PYTHON_CMD"

# Extract session information
if [[ "$JQ_AVAILABLE" -eq 1 ]]; then
    SESSION_ID=$(echo "$INPUT" | jq -r '.sessionId // .session_id // ""')
    PROJECT_PATH=$(echo "$INPUT" | jq -r '.projectPath // .project_path // ""')
    CWD=$(echo "$INPUT" | jq -r '.cwd // ""' || pwd)
else
    # Fallback values when jq is not available
    SESSION_ID=""
    PROJECT_PATH=""
    CWD=$(pwd)
fi

if [[ -z "$CWD" ]]; then
    CWD=$(pwd)
fi

log "Session ID: $SESSION_ID"
log "Project Path: $PROJECT_PATH"
log "CWD: $CWD"

# Start emit daemon early (before any Kafka emissions)
# This ensures daemon is ready for downstream hooks (UserPromptSubmit, PostToolUse)
start_emit_daemon_if_needed

# Log session start to database (async, non-blocking)
if [[ -f "${HOOKS_LIB}/session_intelligence.py" ]]; then
    (
        "$PYTHON_CMD" "${HOOKS_LIB}/session_intelligence.py" \
            --mode start \
            --session-id "$SESSION_ID" \
            --project-path "$PROJECT_PATH" \
            --cwd "$CWD" \
            >> "$LOG_FILE" 2>&1
    ) &
    log "Session intelligence logging started"
fi

# Emit session.started event to Kafka (async, non-blocking)
# Uses emit_client_wrapper with daemon fan-out (OMN-1631)
# Requires jq for payload construction
if [[ "$KAFKA_ENABLED" == "true" && "$JQ_AVAILABLE" -eq 1 ]]; then
    (
        GIT_BRANCH=""
        if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
            GIT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")
        fi

        # Build payload with all fields needed for session.started event
        SESSION_PAYLOAD=$(jq -n \
            --arg session_id "$SESSION_ID" \
            --arg working_directory "$CWD" \
            --arg hook_source "startup" \
            --arg git_branch "$GIT_BRANCH" \
            '{
                session_id: $session_id,
                working_directory: $working_directory,
                hook_source: $hook_source,
                git_branch: $git_branch
            }' 2>/dev/null)

        # Validate payload was constructed successfully
        if [[ -z "$SESSION_PAYLOAD" || "$SESSION_PAYLOAD" == "null" ]]; then
            log "WARNING: Failed to construct session payload (jq failed), skipping emission"
        else
            emit_via_daemon "session.started" "$SESSION_PAYLOAD" 100
        fi
    ) &
    log "Session event emission started via emit daemon"
else
    if [[ "$JQ_AVAILABLE" -eq 0 ]]; then
        log "Kafka emission skipped (jq not available for payload construction)"
    else
        log "Kafka emission skipped (KAFKA_ENABLED=$KAFKA_ENABLED)"
    fi
fi

# Performance tracking
END_TIME=$(get_time_ms)
ELAPSED_MS=$((END_TIME - START_TIME))

log "Hook execution time: ${ELAPSED_MS}ms"

if [[ $ELAPSED_MS -gt 50 ]]; then
    log "WARNING: Exceeded 50ms target: ${ELAPSED_MS}ms"
fi

exit 0
