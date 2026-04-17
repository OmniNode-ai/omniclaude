#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PostToolUse Kafka poison-message guard [OMN-9085].
#
# Classifies Bash tool output against aiokafka UnicodeDecodeError patterns and
# records a CRITICAL friction event. Passthrough-only — never blocks the
# tool result; the failing output still reaches the model so the agent can
# react, but friction is persisted for friction_triage consumption.
#
# Input (stdin): Claude Code PostToolUse JSON with tool_name + tool_response.
# Output (stdout): hookSpecificOutput JSON with additionalContext on match,
#                  or empty {} passthrough on no-match / non-Bash.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"

# Resolve absolute script dir BEFORE any cd.
_resolve_self() {
    local src="$1"
    realpath "$src" 2>/dev/null && return 0
    if command -v python3 >/dev/null 2>&1; then
        python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$src" && return 0
    fi
    return 1
}
_SELF="$(_resolve_self "${BASH_SOURCE[0]}")"
_SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
unset _SELF
unset -f _resolve_self

source "${_SCRIPT_DIR}/error-guard.sh" 2>/dev/null || true

# Python getpath may call os.getcwd() during startup. Ensure CWD is stable.
cd "$HOME" 2>/dev/null || cd /tmp || true

_INPUT_ONEX_STATE_DIR="${ONEX_STATE_DIR:-}"
# shellcheck source=/dev/null
source "${_SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true

EVENT_JSON=$(cat)

# Drain and exit if no ONEX_STATE_DIR resolved (infra-failure tolerance).
if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    echo '{}'
    exit 0
fi

# Extract tool name — passthrough for anything except Bash.
TOOL_NAME=$(printf '%s' "$EVENT_JSON" | jq -r '.tool_name // .toolName // ""' 2>/dev/null || printf '')
if [[ "$TOOL_NAME" != "Bash" ]]; then
    echo '{}'
    exit 0
fi

# Collect candidate output — stdout, stderr, and the generic .output key Claude
# Code uses for Bash tool responses. jq concatenates missing keys as empty.
TOOL_OUTPUT=$(
    printf '%s' "$EVENT_JSON" \
      | jq -r '[(.tool_response.stdout // ""), (.tool_response.stderr // ""), (.tool_response.output // "")] | join("\n")' \
      2>/dev/null || printf ''
)

if [[ -z "$TOOL_OUTPUT" ]]; then
    echo '{}'
    exit 0
fi

# Resolve Python. Prefer repo venv (same priority chain as common.sh) but fall
# back to system python3 so this hook never hard-fails on lite installs.
PYTHON_BIN=""
if [[ -n "${PLUGIN_PYTHON_BIN:-}" && -x "${PLUGIN_PYTHON_BIN}" ]]; then
    PYTHON_BIN="${PLUGIN_PYTHON_BIN}"
else
    PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
    _REPO_ROOT="$(cd "${PLUGIN_ROOT}/../.." 2>/dev/null && pwd)"
    if [[ -x "${_REPO_ROOT}/.venv/bin/python3" ]]; then
        PYTHON_BIN="${_REPO_ROOT}/.venv/bin/python3"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="python3"
    fi
fi
if [[ -z "${PYTHON_BIN}" ]]; then
    echo '{}'
    exit 0
fi

CLASSIFIER_LIB="${_SCRIPT_DIR}/../lib/kafka_poison_message_classifier.py"
if [[ ! -f "${CLASSIFIER_LIB}" ]]; then
    echo '{}'
    exit 0
fi

# Classify via a short inline driver. Pass output via a temp file rather than
# stdin: a heredoc-driven python invocation already consumes stdin for the
# script body, so piping output in would be ignored.
_INPUT_TMP="$(mktemp -t kafka_poison_input.XXXXXX)"
trap 'rm -f "${_INPUT_TMP:-}"' EXIT
printf '%s' "$TOOL_OUTPUT" > "${_INPUT_TMP}"

CLASSIFY_RESULT=$(
    PYTHONPATH="${_SCRIPT_DIR}/../lib:${PYTHONPATH:-}" \
    INPUT_PATH="${_INPUT_TMP}" \
    "${PYTHON_BIN}" -c '
import os, sys
from kafka_poison_message_classifier import classify_kafka_failure
with open(os.environ["INPUT_PATH"], "r", encoding="utf-8", errors="replace") as f:
    data = f.read()
result = classify_kafka_failure(data)
if result is not None:
    sys.stdout.write(f"{result.pattern}\t{result.severity}\n")
' 2>/dev/null || true
)
rm -f "${_INPUT_TMP}"
trap - EXIT

if [[ -z "${CLASSIFY_RESULT}" ]]; then
    echo '{}'
    exit 0
fi

PATTERN=$(printf '%s' "$CLASSIFY_RESULT" | awk -F'\t' 'NR==1{print $1}')
SEVERITY=$(printf '%s' "$CLASSIFY_RESULT" | awk -F'\t' 'NR==1{print $2}')
[[ -z "$PATTERN" ]] && PATTERN="kafka_poison"
[[ -z "$SEVERITY" ]] && SEVERITY="CRITICAL"

SESSION_ID=$(printf '%s' "$EVENT_JSON" | jq -r '.session_id // .sessionId // "unknown"' 2>/dev/null || printf 'unknown')

_sanitize() { printf '%s' "$1" | tr -d '\n\r' | sed 's/"/\\"/g'; }
SESSION_ID=$(_sanitize "$SESSION_ID")

DATE_PREFIX=$(date -u +%Y-%m-%d)
TS_NS=$(date -u +%s%N 2>/dev/null || date -u +%s)

FRICTION_DIR="${ONEX_STATE_DIR}/friction/kafka_poison"
mkdir -p "$FRICTION_DIR" 2>/dev/null || true

FRICTION_FILE="${FRICTION_DIR}/${DATE_PREFIX}-${PATTERN}-${TS_NS}.yaml"

# Verbatim error excerpt — first 40 lines, YAML block-literal to preserve
# formatting without injection risk. YAML block scalar literal content does
# not need escaping of quotes/colons.
VERBATIM_EXCERPT=$(printf '%s' "$TOOL_OUTPUT" | head -40 | sed 's/^/    /')

cat > "$FRICTION_FILE" <<YAML || true
id: kafka-poison-${PATTERN}-${SESSION_ID:0:8}-${TS_NS}
date: ${DATE_PREFIX}
severity: ${SEVERITY}
surface: kafka_poison
category: kafka
title: "Kafka poison message detected (${PATTERN})"
summary: >
  PostToolUse Bash guard detected a Kafka consumer decode failure matching
  pattern '${PATTERN}'. The originating tool output is preserved verbatim
  below so operators can replay and classify the offending record.
impact: >
  aiokafka consumers hitting UnicodeDecodeError crash-loop on every poll,
  taking merge-sweep / dispatch-engine orchestrator ticks down with them.
root_cause: >
  Broker returned a record with bytes the aiokafka decoder cannot parse
  as UTF-8 (e.g. partial frame, truncated header, binary payload in a
  UTF-8 topic).
pattern: "${PATTERN}"
session_id: "${SESSION_ID}"
linear_ticket: OMN-9085
verbatim_output: |
${VERBATIM_EXCERPT}
YAML

# Emit hookSpecificOutput per OMN-9072 so the model sees a short context note
# on its next turn; the failing tool result still reaches it unchanged.
ADDITIONAL_CONTEXT="[kafka_poison_guard] CRITICAL: Kafka consumer poison message detected (pattern=${PATTERN}). Friction recorded at ${FRICTION_FILE}. Investigate and do not retry blindly — record may crash-loop the consumer."

jq -n \
    --arg hook "PostToolUse" \
    --arg ctx "$ADDITIONAL_CONTEXT" \
    '{hookSpecificOutput: {hookEventName: $hook, additionalContext: $ctx}}'

# Suppress unused-variable warning from shellcheck (kept for diagnostics).
: "${_OMNICLAUDE_HOOK_NAME}" "${_INPUT_ONEX_STATE_DIR:-}"

exit 0
