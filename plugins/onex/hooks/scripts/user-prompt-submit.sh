#!/bin/bash
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
    log "Slash command detected: ${SLASH_CMD} — skipping agent routing, defaulting to polymorphic-agent"
    ROUTING_RESULT='{"selected_agent":"polymorphic-agent","confidence":1.0,"reasoning":"slash_command_bypass","method":"slash_command","domain":"workflow_coordination","purpose":"Slash commands manage their own agent dispatch","candidates":[]}'
    # Update tab activity for statusline (e.g. "/ticket-work" → "ticket-work")
    update_tab_activity "${SLASH_CMD#/}"
else
    ROUTING_RESULT="$($PYTHON_CMD "${HOOKS_LIB}/route_via_events_wrapper.py" "$PROMPT" "$CORRELATION_ID" "5000" "$SESSION_ID" 2>>"$LOG_FILE" || echo "")"
    # Clear activity on regular prompts (no longer in a skill workflow)
    update_tab_activity ""
fi

if [ -z "$ROUTING_RESULT" ]; then
    ROUTING_RESULT='{"selected_agent":"polymorphic-agent","confidence":0.5,"reasoning":"fallback","method":"fallback","domain":"workflow_coordination"}'
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

    FUZZY_BEST="$(echo "$CANDIDATES_JSON" | jq -r '.[0].name // "polymorphic-agent"' 2>/dev/null || echo "polymorphic-agent")"
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

If no agent fits, default to polymorphic-agent.
========================================================================
"
fi

LEARNED_PATTERNS=""
SESSION_ALREADY_INJECTED=false
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
# Local Model Delegation Dispatch (OMN-2271)
# -----------------------------
# When ENABLE_LOCAL_INFERENCE_PIPELINE=true AND ENABLE_LOCAL_DELEGATION=true,
# attempt to delegate to a local model via TaskClassifier.is_delegatable().
# Conservative: any error or failed gate falls through to the normal Claude path.
# Runs in the sync path (before final context assembly) — local_delegation_handler.py
# exits 0 on all failures so this block never blocks the hook.
DELEGATION_RESULT=""
DELEGATION_ACTIVE="false"
INFERENCE_PIPELINE_ENABLED=$(_normalize_bool "${ENABLE_LOCAL_INFERENCE_PIPELINE:-false}")
LOCAL_DELEGATION_ENABLED=$(_normalize_bool "${ENABLE_LOCAL_DELEGATION:-false}")

if [[ "$INFERENCE_PIPELINE_ENABLED" == "true" ]] && [[ "$LOCAL_DELEGATION_ENABLED" == "true" ]]; then
    DELEGATION_HANDLER="${HOOKS_LIB}/local_delegation_handler.py"
    if [[ -f "$DELEGATION_HANDLER" ]]; then
        log "Local delegation enabled — classifying prompt (correlation=$CORRELATION_ID)"
        set +e
        DELEGATION_RESULT="$(run_with_timeout 35 $PYTHON_CMD "$DELEGATION_HANDLER" "$PROMPT_B64" "$CORRELATION_ID" 2>>"$LOG_FILE")"
        set -e

        # Validate output is parseable JSON starting with '{'
        if [[ -n "$DELEGATION_RESULT" ]] && echo "$DELEGATION_RESULT" | jq -e . >/dev/null 2>/dev/null; then
            DELEGATION_ACTIVE="$(echo "$DELEGATION_RESULT" | jq -r '.delegated // false' 2>/dev/null || echo 'false')"
        else
            log "WARNING: local_delegation_handler.py produced non-JSON output, skipping"
            DELEGATION_RESULT=""
            DELEGATION_ACTIVE="false"
        fi

        if [[ "$DELEGATION_ACTIVE" == "true" ]]; then
            DELEGATED_RESPONSE="$(echo "$DELEGATION_RESULT" | jq -r '.response // ""' 2>/dev/null || echo '')"
            DELEGATED_MODEL="$(echo "$DELEGATION_RESULT" | jq -r '.model // "local-model"' 2>/dev/null || echo 'local-model')"
            DELEGATED_LATENCY="$(echo "$DELEGATION_RESULT" | jq -r '.latency_ms // 0' 2>/dev/null || echo '0')"
            log "Delegation active: model=$DELEGATED_MODEL latency=${DELEGATED_LATENCY}ms"
            _TS_DEL="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
            echo "[$_TS_DEL] [UserPromptSubmit] DELEGATED model=$DELEGATED_MODEL latency_ms=$DELEGATED_LATENCY confidence=$(echo "$DELEGATION_RESULT" | jq -r '.confidence // 0')" >> "$TRACE_LOG"
        else
            DELEGATION_REASON="$(echo "$DELEGATION_RESULT" | jq -r '.reason // "unknown"' 2>/dev/null || echo 'unknown')"
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

# -----------------------------
# Agent Context Assembly (FIXED: Safe injection)
# -----------------------------
POLLY_DISPATCH_THRESHOLD="${POLLY_DISPATCH_THRESHOLD:-0.7}"
MEETS_THRESHOLD="$(awk -v conf="$CONFIDENCE" -v thresh="$POLLY_DISPATCH_THRESHOLD" 'BEGIN {print (conf >= thresh) ? "true" : "false"}')"

# Construct the core context without expanding internal variables immediately
# Use jq to safely combine the header/footer with the dynamic data to avoid quote issues
AGENT_CONTEXT=$(jq -rn \
    --arg emit_warn "$EMIT_HEALTH_WARNING" \
    --arg yaml "$AGENT_YAML_INJECTION" \
    --arg patterns "$LEARNED_PATTERNS" \
    --arg advisory "$PATTERN_ADVISORY" \
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
    (if $advisory != "" then $advisory + "\n" else "" end) +
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

# Final trace: total context injected
_TS3="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "[$_TS3] [UserPromptSubmit] INJECTED context_chars=${#AGENT_CONTEXT} meets_threshold=$MEETS_THRESHOLD agent=$AGENT_NAME" >> "$TRACE_LOG"

# Final Output via jq to ensure JSON integrity
printf %s "$INPUT" | jq --arg ctx "$AGENT_CONTEXT" \
    '.hookSpecificOutput.hookEventName = "UserPromptSubmit" |
     .hookSpecificOutput.additionalContext = $ctx' 2>>"$LOG_FILE" \
    || { log "ERROR: Final jq output failed, passing through raw input"; printf %s "$INPUT"; }
