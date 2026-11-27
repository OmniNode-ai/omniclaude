#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Delegation Hook (OMN-10607, OMN-23413): PreToolUse Agent/Task and UserPromptSubmit
#
# An Agent/Task call goes through the delegation pipeline (SensitivityGate →
# TaskClassifier → omnimarket node_hook_delegate_effect). When it is answered,
# the runner's last line is the node's PreToolUse deny, whose reason is the
# answer, printed as this hook's output (OMN-26688); an older node's plain answer
# is blocked with exit 2 as before. Otherwise exit 0 and the original tool proceeds. Every prompt (AC33) goes to the node's prompt
# handler, and the runner prints this hook's whole output: a "block" carrying
# the delegated answer, context for Claude, or nothing.
#
# Hook registration: hooks-delegation.v1.json, PreToolUse "^(Agent|Task)$" and
# UserPromptSubmit. One switch: POST_SKILL_DELEGATION_ENFORCER (bit 11).

set -euo pipefail
# ONEX_DELEGATION_HOOK (prompts | subagents) labels each registration in Claude
# Code's settings and in this log, without a second script (OMN-23413).
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")${ONEX_DELEGATION_HOOK:+[${ONEX_DELEGATION_HOOK}]}"

# Resolve paths before cd $HOME
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/error-guard.sh" 2>/dev/null || true

TOOL_INFO=$(cat)
if ! command -v jq >/dev/null 2>&1; then
    # Without jq the event cannot be read. A prompt hook's stdout becomes
    # Claude's context, so anything that may be a prompt prints nothing: echoing
    # it would put the whole hook envelope (prompt, transcript path) into the
    # conversation. A tool call still passes through by echoing its input.
    [[ "$TOOL_INFO" == *UserPromptSubmit* ]] || printf '%s\n' "$TOOL_INFO"
    exit 0
fi
TOOL_NAME=$(printf '%s\n' "$TOOL_INFO" | jq -r '.tool_name // ""' 2>/dev/null) || TOOL_NAME=""
EVENT_NAME=$(printf '%s\n' "$TOOL_INFO" | jq -r '.hook_event_name // "PreToolUse"' 2>/dev/null) || EVENT_NAME="PreToolUse"
# A tool call passes through by echoing its input. A prompt hook's plain stdout
# becomes Claude's context, so a prompt that passes through prints nothing (AC33).
pass_through() { [[ "$EVENT_NAME" == "UserPromptSubmit" ]] || printf '%s\n' "$TOOL_INFO"; exit 0; }
# A disabled prompt is still a new turn. Reset accepted answers without
# classification or inference so re-enabling cannot reuse an older turn.
RESET_ONLY=0
pass_or_reset() { if [[ "$EVENT_NAME" == "UserPromptSubmit" ]]; then RESET_ONLY=1; else pass_through; fi; }

# A customer install (OMN-22498): scripts/install-delegation.sh --apply writes
# ~/.omninode/delegation/hooks-delegation.json, and only that installer
# registers this hook outside the plugin tree. Its presence is the customer's
# opt-in, so the repo guard and the lite default below, which keep the plugin
# quiet in other people's repos, do not silence a hook the customer installed
# on purpose. The hook bit still decides.
_OMNICLAUDE_CALLER_CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
# shellcheck source=../lib/repo_guard.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib/repo_guard.sh" 2>/dev/null || true
if [[ ! -f "${HOME}/.omninode/delegation/hooks-delegation.json" ]] && declare -F is_omninode_repo >/dev/null 2>&1; then
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$_OMNICLAUDE_CALLER_CWD}" \
        is_omninode_repo || pass_or_reset
fi
# The one switch (OMN-22498): `onex hooks disable POST_SKILL_DELEGATION_ENFORCER`
# turns Claude Code delegation off. The bit (11, 0x800) is BORROWED, as Jake
# ruled on OMN-22498 (2026-11-09): EnumHookBit in omnibase_core has every
# default ordinal allocated, the same reason pre_tool_use_agent_model_guard.sh
# borrows PRE_TOOL_AGENT_DISPATCH_GATE. Bit 11 already governs the delegation
# family (post-skill-delegation-enforcer.sh). The old name here,
# PRE_TOOL_USE_DELEGATION, is not a hook bit, and onex_hook_gate passes an
# unknown name, so nothing could switch this hook off.
if ! onex_hook_gate POST_SKILL_DELEGATION_ENFORCER; then
    pass_or_reset
fi

cd "$HOME" 2>/dev/null || cd /tmp || true

# Kill switch
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" || "${PRE_TOOL_DELEGATION_DISABLED:-0}" == "1" ]]; then
    pass_or_reset
fi

# Lite mode guard [OMN-5398]; a customer install is not silenced by it (OMN-22498).
_MODE_SH="${SCRIPT_DIR}/../../lib/mode.sh"
if [[ ! -f "${HOME}/.omninode/delegation/hooks-delegation.json" && -f "$_MODE_SH" ]]; then
    source "$_MODE_SH"
    if [[ "$(omniclaude_mode)" == "lite" ]]; then
        pass_or_reset
    fi
fi
unset _MODE_SH

source "${SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${ONEX_STATE_DIR:-/tmp}/hooks/logs/pre-tool-delegation.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

TIMESTAMP="$(date -u +%FT%TZ)"

# One switch covers prompts and subagent tasks. Other tool calls pass through.
if [[ "$EVENT_NAME" != "UserPromptSubmit" && "$TOOL_NAME" != "Agent" && "$TOOL_NAME" != "Task" ]]; then
    pass_through
fi

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
HOOKS_LIB="${PLUGIN_ROOT}/hooks/lib"
RUNNER="${HOOKS_LIB}/delegation_hook_runner.py"

# Resolve Python (same chain as common.sh, without sourcing it to avoid side effects)
PYTHON_CMD=""
if [[ -n "${PLUGIN_PYTHON_BIN:-}" && -f "${PLUGIN_PYTHON_BIN}" && -x "${PLUGIN_PYTHON_BIN}" ]]; then
    PYTHON_CMD="${PLUGIN_PYTHON_BIN}"
elif [[ -n "${CLAUDE_PLUGIN_DATA:-}" && -x "${CLAUDE_PLUGIN_DATA}/.venv/bin/python3" ]]; then
    PYTHON_CMD="${CLAUDE_PLUGIN_DATA}/.venv/bin/python3"
else
    _repo_root="$(cd "${PLUGIN_ROOT}/../.." 2>/dev/null && pwd)" || _repo_root=""
    if [[ -n "$_repo_root" && -x "${_repo_root}/.venv/bin/python3" ]]; then
        PYTHON_CMD="${_repo_root}/.venv/bin/python3"
    elif [[ -n "${ONEX_REGISTRY_ROOT:-}" && -x "${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3" ]]; then
        PYTHON_CMD="${ONEX_REGISTRY_ROOT}/omniclaude/.venv/bin/python3"
    fi
    unset _repo_root
fi

if [[ -z "$PYTHON_CMD" ]]; then
    echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] WARN: no Python found, passing through" >> "$LOG_FILE" 2>/dev/null || true
    pass_through
fi

if [[ ! -f "$RUNNER" ]]; then
    echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] WARN: runner not found at ${RUNNER}, passing through" >> "$LOG_FILE" 2>/dev/null || true
    pass_through
fi

# Run the delegation runner with tool input on stdin. It delegates the task with
# onex delegate within ONEX_HOOK_DELEGATE_TIMEOUT_S (default 240 s); the alarm
# allows 30 s more. perl's alarm, not `timeout`: macOS ships no `timeout` (GNU
# coreutils), and a missing one made every call exit 127 (OMN-23413).
set +e
DELEGATION_RESULT=$(printf '%s\n' "$TOOL_INFO" | \
    perl -e "alarm $(( ${ONEX_HOOK_DELEGATE_TIMEOUT_S:-240} + 30 )); exec @ARGV or exit 127" env -u PYTHONPATH ONEX_HOOK_RESET_ONLY="$RESET_ONLY" ONEX_HOOK_DELEGATE_TIMEOUT_S="${ONEX_HOOK_DELEGATE_TIMEOUT_S:-240}" "$PYTHON_CMD" "$RUNNER" 2>>"$LOG_FILE")
RUNNER_EXIT=$?
set -e

if [[ "$EVENT_NAME" == "UserPromptSubmit" ]]; then
    # OMN-23413 AC33: the runner printed this hook's whole output and logged why
    # on stderr. decision "block" stops Claude Code before any model call. A
    # disabled or failed run prints nothing.
    [[ $RUNNER_EXIT -ne 0 || "$RESET_ONLY" == "1" ]] || printf '%s' "$DELEGATION_RESULT"
    echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] PROMPT runner_exit=${RUNNER_EXIT} reset_only=${RESET_ONLY}" >> "$LOG_FILE" 2>/dev/null || true
    exit 0
fi

if [[ $RUNNER_EXIT -ne 0 ]]; then
    echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] WARN: runner exited ${RUNNER_EXIT}, passing through" >> "$LOG_FILE" 2>/dev/null || true
    pass_through
fi

# Check if delegation was approved
if [[ "$DELEGATION_RESULT" == DELEGATED:* ]]; then
    echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] BLOCK tool=${TOOL_NAME} agent=$(printf '%s\n' "$TOOL_INFO" | jq -r '.tool_input.name // .tool_input.subagent_type // "(unnamed)"' 2>/dev/null || echo "(unnamed)") result=${DELEGATION_RESULT}" >> "$LOG_FILE" 2>/dev/null || true
    [[ "${DELEGATION_RESULT##*$'\n'}" == "{\"hookSpecificOutput\""* ]] && { printf '%s\n' "${DELEGATION_RESULT##*$'\n'}"; exit 0; }
    printf '%s\n' "$TOOL_INFO"
    echo "DELEGATION RESULT: ${DELEGATION_RESULT}" >&2
    trap - EXIT 2>/dev/null || true
    exit 2
fi

# Not delegatable — pass through
echo "[$TIMESTAMP] [$_OMNICLAUDE_HOOK_NAME] PASS tool=${TOOL_NAME} result=$(printf '%s\n' "$DELEGATION_RESULT" | head -n 1)" >> "$LOG_FILE" 2>/dev/null || true
pass_through
