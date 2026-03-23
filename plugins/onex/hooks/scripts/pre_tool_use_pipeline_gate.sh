#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Pipeline Gate — PreToolUse hook
#
# Blocks Edit/Write/Bash(commit) without an active ticket-pipeline or
# /authorize override. Ensures all implementation goes through the
# design-to-plan -> plan-to-tickets -> ticket-pipeline flow.
#
# Policy modes (from PIPELINE_GATE_MODE env var):
#   advisory (default) — log warning, allow
#   soft               — log warning, allow, add system message
#   hard               — block the tool call
#
# Exit codes:
#   0 — allow the tool call
#   2 — block the tool call (hard mode only)

set -eo pipefail

# --- Lite mode guard [OMN-5398] ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _SCRIPT_DIR _MODE_SH

# Resolve hook infrastructure paths
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
PYTHON_CMD="${PYTHON_CMD:-python3}"
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { echo "ONEX_STATE_DIR not set" >&2; exit 1; }
LOG_FILE="${ONEX_HOOK_LOG}"

# Read stdin (tool invocation JSON)
INPUT=$(cat)

# Extract tool name
TOOL_NAME=$(echo "$INPUT" | $PYTHON_CMD -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('tool_name', ''))
except Exception:
    print('')
" 2>/dev/null || echo "")

# Only gate Edit, Write, and Bash tools
case "$TOOL_NAME" in
    Edit|Write|Bash)
        ;;
    *)
        exit 0
        ;;
esac

# Extract file path (for Edit/Write) or command (for Bash)
GATE_INFO=$(echo "$INPUT" | $PYTHON_CMD -c "
import json, sys
try:
    data = json.load(sys.stdin)
    tool_input = data.get('tool_input', {})
    tool_name = data.get('tool_name', '')
    file_path = tool_input.get('file_path', '')
    command = tool_input.get('command', '')
    print(json.dumps({
        'tool_name': tool_name,
        'file_path': file_path,
        'command': command
    }))
except Exception:
    print(json.dumps({'tool_name': '', 'file_path': '', 'command': ''}))
" 2>/dev/null || echo '{"tool_name":"","file_path":"","command":""}')

FILE_PATH=$(echo "$GATE_INFO" | $PYTHON_CMD -c "import json,sys; print(json.load(sys.stdin).get('file_path',''))" 2>/dev/null || echo "")
COMMAND=$(echo "$GATE_INFO" | $PYTHON_CMD -c "import json,sys; print(json.load(sys.stdin).get('command',''))" 2>/dev/null || echo "")

# --- Whitelisted path check (Edit/Write) ---
if [[ "$TOOL_NAME" == "Edit" || "$TOOL_NAME" == "Write" ]] && [[ -n "$FILE_PATH" ]]; then
    # Check whitelisted path patterns (never blocked)
    WHITELISTED=$($PYTHON_CMD -c "
import sys, fnmatch

path = '$FILE_PATH'
patterns = [
    '**/docs/**', '**/plans/**', '**/memory/**',
    '**/CLAUDE.md', '**/MEMORY.md',
    '**/.claude/settings*', '**/.claude/plugins/*/SKILL.md',
    '**/.claude/plans/**', '**/.claude/memory/**',
    '**/hooks/config/**', '**/dod_sweep_exemptions.yaml',
    '**/__pycache__/**', '/tmp/**'
]

for pat in patterns:
    # Convert glob ** patterns to work with fnmatch
    # fnmatch doesn't support **, so use simple substring checks
    clean = pat.replace('**/', '').replace('/**', '')
    if clean.startswith('*'):
        clean = clean[1:]
    if clean in path or fnmatch.fnmatch(path, pat):
        print('true')
        sys.exit(0)

# Also check path components directly
components = path.split('/')
whitelisted_dirs = ['docs', 'plans', 'memory', '__pycache__']
whitelisted_files = ['CLAUDE.md', 'MEMORY.md', 'dod_sweep_exemptions.yaml']

for comp in components:
    if comp in whitelisted_dirs:
        print('true')
        sys.exit(0)

basename = path.rsplit('/', 1)[-1] if '/' in path else path
if basename in whitelisted_files:
    print('true')
    sys.exit(0)

if path.startswith('/tmp/'):
    print('true')
    sys.exit(0)

# Check .claude subdirectory whitelist
if '/.claude/' in path:
    for sub in ['/plans/', '/memory/', '/settings']:
        if sub in path:
            print('true')
            sys.exit(0)
    if '/plugins/' in path and path.endswith('/SKILL.md'):
        print('true')
        sys.exit(0)

if '/hooks/config/' in path:
    print('true')
    sys.exit(0)

print('false')
" 2>/dev/null || echo "false")

    if [[ "$WHITELISTED" == "true" ]]; then
        exit 0
    fi
fi

# --- Bash command whitelist ---
if [[ "$TOOL_NAME" == "Bash" ]] && [[ -n "$COMMAND" ]]; then
    BASH_ALLOWED=$($PYTHON_CMD -c "
import sys, re, json

command = '''$COMMAND'''

# Split on shell chaining operators to validate each segment
segments = re.split(r'\s*(?:&&|\|\||;)\s*', command)

# Check for dangerous shell constructs
dangerous_patterns = [r'\\\$\(', r'\`', r'<<', r'>>', r'2>', r'<\(']

allowed_prefixes = [
    'git status', 'git diff', 'git log', 'git branch',
    'docker ps', 'docker logs', 'docker inspect',
    'gh pr list', 'gh pr view', 'gh api',
    'pytest', 'mypy', 'ruff', 'pre-commit',
    'uv run pytest', 'uv run mypy', 'uv run ruff', 'uv run pre-commit',
    'ls', 'cat', 'head', 'tail', 'grep', 'find', 'wc'
]

# Check each segment
all_safe = True
for seg in segments:
    seg = seg.strip()
    if not seg:
        continue
    seg_ok = False
    for prefix in allowed_prefixes:
        if seg == prefix or seg.startswith(prefix + ' ') or seg.startswith(prefix + '\t'):
            seg_ok = True
            break
    if not seg_ok:
        all_safe = False
        break

# Even if segments look safe, check for dangerous constructs in original command
if all_safe:
    for pat in dangerous_patterns:
        if re.search(pat, command):
            all_safe = False
            break

print('true' if all_safe else 'false')
" 2>/dev/null || echo "false")

    if [[ "$BASH_ALLOWED" == "true" ]]; then
        exit 0
    fi
fi

# --- Check for active ticket-pipeline ---
PIPELINE_ACTIVE="false"
PIPELINE_STATE_DIR="${ONEX_STATE_DIR}/pipelines"
if [[ -d "$PIPELINE_STATE_DIR" ]]; then
    PIPELINE_ACTIVE=$($PYTHON_CMD -c "
import os, sys, time, json
from pathlib import Path

state_dir = Path('$PIPELINE_STATE_DIR')
file_path = '$FILE_PATH'
now = time.time()
max_age_seconds = 1800  # 30 minutes

# Session correlation
session_id = os.environ.get('CLAUDE_SESSION_ID', '')

for state_file in state_dir.glob('*/state.yaml'):
    try:
        mtime = state_file.stat().st_mtime
        age = now - mtime

        # Recency check: must be modified within 30 minutes
        if age > max_age_seconds:
            continue

        content = state_file.read_text()

        # Check for running status
        if 'status: running' not in content and 'status: monitoring' not in content:
            continue

        # Scope check: if file is in a worktree, verify ticket match
        if file_path and '/omni_worktrees/' in file_path:
            # Extract ticket from worktree path (e.g., /omni_worktrees/OMN-1234/repo/)
            parts = file_path.split('/omni_worktrees/')
            if len(parts) > 1:
                ticket_dir = parts[1].split('/')[0]
                pipeline_dir = str(state_file.parent.name)
                if ticket_dir.startswith('OMN-') and pipeline_dir.startswith('OMN-'):
                    if ticket_dir != pipeline_dir:
                        continue  # Scope mismatch

        # Session correlation (preferred when available)
        if session_id:
            if f'session_id: {session_id}' in content:
                print('true')
                sys.exit(0)
            # In advisory/soft mode, any recent scope-matched pipeline is fine
            # (session mismatch only blocks in hard mode)

        print('true')
        sys.exit(0)
    except Exception:
        continue

print('false')
" 2>/dev/null || echo "false")
fi

if [[ "$PIPELINE_ACTIVE" == "true" ]]; then
    exit 0
fi

# --- Check for /authorize override ---
AUTH_DIR="/tmp/omniclaude-auth"
SESSION_ID="${CLAUDE_SESSION_ID:-unknown}"
if [[ -f "${AUTH_DIR}/${SESSION_ID}.json" ]]; then
    AUTH_VALID=$($PYTHON_CMD -c "
import json, sys, time
try:
    with open('${AUTH_DIR}/${SESSION_ID}.json') as f:
        auth = json.load(f)
    expires = auth.get('expires_at', 0)
    if time.time() < expires:
        print('true')
    else:
        print('false')
except Exception:
    print('false')
" 2>/dev/null || echo "false")

    if [[ "$AUTH_VALID" == "true" ]]; then
        exit 0
    fi
fi

# --- Apply policy ---
MODE="${PIPELINE_GATE_MODE:-advisory}"

WARN_MSG="No active ticket-pipeline detected. Run /design-to-plan -> /plan-to-tickets -> /ticket-pipeline first, or /authorize for emergency override."

case "$MODE" in
    advisory)
        echo "[pipeline-gate] WARNING: $WARN_MSG (advisory mode — allowing)" >> "$LOG_FILE" 2>/dev/null || true
        exit 0
        ;;
    soft)
        echo "[pipeline-gate] WARNING: $WARN_MSG (soft mode — allowing with warning)" >> "$LOG_FILE" 2>/dev/null || true
        # Output JSON for system message injection
        echo "{\"decision\": \"allow\", \"reason\": \"$WARN_MSG\"}"
        exit 0
        ;;
    hard)
        echo "[pipeline-gate] BLOCKED: $WARN_MSG (hard mode)" >> "$LOG_FILE" 2>/dev/null || true
        echo "Edit blocked: no active ticket-pipeline. Use /design-to-plan -> /plan-to-tickets -> /ticket-pipeline, or /authorize for emergency override." >&2
        exit 2
        ;;
    *)
        # Unknown mode — treat as advisory
        echo "[pipeline-gate] WARNING: Unknown mode '$MODE', treating as advisory. $WARN_MSG" >> "$LOG_FILE" 2>/dev/null || true
        exit 0
        ;;
esac
