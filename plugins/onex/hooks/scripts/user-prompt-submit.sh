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
        --arg prompt_preview "$(printf '%s' "${PROMPT:0:100}" | sed -E \
            -e 's/sk-[a-zA-Z0-9]{20,}/sk-***REDACTED***/g' \
            -e 's/AKIA[A-Z0-9]{16}/AKIA***REDACTED***/g' \
            -e 's/ghp_[a-zA-Z0-9]{36}/ghp_***REDACTED***/g' \
            -e 's/gho_[a-zA-Z0-9]{36}/gho_***REDACTED***/g' \
            -e 's/xox[baprs]-[a-zA-Z0-9-]+/xox*-***REDACTED***/g' \
            -e 's/Bearer [a-zA-Z0-9._-]{20,}/Bearer ***REDACTED***/g' \
            -e 's/-----BEGIN [A-Z ]*PRIVATE KEY-----/-----BEGIN ***REDACTED*** PRIVATE KEY-----/g')" \
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
else
    ROUTING_RESULT="$($PYTHON_CMD "${HOOKS_LIB}/route_via_events_wrapper.py" "$PROMPT" "$CORRELATION_ID" "5000" "$SESSION_ID" 2>>"$LOG_FILE" || echo "")"
fi

if [ -z "$ROUTING_RESULT" ]; then
    ROUTING_RESULT='{"selected_agent":"polymorphic-agent","confidence":0.5,"reasoning":"fallback","method":"fallback","domain":"workflow_coordination"}'
fi

# Parse JSON response
AGENT_NAME="$(echo "$ROUTING_RESULT" | jq -r '.selected_agent // "NO_AGENT_DETECTED"')"
CONFIDENCE="$(echo "$ROUTING_RESULT" | jq -r '.confidence // "0.5"')"
SELECTION_METHOD="$(echo "$ROUTING_RESULT" | jq -r '.method // "fallback"')"
AGENT_DOMAIN="$(echo "$ROUTING_RESULT" | jq -r '.domain // "general"')"
AGENT_PURPOSE="$(echo "$ROUTING_RESULT" | jq -r '.purpose // ""')"
SELECTION_REASONING="$(echo "$ROUTING_RESULT" | jq -r '.reasoning // ""')"
LATENCY_MS="$(echo "$ROUTING_RESULT" | jq -r '.latency_ms // "0"')"
CANDIDATES_JSON="$(echo "$ROUTING_RESULT" | jq -r '.candidates // "[]"')"

# -----------------------------
# Candidate List Injection & Pattern Injection
# -----------------------------
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
then read its full YAML from plugins/onex/agents/configs/{name}.yaml
and follow its behavioral directives.

CANDIDATES (ranked by score):
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
    if $PYTHON_CMD "${HOOKS_LIB}/session_marker.py" check --session-id "${SESSION_ID}" 2>/dev/null; then
        SESSION_ALREADY_INJECTED=true
    fi
fi

if [[ "$SESSION_ALREADY_INJECTED" == "false" ]] && [[ -n "$AGENT_NAME" ]] && [[ "$AGENT_NAME" != "NO_AGENT_DETECTED" ]]; then
    log "Loading learned patterns via context injection..."

    PATTERN_INPUT="$(jq -n \
        --arg agent "${AGENT_NAME:-}" \
        --arg domain "${AGENT_DOMAIN:-}" \
        --arg session "${SESSION_ID:-}" \
        --arg project "${PROJECT_NAME:-}" \
        --arg correlation "${CORRELATION_ID:-}" \
        --argjson max_patterns "${MAX_PATTERNS:-5}" \
        --argjson min_confidence "${MIN_CONFIDENCE:-0.7}" \
        '{
            agent_name: $agent,
            domain: $domain,
            session_id: $session,
            project: $project,
            correlation_id: $correlation,
            max_patterns: $max_patterns,
            min_confidence: $min_confidence
        }')"

    # 2s timeout - patterns should be fast (database-backed)
    # Use ONEX-compliant wrapper for pattern injection
    # Use run_with_timeout for portability (works on macOS and Linux)
    if [[ -f "${HOOKS_LIB}/context_injection_wrapper.py" ]]; then
        log "Using context_injection_wrapper.py"
        PATTERN_RESULT="$(echo "$PATTERN_INPUT" | run_with_timeout 2 $PYTHON_CMD "${HOOKS_LIB}/context_injection_wrapper.py" 2>>"$LOG_FILE" || echo '{}')"
    else
        log "INFO: No pattern injector found, skipping pattern injection"
        PATTERN_RESULT='{}'
    fi

    PATTERN_SUCCESS="$(echo "$PATTERN_RESULT" | jq -r '.success // false')"

    if [[ "$PATTERN_SUCCESS" == "true" ]]; then
        LEARNED_PATTERNS="$(echo "$PATTERN_RESULT" | jq -r '.patterns_context // ""')"
        PATTERN_COUNT="$(echo "$PATTERN_RESULT" | jq -r '.pattern_count // 0')"
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
# Agent Context Assembly (FIXED: Safe injection)
# -----------------------------
POLLY_DISPATCH_THRESHOLD="${POLLY_DISPATCH_THRESHOLD:-0.7}"
MEETS_THRESHOLD="$(awk -v conf="$CONFIDENCE" -v thresh="$POLLY_DISPATCH_THRESHOLD" 'BEGIN {print (conf >= thresh) ? "true" : "false"}')"

# Construct the core context without expanding internal variables immediately
# Use jq to safely combine the header/footer with the dynamic data to avoid quote issues
AGENT_CONTEXT=$(jq -rn \
    --arg yaml "$AGENT_YAML_INJECTION" \
    --arg patterns "$LEARNED_PATTERNS" \
    --arg name "$AGENT_NAME" \
    --arg conf "$CONFIDENCE" \
    --arg domain "$AGENT_DOMAIN" \
    --arg purpose "$AGENT_PURPOSE" \
    --arg reason "$SELECTION_REASONING" \
    --arg thresh "$POLLY_DISPATCH_THRESHOLD" \
    --arg meets "$MEETS_THRESHOLD" \
    '
    $yaml + "\n" + $patterns + "\n" +
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

# Final Output via jq to ensure JSON integrity
printf %s "$INPUT" | jq --arg ctx "$AGENT_CONTEXT" \
    '.hookSpecificOutput.hookEventName = "UserPromptSubmit" |
     .hookSpecificOutput.additionalContext = $ctx' 2>>"$LOG_FILE" \
    || { log "ERROR: Final jq output failed, passing through raw input"; printf %s "$INPUT"; }
