#!/bin/bash
# PostToolUse Hook - Shell wrapper to set up venv before running Python enforcer
#
# This wrapper ensures the Poetry venv is used for running Python scripts
# that require aiokafka, psycopg2, and other dependencies not in system Python.

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_FILE="${SCRIPT_DIR}/logs/hook-post-tool-use.log"

# Poetry venv path - use this for ALL Python calls
POETRY_VENV="/Users/jonah/Library/Caches/pypoetry/virtualenvs/omniclaude-agents-kzVi5DqF-py3.12"
# Fallback to symlink if direct path doesn't exist
HOOKS_VENV="${PROJECT_ROOT}/claude/lib/.venv"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

log() { printf "[%s] %s\n" "$(date "+%Y-%m-%d %H:%M:%S")" "$*" >> "$LOG_FILE"; }

log "PostToolUse hook triggered"

# Read stdin (Claude Code sends JSON with tool use info)
INPUT="$(cat)"

# Extract file path from JSON input
# PostToolUse provides: {"tool_name": "Write", "tool_input": {"file_path": "...", "content": "..."}}
FILE_PATH="$(printf %s "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null || echo "")"

if [[ -z "$FILE_PATH" ]]; then
    log "No file path in input, passing through"
    printf %s "$INPUT"
    exit 0
fi

log "Processing file: $FILE_PATH"

# Determine which Python to use - prefer Poetry venv, then symlink, then system
if [[ -f "$POETRY_VENV/bin/python3" ]]; then
    PYTHON_CMD="$POETRY_VENV/bin/python3"
    export PATH="$POETRY_VENV/bin:$PATH"
elif [[ -f "$HOOKS_VENV/bin/python3" ]]; then
    PYTHON_CMD="$HOOKS_VENV/bin/python3"
    export PATH="$HOOKS_VENV/bin:$PATH"
else
    log "WARNING: Poetry venv not found, using system Python (modules may be missing)"
    PYTHON_CMD="python3"
fi

log "Using Python: $PYTHON_CMD"

# Set up PYTHONPATH for imports
export PYTHONPATH="${PROJECT_ROOT}:${SCRIPT_DIR}/lib:${PYTHONPATH:-}"

# Load environment variables from .env if available
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# Run the Python enforcer with the file path
# Note: The enforcer expects file paths as arguments, not stdin
if "$PYTHON_CMD" "${SCRIPT_DIR}/post_tool_use_enforcer.py" "$FILE_PATH" >> "$LOG_FILE" 2>&1; then
    log "PostToolUse enforcer completed successfully"
else
    EXIT_CODE=$?
    log "PostToolUse enforcer failed with exit code $EXIT_CODE"
fi

# Always pass through the original input (hook should not modify output)
printf %s "$INPUT"
exit 0
