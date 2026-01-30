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

# =============================================================================
# Emit Daemon Management
# =============================================================================
# The emit daemon provides fast, non-blocking Kafka emission via Unix socket.
# Starting it in SessionStart ensures no first-prompt latency surprise.

# Socket path can be overridden via OMNICLAUDE_EMIT_SOCKET environment variable
# This enables testing with alternative socket paths and matches emit_client_wrapper.py
EMIT_DAEMON_SOCKET="${OMNICLAUDE_EMIT_SOCKET:-/tmp/omniclaude-emit.sock}"
export EMIT_DAEMON_SOCKET

EMIT_DAEMON_AVAILABLE="false"
export EMIT_DAEMON_AVAILABLE

# Check if socket is responsive (portable - works on macOS and Linux)
# Uses nc with timeout flag on macOS or timeout command on Linux
check_socket_responsive() {
    local socket_path="$1"
    local timeout_sec="${2:-0.1}"

    if command -v timeout >/dev/null 2>&1; then
        # Linux: use timeout command
        timeout "$timeout_sec" bash -c "echo 'ping' | nc -U '$socket_path'" >/dev/null 2>&1
    elif command -v gtimeout >/dev/null 2>&1; then
        # macOS with coreutils: use gtimeout
        gtimeout "$timeout_sec" bash -c "echo 'ping' | nc -U '$socket_path'" >/dev/null 2>&1
    else
        # macOS fallback: nc with -w flag (timeout in seconds, min 1)
        # Note: macOS nc -w only accepts integer seconds, so we use 1s minimum
        echo 'ping' | nc -U -w 1 "$socket_path" >/dev/null 2>&1
    fi
}

start_emit_daemon_if_needed() {
    # Check if daemon already running via socket
    if [[ -S "$EMIT_DAEMON_SOCKET" ]]; then
        # Verify daemon is responsive with quick ping
        if check_socket_responsive "$EMIT_DAEMON_SOCKET" 0.1; then
            log "Emit daemon already running and responsive"
            EMIT_DAEMON_AVAILABLE="true"
            export EMIT_DAEMON_AVAILABLE
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

    # Start daemon in background, detached from this process
    # Redirect output to log file for debugging
    nohup "$PYTHON_CMD" -m omnibase_infra.runtime.emit_daemon \
        --socket "$EMIT_DAEMON_SOCKET" \
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

    # Verify daemon is ready
    if [[ -S "$EMIT_DAEMON_SOCKET" ]]; then
        # Quick connectivity check
        if check_socket_responsive "$EMIT_DAEMON_SOCKET" 0.1; then
            log "Emit daemon ready"
            EMIT_DAEMON_AVAILABLE="true"
            export EMIT_DAEMON_AVAILABLE
            return 0
        else
            log "WARNING: Daemon socket exists but not responsive"
        fi
    else
        log "WARNING: Daemon socket not created within timeout"
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
SESSION_ID=$(echo "$INPUT" | jq -r '.sessionId // .session_id // ""')
PROJECT_PATH=$(echo "$INPUT" | jq -r '.projectPath // .project_path // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // ""' || pwd)

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
if [[ "$KAFKA_ENABLED" == "true" ]]; then
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
    log "Kafka emission skipped (KAFKA_ENABLED=$KAFKA_ENABLED)"
fi

# Performance tracking
END_TIME=$(get_time_ms)
ELAPSED_MS=$((END_TIME - START_TIME))

log "Hook execution time: ${ELAPSED_MS}ms"

if [[ $ELAPSED_MS -gt 50 ]]; then
    log "WARNING: Exceeded 50ms target: ${ELAPSED_MS}ms"
fi

exit 0
