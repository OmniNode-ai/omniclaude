#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# UserPromptSubmit Bus-Mirror Hook (OMN-16162 S1)
#
# Direct-dispatches node_event_emit_effect (omnimarket) with a
# prompt-submitted event, backgrounded so this hook never waits on a Kafka
# round-trip -- the emit node's own file-spool durability owns the actual
# publish; this hook's job is a fast, best-effort hand-off. Follows the
# exact same direct-dispatch convention as session_start_bus_mirror.sh /
# session_end_bus_mirror.sh (OMN-16162 S0).
#
# Privacy invariant (CLAUDE.md "Kafka Topics & Event Schemas"): only
# preview-safe data goes to onex.evt.* topics; the prompt-submitted record
# built here carries only a length count, never the prompt text. Full-prompt
# capture (OMN-19551) is a SEPARATE record: hook_content_capture.py, run after
# the metadata append, puts the prompt on the access-restricted
# onex.cmd.omniintelligence.* surface, scrubbed by the capture-redaction
# contract.
#
# Fail-open per the OMN-13244 baseline's own reasoning: a dead bus, a
# missing Python binary, or malformed stdin must never break or slow the
# user's session. This hook exits 0 unconditionally and emits nothing on
# stdout (UserPromptSubmit additionalContext injection is deliberately not
# used here -- this hook only mirrors to the bus).
#
# Deliberately minimal and separate from user-prompt-submit.sh (which
# remains disabled per the OMN-13244 baseline): this hook does not do
# agent routing, context injection, or any of that script's other
# responsibilities.

set -uo pipefail

_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"

_OMNICLAUDE_CALLER_CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
# shellcheck source=../lib/repo_guard.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib/repo_guard.sh" 2>/dev/null || true
if declare -F is_omninode_repo >/dev/null 2>&1; then
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$_OMNICLAUDE_CALLER_CWD}" \
        is_omninode_repo || {
        cat >/dev/null 2>/dev/null || true
        exit 0
    }
fi

# Lite mode: no bus mirroring in lite mode (generic dev tooling only).
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    # shellcheck disable=SC1090
    source "$_MODE_SH"
    if [[ "$(omniclaude_mode)" == "lite" ]]; then
        cat >/dev/null 2>/dev/null || true
        exit 0
    fi
fi
unset _MODE_SH

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"

# OMN-18704: which agent host is invoking this hook. Declared by the
# registration the host resolved -- the Codex hooks.json passes
# `--actor codex` -- and never sniffed, because a Codex hook process inherits
# its parent's environment and a Codex session started from a Claude Code
# session runs with CLAUDECODE=1 set. The allowlist lives in
# hooks/lib/hook_actor.py; this only lifts the raw value out of argv.
# shellcheck source=../lib/hook_actor.sh
source "${HOOKS_LIB}/hook_actor.sh" 2>/dev/null || true
if declare -F onex_hook_actor_arg >/dev/null 2>&1; then
    HOOK_ACTOR_ARG="$(onex_hook_actor_arg "$@")"
else
    HOOK_ACTOR_ARG="${ONEX_HOOK_ACTOR:-}"
fi

# shellcheck source=onex-paths.sh
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${ONEX_STATE_DIR:-/tmp}/hooks/logs/hook-user-prompt-submit-bus-mirror.log"
# OMN-19519: this log is appended on every event it mirrors and had no
# rotation; the helper from onex-paths.sh bounds it (sampled, never fails).
if declare -F onex_maybe_rotate_log >/dev/null 2>&1; then
    onex_maybe_rotate_log "$LOG_FILE"
fi
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Detect project root (same convention as session_start_bus_mirror.sh).
PROJECT_ROOT="${PLUGIN_ROOT}/../.."
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"
elif [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"
else
    PROJECT_ROOT="$(pwd)"
fi

# Load .env BEFORE common.sh so the KAFKA_BOOTSTRAP_SERVERS contract
# overlay (OMN-16167) is available to the backgrounded dispatch process.
# Never hardcode a broker endpoint here -- the emit node's own handler
# resolves the target from this env var.
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# OMN-16162: advisory criticality -- a missing Python interpreter must
# degrade gracefully (exit 0), not hard-fail. See common.sh's advisory
# allowlist.
export OMNICLAUDE_HOOK_CRITICALITY="advisory"

# shellcheck source=common.sh
source "${HOOKS_DIR}/scripts/common.sh" 2>/dev/null || {
    cat >/dev/null 2>/dev/null || true
    exit 0
}

# OMN-17204: apply the declared hook-edge lane AFTER common.sh.
# common.sh sources ~/.omnibase/.env and $PROJECT_ROOT/.env under `set -a`, so
# before this ticket the publish lane was whatever those files happened to say
# last -- racing ~/.claude/settings.json, which says a different lane. The
# contract (hooks/contracts/hook_edge_lane.yaml) is now the authority and this
# line is where it wins. Order is enforced by
# scripts/validation/validate_hook_edge_lane.py, not left to convention.
# shellcheck source=hook_edge_lane.sh
source "$(dirname "${BASH_SOURCE[0]}")/hook_edge_lane.sh" 2>/dev/null || true
onex_hook_gate USER_PROMPT_SUBMIT || {
    cat >/dev/null 2>/dev/null || true
    exit 0
}

INPUT="$(cat)"

if ! command -v jq >/dev/null 2>&1; then
    # No jq: cannot safely build a JSON payload. Fail-open, no emission.
    exit 0
fi
if ! echo "$INPUT" | jq -e . >/dev/null 2>&1; then
    INPUT='{}'
fi

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // .sessionId // ""' 2>/dev/null) || SESSION_ID=""
# OMN-18609: the lane a hook event belongs to is resolved from the harness's
# own spawn sidecar, keyed by agent id and located from the session transcript.
# A dispatched lane's cwd is the SESSION's directory, not its worktree, so the
# worktree registry alone resolved every record on this fleet to "unresolved".
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // .agentId // ""' 2>/dev/null) || AGENT_ID=""
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // .transcriptPath // ""' 2>/dev/null) || TRANSCRIPT_PATH=""
CWD=$(echo "$INPUT" | jq -r '.cwd // ""' 2>/dev/null) || CWD=""
[[ -z "$CWD" ]] && CWD="$(pwd)"
WORKING_DIRECTORY="$(basename "$CWD")"
# OMN-18704: Codex supplies a per-turn identifier; Claude Code does not.
# Read it host-agnostically -- absent yields the empty string, which the
# appender records as an explicit null rather than omitting the field.
TURN_ID=$(echo "$INPUT" | jq -r '.turn_id // ""' 2>/dev/null) || TURN_ID=""
# Length only -- never the prompt text itself (onex.evt.* privacy invariant).
PROMPT_LENGTH=$(echo "$INPUT" | jq -r '.prompt // "" | length' 2>/dev/null) || PROMPT_LENGTH=0
[[ "$PROMPT_LENGTH" =~ ^[0-9]+$ ]] || PROMPT_LENGTH=0

PAYLOAD=$(jq -nc \
    --arg session_id "$SESSION_ID" \
    --arg working_directory "$WORKING_DIRECTORY" \
    --argjson prompt_length "$PROMPT_LENGTH" \
    '{
        session_id: $session_id,
        working_directory: $working_directory,
        prompt_length: $prompt_length,
        hook_source: "user_prompt_submit"
    }' 2>/dev/null) || PAYLOAD='{}'
[[ -z "$PAYLOAD" || "$PAYLOAD" == "null" ]] && PAYLOAD='{}'

# OMN-17224: fast-path append. This used to invoke
# node_event_emit_effect_dispatch.py, which imported the omnimarket
# handler stack and published to Kafka inline -- 31.08s of a 31.65s
# handle() was a lazily-imported omnibase_infra chain building ~2,497
# Pydantic classes. One such process per tool call produced 14
# concurrent emitters at ~270% CPU on the operator Mac. The hook now
# only appends to the local journal (stdlib only, sub-100ms); the
# singleton drainer (launchd ai.omninode.hook-emit-drainer) pays that
# import once and publishes the backlog.
_EMIT_DISPATCH_PY="${HOOKS_LIB}/hook_emit_append.py"
if [[ -n "${PYTHON_CMD:-}" && -f "$_EMIT_DISPATCH_PY" ]]; then
    (
        "$PYTHON_CMD" "$_EMIT_DISPATCH_PY" \
            --event-type "prompt.submitted" \
            --payload "$PAYLOAD" \
            --correlation-id "${SESSION_ID:-unknown}" \
            --agent-id "$AGENT_ID" \
            --transcript-path "$TRANSCRIPT_PATH" \
            --session-id "$SESSION_ID" \
            --cwd "$CWD" \
            --actor "$HOOK_ACTOR_ARG" \
            --turn-id "$TURN_ID" \
            >>"$LOG_FILE" 2>&1
        # OMN-19551: full-content capture, AFTER the metadata append above and
        # in the same backgrounded subshell, so the content record reads the
        # turn that append just stamped. The hook input goes on stdin, never on
        # argv (a tool result can be megabytes). The module redacts through the
        # capture-redaction contract before anything is journalled, and it
        # journals nothing when the local drainer cannot publish the event
        # type or OMNICLAUDE_CONTENT_CAPTURE is off.
        _CONTENT_CAPTURE_PY="${HOOKS_LIB}/hook_content_capture.py"
        if [[ -f "$_CONTENT_CAPTURE_PY" ]]; then
            printf '%s' "$INPUT" | "$PYTHON_CMD" "$_CONTENT_CAPTURE_PY" \
                --kind prompt \
                --correlation-id "${SESSION_ID:-unknown}" \
                --agent-id "$AGENT_ID" \
                --transcript-path "$TRANSCRIPT_PATH" \
                --session-id "$SESSION_ID" \
                --cwd "$CWD" \
                --actor "$HOOK_ACTOR_ARG" \
                --turn-id "$TURN_ID" \
                >>"$LOG_FILE" 2>&1
        fi
        # OMN-19513: the lineage-carrying hook.event for this prompt, also
        # after the metadata append, so its turn id is the turn that append
        # just opened. UserPromptSubmit is the one hook the all-hooks capture
        # runs from here rather than from claude_hook_capture.sh: every other
        # hook reads the current turn, and only this one would race the
        # allocation.
        _HOOK_CAPTURE_PY="${HOOKS_LIB}/hook_claude_capture.py"
        if [[ -f "$_HOOK_CAPTURE_PY" ]]; then
            printf '%s' "$INPUT" | "$PYTHON_CMD" "$_HOOK_CAPTURE_PY" \
                --actor "$HOOK_ACTOR_ARG" \
                >>"$LOG_FILE" 2>&1
        fi
    # The whole subshell's descriptors go to the log. With two commands in it,
    # bash keeps the subshell alive, and an inherited stdout or stderr pipe
    # would hold the hook's caller until both finished (OMN-19551).
    ) >>"$LOG_FILE" 2>&1 </dev/null &
    disown 2>/dev/null || true
fi

exit 0
