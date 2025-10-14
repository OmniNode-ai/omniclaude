#!/bin/bash
# SessionStart Hook - Capture session initialization intelligence
# Logs session metadata: session_id, project_path, git branch, timestamp
# Performance target: <50ms execution time

set -euo pipefail

# Configuration
LOG_FILE="$HOME/.claude/hooks/hook-session-start.log"
HOOKS_LIB="$HOME/.claude/hooks/lib"
export PYTHONPATH="${HOOKS_LIB}:${PYTHONPATH:-}"

# Performance tracking
START_TIME=$(python3 -c "import time; print(int(time.time() * 1000))")

# Read stdin (Claude Code sends JSON with session info)
INPUT=$(cat)

# Log hook trigger
echo "[$(date '+%Y-%m-%d %H:%M:%S')] SessionStart hook triggered" >> "$LOG_FILE"

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
        python3 "${HOOKS_LIB}/session_intelligence.py" \
            --mode start \
            --session-id "$SESSION_ID" \
            --project-path "$PROJECT_PATH" \
            --cwd "$CWD" \
            >> "$LOG_FILE" 2>&1
    ) &

    PYTHON_PID=$!
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Session intelligence logging started (PID: $PYTHON_PID)" >> "$LOG_FILE"
fi

# Performance tracking
END_TIME=$(python3 -c "import time; print(int(time.time() * 1000))")
ELAPSED_MS=$((END_TIME - START_TIME))

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Hook execution time: ${ELAPSED_MS}ms" >> "$LOG_FILE"

# Warn if execution exceeded 50ms target
if [[ $ELAPSED_MS -gt 50 ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️  WARNING: Hook execution exceeded 50ms target: ${ELAPSED_MS}ms" >> "$LOG_FILE"
fi

# Always return success (don't break user workflow)
exit 0
