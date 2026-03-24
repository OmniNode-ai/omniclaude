#!/bin/bash
# PreToolUse Bash Guard Hook - Portable Plugin Version
# Intercepts Bash tool invocations for command safety validation

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Ensure stable CWD before any Python invocation.
# The session CWD may be on an external drive that disconnects/remounts;
# Python's <frozen getpath> calls os.getcwd() during startup and crashes
# with "failed to make path absolute" if the CWD is unavailable.
cd "$HOME" 2>/dev/null || cd /tmp || true

# Portable Plugin Configuration
# Resolve absolute path of this script, handling relative invocation (e.g. ./pre_tool_use_bash_guard.sh).
# Falls back to python3 if realpath is unavailable (non-GNU macOS without coreutils).
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { echo "ONEX_STATE_DIR not set" >&2; exit 1; }
LOG_FILE="${ONEX_HOOK_LOG}"

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

export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

# Load environment variables
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# Source shared functions (provides PYTHON_CMD, KAFKA_ENABLED)
source "${HOOKS_DIR}/scripts/common.sh"

# Read stdin
TOOL_INFO=$(cat)
if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>>"$LOG_FILE"); then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: invalid hook JSON; failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Bash guard hook invoked for tool: $TOOL_NAME" >> "$LOG_FILE"

# Only intercept Bash tool invocations
if [[ "$TOOL_NAME" != "Bash" ]]; then
    _hook_status "PASS" "not Bash ($TOOL_NAME)" "0"
    echo "$TOOL_INFO"
    exit 0
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Checking Bash command safety" >> "$LOG_FILE"

# Run Python bash guard
set +e
RESULT=$(echo "$TOOL_INFO" | \
    $PYTHON_CMD "${HOOKS_LIB}/bash_guard.py" 2>>"$LOG_FILE")
EXIT_CODE=$?
set -e

# Handle exit codes
if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Bash command ALLOWED" >> "$LOG_FILE"
    _hook_status "PASS" "Bash command allowed" "0"
    echo "$RESULT"
elif [ $EXIT_CODE -eq 2 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Bash command BLOCKED by guard" >> "$LOG_FILE"
    _hook_status "BLOCKED" "Bash command rejected" "0"
    printf '\a' >&2   # BEL to stderr — audible/visual alert in terminal emulators
    echo "$RESULT"    # JSON response to stdout (not mixed with bell)
    exit 2
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: Bash guard failed with code $EXIT_CODE, failing open" >> "$LOG_FILE"
    _hook_status "PASS" "guard error, failing open (exit=$EXIT_CODE)" "0"
    echo "$TOOL_INFO"
    exit 0
fi
