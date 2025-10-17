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

PROMPT="$(printf %s "$INPUT" | jq -r ".prompt // \"\"")"
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
  log "No agent detected, passing through"
  printf %s "$INPUT"
  exit 0
fi

# -----------------------------
# Parse selector output
# -----------------------------
field() { printf %s "$AGENT_DETECTION" | grep "$1" | cut -d: -f2-; }

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
# Correlation ID
# -----------------------------
CORRELATION_ID="$(uuidgen | tr "[:upper:]" "[:lower:]")"

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
if [[ -n "${AGENT_NAME:-}" ]]; then
  log "Tracking intent for $AGENT_NAME"
  printf %s "$PROMPT" | python3 "${HOOKS_LIB}/track_intent.py" \
    --prompt - \
    --agent "$AGENT_NAME" \
    --domain "$AGENT_DOMAIN" \
    --purpose "$AGENT_PURPOSE" \
    --correlation-id "$CORRELATION_ID" \
    --session-id "${SESSION_ID:-}" \
    >> "$LOG_FILE" 2>&1 || log "Intent tracking failed (continuing)"
fi

# -----------------------------
# Background RAG queries
# -----------------------------
if [[ -n "${DOMAIN_QUERY:-}" ]]; then
  log "RAG domain query"
  (
    JSON="$(jq -n --arg q "$DOMAIN_QUERY" --arg ctx "general" --argjson n 5 '{query:$q, match_count:$n, context:$ctx}')"
    curl -s -X POST "${ARCHON_MCP_URL}/api/rag/query" \
      -H "Content-Type: application/json" \
      --data-binary "$JSON" \
      > "/tmp/agent_intelligence_domain_${CORRELATION_ID}.json" 2>&1
  ) &
fi

if [[ -n "${IMPL_QUERY:-}" ]]; then
  log "RAG implementation query"
  (
    JSON="$(jq -n --arg q "$IMPL_QUERY" --arg ctx "general" --argjson n 3 '{query:$q, match_count:$n, context:$ctx}')"
    curl -s -X POST "${ARCHON_MCP_URL}/api/rag/query" \
      -H "Content-Type: application/json" \
      --data-binary "$JSON" \
      > "/tmp/agent_intelligence_impl_${CORRELATION_ID}.json" 2>&1
  ) &
fi

# -----------------------------
# Context blocks - AGENT DISPATCH DIRECTIVE
# -----------------------------
AGENT_CONTEXT="$(cat <<EOF

========================================================================
🎯 AGENT DISPATCH DIRECTIVE (Auto-detected by hooks)
========================================================================

DETECTED AGENT: ${AGENT_NAME}
Confidence: ${CONFIDENCE} | Method: ${SELECTION_METHOD} | Latency: ${LATENCY_MS}ms
Domain: ${AGENT_DOMAIN}
Purpose: ${AGENT_PURPOSE}

REQUIRED ACTION: Use the Task tool to dispatch this request to agent-workflow-coordinator

Task Tool Configuration:
┌────────────────────────────────────────────────────────────────────┐
│ description: "${AGENT_DOMAIN} task execution"                       │
│ subagent_type: "agent-workflow-coordinator"                         │
│ prompt: "Route to ${AGENT_NAME} and execute the following request: │
│                                                                      │
│   ${PROMPT:0:200}...                                                │
│                                                                      │
│   Intelligence Context (pre-gathered by hooks):                    │
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
│   The agent-workflow-coordinator will handle routing, execution,    │
│   and intelligence integration for this task."                       │
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

  # Create workflow input JSON
  WORKFLOW_JSON="$(jq -n \
    --arg prompt "$PROMPT" \
    --arg workspace "/Volumes/PRO-G40/Code/omniclaude" \
    --arg corr_id "$CORRELATION_ID" \
    '{user_prompt: $prompt, workspace_path: $workspace, correlation_id: $corr_id}')"

  # Launch dispatch_runner.py and capture output to log only
  OUTPUT_FILE="/tmp/workflow_${CORRELATION_ID}.log"

  (
    cd /Volumes/PRO-G40/Code/omniclaude/agents/parallel_execution
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
   .hookSpecificOutput.additionalContext = $ctx'
