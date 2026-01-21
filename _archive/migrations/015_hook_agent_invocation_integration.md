# Migration 015: Hook Agent Invocation Integration

**Date**: 2025-10-31
**Type**: Feature Enhancement
**Priority**: HIGH
**Estimated Time**: 1-2 hours

---

## Overview

Integrate agent invocation into UserPromptSubmit hook to enable automatic agent transformation based on routing decisions.

**Current State**: Hook detects agents but only injects text directive
**Target State**: Hook loads agent YAML and injects complete identity

---

## Files Modified

### 1. `/Users/jonah/.claude/hooks/user-prompt-submit.sh`

**Location**: After line 123 (after routing completes)

#### Add: Agent Invocation Section

```bash
# -----------------------------
# Agent Invocation (NEW)
# -----------------------------
if [[ -n "$AGENT_NAME" ]] && [[ "$AGENT_NAME" != "NO_AGENT_DETECTED" ]]; then
  log "Invoking agent via invoke_agent_from_hook.py..."

  # Prepare invocation input JSON
  INVOKE_INPUT="$(jq -n \
    --arg prompt "$PROMPT" \
    --arg corr_id "$CORRELATION_ID" \
    --arg sess_id "${SESSION_ID:-unknown}" \
    --argjson ctx '{}' \
    '{prompt: $prompt, correlation_id: $corr_id, session_id: $sess_id, context: $ctx}')"

  # Call agent invoker (with timeout to prevent hangs)
  INVOKE_RESULT="$(echo "$INVOKE_INPUT" | timeout 3 python3 "${HOOKS_LIB}/invoke_agent_from_hook.py" 2>>"$LOG_FILE" || echo '{}')"

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
```

#### Modify: AGENT_CONTEXT Generation (Lines 384-426)

**Before**:
```bash
AGENT_CONTEXT="$(cat <<EOF

========================================================================
🎯 AGENT DISPATCH DIRECTIVE (Auto-detected by hooks)
========================================================================

DETECTED AGENT: ${AGENT_NAME}
[...]
EOF
)"
```

**After**:
```bash
AGENT_CONTEXT="$(cat <<EOF
${AGENT_YAML_INJECTION}

========================================================================
🎯 AGENT DISPATCH DIRECTIVE (Auto-detected by hooks)
========================================================================

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
│   - Domain: /tmp/agent_intelligence_domain_${CORRELATION_ID}.json   │
│   - Implementation: /tmp/agent_intelligence_impl_${CORRELATION_ID}.json │
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
```

---

## Dependencies

All required infrastructure already exists:

- ✅ `agents/lib/invoke_agent_from_hook.py` - Ready to use
- ✅ `agents/lib/agent_invoker.py` - Complete implementation
- ✅ `~/.claude/agent-definitions/*.yaml` - 50+ agent configs
- ✅ Event-based routing - Working perfectly
- ✅ Database logging - All tables ready

**No new dependencies required!**

---

## Testing

### Pre-Migration Verification

```bash
# 1. Verify agent invoker works standalone
echo '{"prompt": "debug database connection", "correlation_id": "test-123", "session_id": "test-session", "context": {}}' | \
  python3 ~/.claude/hooks/lib/invoke_agent_from_hook.py

# Expected output:
{
  "success": true,
  "pathway": "direct_single",
  "agent_name": "agent-debug-database",
  "context_injection": "# POLYMORPHIC AGENT IDENTITY INJECTION..."
}

# 2. Verify agent YAML exists
ls ~/.claude/agent-definitions/ | grep -E "debug|api|devops"

# Should see:
debug-database.yaml
debug-intelligence.yaml
api-architect.yaml
devops-infrastructure.yaml
```

### Post-Migration Testing

**Test 1: Database Debugging**
```bash
# Trigger hook with database prompt
# (via Claude Code UI or test harness)

Prompt: "Help me debug a slow PostgreSQL query"

# Check logs
tail -50 ~/.claude/hooks/hook-enhanced.log | grep -A5 "Invoking agent"

# Should see:
[2025-10-31 14:30:00] Invoking agent via invoke_agent_from_hook.py...
[2025-10-31 14:30:00] Agent YAML loaded successfully (2847 chars)

# Verify YAML in context
grep -A10 "POLYMORPHIC AGENT IDENTITY" ~/.claude/hooks/hook-enhanced.log

# Should see agent YAML content
```

**Test 2: API Architecture**
```bash
Prompt: "Design a REST API for user management"

# Expected:
- Agent: agent-api-architect
- YAML: Includes API design principles, REST patterns
- Response: Specialized API architecture advice
```

**Test 3: DevOps Infrastructure**
```bash
Prompt: "Fix Docker container that won't start"

# Expected:
- Agent: agent-devops-infrastructure
- YAML: Includes container debugging, orchestration
- Response: Systematic container troubleshooting
```

### Validation Checklist

After each test, verify:

- [ ] Hook log shows "Invoking agent via invoke_agent_from_hook.py"
- [ ] Hook log shows "Agent YAML loaded successfully (N chars)"
- [ ] AGENT_CONTEXT includes "POLYMORPHIC AGENT IDENTITY INJECTION"
- [ ] AGENT_CONTEXT includes agent_identity YAML block
- [ ] Claude Code response shows specialized behavior (not generic)
- [ ] Database has routing_decision record
- [ ] Correlation ID links routing → manifest → execution

### Negative Testing

**Test: Agent YAML Not Found**
```bash
# Manually trigger with non-existent agent
AGENT_NAME="agent-nonexistent" ...

# Expected:
- Hook log: "WARNING: Agent invocation failed"
- AGENT_CONTEXT: "⚠️ AGENT IDENTITY NOT LOADED - Directive mode only"
- Still functional (graceful degradation)
```

**Test: Agent Invoker Timeout**
```bash
# Simulate slow invocation (should timeout at 3s)

# Expected:
- Hook continues (non-blocking)
- Falls back to directive-only mode
- No crash or hang
```

---

## Rollback Plan

If issues arise, revert to previous behavior:

### Quick Rollback

**Option 1: Disable Agent Invocation**
```bash
# In user-prompt-submit.sh, comment out invocation section:

# # -----------------------------
# # Agent Invocation (DISABLED)
# # -----------------------------
# if [[ -n "$AGENT_NAME" ]] && [[ "$AGENT_NAME" != "NO_AGENT_DETECTED" ]]; then
#   # Agent invocation code...
# fi
AGENT_YAML_INJECTION=""  # Force empty
```

**Option 2: Git Revert**
```bash
# Revert to previous version
cd ~/.claude/hooks
git diff user-prompt-submit.sh  # Review changes
git checkout HEAD~1 -- user-prompt-submit.sh
```

### Verification After Rollback

```bash
# Test hook still works
echo '{"prompt": "test"}' | ~/.claude/hooks/user-prompt-submit.sh

# Should output JSON without errors
```

---

## Performance Impact

### Expected Changes

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Hook latency | 50-100ms | 75-125ms | +25ms |
| Agent detection | 5-10ms | 5-10ms | No change |
| YAML loading | N/A | 15-25ms | +15-25ms |
| Context size | ~2KB | ~5-8KB | +3-6KB |
| Total time | 50-100ms | 75-125ms | +25% |

**Acceptable**: Hook remains under 200ms target

### Optimization Opportunities (Future)

1. **Cache agent YAML** - Load once per session
2. **Async YAML loading** - Parallel with other hook tasks
3. **Lazy loading** - Only load YAML when confidence > threshold

---

## Database Impact

### New Records

After each agent invocation:

**agent_execution_logs** (if agent executes):
```sql
INSERT INTO agent_execution_logs (
  execution_id,
  correlation_id,
  agent_name,
  status,
  started_at
) VALUES (...);
```

**Expected Volume**: Same as current routing decisions (1 per user prompt)

### Schema Changes

**None required** - All tables already exist

---

## Monitoring

### Success Metrics

After 1 week, measure:

1. **Agent Invocation Success Rate**
   ```sql
   SELECT
     COUNT(*) FILTER (WHERE status = 'success') * 100.0 / COUNT(*) as success_rate
   FROM agent_execution_logs
   WHERE created_at > NOW() - INTERVAL '7 days';
   ```
   **Target**: >95%

2. **Agent Identity Injection Rate**
   ```bash
   # Count hooks with YAML injection
   grep "Agent YAML loaded successfully" ~/.claude/hooks/hook-enhanced.log | wc -l
   ```
   **Target**: Matches routing decision count

3. **Average YAML Size**
   ```bash
   # Extract YAML sizes from logs
   grep "Agent YAML loaded successfully" ~/.claude/hooks/hook-enhanced.log | \
     sed -E 's/.*\(([0-9]+) chars\).*/\1/' | \
     awk '{sum+=$1; count++} END {print sum/count}'
   ```
   **Expected**: 2000-3000 chars

### Failure Monitoring

Watch for:
- `WARNING: Agent invocation failed` in logs
- Timeout errors (>3s)
- Missing YAML files
- JSON parse errors

### Alerts (Optional)

```bash
# Daily cron: Check invocation failures
failures=$(grep -c "Agent invocation failed" ~/.claude/hooks/hook-enhanced.log)
if [ $failures -gt 10 ]; then
  echo "ALERT: $failures agent invocations failed today"
fi
```

---

## Documentation Updates

After migration completes:

1. **AGENT_DISPATCH_SYSTEM.md**
   - Update to reflect actual implementation
   - Remove outdated Task tool directive references
   - Add YAML injection examples

2. **HOW_TO_USE_POLYMORPHIC_AGENTS.md**
   - Add verification steps
   - Include example responses showing transformation
   - Update troubleshooting section

3. **TROUBLESHOOTING.md**
   - Add "Agent detected but not invoked" section
   - Add YAML loading failure debugging

4. **CLAUDE.md** (project root)
   - Update agent workflow diagram
   - Add invocation flow documentation

---

## Implementation Checklist

Before starting:
- [ ] Backup current `user-prompt-submit.sh`
- [ ] Verify all dependencies exist
- [ ] Test `invoke_agent_from_hook.py` standalone

During implementation:
- [ ] Add agent invocation section (after line 123)
- [ ] Modify AGENT_CONTEXT generation (lines 384-426)
- [ ] Add error handling and logging
- [ ] Test with 3+ different agents

After implementation:
- [ ] Run all validation tests
- [ ] Check database records
- [ ] Verify correlation ID tracking
- [ ] Update documentation
- [ ] Monitor for 24-48 hours

---

## Code Diff Summary

```diff
--- a/user-prompt-submit.sh
+++ b/user-prompt-submit.sh
@@ -123,6 +123,38 @@
 log "Reasoning: ${SELECTION_REASONING:0:120}..."

+# -----------------------------
+# Agent Invocation (NEW)
+# -----------------------------
+if [[ -n "$AGENT_NAME" ]] && [[ "$AGENT_NAME" != "NO_AGENT_DETECTED" ]]; then
+  log "Invoking agent via invoke_agent_from_hook.py..."
+
+  # Prepare invocation input JSON
+  INVOKE_INPUT="$(jq -n \
+    --arg prompt "$PROMPT" \
+    --arg corr_id "$CORRELATION_ID" \
+    --arg sess_id "${SESSION_ID:-unknown}" \
+    --argjson ctx '{}' \
+    '{prompt: $prompt, correlation_id: $corr_id, session_id: $sess_id, context: $ctx}')"
+
+  # Call agent invoker (with timeout)
+  INVOKE_RESULT="$(echo "$INVOKE_INPUT" | timeout 3 python3 "${HOOKS_LIB}/invoke_agent_from_hook.py" 2>>"$LOG_FILE" || echo '{}')"
+
+  INVOKE_SUCCESS="$(echo "$INVOKE_RESULT" | jq -r '.success // false')"
+
+  if [[ "$INVOKE_SUCCESS" == "true" ]]; then
+    AGENT_YAML_INJECTION="$(echo "$INVOKE_RESULT" | jq -r '.context_injection // ""')"
+    if [[ -n "$AGENT_YAML_INJECTION" ]]; then
+      log "Agent YAML loaded successfully (${#AGENT_YAML_INJECTION} chars)"
+    fi
+  else
+    log "WARNING: Agent invocation failed"
+    AGENT_YAML_INJECTION=""
+  fi
+else
+  AGENT_YAML_INJECTION=""
+fi
+
 # Handle no agent detected
 if [[ "$AGENT_NAME" == "NO_AGENT_DETECTED" ]] || [[ -z "$AGENT_NAME" ]]; then

@@ -384,6 +416,7 @@
 AGENT_CONTEXT="$(cat <<EOF
+${AGENT_YAML_INJECTION}

 ========================================================================
 🎯 AGENT DISPATCH DIRECTIVE (Auto-detected by hooks)
```

**Lines Added**: ~35
**Lines Modified**: ~5
**Total Change**: ~40 lines

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Hook timeout | Low | Medium | 3s timeout + fallback |
| Missing YAML | Low | Low | Graceful degradation |
| YAML parse error | Low | Low | JSON validation in invoker |
| Increased latency | Medium | Low | <200ms total (acceptable) |
| Breaking change | Very Low | Medium | Extensive testing + rollback plan |

**Overall Risk**: LOW

---

## Success Criteria

Migration considered successful when:

1. ✅ Agent YAML loaded for 95%+ of detected agents
2. ✅ Claude Code responds as specialized agent (verified manually)
3. ✅ Hook latency remains <200ms
4. ✅ No increase in hook failures
5. ✅ Database tracking complete (routing → manifest → execution)
6. ✅ Documentation updated to reflect actual behavior

---

**Estimated Timeline**:
- Implementation: 30-45 minutes
- Testing: 45-60 minutes
- Documentation: 30 minutes
- **Total**: 2-3 hours

**Priority**: HIGH - Enables core polymorphic agent functionality
