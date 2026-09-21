#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Prose-sink backtick command-substitution admission gate (OMN-18750).
#
# Inside a double-quoted shell string a backtick pair is command substitution.
# Markdown uses backticks to quote a command name. When a lane writes a note
# ABOUT a command into a ledger, a checkpoint, a pull-request body or a commit
# message, the shell runs the command the note is quoting.
#
# Measured twice on 2026-09-18. Both lanes wrote `uv run onex` inside a
# double-quoted echo appending to a checkpoint; both tool calls came back with
# "Failed to spawn: onex", the quoted words were dropped from the note, and the
# error read as a broken PostToolUse hook until every hook in the plugin had
# been run against a fixture payload.
#
# This wrapper decides nothing. It pre-filters on the presence of a backtick,
# then hands the payload to lib/prose_command_substitution_guard.py, which
# walks the command's quote state. Patterned on the OMN-17334 git-stash guard.
#
# Gate bit: BASH_GUARD (this is a PreToolUse Bash admission gate; it does not
#           mint a new bit).
#   Disable with: onex hooks disable BASH_GUARD

set -euo pipefail

# error-guard.sh sources hook-gate.sh, which supplies onex_hook_gate and
# _hook_status without common.sh. common.sh is deliberately NOT sourced: its
# find_python() hard-fails with `exit 1` when no venv is present, and the
# error-guard EXIT trap would convert that into `exit 0` -- a silent
# fail-OPEN. The decision core is standard-library-only precisely so this
# guard can resolve an interpreter itself and refuse when it cannot.
#
# Sourcing this is load-bearing, not cosmetic: without onex_hook_gate in
# scope, `if ! onex_hook_gate BASH_GUARD` takes the DISABLED branch on a
# command-not-found, and the guard no-ops on every call while reporting
# nothing -- the exact hook shape OMN-18750 exists to stop shipping.
# shellcheck source=./error-guard.sh
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Resolve this script's own directory BEFORE any cd: BASH_SOURCE may be
# relative, and resolving it afterwards lands in the wrong tree.
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
GUARD_PY="${SCRIPT_DIR}/../lib/prose_command_substitution_guard.py"
unset _SELF

# The decision depends on the command text alone, never on this script's CWD,
# so a stability cd is safe.
cd "$HOME" 2>/dev/null || cd /tmp || true

_CALLER_HOOK_LOG="${ONEX_HOOK_LOG:-}"
# shellcheck source=./onex-paths.sh
source "${SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${_CALLER_HOOK_LOG:-${ONEX_HOOK_LOG:-${HOME}/.claude/onex-hooks.log}}"
unset _CALLER_HOOK_LOG
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

_log() {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] prose-substitution-guard: $*" >> "$LOG_FILE" 2>/dev/null || true
}

if ! onex_hook_gate BASH_GUARD; then
    _log "DISABLED: BASH_GUARD is cleared in ONEX_HOOKS_MASK, so this command was not evaluated for a prose-sink command substitution. Re-enable with: onex hooks enable BASH_GUARD"
    cat >/dev/null
    exit 0
fi

_block() {
    # OMN-18946: a refusal reaches an aggregated surface, not only this
    # turn's terminal and a log nobody reads. Backgrounded and fail-open.
    hook_record_refusal "$1" "$2" 2>/dev/null || true
    _hook_status "BLOCKED" "$1" "0" 2>/dev/null || true
    _log "BLOCKED: $1"
    jq -n --arg reason "$2" '{"decision": "block", "reason": $reason}' 2>/dev/null \
        || printf '{"decision": "block", "reason": %s}\n' "$(printf '%s' "$2" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    trap - EXIT
    exit 2
}

TOOL_INFO=$(cat)

# Cheap OVER-matching pre-filter. It decides nothing. A command with no
# backtick cannot carry a backtick substitution, so it never pays for an
# interpreter start.
case "$TOOL_INFO" in
    *'`'*) : ;;
    *)
        _hook_status "PASS" "no backtick in payload" "0" 2>/dev/null || true
        exit 0
        ;;
esac

if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null); then
    _block "unparseable hook JSON carrying a backtick" \
        "BLOCKED: the PreToolUse payload for this Bash call carries a backtick but is not readable JSON, so the guard cannot tell whether a command substitution sits inside quoted prose (OMN-18750). An unverifiable payload is refused, never assumed safe. To disable this guard: onex hooks disable BASH_GUARD"
fi

if [[ "$TOOL_NAME" != "Bash" ]]; then
    _hook_status "PASS" "not a Bash call ($TOOL_NAME)" "0" 2>/dev/null || true
    exit 0
fi

if [[ ! -f "$GUARD_PY" ]]; then
    _block "decision core missing" \
        "BLOCKED: the OMN-18750 prose-substitution admission gate is missing at ${GUARD_PY}, so this command's backticks cannot be judged. Repair the plugin install, or disable the guard deliberately: onex hooks disable BASH_GUARD"
fi

_resolve_python() {
    if [[ -n "${PLUGIN_PYTHON_BIN:-}" && -x "${PLUGIN_PYTHON_BIN}" ]]; then
        echo "${PLUGIN_PYTHON_BIN}"
        return 0
    fi
    if [[ -n "${CLAUDE_PLUGIN_DATA:-}" && -x "${CLAUDE_PLUGIN_DATA}/.venv/bin/python3" ]]; then
        echo "${CLAUDE_PLUGIN_DATA}/.venv/bin/python3"
        return 0
    fi
    local repo_venv
    repo_venv="$(cd "${PLUGIN_ROOT}/../.." 2>/dev/null && pwd)/.venv/bin/python3"
    if [[ -x "$repo_venv" ]]; then
        echo "$repo_venv"
        return 0
    fi
    local brew_py
    for brew_py in /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13; do  # public-skill-ok: canonical brew interpreter path, CLAUDE.md rule 11 precedent
        if [[ -x "$brew_py" ]]; then
            echo "$brew_py"
            return 0
        fi
    done
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return 0
    fi
    return 1
}

if ! GUARD_PYTHON="$(_resolve_python)"; then
    _block "no python interpreter" \
        "BLOCKED: no Python interpreter could be resolved to run the OMN-18750 prose-substitution admission gate, so this command cannot be checked. Repair the plugin install, or disable the guard deliberately: onex hooks disable BASH_GUARD"
fi

set +e
GUARD_OUT=$(printf '%s' "$TOOL_INFO" | env -u PYTHONPATH OMNI_HOME="${OMNI_HOME:-}" "$GUARD_PYTHON" "$GUARD_PY" 2>&1)
GUARD_RC=$?
set -e

if [[ $GUARD_RC -eq 0 ]]; then
    GUARD_NOTES=$(printf '%s' "$GUARD_OUT" | tail -n 1 \
        | jq -r 'select(type == "object") | .notes // [] | join(" | ")' 2>/dev/null || true)
    if [[ -n "$GUARD_NOTES" ]]; then
        _log "$GUARD_NOTES"
    fi
    _hook_status "PASS" "no prose-sink command substitution in this command" "0" 2>/dev/null || true
    exit 0
fi

if [[ $GUARD_RC -eq 2 ]]; then
    REASON=$(printf '%s' "$GUARD_OUT" | jq -r '.reason // empty' 2>/dev/null || true)
    if [[ -z "$REASON" ]]; then
        REASON="BLOCKED: this command writes prose carrying an unescaped backtick command substitution, which the shell will execute (OMN-18750), and the guard's own detail payload was unreadable."
    fi
    _block "prose-sink command substitution" "$REASON"
fi

_block "guard evaluation failed (rc=${GUARD_RC})" \
    "BLOCKED: the OMN-18750 prose-substitution admission gate could not evaluate this Bash command (exit ${GUARD_RC}), so whether it executes a command out of its own prose is unknown and the command is refused. Detail: $(printf '%s' "$GUARD_OUT" | head -c 400). To disable this guard deliberately: onex hooks disable BASH_GUARD"
