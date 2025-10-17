# Agent Dispatch Directive System

## Overview

The Claude Code hooks now provide **actionable dispatch directives**, not just passive detection. When an agent is detected, the hook generates complete Task tool configuration for immediate execution.

## Architecture Flow

```
User Prompt
    ↓
UserPromptSubmit Hook (bash + Python)
    ↓
┌─────────────────────────────────────┐
│ 1. Hybrid Agent Detection           │
│    - Pattern matching (~1-2ms)      │
│    - Trigger matching (~2-5ms)      │
│    - AI selection (optional, ~500ms)│
├─────────────────────────────────────┤
│ 2. Intelligence Gathering           │
│    - RAG domain query (background)  │
│    - RAG implementation query       │
│    - Metadata extraction            │
│    - Correlation ID generation      │
├─────────────────────────────────────┤
│ 3. Dispatch Directive Generation    │
│    - Task tool configuration        │
│    - Complete intelligence package  │
│    - Framework requirements         │
│    - Actionable instructions        │
└─────────────────────────────────────┘
    ↓
Claude Code receives directive
    ↓
CHOICE:
├─ Option A (Recommended): Execute Task tool as directed
│      ↓
│  agent-workflow-coordinator
│      ↓
│  Detected agent execution
│      ↓
│  Results
│
└─ Option B: Manual execution with intelligence context
```

## What Changed

### Before: Passive Context Injection

```markdown
---
[Agent Framework Context - Auto-injected by hooks]

Agent Detected: agent-devops-infrastructure
Agent Domain: devops_infrastructure
Agent Purpose: Container orchestration...

[Just informational context]
```

**Problem**: Claude Code receives detection info but must manually decide what to do.

### After: Actionable Dispatch Directive

```markdown
========================================================================
🎯 AGENT DISPATCH DIRECTIVE (Auto-detected by hooks)
========================================================================

DETECTED AGENT: agent-devops-infrastructure
Confidence: 0.8 | Method: trigger | Latency: 5ms

REQUIRED ACTION: Use the Task tool to dispatch to agent-workflow-coordinator

Task Tool Configuration:
┌────────────────────────────────────────────────┐
│ description: "devops_infrastructure execution" │
│ subagent_type: "agent-workflow-coordinator"    │
│ prompt: "Route to agent-devops-infrastructure: │
│   [Complete enriched context...]"              │
└────────────────────────────────────────────────┘

Why this dispatch is recommended:
- [Detection reasoning...]
========================================================================
```

**Benefit**: Claude Code has complete, ready-to-execute Task tool configuration.

## Components

### 1. Hybrid Agent Selector
**File**: `claude_hooks/lib/hybrid_agent_selector.py`

3-stage detection pipeline:
- **Stage 1**: Pattern matching (explicit @agent-name patterns)
- **Stage 2**: Trigger matching (keyword-based from agent registry)
- **Stage 3**: AI selection (semantic analysis via local/cloud models)

**Fixed bugs**:
- ✅ Handle capabilities as dict OR list (was failing on list format)
- ✅ Graceful error handling for malformed agent configs

### 2. UserPromptSubmit Hook
**File**: `claude_hooks/user-prompt-submit.sh`

**Enhanced sections**:
```bash
# Agent detection with hybrid selector
AGENT_DETECTION="$(
  printf %s "$PROMPT" | python3 "${HOOKS_LIB}/hybrid_agent_selector.py" - \
    --enable-ai "${ENABLE_AI_AGENT_SELECTION:-true}" \
    --model-preference "${AI_MODEL_PREFERENCE:-5090}" \
    --confidence-threshold "${AI_AGENT_CONFIDENCE_THRESHOLD:-0.8}" \
    --timeout "${AI_SELECTION_TIMEOUT_MS:-3000}"
)"

# NEW: Dispatch directive generation
AGENT_CONTEXT="$(cat <<EOF
🎯 AGENT DISPATCH DIRECTIVE (Auto-detected by hooks)
...
Task Tool Configuration:
│ description: "${AGENT_DOMAIN} task execution"
│ subagent_type: "agent-workflow-coordinator"
│ prompt: "Route to ${AGENT_NAME}..."
EOF
)"
```

### 3. Agent Registry
**Location**: `~/.claude/agent-definitions/agent-registry.yaml`

Defines agents with:
- Activation triggers
- Domain classification
- Purpose descriptions
- Capability lists

**Fixed configs**:
- ✅ `agent-devops-infrastructure.yaml` - Fixed YAML syntax error

## Intelligence Package

Each dispatch directive includes:

```yaml
Intelligence Context:
  agent: agent-devops-infrastructure
  domain: devops_infrastructure
  purpose: Container orchestration, CI/CD...
  confidence: 0.8
  detection_method: trigger
  detection_reasoning: Matched triggers 'deploy infrastructure'

  rag_intelligence:
    domain: /tmp/agent_intelligence_domain_{correlation_id}.json
    implementation: /tmp/agent_intelligence_impl_{correlation_id}.json

  correlation:
    correlation_id: uuid
    archon_mcp: http://localhost:8051

  framework_requirements:
    mandatory_functions: 47 (IC-001 to FI-004)
    quality_gates: 23
    performance_thresholds: 33
```

## Configuration

### Environment Variables

```bash
# Agent detection control
ENABLE_AI_AGENT_SELECTION=true
AI_MODEL_PREFERENCE=5090  # or mac-studio, gemini-flash, auto
AI_AGENT_CONFIDENCE_THRESHOLD=0.8
AI_SELECTION_TIMEOUT_MS=3000

# Database logging (from .env)
DB_PASSWORD=omninode-bridge-postgres-dev-2024

# Archon MCP
ARCHON_MCP_URL=http://localhost:8051
ARCHON_INTELLIGENCE_URL=http://localhost:8053
```

### Available AI Models

For AI-powered selection (Stage 3):

**Local (vLLM)**:
- RTX 5090: DeepSeek-Lite (2.0 weight)
- Mac Studio: Codestral (1.5 weight)
- RTX 4090: Llama 3.1 (1.2 weight)
- Mac Mini: DeepSeek-Full (1.8 weight)

**Cloud APIs**:
- Gemini Flash (1.0 weight)
- Z.ai GLM models

## Performance

### Detection Latency

| Stage | Latency | Confidence |
|-------|---------|------------|
| Pattern match | 1-2ms | 1.0 (100%) |
| Trigger match | 2-5ms | 0.7-0.9 |
| AI selection | 100-500ms | 0.0-1.0 |

**Total**: 5-50ms (without AI), 100-550ms (with AI)

### Intelligence Gathering

- RAG queries: Background (non-blocking)
- Metadata extraction: ~10ms
- Correlation ID: <1ms

**Total overhead**: <100ms for UserPromptSubmit hook

## Usage Examples

### Example 1: DevOps Infrastructure

**User prompt**: "deploy kubernetes cluster with monitoring"

**Hook detects**:
```
DETECTED AGENT: agent-devops-infrastructure
Confidence: 0.85 | Method: trigger
```

**Directive generated**:
```
Use Task tool:
  description: "devops_infrastructure task execution"
  subagent_type: "agent-workflow-coordinator"
  prompt: "Route to agent-devops-infrastructure:
    deploy kubernetes cluster with monitoring
    [+ intelligence context...]"
```

**Result**: Claude Code executes Task → agent-workflow-coordinator → agent-devops-infrastructure

### Example 2: Code Generation

**User prompt**: "create new ONEX microservice for user authentication"

**Hook detects**:
```
DETECTED AGENT: agent-code-generator
Confidence: 0.9 | Method: pattern
```

**Directive generated**:
```
Use Task tool:
  description: "code_generation task execution"
  subagent_type: "agent-workflow-coordinator"
  prompt: "Route to agent-code-generator:
    create new ONEX microservice for user authentication
    [+ ONEX patterns, templates, quality gates...]"
```

## Monitoring & Analytics

### Hook Intelligence Dashboard

```bash
# View recent agent detections
python3 claude_hooks/tools/hook_dashboard.py

# View specific correlation trace
python3 claude_hooks/tools/hook_dashboard.py trace <correlation-id>
```

### Database Queries

```sql
-- Recent agent dispatches
SELECT
  created_at,
  payload->>'agent_detected' as agent,
  payload->>'detection_method' as method,
  payload->>'confidence' as confidence
FROM hook_events
WHERE source = 'UserPromptSubmit'
  AND payload->>'agent_detected' IS NOT NULL
ORDER BY created_at DESC
LIMIT 10;
```

## Testing

### Test Agent Detection

```bash
# Test without AI (fast)
echo "deploy infrastructure" | \
  python3 ~/.claude/hooks/lib/hybrid_agent_selector.py - \
  --enable-ai false

# Test with AI (slower but more accurate)
echo "help me optimize database queries" | \
  python3 ~/.claude/hooks/lib/hybrid_agent_selector.py - \
  --enable-ai true \
  --model-preference 5090
```

### Test Full Hook

Submit a prompt in Claude Code and check:

```bash
# Hook execution log
tail -f ~/.claude/hooks/hook-enhanced.log

# Database events
PGPASSWORD=omninode-bridge-postgres-dev-2024 psql \
  -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT * FROM hook_events ORDER BY created_at DESC LIMIT 5;"
```

## Troubleshooting

### Agent not detected

1. Check agent registry: `~/.claude/agent-definitions/agent-registry.yaml`
2. Verify triggers match your prompt
3. Enable AI selection for semantic matching
4. Check logs: `tail -f ~/.claude/hooks/hook-enhanced.log`

### AI selection failing

```
AI selection failed: unhashable type: 'slice'
```
**Fixed**: Update to latest ai_agent_selector.py (handles dict/list capabilities)

### Hook not running

1. Verify symlinks: `ls -la ~/.claude/hooks`
2. Check hook permissions: `chmod +x ~/.claude/hooks/*.sh`
3. Source environment: `source .env`

## Future Enhancements

- [ ] **Dispatch analytics**: Track dispatch success rates
- [ ] **Learning system**: Improve detection based on user feedback
- [ ] **Multi-agent coordination**: Detect when multiple agents needed
- [ ] **Context-aware routing**: Use conversation history for better detection
- [ ] **Performance optimization**: Cache agent configs, warm up models

## See Also

- [Hook Intelligence Guide](HOOK_INTELLIGENCE_GUIDE.md)
- [Setup Guide](SETUP.md)
- [Hook Dashboard](tools/hook_dashboard.py)
- [Agent Workflow Coordinator](../agents/agent-workflow-coordinator.md)
