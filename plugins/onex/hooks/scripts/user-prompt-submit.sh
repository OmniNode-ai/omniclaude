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

log() { printf "[%s] %s\n" "$(date "+%Y-%m-%d %H:%M:%S")" "$*" >> "$LOG_FILE"; }
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
log "Prompt: ${PROMPT:0:100}..."
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
# Uses omniclaude-emit CLI with 250ms hard timeout
SESSION_ID="$(printf %s "$INPUT" | jq -r '.sessionId // .session_id // ""' 2>/dev/null || echo "")"
if [[ -z "$SESSION_ID" ]]; then
    SESSION_ID="$CORRELATION_ID"
fi
PROMPT_LENGTH="${#PROMPT}"
PROMPT_PREVIEW="${PROMPT:0:100}"

if [[ "$KAFKA_ENABLED" == "true" ]]; then
    (
        $PYTHON_CMD -m omniclaude.hooks.cli_emit prompt-submitted \
            --session-id "$SESSION_ID" \
            --preview "$PROMPT_PREVIEW" \
            --length "$PROMPT_LENGTH" \
            >> "$LOG_FILE" 2>&1 || log "Kafka emit failed (non-fatal)"
    ) &
    log "Prompt event emission started"
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

log "Agent: $AGENT_NAME conf=$CONFIDENCE method=$SELECTION_METHOD latency=${LATENCY_MS}ms (service=${SERVICE_USED})"

# Log routing decision (non-blocking)
if [[ -n "$AGENT_NAME" ]] && [[ "$AGENT_NAME" != "NO_AGENT_DETECTED" ]]; then
    (
        $PYTHON_CMD "${HOOKS_LIB}/log_hook_event.py" routing \
            --agent "$AGENT_NAME" \
            --confidence "$CONFIDENCE" \
            --method "$SELECTION_METHOD" \
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
            2>>"$LOG_FILE" || log "WARNING: Domain intelligence request failed"
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
            2>>"$LOG_FILE" || log "WARNING: Implementation intelligence request failed"
    ) &
fi

# -----------------------------
# Agent Context Injection
# -----------------------------
AGENT_ROLE="${AGENT_NAME#agent-}"

AGENT_CONTEXT="$(cat <<EOF
${AGENT_YAML_INJECTION}

========================================================================
MANDATORY AGENT DISPATCH DIRECTIVE
========================================================================

CRITICAL INSTRUCTION: DO NOT USE TASK TOOL

DETECTED AGENT: ${AGENT_NAME}
Detected Role: ${AGENT_ROLE}
Confidence: ${CONFIDENCE} | Method: ${SELECTION_METHOD} | Latency: ${LATENCY_MS}ms
Domain: ${AGENT_DOMAIN}
Purpose: ${AGENT_PURPOSE}

$(if [[ -n "$AGENT_YAML_INJECTION" ]]; then
    echo "AGENT IDENTITY LOADED - Polymorphic transformation active"
    echo "   Complete agent configuration injected above"
else
    echo "AGENT IDENTITY NOT LOADED - Directive mode only"
    echo "   Agent detected but YAML not available (check logs)"
fi)

========================================================================
EXECUTION MODE: DIRECT AGENT RESPONSE REQUIRED
========================================================================

You MUST respond directly as the ${AGENT_NAME} agent.

DO NOT:
  - Use the Task tool to delegate
  - Launch a separate agent
  - Dispatch this to another process

DO:
  - Assume the ${AGENT_ROLE} identity immediately
  - Use the agent capabilities defined above
  - Respond directly using agent expertise
  - Apply agent-specific workflows and methods

ROUTING COMPLETE - You are now ${AGENT_NAME}.

Intelligence Context Available:
- Domain: {REPO}/tmp/agent_intelligence_domain_${CORRELATION_ID}.json
- Implementation: {REPO}/tmp/agent_intelligence_impl_${CORRELATION_ID}.json
- Correlation ID: ${CORRELATION_ID}

Routing Reasoning: ${SELECTION_REASONING:0:200}
========================================================================
EOF
)"

# Output with injected context
printf %s "$INPUT" | jq --arg ctx "$AGENT_CONTEXT" \
    '.hookSpecificOutput.hookEventName = "UserPromptSubmit" |
     .hookSpecificOutput.additionalContext = $ctx' 2>>"$LOG_FILE"
