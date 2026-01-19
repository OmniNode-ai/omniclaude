#!/bin/bash
# PostToolUse Hook - ONEX Event Emission Stub
# OMN-1399: Schema definition only, emission in OMN-1400
# Performance target: <100ms execution time

set -euo pipefail

# Read hook input from stdin
INPUT=$(cat)

# Log for debugging (optional)
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
LOG_FILE="${HOOKS_DIR}/logs/hook-post-tool-use.log"
mkdir -p "$(dirname "$LOG_FILE")"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] PostToolUse hook triggered (stub mode)" >> "$LOG_FILE"

# Extract tool info for logging
TOOL_NAME=$(echo "$INPUT" | jq -r '.toolName // .tool_name // "unknown"' 2>/dev/null || echo "unknown")
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Tool: $TOOL_NAME" >> "$LOG_FILE"

# OMN-1400 will add: Event emission to Kafka using ModelToolExecuted schema

# Return valid response (continue hook execution)
echo '{"continue": true}'
exit 0
