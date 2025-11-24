#!/bin/bash
# UserPromptSubmit Hook - Quote-Immune Rewrite (no single-quote characters)

set -euo pipefail

# -----------------------------
# Config
# -----------------------------
LOG_FILE="$HOME/.claude/hooks/hook-enhanced.log"
HOOKS_LIB="$HOME/.claude/hooks/lib"
export PYTHONPATH="${HOOKS_LIB}:${PYTHONPATH:-}"

# Detect project root dynamically
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Create tmp directory for this session
mkdir -p "$PROJECT_ROOT/tmp"

# Load environment variables from .env if available
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a  # automatically export all variables
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# Load database credentials for all scripts (sets PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE)
if [[ -f "$PROJECT_ROOT/scripts/db-credentials.sh" ]]; then
    source "$PROJECT_ROOT/scripts/db-credentials.sh" --silent
fi

export ARCHON_INTELLIGENCE_URL="${ARCHON_INTELLIGENCE_URL:-http://localhost:8053}"

# Kafka/Redpanda configuration for event-based routing
# IMPORTANT: KAFKA_BOOTSTRAP_SERVERS should be set in .env file
# If not set, we use a development fallback with an explicit warning
if [[ -z "$KAFKA_BOOTSTRAP_SERVERS" ]]; then
    # Development fallback (only used if .env not sourced)
    export KAFKA_BOOTSTRAP_SERVERS="192.168.86.200:29092"
    echo "WARNING: KAFKA_BOOTSTRAP_SERVERS not set in .env. Using development fallback: 192.168.86.200:29092" >&2
    echo "         For production, set KAFKA_BOOTSTRAP_SERVERS in .env file." >&2
fi

# Set KAFKA_BROKERS as alias to KAFKA_BOOTSTRAP_SERVERS (for backward compatibility)
export KAFKA_BROKERS="${KAFKA_BROKERS:-$KAFKA_BOOTSTRAP_SERVERS}"

# Database credentials for hook event logging (required from .env)
# Use POSTGRES_PASSWORD from .env for database connections
# Note: Using POSTGRES_PASSWORD directly (no alias)

log() { printf "[%s] %s\n" "$(date "+%Y-%m-%d %H:%M:%S")" "$*" >> "$LOG_FILE"; }
b64() { printf %s "$1" | base64; }

# -----------------------------
# Input
# -----------------------------
INPUT="$(cat)"
log "UserPromptSubmit hook triggered"

PROMPT="$(printf %s "$INPUT" | jq -r ".prompt // \"\"" 2>>"$LOG_FILE" || echo "")"
if [[ -z "$PROMPT" ]]; then
  log "ERROR: No prompt in input"
  printf %s "$INPUT"
  exit 0
fi
log "Prompt: ${PROMPT:0:100}..."
PROMPT_B64="$(b64 "$PROMPT")"

# Generate correlation ID early (before agent detection)
if command -v uuidgen >/dev/null 2>&1; then
    CORRELATION_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
else
    CORRELATION_ID="$(python3 -c 'import uuid; print(str(uuid.uuid4()))' | tr '[:upper:]' '[:lower:]')"
fi

# Log hook invocation (non-blocking)
(
  python3 "${HOOKS_LIB}/log_hook_event.py" invocation \
    --hook-name "UserPromptSubmit" \
    --prompt "$PROMPT" \
    --correlation-id "$CORRELATION_ID" \
    2>>"$LOG_FILE" || true
) &

# -----------------------------
# Workflow detection
# -----------------------------
WORKFLOW_TRIGGER="$(
  PROMPT_B64="$PROMPT_B64" HOOKS_LIB="$HOOKS_LIB" python3 - <<\PY 2>>"$LOG_FILE" || echo ""
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
# Agent detection via Event-Based Routing
# -----------------------------
log "Calling event-based routing service via Kafka..."

# Call event-based routing wrapper (replaces HTTP call to port 8055)
ROUTING_RESULT="$(python3 "${HOOKS_LIB}/route_via_events_wrapper.py" "$PROMPT" "$CORRELATION_ID" 2>>"$LOG_FILE" || echo "")"

# Check if routing call succeeded
ROUTING_EXIT_CODE=$?
if [ $ROUTING_EXIT_CODE -ne 0 ] || [ -z "$ROUTING_RESULT" ]; then
  log "Event-based routing unavailable (exit code: $ROUTING_EXIT_CODE), using fallback"

  # Log routing error (non-blocking)
  (
    python3 "${HOOKS_LIB}/log_hook_event.py" error \
      --hook-name "UserPromptSubmit" \
      --error-message "Event-based routing service unavailable (exit code: $ROUTING_EXIT_CODE)" \
      --error-type "ServiceUnavailable" \
      --correlation-id "$CORRELATION_ID" \
      --context "{\"service\":\"event-based-routing\",\"exit_code\":$ROUTING_EXIT_CODE}" \
      2>>"$LOG_FILE" || true
  ) &

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

# Extract queries if available
DOMAIN_QUERY="$(echo "$ROUTING_RESULT" | jq -r '.domain_query // ""')"
IMPL_QUERY="$(echo "$ROUTING_RESULT" | jq -r '.implementation_query // ""')"

log "Agent: $AGENT_NAME conf=$CONFIDENCE method=$SELECTION_METHOD latency=${LATENCY_MS}ms (service=${SERVICE_USED})"
log "Domain: $AGENT_DOMAIN"
log "Reasoning: ${SELECTION_REASONING:0:120}..."

# Log routing decision (non-blocking)
if [[ -n "$AGENT_NAME" ]] && [[ "$AGENT_NAME" != "NO_AGENT_DETECTED" ]]; then
  (
    python3 "${HOOKS_LIB}/log_hook_event.py" routing \
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
# Agent Invocation (NEW - Migration 015)
# -----------------------------
if [[ -n "$AGENT_NAME" ]] && [[ "$AGENT_NAME" != "NO_AGENT_DETECTED" ]]; then
  log "Loading agent YAML via simple_agent_loader.py..."

  # Prepare invocation input JSON with detected agent name
  INVOKE_INPUT="$(jq -n \
    --arg agent "$AGENT_NAME" \
    '{agent_name: $agent}')"

  # Call simple agent loader (lightweight, no framework dependencies)
  INVOKE_RESULT="$(echo "$INVOKE_INPUT" | timeout 3 python3 "${HOOKS_LIB}/simple_agent_loader.py" 2>>"$LOG_FILE" || echo '{}')"

  # Check if invocation succeeded
  INVOKE_SUCCESS="$(echo "$INVOKE_RESULT" | jq -r '.success // false')"

  if [[ "$INVOKE_SUCCESS" == "true" ]]; then
    # Extract agent YAML injection
    AGENT_YAML_INJECTION="$(echo "$INVOKE_RESULT" | jq -r '.context_injection // ""')"

    if [[ -n "$AGENT_YAML_INJECTION" ]]; then
      log "Agent YAML loaded successfully (${#AGENT_YAML_INJECTION} chars)"
    else
      log "WARNING: Agent invocation succeeded but no YAML returned"
      AGENT_YAML_INJECTION=""
    fi
  else
    log "WARNING: Agent invocation failed, using directive-only mode"
    INVOKE_ERROR="$(echo "$INVOKE_RESULT" | jq -r '.error // "Unknown error"')"
    log "Agent invocation error: ${INVOKE_ERROR}"
    AGENT_YAML_INJECTION=""
  fi
else
  AGENT_YAML_INJECTION=""
fi

# Handle no agent detected
if [[ "$AGENT_NAME" == "NO_AGENT_DETECTED" ]] || [[ -z "$AGENT_NAME" ]]; then
  log "No agent detected, logging failure..."

  # Log no agent detected error (non-blocking)
  (
    python3 "${HOOKS_LIB}/log_hook_event.py" error \
      --hook-name "UserPromptSubmit" \
      --error-message "No agent detected by router service" \
      --error-type "NoAgentDetected" \
      --correlation-id "$CORRELATION_ID" \
      --context "{\"service_used\":\"$SERVICE_USED\",\"method\":\"$SELECTION_METHOD\"}" \
      2>>"$LOG_FILE" || true
  ) &

  # Log detection failure
  FAILURE_CORRELATION_ID="$(python3 -c 'import uuid; print(str(uuid.uuid4()))' | tr '[:upper:]' '[:lower:]')"
  FAILURE_PROMPT_B64="$(printf %s "${PROMPT:0:500}" | base64)"
  PROMPT_B64="$FAILURE_PROMPT_B64" FAILURE_CORRELATION_ID="$FAILURE_CORRELATION_ID" \
    PROJECT_PATH="${PROJECT_PATH:-}" PROJECT_NAME="${PROJECT_NAME:-}" SESSION_ID="${SESSION_ID:-}" \
    SERVICE_USED="$SERVICE_USED" \
    python3 - <<'PYFAIL' 2>>"$LOG_FILE" || log "WARNING: Failed to log detection failure"
import sys
import os
import base64
sys.path.insert(0, os.path.expanduser("~/.claude/hooks/lib"))
try:
    from hook_event_adapter import get_hook_event_adapter

    # Safely decode base64-encoded prompt
    user_request = base64.b64decode(os.environ.get("PROMPT_B64", "")).decode("utf-8", "replace")

    adapter = get_hook_event_adapter()
    adapter.publish_detection_failure(
        user_request=user_request,
        failure_reason="No agent detected by router service" if os.environ.get("SERVICE_USED") == "true" else "Router service unavailable",
        attempted_methods=["router_service" if os.environ.get("SERVICE_USED") == "true" else "fallback"],
        correlation_id=os.environ.get("FAILURE_CORRELATION_ID"),
        project_path=os.environ.get("PROJECT_PATH"),
        project_name=os.environ.get("PROJECT_NAME"),
        session_id=os.environ.get("SESSION_ID")
    )
except Exception as e:
    print(f"Error logging detection failure: {e}", file=sys.stderr)
PYFAIL

  log "No agent detected, passing through"
  printf %s "$INPUT"
  exit 0
fi

# -----------------------------
# Project Context Extraction
# -----------------------------
PROJECT_PATH="${CLAUDE_PROJECT_DIR:-$(pwd)}"
PROJECT_NAME="$(basename "$PROJECT_PATH")"
# Generate UUID if SESSION_ID not set (avoid 'unknown' string violating DB schema)
if command -v uuidgen >/dev/null 2>&1; then
    SESSION_ID="${CLAUDE_SESSION_ID:-$(uuidgen | tr '[:upper:]' '[:lower:]')}"
else
    SESSION_ID="${CLAUDE_SESSION_ID:-$(python3 -c 'import uuid; print(str(uuid.uuid4()))')}"
fi

log "Project: $PROJECT_NAME, Session: ${SESSION_ID:0:8}..., Correlation: ${CORRELATION_ID:0:8}..."

# -----------------------------
# Log Routing Decision with Project Context
# -----------------------------
if [[ -n "$AGENT_NAME" ]] && [[ "$AGENT_NAME" != "NO_AGENT_DETECTED" ]]; then
  log "Logging routing decision for project $PROJECT_NAME..."

  # Check if the skill exists before attempting to log
  SKILL_PATH="$HOME/.claude/skills/agent-tracking/log-routing-decision/execute_unified.py"
  if [[ -f "$SKILL_PATH" ]]; then
    # Convert latency to integer (remove decimal part)
    LATENCY_INT="${LATENCY_MS%.*}"
    # Validate numeric value with regex
    if [[ ! "$LATENCY_INT" =~ ^[0-9]+$ ]]; then
      LATENCY_INT="0"
    fi

    python3 "$SKILL_PATH" \
        --agent "$AGENT_NAME" \
        --confidence "$CONFIDENCE" \
        --strategy "$SELECTION_METHOD" \
        --latency-ms "$LATENCY_INT" \
        --user-request "${PROMPT:0:200}" \
        --project-path "$PROJECT_PATH" \
        --project-name "$PROJECT_NAME" \
        --session-id "$SESSION_ID" \
        --correlation-id "$CORRELATION_ID" \
        --reasoning "${SELECTION_REASONING:0:500}" \
        2>>"$LOG_FILE" || log "WARNING: Failed to log routing decision"
  else
    log "WARNING: Routing decision logging skill not found at $SKILL_PATH"
  fi

  # Log agent action (agent dispatch)
  ACTION_SKILL_PATH="$HOME/.claude/skills/agent-tracking/log-agent-action/execute_unified.py"
  if [[ -f "$ACTION_SKILL_PATH" ]]; then
    log "Logging agent dispatch action..."

    # Build action details JSON
    ACTION_DETAILS="$(jq -n \
      --arg method "$SELECTION_METHOD" \
      --arg confidence "$CONFIDENCE" \
      --arg latency "$LATENCY_MS" \
      '{selection_method: $method, confidence: $confidence, latency_ms: $latency}')"

    python3 "$ACTION_SKILL_PATH" \
        --agent "$AGENT_NAME" \
        --action-type "decision" \
        --action-name "agent_selected" \
        --details "$ACTION_DETAILS" \
        --correlation-id "$CORRELATION_ID" \
        --project-path "$PROJECT_PATH" \
        --project-name "$PROJECT_NAME" \
        --working-directory "$(pwd)" \
        2>>"$LOG_FILE" || log "WARNING: Failed to log agent action"
  fi

  # Log UserPromptSubmit event to hook_events table
  log "Logging UserPromptSubmit event to hook_events table..."
  (
    PROMPT_B64="$PROMPT_B64" HOOKS_LIB="$HOOKS_LIB" \
    AGENT_NAME="$AGENT_NAME" AGENT_DOMAIN="$AGENT_DOMAIN" \
    CORRELATION_ID="$CORRELATION_ID" SELECTION_METHOD="$SELECTION_METHOD" \
    CONFIDENCE="$CONFIDENCE" LATENCY_MS="$LATENCY_MS" \
    SELECTION_REASONING="$SELECTION_REASONING" \
    python3 - <<'PYLOG' 2>>"$LOG_FILE" || log "WARNING: Failed to log UserPromptSubmit to hook_events"
import sys
import os
import base64
sys.path.insert(0, os.path.expanduser("~/.claude/hooks/lib"))
try:
    from hook_event_logger import get_logger

    # Decode prompt
    prompt = base64.b64decode(os.environ.get("PROMPT_B64", "")).decode("utf-8", "replace")

    # Get logger and log event
    logger = get_logger()
    event_id = logger.log_userprompt(
        prompt=prompt,
        agent_detected=os.environ.get("AGENT_NAME"),
        agent_domain=os.environ.get("AGENT_DOMAIN"),
        correlation_id=os.environ.get("CORRELATION_ID"),
        detection_method=os.environ.get("SELECTION_METHOD"),
        confidence=float(os.environ.get("CONFIDENCE", "0.0")),
        latency_ms=float(os.environ.get("LATENCY_MS", "0.0")),
        reasoning=os.environ.get("SELECTION_REASONING"),
    )
    if event_id:
        print(f"✓ UserPromptSubmit event logged: {event_id}", file=sys.stderr)
    else:
        print("✗ Failed to log UserPromptSubmit event", file=sys.stderr)
except Exception as e:
    print(f"Error logging UserPromptSubmit: {e}", file=sys.stderr)
PYLOG
  ) &
fi

# -----------------------------
# Metadata extraction
# -----------------------------
if [[ -f "${HOOKS_LIB}/metadata_extractor.py" ]] && [[ -f "${HOOKS_LIB}/correlation_manager.py" ]]; then
  log "Extracting enhanced metadata"
  METADATA_JSON="$(
    PROMPT_B64="$PROMPT_B64" HOOKS_LIB="$HOOKS_LIB" AGENT_NAME="$AGENT_NAME" python3 - <<\PY 2>>"$LOG_FILE" || echo "{}"
import os, sys, json, base64
sys.path.insert(0, os.environ["HOOKS_LIB"])
try:
    from metadata_extractor import MetadataExtractor
    from correlation_manager import get_correlation_context
except Exception:
    print("{}"); raise SystemExit
prompt = base64.b64decode(os.environ["PROMPT_B64"]).decode("utf-8", "replace")
extractor = MetadataExtractor(working_dir=os.getcwd())
metadata = extractor.extract_all(
    prompt=prompt,
    agent_name=os.environ.get("AGENT_NAME") or None,
    correlation_context=get_correlation_context()
)
print(json.dumps(metadata))
PY
  )"
  log "Metadata extracted"
else
  METADATA_JSON="{}"
  log "Metadata extraction skipped"
fi

# -----------------------------
# Intent tracking
# -----------------------------
if [[ -n "${AGENT_NAME:-}" ]] && [[ -n "${AGENT_DOMAIN:-}" ]] && [[ -n "${AGENT_PURPOSE:-}" ]]; then
  log "Tracking intent for $AGENT_NAME"
  (
    printf %s "$PROMPT" | timeout 3 python3 "${HOOKS_LIB}/track_intent.py" \
      --prompt - \
      --agent "$AGENT_NAME" \
      --domain "$AGENT_DOMAIN" \
      --purpose "$AGENT_PURPOSE" \
      --correlation-id "$CORRELATION_ID" \
      --session-id "$SESSION_ID" \
      >> "$LOG_FILE" 2>&1
  ) || log "Intent tracking failed (continuing)"
fi

# -----------------------------
# Event Bus Intelligence Requests
# -----------------------------
if [[ -n "${DOMAIN_QUERY:-}" ]]; then
  log "Publishing domain intelligence request to event bus"
  (
    python3 "${HOOKS_LIB}/publish_intelligence_request.py" \
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
    python3 "${HOOKS_LIB}/publish_intelligence_request.py" \
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
# System Manifest Injection
# -----------------------------
log "Loading system manifest for agent context..."

# Use manifest_loader.py to avoid heredoc quoting issues
MANIFEST_LOADER="$HOME/.claude/hooks/lib/manifest_loader.py"
if [[ ! -f "$MANIFEST_LOADER" ]]; then
  # Fallback to hooks directory
  MANIFEST_LOADER="${HOOKS_LIB}/../manifest_loader.py"
fi

SYSTEM_MANIFEST="$(PROJECT_PATH="$PROJECT_PATH" CORRELATION_ID="$CORRELATION_ID" AGENT_NAME="${AGENT_NAME:-unknown}" python3 "$MANIFEST_LOADER" --correlation-id "$CORRELATION_ID" --agent-name "${AGENT_NAME:-unknown}" 2>>"$LOG_FILE" || echo "System Manifest: Not available")"

if [[ -n "$SYSTEM_MANIFEST" ]]; then
  log "System manifest loaded successfully (${#SYSTEM_MANIFEST} chars)"
else
  log "System manifest not available, continuing without it"
  SYSTEM_MANIFEST="System Manifest: Not available"
fi

# -----------------------------
# Context blocks - AGENT DISPATCH DIRECTIVE
# -----------------------------
# Strip "agent-" prefix to get the role/configuration name
AGENT_ROLE="${AGENT_NAME#agent-}"

AGENT_CONTEXT="$(cat <<EOF
${AGENT_YAML_INJECTION}

========================================================================
🎯 MANDATORY AGENT DISPATCH DIRECTIVE
========================================================================

⚠️  CRITICAL INSTRUCTION: DO NOT USE TASK TOOL

DETECTED AGENT: ${AGENT_NAME}
Detected Role: ${AGENT_ROLE}
Confidence: ${CONFIDENCE} | Method: ${SELECTION_METHOD} | Latency: ${LATENCY_MS}ms
Domain: ${AGENT_DOMAIN}
Purpose: ${AGENT_PURPOSE}

$(if [[ -n "$AGENT_YAML_INJECTION" ]]; then
  echo "✅ AGENT IDENTITY LOADED - Polymorphic transformation active"
  echo "   Complete agent configuration injected above"
else
  echo "⚠️  AGENT IDENTITY NOT LOADED - Directive mode only"
  echo "   Agent detected but YAML not available (check logs)"
fi)

========================================================================
⚠️  EXECUTION MODE: DIRECT AGENT RESPONSE REQUIRED
========================================================================

You MUST respond directly as the ${AGENT_NAME} agent.

DO NOT:
  ❌ Use the Task tool to delegate
  ❌ Launch a separate agent
  ❌ Dispatch this to another process

DO:
  ✅ Assume the ${AGENT_ROLE} identity immediately
  ✅ Use the agent capabilities defined above
  ✅ Respond directly using agent expertise
  ✅ Apply agent-specific workflows and methods

ROUTING COMPLETE - You are now ${AGENT_NAME}.

Intelligence Context Available:
┌────────────────────────────────────────────────────────────────────┐
│ Requested Role: ${AGENT_ROLE}                                       │
│ Agent: ${AGENT_NAME}                                                │
│ Domain: ${AGENT_DOMAIN}                                             │
│ Detection Confidence: ${CONFIDENCE}                                 │
│ Detection Method: ${SELECTION_METHOD}                               │
│ Detection Reasoning: ${SELECTION_REASONING:0:150}                   │
│                                                                      │
│ RAG Intelligence:                                                   │
│   - Domain: {REPO}/tmp/agent_intelligence_domain_${CORRELATION_ID}.json   │
│   - Implementation: {REPO}/tmp/agent_intelligence_impl_${CORRELATION_ID}.json │
│                                                                      │
│ Correlation ID: ${CORRELATION_ID}                                   │
│                                                                      │
│ Framework Requirements:                                              │
│   - 47 mandatory functions (IC-001 to FI-004)                       │
│   - 23 quality gates validation                                     │
│   - Performance thresholds compliance                                │
└────────────────────────────────────────────────────────────────────┘

Routing Reasoning: ${SELECTION_REASONING:0:200}
========================================================================

${SYSTEM_MANIFEST}

========================================================================
EOF
)"

WORKFLOW_CONTEXT=""
if [[ "$WORKFLOW_DETECTED" == "true" ]]; then
  log "Launching automated workflow with output capture"

  # Get repository root dynamically
  REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "${WORKSPACE_PATH:-$PWD}")"

  # Create workflow input JSON
  WORKFLOW_JSON="$(jq -n \
    --arg prompt "$PROMPT" \
    --arg workspace "$REPO_ROOT" \
    --arg corr_id "$CORRELATION_ID" \
    '{user_prompt: $prompt, workspace_path: $workspace, correlation_id: $corr_id}')"

  # Launch dispatch_runner.py and capture output to log only
  OUTPUT_FILE="$PROJECT_ROOT/tmp/workflow_${CORRELATION_ID}.log"

  (
    cd "$REPO_ROOT/agents/parallel_execution" 2>/dev/null || cd "${WORKSPACE_PATH:-$PWD}/agents/parallel_execution"
    echo "$WORKFLOW_JSON" | python3 dispatch_runner.py --enable-context --enable-quorum > "$OUTPUT_FILE" 2>&1
  ) &
  WORKFLOW_PID=$!

  log "Workflow launched with PID $WORKFLOW_PID, output: $OUTPUT_FILE"

  WORKFLOW_CONTEXT="$(cat <<EOF

========================================================================
AUTOMATED WORKFLOW LAUNCHED
========================================================================

The Python-based workflow system is executing your request:
  "${PROMPT:0:120}..."

Configuration:
  - Multi-agent orchestration (Gemini/ZAI models)
  - Task breakdown with Architect agent
  - Parallel execution with coordination

Process ID: $WORKFLOW_PID
Log File: $OUTPUT_FILE
Correlation ID: $CORRELATION_ID

Monitor progress: tail -f $OUTPUT_FILE

The workflow runs independently. Results will be available in the log.
========================================================================
EOF
)"
fi

# Combine workflow and agent context
FINAL_CONTEXT="${WORKFLOW_CONTEXT}${AGENT_CONTEXT}"

# Output with injected context via hookSpecificOutput.additionalContext
printf %s "$INPUT" | jq --arg ctx "$FINAL_CONTEXT" \
  '.hookSpecificOutput.hookEventName = "UserPromptSubmit" |
   .hookSpecificOutput.additionalContext = $ctx' 2>>"$LOG_FILE"
