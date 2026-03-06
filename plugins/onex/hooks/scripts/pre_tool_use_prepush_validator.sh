#!/bin/bash
# PreToolUse Pre-Push Validator Hook
# Intercepts git push commands and runs adaptive validation checks before allowing push

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

cd "$HOME" 2>/dev/null || cd /tmp || true

_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${LOG_FILE:-$HOME/.claude/hooks.log}"

PROJECT_ROOT="${PLUGIN_ROOT}/../.."
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"
elif [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"
else
    PROJECT_ROOT="$(pwd)"
fi

mkdir -p "$(dirname "$LOG_FILE")"

export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

source "${HOOKS_DIR}/scripts/common.sh"

# Read stdin
TOOL_INFO=$(cat)
if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>>"$LOG_FILE"); then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: invalid hook JSON; failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi

# Only intercept Bash tool invocations
if [[ "$TOOL_NAME" != "Bash" ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Check if command contains git push
COMMAND=$(echo "$TOOL_INFO" | jq -r '.tool_input.command // empty' 2>/dev/null)
if [[ -z "$COMMAND" ]] || ! echo "$COMMAND" | grep -qE '(^|\s|&&|\|)git\s+push(\s|$)'; then
    echo "$TOOL_INFO"
    exit 0
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Pre-push validator triggered" >> "$LOG_FILE"

# Run Python pre-push validator
set +e
RESULT=$(echo "$TOOL_INFO" | \
    $PYTHON_CMD "${HOOKS_LIB}/prepush_validator.py" 2>>"$LOG_FILE")
EXIT_CODE=$?
set -e

if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Pre-push validation PASSED" >> "$LOG_FILE"
    echo "$RESULT"
elif [ $EXIT_CODE -eq 2 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Pre-push validation BLOCKED" >> "$LOG_FILE"
    echo "$RESULT"
    exit 2
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: Pre-push validator failed with code $EXIT_CODE, failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi
