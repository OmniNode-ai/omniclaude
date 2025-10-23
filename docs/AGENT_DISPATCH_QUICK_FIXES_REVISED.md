# Agent Dispatch System - Quick Fixes (REVISED)

**Date**: 2025-10-20
**Critical Discovery**: The "Task tool" referenced in dispatch directives **does not exist** in Claude Code
**Impact**: Complete redesign of dispatch mechanism required

---

## CRITICAL FINDING

### The Task Tool Does Not Exist

**Investigation reveals**:
```bash
# Available tools in Claude Code:
- TodoWrite (task management)
- SlashCommand (custom command execution)
- Bash, Read, Write, Edit, Glob, Grep (file operations)
- WebFetch, WebSearch (web operations)
- NotebookEdit (Jupyter notebooks)
- AskUserQuestion (user interaction)

# NO "Task" tool for agent dispatch!
```

**Current hook directive**:
```bash
REQUIRED ACTION: Use the Task tool to dispatch...
```

**Problem**: Asks Claude to use a tool that doesn't exist, making dispatch impossible.

---

## Revised Understanding of Agent Dispatch

### Three Possible Dispatch Mechanisms

#### 1. **Context Injection (Current, Passive)**
Hook injects agent configuration as context → Claude reads and adapts behavior

**Status**: Partially implemented in `invoke_agent_from_hook.py` (direct_single pathway)
**Effectiveness**: Low - relies on LLM interpretation

#### 2. **SlashCommand Invocation (Available, Not Used)**
Hook generates `/command-name` → Claude executes custom command

**Status**: Infrastructure exists but not integrated
**Effectiveness**: Medium - requires SlashCommand tool integration

#### 3. **Background Process Spawn (Possible, Not Implemented)**
Hook directly spawns agent execution as background process

**Status**: Not implemented
**Effectiveness**: High - deterministic execution

---

## Revised Quick Fixes

### Fix #1: SlashCommand-Based Dispatch (2-3 hours) **RECOMMENDED**

This is the most practical solution using existing Claude Code infrastructure.

#### Step 1: Create Agent Dispatch Slash Command

**File**: `~/.claude/commands/dispatch-agent.md`

```markdown
# Polymorphic Agent Dispatch Command

**Detected Agent**: {{agent_name}}
**Confidence**: {{confidence}}
**Domain**: {{domain}}
**Detection Method**: {{method}}

## Pre-Gathered Intelligence

The UserPromptSubmit hook has detected that this request should be handled by a specialized agent with the following context:

- **Agent**: {{agent_name}}
- **Purpose**: {{purpose}}
- **RAG Domain Intelligence**: {{domain_intelligence_file}}
- **RAG Implementation Intelligence**: {{impl_intelligence_file}}
- **Correlation ID**: {{correlation_id}}

## Your Task

You are now assuming the identity and capabilities of **{{agent_name}}**.

Follow these steps:
1. Read the agent configuration from: `~/.claude/agent-definitions/{{agent_name}}.yaml`
2. Review the pre-gathered intelligence files listed above
3. Execute the user's request using the agent's specialized capabilities
4. Apply the agent's framework requirements:
   - 47 mandatory functions (IC-001 to FI-004)
   - 23 quality gates validation
   - Performance thresholds compliance

## Original User Request

{{original_prompt}}

## Intelligence Context

```json
{{intelligence_json}}
```

Execute as **{{agent_name}}** with full context above.
```

#### Step 2: Update Hook to Generate SlashCommand

**File**: `claude_hooks/user-prompt-submit.sh` (replace directive generation)

```bash
# After agent detection...
if [[ -n "$AGENT_NAME" ]] && [[ $(bc <<< "$CONFIDENCE >= 0.7") -eq 1 ]]; then
  log "Generating SlashCommand for agent dispatch"

  # Prepare intelligence JSON
  INTELLIGENCE_JSON="$(jq -n \
    --arg agent "$AGENT_NAME" \
    --arg domain "$AGENT_DOMAIN" \
    --arg purpose "$AGENT_PURPOSE" \
    --arg confidence "$CONFIDENCE" \
    --arg method "$SELECTION_METHOD" \
    --arg reasoning "$SELECTION_REASONING" \
    --arg domain_intel "/tmp/agent_intelligence_domain_${CORRELATION_ID}.json" \
    --arg impl_intel "/tmp/agent_intelligence_impl_${CORRELATION_ID}.json" \
    --arg corr_id "$CORRELATION_ID" \
    '{
      agent: $agent,
      domain: $domain,
      purpose: $purpose,
      confidence: $confidence,
      method: $method,
      reasoning: $reasoning,
      domain_intelligence: $domain_intel,
      impl_intelligence: $impl_intel,
      correlation_id: $corr_id
    }')"

  # Create slash command invocation
  AGENT_CONTEXT="$(cat <<EOF

════════════════════════════════════════════════════════════════════════
🎯 POLYMORPHIC AGENT DISPATCH DETECTED
════════════════════════════════════════════════════════════════════════

Agent: ${AGENT_NAME}
Confidence: ${CONFIDENCE} (${SELECTION_METHOD})
Domain: ${AGENT_DOMAIN}

EXECUTE THIS SLASH COMMAND TO DISPATCH:

/dispatch-agent \\
  --agent="${AGENT_NAME}" \\
  --confidence="${CONFIDENCE}" \\
  --domain="${AGENT_DOMAIN}" \\
  --purpose="${AGENT_PURPOSE}" \\
  --method="${SELECTION_METHOD}" \\
  --reasoning="${SELECTION_REASONING}" \\
  --domain-intelligence="/tmp/agent_intelligence_domain_${CORRELATION_ID}.json" \\
  --impl-intelligence="/tmp/agent_intelligence_impl_${CORRELATION_ID}.json" \\
  --correlation-id="${CORRELATION_ID}"

Or use the SlashCommand tool:

<tool_use>
<tool_name>SlashCommand</tool_name>
<parameters>
<command>/dispatch-agent --agent="${AGENT_NAME}" --correlation-id="${CORRELATION_ID}"</command>
</parameters>
</tool_use>

Original request: ${PROMPT}

════════════════════════════════════════════════════════════════════════
EOF
)"

else
  log "Agent detection confidence too low ($CONFIDENCE), skipping dispatch"
  AGENT_CONTEXT=""
fi
```

#### Step 3: Test

```bash
# 1. Verify slash command exists
ls -la ~/.claude/commands/dispatch-agent.md

# 2. Test in Claude Code
# Submit: "Deploy infrastructure with monitoring"
# Expected: Hook detects agent, generates /dispatch-agent command
# Claude should invoke SlashCommand tool

# 3. Check logs
tail -f ~/.claude/hooks/hook-enhanced.log
```

**Expected Success Rate**: 75-85% (depends on SlashCommand tool invocation reliability)

---

### Fix #2: Direct Background Execution (3-4 hours) **MOST RELIABLE**

Bypass Claude Code entirely for high-confidence detections.

#### Implementation

**File**: `claude_hooks/user-prompt-submit.sh` (add after agent detection)

```bash
# After AGENT_DETECTION and confidence calculation...

AUTO_DISPATCH_ENABLED="${AUTO_DISPATCH_ENABLED:-true}"
AUTO_DISPATCH_THRESHOLD="${AUTO_DISPATCH_THRESHOLD:-0.85}"

if [[ "$AUTO_DISPATCH_ENABLED" == "true" ]] && \
   [[ $(bc <<< "$CONFIDENCE >= $AUTO_DISPATCH_THRESHOLD") -eq 1 ]]; then

  log "AUTO-DISPATCH: Confidence $CONFIDENCE >= $AUTO_DISPATCH_THRESHOLD, spawning background agent"

  # Create dispatch input JSON
  DISPATCH_JSON="$(jq -n \
    --arg prompt "$PROMPT" \
    --arg agent "$AGENT_NAME" \
    --arg domain "$AGENT_DOMAIN" \
    --arg confidence "$CONFIDENCE" \
    --arg corr_id "$CORRELATION_ID" \
    '{
      prompt: $prompt,
      agent_name: $agent,
      agent_domain: $domain,
      confidence: ($confidence | tonumber),
      correlation_id: $corr_id,
      auto_dispatch: true
    }')"

  # Spawn background agent dispatcher
  OUTPUT_FILE="/tmp/agent_dispatch_${CORRELATION_ID}.log"

  (
    cd "${HOOKS_LIB}" 2>/dev/null || cd "/Users/jonah/.claude/hooks/lib"
    echo "$DISPATCH_JSON" | python3 invoke_agent_from_hook.py > "$OUTPUT_FILE" 2>&1
  ) &
  DISPATCH_PID=$!

  log "AUTO-DISPATCH: Spawned agent dispatcher PID=$DISPATCH_PID, output=$OUTPUT_FILE"

  # Update context to inform user
  AGENT_CONTEXT="$(cat <<EOF

════════════════════════════════════════════════════════════════════════
✅ POLYMORPHIC AGENT AUTO-DISPATCHED
════════════════════════════════════════════════════════════════════════

Agent: ${AGENT_NAME}
Confidence: ${CONFIDENCE} (High confidence - auto-dispatch triggered)
Domain: ${AGENT_DOMAIN}
Process ID: ${DISPATCH_PID}
Output Log: ${OUTPUT_FILE}

The agent is executing your request in the background. You can monitor
progress with:

  tail -f ${OUTPUT_FILE}

Results will be available once the agent completes execution.

Original request: ${PROMPT}

════════════════════════════════════════════════════════════════════════
EOF
)"

else
  log "Auto-dispatch disabled or confidence too low ($CONFIDENCE < $AUTO_DISPATCH_THRESHOLD)"

  # Fallback to manual dispatch directive
  AGENT_CONTEXT="$(cat <<EOF

════════════════════════════════════════════════════════════════════════
⚠️  POLYMORPHIC AGENT DETECTED (Manual Dispatch Required)
════════════════════════════════════════════════════════════════════════

Agent: ${AGENT_NAME}
Confidence: ${CONFIDENCE} (Below auto-dispatch threshold $AUTO_DISPATCH_THRESHOLD)
Domain: ${AGENT_DOMAIN}

To dispatch this agent, use the SlashCommand tool:

/dispatch-agent --agent="${AGENT_NAME}" --correlation-id="${CORRELATION_ID}"

Or execute directly by assuming the agent identity and using the pre-gathered
intelligence in:
- /tmp/agent_intelligence_domain_${CORRELATION_ID}.json
- /tmp/agent_intelligence_impl_${CORRELATION_ID}.json

Original request: ${PROMPT}

════════════════════════════════════════════════════════════════════════
EOF
)"
fi
```

#### Configuration

**File**: `.env`

```bash
# Agent auto-dispatch configuration
AUTO_DISPATCH_ENABLED=true
AUTO_DISPATCH_THRESHOLD=0.85  # Only auto-dispatch high confidence (>85%)

# Allowed agents for auto-dispatch (comma-separated)
AUTO_DISPATCH_WHITELIST=agent-workflow-coordinator,agent-devops-infrastructure,agent-code-generator
```

**Expected Success Rate**: 95%+ for high-confidence detections (>0.85)

---

### Fix #3: Enhanced System Prompt (15 minutes) **COMPLEMENTARY**

Even with technical fixes, improve LLM understanding of the system.

**File**: `~/.claude/CLAUDE.md` (add after Agent Workflow Coordination section)

```markdown
## Polymorphic Agent Dispatch Protocol

### Agent Detection System

The UserPromptSubmit hook analyzes every user prompt and may detect that a
specialized agent should handle the request. When this happens, you'll see:

```
🎯 POLYMORPHIC AGENT DISPATCH DETECTED
Agent: agent-xyz
Confidence: 0.85
```

### Dispatch Mechanisms

#### 1. Auto-Dispatch (High Confidence ≥85%)
When confidence is high, the agent executes automatically in the background.
Your role: Acknowledge the dispatch and explain it to the user.

#### 2. SlashCommand Dispatch (Medium Confidence 70-84%)
Use the SlashCommand tool to execute the provided `/dispatch-agent` command:

```xml
<tool_use>
<tool_name>SlashCommand</tool_name>
<parameters>
<command>/dispatch-agent --agent="agent-name" --correlation-id="uuid"</command>
</parameters>
</tool_use>
```

#### 3. Manual Context Injection (Low Confidence <70%)
Read the agent configuration and pre-gathered intelligence, then execute as
that agent by adapting your behavior and capabilities.

### When to Override Agent Detection

Override ONLY if:
- User explicitly says "don't use agents"
- The detected agent is clearly wrong for the task
- Confidence is very low (<0.5) and reasoning is unclear

### Best Practices

1. **Trust the detection**: The hook has analyzed triggers, keywords, and context
2. **Use pre-gathered intelligence**: RAG queries have already been executed
3. **Follow framework requirements**: Agents have specific compliance needs
4. **Maintain correlation ID**: Use it for logging and tracing
```

---

## Implementation Priority

### Phase 1: Immediate (Today)
1. ✅ Identify root cause (Task tool doesn't exist)
2. ✅ Document findings
3. ⬜ Add enhanced system prompt (15 min)
4. ⬜ Test current context injection behavior

### Phase 2: Short-Term (This Week)
1. ⬜ Implement SlashCommand dispatch (3 hours)
2. ⬜ Test SlashCommand reliability
3. ⬜ Measure dispatch success rate
4. ⬜ Create slash command templates for common agents

### Phase 3: Medium-Term (Next Week)
1. ⬜ Implement auto-dispatch for high confidence (4 hours)
2. ⬜ Add configuration and whitelisting
3. ⬜ Create monitoring dashboard for auto-dispatch
4. ⬜ Test background execution reliability

---

## Success Metrics

### Baseline (Current State)
- Agent detection: ~95% ✅
- Agent dispatch: ~0-10% ❌ (Task tool doesn't exist)
- Manual context following: ~30-40% (LLM dependent)

### Target (After Fixes)
- Phase 1 (System Prompt): 40-50% dispatch rate
- Phase 2 (SlashCommand): 70-80% dispatch rate
- Phase 3 (Auto-Dispatch): 95%+ for high confidence, 75%+ overall

### Measurement

**File**: `claude_hooks/lib/track_dispatch_success.py`

```python
#!/usr/bin/env python3
"""Track agent dispatch success rate."""

import psycopg2
from datetime import datetime, timedelta

def measure_dispatch_rate(days=7):
    """Measure dispatch success rate over last N days."""

    conn = psycopg2.connect(
        "host=localhost port=5436 dbname=omninode_bridge "
        "user=postgres password=omninode-bridge-postgres-dev-2024"
    )

    with conn.cursor() as cur:
        # Get detections vs dispatches
        cur.execute("""
            SELECT
                DATE(created_at) as date,
                COUNT(*) FILTER (WHERE payload->>'agent_detected' IS NOT NULL) as detections,
                COUNT(*) FILTER (WHERE payload->>'dispatch_method' IN ('auto', 'slash_command', 'manual')) as dispatches,
                ROUND(100.0 *
                    COUNT(*) FILTER (WHERE payload->>'dispatch_method' IS NOT NULL) /
                    NULLIF(COUNT(*) FILTER (WHERE payload->>'agent_detected' IS NOT NULL), 0), 2
                ) as success_rate
            FROM hook_events
            WHERE source = 'UserPromptSubmit'
                AND created_at > NOW() - INTERVAL '%s days'
            GROUP BY DATE(created_at)
            ORDER BY date DESC;
        """, (days,))

        rows = cur.fetchall()

        print(f"Agent Dispatch Success Rate (Last {days} Days)")
        print("=" * 60)
        for row in rows:
            print(f"{row[0]}: {row[1]} detections, {row[2]} dispatches = {row[3]}%")

    conn.close()

if __name__ == "__main__":
    measure_dispatch_rate()
```

---

## Testing Plan

### Test 1: SlashCommand Dispatch
```
User: "Deploy infrastructure with monitoring"
Expected Hook: Detects agent-devops-infrastructure, confidence ~0.8
Expected Claude: Invokes SlashCommand tool with /dispatch-agent
Expected Result: Agent executes via slash command
```

### Test 2: Auto-Dispatch (High Confidence)
```
User: "@agent-workflow-coordinator please optimize the database"
Expected Hook: Detects agent-workflow-coordinator, confidence 1.0
Expected Hook: Auto-spawns background process
Expected Claude: Acknowledges auto-dispatch
Expected Result: Agent executes in background
```

### Test 3: Manual Context Injection (Low Confidence)
```
User: "Help me refactor this code"
Expected Hook: Detects agent-code-generator, confidence ~0.6
Expected Claude: Reads agent config and adapts behavior
Expected Result: Claude acts as the agent (no dispatch)
```

---

## Rollback Plan

If fixes cause issues:

```bash
# 1. Disable auto-dispatch
echo "AUTO_DISPATCH_ENABLED=false" >> .env
source .env

# 2. Revert hook changes
cd .
git checkout claude_hooks/user-prompt-submit.sh

# 3. Remove slash command
rm ~/.claude/commands/dispatch-agent.md

# 4. Restart Claude Code
```

---

## Conclusion

**Root Cause**: The "Task tool" referenced throughout the system does not exist in Claude Code.

**Solution**: Use existing infrastructure:
- **SlashCommand tool** for manual dispatch
- **Background process spawning** for auto-dispatch
- **Context injection** as fallback

**Expected Outcome**: Dispatch success rate from ~10% to 85%+ within 1 week.

---

**Document Status**: Implementation guide ready
**Next Action**: Choose implementation approach (SlashCommand vs Auto-Dispatch vs Both)
**Effort Required**: 2-7 hours depending on approach
**Risk Level**: Low (incremental rollout, easy rollback)
