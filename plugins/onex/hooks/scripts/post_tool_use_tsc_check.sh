#!/usr/bin/env bash
# post_tool_use_tsc_check.sh
# PostToolUse hook: run tsc --noEmit after editing TypeScript files.
# Fires on Edit|Write tool completions. Reads tool_name and tool_input from stdin JSON.
# Exits 0 always (informational only — errors are surfaced as stdout warnings).

set -euo pipefail

# --- Lite mode guard [OMN-5398] ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _SCRIPT_DIR _MODE_SH

INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null || true)

if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
  exit 0
fi

FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
inp = d.get('tool_input', {})
print(inp.get('file_path', inp.get('path', '')))
" 2>/dev/null || true)

# Only fire on TypeScript files
if [[ "$FILE_PATH" != *.ts && "$FILE_PATH" != *.tsx ]]; then
  exit 0
fi

# Find the nearest tsconfig.json by walking up from the file's directory
DIR=$(dirname "$FILE_PATH")
TSCONFIG=""
while [[ "$DIR" != "/" ]]; do
  if [[ -f "$DIR/tsconfig.json" ]]; then
    TSCONFIG="$DIR/tsconfig.json"
    break
  fi
  DIR=$(dirname "$DIR")
done

if [[ -z "$TSCONFIG" ]]; then
  exit 0
fi

PROJECT_DIR=$(dirname "$TSCONFIG")

TSC_OUT=$(cd "$PROJECT_DIR" && npx tsc --noEmit 2>&1 | head -20 || true)

if [[ -n "$TSC_OUT" ]]; then
  echo ""
  echo "⚠ TypeScript errors detected after editing $FILE_PATH:"
  echo "$TSC_OUT"
fi

exit 0
