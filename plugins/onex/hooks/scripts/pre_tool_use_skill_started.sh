#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Append the skill lifecycle start at the actual PreToolUse boundary.
#
# The matching completion is emitted by post-tool-use-quality.sh after Claude
# returns. Both records use Claude's tool_use_id as their invocation key; this
# hook never invents a timestamp or a run identifier.

set -uo pipefail

_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${ONEX_STATE_DIR:-/tmp}/hooks/logs/pre-tool-use-skill-started.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

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
if ! command -v jq >/dev/null 2>&1 || ! printf '%s' "$INPUT" | jq -e . >/dev/null 2>&1; then
    exit 0
fi

RUN_ID="$(printf '%s' "$INPUT" | jq -r '.tool_use_id // ""' 2>/dev/null)" || RUN_ID=""
SESSION_ID="$(printf '%s' "$INPUT" | jq -r '.session_id // .sessionId // ""' 2>/dev/null)" || SESSION_ID=""
SKILL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_input.skill // .tool_input.name // ""' 2>/dev/null)" || SKILL_NAME=""
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

# This is intentionally synchronous only through the local emit daemon. It
# must pass the semantic key so the registry applies redact_capture before any
# topic fan-out; it never contacts Kafka from the Claude hook path.
emit_via_daemon "skill.started" "$PAYLOAD" 50 || true
exit 0
