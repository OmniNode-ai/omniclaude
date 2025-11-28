#!/bin/bash
# SessionEnd Hook - Capture session completion and aggregate statistics
#
# Aggregates session data from hook_events to provide insights into:
# - Session duration
# - Total prompts submitted
# - Total tools executed
# - Agents invoked
# - Workflow pattern classification
#
# Performance target: <50ms execution time

set -euo pipefail

# Configuration
LOG_FILE="$HOME/.claude/hooks/hook-enhanced.log"
HOOKS_LIB="$HOME/.claude/onex/lib"
export PYTHONPATH="${HOOKS_LIB}:${PYTHONPATH:-}"

# Read stdin (Claude Code sends JSON with session info)
INPUT=$(cat)

# Log hook trigger
echo "[$(date '+%Y-%m-%d %H:%M:%S')] SessionEnd hook triggered" >> "$LOG_FILE"

# Extract session metadata from JSON (if available)
SESSION_ID=$(echo "$INPUT" | jq -r '.sessionId // ""' 2>/dev/null || echo "")
SESSION_DURATION=$(echo "$INPUT" | jq -r '.durationMs // 0' 2>/dev/null || echo "0")

# Log session info
if [[ -n "$SESSION_ID" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Session ID: $SESSION_ID" >> "$LOG_FILE"
fi
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Duration: ${SESSION_DURATION}ms" >> "$LOG_FILE"

# Call session intelligence module (async, non-blocking)
# This aggregates statistics from hook_events and logs SessionEnd event
(
    python3 "${HOOKS_LIB}/session_intelligence.py" \
        --mode end \
        --session-id "${SESSION_ID}" \
        --metadata "{\"hook_duration_ms\": ${SESSION_DURATION}}" \
        >> "$LOG_FILE" 2>&1 || echo "[$(date '+%Y-%m-%d %H:%M:%S')] Session end logging failed (continuing)" >> "$LOG_FILE"
) &

# Clean up correlation state (session is ending)
if [[ -f "${HOOKS_LIB}/correlation_manager.py" ]]; then
    python3 -c "
import sys
sys.path.insert(0, '${HOOKS_LIB}')
from correlation_manager import get_manager
get_manager().clear()
" 2>/dev/null || true
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] SessionEnd hook completed" >> "$LOG_FILE"

# Always output the input unchanged (hooks must pass through)
echo "$INPUT"

exit 0
