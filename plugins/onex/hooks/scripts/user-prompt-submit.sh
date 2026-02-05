#!/bin/bash
# UserPromptSubmit Hook - Portable Plugin Version
# Provides: Agent routing, manifest injection, correlation tracking

set -euo pipefail

# -----------------------------
# Portable Plugin Configuration
# -----------------------------
# CLAUDE_PLUGIN_ROOT is set by Claude Code when loading plugins
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${HOOKS_DIR}/logs/hook-enhanced.log"

# Detect project root (go up from plugin location to find .env)
# Plugin is at: <project>/plugins/omniclaude-core/
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

# Set PYTHONPATH to include lib directories
export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

# Load environment variables from .env if available
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# Source shared functions (provides PYTHON_CMD, KAFKA_ENABLED, get_time_ms)
source "${HOOKS_DIR}/scripts/common.sh"

export ARCHON_INTELLIGENCE_URL="${ARCHON_INTELLIGENCE_URL:-http://localhost:8053}"

# Skip pattern injection if SessionStart already injected (OMN-1675)
# When true, UserPromptSubmit will check session marker before injecting patterns
SKIP_IF_SESSION_INJECTED="${OMNICLAUDE_SESSION_SKIP_IF_INJECTED:-true}"

# Preflight check for jq (required for claude-hook-event JSON construction)
SKIP_CLAUDE_HOOK_EVENT_EMIT=0
if ! command -v jq >/dev/null 2>&1; then
    log "ERROR: jq not found, skipping claude-hook-event emission"
    SKIP_CLAUDE_HOOK_EVENT_EMIT=1
fi
b64() { printf %s "$1" | base64; }

# Define timeout function (portable, works on macOS)
run_with_timeout() {
    local timeout_sec="$1"
    shift
    perl -e 'alarm shift; exec @ARGV' "$timeout_sec" "$@"
}

# Create tmp directory
mkdir -p "$PROJECT_ROOT/tmp"

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
if [ ${#PROMPT} -gt 100 ]; then
    log "Prompt: ${PROMPT:0:100}..."
else
    log "Prompt: ${PROMPT}"
fi
PROMPT_B64="$(b64 "$PROMPT")"

# Generate correlation ID
if command -v uuidgen >/dev/null 2>&1; then
    CORRELATION_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
else
    CORRELATION_ID="$($PYTHON_CMD -c 'import uuid; print(str(uuid.uuid4()))' | tr '[:upper:]' '[:lower:]')"
fi

# Log hook invocation (non-blocking)
(
    $PYTHON_CMD "${HOOKS_LIB}/log_hook_event.py" invocation \
        --hook-name "UserPromptSubmit" \
        --prompt "$PROMPT" \
        --correlation-id "$CORRELATION_ID" \
        2>>"$LOG_FILE" || true
) &

# Emit prompt.submitted event to Kafka (async, non-blocking)
# Uses emit_client_wrapper with daemon fan-out (OMN-1631)
SESSION_ID="$(printf %s "$INPUT" | jq -r '.sessionId // .session_id // ""' 2>/dev/null || echo "")"
if [[ -z "$SESSION_ID" ]]; then
    SESSION_ID="$CORRELATION_ID"
fi
PROMPT_LENGTH="${#PROMPT}"
PROMPT_PREVIEW="${PROMPT:0:100}"

if [[ "$KAFKA_ENABLED" == "true" ]]; then
    # Debug: Log environment for troubleshooting (only when OMNICLAUDE_DEBUG=true)
    if [[ "${OMNICLAUDE_DEBUG:-false}" == "true" ]]; then
        log "DEBUG: PYTHON_CMD=$PYTHON_CMD"
        log "DEBUG: KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-NOT_SET}"
        log "DEBUG: KAFKA_ENVIRONMENT=${KAFKA_ENVIRONMENT:-NOT_SET}"
    fi

    # -----------------------------------------------------------------------
    # UNIFIED EMISSION via emit_client_wrapper (OMN-1631)
    # -----------------------------------------------------------------------
    # Single emission call - daemon handles fan-out to both topics:
    #   1. Observability topic (prompt-submitted) - 100-char sanitized preview
    #   2. Intelligence topic (claude-hook-event) - full prompt for:
    #      - Intent classification
    #      - Pattern learning
    #      - RAG optimization
    #      - Workflow analysis
    #
    # PRIVACY CONTROLS (enforced at infrastructure level):
    #   - Topic-level ACLs restrict intelligence consumers
    #   - Network isolation for intelligence consumers
    #   - Aggressive retention policy (7-14 days recommended)
    #
    # See CLAUDE.md "Privacy Guidelines" section for full documentation.
    # -----------------------------------------------------------------------
    if [ "${SKIP_CLAUDE_HOOK_EVENT_EMIT:-0}" -ne 1 ]; then
        # Build payload with all fields needed for both topics
        PROMPT_PAYLOAD=$(jq -n \
            --arg session_id "$SESSION_ID" \
            --arg prompt "$PROMPT" \
            --arg prompt_preview "$PROMPT_PREVIEW" \
            --argjson prompt_length "$PROMPT_LENGTH" \
            --arg correlation_id "$CORRELATION_ID" \
            --arg event_type "UserPromptSubmit" \
            '{
                session_id: $session_id,
                prompt: $prompt,
                prompt_preview: $prompt_preview,
                prompt_length: $prompt_length,
                correlation_id: $correlation_id,
                event_type: $event_type
            }' 2>/dev/null)

        # Validate payload was constructed successfully
        if [[ -z "$PROMPT_PAYLOAD" || "$PROMPT_PAYLOAD" == "null" ]]; then
            log "WARNING: Failed to construct prompt payload (jq failed), skipping emission"
        else
            # Emit via daemon (async, non-blocking)
            # Daemon handles fan-out to observability + intelligence topics
            emit_via_daemon "prompt.submitted" "$PROMPT_PAYLOAD" 100 &

            log "Prompt event emission started via emit daemon (unified fan-out)"
        fi
    else
        log "Prompt event emission skipped (jq unavailable)"
    fi
fi

# -----------------------------
# Workflow Detection
# -----------------------------
WORKFLOW_TRIGGER="$(
    PROMPT_B64="$PROMPT_B64" HOOKS_LIB="$HOOKS_LIB" $PYTHON_CMD - <<\PY 2>>"$LOG_FILE" || echo ""
import os, sys, base64
sys.path.insert(0, os.environ["HOOKS_LIB"])
try:
    from agent_detector import AgentDetector
except Exception:
    sys.exit(0)
prompt = base64.b64decode(os.environ["PROMPT_B64"]).decode("utf-8", "replace")
if AgentDetector().detect_automated_workflow(prompt):
    print("AUTOMATED_WORKFLOW_DETECTED")
PY
)"
WORKFLOW_DETECTED="false"
if [[ "$WORKFLOW_TRIGGER" == "AUTOMATED_WORKFLOW_DETECTED" ]]; then
    log "Automated workflow trigger detected"
    WORKFLOW_DETECTED="true"
fi

# -----------------------------
# Agent Detection via Event-Based Routing
# -----------------------------
log "Calling event-based routing service via Kafka..."

ROUTING_RESULT="$($PYTHON_CMD "${HOOKS_LIB}/route_via_events_wrapper.py" "$PROMPT" "$CORRELATION_ID" 2>>"$LOG_FILE" || echo "")"

ROUTING_EXIT_CODE=$?
if [ $ROUTING_EXIT_CODE -ne 0 ] || [ -z "$ROUTING_RESULT" ]; then
    log "Event-based routing unavailable (exit code: $ROUTING_EXIT_CODE), using fallback"
    ROUTING_RESULT='{"selected_agent":"polymorphic-agent","confidence":0.5,"reasoning":"Event-based routing unavailable - using fallback","method":"fallback","latency_ms":0,"domain":"workflow_coordination","purpose":"Intelligent coordinator for development workflows"}'
    SERVICE_USED="false"
else
    log "Event-based routing responded successfully"
    SERVICE_USED="true"
fi

log "Routing result: ${ROUTING_RESULT:0:200}..."

# Parse JSON response
AGENT_NAME="$(echo "$ROUTING_RESULT" | jq -r '.selected_agent // "NO_AGENT_DETECTED"')"
CONFIDENCE="$(echo "$ROUTING_RESULT" | jq -r '.confidence // "0.5"')"
SELECTION_METHOD="$(echo "$ROUTING_RESULT" | jq -r '.method // "fallback"')"
SELECTION_REASONING="$(echo "$ROUTING_RESULT" | jq -r '.reasoning // ""')"
LATENCY_MS="$(echo "$ROUTING_RESULT" | jq -r '.latency_ms // "0"')"
AGENT_DOMAIN="$(echo "$ROUTING_RESULT" | jq -r '.domain // "general"')"
AGENT_PURPOSE="$(echo "$ROUTING_RESULT" | jq -r '.purpose // ""')"
DOMAIN_QUERY="$(echo "$ROUTING_RESULT" | jq -r '.domain_query // ""')"
IMPL_QUERY="$(echo "$ROUTING_RESULT" | jq -r '.implementation_query // ""')"
ROUTING_PATH="$(echo "$ROUTING_RESULT" | jq -r '.routing_path // "local"')"

log "Agent: $AGENT_NAME conf=$CONFIDENCE method=$SELECTION_METHOD routing_path=$ROUTING_PATH latency=${LATENCY_MS}ms (service=${SERVICE_USED})"

# Log routing decision (non-blocking)
if [[ -n "$AGENT_NAME" ]] && [[ "$AGENT_NAME" != "NO_AGENT_DETECTED" ]]; then
    (
        $PYTHON_CMD "${HOOKS_LIB}/log_hook_event.py" routing \
            --agent "$AGENT_NAME" \
            --confidence "$CONFIDENCE" \
            --method "$SELECTION_METHOD" \
            --routing-path "$ROUTING_PATH" \
            --correlation-id "$CORRELATION_ID" \
            --latency-ms "${LATENCY_MS%.*}" \
            --reasoning "${SELECTION_REASONING:0:200}" \
            --domain "$AGENT_DOMAIN" \
            --context "{\"service_used\":\"$SERVICE_USED\"}" \
            2>>"$LOG_FILE" || true
    ) &
fi

# -----------------------------
# Agent YAML Loading
# -----------------------------
AGENT_YAML_INJECTION=""
if [[ -n "$AGENT_NAME" ]] && [[ "$AGENT_NAME" != "NO_AGENT_DETECTED" ]]; then
    log "Loading agent YAML via simple_agent_loader.py..."

    INVOKE_INPUT="$(jq -n --arg agent "$AGENT_NAME" '{agent_name: $agent}')"
    INVOKE_RESULT="$(echo "$INVOKE_INPUT" | run_with_timeout 3 $PYTHON_CMD "${HOOKS_LIB}/simple_agent_loader.py" 2>>"$LOG_FILE" || echo '{}')"
    INVOKE_SUCCESS="$(echo "$INVOKE_RESULT" | jq -r '.success // false')"

    if [[ "$INVOKE_SUCCESS" == "true" ]]; then
        AGENT_YAML_INJECTION="$(echo "$INVOKE_RESULT" | jq -r '.context_injection // ""')"
        if [[ -n "$AGENT_YAML_INJECTION" ]]; then
            log "Agent YAML loaded successfully (${#AGENT_YAML_INJECTION} chars)"
        fi
    else
        log "WARNING: Agent invocation failed, using directive-only mode"
    fi
fi

# Handle no agent detected
if [[ "$AGENT_NAME" == "NO_AGENT_DETECTED" ]] || [[ -z "$AGENT_NAME" ]]; then
    log "No agent detected, passing through"
    printf %s "$INPUT"
    exit 0
fi

# -----------------------------
# Project Context
# -----------------------------
PROJECT_PATH="${CLAUDE_PROJECT_DIR:-$(pwd)}"
PROJECT_NAME="$(basename "$PROJECT_PATH")"
if command -v uuidgen >/dev/null 2>&1; then
    SESSION_ID="${CLAUDE_SESSION_ID:-$(uuidgen | tr '[:upper:]' '[:lower:]')}"
else
    SESSION_ID="${CLAUDE_SESSION_ID:-$($PYTHON_CMD -c 'import uuid; print(str(uuid.uuid4()))')}"
fi

log "Project: $PROJECT_NAME, Session: ${SESSION_ID:0:8}..., Correlation: ${CORRELATION_ID:0:8}..."

# -----------------------------
# Intelligence Requests (Non-blocking)
# -----------------------------
if [[ -n "${DOMAIN_QUERY:-}" ]]; then
    log "Publishing domain intelligence request to event bus"
    (
        $PYTHON_CMD "${HOOKS_LIB}/publish_intelligence_request.py" \
            --query-type "domain" \
            --query "$DOMAIN_QUERY" \
            --correlation-id "$CORRELATION_ID" \
            --agent-name "${AGENT_NAME:-unknown}" \
            --agent-domain "${AGENT_DOMAIN:-general}" \
            --output-file "$PROJECT_ROOT/tmp/agent_intelligence_domain_${CORRELATION_ID}.json" \
            --match-count 5 \
            --timeout-ms 500 \
            2>>"$LOG_FILE" || { rc=$?; log "WARNING: Domain intelligence request failed (exit=$rc)"; }
    ) &
fi

if [[ -n "${IMPL_QUERY:-}" ]]; then
    log "Publishing implementation intelligence request to event bus"
    (
        $PYTHON_CMD "${HOOKS_LIB}/publish_intelligence_request.py" \
            --query-type "implementation" \
            --query "$IMPL_QUERY" \
            --correlation-id "$CORRELATION_ID" \
            --agent-name "${AGENT_NAME:-unknown}" \
            --agent-domain "${AGENT_DOMAIN:-general}" \
            --output-file "$PROJECT_ROOT/tmp/agent_intelligence_impl_${CORRELATION_ID}.json" \
            --match-count 3 \
            --timeout-ms 500 \
            2>>"$LOG_FILE" || { rc=$?; log "WARNING: Implementation intelligence request failed (exit=$rc)"; }
    ) &
fi

# -----------------------------
# Check if SessionStart already injected (OMN-1675)
# -----------------------------
SESSION_ALREADY_INJECTED=false

if [[ "$SKIP_IF_SESSION_INJECTED" == "true" ]] && [[ -f "${HOOKS_LIB}/session_marker.py" ]]; then
    if $PYTHON_CMD "${HOOKS_LIB}/session_marker.py" check --session-id "${SESSION_ID}" 2>/dev/null; then
        SESSION_ALREADY_INJECTED=true
        log "Skipping pattern injection: SessionStart already injected for session ${SESSION_ID:0:8}..."
    fi
fi

# -----------------------------
# Learned Pattern Injection (OMN-1403)
# -----------------------------
LEARNED_PATTERNS=""
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

    # 2s timeout - patterns should be fast (file-based)
    # Try ONEX-compliant wrapper first, fall back to legacy injector
    # Use run_with_timeout for portability (works on macOS and Linux)
    if [[ -f "${HOOKS_LIB}/context_injection_wrapper.py" ]]; then
        log "Using ONEX-compliant context_injection_wrapper.py"
        PATTERN_RESULT="$(echo "$PATTERN_INPUT" | run_with_timeout 2 $PYTHON_CMD "${HOOKS_LIB}/context_injection_wrapper.py" 2>>"$LOG_FILE" || echo '{}')"
    elif [[ -f "${HOOKS_LIB}/learned_pattern_injector.py" ]]; then
        log "Falling back to legacy learned_pattern_injector.py"
        PATTERN_RESULT="$(echo "$PATTERN_INPUT" | run_with_timeout 2 $PYTHON_CMD "${HOOKS_LIB}/learned_pattern_injector.py" 2>>"$LOG_FILE" || echo '{}')"
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
# Agent Context Injection
# -----------------------------
AGENT_ROLE="${AGENT_NAME#agent-}"

# Confidence threshold for Polly dispatch (default: 0.7)
POLLY_DISPATCH_THRESHOLD="${POLLY_DISPATCH_THRESHOLD:-0.7}"

# Check if confidence meets dispatch threshold
CONFIDENCE_NUM="$(echo "$CONFIDENCE" | awk '{printf "%.2f", $1}')"
MEETS_THRESHOLD="$(awk -v conf="$CONFIDENCE_NUM" -v thresh="$POLLY_DISPATCH_THRESHOLD" 'BEGIN {print (conf >= thresh) ? "true" : "false"}')"

if [[ "$MEETS_THRESHOLD" == "true" ]] && [[ "$AGENT_NAME" == "polymorphic-agent" ]]; then
    # High confidence Polly routing - DISPATCH via /parallel-solve skill
    AGENT_CONTEXT="$(cat <<EOF
${AGENT_YAML_INJECTION}
${LEARNED_PATTERNS}

========================================================================
POLLY-FIRST DISPATCH DIRECTIVE
========================================================================

ROUTING DECISION: Dispatch via /parallel-solve skill
Confidence: ${CONFIDENCE} (threshold: ${POLLY_DISPATCH_THRESHOLD})
Method: ${SELECTION_METHOD} | Latency: ${LATENCY_MS}ms
Domain: ${AGENT_DOMAIN}
Purpose: ${AGENT_PURPOSE}

========================================================================
EXECUTION MODE: PARALLEL-SOLVE SKILL DISPATCH REQUIRED
========================================================================

You MUST use the Skill tool to invoke /parallel-solve for this work.

DISPATCH PATTERN:
\`\`\`
Skill(skill="parallel-solve", args="<user request summary>")
\`\`\`

The /parallel-solve skill will:
  1. Analyze the task and break it into independent subtasks
  2. Dispatch multiple polymorphic-agents IN PARALLEL (single message, multiple Task calls)
  3. Aggregate results and report back

DO:
  - Use the Skill tool with skill="parallel-solve"
  - Pass the user's request as args (or empty if context is sufficient)
  - Let /parallel-solve handle task decomposition and parallel execution

DO NOT:
  - Execute the work directly yourself
  - Use Task tool directly (use Skill tool with parallel-solve instead)
  - Dispatch tasks sequentially when they could be parallel

WHY /parallel-solve:
  - ENFORCES parallel execution (multiple Pollys in single message)
  - Automatic task decomposition and dependency analysis
  - Full ONEX capabilities and observability
  - Consistent execution patterns across all workflows

EXCEPTION - When to skip /parallel-solve:
  - Simple questions that need direct answers (no code changes)
  - Explicit user request to "do X directly" or "don't parallelize"
  - Single-file trivial changes (< 5 lines)

Intelligence Context Available:
- Domain: {REPO}/tmp/agent_intelligence_domain_${CORRELATION_ID}.json
- Implementation: {REPO}/tmp/agent_intelligence_impl_${CORRELATION_ID}.json
- Correlation ID: ${CORRELATION_ID}

Routing Reasoning: ${SELECTION_REASONING:0:200}
========================================================================
EOF
)"
else
    # Low confidence or non-Polly agent - respond directly (fallback behavior)
    AGENT_CONTEXT="$(cat <<EOF
${AGENT_YAML_INJECTION}
${LEARNED_PATTERNS}

========================================================================
AGENT CONTEXT (Low Confidence / Direct Mode)
========================================================================

DETECTED AGENT: ${AGENT_NAME}
Detected Role: ${AGENT_ROLE}
Confidence: ${CONFIDENCE} (below threshold ${POLLY_DISPATCH_THRESHOLD} or non-Polly agent)
Method: ${SELECTION_METHOD} | Latency: ${LATENCY_MS}ms
Domain: ${AGENT_DOMAIN}
Purpose: ${AGENT_PURPOSE}

$(if [[ -n "$AGENT_YAML_INJECTION" ]]; then
    echo "AGENT IDENTITY LOADED"
    echo "   Complete agent configuration injected above"
else
    echo "AGENT IDENTITY NOT LOADED"
    echo "   Agent detected but YAML not available (check logs)"
fi)

========================================================================
EXECUTION MODE: DIRECT RESPONSE (Fallback)
========================================================================

Confidence is below dispatch threshold or agent is not polymorphic-agent.
Respond directly using the detected agent's expertise.

Intelligence Context Available:
- Domain: {REPO}/tmp/agent_intelligence_domain_${CORRELATION_ID}.json
- Implementation: {REPO}/tmp/agent_intelligence_impl_${CORRELATION_ID}.json
- Correlation ID: ${CORRELATION_ID}

Routing Reasoning: ${SELECTION_REASONING:0:200}
========================================================================
EOF
)"
fi

# Output with injected context
printf %s "$INPUT" | jq --arg ctx "$AGENT_CONTEXT" \
    '.hookSpecificOutput.hookEventName = "UserPromptSubmit" |
     .hookSpecificOutput.additionalContext = $ctx' 2>>"$LOG_FILE"
