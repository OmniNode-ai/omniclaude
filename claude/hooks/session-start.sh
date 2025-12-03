#!/bin/bash
# SessionStart Hook - Capture session initialization intelligence
# Logs session metadata: session_id, project_path, git branch, timestamp
# Performance target: <50ms execution time

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_FILE="${SCRIPT_DIR}/logs/hook-session-start.log"
HOOKS_LIB="${SCRIPT_DIR}/lib"

# Poetry venv path - use this for ALL Python calls
POETRY_VENV="/Users/jonah/Library/Caches/pypoetry/virtualenvs/omniclaude-agents-kzVi5DqF-py3.12"
# Fallback to symlink if direct path doesn't exist
HOOKS_VENV="${PROJECT_ROOT}/claude/lib/.venv"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Determine which Python to use - prefer Poetry venv, then symlink, then system
if [[ -f "$POETRY_VENV/bin/python3" ]]; then
    PYTHON_CMD="$POETRY_VENV/bin/python3"
    export PATH="$POETRY_VENV/bin:$PATH"
elif [[ -f "$HOOKS_VENV/bin/python3" ]]; then
    PYTHON_CMD="$HOOKS_VENV/bin/python3"
    export PATH="$HOOKS_VENV/bin:$PATH"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: Poetry venv not found, using system Python" >> "$LOG_FILE"
    PYTHON_CMD="python3"
fi

export PYTHONPATH="${PROJECT_ROOT}:${HOOKS_LIB}:${PYTHONPATH:-}"

# Load environment variables from .env if available
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a  # automatically export all variables
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# Performance tracking (use Python for millisecond precision on macOS)
START_TIME=$($PYTHON_CMD -c "import time; print(int(time.time() * 1000))")

# Read stdin (Claude Code sends JSON with session info)
INPUT=$(cat)

# Log hook trigger
echo "[$(date '+%Y-%m-%d %H:%M:%S')] SessionStart hook triggered" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Using Python: $PYTHON_CMD" >> "$LOG_FILE"

# Extract session information from JSON
SESSION_ID=$(echo "$INPUT" | jq -r '.sessionId // .session_id // ""')
PROJECT_PATH=$(echo "$INPUT" | jq -r '.projectPath // .project_path // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // ""' || pwd)

# Fallback to pwd if CWD is empty
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

    PYTHON_PID=$!
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Session intelligence logging started (PID: $PYTHON_PID)" >> "$LOG_FILE"
fi

# Performance tracking (use Python for millisecond precision on macOS)
END_TIME=$($PYTHON_CMD -c "import time; print(int(time.time() * 1000))")
ELAPSED_MS=$((END_TIME - START_TIME))

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Hook execution time: ${ELAPSED_MS}ms" >> "$LOG_FILE"

# Warn if execution exceeded 50ms target
if [[ $ELAPSED_MS -gt 50 ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: Hook execution exceeded 50ms target: ${ELAPSED_MS}ms" >> "$LOG_FILE"
fi

# Always return success (don't break user workflow)
exit 0
