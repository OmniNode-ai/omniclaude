#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# UserPromptSubmit Hook - Portable Plugin Version - FIXED
# Provides: Agent routing, manifest injection, correlation tracking

set -euo pipefail

# -----------------------------
# Portable Plugin Configuration
# -----------------------------
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${HOOKS_DIR}/logs/hook-enhanced.log"

PROJECT_ROOT="${PLUGIN_ROOT}/../.."
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"
elif [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"
else
    PROJECT_ROOT="$(pwd)"
fi

mkdir -p "$(dirname "$LOG_FILE")"
export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

source "${HOOKS_DIR}/scripts/common.sh"
export ARCHON_INTELLIGENCE_URL="${ARCHON_INTELLIGENCE_URL:-http://localhost:8053}"
SKIP_IF_SESSION_INJECTED="${OMNICLAUDE_SESSION_SKIP_IF_INJECTED:-true}"

SKIP_CLAUDE_HOOK_EVENT_EMIT=0
if ! command -v jq >/dev/null 2>&1; then
    log "ERROR: jq not found, skipping claude-hook-event emission"
    SKIP_CLAUDE_HOOK_EVENT_EMIT=1
fi
b64() { printf %s "$1" | base64; }

run_with_timeout() {
    local timeout_sec="$1"
    shift
    perl -e 'alarm shift; exec @ARGV' "$timeout_sec" "$@"
}

# -----------------------------
# Input Processing
# -----------------------------
INPUT="$(cat)"
# Start-of-hook timestamp for total latency measurement (OMN-2344)
_HOOK_START_MS="$(date +%s%3N 2>/dev/null || echo 0)"
if ! echo "$INPUT" | jq -e . >/dev/null 2>>"$LOG_FILE"; then
    log "ERROR: Malformed JSON on stdin, using empty object"
    INPUT='{}'
fi
log "UserPromptSubmit hook triggered (plugin mode)"

PROMPT="$(printf %s "$INPUT" | jq -r ".prompt // \"\"" 2>>"$LOG_FILE" || echo "")"
if [[ -z "$PROMPT" ]]; then
    log "ERROR: No prompt in input"
    printf %s "$INPUT"
    exit 0
fi

PROMPT_B64="$(b64 "$PROMPT")"

if command -v uuidgen >/dev/null 2>&1; then
    CORRELATION_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
else
    CORRELATION_ID="$($PYTHON_CMD -c 'import uuid; print(str(uuid.uuid4()))' | tr '[:upper:]' '[:lower:]')"
fi

# Log hook invocation (non-blocking)
# Pass prompt via stdin to avoid exposing it in process table (ps aux / /proc/PID/cmdline)
(
    printf '%s' "$PROMPT" | $PYTHON_CMD "${HOOKS_LIB}/log_hook_event.py" invocation \
        --hook-name "UserPromptSubmit" \
        --prompt-stdin \
        --correlation-id "$CORRELATION_ID" \
        2>>"$LOG_FILE" || true
) &

SESSION_ID="$(printf %s "$INPUT" | jq -r '.sessionId // .session_id // ""' 2>/dev/null || echo "")"
# NOTE: When sessionId is absent, SESSION_ID falls back to CORRELATION_ID.
# The accumulator file is then written as /tmp/omniclaude-session-<correlation_id>.json.
# session-end.sh derives SESSION_STATE_FILE from .sessionId, so the file names
# will not match and the accumulator will be orphaned in /tmp.  This is a known
# limitation — sessionId should always be present in normal Claude Code operation.
[[ -z "$SESSION_ID" ]] && SESSION_ID="$CORRELATION_ID"

if [[ "$KAFKA_ENABLED" == "true" ]] && [ "${SKIP_CLAUDE_HOOK_EVENT_EMIT:-0}" -ne 1 ]; then
    # Privacy contract for dual-emission via daemon fan-out:
    #   - onex.evt.* topics receive ONLY prompt_preview (100-char redacted) + prompt_length
    #   - onex.cmd.omniintelligence.* topics receive the full prompt via prompt_b64
    # The daemon's EventRegistry handles per-topic field filtering:
    #   evt payloads MUST NOT include prompt_b64 (daemon strips it).
    #   cmd payloads include prompt_b64 for intelligence processing.
    PROMPT_PAYLOAD=$(jq -n \
        --arg session_id "$SESSION_ID" \
        --arg prompt_preview "$(printf '%s' "${PROMPT:0:100}" | redact_secrets)" \
        --argjson prompt_length "${#PROMPT}" \
        --arg prompt_b64 "$PROMPT_B64" \
        --arg correlation_id "$CORRELATION_ID" \
        --arg event_type "UserPromptSubmit" \
        '{session_id: $session_id, prompt_preview: $prompt_preview, prompt_length: $prompt_length, prompt_b64: $prompt_b64, correlation_id: $correlation_id, event_type: $event_type}' 2>/dev/null)

    if [[ -n "$PROMPT_PAYLOAD" ]]; then
        emit_via_daemon "prompt.submitted" "$PROMPT_PAYLOAD" 100 &
    fi
fi

# -----------------------------
# Workflow Detection (FIXED: Quoted Heredoc)
# -----------------------------
WORKFLOW_TRIGGER="$(
    export PROMPT_B64="$PROMPT_B64"
    export HOOKS_LIB="$HOOKS_LIB"
    $PYTHON_CMD - <<'PY' 2>>"$LOG_FILE" || echo ""
import os, sys, base64
sys.path.insert(0, os.environ["HOOKS_LIB"])
try:
    from agent_detector import AgentDetector
    prompt = base64.b64decode(os.environ["PROMPT_B64"]).decode("utf-8", "replace")
    if AgentDetector().detect_automated_workflow(prompt):
        print("AUTOMATED_WORKFLOW_DETECTED")
except Exception:
    pass
PY
)"
WORKFLOW_DETECTED="false"
[[ "$WORKFLOW_TRIGGER" == "AUTOMATED_WORKFLOW_DETECTED" ]] && WORKFLOW_DETECTED="true"

# -----------------------------
# Agent Detection & Routing
# -----------------------------

# Slash commands manage their own agent dispatch — skip routing to avoid
# the router matching on command *arguments* (e.g. "code review" in
# "/local-review ...code review..." would incorrectly match code-quality-analyzer).
if [[ "$PROMPT" =~ ^/[a-zA-Z_-] ]]; then
    SLASH_CMD="$(echo "$PROMPT" | grep -oE '^/[a-zA-Z_-]+' || echo "")"
    log "Slash command detected: ${SLASH_CMD} — skipping agent routing (slash commands manage their own dispatch)"
    # Route slash commands through polymorphic-agent so the Skill() loader
    # runs inside the correct agent context. method="slash_command" lets
    # session-end.sh distinguish this from a real router decision.
    ROUTING_RESULT='{"selected_agent":"polymorphic-agent","confidence":0.85,"reasoning":"slash_command_delegation","method":"slash_command","domain":"workflow","purpose":"Coordinate skill execution — delegate complex skills to Task tool via Task(subagent_type=onex:polymorphic-agent)","candidates":[{"name":"polymorphic-agent","score":0.85,"description":"Multi-agent workflow coordinator for skills and complex tasks"}]}'
    # Update tab activity for statusline (e.g. "/ticket-work" → "ticket-work")
    update_tab_activity "${SLASH_CMD#/}"
else
    ROUTING_RESULT="$($PYTHON_CMD "${HOOKS_LIB}/route_via_events_wrapper.py" "$PROMPT" "$CORRELATION_ID" "5000" "$SESSION_ID" 2>>"$LOG_FILE" || echo "")"
    # Clear activity on regular prompts (no longer in a skill workflow)
    update_tab_activity ""
fi

if [ -z "$ROUTING_RESULT" ]; then
    ROUTING_RESULT='{"selected_agent":"","confidence":0.0,"reasoning":"routing unavailable","method":"fallback","domain":"","candidates":[]}'
fi

# -----------------------------------------------------------------------
# Pipeline Trace Logging — unified trace for routing/injection visibility
# tail -f ~/.claude/logs/pipeline-trace.log to see the full chain
# -----------------------------------------------------------------------
TRACE_LOG="$HOME/.claude/logs/pipeline-trace.log"
mkdir -p "$(dirname "$TRACE_LOG")" 2>/dev/null
_TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
_PROMPT_SHORT="$(printf '%s' "${PROMPT:0:80}" | redact_secrets)"
echo "[$_TS] [UserPromptSubmit] PROMPT prompt_length=${#PROMPT} preview=\"${_PROMPT_SHORT}\"" >> "$TRACE_LOG"

# Parse JSON response
AGENT_NAME="$(echo "$ROUTING_RESULT" | jq -r '.selected_agent // "NO_AGENT_DETECTED"')"
CONFIDENCE="$(echo "$ROUTING_RESULT" | jq -r '.confidence // "0.5"')"
SELECTION_METHOD="$(echo "$ROUTING_RESULT" | jq -r '.method // "fallback"')"
AGENT_DOMAIN="$(echo "$ROUTING_RESULT" | jq -r '.domain // "general"')"
AGENT_PURPOSE="$(echo "$ROUTING_RESULT" | jq -r '.purpose // ""')"
SELECTION_REASONING="$(echo "$ROUTING_RESULT" | jq -r '.reasoning // ""')"
LATENCY_MS="$(echo "$ROUTING_RESULT" | jq -r '.latency_ms // "0"')"
CANDIDATES_JSON="$(echo "$ROUTING_RESULT" | jq -r '.candidates // "[]"')"

echo "[$_TS] [UserPromptSubmit] ROUTING agent=$AGENT_NAME confidence=$CONFIDENCE method=$SELECTION_METHOD latency_ms=$LATENCY_MS" >> "$TRACE_LOG"

# -----------------------------
# Candidate List Injection & Pattern Injection
# -----------------------------
# OMN-1980: Agent YAML loading removed from sync hook path.
# The hook injects a candidate list; Claude loads the selected agent's YAML on-demand.
# This saves ~100ms+ from the sync path and lets the LLM make the final selection
# using semantic understanding (better precision than fuzzy matching alone).

_TS2="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "[$_TS2] [UserPromptSubmit] CANDIDATE_LIST agent=$AGENT_NAME candidates=${CANDIDATES_JSON}" >> "$TRACE_LOG"

AGENT_YAML_INJECTION=""
CANDIDATE_COUNT="$(echo "$CANDIDATES_JSON" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo "0")"

if [[ "$CANDIDATE_COUNT" -gt 0 ]]; then
    CANDIDATE_LIST="$(echo "$CANDIDATES_JSON" | jq -r '
        [to_entries[] | "\(.key + 1). \(.value.name) (\(.value.score)) - \(.value.description // "No description")"] | join("\n")
    ' 2>/dev/null || echo "")"

    FUZZY_BEST="$(echo "$CANDIDATES_JSON" | jq -r '.[0].name // ""' 2>/dev/null || echo "")"
    FUZZY_BEST_SCORE="$(echo "$CANDIDATES_JSON" | jq -r '.[0].score // "0.5"' 2>/dev/null || echo "0.5")"

    AGENT_YAML_INJECTION="========================================================================
AGENT ROUTING - SELECT AND ACT
========================================================================
The following agents matched your request. Pick the best match,
read its YAML from plugins/onex/agents/configs/{name}.yaml,
and follow its behavioral directives.

CANDIDATES (ranked by fuzzy score):
${CANDIDATE_LIST}

FUZZY BEST: ${FUZZY_BEST} (${FUZZY_BEST_SCORE})
YOUR DECISION: Pick the agent that best matches the user's actual intent.
========================================================================
"
fi

LEARNED_PATTERNS=""
SESSION_ALREADY_INJECTED=false
# Extraction event field defaults (overridden if injection succeeds)
PATTERN_SUCCESS="false"
PATTERN_COUNT=0
COHORT="treatment"
RETRIEVAL_MS=0
if [[ "$SKIP_IF_SESSION_INJECTED" == "true" ]] && [[ -f "${HOOKS_LIB}/session_marker.py" ]]; then
    if $PYTHON_CMD "${HOOKS_LIB}/session_marker.py" check --session-id "${SESSION_ID}" >/dev/null 2>/dev/null; then
        SESSION_ALREADY_INJECTED=true
    fi
fi

if [[ "$SESSION_ALREADY_INJECTED" == "false" ]] && [[ -n "$AGENT_NAME" ]] && [[ "$AGENT_NAME" != "NO_AGENT_DETECTED" ]]; then
    log "Loading learned patterns via context injection..."

    # Validate numeric env vars before passing to jq --argjson
    _max_patterns="${MAX_PATTERNS:-5}"
    _min_confidence="${MIN_CONFIDENCE:-0.7}"
    [[ "$_max_patterns" =~ ^[0-9]+$ ]] || _max_patterns=5
    [[ "$_min_confidence" =~ ^[0-9]*\.?[0-9]+$ ]] || _min_confidence=0.7

    PATTERN_INPUT="$(jq -n \
        --arg agent "${AGENT_NAME:-}" \
        --arg domain "${AGENT_DOMAIN:-}" \
        --arg session "${SESSION_ID:-}" \
        --arg project "${PROJECT_ROOT:-}" \
        --arg correlation "${CORRELATION_ID:-}" \
        --argjson max_patterns "$_max_patterns" \
        --argjson min_confidence "$_min_confidence" \
        '{
            agent_name: $agent,
            domain: $domain,
            session_id: $session,
            project: $project,
            correlation_id: $correlation,
            max_patterns: $max_patterns,
            min_confidence: $min_confidence
        }')"

    # 1s timeout (safety net, not target). Perl's alarm() truncates to integer,
    # so sub-second values become 0 (cancels the alarm). Use integer seconds only.
    # The entire UserPromptSubmit hook has a <500ms budget (CLAUDE.md);
    # this timeout caps worst-case latency while the budget governs typical runs.
    # Use ONEX-compliant wrapper for pattern injection
    # Use run_with_timeout for portability (works on macOS and Linux)
    if [[ -f "${HOOKS_LIB}/context_injection_wrapper.py" ]]; then
        log "Using context_injection_wrapper.py"
        PATTERN_RESULT="$(echo "$PATTERN_INPUT" | run_with_timeout 1 $PYTHON_CMD "${HOOKS_LIB}/context_injection_wrapper.py" 2>>"$LOG_FILE" || echo '{}')"
    else
        log "INFO: No pattern injector found, skipping pattern injection"
        PATTERN_RESULT='{}'
    fi

    PATTERN_SUCCESS="$(echo "$PATTERN_RESULT" | jq -r '.success // false' 2>/dev/null || echo 'false')"
    LEARNED_PATTERNS=""

    if [[ "$PATTERN_SUCCESS" == "true" ]]; then
        LEARNED_PATTERNS="$(echo "$PATTERN_RESULT" | jq -r '.patterns_context // ""' 2>/dev/null || echo '')"
        PATTERN_COUNT="$(echo "$PATTERN_RESULT" | jq -r '.pattern_count // 0' 2>/dev/null || echo '0')"
        COHORT="$(echo "$PATTERN_RESULT" | jq -r '.cohort // "treatment"' 2>/dev/null || echo 'treatment')"
        RETRIEVAL_MS="$(echo "$PATTERN_RESULT" | jq -r '.retrieval_ms // 0' 2>/dev/null || echo '0')"
        if [[ -n "$LEARNED_PATTERNS" ]] && [[ "$PATTERN_COUNT" != "0" ]]; then
            log "Learned patterns loaded: ${PATTERN_COUNT} patterns"
        fi
    else
        log "INFO: No learned patterns available"
    fi
elif [[ "$SESSION_ALREADY_INJECTED" == "true" ]]; then
    log "Using patterns from SessionStart injection (session ${SESSION_ID:0:8}...)"
fi

# -----------------------------
# Session Accumulator: Write raw signal state for session-end feedback (OMN-2356)
# session-end.sh reads this file to emit raw outcome signals to routing-feedback topic.
# Kept minimal: only observable facts, no derived scores.
# Written ONCE (first UserPromptSubmit) so the first-prompt routing and injection
# outcome are preserved. Subsequent prompts skip the write when the file already
# exists, preventing a later prompt (SESSION_ALREADY_INJECTED=true, PATTERN_SUCCESS
# undefined) from overwriting injection_occurred=true with injection_occurred=false.
# Uses atomic write (jq + redirect) — if jq fails the file is left unchanged.
# -----------------------------
if [[ -n "$SESSION_ID" ]]; then
    _ACCUM_FILE="/tmp/omniclaude-session-${SESSION_ID}.json"  # noqa: S108  # nosec B108
    # Note: TOCTOU race between -f check and mv is intentional — second writer wins,
    # first-prompt state may be lost, but this is acceptable since sessionId is unique
    # per session and concurrent hooks are extremely unlikely.
    if [[ ! -f "$_ACCUM_FILE" ]]; then
        # Guard: PATTERN_COUNT must be numeric before passing to jq --argjson.
        # A non-numeric string (e.g. from a malformed wrapper response) would
        # cause jq to fail silently (|| true) and leave _ACCUM_FILE unwritten.
        [[ "${PATTERN_COUNT:-0}" =~ ^[0-9]+$ ]] || PATTERN_COUNT=0
        # Guard: CONFIDENCE must be numeric before passing to jq --argjson.
        [[ "${CONFIDENCE:-0.5}" =~ ^[0-9]+(\.[0-9]+)?$ ]] || CONFIDENCE="0.5"
        # Clamp to [0.0, 1.0] — le=1.0 constraint matches schema
        awk "BEGIN{exit !($CONFIDENCE > 1.0)}" 2>/dev/null && CONFIDENCE="1.0"
        _INJECT_OCCURRED="false"
        [[ "${PATTERN_SUCCESS:-false}" == "true" ]] && [[ "${PATTERN_COUNT:-0}" != "0" ]] && _INJECT_OCCURRED="true"
        # When SESSION_ALREADY_INJECTED=true (SessionStart performed injection),
        # PATTERN_SUCCESS stays "false" for this prompt — override so injection_occurred
        # is truthful. PATTERN_COUNT remains 0 (count unknown for SessionStart injection).
        [[ "$SESSION_ALREADY_INJECTED" == "true" ]] && _INJECT_OCCURRED="true"
        # Normalize sentinel to empty string — "NO_AGENT_DETECTED" is a jq fallback
        # for malformed/partial routing JSON, not a real agent name.
        _ACCUM_AGENT="${AGENT_NAME}"
        [[ "$_ACCUM_AGENT" == "NO_AGENT_DETECTED" ]] && _ACCUM_AGENT=""
        _ACCUM_JSON="$(jq -n \
            --argjson injection_occurred "$_INJECT_OCCURRED" \
            --argjson patterns_injected_count "${PATTERN_COUNT:-0}" \
            --arg agent_selected "$_ACCUM_AGENT" \
            --argjson routing_confidence "${CONFIDENCE:-0.5}" \
            '{
                injection_occurred: $injection_occurred,
                patterns_injected_count: $patterns_injected_count,
                agent_selected: $agent_selected,
                routing_confidence: $routing_confidence
            }' 2>/dev/null)" || true
        if [[ -n "$_ACCUM_JSON" ]]; then
            _ACCUM_TMP="$_ACCUM_FILE.tmp.$$"
            printf '%s\n' "$_ACCUM_JSON" > "$_ACCUM_TMP" && mv "$_ACCUM_TMP" "$_ACCUM_FILE" || rm -f "$_ACCUM_TMP"
            log "Session accumulator written: ${_ACCUM_FILE}"
        fi
    else
        log "Session accumulator already exists, preserving first-prompt state: ${_ACCUM_FILE}"
    fi
fi

# -----------------------------
# Emit Health Check: Surface persistent failures
# -----------------------------
EMIT_HEALTH_WARNING=""
_EMIT_STATUS="${HOOKS_DIR}/logs/emit-health/status"
if [[ -f "$_EMIT_STATUS" ]]; then
    # Single read splits all 4 whitespace-delimited fields from the status file
    # Format: <fail_count> <fail_timestamp> <success_timestamp> <event_type>
    read -r _FAIL_COUNT _FAIL_TS _SUCCESS_TS _FAIL_EVT < "$_EMIT_STATUS" 2>/dev/null \
        || { _FAIL_COUNT=0; _FAIL_TS=0; _SUCCESS_TS=0; _FAIL_EVT="unknown"; }
    [[ "$_FAIL_COUNT" =~ ^[0-9]+$ ]] || _FAIL_COUNT=0
    [[ "$_FAIL_TS" =~ ^[0-9]+$ ]] || _FAIL_TS=0
    [[ "$_SUCCESS_TS" =~ ^[0-9]+$ ]] || _SUCCESS_TS=0
    _NOW=$(date -u +%s)
    _AGE=$((_NOW - _FAIL_TS))
    # Guard: negative age = clock skew, treat as stale
    [[ $_AGE -lt 0 ]] && _AGE=999

    # Guard invariants when fields default to 0:
    #   _FAIL_COUNT=0 → fails the -ge 3 check, so no warning fires.
    #   _FAIL_TS=0    → _AGE becomes ~epoch-seconds (~1.7B), fails -le 60.
    #   _SUCCESS_TS=0 → _FAIL_TS > 0 would pass, but only matters if both
    #                    _FAIL_COUNT and _AGE already passed their thresholds.
    # Result: all three conditions must be true, so any zeroed field is safe.
    if [[ $_FAIL_COUNT -ge 3 && $_AGE -le 60 && $_FAIL_TS -gt $_SUCCESS_TS ]]; then
        EMIT_HEALTH_WARNING="EVENT EMISSION DEGRADED: ${_FAIL_COUNT} consecutive failures (last: ${_FAIL_EVT}, ${_AGE}s ago). Events not reaching Kafka."
        log "WARNING: Emit daemon degraded (${_FAIL_COUNT} consecutive failures, last_event=${_FAIL_EVT})"
    fi

    # Escalation: overrides the degraded warning above for sustained failures
    if [[ $_FAIL_COUNT -ge 10 && $_AGE -le 600 && $_FAIL_TS -gt $_SUCCESS_TS ]]; then
        EMIT_HEALTH_WARNING="EVENT EMISSION DOWN: ${_FAIL_COUNT} consecutive failures over ${_AGE}s. Daemon likely crashed. Run: pkill -f 'omniclaude.publisher' and start a new session."
    fi
fi

# -----------------------------
# Pattern Violation Advisory (OMN-2269)
# -----------------------------
# Load pending advisories from PostToolUse pattern enforcement.
# Strictly informational -- Claude can act on advisories or not.
# Respects session cooldown from OMN-2263.
PATTERN_ADVISORY=""
ADVISORY_FORMATTER="${HOOKS_LIB}/pattern_advisory_formatter.py"
if [[ -f "$ADVISORY_FORMATTER" ]]; then
    ADVISORY_INPUT=$(jq -n --arg session_id "$SESSION_ID" '{session_id: $session_id}' 2>/dev/null)
    if [[ -n "$ADVISORY_INPUT" ]]; then
        set +e
        PATTERN_ADVISORY=$(echo "$ADVISORY_INPUT" | run_with_timeout 1 "$PYTHON_CMD" "$ADVISORY_FORMATTER" load 2>>"$LOG_FILE")
        set -e
        # Guard against partial stdout from a hard-crashed subprocess (e.g. SIGKILL).
        # Valid advisory output starts with "## " (the markdown header).
        if [[ -n "$PATTERN_ADVISORY" ]] && [[ ! $PATTERN_ADVISORY =~ ^##\  ]]; then
            PATTERN_ADVISORY=""
        fi
        if [[ -n "$PATTERN_ADVISORY" ]]; then
            log "Pattern advisory loaded for context injection"
            _TS_ADV="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
            echo "[$_TS_ADV] [UserPromptSubmit] PATTERN_ADVISORY chars=${#PATTERN_ADVISORY}" >> "$TRACE_LOG"
        fi
    fi
fi

# -----------------------------
# Intent Classification (OMN-2493)
# -----------------------------
# Run intent classification synchronously (inline, capped by run_with_timeout).
# The classifier stores intent_id + intent_class in the correlation file.
# Classification result is also injected into additionalContext so Claude
# can apply model selection and validator hints inline.
#
# Design:
#   - run_with_timeout caps wall-clock to 1s (consistent with injection budget)
#   - Any failure → INTENT_CONTEXT="" → no context change, hook continues
#   - Exits 0 on all failures (invariant)
INTENT_CONTEXT=""
INTENT_CLASSIFIER="${HOOKS_LIB}/intent_classifier.py"
if [[ -f "$INTENT_CLASSIFIER" ]]; then
    set +e
    INTENT_RESULT="$(printf '%s' "$PROMPT_B64" | run_with_timeout 1 "$PYTHON_CMD" \
        "$INTENT_CLASSIFIER" \
        --prompt-stdin \
        --session-id "$SESSION_ID" \
        --correlation-id "$CORRELATION_ID" \
        2>>"$LOG_FILE")"
    set -e

    _INTENT_SUCCESS="$(echo "$INTENT_RESULT" | jq -r '.success // false' 2>/dev/null || echo 'false')"
    if [[ "$_INTENT_SUCCESS" == "true" ]]; then
        _INTENT_CLASS="$(echo "$INTENT_RESULT" | jq -r '.intent_class // "GENERAL"' 2>/dev/null || echo 'GENERAL')"
        _INTENT_CONF="$(echo "$INTENT_RESULT" | jq -r '.confidence // 0' 2>/dev/null || echo '0')"
        _INTENT_ID="$(echo "$INTENT_RESULT" | jq -r '.intent_id // ""' 2>/dev/null || echo '')"
        _INTENT_ELAPSED="$(echo "$INTENT_RESULT" | jq -r '.elapsed_ms // 0' 2>/dev/null || echo '0')"
        log "Intent classified: class=${_INTENT_CLASS} confidence=${_INTENT_CONF} elapsed_ms=${_INTENT_ELAPSED}"

        # Build intent context block using the model hints module
        INTENT_CONTEXT="$(
            export HOOKS_LIB="$HOOKS_LIB"
            export INTENT_CLASS="$_INTENT_CLASS"
            export INTENT_CONF="$_INTENT_CONF"
            export INTENT_ID="$_INTENT_ID"
            $PYTHON_CMD - <<'PYBLOCK' 2>>"$LOG_FILE" || echo ""
import os, sys
sys.path.insert(0, os.environ["HOOKS_LIB"])
try:
    import intent_model_hints as imh
    print(imh.format_intent_context(
        intent_class=os.environ.get("INTENT_CLASS", "GENERAL"),
        confidence=float(os.environ.get("INTENT_CONF", "0")),
        intent_id=os.environ.get("INTENT_ID", ""),
    ))
except Exception:
    pass
PYBLOCK
        )"
        _TS_INT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
        echo "[$_TS_INT] [UserPromptSubmit] INTENT class=${_INTENT_CLASS} confidence=${_INTENT_CONF} elapsed_ms=${_INTENT_ELAPSED}" >> "$TRACE_LOG"
    else
        log "INFO: Intent classification unavailable or failed — proceeding without intent context"
    fi
fi

# -----------------------------
# Local Model Delegation Dispatch (OMN-2271)
# -----------------------------
# Delegation runs AFTER routing + injection + advisory because:
# 1. Routing provides agent context that shapes the delegation decision
# 2. If delegation succeeds, we short-circuit all final assembly
# 3. Reordering would bypass agent context that local models need
#
# When ENABLE_LOCAL_INFERENCE_PIPELINE=true AND ENABLE_LOCAL_DELEGATION=true,
# attempt to delegate to a local model via TaskClassifier.is_delegatable().
# Conservative: any error or failed gate falls through to the normal Claude path.
# Runs in the sync path (before final context assembly) — local_delegation_handler.py
# exits 0 on all failures so this block never blocks the hook.
DELEGATION_RESULT=""
DELEGATION_ACTIVE="false"
INFERENCE_PIPELINE_ENABLED=$(_normalize_bool "${ENABLE_LOCAL_INFERENCE_PIPELINE:-false}")
LOCAL_DELEGATION_ENABLED=$(_normalize_bool "${ENABLE_LOCAL_DELEGATION:-false}")

if [[ "$INFERENCE_PIPELINE_ENABLED" == "true" ]] && [[ "$LOCAL_DELEGATION_ENABLED" == "true" ]] \
        && [[ "$WORKFLOW_DETECTED" != "true" ]] \
        && [[ ! "$PROMPT" =~ ^/ ]]; then  # Slash commands invoke structured skills/commands — never delegate to local models
    DELEGATION_HANDLER="${HOOKS_LIB}/local_delegation_handler.py"
    if [[ -f "$DELEGATION_HANDLER" ]]; then
        log "Local delegation enabled — classifying prompt (correlation=$CORRELATION_ID)"
        set +e
        DELEGATION_RESULT="$(printf '%s' "$PROMPT_B64" | run_with_timeout 8 "$PYTHON_CMD" "$DELEGATION_HANDLER" --prompt-stdin "$CORRELATION_ID" 2>>"$LOG_FILE")"
        set -e

        # Validate output is a parseable JSON object (not just any valid JSON value)
        if [[ -n "$DELEGATION_RESULT" ]] && jq -e 'type == "object"' <<< "$DELEGATION_RESULT" >/dev/null 2>/dev/null; then
            DELEGATION_ACTIVE="$(jq -r '.delegated // false' <<< "$DELEGATION_RESULT" 2>/dev/null || echo 'false')"
        else
            log "WARNING: local_delegation_handler.py produced non-JSON output, skipping"
            DELEGATION_RESULT=""
            DELEGATION_ACTIVE="false"
        fi

        if [[ "$DELEGATION_ACTIVE" == "true" ]]; then
            DELEGATED_RESPONSE="$(jq -r '.response // ""' <<< "$DELEGATION_RESULT" 2>/dev/null || echo '')"
            DELEGATED_MODEL="$(jq -r '.model // "local-model"' <<< "$DELEGATION_RESULT" 2>/dev/null || echo 'local-model')"
            DELEGATED_LATENCY="$(jq -r '.latency_ms // 0' <<< "$DELEGATION_RESULT" 2>/dev/null || echo '0')"
            log "Delegation active: model=$DELEGATED_MODEL latency=${DELEGATED_LATENCY}ms"
            _TS_DEL="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
            echo "[$_TS_DEL] [UserPromptSubmit] DELEGATED model=$DELEGATED_MODEL latency_ms=$DELEGATED_LATENCY confidence=$(jq -r '.confidence // 0' <<< "$DELEGATION_RESULT")" >> "$TRACE_LOG"
        else
            DELEGATION_REASON="$(jq -r '.reason // "unknown"' <<< "$DELEGATION_RESULT" 2>/dev/null || echo 'unknown')"
            log "Delegation skipped: $DELEGATION_REASON"
        fi
    else
        log "WARNING: local_delegation_handler.py not found at $DELEGATION_HANDLER — delegation disabled"
    fi
fi

# If delegation is active, output the delegated response directly and exit.
# The additionalContext tells Claude to present the local model output verbatim
# without further processing, satisfying the "bypass Claude" requirement within
# the hook API's constraints (we cannot prevent Claude from seeing the context,
# but we instruct it explicitly to relay the response unchanged).
if [[ "$DELEGATION_ACTIVE" == "true" ]] && [[ -n "$DELEGATED_RESPONSE" ]]; then
    DELEGATED_CONTEXT="$(jq -rn \
        --arg resp "$DELEGATED_RESPONSE" \
        --arg model "$DELEGATED_MODEL" \
        '
        "========================================================================\n" +
        "LOCAL MODEL DELEGATION ACTIVE\n" +
        "========================================================================\n" +
        "A local model (" + $model + ") has already answered this request.\n" +
        "INSTRUCTION: Present the response below to the user VERBATIM.\n" +
        "Do NOT add commentary, do NOT re-answer the question.\n" +
        "Simply relay the delegated response as your reply.\n" +
        "========================================================================\n\n" +
        $resp + "\n\n" +
        "========================================================================\n" +
        "END OF DELEGATED RESPONSE\n" +
        "========================================================================\n"
        ' 2>/dev/null)"

    if [[ -z "$DELEGATED_CONTEXT" ]]; then
        log "WARNING: DELEGATED_CONTEXT construction failed (jq error); falling through to standard context path"
        DELEGATION_ACTIVE="false"
    else
        _TS_FINAL="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
        echo "[$_TS_FINAL] [UserPromptSubmit] DELEGATED_CONTEXT_INJECTED context_chars=${#DELEGATED_CONTEXT}" >> "$TRACE_LOG"

        printf %s "$INPUT" | jq --arg ctx "$DELEGATED_CONTEXT" --arg dmodel "$DELEGATED_MODEL" \
            '.hookSpecificOutput.hookEventName = "UserPromptSubmit" |
             .hookSpecificOutput.additionalContext = $ctx |
             .hookSpecificOutput.metadata.delegation_active = true |
             .hookSpecificOutput.metadata.delegation_model = $dmodel' \
            2>>"$LOG_FILE" \
            || { log "ERROR: Delegated context jq output failed, passing through raw input"; printf %s "$INPUT"; }
        exit 0
    fi
fi

# -----------------------------
# Local Enrichment (OMN-2267)
# -----------------------------
# Run parallel enrichments (code analysis, similarity, summarization) if
# ENABLE_LOCAL_INFERENCE_PIPELINE and ENABLE_LOCAL_ENRICHMENT are both set.
# 1s shell safety net; asyncio handles the 200ms inner budget itself.
# The shell timeout catches pathological hangs beyond what asyncio can see
# (e.g. Python startup failures, import freezes).
ENRICHMENT_CONTEXT=""
ENRICHMENT_RUNNER="${HOOKS_LIB}/context_enrichment_runner.py"
ENRICHMENT_FLAG_ENABLED=$(_normalize_bool "${ENABLE_LOCAL_ENRICHMENT:-false}")
if [[ "$INFERENCE_PIPELINE_ENABLED" == "true" ]] && [[ "$ENRICHMENT_FLAG_ENABLED" == "true" ]] && [[ -f "$ENRICHMENT_RUNNER" ]]; then
    # Normalize routing sentinels to empty string so Python maps them to None.
    # "NO_AGENT_DETECTED" is a jq fallback for absent/malformed routing JSON.
    # "null" is the literal string jq emits when the agent_name field is JSON null.
    # In both cases downstream dashboards expect null, not the sentinel string.
    # Python's `input_data.get("agent_name") or None` does NOT catch the string "null".
    # Note: AGENT_NAME is always set by the routing block above (line 174); the :- default
    # is a safety net for any future code path that bypasses routing, yielding empty string.
    AGENT_NAME_FOR_ENRICHMENT="${AGENT_NAME:-}"
    [[ "$AGENT_NAME_FOR_ENRICHMENT" == "NO_AGENT_DETECTED" ]] && AGENT_NAME_FOR_ENRICHMENT=""
    [[ "$AGENT_NAME_FOR_ENRICHMENT" == "null" ]] && AGENT_NAME_FOR_ENRICHMENT=""
    # Shell normalizes NO_AGENT_DETECTED/null → ""; Python normalizes "" → None via `or None`.
    # Both guards are required: removing either breaks the contract.
    # Known sentinels from routing layer (update here if routing adds new sentinel values):
    #   "NO_AGENT_DETECTED" -- jq fallback for absent/malformed routing JSON (guard above)
    #   "null"              -- literal string jq emits when agent_name field is JSON null (guard above)
    #   ""                  -- empty string produced when routing returns an empty selected_agent;
    #                          in jq, "" is truthy so `// "NO_AGENT_DETECTED"` does NOT fire for
    #                          it; bypasses both explicit guards; Python maps "" → None via
    #                          `input_data.get("agent_name") or None` implicitly
    ENRICHMENT_INPUT=$(jq -n \
        --arg prompt "$PROMPT" \
        --arg session_id "$SESSION_ID" \
        --arg correlation_id "$CORRELATION_ID" \
        --arg project_path "$PROJECT_ROOT" \
        --arg agent_name "$AGENT_NAME_FOR_ENRICHMENT" \
        '{prompt: $prompt, session_id: $session_id, correlation_id: $correlation_id, project_path: $project_path, agent_name: $agent_name}' 2>/dev/null)
    if [[ -n "$ENRICHMENT_INPUT" ]]; then
        set +e
        # 1s = Python startup overhead + 200ms inner budget
        ENRICHMENT_RESULT=$(echo "$ENRICHMENT_INPUT" | run_with_timeout 1 "$PYTHON_CMD" "$ENRICHMENT_RUNNER" 2>>"$LOG_FILE")
        set -e
        ENRICHMENT_SUCCESS=$(echo "$ENRICHMENT_RESULT" | jq -r '.success // false' 2>/dev/null || echo 'false')
        if [[ "$ENRICHMENT_SUCCESS" == "true" ]]; then
            ENRICHMENT_CONTEXT=$(echo "$ENRICHMENT_RESULT" | jq -r '.enrichment_context // ""' 2>/dev/null || echo '')
            _ENR_COUNT=$(echo "$ENRICHMENT_RESULT" | jq -r '.enrichment_count // 0' 2>/dev/null || echo '0')
            _ENR_TOKENS=$(echo "$ENRICHMENT_RESULT" | jq -r '.tokens_used // 0' 2>/dev/null || echo '0')
            if [[ -n "$ENRICHMENT_CONTEXT" ]] && [[ "$_ENR_COUNT" != "0" ]]; then
                log "Enrichments loaded: ${_ENR_COUNT} enrichments, ${_ENR_TOKENS} tokens"
                _TS_ENR="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
                echo "[$_TS_ENR] [UserPromptSubmit] ENRICHMENT count=${_ENR_COUNT} tokens=${_ENR_TOKENS}" >> "$TRACE_LOG"
            fi
        else
            log "INFO: No enrichments available (disabled or handlers not installed)"
        fi
    fi
fi

# -----------------------------
# Agent Context Assembly (FIXED: Safe injection)
# -----------------------------
POLLY_DISPATCH_THRESHOLD="${POLLY_DISPATCH_THRESHOLD:-0.7}"
MEETS_THRESHOLD="$(awk -v conf="$CONFIDENCE" -v thresh="$POLLY_DISPATCH_THRESHOLD" 'BEGIN {print (conf >= thresh) ? "true" : "false"}')"

# Only inject agent context when an agent was actually matched.
# When nothing matched, pass through with no additional context — no fallback noise.
AGENT_CONTEXT=""
if [[ -n "$AGENT_NAME" ]] && [[ "$AGENT_NAME" != "NO_AGENT_DETECTED" ]]; then
    AGENT_CONTEXT=$(jq -rn \
        --arg emit_warn "$EMIT_HEALTH_WARNING" \
        --arg yaml "$AGENT_YAML_INJECTION" \
        --arg patterns "$LEARNED_PATTERNS" \
        --arg enrichment "$ENRICHMENT_CONTEXT" \
        --arg advisory "$PATTERN_ADVISORY" \
        --arg intent "$INTENT_CONTEXT" \
        --arg name "$AGENT_NAME" \
        --arg conf "$CONFIDENCE" \
        --arg domain "$AGENT_DOMAIN" \
        --arg purpose "$AGENT_PURPOSE" \
        --arg reason "$SELECTION_REASONING" \
        --arg thresh "$POLLY_DISPATCH_THRESHOLD" \
        --arg meets "$MEETS_THRESHOLD" \
        '
        (if $emit_warn != "" then $emit_warn + "\n\n" else "" end) +
        $yaml + "\n" + $patterns + "\n" +
        (if $enrichment != "" then $enrichment + "\n" else "" end) +
        (if $advisory != "" then $advisory + "\n" else "" end) +
        (if $intent != "" then $intent + "\n" else "" end) +
        "========================================================================\n" +
        "AGENT CONTEXT\n" +
        "========================================================================\n" +
        "AGENT: " + $name + "\n" +
        "CONFIDENCE: " + $conf + " (Threshold: " + $thresh + ")\n" +
        "MEETS THRESHOLD: " + $meets + "\n" +
        "DOMAIN: " + $domain + "\n" +
        "PURPOSE: " + $purpose + "\n" +
        "REASONING: " + $reason + "\n" +
        "========================================================================\n"
        ')
fi

# Final trace: total context injected
_TS3="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "[$_TS3] [UserPromptSubmit] INJECTED context_chars=${#AGENT_CONTEXT} meets_threshold=$MEETS_THRESHOLD agent=$AGENT_NAME" >> "$TRACE_LOG"

# -----------------------------
# Emit extraction pipeline events (non-blocking) OMN-2344
# Fires context.utilization + agent.match + latency.breakdown to omnidash topics.
# Always runs in a background subshell — never blocks the hook.
# -----------------------------
if [[ "$KAFKA_ENABLED" == "true" ]] && [[ -f "${HOOKS_LIB}/extraction_event_emitter.py" ]]; then
    _HOOK_END_MS="$(date +%s%3N 2>/dev/null || echo 0)"
    _TOTAL_LATENCY_MS="$(( _HOOK_END_MS - _HOOK_START_MS ))"
    # Clamp to 0 on clock skew (e.g. date fallback produces 0-0=0 which is fine)
    [[ "$_TOTAL_LATENCY_MS" -lt 0 ]] 2>/dev/null && _TOTAL_LATENCY_MS=0
    _INJECTION_OCCURRED="false"
    [[ "${PATTERN_SUCCESS:-false}" == "true" ]] && [[ "${PATTERN_COUNT:-0}" != "0" ]] && _INJECTION_OCCURRED="true"
    _EXTRACTION_PAYLOAD=$(jq -n \
        --arg session_id "$SESSION_ID" \
        --arg correlation_id "$CORRELATION_ID" \
        --arg agent_name "${AGENT_NAME:-polymorphic-agent}" \
        --arg cohort "${COHORT:-treatment}" \
        --argjson injection_occurred "$_INJECTION_OCCURRED" \
        --argjson patterns_count "${PATTERN_COUNT:-0}" \
        --argjson routing_time_ms "${LATENCY_MS:-0}" \
        --argjson retrieval_time_ms "${RETRIEVAL_MS:-0}" \
        --argjson injection_time_ms "${RETRIEVAL_MS:-0}" \
        --argjson user_visible_latency_ms "$_TOTAL_LATENCY_MS" \
        --argjson routing_confidence "${CONFIDENCE:-0.5}" \
        '{
            session_id: $session_id,
            correlation_id: $correlation_id,
            agent_name: $agent_name,
            agent_match_score: $routing_confidence,
            routing_confidence: $routing_confidence,
            cohort: $cohort,
            injection_occurred: $injection_occurred,
            patterns_count: $patterns_count,
            routing_time_ms: $routing_time_ms,
            retrieval_time_ms: $retrieval_time_ms,
            injection_time_ms: $injection_time_ms,
            user_visible_latency_ms: $user_visible_latency_ms,
            cache_hit: false
        }' 2>/dev/null)
    if [[ -n "$_EXTRACTION_PAYLOAD" ]]; then
        (
            echo "$_EXTRACTION_PAYLOAD" | $PYTHON_CMD "${HOOKS_LIB}/extraction_event_emitter.py" \
                2>>"$LOG_FILE" || true
        ) &
    fi
fi

# Final Output via jq to ensure JSON integrity
printf %s "$INPUT" | jq --arg ctx "$AGENT_CONTEXT" \
    '.hookSpecificOutput.hookEventName = "UserPromptSubmit" |
     .hookSpecificOutput.additionalContext = $ctx' 2>>"$LOG_FILE" \
    || { log "ERROR: Final jq output failed, passing through raw input"; printf %s "$INPUT"; }
