#!/bin/bash
# UserPromptSubmit Hook - Quote-Immune Rewrite (no single-quote characters)

set -euo pipefail

# -----------------------------
# Config
# -----------------------------
LOG_FILE="$HOME/.claude/hooks/hook-enhanced.log"
HOOKS_LIB="$HOME/.claude/hooks/lib"
export PYTHONPATH="${HOOKS_LIB}:${PYTHONPATH:-}"

export ARCHON_MCP_URL="${ARCHON_MCP_URL:-http://localhost:8051}"
export ARCHON_INTELLIGENCE_URL="${ARCHON_INTELLIGENCE_URL:-http://localhost:8053}"

# Database credentials for hook event logging (required from .env)
# Set DB_PASSWORD in your .env file or environment
export DB_PASSWORD="${DB_PASSWORD:-}"

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
# Agent detection (prompt via stdin)
# -----------------------------
AGENT_DETECTION="$(
  printf %s "$PROMPT" | python3 "${HOOKS_LIB}/hybrid_agent_selector.py" - \
    --enable-ai "${ENABLE_AI_AGENT_SELECTION:-true}" \
    --model-preference "${AI_MODEL_PREFERENCE:-5090}" \
    --confidence-threshold "${AI_AGENT_CONFIDENCE_THRESHOLD:-0.8}" \
    --timeout "${AI_SELECTION_TIMEOUT_MS:-3000}" \
    2>>"$LOG_FILE" || echo "NO_AGENT_DETECTED"
)"
log "Detection result: $AGENT_DETECTION"

if [[ "$AGENT_DETECTION" == "NO_AGENT_DETECTED" ]] || [[ -z "$AGENT_DETECTION" ]]; then
  log "No agent detected, logging failure..."

  # Log detection failure
  FAILURE_CORRELATION_ID="$(python3 -c 'import uuid; print(str(uuid.uuid4()))' | tr '[:upper:]' '[:lower:]')"
  FAILURE_PROMPT_B64="$(printf %s "${PROMPT:0:500}" | base64)"
  PROMPT_B64="$FAILURE_PROMPT_B64" FAILURE_CORRELATION_ID="$FAILURE_CORRELATION_ID" \
    PROJECT_PATH="${PROJECT_PATH:-}" PROJECT_NAME="${PROJECT_NAME:-}" SESSION_ID="${SESSION_ID:-}" \
    ENABLE_AI="$ENABLE_AI_AGENT_SELECTION" \
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
        failure_reason="No agent detected by hybrid selector",
        attempted_methods=[os.environ.get("ENABLE_AI") == "true" and "ai" or "trigger", "fuzzy"],
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
# Parse selector output
# -----------------------------
field() { printf %s "$AGENT_DETECTION" | grep "$1" | cut -d: -f2- || echo ""; }

AGENT_NAME="$(field "AGENT_DETECTED:" | tr -d " ")"
CONFIDENCE="$(field "CONFIDENCE:" | tr -d " ")"
SELECTION_METHOD="$(field "METHOD:" | tr -d " ")"
SELECTION_REASONING="$(field "REASONING:")"
LATENCY_MS="$(field "LATENCY_MS:" | tr -d " ")"
DOMAIN_QUERY="$(field "DOMAIN_QUERY:")"
IMPL_QUERY="$(field "IMPLEMENTATION_QUERY:")"
AGENT_DOMAIN="$(field "AGENT_DOMAIN:")"
AGENT_PURPOSE="$(field "AGENT_PURPOSE:")"

log "Agent: $AGENT_NAME conf=$CONFIDENCE method=$SELECTION_METHOD latency=${LATENCY_MS}ms"
log "Domain: $AGENT_DOMAIN"
log "Reasoning: ${SELECTION_REASONING:0:120}..."

# -----------------------------
# Project Context Extraction
# -----------------------------
PROJECT_PATH="${CLAUDE_PROJECT_DIR:-$(pwd)}"
PROJECT_NAME="$(basename "$PROJECT_PATH")"
SESSION_ID="${CLAUDE_SESSION_ID:-unknown}"

log "Project: $PROJECT_NAME, Session: ${SESSION_ID:0:8}..."

# -----------------------------
# Correlation ID
# -----------------------------
# Use uuidgen if available, fallback to Python
if command -v uuidgen >/dev/null 2>&1; then
    CORRELATION_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
else
    CORRELATION_ID="$(python3 -c 'import uuid; print(str(uuid.uuid4()))' | tr '[:upper:]' '[:lower:]')"
fi

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
    [[ -z "$LATENCY_INT" ]] && LATENCY_INT="0"

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
      --session-id "${SESSION_ID:-}" \
      >> "$LOG_FILE" 2>&1
  ) || log "Intent tracking failed (continuing)"
fi

# -----------------------------
# Background RAG queries
# -----------------------------
if [[ -n "${DOMAIN_QUERY:-}" ]]; then
  log "RAG domain query"
  (
    JSON="$(jq -n --arg q "$DOMAIN_QUERY" --arg ctx "general" --argjson n 5 '{query:$q, match_count:$n, context:$ctx}')"
    curl -s --max-time 2 -X POST "${ARCHON_MCP_URL}/api/rag/query" \
      -H "Content-Type: application/json" \
      --data-binary "$JSON" \
      > "/tmp/agent_intelligence_domain_${CORRELATION_ID}.json" 2>&1
  ) &
fi

if [[ -n "${IMPL_QUERY:-}" ]]; then
  log "RAG implementation query"
  (
    JSON="$(jq -n --arg q "$IMPL_QUERY" --arg ctx "general" --argjson n 3 '{query:$q, match_count:$n, context:$ctx}')"
    curl -s --max-time 2 -X POST "${ARCHON_MCP_URL}/api/rag/query" \
      -H "Content-Type: application/json" \
      --data-binary "$JSON" \
      > "/tmp/agent_intelligence_impl_${CORRELATION_ID}.json" 2>&1
  ) &
fi

# -----------------------------
# Context blocks - AGENT DISPATCH DIRECTIVE
# -----------------------------
# Strip "agent-" prefix to get the role/configuration name
AGENT_ROLE="${AGENT_NAME#agent-}"

AGENT_CONTEXT="$(cat <<EOF

========================================================================
🎯 AGENT DISPATCH DIRECTIVE (Auto-detected by hooks)
========================================================================

DETECTED AGENT: ${AGENT_NAME}
Detected Role: ${AGENT_ROLE}
Confidence: ${CONFIDENCE} | Method: ${SELECTION_METHOD} | Latency: ${LATENCY_MS}ms
Domain: ${AGENT_DOMAIN}
Purpose: ${AGENT_PURPOSE}

REQUIRED ACTION: Use the Task tool to dispatch to polymorphic-agent

Task Tool Configuration:
┌────────────────────────────────────────────────────────────────────┐
│ description: "${AGENT_DOMAIN} task execution"                       │
│ subagent_type: "polymorphic-agent"                                  │
│ prompt: "Load configuration for role '${AGENT_ROLE}' and execute:   │
│                                                                      │
│   ${PROMPT:0:200}...                                                │
│                                                                      │
│   Intelligence Context (pre-gathered by hooks):                    │
│   - Requested Role: ${AGENT_ROLE}                                   │
│   - Agent: ${AGENT_NAME}                                            │
│   - Domain: ${AGENT_DOMAIN}                                         │
│   - Purpose: ${AGENT_PURPOSE}                                       │
│   - Detection Confidence: ${CONFIDENCE}                             │
│   - Detection Method: ${SELECTION_METHOD}                           │
│   - Detection Reasoning: ${SELECTION_REASONING:0:120}...            │
│   - RAG Domain Intelligence: /tmp/agent_intelligence_domain_${CORRELATION_ID}.json │
│   - RAG Implementation Intelligence: /tmp/agent_intelligence_impl_${CORRELATION_ID}.json │
│   - Correlation ID: ${CORRELATION_ID}                               │
│   - Archon MCP: ${ARCHON_MCP_URL}                                   │
│                                                                      │
│   Framework Requirements:                                            │
│   - 47 mandatory functions (IC-001 to FI-004)                       │
│   - 23 quality gates validation                                     │
│   - Performance thresholds compliance                                │
│                                                                      │
│   The agent will handle execution and intelligence integration       │
│   for this task."                                                    │
└────────────────────────────────────────────────────────────────────┘

Why this dispatch is recommended:
- ${SELECTION_REASONING:0:200}

Alternative: If you prefer manual execution, the above intelligence context
is available for your direct use.
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
  OUTPUT_FILE="/tmp/workflow_${CORRELATION_ID}.log"

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
