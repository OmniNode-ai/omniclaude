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
    echo "    - PLUGIN_PYTHON_BIN=/path/to/python3 (explicit override)" 1>&2
    echo "    - ${PLUGIN_ROOT}/lib/.venv/bin/python3 (deploy the plugin)" 1>&2
    echo "    - OMNICLAUDE_PROJECT_ROOT=/path/to/repo with .venv (dev mode)" 1>&2
    echo "" 1>&2
    echo "  Quick fix: run the deploy skill with --repair-venv to build lib/.venv" 1>&2
    echo "  in the active cache version without a full redeploy:" 1>&2
    echo "    \${CLAUDE_PLUGIN_ROOT}/skills/deploy-local-plugin/deploy.sh --repair-venv" 1>&2
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
# Accepts: true, 1, yes, on (case-insensitive) -> "true"
# Everything else -> "false"

_normalize_bool() {
    # Use tr for lowercase conversion (compatible with bash 3.2 on macOS)
    # Accepted truthy values mirror Python's _TRUTHY frozenset in
    # local_delegation_handler.py: true, 1, yes, on
    local val
    val=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$val" in
        true|1|yes|on) echo "true" ;;
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

# Load global ~/.claude/.env first (lowest priority — project .env overrides below).
# This ensures LLM routing, Kafka, and other shared vars are always available even
# when the hook runs from a non-project CWD (e.g. home dir on dock launch).
_CLAUDE_GLOBAL_ENV="${HOME}/.claude/.env"
if [[ -f "${_CLAUDE_GLOBAL_ENV}" ]]; then
    set -a
    # shellcheck disable=SC1090
    if ! source "${_CLAUDE_GLOBAL_ENV}" 2>/dev/null; then
        if [[ -n "${LOG_FILE:-}" ]]; then
            log "WARN: Failed to source ${_CLAUDE_GLOBAL_ENV} - check file syntax"
        fi
    fi
    set +a
fi
unset _CLAUDE_GLOBAL_ENV

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
# Slack Webhook Alerting
# =============================================================================
# Send a Slack notification for hook/daemon failures.
# Self-protecting: curl timeouts guarantee max 2s delay even on DNS hangs.
# Rate-limited per category (5-min window) to prevent alert spam.
# Always call from a backgrounded subshell: ( slack_notify "cat" "msg" ) &
#
# Requires:
#   - SLACK_WEBHOOK_URL: Webhook URL (no-op if unset)
#
# Usage: ( slack_notify "daemon_startup" "Emit daemon failed to start..." ) &

# Cache hostname once at source time
_SLACK_HOST="${HOSTNAME:-$(hostname -s 2>/dev/null || echo unknown)}"

slack_notify() {
    local category="$1"
    local message="$2"
    local webhook_url="${SLACK_WEBHOOK_URL:-}"

    # No-op if webhook not configured
    [[ -z "$webhook_url" ]] && return 0

    # Rate limiting: 5-minute window per category
    local rate_dir="/tmp/omniclaude-slack-rate"
    mkdir -p "$rate_dir" 2>/dev/null || true
    # Sanitize category for safe filename (alphanumeric + dash + underscore only)
    local safe_cat
    safe_cat=$(printf '%s' "$category" | tr -cd 'a-zA-Z0-9_-')
    [[ -z "$safe_cat" ]] && safe_cat="unknown"
    local rate_file="${rate_dir}/${safe_cat}.last"

    if [[ -f "$rate_file" ]]; then
        local last_sent
        last_sent=$(cat "$rate_file" 2>/dev/null) || last_sent=0
        [[ "$last_sent" =~ ^[0-9]+$ ]] || last_sent=0
        local now
        now=$(date -u +%s)
        if (( now - last_sent < 300 )); then
            return 0  # Rate limited, skip
        fi
    fi

    # JSON-escape the message: backslashes first, then quotes, then control chars
    local escaped
    escaped=$(printf '%s' "$message" \
        | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' \
        | tr '\n' ' ' | tr '\r' ' ' | tr '\t' ' ')

    # Send with strict timeouts (connect 1s, total 2s).
    # Use --url flag instead of positional argument so the webhook URL does not
    # appear in process list output (ps aux) on multi-user systems.
    if curl -s -S --connect-timeout 1 --max-time 2 \
        -H 'Content-Type: application/json' \
        -d "{\"text\": \"${escaped}\"}" \
        --url "$webhook_url" >/dev/null 2>&1; then
        # Record send time for rate limiting
        date -u +%s > "$rate_file" 2>/dev/null || true
    fi

    return 0
}

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
    local health_dir="${HOOKS_DIR}/logs/emit-health"
    # Status file is keyed per event_type so failure counters are isolated.
    # A sanitized form of event_type is used to produce a safe filename.
    local _safe_event_type
    _safe_event_type=$(printf '%s' "$event_type" | tr -cd 'a-zA-Z0-9_-')
    [[ -z "$_safe_event_type" ]] && _safe_event_type="unknown"
    local status_file="${health_dir}/status-${_safe_event_type}"

    mkdir -p "$health_dir" 2>/dev/null || true

    if "$PYTHON_CMD" "${HOOKS_LIB}/emit_client_wrapper.py" emit \
        --event-type "$event_type" --payload "$payload" --timeout "$timeout_ms" \
        >> "$LOG_FILE" 2>&1; then
        # Success: reset failure count, record success timestamp
        local _now
        _now=$(date -u +%s)
        local _tmp="${status_file}.tmp.$$"
        echo "0 0 $_now $event_type" > "$_tmp" && mv -f "$_tmp" "$status_file" 2>/dev/null || rm -f "$_tmp"
        return 0
    else
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Emit daemon failed for ${event_type}" >> "$LOG_FILE"
        # Increment failure count, preserve last_success_ts
        # Single read splits all fields from the status file in one shot (no TOCTOU)
        # Format: <fail_count> <fail_timestamp> <success_timestamp> <event_type>
        local _prev_failures=0 _prev_success_ts=0
        if [[ -f "$status_file" ]]; then
            local _prev_fail_ts=0 _prev_evt=""
            read -r _prev_failures _prev_fail_ts _prev_success_ts _prev_evt < "$status_file" 2>/dev/null \
                || { _prev_failures=0; _prev_success_ts=0; }
            [[ "$_prev_failures" =~ ^[0-9]+$ ]] || _prev_failures=0
            [[ "$_prev_success_ts" =~ ^[0-9]+$ ]] || _prev_success_ts=0
        fi
        local _now
        _now=$(date -u +%s)
        local _tmp="${status_file}.tmp.$$"
        echo "$((_prev_failures + 1)) $_now $_prev_success_ts $event_type" > "$_tmp" \
            && mv -f "$_tmp" "$status_file" 2>/dev/null || rm -f "$_tmp"
        # Milestone-based Slack alerts for sustained failures (avoid spam)
        local n=$((_prev_failures + 1))
        if (( n == 10 || n == 25 || n == 50 || n == 100 )); then
            local _last_ok
            if [[ -z "$_prev_success_ts" || "$_prev_success_ts" -eq 0 ]]; then
                _last_ok="never"
            else
                _last_ok=$(date -u -r "${_prev_success_ts}" +"%Y-%m-%d %H:%M:%S UTC" 2>/dev/null || echo "never")
            fi
            ( slack_notify "emit_sustained" "[omniclaude][${_SLACK_HOST}] ${n} consecutive emit failures for '${event_type}'. Last success: ${_last_ok}. Daemon may be unhealthy." ) &
        fi
        return 1
    fi
}

# =============================================================================
# Tab Activity Helper (Statusline Integration)
# =============================================================================
# Updates the tab activity for the statusline tab bar.
# Writes a lightweight file read by statusline.sh on each render.
# Activity persists until the next prompt clears or replaces it.
#
# The activity file stores an ANSI 256-color code (integer). The statusline
# renders a colored dot (●) using that code. Each skill gets a deterministic
# color via skill_dot_color(). Skills can override by setting `dot_color: NNN`
# in their SKILL.md frontmatter.
#
# Usage: update_tab_activity "ticket-work"    # Set activity (auto-color)
#        update_tab_activity ""               # Clear activity

# Curated palette of 16 visually distinct 256-colors for skill dots
_DOT_PALETTE=(196 208 220 82 46 49 39 27 129 165 205 214 117 156 183 209)

# Map a skill name to a deterministic 256-color code from the palette.
# Checks SKILL.md frontmatter for `dot_color:` override first.
skill_dot_color() {
    local skill="$1"

    # Check for frontmatter override (dot_color: NNN)
    local plugin_root="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-}}"
    if [ -n "$plugin_root" ]; then
        local skill_md="${plugin_root}/skills/${skill}/SKILL.md"
        if [ -f "$skill_md" ]; then
            local override
            override=$(sed -n '/^---$/,/^---$/{ /^dot_color:/{ s/^dot_color:[[:space:]]*//; s/[^0-9]//g; p; q; } }' "$skill_md" 2>/dev/null)
            if [ -n "$override" ]; then
                echo "$override"
                return 0
            fi
        fi
    fi

    # Hash skill name to palette index
    # Multiplier 37 chosen for better distribution: 37 mod 16 = 5 (coprime to 16),
    # whereas 31 mod 16 = 15 which biases lower bits toward last few chars.
    local hash=0 i char_val
    for ((i=0; i<${#skill}; i++)); do
        printf -v char_val '%d' "'${skill:$i:1}"
        hash=$(( (hash * 37 + char_val) % ${#_DOT_PALETTE[@]} ))
    done
    echo "${_DOT_PALETTE[$hash]}"
}

update_tab_activity() {
    local activity="$1"
    local iterm_guid="${ITERM_SESSION_ID:-}"
    [ -z "$iterm_guid" ] && return 0
    local guid="${iterm_guid#*:}"
    local activity_file="/tmp/omniclaude-tabs/${guid}.activity"
    mkdir -p "/tmp/omniclaude-tabs" 2>/dev/null || true
    if [ -n "$activity" ]; then
        local color
        color=$(skill_dot_color "$activity")
        printf '%s' "$color" > "$activity_file" 2>/dev/null || true
    else
        : > "$activity_file" 2>/dev/null || true
    fi
}

# =============================================================================
# Secret Redaction
# =============================================================================
# Redacts known secret patterns from stdin. Used by hook scripts before writing
# to trace logs or Kafka payloads. Covers API keys, tokens, PEM keys, and
# bearer tokens. Reads from stdin, writes redacted output to stdout.
#
# Usage: echo "$sensitive_text" | redact_secrets

redact_secrets() {
    sed -E \
        -e 's/sk-[a-zA-Z0-9]{20,}/sk-***REDACTED***/g' \
        -e 's/AKIA[A-Z0-9]{16}/AKIA***REDACTED***/g' \
        -e 's/ghp_[a-zA-Z0-9]{36}/ghp_***REDACTED***/g' \
        -e 's/gho_[a-zA-Z0-9]{36}/gho_***REDACTED***/g' \
        -e 's/xox[baprs]-[a-zA-Z0-9-]+/xox*-***REDACTED***/g' \
        -e 's/Bearer [a-zA-Z0-9._-]{20,}/Bearer ***REDACTED***/g' \
        -e 's/:\/\/[^:]+:[^@]+@/:\/\/***:***@/g' \
    | perl -0777 -pe 's/-----BEGIN [A-Z ]*(?:PRIVATE|RSA|EC|DSA) KEY-----[\s\S]*?-----END [A-Z ]*(?:PRIVATE|RSA|EC|DSA) KEY-----/[REDACTED PEM KEY]/g'
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
