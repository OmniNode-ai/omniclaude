#!/bin/bash
# UserPromptSubmit Hook - Simple Test Version
# Tests that hooks are working before full implementation

set -euo pipefail

# Log file for debugging
LOG_FILE="$HOME/.claude/hooks/hook-test.log"

# Read the prompt JSON from stdin
INPUT=$(cat)

# Log that hook was triggered
echo "[$(date '+%Y-%m-%d %H:%M:%S')] UserPromptSubmit hook triggered" >> "$LOG_FILE"

# Extract the prompt from the JSON
PROMPT=$(echo "$INPUT" | jq -r '.prompt // ""')

# Log the prompt (first 100 chars)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Prompt: ${PROMPT:0:100}..." >> "$LOG_FILE"

# Check if prompt mentions "agent"
if echo "$PROMPT" | grep -qi "agent"; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Agent pattern detected!" >> "$LOG_FILE"

    # Add a simple context injection
    ENHANCED_PROMPT=$(cat <<EOF
$PROMPT

---
🔧 [Hook Test Active] Agent-related prompt detected. Hook system is working!
EOF
)

    # Output the enhanced prompt as JSON
    echo "$INPUT" | jq --arg enhanced_prompt "$ENHANCED_PROMPT" '.hookSpecificOutput.additionalContext = $enhanced_prompt'
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] No agent pattern detected" >> "$LOG_FILE"
    # Pass through unchanged
    echo "$INPUT"
fi

exit 0
