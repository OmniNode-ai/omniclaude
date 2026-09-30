#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Append the skill lifecycle start at the actual PreToolUse boundary.
#
# The matching completion is emitted by post-tool-use-quality.sh after Claude
# returns. Both records use Claude's tool_use_id as their invocation key; this
# hook never invents a timestamp or a run identifier.

set -uo pipefail

# OMN-20109: this script's directory, resolved once without a dirname exec.
_ONEX_HOOK_SELF_DIR="${BASH_SOURCE[0]%/*}"; [[ "${BASH_SOURCE[0]}" == */* ]] || _ONEX_HOOK_SELF_DIR=.; [[ -n "$_ONEX_HOOK_SELF_DIR" ]] || _ONEX_HOOK_SELF_DIR=/
_OMNICLAUDE_HOOK_NAME="${BASH_SOURCE[0]##*/}"
_SCRIPT_DIR="$(cd "${_ONEX_HOOK_SELF_DIR}" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${ONEX_STATE_DIR:-/tmp}/hooks/logs/pre-tool-use-skill-started.log"
[[ -d "${LOG_FILE%/*}" ]] || mkdir -p "$(dirname "${LOG_FILE}")" 2>/dev/null || true

export OMNICLAUDE_HOOK_CRITICALITY="advisory"
source "${HOOKS_DIR}/scripts/common.sh" 2>/dev/null || {
    cat >/dev/null 2>/dev/null || true
    exit 0
}
onex_hook_gate PRE_TOOL_USE_QUALITY || {
    cat >/dev/null 2>/dev/null || true
    exit 0
}

INPUT="$(cat)"
if ! command -v jq >/dev/null 2>&1; then
    exit 0
fi

# OMN-20109: the validity test and every field are ONE jq, not six. Each field
# expression is the one its own jq used. `raw` prints what `jq -r` printed into
# `$(...)`: a string minus trailing newlines, any other value as jq's indented
# JSON. A read that errors yields "" as its `|| VAR=""` did. `_SS_VALID` is the
# old `jq -e .` test: absent when the input does not parse, is empty, or is
# null or false, and the hook exits exactly as it did.
_SS_FIELDS="$(printf '%s' "$INPUT" | jq -r '
    def ind($n): [range($n) | "  "] | join("");
    def pp($n): if type == "object" then
            (if length == 0 then "{}" else "{\n" + ([to_entries[]
                | ind($n + 1) + (.key | tojson) + ": " + (.value | pp($n + 1))]
                | join(",\n")) + "\n" + ind($n) + "}" end)
        elif type == "array" then
            (if length == 0 then "[]" else "[\n" + ([.[] | ind($n + 1) + pp($n + 1)]
                | join(",\n")) + "\n" + ind($n) + "]" end)
        else tojson end;
    def raw: if type == "string"
        then (if endswith("\n") then (.[:-1] | raw) else . end)
        else pp(0) end;
    (if . == null or . == false then "" else "_SS_VALID=1\n" end)
    + @sh "RUN_ID=\(try (.tool_use_id // "" | raw) catch "")\n"
    + @sh "SESSION_ID=\(try (.session_id // .sessionId // "" | raw) catch "")\n"
    + @sh "AGENT_ID=\(try (.agent_id // .agentId // "" | raw) catch "")\n"
    + @sh "TRANSCRIPT_PATH=\(try (.transcript_path // .transcriptPath // "" | raw) catch "")\n"
    + @sh "SKILL_NAME=\(try (.tool_input.skill // .tool_input.name // "" | raw) catch "")"
' 2>/dev/null)" || _SS_FIELDS=""
_SS_VALID=""
RUN_ID="" SESSION_ID="" AGENT_ID="" TRANSCRIPT_PATH="" SKILL_NAME=""
[[ -n "$_SS_FIELDS" ]] && eval "$_SS_FIELDS"
[[ "$_SS_VALID" == "1" ]] || exit 0
unset _SS_FIELDS _SS_VALID
# OMN-18609: AGENT_ID and TRANSCRIPT_PATH above locate the harness spawn
# sidecar that names the lane. Read here rather than in emit_to_journal so the
# lookup uses the SAME payload the hook was handed; a dispatched lane's cwd is
# the session's directory, not its worktree, so the worktree registry alone
# cannot attribute these events.
CORRELATION_ID="${ONEX_CORRELATION_ID:-$SESSION_ID}"

# The semantic registry requires these fields. Do not emit an unvalidated
# partial record, and do not manufacture sentinels that could look real.
if [[ -z "$RUN_ID" || -z "$SESSION_ID" || -z "$SKILL_NAME" || -z "$CORRELATION_ID" ]]; then
    exit 0
fi

PAYLOAD="$(jq -nc \
    --arg run_id "$RUN_ID" \
    --arg skill_name "$SKILL_NAME" \
    --arg repo_id "omniclaude" \
    --arg correlation_id "$CORRELATION_ID" \
    '{run_id: $run_id, skill_name: $skill_name, repo_id: $repo_id,
      correlation_id: $correlation_id}' 2>/dev/null)" || exit 0

# OMN-18471: this class is re-homed onto the journal path. Until 2026-09-16
# its ONLY call site was emit_via_daemon, which writes to a Unix socket that
# has not existed since 2026-06-08 -- so skill.started had no delivery path at
# all, not a second one. Zero occurrences of it appeared in a 5,000-record
# sample of the 50,002 then queued in the journal. It is also the class the
# stuck Slack alert named ("100 consecutive emit failures for 'skill.started'"),
# which is why repairing the drainer did nothing for it.
#
# The journal append is the delivery path. The emit_via_daemon call is kept
# beside it, not in place of it, because emit_via_daemon is retired as one
# change once every orphaned class is re-homed (AC5) -- removing its call
# sites one at a time would leave the surface half-migrated with no gate able
# to say which half.
#
# Neither call contacts Kafka from the Claude hook path. The semantic key is
# passed so the registry applies redact_capture before any topic fan-out.
emit_to_journal "skill.started" "$PAYLOAD" "$CORRELATION_ID"
exit 0
