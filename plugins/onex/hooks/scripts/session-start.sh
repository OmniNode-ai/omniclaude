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

# Source shared functions (provides PYTHON_CMD, KAFKA_ENABLED, get_time_ms)
source "${HOOKS_DIR}/scripts/common.sh"

export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

# Performance tracking
START_TIME=$(get_time_ms)

# Read stdin
INPUT=$(cat)

echo "[$(date '+%Y-%m-%d %H:%M:%S')] SessionStart hook triggered (plugin mode)" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Using Python: $PYTHON_CMD" >> "$LOG_FILE"

# Extract session information
SESSION_ID=$(echo "$INPUT" | jq -r '.sessionId // .session_id // ""')
PROJECT_PATH=$(echo "$INPUT" | jq -r '.projectPath // .project_path // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // ""' || pwd)

if [[ -z "$CWD" ]]; then
    CWD=$(pwd)
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Session ID: $SESSION_ID" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Project Path: $PROJECT_PATH" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] CWD: $CWD" >> "$LOG_FILE"

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
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Session intelligence logging started" >> "$LOG_FILE"
fi

# Emit session.started event to Kafka (async, non-blocking)
# Uses omniclaude-emit CLI with 250ms hard timeout
if [[ "$KAFKA_ENABLED" == "true" ]]; then
    (
        GIT_BRANCH=""
        if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
            GIT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")
        fi

        "$PYTHON_CMD" -m omniclaude.hooks.cli_emit session-started \
            --session-id "$SESSION_ID" \
            --cwd "$CWD" \
            --source "startup" \
            ${GIT_BRANCH:+--git-branch "$GIT_BRANCH"} \
            >> "$LOG_FILE" 2>&1 || { rc=$?; echo "[$(date '+%Y-%m-%d %H:%M:%S')] Kafka emit failed (exit=$rc, non-fatal)" >> "$LOG_FILE"; }
    ) &
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Session event emission started" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Kafka emission skipped (KAFKA_ENABLED=$KAFKA_ENABLED)" >> "$LOG_FILE"
fi

# Performance tracking
END_TIME=$(get_time_ms)
ELAPSED_MS=$((END_TIME - START_TIME))

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Hook execution time: ${ELAPSED_MS}ms" >> "$LOG_FILE"

if [[ $ELAPSED_MS -gt 50 ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: Exceeded 50ms target: ${ELAPSED_MS}ms" >> "$LOG_FILE"
fi

exit 0
