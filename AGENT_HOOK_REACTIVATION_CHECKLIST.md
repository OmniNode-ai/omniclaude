# Agent Hook Reactivation Checklist

## Current Status: DISABLED ⚠️

**Date Disabled**: 2025-10-10
**Reason**: Python dependency issues in agent framework preventing parallel dispatch and invocation
**Hook Modified**: `/Users/jonah/.claude/hooks/user-prompt-submit-enhanced.sh`

---

## What's Disabled

The following functionality has been temporarily disabled in the UserPromptSubmit hook:

- ❌ Agent detection (agent_detector.py)
- ❌ Agent context injection
- ❌ Background intelligence gathering (RAG queries)
- ❌ Agent identity polymorphism
- ❌ hookSpecificOutput.additionalContext injection

## What's Still Working

The following hook functionality remains operational:

- ✅ Basic prompt passthrough
- ✅ Correlation ID generation and tracking
- ✅ Database event logging (hook_events table)
- ✅ Enhanced metadata extraction
- ✅ Session tracking
- ✅ Log file recording

---

## Root Cause: Dependency Chain Failure

### Error Details

```
ERROR: Failed to import agent framework:
Please install `google-genai` to use the Google model
```

### Error Chain

1. `agent_invoker.py` attempts to import from agent framework
2. Agent framework (`agent_dispatcher.py`) imports Pydantic AI components
3. Pydantic AI tries to load Google model plugin
4. Missing `google-genai` package causes import failure
5. Entire `agent_invoker.py` module becomes unusable
6. Hook cannot invoke agents via any pathway

### Affected Components

- ❌ `agent_invoker.py` - Cannot import due to framework dependencies
- ❌ `invoke_agent_from_hook.py` - Depends on agent_invoker
- ✅ `agent_pathway_detector.py` - Standalone, works correctly
- ✅ `agent_detector.py` - Works, but disabled to avoid broken integration

---

## Reactivation Checklist

### Phase 1: Fix Dependencies (Required)

- [ ] **Install missing Python packages**
  ```bash
  cd /Volumes/PRO-G40/Code/omniclaude
  pip install google-genai
  pip install pydantic-ai-slim[google]
  pip install certifi  # For SSL certificate verification
  ```

- [ ] **Verify agent framework imports**
  ```bash
  cd /Users/jonah/.claude/hooks/lib
  python3 -c "from agent_invoker import AgentInvoker; print('✓ Import successful')"
  ```

- [ ] **Test pathway detector standalone**
  ```bash
  python3 agent_pathway_detector.py "@agent-testing Test coverage analysis"
  # Expected: Detects direct_single pathway
  ```

- [ ] **Test agent invoker CLI**
  ```bash
  python3 agent_invoker.py "test prompt" --mode auto --stats
  # Expected: Returns detection result without errors
  ```

### Phase 2: Test Parallel Dispatch (Required)

- [ ] **Test coordinator pathway**
  ```bash
  python3 agent_invoker.py "coordinate: Implement user authentication" --mode coordinator
  # Expected: Returns coordinator invocation result
  ```

- [ ] **Test direct single pathway**
  ```bash
  python3 agent_invoker.py "@agent-testing Analyze test coverage" --mode direct_single
  # Expected: Returns agent config for context injection
  ```

- [ ] **Test direct parallel pathway**
  ```bash
  python3 agent_invoker.py "parallel: @agent-testing, @agent-security Review code" --mode direct_parallel
  # Expected: Returns parallel execution result with multiple agents
  ```

- [ ] **Test via hook integration script**
  ```bash
  echo '{"prompt": "@agent-testing Test", "correlation_id": "test-123", "session_id": "sess-456", "context": {}}' | \
    python3 invoke_agent_from_hook.py
  # Expected: Returns context_injection YAML
  ```

### Phase 3: Verify Database Integration (Required)

- [ ] **Check database tables are accessible**
  ```bash
  PGPASSWORD=omninode-bridge-postgres-dev-2024 psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "\d agent_routing_decisions"
  # Expected: Shows table schema
  ```

- [ ] **Test database logging**
  ```python
  # Test hook_event_logger.py
  python3 -c "
  import sys
  sys.path.insert(0, '/Users/jonah/.claude/hooks/lib')
  from hook_event_logger import log_userprompt
  log_userprompt('Test prompt', 'agent-testing', 'testing', 'test-corr-id', None, {})
  print('✓ Database logging successful')
  "
  ```

- [ ] **Verify tracking tables**
  ```sql
  -- Check if tracking is working
  SELECT COUNT(*) FROM agent_routing_decisions;
  SELECT COUNT(*) FROM hook_events WHERE source = 'UserPromptSubmit';
  ```

### Phase 4: Re-enable Agent Hook (After Phase 1-3 Pass)

- [ ] **Uncomment agent detection in user-prompt-submit-enhanced.sh**

  Find line ~42:
  ```bash
  # DISABLED: Agent detection
  # AGENT_DETECTION=$(python3 "${HOOKS_LIB}/agent_detector.py" "$PROMPT" 2>>"$LOG_FILE" || echo "NO_AGENT_DETECTED")
  ```

  Change to:
  ```bash
  # Agent detection RE-ENABLED (dependencies fixed)
  AGENT_DETECTION=$(python3 "${HOOKS_LIB}/agent_detector.py" "$PROMPT" 2>>"$LOG_FILE" || echo "NO_AGENT_DETECTED")
  ```

- [ ] **Remove force-disable variables**

  Find lines ~46-52:
  ```bash
  # Force no agent detection for now
  AGENT_DETECTION="NO_AGENT_DETECTED"
  AGENT_NAME=""
  DOMAIN_QUERY=""
  IMPL_QUERY=""
  AGENT_DOMAIN=""
  AGENT_PURPOSE=""
  ```

  Remove these lines completely

- [ ] **Restore agent detection conditional**

  Restore the original conditional that checks if agent was detected:
  ```bash
  # Check if agent was detected
  if [[ "$AGENT_DETECTION" == "NO_AGENT_DETECTED" ]] || [[ -z "$AGENT_DETECTION" ]]; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] No agent detected, passing through" >> "$LOG_FILE"
      echo "$INPUT"
      exit 0
  fi

  # Extract agent information
  AGENT_NAME=$(echo "$AGENT_DETECTION" | grep "AGENT_DETECTED:" | cut -d: -f2 | tr -d ' ')
  DOMAIN_QUERY=$(echo "$AGENT_DETECTION" | grep "DOMAIN_QUERY:" | cut -d: -f2-)
  IMPL_QUERY=$(echo "$AGENT_DETECTION" | grep "IMPLEMENTATION_QUERY:" | cut -d: -f2-)
  AGENT_DOMAIN=$(echo "$AGENT_DETECTION" | grep "AGENT_DOMAIN:" | cut -d: -f2-)
  AGENT_PURPOSE=$(echo "$AGENT_DETECTION" | grep "AGENT_PURPOSE:" | cut -d: -f2-)

  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Agent detected: $AGENT_NAME" >> "$LOG_FILE"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Domain: $AGENT_DOMAIN" >> "$LOG_FILE"
  ```

- [ ] **Uncomment context building**

  Find line ~134:
  ```bash
  # DISABLED: Agent context building and injection
  ```

  Restore the full context building section (lines 135-163 in original)

- [ ] **Restore hookSpecificOutput injection**

  Find line ~225:
  ```bash
  # DISABLED: Agent context injection via hookSpecificOutput
  # Output enhanced prompt via hookSpecificOutput.additionalContext
  # echo "$INPUT" | jq --arg context "$AGENT_CONTEXT" '.hookSpecificOutput.hookEventName = "UserPromptSubmit" | .hookSpecificOutput.additionalContext = $context'

  # Pass through without modification while agent detection is disabled
  echo "$INPUT"
  ```

  Change to:
  ```bash
  # Output enhanced prompt via hookSpecificOutput.additionalContext
  echo "$INPUT" | jq --arg context "$AGENT_CONTEXT" '.hookSpecificOutput.hookEventName = "UserPromptSubmit" | .hookSpecificOutput.additionalContext = $context'
  ```

### Phase 5: Integration Testing (After Re-enabling)

- [ ] **Test agent detection end-to-end**
  ```
  User prompt: "@agent-testing Analyze test coverage"
  Expected: Agent context injected, identity assumed
  ```

- [ ] **Test coordinator dispatch**
  ```
  User prompt: "coordinate: Implement authentication system"
  Expected: agent-workflow-coordinator spawned via Task tool
  ```

- [ ] **Test parallel agents**
  ```
  User prompt: "parallel: @agent-testing, @agent-security Review PR #123"
  Expected: Multiple agents invoked in parallel, results aggregated
  ```

- [ ] **Verify database tracking**
  ```sql
  -- After running tests above, check:
  SELECT COUNT(*) FROM agent_routing_decisions WHERE created_at > NOW() - INTERVAL '5 minutes';
  -- Expected: Should show new entries

  SELECT * FROM hook_events WHERE source = 'UserPromptSubmit' ORDER BY created_at DESC LIMIT 5;
  -- Expected: Should show agent detections
  ```

- [ ] **Check correlation tracking**
  ```sql
  -- Verify correlation IDs are properly tracked
  SELECT
    he.created_at,
    he.metadata->>'correlation_id' as corr_id,
    he.payload->>'agent_detected' as agent,
    ard.selected_agent,
    ard.confidence_score
  FROM hook_events he
  LEFT JOIN agent_routing_decisions ard ON he.metadata->>'correlation_id' = ard.correlation_id
  WHERE he.source = 'UserPromptSubmit'
  ORDER BY he.created_at DESC
  LIMIT 10;
  -- Expected: Correlation IDs match between tables
  ```

### Phase 6: Performance Validation (After Integration Tests Pass)

- [ ] **Measure detection overhead**
  - Target: <10ms for pathway detection
  - Target: <30ms for YAML loading
  - Target: <100ms total hook execution

- [ ] **Test with 10 consecutive prompts**
  - Verify no memory leaks
  - Check database connection pooling works
  - Confirm background RAG queries don't block

- [ ] **Stress test parallel mode**
  - Test with 5+ agents in parallel
  - Verify no race conditions
  - Check error handling when agents fail

---

## Known Issues to Watch For

### Issue 1: Import Failures
**Symptom**: Hook logs show "Failed to import agent framework"
**Cause**: Missing Python dependencies
**Fix**: Install all dependencies from Phase 1

### Issue 2: Database Connection Failures
**Symptom**: Hook logs show "Failed to log event to database"
**Cause**: PostgreSQL not running or connection details incorrect
**Fix**: Check database is running on localhost:5436

### Issue 3: Agent Config Not Found
**Symptom**: "Agent config not found: agent-xyz"
**Cause**: YAML file missing or in wrong location
**Fix**: Check files exist in `~/.claude/agents/configs/` or `~/.claude/agent-definitions/`

### Issue 4: Coordinator Not Spawning
**Symptom**: Coordinator pathway detected but agent doesn't execute
**Cause**: ParallelCoordinator initialization failure
**Fix**: Check agent_dispatcher.py logs for errors

---

## Quick Re-enable Command

After all phases pass, use this script to quickly re-enable:

```bash
#!/bin/bash
# quick-reenable-agents.sh

cd /Users/jonah/.claude/hooks

# Backup current version
cp user-prompt-submit-enhanced.sh user-prompt-submit-enhanced.sh.disabled

# Restore from backup (if you made one before disabling)
if [[ -f user-prompt-submit-enhanced.sh.pre-disable ]]; then
    cp user-prompt-submit-enhanced.sh.pre-disable user-prompt-submit-enhanced.sh
    echo "✓ Agent hook restored from backup"
else
    echo "⚠ No backup found. Manually uncomment disabled sections."
fi

# Test
echo '{"prompt": "test"}' | bash user-prompt-submit-enhanced.sh > /dev/null 2>&1
if [[ $? -eq 0 ]]; then
    echo "✓ Hook functional"
else
    echo "✗ Hook test failed"
fi
```

---

## Reference Files

### Modified Files
- `/Users/jonah/.claude/hooks/user-prompt-submit-enhanced.sh` - Main hook file (DISABLED sections)

### New Files Created (Ready to Use)
- `/Users/jonah/.claude/hooks/lib/agent_pathway_detector.py` - Pathway detection (✅ Working)
- `/Users/jonah/.claude/hooks/lib/agent_invoker.py` - Agent invocation (❌ Import failure)
- `/Users/jonah/.claude/hooks/lib/invoke_agent_from_hook.py` - Hook integration (❌ Import failure)
- `/Volumes/PRO-G40/Code/omniclaude/agents/parallel_execution/DUAL_PATHWAY_ARCHITECTURE.md` - Architecture doc

### Dependencies to Install
```bash
pip install google-genai
pip install pydantic-ai-slim[google]
pip install certifi
```

---

## Monitoring After Re-activation

### Log Files to Watch
```bash
# Main hook log
tail -f ~/.claude/hooks/hook-enhanced.log

# Check for errors
grep -i error ~/.claude/hooks/hook-enhanced.log | tail -20

# Check agent detections
grep "Agent detected" ~/.claude/hooks/hook-enhanced.log | tail -10
```

### Database Queries
```sql
-- Agent detection rate
SELECT
    COUNT(*) FILTER (WHERE payload->>'agent_detected' IS NOT NULL) as with_agent,
    COUNT(*) as total,
    ROUND(100.0 * COUNT(*) FILTER (WHERE payload->>'agent_detected' IS NOT NULL) / COUNT(*), 1) as detection_rate_pct
FROM hook_events
WHERE source = 'UserPromptSubmit'
  AND created_at > NOW() - INTERVAL '1 hour';

-- Agent invocation success rate
SELECT
    COUNT(*) FILTER (WHERE confidence_score >= 0.6) as high_confidence,
    COUNT(*) as total,
    AVG(routing_time_ms) as avg_routing_ms
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '1 hour';
```

---

**Status**: Ready for Phase 1 (dependency installation)
**Next Step**: Install Python dependencies and test imports
**Expected Time**: 30-60 minutes for full reactivation

