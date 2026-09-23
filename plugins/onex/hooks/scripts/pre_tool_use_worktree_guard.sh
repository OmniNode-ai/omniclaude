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

# Portable Plugin Configuration
# Resolve absolute path of this script, handling relative invocation (e.g. ./pre_tool_use_worktree_guard.sh).
# Falls back to python3 if realpath is unavailable (non-GNU macOS without coreutils).
# Resolved BEFORE any `cd`: BASH_SOURCE[0] may be relative [OMN-19047].
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; p=os.path.realpath(sys.argv[1]); print(p) if os.path.exists(p) else sys.exit(1)" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"

# Ensure stable CWD before any Python invocation.
# The session CWD may be on an external drive that disconnects/remounts;
# Python's <frozen getpath> calls os.getcwd() during startup and crashes
# with "failed to make path absolute" if the CWD is unavailable.
# Absolute script directory, resolved while the caller's CWD is still in
# effect. BASH_SOURCE[0] may be relative, so a sibling sourced after the
# cd below cannot be found through it [OMN-19047].
HOOK_SCRIPT_DIR="${HOOK_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

cd "$HOME" 2>/dev/null || cd /tmp || true
source "${HOOK_SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true
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
# Worktree path enforcement (OMN-7018, OMN-9896, OMN-9906, OMN-19229, OMN-19123)
#
# The decision is made by ../lib/worktree_add_guard.py, which reads the
# command the way the shell and git do: it splits words with their quoting,
# skips comments, here-document bodies and redirections, expands $NAME,
# ${NAME} and ~ from this environment plus assignments earlier in the same
# command, follows `cd` and every `git -C <dir>`, consumes the values of
# -b/-B/--reason, honours `--`, and resolves a relative destination against
# the directory git runs in. It refuses, fail-closed, a destination outside
# the canonical root and one it cannot resolve (an unset variable, command
# substitution, which it never executes, an unknown option). The token loop
# it replaces took the first non-dash word after `add`, so the value of -b,
# an unexpanded "$WT" or a `2>&1` was judged as the path, and it never saw
# the `git -C <dir> worktree add` form at all.
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
_block() {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] BLOCKED: $1: $2" >> "$LOG_FILE"
    _hook_status "BLOCKED" "$1" "0"
    hook_record_refusal "$1" "$2" 2>/dev/null || true
    jq -n --arg reason "$2" '{"decision": "block", "reason": $reason}'
    trap - EXIT
    exit 2
}

CMD=$(echo "$TOOL_INFO" | jq -er '.tool_input.command // empty' 2>/dev/null || true)
# Cheap OVER-matching pre-filter: it decides nothing. Quoted text is kept,
# because a `bash -c '...'` script is quoted and is judged too.
if printf '%s' "$CMD" | grep -qE 'worktree[^[:alnum:]]+add'; then
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
        CANONICAL_ROOT=""
    fi

    GUARD_PY="${HOOKS_DIR}/lib/worktree_add_guard.py"
    if [[ ! -f "$GUARD_PY" ]]; then
        _block "decision core missing" \
            "BLOCKED: the worktree guard's decision core is missing at ${GUARD_PY}, so this \`git worktree add\` cannot be judged. Repair the plugin install, or disable the guard deliberately: onex hooks disable WORKTREE_GUARD"
    fi
    _rc=0
    GUARD_OUT=$(printf '%s' "$TOOL_INFO" \
        | "$PYTHON_CMD" "$GUARD_PY" --root "$CANONICAL_ROOT" --cwd "$HOOK_ORIGINAL_CWD" \
        2>>"$LOG_FILE") || _rc=$?
    if [[ "$_rc" -eq 2 ]]; then
        _reason=$(printf '%s' "$GUARD_OUT" | jq -r '.reason // empty' 2>/dev/null || true)
        _block "worktree add refused" \
            "${_reason:-BLOCKED: the worktree guard refused this command but its reason could not be read. To disable this guard: onex hooks disable WORKTREE_GUARD}"
    elif [[ "$_rc" -ne 0 ]]; then
        _block "worktree guard failed" \
            "BLOCKED: the worktree guard's decision core exited ${_rc}, so this \`git worktree add\` could not be judged; an unjudged worktree destination is refused. To disable this guard: onex hooks disable WORKTREE_GUARD"
    fi
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Worktree add ALLOWED: ${GUARD_OUT:-no destination created}" >> "$LOG_FILE"
fi

# ------------------------------------------------------------------
# Default — ALLOW
# ------------------------------------------------------------------
_hook_status "PASS" "worktree guard check complete" "0"
echo "$TOOL_INFO"
exit 0
