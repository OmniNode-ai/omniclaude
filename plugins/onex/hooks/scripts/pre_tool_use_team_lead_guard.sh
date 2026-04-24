#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Team-Lead Foreground Guard (OMN-7843)
#
# When the current session is the team lead of a team with one or more
# non-lead members, block foreground tool calls (Read/Edit/Write/Bash/Glob/Grep)
# so the lead delegates via SendMessage / Agent / TaskCreate instead.
#
# Bypass paths (all documented in lib/team_lead_foreground_guard.py):
#   1. ONEX_TEAM_LEAD_GUARD_DISABLE=1 — hard kill-switch (env)
#   2. ~/.claude/omniclaude-team-lead-guard-disabled — file-marker kill-switch
#   3. TEAM_LEAD_FOREGROUND_BLOCK is unset (guard is opt-in; default OFF)
#   4. CLAUDE_AGENT_ID is set — subagents bypass unconditionally
#   5. No active team, or team has only the lead as a member
#
# Pattern mirrors pre_tool_use_overseer_foreground_block.sh.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Resolve script location BEFORE changing cwd — BASH_SOURCE may be relative.
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR

# Ensure stable CWD before any Python invocation.
cd "$HOME" 2>/dev/null || cd /tmp || true
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${ONEX_HOOK_LOG:-/tmp/onex-hooks.log}"

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Read stdin once so we can echo the original payload on fail-open paths.
TOOL_INFO=$(cat)

# Parse tool name — fail open on bad JSON.
TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null) || {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ERROR: invalid hook JSON; failing open" >> "$LOG_FILE" 2>/dev/null || true
    echo "$TOOL_INFO"
    exit 0
}

# Fast pre-flight: kill-switch OR guard disabled OR subagent → skip Python entirely.
# This keeps the hot path under 1ms on every PreToolUse that doesn't need checks.
if [[ "${ONEX_TEAM_LEAD_GUARD_DISABLE:-}" == "1" ]] \
   || [[ "${ONEX_TEAM_LEAD_GUARD_DISABLE:-}" == "true" ]] \
   || [[ -f "$HOME/.claude/omniclaude-team-lead-guard-disabled" ]] \
   || [[ "${TEAM_LEAD_FOREGROUND_BLOCK:-}" != "true" && "${TEAM_LEAD_FOREGROUND_BLOCK:-}" != "1" && "${TEAM_LEAD_FOREGROUND_BLOCK:-}" != "yes" ]] \
   || [[ -n "${CLAUDE_AGENT_ID:-}" ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Only the BLOCK_TOOLS set triggers the Python check. Matcher in hooks.json
# scopes this further, but a belt-and-braces check here keeps the guard cheap
# if the matcher ever drifts.
if [[ ! "$TOOL_NAME" =~ ^(Read|Edit|Write|Bash|Glob|Grep)$ ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Locate Python. The guard module uses only stdlib — any Python 3.10+ works.
# We intentionally DO NOT source common.sh: its strict venv discovery path can
# hard-exit when the plugin venv isn't materialised, which would convert this
# hook from fail-open to fail-closed. Stdlib-only means plain python3 is safe.
PYTHON_CMD="${PLUGIN_PYTHON_BIN:-python3}"

# Run Python guard.
set +e
RESULT=$(echo "$TOOL_INFO" | \
    CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" \
    $PYTHON_CMD "${HOOKS_LIB}/team_lead_foreground_guard.py" 2>>"$LOG_FILE")
EXIT_CODE=$?
set -e

if [[ $EXIT_CODE -eq 2 ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED $TOOL_NAME: team-lead foreground guard fired" >> "$LOG_FILE" 2>/dev/null || true
    printf '\a' >&2
    echo "$RESULT"
    trap - EXIT
    exit 2
elif [[ $EXIT_CODE -eq 0 ]]; then
    # Guard allowed. Emit the original payload (Python prints "{}" on allow).
    echo "$TOOL_INFO"
    exit 0
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ERROR: guard failed with code $EXIT_CODE, failing open" >> "$LOG_FILE" 2>/dev/null || true
    echo "$TOOL_INFO"
    exit 0
fi
