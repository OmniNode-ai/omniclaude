#!/bin/bash
# PreToolUse Worktree Guard Hook - Portable Plugin Version
#
# Dedicated, minimally-scoped extraction (OMN-14330) of the OMN-7018
# canonical-worktree-root enforcement from pre_tool_use_bash_guard.sh /
# bash_guard.py. This script intercepts ONLY `git worktree add` Bash
# invocations and blocks any that target a path outside the canonical
# $OMNI_HOME/omni_worktrees/<ticket>/<repo>/ root. It does not perform any
# of bash_guard.py's other checks (destructive-command HARD_BLOCK,
# `--no-verify` enforcement, `gh pr merge` method-mismatch blocking,
# required-review-count blocking, SOFT_ALERT, CONTEXT_ADVISORY) — those
# remain unregistered under the OMN-13244 measurement baseline. Mirrors the
# OMN-13856 Done-flip-guard carve-out precedent: one targeted script, one
# targeted hooks.json entry, everything else stays off.
#
# Root cause this closes: OMN-13244 gutted hooks.json to {}, which silently
# disabled the OMN-7018 worktree-add canonical-root check. With no hook
# registered, `git worktree add` could land anywhere, including directly
# inside a canonical clone under omni_home/ — see handoff §6 (~200 duplicate
# commits landed in the omniclaude canonical clone while the guard was off).
#
# Scope note: this restores the `git worktree add` canonical-root check —
# the actual existing OMN-7018 guarantee. It does not intercept a raw
# `git checkout -b` / `git commit` run with CWD already inside a canonical
# clone; that is a different, currently-unimplemented protection.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"

_OMNICLAUDE_CALLER_CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
# shellcheck source=../lib/repo_guard.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib/repo_guard.sh" 2>/dev/null || true
if declare -F is_omninode_repo >/dev/null 2>&1; then
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$_OMNICLAUDE_CALLER_CWD}" \
        is_omninode_repo || {
        _OMNICLAUDE_PASSTHROUGH=$(cat)
        echo "$_OMNICLAUDE_PASSTHROUGH"
        trap - EXIT 2>/dev/null || true
        exit 0
    }
fi
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true
HOOK_ORIGINAL_CWD="$(pwd -P 2>/dev/null || pwd)"

# Ensure stable CWD before any Python invocation.
# The session CWD may be on an external drive that disconnects/remounts;
# Python's <frozen getpath> calls os.getcwd() during startup and crashes
# with "failed to make path absolute" if the CWD is unavailable.
cd "$HOME" 2>/dev/null || cd /tmp || true

# Portable Plugin Configuration
# Resolve absolute path of this script, handling relative invocation (e.g. ./pre_tool_use_worktree_guard.sh).
# Falls back to python3 if realpath is unavailable (non-GNU macOS without coreutils).
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${ONEX_HOOK_LOG}"

# Detect project root
PROJECT_ROOT="${PLUGIN_ROOT}/../.."
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"
elif [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"
else
    PROJECT_ROOT="$(pwd)"
fi

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Load environment variables (picks up OMNI_HOME / ONEX_WORKTREES_ROOT overrides)
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# Source shared functions (provides PYTHON_CMD, onex_hook_gate, _hook_status)
source "${HOOKS_DIR}/scripts/common.sh"
onex_hook_gate WORKTREE_GUARD || exit 0

# Read stdin
TOOL_INFO=$(cat)
if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>>"$LOG_FILE"); then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: invalid hook JSON; failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Worktree guard hook invoked for tool: $TOOL_NAME" >> "$LOG_FILE"

# Only intercept Bash tool invocations
if [[ "$TOOL_NAME" != "Bash" ]]; then
    _hook_status "PASS" "not Bash ($TOOL_NAME)" "0"
    echo "$TOOL_INFO"
    exit 0
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Checking Bash command for worktree-add canonical-root violations" >> "$LOG_FILE"

# ---------------------------------------------------------------------------
# Worktree path enforcement (OMN-7018, OMN-9896, OMN-9906)
#
# Phase 1: supports only common `git worktree add <path> [-b <branch>]` form.
# Unsupported flag/order variants (--lock, --detach, flags before path) trigger
# conservative block until argument parsing is hardened.
#
# Configuration:
#   ONEX_HOOKS_MASK   clear WORKTREE_GUARD bit -> this entire script is gated
#                     off at the top (onex_hook_gate WORKTREE_GUARD above).
#                     Use: onex hooks disable WORKTREE_GUARD
#                     Use this if you are running this plugin outside the
#                     OmniNode workspace (alpha testers, non-OmniNode work).
#   ONEX_WORKTREES_ROOT   absolute path   -> override canonical worktree root.
#   OMNI_WORKTREES_DIR    absolute path   -> legacy alias (Python guard parity).
#   OMNI_HOME             absolute path   -> required when neither override is
#                         set; canonical root resolves to "$OMNI_HOME/omni_worktrees".
#                         Fail-fast: missing OMNI_HOME with no override blocks
#                         with an actionable error rather than silently picking
#                         a wrong default (omni_home CLAUDE.md rule #8).
# ---------------------------------------------------------------------------
CMD=$(echo "$TOOL_INFO" | jq -er '.tool_input.command // empty' 2>/dev/null || true)
# Strip single- and double-quoted strings before checking for git worktree add
# to avoid false positives on commit messages, grep patterns, etc.
CMD_UNQUOTED=$(echo "$CMD" | sed -E "s/\"([^\"\\\\]|\\\\.)*\"//g; s/'[^']*'//g")
if echo "$CMD_UNQUOTED" | grep -qE 'git\s+worktree\s+add'; then
    # Extract the first non-flag argument after "add" as the path.
    # Strip only backslash+newline continuations (not all backslashes) so
    # multi-line commands parse cleanly without corrupting path characters.
    # Use Python for the substitution — macOS sed doesn't support \n in patterns.
    CMD_FLAT=$(printf '%s' "$CMD" \
        | "$PYTHON_CMD" -c "import sys; print(sys.stdin.read().replace('\\\\\n', ' ').replace('\n', ' '))" \
        2>/dev/null || printf '%s' "$CMD" | tr '\n' ' ')
    WORKTREE_PATH=""
    _in_add=false
    for _token in $CMD_FLAT; do
        if [[ "$_in_add" == "true" && "$_token" != -* && -n "$_token" ]]; then
            WORKTREE_PATH="$_token"
            break
        fi
        [[ "$_token" == "add" ]] && _in_add=true
    done

    # Resolve canonical worktree root. Order:
    #   1. ONEX_WORKTREES_ROOT (explicit override)
    #   2. OMNI_WORKTREES_DIR (legacy alias; mirrors Python bash_guard.py)
    #   3. $OMNI_HOME/omni_worktrees (fail-fast on unset OMNI_HOME)
    if [[ -n "${ONEX_WORKTREES_ROOT:-}" ]]; then
        CANONICAL_ROOT="${ONEX_WORKTREES_ROOT%/}"
    elif [[ -n "${OMNI_WORKTREES_DIR:-}" ]]; then
        CANONICAL_ROOT="${OMNI_WORKTREES_DIR%/}"
    elif [[ -n "${OMNI_HOME:-}" ]]; then
        CANONICAL_ROOT="${OMNI_HOME%/}/omni_worktrees"
    else
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] BLOCKED: cannot resolve worktree root — OMNI_HOME unset and no ONEX_WORKTREES_ROOT override" >> "$LOG_FILE"
        _hook_status "BLOCKED" "worktree root unresolvable (OMNI_HOME unset)" "0"
        jq -n --arg reason "BLOCKED: cannot resolve canonical worktree root. Set OMNI_HOME (preferred), set ONEX_WORKTREES_ROOT, or disable this guard by clearing the WORKTREE_GUARD bit: onex hooks disable WORKTREE_GUARD" \
            '{"decision": "block", "reason": $reason}'
        trap - EXIT
        exit 2
    fi

    if [[ -z "$WORKTREE_PATH" ]]; then
        # Could not parse path — fail closed
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] BLOCKED: Could not parse worktree path from command" >> "$LOG_FILE"
        _hook_status "BLOCKED" "worktree path unparseable" "0"
        jq -n --arg reason "BLOCKED: Could not parse worktree path from command. Use: git worktree add <path> [-b <branch>]. To disable this guard: onex hooks disable WORKTREE_GUARD" \
            '{"decision": "block", "reason": $reason}'
        trap - EXIT
        exit 2
    fi

    NORMALIZED_ROOT="$("$PYTHON_CMD" -c 'import os, sys; print(os.path.abspath(os.path.normpath(sys.argv[1])))' "$CANONICAL_ROOT")"
    NORMALIZED_WORKTREE="$("$PYTHON_CMD" -c 'import os, sys; base, path = sys.argv[1:3]; target = path if os.path.isabs(path) else os.path.join(base, path); print(os.path.abspath(os.path.normpath(target)))' "$HOOK_ORIGINAL_CWD" "$WORKTREE_PATH")"

    if [[ "$NORMALIZED_WORKTREE" != "$NORMALIZED_ROOT"/* ]]; then
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] BLOCKED: Worktree path outside canonical root: $NORMALIZED_WORKTREE" >> "$LOG_FILE"
        _hook_status "BLOCKED" "worktree path outside canonical root" "0"
        jq -n --arg reason "BLOCKED: Worktrees must be created under $NORMALIZED_ROOT. Got: $NORMALIZED_WORKTREE. To use a different root set ONEX_WORKTREES_ROOT, or to disable this guard: onex hooks disable WORKTREE_GUARD" \
            '{"decision": "block", "reason": $reason}'
        trap - EXIT
        exit 2
    fi

    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Worktree add ALLOWED (canonical root match)" >> "$LOG_FILE"
fi

# ------------------------------------------------------------------
# Default — ALLOW
# ------------------------------------------------------------------
_hook_status "PASS" "worktree guard check complete" "0"
echo "$TOOL_INFO"
exit 0
