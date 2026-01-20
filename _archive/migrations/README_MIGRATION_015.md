# Migration 015: Agent Invocation Integration

**Status**: Ready for Implementation
**Date**: 2025-10-31
**Priority**: HIGH

---

## Quick Summary

**Problem**: UserPromptSubmit hooks detect agents correctly but Claude Code doesn't automatically transform into them.

**Root Cause**: Hook only injects text directive, doesn't load agent YAML definition.

**Solution**: Add 35 lines to `user-prompt-submit.sh` to call existing `invoke_agent_from_hook.py`.

**Impact**: Enables complete polymorphic agent system - Claude Code will transform into detected agents.

**Effort**: 2-3 hours (implementation + testing + docs)

---

## Files

1. **AGENT_INVOCATION_GAP_ANALYSIS.md** - Complete investigation and analysis
2. **015_hook_agent_invocation_integration.md** - Implementation guide and migration plan

---

## Current vs Expected Behavior

### Current (Broken) ❌

```
User: "Help me debug this database issue"
  ↓
Hook detects: agent-debug-database (confidence: 0.92)
  ↓
Hook injects: "🎯 AGENT DISPATCH DIRECTIVE
               DETECTED AGENT: agent-debug-database
               (polymorphic agent will read this directive automatically)"
  ↓
Claude Code: [Responds as generic assistant]
```

**Problem**: Text directive is just informational - no actual transformation happens.

### Expected (Working) ✅

```
User: "Help me debug this database issue"
  ↓
Hook detects: agent-debug-database (confidence: 0.92)
  ↓
Hook invokes: invoke_agent_from_hook.py ← NEW
  ↓
Hook loads: debug-database.yaml ← NEW
  ↓
Hook injects: Complete agent YAML (identity, capabilities, philosophy) ← NEW
  ↓
Claude Code: [Transforms into Database Debug Specialist]
              [Responds with systematic database debugging methodology]
```

**Result**: Claude Code fully assumes agent identity and capabilities.

---

## What's Already Working ✅

Good news - 95% of infrastructure is complete:

1. **Agent Routing** ✅
   - Event-based routing via Kafka
   - 90%+ confidence scores
   - Database logging

2. **Agent Definitions** ✅
   - 50+ agent YAML files
   - Complete configurations
   - Identity, capabilities, philosophy

3. **Agent Invoker** ✅
   - `agent_invoker.py` (488 lines)
   - `invoke_agent_from_hook.py` (270 lines)
   - Ready to use - just not being called!

4. **Database Tracking** ✅
   - All tables exist
   - Complete audit trail
   - Correlation ID tracking

**Only Missing**: 35 lines in hook script to call the invoker!

---

## Implementation Steps

### 1. Read the Analysis

Start with **AGENT_INVOCATION_GAP_ANALYSIS.md**:
- Understand the complete flow
- See what's broken and why
- Review expected vs actual behavior

### 2. Review the Migration

Read **015_hook_agent_invocation_integration.md**:
- See exact code changes needed
- Review testing plan
- Understand rollback strategy

### 3. Pre-Implementation Testing

```bash
# Test agent invoker works
echo '{"prompt": "debug database", "correlation_id": "test-123", "session_id": "test", "context": {}}' | \
  python3 ~/.claude/hooks/lib/invoke_agent_from_hook.py

# Expected output:
{
  "success": true,
  "pathway": "direct_single",
  "agent_name": "agent-debug-database",
  "context_injection": "# POLYMORPHIC AGENT IDENTITY INJECTION..."
}
```

If this fails, fix before proceeding.

### 4. Backup

```bash
# Backup hook script
cp ~/.claude/hooks/user-prompt-submit.sh \
   ~/.claude/hooks/user-prompt-submit.sh.backup-$(date +%Y%m%d)
```

### 5. Implement Changes

Edit `~/.claude/hooks/user-prompt-submit.sh`:

**Location 1**: After line 123 (after routing completes)
```bash
# Add agent invocation section (~30 lines)
# See migration doc for exact code
```

**Location 2**: Line 384 (AGENT_CONTEXT generation)
```bash
# Modify to include AGENT_YAML_INJECTION
# See migration doc for exact code
```

### 6. Test

```bash
# Test 1: Database debugging
# (Trigger via Claude Code UI)
Prompt: "Help me debug a slow PostgreSQL query"

# Check logs
tail -50 ~/.claude/hooks/hook-enhanced.log

# Should see:
[...] Invoking agent via invoke_agent_from_hook.py...
[...] Agent YAML loaded successfully (2847 chars)

# Test 2: API design
Prompt: "Design a REST API for user management"

# Test 3: DevOps
Prompt: "Fix Docker container that won't start"
```

### 7. Verify

After each test:
- [ ] Hook log shows agent invocation
- [ ] YAML loaded successfully
- [ ] Claude Code responds as specialized agent (NOT generic)
- [ ] Database has routing and execution records
- [ ] Correlation ID links everything

### 8. Monitor

Watch for 24-48 hours:
- Check success rate: >95%
- Check latency: <200ms
- Check failures: minimal
- Check database: complete records

---

## Quick Verification Script

```bash
#!/bin/bash
# verify_agent_invocation.sh

echo "=== Agent Invocation Verification ==="

# 1. Check agent invoker exists and works
echo "1. Testing agent invoker..."
result=$(echo '{"prompt":"test","correlation_id":"test","session_id":"test","context":{}}' | \
  python3 ~/.claude/hooks/lib/invoke_agent_from_hook.py 2>/dev/null)

if echo "$result" | grep -q "success"; then
  echo "✅ Agent invoker working"
else
  echo "❌ Agent invoker failed"
  echo "$result"
  exit 1
fi

# 2. Check agent YAMLs exist
echo "2. Checking agent definitions..."
yaml_count=$(ls ~/.claude/agent-definitions/*.yaml 2>/dev/null | wc -l)
if [ "$yaml_count" -gt 10 ]; then
  echo "✅ Found $yaml_count agent YAML files"
else
  echo "❌ Missing agent YAML files (found: $yaml_count)"
  exit 1
fi

# 3. Check hook has invocation code
echo "3. Checking hook integration..."
if grep -q "invoke_agent_from_hook.py" ~/.claude/hooks/user-prompt-submit.sh; then
  echo "✅ Hook has invocation integration"
else
  echo "⚠️  Hook missing invocation integration (not yet implemented)"
fi

# 4. Check recent invocations
echo "4. Checking recent invocations..."
recent=$(grep -c "Agent YAML loaded successfully" ~/.claude/hooks/hook-enhanced.log 2>/dev/null || echo "0")
echo "   Recent invocations: $recent"

echo ""
echo "=== Summary ==="
echo "Agent invoker: Ready"
echo "Agent YAMLs: $yaml_count files"
echo "Hook integration: $(grep -q invoke_agent_from_hook.py ~/.claude/hooks/user-prompt-submit.sh && echo "✅" || echo "❌")"
echo "Recent uses: $recent"
```

---

## Troubleshooting

### Issue: Agent YAML Not Loading

**Symptoms**:
```
[...] WARNING: Agent invocation failed
[...] Agent YAML loaded successfully (0 chars)
```

**Debug**:
```bash
# Test invoker directly
echo '{"prompt":"debug db","correlation_id":"test","session_id":"test","context":{}}' | \
  python3 ~/.claude/hooks/lib/invoke_agent_from_hook.py

# Check error output
```

**Common Causes**:
1. Agent YAML file missing or corrupted
2. Python path issues
3. YAML syntax errors

**Fix**:
```bash
# Verify YAML exists
ls ~/.claude/agent-definitions/debug-database.yaml

# Test YAML syntax
python3 -c "import yaml; yaml.safe_load(open('/Users/jonah/.claude/agent-definitions/debug-database.yaml'))"
```

### Issue: Hook Timeout

**Symptoms**:
```
[...] Invoking agent via invoke_agent_from_hook.py...
[...] WARNING: Agent invocation failed
```

**Debug**:
```bash
# Check timeout in hook
grep "timeout 3" ~/.claude/hooks/user-prompt-submit.sh
```

**Fix**:
```bash
# Increase timeout if needed (in hook script)
timeout 5 python3 "${HOOKS_LIB}/invoke_agent_from_hook.py"
```

### Issue: No Agent Detected

**Symptoms**:
```
[...] No agent detected, passing through
```

**This is NOT this migration's issue** - this is routing detection.

**Debug routing instead**:
```bash
# Check routing service
curl http://localhost:8055/health 2>/dev/null || echo "Router service not running"

# Check agent registry
ls ~/.claude/agent-definitions/agent-registry.yaml
```

---

## Rollback

If problems occur:

```bash
# Option 1: Quick disable
# Edit user-prompt-submit.sh, add at line 125:
AGENT_YAML_INJECTION=""  # Force disabled

# Option 2: Full revert
cp ~/.claude/hooks/user-prompt-submit.sh.backup-YYYYMMDD \
   ~/.claude/hooks/user-prompt-submit.sh
```

---

## Success Metrics

After 1 week of running:

```sql
-- 1. Agent invocation success rate
SELECT
  COUNT(*) FILTER (WHERE agent_name != 'polymorphic-agent') as specialized_agents,
  COUNT(*) as total_agents,
  COUNT(*) FILTER (WHERE agent_name != 'polymorphic-agent') * 100.0 / COUNT(*) as specialization_rate
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '7 days';

-- Target: >80% specialization rate (more than polymorphic-agent fallback)
```

```bash
# 2. YAML injection success rate
invocations=$(grep -c "Invoking agent" ~/.claude/hooks/hook-enhanced.log)
successes=$(grep -c "Agent YAML loaded successfully" ~/.claude/hooks/hook-enhanced.log)
success_rate=$((successes * 100 / invocations))

echo "Success rate: $success_rate%"
# Target: >95%
```

---

## Related Documentation

**Investigation**:
- `AGENT_INVOCATION_GAP_ANALYSIS.md` - Complete root cause analysis

**Implementation**:
- `015_hook_agent_invocation_integration.md` - Step-by-step migration guide

**Architecture**:
- `/Users/jonah/.claude/hooks/AGENT_DISPATCH_SYSTEM.md` - Agent dispatch overview
- `CLAUDE.md` - Polymorphic agent framework documentation

**Code**:
- `~/.claude/hooks/user-prompt-submit.sh` - Hook script to modify
- `~/.claude/hooks/lib/invoke_agent_from_hook.py` - Agent invoker CLI
- `agents/lib/agent_invoker.py` - Core invocation logic

---

## Timeline

**Total Estimated Time**: 2-3 hours

| Phase | Time | Tasks |
|-------|------|-------|
| **Pre-work** | 15 min | Read docs, verify prerequisites |
| **Backup** | 5 min | Backup hook script |
| **Implementation** | 30-45 min | Add invocation code to hook |
| **Testing** | 45-60 min | Test 3+ agents, verify behavior |
| **Documentation** | 30 min | Update docs to reflect reality |
| **Monitoring** | Ongoing | Watch for issues over 24-48h |

---

## Questions?

**Q**: Will this break existing functionality?
**A**: No - graceful degradation if invocation fails. Hook still works without YAML.

**Q**: What if agent YAML is missing?
**A**: Falls back to directive-only mode (current behavior). Non-blocking.

**Q**: How much slower will hooks be?
**A**: +25ms average (75-125ms total, still under 200ms target).

**Q**: Can I test without modifying the hook?
**A**: Yes - test `invoke_agent_from_hook.py` standalone first.

**Q**: What if I need to rollback?
**A**: Just restore backup or set `AGENT_YAML_INJECTION=""` to disable.

---

## Next Steps

1. ✅ Read **AGENT_INVOCATION_GAP_ANALYSIS.md** (understand the problem)
2. ✅ Read **015_hook_agent_invocation_integration.md** (implementation plan)
3. ⏭️ **Test agent invoker standalone** (verify prerequisites)
4. ⏭️ **Backup hook script** (safety first)
5. ⏭️ **Implement changes** (35 lines of code)
6. ⏭️ **Test with real prompts** (verify behavior)
7. ⏭️ **Monitor and validate** (ensure success)

---

**Priority**: HIGH - This enables the core polymorphic agent functionality

**Confidence**: HIGH - All infrastructure exists, just needs to be wired together

**Risk**: LOW - Non-blocking, graceful degradation, easy rollback
