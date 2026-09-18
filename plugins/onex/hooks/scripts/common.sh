#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

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
# Hook Bitmask Gate [OMN-9617]
# =============================================================================
# Sources hook_bits.sh once per session. Each GATE wrapper calls:
#   onex_hook_gate <BIT_NAME> || exit 0
# to silently skip when the bit is cleared in ONEX_HOOKS_MASK.
: "${ONEX_HOOK_BITS_SOURCED:=}"
if [[ -z "$ONEX_HOOK_BITS_SOURCED" ]]; then
  _hook_bits_path="${HOOKS_DIR:-$(dirname "${BASH_SOURCE[0]}")/..}/lib/hook_bits.sh"
  if [[ -f "$_hook_bits_path" ]]; then
    source "$_hook_bits_path"
  fi
  ONEX_HOOK_BITS_SOURCED=1
fi
unset _hook_bits_path

onex_hook_gate() {
  local bit_name="$1"
  local bit
  bit="$(hook_bits_bit_for_name "$bit_name" 2>/dev/null || true)"
  [[ -z "$bit" ]] && return 0
  local mask
  mask="$(hook_bits_parse_mask "${ONEX_HOOKS_MASK:-$HOOK_BITS_DEFAULT_MASK}")"
  hook_bits_is_enabled "$mask" "$bit"
}

# =============================================================================
# Python Environment Detection
# =============================================================================
# Canonical Homebrew Python interpreter for macOS hook launchers (OMN-10113).
# All hook scripts that invoke Python must use: env -u PYTHONPATH "$BREW_PY" ...
# This prevents PYTHONPATH leaks from the parent shell from corrupting imports.
# Scope: macOS Apple Silicon only (ARM Homebrew prefix /opt/homebrew).
# Intel Mac (/usr/local) and Linux are not supported runtime profiles for these hooks.
# Version is intentionally pinned to 3.13 per the one-Python policy (OMN-10079).
#
# NOTE FOR AGENTS WORKING IN GIT WORKTREES (OMN-11422):
# These hook scripts export PYTHONPATH into the Claude Code session environment.
# That value propagates to every subprocess, including agent tool invocations.
# In a worktree the local src/ layout differs from the canonical clone, so the
# inherited PYTHONPATH silently shadows the worktree's packages.
# Rule: all Python invocations inside worktrees MUST be prefixed with env -u PYTHONPATH:
#   env -u PYTHONPATH uv run pytest tests/ -v
#   env -u PYTHONPATH uv run python -m <module>
#   env -u PYTHONPATH python3 <script>
# uv run alone is NOT sufficient — uv preserves inherited env vars.
BREW_PY="/opt/homebrew/bin/python3.13"
export BREW_PY

# Default path to the omniclaude event registry YAML (OMN-10117).
# Consumers: session-start.sh daemon launcher, Task 14 launcher, Task 22 restart handler.
# Override: set ONEX_EMIT_EVENT_REGISTRY before sourcing common.sh.
: "${ONEX_EMIT_EVENT_REGISTRY:=${OMNI_HOME:-}/omniclaude/plugins/onex/lib/event_registry/omniclaude.yaml}"
export ONEX_EMIT_EVENT_REGISTRY

# Shared emit-daemon paths for hook launch/restart/stop surfaces.
# Session-start may override EMIT_DAEMON_SOCKET before sourcing common.sh.
# OMN-18471 AC5: the emit-daemon socket and pid paths are gone with the
# path that used them. Nothing opens ~/.claude/emit.sock any more.

# Strict priority chain with NO fallbacks. If no valid Python is found,
# hooks refuse to run. This prevents silent degradation where hooks run
# against the wrong interpreter with missing dependencies.
#
# Priority:
#   1. PLUGIN_PYTHON_BIN env var (explicit override / escape hatch)
#   2. CLAUDE_PLUGIN_DATA/.venv (OMN-10500: built by ensure-plugin-venv.sh, survives plugin updates)
#   2.5. Repo main venv at PLUGIN_ROOT/../../.venv (OMN-7310: only works from source, not cache)
#   3. ONEX_REGISTRY_ROOT/omniclaude/.venv (plugin cache path can't resolve repo venv)
#   4. OMNICLAUDE_PROJECT_ROOT/.venv (explicit dev mode, no heuristics)
#   5. Hard failure with actionable error message

find_python() {
    # 1. Explicit override (escape hatch for custom environments)
    if [[ -n "${PLUGIN_PYTHON_BIN:-}" && -f "${PLUGIN_PYTHON_BIN}" && -x "${PLUGIN_PYTHON_BIN}" ]]; then
        echo "${PLUGIN_PYTHON_BIN}"
        return
    fi

    # 2. Plugin data venv (CLAUDE_PLUGIN_DATA — survives plugin updates, built by ensure-plugin-venv.sh)
    if [[ -n "${CLAUDE_PLUGIN_DATA:-}" && -x "${CLAUDE_PLUGIN_DATA}/.venv/bin/python3" ]]; then
        echo "${CLAUDE_PLUGIN_DATA}/.venv/bin/python3"
        return
    fi

    # 2.5. Repo main venv (OMN-7310: plugin lives at plugins/onex/, repo root is ../..)
    local repo_root
    repo_root="$(cd "${PLUGIN_ROOT}/../.." 2>/dev/null && pwd)"
    if [[ -n "$repo_root" && -f "${repo_root}/.venv/bin/python3" && -x "${repo_root}/.venv/bin/python3" ]]; then
        echo "${repo_root}/.venv/bin/python3"
        return
    fi

    # 2.5. ONEX_REGISTRY_ROOT-based resolution (plugin cache can't find repo venv)
    if [[ -n "${ONEX_REGISTRY_ROOT:-}" && -f "${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3" && -x "${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3" ]]; then
        echo "${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3"
        return
    fi

    # 3. Explicit dev-mode project venv (no heuristics, no CWD probing)
    if [[ -n "${OMNICLAUDE_PROJECT_ROOT:-}" && -f "${OMNICLAUDE_PROJECT_ROOT}/.venv/bin/python3" && -x "${OMNICLAUDE_PROJECT_ROOT}/.venv/bin/python3" ]]; then
        echo "${OMNICLAUDE_PROJECT_ROOT}/.venv/bin/python3"
        return
    fi

    # 4. Lite mode: accept system Python when mode is lite (or mode.sh absent)
    if command -v python3 &>/dev/null; then
        local mode_sh
        mode_sh="$(dirname "${BASH_SOURCE[0]}")/../../lib/mode.sh"
        if [[ -f "$mode_sh" ]]; then
            # shellcheck disable=SC1090
            source "$mode_sh"
            if [[ "$(omniclaude_mode)" == "lite" ]]; then
                echo "python3"
                return
            fi
        else
            # mode.sh absent (e.g., incomplete deploy, container install):
            # default to lite — accept system Python rather than hard-failing.
            # WARNING: if this is a broken full-mode deploy, hooks will run against
            # system Python which may lack omniclaude imports. Log for visibility.
            echo "WARN: mode.sh not found at ${mode_sh}; defaulting to lite mode (system python3)" >&2
            echo "python3"
            return
        fi
    fi

    # No fallback: return empty to trigger hard failure
    echo ""
}

# =============================================================================
# Venv Verification Helper (OMN-3729)
# =============================================================================
# Reusable guard for any script that copies files near or inside the venv.
# Returns 0 when the venv looks healthy, 1 with a warning on stderr otherwise.
#
# Usage:
#   verify_venv_or_warn "/path/to/.venv"  || return 1
#   verify_venv_or_warn "${PLUGIN_ROOT}/lib/.venv" || echo "skipping venv-dependent step"

verify_venv_or_warn() {
    local venv_dir="$1"
    if [[ ! -f "${venv_dir}/bin/python3" || ! -x "${venv_dir}/bin/python3" ]]; then
        echo "WARN: Venv missing or broken at ${venv_dir}. Run: deploy.sh --repair-venv" 1>&2
        return 1
    fi
    return 0
}

# =============================================================================
# Inline Venv Auto-Repair (OMN-3726, updated OMN-7310)
# =============================================================================
# If find_python() returns empty, attempt to run `uv sync` in the repo root
# to create/repair the repo's main .venv. Rate-limited via marker file.
#
# Returns: path to the repo venv python3 interpreter, or empty string

_try_inline_venv_repair() {
    local repo_root
    repo_root="$(cd "${PLUGIN_ROOT}/../.." 2>/dev/null && pwd)"
    local venv_dir="${repo_root}/.venv"
    local repair_failed_marker="/tmp/omniclaude-venv-repair-failed"
    local repair_log="/tmp/omniclaude-venv-repair.log"

    # Rate-limit: skip if a previous repair failed less than 5 minutes ago
    if [[ -f "$repair_failed_marker" ]]; then
        local marker_ts
        marker_ts=$(stat -f '%m' "$repair_failed_marker" 2>/dev/null \
            || stat -c '%Y' "$repair_failed_marker" 2>/dev/null \
            || echo 0)
        local now
        now=$(date +%s)
        if (( now - marker_ts < 300 )); then
            echo ""
            return 1
        fi
        rm -f "$repair_failed_marker" 2>/dev/null || true
    fi

    # Require uv for repo venv repair
    if ! command -v uv &>/dev/null; then
        touch "$repair_failed_marker" 2>/dev/null || true
        echo ""
        return 1
    fi

    # Require pyproject.toml at repo root
    if [[ ! -f "${repo_root}/pyproject.toml" ]]; then
        touch "$repair_failed_marker" 2>/dev/null || true
        echo ""
        return 1
    fi

    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Auto-repair: running uv sync in ${repo_root}" >> "$repair_log" 2>/dev/null || true
    if (cd "$repo_root" && uv sync >> "$repair_log" 2>&1); then
        local repaired_python="${venv_dir}/bin/python3"
        if [[ -x "$repaired_python" ]]; then
            rm -f "$repair_failed_marker" 2>/dev/null || true
            echo "$repaired_python"
            return 0
        fi
    fi

    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Auto-repair: uv sync failed" >> "$repair_log" 2>/dev/null || true
    touch "$repair_failed_marker" 2>/dev/null || true
    echo ""
    return 1
}

# Resolve Python — hard fail if not found (unless advisory hook)
# NOTE: This exit 1 intentionally violates the "hooks exit 0" invariant (CLAUDE.md).
# Rationale: running hooks against the wrong Python produces non-reproducible bugs
# that are far worse than a visible, actionable error. See OMN-2051.
#
# OMN-3725: Advisory hooks (session-end, stop, pre-compact, post-tool-use-quality)
# exit 0 gracefully when Python is missing. Critical hooks still hard-fail.
# The advisory allowlist is checked via BASH_SOURCE[1] (the sourcing script)
# to prevent env-var-only spoofing of OMNICLAUDE_HOOK_CRITICALITY.
PYTHON_CMD="$(find_python)"
if [[ -z "${PYTHON_CMD}" ]]; then
    # Attempt inline venv repair before hard-failing (OMN-3726)
    PYTHON_CMD="$(_try_inline_venv_repair 2>/dev/null)" || PYTHON_CMD=""
fi
if [[ -z "${PYTHON_CMD}" ]]; then
    # OMN-3725: Advisory hooks exit gracefully when Python is missing
    _hook_base="$(basename "${BASH_SOURCE[1]:-}" 2>/dev/null || echo "")"
    _advisory_ok=false
    case "$_hook_base" in
        session-end.sh|stop.sh|pre-compact.sh|post-tool-use-quality.sh) _advisory_ok=true ;;
        # OMN-16162: SessionStart/SessionEnd bus-mirror hooks are best-effort
        # direct-dispatch hand-offs -- a missing Python interpreter must
        # degrade gracefully, not hard-fail the session.
        session_start_bus_mirror.sh|session_end_bus_mirror.sh) _advisory_ok=true ;;
        # OMN-16162 S1: UserPromptSubmit/PostToolUse bus-mirror hooks are the
        # same best-effort direct-dispatch hand-off pattern, extended to the
        # prompt-submitted/tool-executed topics.
        user_prompt_submit_bus_mirror.sh|post_tool_use_bus_mirror.sh) _advisory_ok=true ;;
    esac

    if [[ "${OMNICLAUDE_HOOK_CRITICALITY:-critical}" == "advisory" && "$_advisory_ok" == "true" ]]; then
        echo "WARN: No Python found. Advisory hook exiting gracefully." 1>&2
        cat > /dev/null 2>/dev/null || true
        exit 0
    fi
    # Critical hook: hard-fail with actionable error
    echo "ERROR: No valid Python found for ONEX hooks." 1>&2
    echo "  Expected one of:" 1>&2
    echo "    - PLUGIN_PYTHON_BIN=/path/to/python3 (explicit override)" 1>&2
    echo "    - Repo .venv at \$(cd PLUGIN_ROOT/../.. && pwd)/.venv (run: uv sync)" 1>&2
    echo "    - ONEX_REGISTRY_ROOT/omniclaude/.venv (set ONEX_REGISTRY_ROOT in shell profile, run: uv sync)" 1>&2
    echo "    - OMNICLAUDE_PROJECT_ROOT=/path/to/repo with .venv (dev mode)" 1>&2
    echo "" 1>&2
    echo "  Auto-repair was attempted but failed. Check /tmp/omniclaude-venv-repair.log" 1>&2
    echo "" 1>&2
    echo "  Quick fix: cd to the omniclaude repo root and run 'uv sync'" 1>&2
    exit 1
fi
export PYTHON_CMD

# =============================================================================
# Venv Sentinel Check (OMN-3727)
# =============================================================================
# After PYTHON_CMD is resolved, check for .omniclaude-sentinel in the venv.
# If missing, write one and trigger background integrity verification.
# The sentinel is a single-line ISO 8601 timestamp written by deploy.sh or
# auto-repair. Its absence indicates the venv was not created through a
# normal deploy path and may need verification.
#
# Timing: Single stat = ~0.1ms. Background verification adds zero to the
# synchronous path.

_bg_verify_venv() {
    local venv_dir="$1"
    local repair_log="/tmp/omniclaude-venv-repair.log"
    local python_bin="${venv_dir}/bin/python3"

    # Quick import check — if omniclaude imports cleanly, venv is healthy
    if "$python_bin" -c "import omniclaude" >/dev/null 2>&1; then
        return 0
    fi

    # Import failed — attempt background pip install to repair
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Sentinel verify: import omniclaude failed, attempting background repair" >> "$repair_log" 2>/dev/null || true

    local plugin_root_dir="${PLUGIN_ROOT:-}"
    if [[ -n "$plugin_root_dir" && -f "${plugin_root_dir}/pyproject.toml" ]]; then
        "$python_bin" -m pip install --quiet --disable-pip-version-check \
            -e "${plugin_root_dir}" >> "$repair_log" 2>&1 || true
    elif [[ -n "$plugin_root_dir" && -f "${plugin_root_dir}/requirements.txt" ]]; then
        "$python_bin" -m pip install --quiet --disable-pip-version-check \
            -r "${plugin_root_dir}/requirements.txt" >> "$repair_log" 2>&1 || true
    fi

    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Sentinel verify: background repair finished" >> "$repair_log" 2>/dev/null || true
}

if [[ "${PYTHON_CMD}" == *"/.venv/bin/python3" ]]; then
    _SENTINEL="${PYTHON_CMD%/bin/python3}/.omniclaude-sentinel"
    if [[ ! -f "${_SENTINEL}" ]]; then
        date -u +"%Y-%m-%dT%H:%M:%SZ" > "${_SENTINEL}" 2>/dev/null || true
        ( _bg_verify_venv "${PYTHON_CMD%/bin/python3}" ) &
    fi
    unset _SENTINEL
fi

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

# Load global ~/.omnibase/.env first (lowest priority — project .env overrides below).
# This ensures LLM routing, Kafka, and other shared vars are always available even
# when the hook runs from a non-project CWD (e.g. home dir on dock launch).
_CLAUDE_GLOBAL_ENV="${HOME}/.omnibase/.env"
if [[ -f "${_CLAUDE_GLOBAL_ENV}" ]]; then
    set -a
    # shellcheck disable=SC1090
    if ! source "${_CLAUDE_GLOBAL_ENV}" 2>/dev/null; then
        if [[ -n "${LOG_FILE:-}" ]]; then
            # Use printf instead of log() — log() function is defined later in this file
            # and may not be available at this point in the source order.
            printf "[%s] WARN: Failed to source %s - check file syntax\n" \
                "$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo 'unknown')" \
                "${_CLAUDE_GLOBAL_ENV}" >> "${LOG_FILE}" 2>/dev/null || true
        fi
    fi
    set +a
fi
unset _CLAUDE_GLOBAL_ENV

# PROJECT_ROOT may be unbound in hook wrappers that source common.sh without
# setting it. Under `set -u` a bare ${PROJECT_ROOT} dereference raises
# "unbound variable", crashing the wrapper -- which fails GATE hooks OPEN via
# the error-guard EXIT trap (OMN-13848). Default to empty so an unset
# PROJECT_ROOT simply skips .env loading instead of crashing the hook.
if [[ -f "${PROJECT_ROOT:-}/.env" ]]; then
    # Source .env - note this WILL override already-set variables
    # Using set -a to export all variables, then set +a to stop
    set -a
    # shellcheck disable=SC1091
    # Note: We use 2>/dev/null because .env files may contain comments or blank
    # lines that produce benign warnings. Syntax errors are rare in .env files.
    if ! source "${PROJECT_ROOT:-}/.env" 2>/dev/null; then
        # Only log if LOG_FILE is set (caller script responsibility)
        if [[ -n "${LOG_FILE:-}" ]]; then
            # Use printf instead of log() — log() function is defined later in this file
            # and may not be available at this point in the source order.
            printf "[%s] WARN: Failed to source %s - check file syntax\n" \
                "$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo 'unknown')" \
                "${PROJECT_ROOT:-}/.env" >> "${LOG_FILE}" 2>/dev/null || true
        fi
    fi
    set +a
fi

# =============================================================================
# Kafka Configuration
# =============================================================================
# Kafka is REQUIRED for OmniClaude intelligence gathering.
# The entire architecture is event-driven via Kafka - without it, hooks have no purpose.
# Set KAFKA_BOOTSTRAP_SERVERS in .env (e.g., KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092).
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
# Slack Alerting
# =============================================================================
# Send a Slack notification for hook/daemon failures.
# Self-protecting: curl timeouts guarantee max 2s delay even on DNS hangs.
# Rate-limited per category (5-min window) to prevent alert spam.
# Always call from a backgrounded subshell: ( slack_notify "cat" "msg" ) &
#
# Delivery itself lives in alert-channel.sh (OMN-15600): the Slack Web API
# via a bot token is the sole channel — SLACK_WEBHOOK_URL was retired, not
# replaced — and a non-2xx outcome is recorded on a durable log plus a local
# notification instead of being discarded.
#
# Channel (no-op only when not configured):
#   - SLACK_BOT_TOKEN + SLACK_CHANNEL_ID: Slack Web API
#
# Returns: 0 delivered, 1 configured-but-dead, 2 not configured.
#
# Usage: ( slack_notify "daemon_startup" "Emit daemon failed to start..." ) &

# shellcheck source=./alert-channel.sh
source "$(dirname "${BASH_SOURCE[0]}")/alert-channel.sh" 2>/dev/null || true

# Cache hostname once at source time
_SLACK_HOST="${HOSTNAME:-$(hostname -s 2>/dev/null || echo unknown)}"

slack_notify() {
    local category="$1"
    local message="$2"

    # No-op only when the bot-token channel is not configured. A channel that
    # is configured but dead is NOT a no-op — see alert_channel_send
    # (OMN-15600). SLACK_WEBHOOK_URL is retired; there is no fallback.
    if [[ -z "${SLACK_BOT_TOKEN:-}" ]] || [[ -z "${SLACK_CHANNEL_ID:-}" ]]; then
        return 2
    fi

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

    # Record the attempt for rate limiting regardless of outcome — a dead
    # channel must not cost a 2s curl on every hook invocation. The delivery
    # failure itself is recorded durably by alert_channel_send.
    date -u +%s > "$rate_file" 2>/dev/null || true

    local rc=0
    alert_channel_send "$category" "$message" || rc=$?
    return $rc
}

# =============================================================================
# Degraded Hook Notification (OMN-6567)
# =============================================================================
# Send a Slack notification when a hook exits 0 but ran in degraded mode
# (e.g. Python subprocess hit ModuleNotFoundError/ImportError). Complements
# error-guard.sh which only catches non-zero exits.
#
# Debounce key: {hook_name}:{sha256_of_first_error_line} — different errors
# from the same hook are tracked separately.
# Debounce window: 15 minutes (longer than error-guard's 5 min because
# degraded errors repeat on every tool call).
#
# Dependencies: curl (best-effort). No Python, no jq.
# Must not write to stdout (hooks use stdout for Claude Code communication).
# Always call from a backgrounded subshell: ( notify_hook_degraded "foo" "msg" ) &
#
# Usage: ( notify_hook_degraded "$_OMNICLAUDE_HOOK_NAME" "$(head -1 "$_stderr_tmp")" ) &

notify_hook_degraded() {
    local hook_name="$1"
    local error_message="$2"

    # No-op only when the bot-token channel is not configured (OMN-15600).
    # SLACK_WEBHOOK_URL is retired; there is no fallback.
    if [[ -z "${SLACK_BOT_TOKEN:-}" ]] || [[ -z "${SLACK_CHANNEL_ID:-}" ]]; then
        return 2
    fi

    # Build debounce key: hook_name:sha256(first_line_of_error)
    # Use shasum (macOS) or sha256sum (Linux) for the hash
    local error_hash
    if command -v shasum >/dev/null 2>&1; then
        error_hash=$(printf '%s' "$error_message" | shasum -a 256 2>/dev/null | cut -c1-16)
    elif command -v sha256sum >/dev/null 2>&1; then
        error_hash=$(printf '%s' "$error_message" | sha256sum 2>/dev/null | cut -c1-16)
    else
        # Fallback: use a simple tr-based sanitization as key
        error_hash=$(printf '%s' "$error_message" | tr -cd 'a-zA-Z0-9' | cut -c1-32)
    fi
    [[ -z "$error_hash" ]] && error_hash="unknown"

    # Sanitize hook name for safe filename
    local safe_hook
    safe_hook=$(printf '%s' "$hook_name" | tr -cd 'a-zA-Z0-9_-')
    [[ -z "$safe_hook" ]] && safe_hook="unknown"

    local safe_key="${safe_hook}_${error_hash}"

    # Rate limiting: 15-minute window per debounce key
    local rate_dir="/tmp/omniclaude-slack-rate"
    mkdir -p "$rate_dir" 2>/dev/null || true
    local rate_file="${rate_dir}/degraded-${safe_key}.last"

    if [[ -f "$rate_file" ]]; then
        local last_sent
        last_sent=$(cat "$rate_file" 2>/dev/null) || last_sent=0
        [[ "$last_sent" =~ ^[0-9]+$ ]] || last_sent=0
        local now
        now=$(date -u +%s)
        if (( now - last_sent < 900 )); then
            return 0  # Rate limited, skip
        fi
    fi

    # Record the attempt for rate limiting regardless of outcome (see slack_notify).
    date -u +%s > "$rate_file" 2>/dev/null || true

    local rc=0
    alert_channel_send "hook_degraded_${safe_hook}" \
        "[hook-degraded][${_SLACK_HOST}] Hook '${hook_name}' running degraded: ${error_message}" || rc=$?
    return $rc
}

# =============================================================================
# Structured Hook Error Emission (OMN-7158)
# =============================================================================
# Emit structured hook error event to Kafka via temp-file handoff.
# SECURITY: Never interpolates raw stderr into python -c. Writes to temp file.
# Always call from a backgrounded subshell: ( emit_hook_error_event "$_stderr_tmp" ) &
#
# Usage: ( emit_hook_error_event "$_stderr_tmp" ) &

emit_hook_error_event() {
    local stderr_file="$1"
    [[ -z "$stderr_file" || ! -f "$stderr_file" || ! -s "$stderr_file" ]] && return 0
    "$PYTHON_CMD" -m plugins.onex.hooks.lib.hook_error_emitter \
        --hook-name "${_OMNICLAUDE_HOOK_NAME:-unknown}" \
        --error-file "$stderr_file" \
        --session-id "${SESSION_ID:-unknown}" \
        --python-version "$("$PYTHON_CMD" --version 2>&1)" \
        --hook-script-path "${BASH_SOURCE[1]:-unknown}" \
        2>/dev/null || true  # fire-and-forget
}

# =============================================================================
# Emit Daemon Helper (OMN-1631, OMN-1632)
# =============================================================================
# The legacy emit path is GONE (OMN-18471 AC5)
# =============================================================================
# `emit_via_daemon()` and `_try_restart_emit_daemon()` lived here. They wrote
# to a Unix socket at ~/.claude/emit.sock and kept per-event-type
# consecutive-failure counters under ${ONEX_STATE_DIR}/hooks/logs/emit-health/.
#
# That socket has not existed since 2026-06-08. From that date the function
# failed on every call and the counters recorded a constant rather than a
# signal -- read live on 2026-09-16 they claimed 101,009 consecutive failures
# for tool.executed with a last success in June, and they would have said
# exactly that whether hook capture was healthy or dead. During the 22-hour
# drainer outage of 2026-09-15/16 they produced no signal of their own.
#
# Worse than useless, they were load-bearing in the wrong direction: eight
# event classes had `emit_via_daemon` as their ONLY call site, so those
# classes were not dual-homed, they were undelivered. Removing this function
# before they were re-homed would have deleted the only call site they had,
# which is why AC5 was gated on AC1-AC4 rather than done first.
#
# All twelve classes now reach the broker through `emit_to_journal` below.
# Delivery liveness is `hook_emit_health.py`, which reads journal backlog
# depth and the drainer's last CONFIRMED publish -- the two facts only the
# live path can state.


# =============================================================================
# Journal Append (OMN-17224 fast path, OMN-18471 re-homing, OMN-18702 restore)
# =============================================================================
# Append one event to the local hook-emit journal. The launchd singleton
# drainer (hook_emit_drainer.py) publishes it to the contract-declared lane.
#
# This is the ONLY delivery path a hook event has, and it is the same writer
# `post_tool_use_bus_mirror.sh` uses for tool.executed -- which is why that
# one class kept working while every class routed through this function did
# not.
#
# OMN-18702: this function was added by 0477e64f6 and then DELETED by
# 7924f64b7, as collateral in the 293-line removal of emit_via_daemon and its
# counter surface -- it sat in the middle of the block that was cut. Its ten
# call sites survived, so from 2026-09-17T06:50Z every one of them exited 127
# and dropped its event. Nothing reported it: the two guards that read this
# surface (test_hook_edge_lane.py, test_hook_emit_health.py) match the
# CALL-SITE TOKEN as text and never ask whether the callee exists, so they
# stayed green for the whole outage. The check that closes that gap is
# tests/hooks/test_emit_to_journal_callee_omn18702.py, which runs the hook
# scripts and reports any callee defined nowhere in the tree.
#
# Requires: PYTHON_CMD (set by this file). HOOKS_LIB and LOG_FILE are used
# when the caller sets them, and resolved or defaulted when it does not --
# a delivery path must not depend on each caller remembering to export a
# variable.
#
# Backgrounded and fail-open by construction: a hook that cannot record
# telemetry must never slow or break the operator's session. The per-call
# cost is one stdlib-only Python process; publishing is the drainer's job.
#
# Usage: emit_to_journal <event_type> <payload_json> [correlation_id] [cwd]

emit_to_journal() {
    local event_type="$1"
    local payload="$2"
    local correlation_id="${3:-}"
    # The lane registry is resolved against the directory the HOOK fired in,
    # not this backgrounded process's own cwd (OMN-18609). Several callers
    # cd to $HOME before invoking Python, so reading it here would attribute
    # every record to no lane at all.
    local cwd="${4:-${CLAUDE_PROJECT_DIR:-$PWD}}"

    local lib_dir="${HOOKS_LIB:-}"
    if [[ -z "$lib_dir" ]]; then
        lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" 2>/dev/null && pwd)" || lib_dir=""
    fi

    local append_py="${lib_dir}/hook_emit_append.py"
    [[ -n "${PYTHON_CMD:-}" && -f "$append_py" ]] || return 0

    local -a args=(--event-type "$event_type" --payload "$payload")
    [[ -n "$correlation_id" ]] && args+=(--correlation-id "$correlation_id")
    [[ -n "$cwd" ]] && args+=(--cwd "$cwd")

    (
        "$PYTHON_CMD" "$append_py" "${args[@]}" >>"${LOG_FILE:-/dev/null}" 2>&1
    ) &
    disown 2>/dev/null || true
    return 0
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

# =============================================================================
# Hook health probe consumption [F32 / OMN-15600 / OMN-15606]
# =============================================================================
# Runs the session-start hook-health probe and reports its verdict on the local
# log — the one surface guaranteed not to be the channel that is broken.
#
# This lives in common.sh, not inline in session-start.sh, so the consumption
# logic can be driven directly by tests rather than through a re-implementation
# of it (see tests/unit/hooks/scripts/test_session_start_probe_consumption.py).
#
# FAIL-CLOSED (OMN-15606). The previous inline block defaulted the channel
# status to "unknown" on any parse failure and only logged on "dead", so
# "probe crashed", "probe emitted malformed JSON", "probe never ran" and
# "channel healthy" were one silent case. Every not-affirmatively-healthy
# outcome now produces its own distinct, non-silent line.
#
# Requires: PYTHON_CMD, LOG_FILE (and BREW_PY where available).
# Returns: 0 only when the probe ran and reported no failures.
run_hook_health_probe() {
    local probe_json="" probe_rc=0 failures="" channel="" rc=0

    probe_json=$("$PYTHON_CMD" -m omniclaude.hooks.lib.hook_health_probe 2>>"$LOG_FILE") \
        || probe_rc=$?

    # Parse with the resolved hook interpreter, PYTHONPATH stripped so an
    # inherited PYTHONPATH cannot shadow stdlib json. PYTHON_CMD (not BREW_PY)
    # is used deliberately: find_python hard-fails when it cannot resolve, so
    # it always exists, whereas BREW_PY is a macOS-only literal that is absent
    # on Linux CI — where the parse would fail and every probe outcome would
    # collapse into "unreadable".

    failures=$(printf '%s' "$probe_json" | env -u PYTHONPATH "$PYTHON_CMD" -c \
        'import json,sys; print(int(json.load(sys.stdin)["failures"]))' \
        2>>"$LOG_FILE") || failures=""
    channel=$(printf '%s' "$probe_json" | env -u PYTHONPATH "$PYTHON_CMD" -c \
        'import json,sys; print(json.load(sys.stdin)["alert_channel"]["status"])' \
        2>>"$LOG_FILE") || channel=""

    if [[ -z "$failures" || -z "$channel" ]]; then
        # The probe did not produce a readable verdict, so nothing was checked.
        # That is a failure OF the check, and is reported as one.
        log "ERROR: hook-health probe output unreadable (probe exit ${probe_rc}) — handler-import and alert-channel checks did NOT run this session. See hooks.log."
        return 1
    fi

    if [[ "$failures" != "0" ]]; then
        log "WARNING: $failures hook-health failure(s) (handler imports and/or alert channel). See hooks.log for details."
        rc=1
    fi

    case "$channel" in
        live|not_configured)
            # Affirmatively established, or affirmatively absent — alerting
            # works, so this is not a failure. A dead SECONDARY channel is
            # still surfaced: it delivers nothing and wants cleaning up, and
            # if the live primary later lapses it is the only one left.
            local dead_channels=""
            dead_channels=$(printf '%s' "$probe_json" | env -u PYTHONPATH "$PYTHON_CMD" -c \
                'import json,sys; print(",".join(json.load(sys.stdin)["alert_channel"].get("dead_channels") or []))' \
                2>>"$LOG_FILE") || dead_channels=""
            if [[ -n "$dead_channels" ]]; then
                log "WARNING: alert channel degraded — ${dead_channels} dead, still delivering via another channel. See ${HOME}/.omnibase/alert_delivery_failures.log"
            fi
            ;;
        dead)
            log "ERROR: alert channel is DEAD — hook alerts are delivering to nothing. See ${HOME}/.omnibase/alert_delivery_failures.log"
            rc=1
            ;;
        probe_error)
            log "ERROR: alert-channel liveness probe FAILED to run — channel liveness is UNVERIFIED this session, which is not the same as healthy. See hooks.log."
            rc=1
            ;;
        *)
            log "ERROR: alert-channel status '${channel}' is not a declared EnumChannelStatus member — treating channel liveness as UNVERIFIED."
            rc=1
            ;;
    esac

    return "$rc"
}
