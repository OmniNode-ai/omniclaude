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
# shellcheck source=common.sh
source "${HOOKS_DIR}/scripts/common.sh"

# Daemon status file path (used by write_daemon_status for observability)
readonly DAEMON_STATUS_FILE="${HOOKS_DIR}/logs/daemon-status"

# Write daemon status atomically to prevent race conditions
write_daemon_status() {
    local status="$1"
    local tmp_file="${DAEMON_STATUS_FILE}.tmp.$$"

    # Ensure logs directory exists
    mkdir -p "${HOOKS_DIR}/logs" 2>/dev/null || true

    # Atomic write: write to temp file then rename
    if echo "$status" > "$tmp_file" 2>/dev/null; then
        mv "$tmp_file" "$DAEMON_STATUS_FILE" 2>/dev/null || rm -f "$tmp_file"
    fi
}

export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

# Boolean normalization: _normalize_bool is provided by common.sh (sourced above)

# SessionStart injection config (OMN-1675)
SESSION_INJECTION_ENABLED="${OMNICLAUDE_SESSION_INJECTION_ENABLED:-true}"
SESSION_INJECTION_ENABLED=$(_normalize_bool "$SESSION_INJECTION_ENABLED")
SESSION_INJECTION_TIMEOUT_MS="${OMNICLAUDE_SESSION_INJECTION_TIMEOUT_MS:-500}"
SESSION_INJECTION_MAX_PATTERNS="${OMNICLAUDE_SESSION_INJECTION_MAX_PATTERNS:-10}"
SESSION_INJECTION_MIN_CONFIDENCE="${OMNICLAUDE_SESSION_INJECTION_MIN_CONFIDENCE:-0.7}"
SESSION_INJECTION_INCLUDE_FOOTER="${OMNICLAUDE_SESSION_INJECTION_INCLUDE_FOOTER:-false}"
SESSION_INJECTION_INCLUDE_FOOTER=$(_normalize_bool "$SESSION_INJECTION_INCLUDE_FOOTER")

# Define timeout function (portable, works on macOS)
# Uses perl alarm() because GNU coreutils 'timeout' command is not available
# on macOS by default. perl is pre-installed on macOS and provides SIGALRM.
# NOTE: perl alarm() only accepts integers, so we use ceiling (round UP).
run_with_timeout() {
    local timeout_sec="$1"
    shift
    # perl alarm() only accepts integers; use ceiling (round UP) for fractional seconds.
    # IMPORTANT: printf "%.0f" uses banker's rounding which may round 0.5 to 0 (no timeout!)
    # Ceiling ensures: 0.5s -> 1s, 0.1s -> 1s, 1.5s -> 2s (always safe, never zero)
    local int_timeout
    int_timeout=$(awk -v t="$timeout_sec" 'BEGIN { printf "%d", int(t) + (t > int(t) ? 1 : 0) }')
    [[ "$int_timeout" -lt 1 ]] && int_timeout=1
    perl -e 'alarm shift; exec @ARGV' "$int_timeout" "$@"
}

# Preflight check for jq (required for JSON parsing)
JQ_AVAILABLE=1
if ! command -v jq >/dev/null 2>&1; then
    log "WARNING: jq not found, using fallback values and skipping Kafka emission"
    JQ_AVAILABLE=0
fi

# Preflight check for bc (used for timeout calculation)
BC_AVAILABLE=1
if ! command -v bc >/dev/null 2>&1; then
    log "WARNING: bc not found, using shell arithmetic fallback for timeout calculation"
    BC_AVAILABLE=0
fi

# =============================================================================
# Emit Daemon Management
# =============================================================================
# The emit daemon provides fast, non-blocking Kafka emission via Unix socket.
# Starting it in SessionStart ensures no first-prompt latency surprise.

# Socket path can be overridden via OMNICLAUDE_EMIT_SOCKET environment variable
# This enables testing with alternative socket paths and matches emit_client_wrapper.py
# Note: Not exported because emit_client_wrapper.py reads OMNICLAUDE_EMIT_SOCKET directly
# Use $TMPDIR for consistency with Python's tempfile.gettempdir() (both check TMPDIR first)
_TMPDIR="${TMPDIR:-/tmp}"
_TMPDIR="${_TMPDIR%/}"  # Remove trailing slash (macOS TMPDIR often ends with /)
EMIT_DAEMON_SOCKET="${OMNICLAUDE_EMIT_SOCKET:-${_TMPDIR}/omniclaude-emit.sock}"

# Check if daemon is responsive via real protocol ping.
#
# Uses emit_client_wrapper.py's ping command with explicit socket path
# passed via OMNICLAUDE_EMIT_SOCKET env var. This ensures we ping the
# ACTUAL daemon at the expected socket path, not whatever DEFAULT_SOCKET_PATH
# resolves to (which caused the silent mismatch bug on macOS).
check_socket_responsive() {
    local socket_path="$1"
    local timeout_sec="${2:-0.5}"
    # Real protocol ping — passes socket path explicitly via env var
    # so we ping the ACTUAL daemon, not whatever DEFAULT_SOCKET_PATH resolves to.
    # Each invocation is a fresh process, so OMNICLAUDE_EMIT_SOCKET is read fresh.
    OMNICLAUDE_EMIT_SOCKET="$socket_path" \
    OMNICLAUDE_EMIT_TIMEOUT="$timeout_sec" \
        "$PYTHON_CMD" "${HOOKS_LIB}/emit_client_wrapper.py" ping >/dev/null 2>&1
}

start_emit_daemon_if_needed() {
    # Check if publisher already running via socket
    if [[ -S "$EMIT_DAEMON_SOCKET" ]]; then
        # Verify publisher is responsive with quick ping
        if check_socket_responsive "$EMIT_DAEMON_SOCKET" 0.1; then
            log "Publisher already running and responsive"
            return 0
        else
            # Socket exists but publisher not responsive - remove stale socket
            log "Removing stale publisher socket"
            rm -f "$EMIT_DAEMON_SOCKET" 2>/dev/null || true
        fi
    fi

    # Check if publisher module is available (omniclaude.publisher, OMN-1944)
    if ! "$PYTHON_CMD" -c "import omniclaude.publisher" 2>/dev/null; then
        # Fallback: try legacy omnibase_infra emit daemon
        if "$PYTHON_CMD" -c "import omnibase_infra.runtime.emit_daemon" 2>/dev/null; then
            log "Using legacy emit daemon (omnibase_infra)"
            _start_legacy_emit_daemon
            return $?
        fi
        log "Publisher module not available (omniclaude.publisher)"
        return 0  # Non-fatal, continue without publisher
    fi

    log "Starting publisher (omniclaude.publisher)..."

    # Ensure logs directory exists for publisher output
    mkdir -p "${HOOKS_DIR}/logs"

    if [[ -z "${KAFKA_BOOTSTRAP_SERVERS:-}" ]]; then
        log "WARNING: KAFKA_BOOTSTRAP_SERVERS not set - Kafka features disabled"
        log "INFO: To enable intelligence gathering, set KAFKA_BOOTSTRAP_SERVERS in your .env file"
        log "INFO: Example: KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092"
        write_daemon_status "kafka_not_configured"
        return 0  # Non-fatal - continue without Kafka, hook still provides ticket context
    fi

    # Start publisher in background, detached from this process (OMN-1944)
    nohup "$PYTHON_CMD" -m omniclaude.publisher start \
        --kafka-servers "$KAFKA_BOOTSTRAP_SERVERS" \
        --socket-path "$EMIT_DAEMON_SOCKET" \
        >> "${HOOKS_DIR}/logs/emit-daemon.log" 2>&1 &

    local daemon_pid=$!
    log "Publisher started with PID $daemon_pid"

    # Wait briefly for publisher to create socket (max 200ms in 20ms increments)
    local wait_count=0
    local max_wait=10
    while [[ ! -S "$EMIT_DAEMON_SOCKET" && $wait_count -lt $max_wait ]]; do
        sleep 0.02
        ((wait_count++))
    done

    # Retry-based socket verification after file appears.
    if [[ -S "$EMIT_DAEMON_SOCKET" ]]; then
        local verify_attempt=0
        # 5 attempts x 0.2s timeout + 10ms gap = ~1.05s worst-case on sync path
        local max_verify_attempts=5

        while [[ $verify_attempt -lt $max_verify_attempts ]]; do
            if check_socket_responsive "$EMIT_DAEMON_SOCKET" 0.2; then
                log "Publisher ready (verified on attempt $((verify_attempt + 1)))"
                write_daemon_status "running"
                mkdir -p "${HOOKS_DIR}/logs/emit-health" 2>/dev/null || true
                rm -f "${HOOKS_DIR}/logs/emit-health/warning" 2>/dev/null || true
                return 0
            fi
            ((verify_attempt++))
            sleep 0.01
        done

        log "WARNING: Publisher socket exists but not responsive after $max_verify_attempts verification attempts"
    else
        log "WARNING: Publisher startup timed out after ${max_wait}x20ms, continuing without publisher"
    fi

    # Publisher failed to start properly - write warning file and continue
    mkdir -p "${HOOKS_DIR}/logs/emit-health" 2>/dev/null || true
    local _tmp="${HOOKS_DIR}/logs/emit-health/warning.tmp.$$"
    cat > "$_tmp" <<WARN
EVENT EMISSION UNHEALTHY: The emit daemon is not responding to health checks. Intelligence gathering and observability events are NOT being captured. Socket: ${EMIT_DAEMON_SOCKET}. Check: ${HOOKS_DIR}/logs/emit-daemon.log
WARN
    mv -f "$_tmp" "${HOOKS_DIR}/logs/emit-health/warning" 2>/dev/null || rm -f "$_tmp"
    log "Continuing without publisher (session startup not blocked)"
    return 0
}

# Legacy fallback: start omnibase_infra emit daemon (will be removed by OMN-1945)
_start_legacy_emit_daemon() {
    if [[ -z "${KAFKA_BOOTSTRAP_SERVERS:-}" ]]; then
        write_daemon_status "kafka_not_configured"
        return 0
    fi
    nohup "$PYTHON_CMD" -m omnibase_infra.runtime.emit_daemon.cli start \
        --kafka-servers "$KAFKA_BOOTSTRAP_SERVERS" \
        --socket-path "$EMIT_DAEMON_SOCKET" \
        --daemonize \
        >> "${HOOKS_DIR}/logs/emit-daemon.log" 2>&1 &
    local daemon_pid=$!
    log "Legacy daemon started with PID $daemon_pid"
    local wait_count=0
    local max_wait=10
    while [[ ! -S "$EMIT_DAEMON_SOCKET" && $wait_count -lt $max_wait ]]; do
        sleep 0.02
        ((wait_count++))
    done
    if [[ -S "$EMIT_DAEMON_SOCKET" ]]; then
        write_daemon_status "running"
    fi
    return 0
}

# Performance tracking
START_TIME=$(get_time_ms)

# Read stdin
INPUT=$(cat)
if [[ "$JQ_AVAILABLE" -eq 1 ]]; then
    if ! echo "$INPUT" | jq -e . >/dev/null 2>>"$LOG_FILE"; then
        log "ERROR: Malformed JSON on stdin, using empty object"
        INPUT='{}'
    fi
fi

log "SessionStart hook triggered (plugin mode)"
log "Using Python: $PYTHON_CMD"

# Extract session information
if [[ "$JQ_AVAILABLE" -eq 1 ]]; then
    SESSION_ID=$(echo "$INPUT" | jq -r '.sessionId // .session_id // ""')
    PROJECT_PATH=$(echo "$INPUT" | jq -r '.projectPath // .project_path // ""')
    CWD=$(echo "$INPUT" | jq -r '.cwd // ""' || pwd)
    # Generate correlation ID for this session (used for pattern injection tracking)
    CORRELATION_ID=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "session-${SESSION_ID:-unknown}-$(date +%s)")
else
    # Fallback values when jq is not available
    SESSION_ID=""
    PROJECT_PATH=""
    CWD=$(pwd)
    CORRELATION_ID=""
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

# -----------------------------
# Session State Initialization (OMN-2119)
# -----------------------------
# Sync path: mkdir only (O(1), <5ms).
# Async path: adapter creates run + updates index (backgrounded).
# Idempotency: stamp file (.done) prevents re-init on reconnect.
# Concurrency: PID file (.pid) prevents duplicate concurrent spawns.

_init_session_state() {
    # Sync: ensure state directory exists (O(1))
    mkdir -p "${HOME}/.claude/state/runs" 2>/dev/null || true

    # Sanitize SESSION_ID for safe use in filenames
    local safe_id
    safe_id=$(echo "$SESSION_ID" | tr -cd 'a-zA-Z0-9-')

    # Empty SESSION_ID safety: skip idempotency AND PID guards entirely.
    # When safe_id is empty, both the stamp file (.done) and PID guard file (.pid)
    # would collapse to a shared path for ALL empty-ID sessions, causing
    # cross-session interference. Idempotency for empty sessions isn't critical
    # since the data will be overwritten anyway.
    if [[ -z "$safe_id" ]]; then
        log "WARNING: Empty SESSION_ID, skipping idempotency and PID guards"
    else
        # Idempotency guard: prevent duplicate init on reconnect.
        # SessionStart may fire multiple times for the same session (reconnects).
        # The stamp file persists after the adapter completes, so subsequent calls
        # for the same session return immediately (O(1) file existence check).
        # Cleanup: /tmp is cleared on reboot (both Linux and macOS), so stamp
        # files do not accumulate across reboots. No active cleanup needed.
        local stamp_file="/tmp/omniclaude-state-init-${safe_id}.done"
        if [[ -f "$stamp_file" ]]; then
            log "Session state already initialized (stamp: $stamp_file), skipping"
            return 0
        fi

        # PID guard: prevent duplicate concurrent spawns for same session.
        # This protects against rapid-fire SessionStart events before the first
        # background adapter call has finished and written the stamp file.
        local guard_file="/tmp/omniclaude-state-init-${safe_id}.pid"
        local guard_pid
        guard_pid=$(cat "$guard_file" 2>/dev/null)
        if [[ "$guard_pid" =~ ^[0-9]+$ ]] && kill -0 "$guard_pid" 2>/dev/null; then
            log "Session state init already running (PID $guard_pid), skipping"
            return 0
        fi
    fi

    # Async: background the adapter call
    if [[ -f "${HOOKS_LIB}/node_session_state_adapter.py" ]]; then
        (
            # Write PID guard only when safe_id is non-empty (guard_file is defined)
            if [[ -n "$safe_id" ]]; then
                echo "$BASHPID" > "/tmp/omniclaude-state-init-${safe_id}.pid" 2>/dev/null || true
            fi
            # Capture adapter stdout separately from stderr so we can parse the
            # JSON result. stderr goes to $LOG_FILE for diagnostics; stdout is
            # captured into adapter_stdout for run_id extraction.
            adapter_stdout=$(echo "$INPUT" | "$PYTHON_CMD" "${HOOKS_LIB}/node_session_state_adapter.py" init 2>>"$LOG_FILE")
            local adapter_exit=$?
            # Log the adapter output for diagnostics
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] [session-state] adapter stdout: ${adapter_stdout:-<empty>}" >> "$LOG_FILE"
            # Extract run_id from adapter JSON output.
            # The adapter outputs {"run_id": "...", "state": "..."} on success
            # and {} on logical failure (missing session_id, lock timeout, etc.).
            # Since the adapter always exits 0 (fail-open design), we must check
            # for a non-empty run_id to distinguish success from logical failure.
            local adapter_run_id=""
            if [[ "$JQ_AVAILABLE" -eq 1 ]]; then
                adapter_run_id=$(echo "$adapter_stdout" | jq -r '.run_id // ""' 2>/dev/null) || adapter_run_id=""
            else
                # Fallback: grep for run_id value (handles {"run_id": "uuid-here", ...})
                adapter_run_id=$(echo "$adapter_stdout" | grep -o '"run_id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"run_id"[[:space:]]*:[[:space:]]*"//;s/"$//' 2>/dev/null) || adapter_run_id=""
            fi
            # Clean up PID guard and write stamp only when safe_id is non-empty
            if [[ -n "$safe_id" ]]; then
                rm -f "/tmp/omniclaude-state-init-${safe_id}.pid" 2>/dev/null || true
                # Write stamp file ONLY when adapter returned a valid run_id.
                # The adapter always exits 0 (fail-open), so exit code alone
                # cannot distinguish success from logical failure. A non-empty
                # run_id confirms the init actually completed (run doc written,
                # session index updated). Without this check, a failed init
                # (e.g., lock timeout, missing session_id) would write the stamp
                # and permanently prevent retry on reconnect.
                if [[ $adapter_exit -eq 0 ]] && [[ -n "$adapter_run_id" ]]; then
                    echo "$$" > "/tmp/omniclaude-state-init-${safe_id}.done" 2>/dev/null || true
                elif [[ $adapter_exit -eq 0 ]] && [[ -z "$adapter_run_id" ]]; then
                    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [session-state] WARNING: adapter exited 0 but run_id is empty — logical init failure, stamp NOT written (retry allowed on reconnect)" >> "$LOG_FILE"
                fi
            fi
        ) &
        log "Session state init started in background (PID: $!)"
    fi
}

_init_session_state

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

# -----------------------------
# Learned Pattern Injection (OMN-1675) - ASYNC IMPLEMENTATION
# -----------------------------
# PERFORMANCE GUARANTEE: Pattern injection runs in a background subshell via `( ... ) &`.
# This ensures the main hook returns immediately (<50ms target) regardless of:
#   - Pattern retrieval latency from OmniMemory
#   - Network timeout to intelligence services
#   - Any errors in the injection pipeline
#
# The first UserPromptSubmit will handle pattern injection (session not yet marked).
# This async process marks the session after completion to prevent duplicate injection
# on subsequent prompts.
#
# CRITICAL: Session is marked as injected for ALL outcomes:
#   - Success with patterns: marked with injection_id
#   - Control cohort (A/B testing): marked with "cohort-<name>"
#   - Empty patterns (no relevant patterns): marked with "no-patterns"
#   - Error/timeout: marked with "error-exit-<code>" (e.g., error-exit-142 for timeout)
#   - Fallback: marked with "async-completed" (rare edge case)
# This prevents UserPromptSubmit from attempting duplicate injection.
#
# Trade-off: SessionStart returns immediately without patterns in additionalContext.
# UserPromptSubmit provides fallback injection for the first prompt.

if [[ "${SESSION_INJECTION_ENABLED:-true}" == "true" ]] && [[ -f "${HOOKS_LIB}/context_injection_wrapper.py" ]] && [[ "$JQ_AVAILABLE" -eq 1 ]]; then
    log "Starting async pattern injection for SessionStart"

    # Run pattern injection in background subshell (non-blocking)
    (
        _async_log() {
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] [session-start-async] $*" >> "$LOG_FILE"
        }

        _async_log "Async pattern injection started for session ${SESSION_ID:-unknown}"

        # Build injection input
        PATTERN_INPUT="$(jq -n \
            --arg session "${SESSION_ID:-}" \
            --arg project "${PROJECT_PATH:-$(pwd)}" \
            --arg correlation "${CORRELATION_ID:-}" \
            --argjson max_patterns "${SESSION_INJECTION_MAX_PATTERNS:-10}" \
            --argjson min_confidence "${SESSION_INJECTION_MIN_CONFIDENCE:-0.7}" \
            --argjson include_footer "${SESSION_INJECTION_INCLUDE_FOOTER:-false}" \
            '{
                session_id: $session,
                project: $project,
                correlation_id: $correlation,
                max_patterns: $max_patterns,
                min_confidence: $min_confidence,
                injection_context: "session_start",
                include_footer: $include_footer,
                emit_event: true
            }' 2>/dev/null)"

        # Call wrapper with timeout (500ms default, convert to seconds)
        # Use bc if available, otherwise fall back to shell arithmetic
        if [[ "$BC_AVAILABLE" -eq 1 ]]; then
            TIMEOUT_SEC=$(echo "scale=1; ${SESSION_INJECTION_TIMEOUT_MS:-500} / 1000" | bc)
        else
            # Shell arithmetic fallback: integer division + one decimal place
            # e.g., 500ms -> 0.5s, 1000ms -> 1.0s, 1500ms -> 1.5s
            _timeout_ms="${SESSION_INJECTION_TIMEOUT_MS:-500}"
            _timeout_sec=$((_timeout_ms / 1000))
            _timeout_decimal=$(((_timeout_ms % 1000) / 100))
            TIMEOUT_SEC="${_timeout_sec}.${_timeout_decimal}"
            # Ensure minimum timeout of 0.1s to prevent effectively disabling timeout
            if [[ "$TIMEOUT_SEC" == "0.0" ]] || [[ "$TIMEOUT_SEC" == "0" ]]; then
                TIMEOUT_SEC="0.1"
            fi
        fi
        INJECTION_EXIT_CODE=0
        PATTERN_RESULT="$(echo "$PATTERN_INPUT" | run_with_timeout "${TIMEOUT_SEC}" $PYTHON_CMD "${HOOKS_LIB}/context_injection_wrapper.py" 2>>"$LOG_FILE")" || {
            INJECTION_EXIT_CODE=$?
            # Log detailed error context for debugging
            # Exit codes: 142 = SIGALRM (timeout), 1 = general error, other = script-specific
            _async_log "WARNING: Pattern injection failed - exit_code=${INJECTION_EXIT_CODE} timeout_sec=${TIMEOUT_SEC} session=${SESSION_ID:-unknown}"
            if [[ $INJECTION_EXIT_CODE -eq 142 ]]; then
                _async_log "DEBUG: Injection timed out after ${TIMEOUT_SEC}s (SIGALRM). Consider increasing SESSION_INJECTION_TIMEOUT_MS (current: ${SESSION_INJECTION_TIMEOUT_MS:-500})"
            else
                _async_log "DEBUG: Injection error (check stderr above in log). Wrapper: ${HOOKS_LIB}/context_injection_wrapper.py"
            fi
            PATTERN_RESULT='{}'
        }

        # Extract results
        INJECTION_ID="$(echo "$PATTERN_RESULT" | jq -r '.injection_id // ""' 2>/dev/null)"
        INJECTION_COHORT="$(echo "$PATTERN_RESULT" | jq -r '.cohort // ""' 2>/dev/null)"
        PATTERN_COUNT="$(echo "$PATTERN_RESULT" | jq -r '.pattern_count // 0' 2>/dev/null)"

        _async_log "Pattern injection complete: count=$PATTERN_COUNT cohort=$INJECTION_COHORT"

        # Mark session as injected (for UserPromptSubmit coordination)
        # CRITICAL: Always mark session when injection was ATTEMPTED, regardless of result.
        # This prevents duplicate injection attempts from UserPromptSubmit on subsequent prompts.
        #
        # Marker ID selection (in priority order):
        #   1. injection_id: Successful injection with patterns
        #   2. cohort name: Control cohort (A/B testing) or treatment without patterns
        #   3. "no-patterns": Empty pattern result (no relevant patterns found)
        #   4. "error-exit-<code>": Injection failed with specific exit code
        #   5. "async-completed": Final fallback (should rarely happen)
        if [[ -f "${HOOKS_LIB}/session_marker.py" ]]; then
            # Determine marker_id based on injection outcome
            if [[ -n "$INJECTION_ID" ]]; then
                marker_id="$INJECTION_ID"
                marker_reason="injection_success"
            elif [[ -n "$INJECTION_COHORT" ]]; then
                marker_id="cohort-${INJECTION_COHORT}"
                marker_reason="cohort_assigned"
            elif [[ $INJECTION_EXIT_CODE -ne 0 ]]; then
                marker_id="error-exit-${INJECTION_EXIT_CODE}"
                marker_reason="injection_error"
            elif [[ "$PATTERN_COUNT" -eq 0 ]]; then
                marker_id="no-patterns"
                marker_reason="empty_result"
            else
                marker_id="async-completed"
                marker_reason="fallback"
            fi

            _async_log "Marking session: marker_id=$marker_id reason=$marker_reason pattern_count=$PATTERN_COUNT"

            if $PYTHON_CMD "${HOOKS_LIB}/session_marker.py" mark \
                --session-id "${SESSION_ID}" \
                --injection-id "$marker_id" 2>>"$LOG_FILE"; then
                _async_log "Session marked as injected (marker_id=$marker_id, reason=$marker_reason)"
            else
                _async_log "WARNING: Failed to mark session as injected (marker_id=$marker_id)"
            fi
        fi
    ) &
    # PERFORMANCE: Background subshell (&) ensures main hook returns immediately.
    # The pattern injection runs asynchronously and will NOT block hook completion.
    # Session is marked after async completion to coordinate with UserPromptSubmit.
    log "Async pattern injection started in background (PID: $!) - hook will return immediately"
elif [[ "${SESSION_INJECTION_ENABLED:-true}" != "true" ]]; then
    log "Pattern injection disabled (SESSION_INJECTION_ENABLED=false)"
elif [[ "$JQ_AVAILABLE" -eq 0 ]]; then
    log "Pattern injection skipped (jq not available)"
else
    log "Pattern injection skipped (context_injection_wrapper.py not found)"
fi

# -----------------------------
# Ticket Context Injection (OMN-1830)
# -----------------------------
# Inject active ticket context for session continuity.
# Runs SYNCHRONOUSLY because it's purely local filesystem (fast).
# This ensures ticket context is available immediately in additionalContext.

TICKET_INJECTION_ENABLED="${OMNICLAUDE_TICKET_INJECTION_ENABLED:-true}"
TICKET_INJECTION_ENABLED=$(_normalize_bool "$TICKET_INJECTION_ENABLED")
TICKET_CONTEXT=""

if [[ "${TICKET_INJECTION_ENABLED}" == "true" ]] && [[ -f "${HOOKS_LIB}/ticket_context_injector.py" ]]; then
    log "Checking for active ticket context"

    # Run ticket context injection synchronously via CLI (fast, local-only)
    # Single Python invocation for better performance within 50ms budget
    TICKET_OUTPUT=$(echo '{}' | "$PYTHON_CMD" "${HOOKS_LIB}/ticket_context_injector.py" 2>>"$LOG_FILE") || TICKET_OUTPUT='{}'

    # Parse CLI output using jq
    if [[ "$JQ_AVAILABLE" -eq 1 ]]; then
        ACTIVE_TICKET=$(echo "$TICKET_OUTPUT" | jq -r '.ticket_id // empty' 2>/dev/null) || ACTIVE_TICKET=""
        TICKET_CONTEXT=$(echo "$TICKET_OUTPUT" | jq -r '.ticket_context // empty' 2>/dev/null) || TICKET_CONTEXT=""
        TICKET_RETRIEVAL_MS=$(echo "$TICKET_OUTPUT" | jq -r '.retrieval_ms // 0' 2>/dev/null) || TICKET_RETRIEVAL_MS=0

        if [[ -n "$ACTIVE_TICKET" ]] && [[ -n "$TICKET_CONTEXT" ]]; then
            log "Active ticket found: $ACTIVE_TICKET (retrieved in ${TICKET_RETRIEVAL_MS}ms)"
            log "Ticket context generated (${#TICKET_CONTEXT} chars)"
        else
            log "No active ticket found"
        fi
    else
        # Fallback: extract ticket_context using basic string parsing
        TICKET_CONTEXT=$(echo "$TICKET_OUTPUT" | "$PYTHON_CMD" -c "import sys,json; d=json.load(sys.stdin); print(d.get('ticket_context',''))" 2>/dev/null) || TICKET_CONTEXT=""
        log "Ticket context check completed (jq unavailable for detailed parsing)"
    fi
elif [[ "${TICKET_INJECTION_ENABLED}" != "true" ]]; then
    log "Ticket context injection disabled (TICKET_INJECTION_ENABLED=false)"
else
    log "Ticket context injection skipped (ticket_context_injector.py not found)"
fi

# -----------------------------
# Architecture Handshake Injection (OMN-1860)
# -----------------------------
# Inject architecture handshake from .claude/architecture-handshake.md
# Runs SYNCHRONOUSLY because it's purely local filesystem (fast).
# Combined with ticket context in additionalContext (handshake first, then ticket).

HANDSHAKE_INJECTION_ENABLED="${OMNICLAUDE_HANDSHAKE_INJECTION_ENABLED:-true}"
HANDSHAKE_INJECTION_ENABLED=$(_normalize_bool "$HANDSHAKE_INJECTION_ENABLED")
HANDSHAKE_CONTEXT=""

if [[ "${HANDSHAKE_INJECTION_ENABLED}" == "true" ]] && [[ -f "${HOOKS_LIB}/architecture_handshake_injector.py" ]]; then
    log "Checking for architecture handshake"

    # Build input JSON with project path (prefer repo root over CWD)
    # PROJECT_PATH is set from hook input, PROJECT_ROOT is detected from .env location
    HANDSHAKE_PROJECT="${PROJECT_PATH:-}"
    if [[ -z "$HANDSHAKE_PROJECT" ]]; then
        HANDSHAKE_PROJECT="${PROJECT_ROOT:-}"
    fi
    if [[ -z "$HANDSHAKE_PROJECT" ]]; then
        HANDSHAKE_PROJECT="$CWD"
    fi
    HANDSHAKE_INPUT=$(jq -n --arg project "$HANDSHAKE_PROJECT" '{"project_path": $project}' 2>/dev/null) || HANDSHAKE_INPUT='{}'

    # Run architecture handshake injection synchronously via CLI (fast, local-only)
    HANDSHAKE_OUTPUT=$(echo "$HANDSHAKE_INPUT" | "$PYTHON_CMD" "${HOOKS_LIB}/architecture_handshake_injector.py" 2>>"$LOG_FILE") || HANDSHAKE_OUTPUT='{}'

    # Parse CLI output using jq
    if [[ "$JQ_AVAILABLE" -eq 1 ]]; then
        HANDSHAKE_PATH=$(echo "$HANDSHAKE_OUTPUT" | jq -r '.handshake_path // empty' 2>/dev/null) || HANDSHAKE_PATH=""
        HANDSHAKE_CONTEXT=$(echo "$HANDSHAKE_OUTPUT" | jq -r '.handshake_context // empty' 2>/dev/null) || HANDSHAKE_CONTEXT=""
        HANDSHAKE_RETRIEVAL_MS=$(echo "$HANDSHAKE_OUTPUT" | jq -r '.retrieval_ms // 0' 2>/dev/null) || HANDSHAKE_RETRIEVAL_MS=0

        if [[ -n "$HANDSHAKE_PATH" ]] && [[ -n "$HANDSHAKE_CONTEXT" ]]; then
            log "Architecture handshake found: $HANDSHAKE_PATH (retrieved in ${HANDSHAKE_RETRIEVAL_MS}ms)"
            log "Handshake context generated (${#HANDSHAKE_CONTEXT} chars)"
        else
            log "No architecture handshake found"
        fi
    else
        # Fallback: extract handshake_context using Python
        HANDSHAKE_CONTEXT=$(echo "$HANDSHAKE_OUTPUT" | "$PYTHON_CMD" -c "import sys,json; d=json.load(sys.stdin); print(d.get('handshake_context',''))" 2>/dev/null) || HANDSHAKE_CONTEXT=""
        log "Handshake check completed (jq unavailable for detailed parsing)"
    fi
elif [[ "${HANDSHAKE_INJECTION_ENABLED}" != "true" ]]; then
    log "Architecture handshake injection disabled (HANDSHAKE_INJECTION_ENABLED=false)"
else
    log "Architecture handshake injection skipped (architecture_handshake_injector.py not found)"
fi

# Performance tracking
END_TIME=$(get_time_ms)
ELAPSED_MS=$((END_TIME - START_TIME))

log "Hook execution time: ${ELAPSED_MS}ms"

if [[ $ELAPSED_MS -gt 50 ]]; then
    log "WARNING: Exceeded 50ms target: ${ELAPSED_MS}ms"
fi

# Build output with additionalContext
# NOTE: Pattern injection is async, so patterns won't be available here.
# UserPromptSubmit will handle pattern injection for the first prompt.
# Architecture handshake and ticket context are sync, so they ARE available immediately.
# Combined format: handshake first, then ticket context (separated by ---)
if [[ "$JQ_AVAILABLE" -eq 1 ]]; then
    # Check for emit health warning
    COMBINED_CONTEXT=""
    if [[ -f "${HOOKS_DIR}/logs/emit-health/warning" ]]; then
        _EMIT_WARN=$(cat "${HOOKS_DIR}/logs/emit-health/warning" 2>/dev/null || true)
        if [[ -n "$_EMIT_WARN" ]]; then
            COMBINED_CONTEXT="$_EMIT_WARN"
        fi
    fi

    # Combine handshake and ticket context if both present
    HAS_HANDSHAKE="false"
    HAS_TICKET="false"

    if [[ -n "$HANDSHAKE_CONTEXT" ]]; then
        if [[ -n "$COMBINED_CONTEXT" ]]; then
            COMBINED_CONTEXT="${COMBINED_CONTEXT}

${HANDSHAKE_CONTEXT}"
        else
            COMBINED_CONTEXT="$HANDSHAKE_CONTEXT"
        fi
        HAS_HANDSHAKE="true"
    fi

    if [[ -n "$TICKET_CONTEXT" ]]; then
        if [[ -n "$COMBINED_CONTEXT" ]]; then
            # Add separator between handshake and ticket context
            COMBINED_CONTEXT="${COMBINED_CONTEXT}

---

${TICKET_CONTEXT}"
        else
            COMBINED_CONTEXT="$TICKET_CONTEXT"
        fi
        HAS_TICKET="true"
    fi

    if [[ -n "$COMBINED_CONTEXT" ]]; then
        # Include combined context in additionalContext (sync injection)
        printf '%s' "$INPUT" | jq \
            --arg ctx "$COMBINED_CONTEXT" \
            --argjson has_handshake "$HAS_HANDSHAKE" \
            --argjson has_ticket "$HAS_TICKET" \
            '.hookSpecificOutput.hookEventName = "SessionStart" |
             .hookSpecificOutput.additionalContext = $ctx |
             .hookSpecificOutput.metadata.injection_mode = "sync" |
             .hookSpecificOutput.metadata.has_handshake_context = $has_handshake |
             .hookSpecificOutput.metadata.has_ticket_context = $has_ticket'
    elif [[ "${SESSION_INJECTION_ENABLED:-true}" == "true" ]]; then
        # Async pattern injection was started - set metadata to indicate this
        printf '%s' "$INPUT" | jq \
            '.hookSpecificOutput.hookEventName = "SessionStart" |
             .hookSpecificOutput.metadata.injection_mode = "async"'
    else
        # Injection disabled, just pass through with hookEventName
        printf '%s' "$INPUT" | jq '.hookSpecificOutput.hookEventName = "SessionStart"'
    fi
else
    # No jq available, echo input as-is
    printf '%s' "$INPUT"
fi

exit 0
