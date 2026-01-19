#!/bin/bash
# UserPromptSubmit Hook - ONEX Event Emission Stub
# OMN-1399: Schema definition only, emission in OMN-1400
# Performance target: <500ms execution time

set -euo pipefail

# Read hook input from stdin
INPUT=$(cat)

# Log for debugging (optional)
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
LOG_FILE="${HOOKS_DIR}/logs/hook-user-prompt-submit.log"
mkdir -p "$(dirname "$LOG_FILE")"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] UserPromptSubmit hook triggered (stub mode)" >> "$LOG_FILE"

# Extract prompt info for logging
PROMPT_PREVIEW=$(echo "$INPUT" | jq -r '.prompt // ""' 2>/dev/null | head -c 100 || echo "")
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Prompt preview: ${PROMPT_PREVIEW}..." >> "$LOG_FILE"

# OMN-1400 will add: Event emission to Kafka using ModelPromptSubmitted schema

# Return valid response (continue hook execution)
echo '{"continue": true}'
exit 0
