# Agent Observability Diagnostic Plan

**Created**: 2025-10-24
**Issue**: Agent execution tables exist but contain no/stale data
**Goal**: Diagnose why agent logging isn't working and fix observability

---

## Current Status

### ✅ What We Fixed Today
1. **IntelligenceEventClient** - Now sends file content (21KB+), not empty strings
2. **Database Connection** - Added PG_DSN to .env, connects to localhost:5436
3. **AgentExecutionLogger** - New comprehensive logger with DB + file fallback
4. **Integration Test** - Verifies intelligence service responses (quality_score=0.43)

### ❌ What's Broken
**Agent tables exist but have NO DATA**:
- `agent_execution_logs` - Should log all agent executions
- `agent_routing_decisions` - Should log routing decisions
- `agent_actions` - Should log agent actions
- Other agent_* tables - All empty or stale

---

## Investigation Plan

### Phase 1: Analyze Existing Scripts ✅

**Files to investigate**:
```bash
analyze_intelligence.py       # Uses IntelligenceEventClient directly
analyze_with_archon.py         # Uses Archon MCP tools
```

**Questions**:
1. Are these scripts useful as integration tests?
2. Do they demonstrate correct usage patterns?
3. Should they be moved to agents/tests/ or deleted?
4. Can we extract reusable patterns from them?

**Action**: Review scripts, decide keep/convert/delete

---

### Phase 2: Database Schema Audit

**Task**: Verify all agent observability tables

```sql
-- Check which tables exist
\dt agent_*

-- Check which tables have data
SELECT 'agent_execution_logs' as table_name, COUNT(*) FROM agent_execution_logs
UNION ALL
SELECT 'agent_routing_decisions', COUNT(*) FROM agent_routing_decisions
UNION ALL
SELECT 'agent_actions', COUNT(*) FROM agent_actions
UNION ALL
SELECT 'agent_detection_failures', COUNT(*) FROM agent_detection_failures
UNION ALL
SELECT 'agent_transformation_events', COUNT(*) FROM agent_transformation_events;

-- Check most recent entries (if any)
SELECT table_name, MAX(created_at) as last_entry
FROM (
  SELECT 'agent_execution_logs' as table_name, started_at as created_at
    FROM agent_execution_logs
  UNION ALL
  SELECT 'agent_routing_decisions', decision_timestamp FROM agent_routing_decisions
) sub
GROUP BY table_name;
```

**Expected Issues**:
- Tables exist but empty
- Old/stale data from previous testing
- Schema mismatches (wrong column names)

**Action**: Document current state, identify schema issues

---

### Phase 3: Code Flow Analysis

**Trace the logging path**:

1. **Agent Dispatch Flow**
   ```
   User Request → Enhanced Router → Agent Selection → ???
   Where does logging happen?
   ```

2. **Expected Logging Points**
   - `enhanced_router.py` - Should log routing decisions to `agent_routing_decisions`
   - Agent execution - Should use `AgentExecutionLogger` → `agent_execution_logs`
   - Hook triggers - Should log to `hook_events`

3. **Find the Gap**
   ```bash
   # Search for code that SHOULD be logging
   grep -r "agent_execution_logs" agents/
   grep -r "agent_routing_decisions" agents/
   grep -r "AgentExecutionLogger" agents/

   # Find if anyone is using the old error_logging.py
   grep -r "from.*error_logging" agents/
   grep -r "from.*success_logging" agents/
   ```

**Action**: Map expected vs actual logging calls

---

### Phase 4: Integration Points

**Check if logging is integrated**:

1. **Enhanced Router** (`agents/lib/enhanced_router.py`)
   - Does it log routing decisions?
   - Where should it call `agent_routing_decisions` insert?
   - Is it using the skills/agent-tracking/log-routing-decision?

2. **Polymorphic Agent** (`agents/definitions/polymorphic-agent.yaml`)
   - Should it use AgentExecutionLogger?
   - Where in the agent lifecycle?

3. **Skills** (`skills/`)
   - `log-execution/execute.py` - Correct implementation reference
   - `agent-tracking/` - What do these skills do?
   - Are skills being called at all?

**Action**: Identify missing integration points

---

### Phase 5: Skills Investigation

**Analyze agent tracking skills**:

```bash
ls -la skills/agent-tracking/
ls -la skills/log-execution/
```

**Questions**:
1. What skills exist for agent logging?
2. Are they being invoked?
3. Do they use the correct tables?
4. Are they using Kafka or direct DB writes?

**Key Files**:
- `skills/log-execution/execute.py` - ✅ Correct pattern (uses agent_execution_logs)
- `skills/agent-tracking/*/execute_kafka.py` - Check if using Kafka events
- Look for any skills calling old `error_events`/`success_events` tables

**Action**: Audit all skills, fix broken ones

---

### Phase 6: Environment & Configuration

**Verify runtime environment**:

1. **Database Connection**
   ```bash
   # Test connection
   poetry run python -c "
   import asyncio
   from agents.lib.db import get_pg_pool

   async def test():
       pool = await get_pg_pool()
       if pool:
           async with pool.acquire() as conn:
               result = await conn.fetchval('SELECT current_database()')
               print(f'Connected to: {result}')
       else:
           print('ERROR: No database pool')

   asyncio.run(test())
   "
   ```

2. **Environment Variables**
   ```bash
   # Check if PG_DSN is loaded in runtime
   env | grep PG_DSN
   env | grep POSTGRES_
   ```

3. **Kafka Configuration**
   ```bash
   # Check if Kafka events are configured
   env | grep KAFKA
   env | grep REDPANDA
   ```

**Action**: Ensure environment is correct for all execution contexts

---

### Phase 7: Test Execution

**Create test that exercises full path**:

```python
# Test: agents/tests/test_agent_observability.py

import asyncio
import pytest
from agents.lib.agent_execution_logger import log_agent_execution
from agents.lib.db import get_pg_pool

@pytest.mark.integration
async def test_agent_execution_logging():
    """Verify agent execution logging writes to database."""

    # Create and log execution
    logger = await log_agent_execution(
        agent_name="test-observability",
        user_prompt="Test full logging path",
    )

    await logger.progress(stage="testing", percent=50)
    await logger.complete(status="success", quality_score=0.95)

    # Verify database entry exists
    pool = await get_pg_pool()
    assert pool is not None, "Database pool not available"

    async with pool.acquire() as conn:
        result = await conn.fetchrow(
            "SELECT * FROM agent_execution_logs WHERE execution_id = $1",
            logger.execution_id
        )

        assert result is not None, "No database entry found"
        assert result["agent_name"] == "test-observability"
        assert result["status"] == "success"
        assert result["quality_score"] == 0.95
        assert result["duration_ms"] > 0
```

**Action**: Run test, identify failures

---

### Phase 8: Fix Implementation

**Based on findings, implement fixes**:

1. **If agents aren't using logger**:
   - Add AgentExecutionLogger to agent base class
   - Update polymorphic-agent to use it
   - Add lifecycle hooks (start/progress/complete)

2. **If router isn't logging**:
   - Add routing decision logging to enhanced_router.py
   - Use agent_routing_decisions table
   - Log: agent_name, confidence, method, triggers matched

3. **If skills aren't being called**:
   - Identify why skills aren't invoked
   - Add skill invocation to agent lifecycle
   - Or convert skills to direct library calls

4. **If schema mismatches**:
   - Update code to match actual schema
   - Or run migrations to fix schema
   - Document required schema in docs/

**Action**: Implement fixes systematically

---

### Phase 9: Validation

**Verify fixes work end-to-end**:

1. **Run integration test suite**
   ```bash
   poetry run pytest -m integration agents/tests/
   ```

2. **Execute real agent workflow**
   ```bash
   # Use a real agent and verify it logs
   # Check database after execution
   ```

3. **Check database**
   ```sql
   -- Should have recent entries
   SELECT * FROM agent_execution_logs
   ORDER BY started_at DESC LIMIT 10;

   SELECT * FROM agent_routing_decisions
   ORDER BY decision_timestamp DESC LIMIT 10;
   ```

4. **Check fallback logs**
   ```bash
   ls -la /tmp/omniclaude_logs/$(date +%Y-%m-%d)/
   ```

**Success Criteria**:
- ✅ Every agent execution creates database entry
- ✅ Routing decisions logged
- ✅ Quality scores captured
- ✅ Fallback logs work when DB unavailable
- ✅ Integration tests pass

---

## Quick Start Commands

```bash
# 1. Check database tables
PGPASSWORD='omninode-bridge-postgres-dev-2024' psql -h localhost -p 5436 \
  -U postgres -d omninode_bridge -c "\dt agent_*"

# 2. Check table data counts
PGPASSWORD='omninode-bridge-postgres-dev-2024' psql -h localhost -p 5436 \
  -U postgres -d omninode_bridge -c "
  SELECT 'agent_execution_logs' as tbl, COUNT(*) FROM agent_execution_logs
  UNION ALL
  SELECT 'agent_routing_decisions', COUNT(*) FROM agent_routing_decisions
  UNION ALL
  SELECT 'agent_actions', COUNT(*) FROM agent_actions;"

# 3. Test new logger
poetry run python -c "
import asyncio
from agents.lib.agent_execution_logger import log_agent_execution

async def test():
    logger = await log_agent_execution(
        agent_name='diagnostic-test',
        user_prompt='Testing observability'
    )
    await logger.progress(stage='testing', percent=50)
    await logger.complete(status='success', quality_score=0.90)
    print(f'✅ Logged execution: {logger.execution_id}')

asyncio.run(test())
"

# 4. Verify it worked
PGPASSWORD='omninode-bridge-postgres-dev-2024' psql -h localhost -p 5436 \
  -U postgres -d omninode_bridge -c "
  SELECT execution_id, agent_name, status, quality_score, duration_ms
  FROM agent_execution_logs
  WHERE agent_name = 'diagnostic-test'
  ORDER BY started_at DESC LIMIT 1;"

# 5. Check fallback logs
ls -la /tmp/omniclaude_logs/$(date +%Y-%m-%d)/

# 6. Review analyze scripts
cat analyze_intelligence.py | head -50
cat analyze_with_archon.py | head -50
```

---

## Files to Review

### New Files Created Today
- `agents/lib/agent_execution_logger.py` - ✅ Comprehensive logger (READY)
- `agents/tests/test_intelligence_event_client.py::TestIntelligenceIntegration` - ✅ Integration test (WORKING)

### Scripts to Investigate
- `analyze_intelligence.py` - **TODO: Review for test conversion**
- `analyze_with_archon.py` - **TODO: Review for test conversion**

### Existing Files to Audit
- `agents/lib/enhanced_router.py` - Does it log routing decisions?
- `agents/lib/error_logging.py` - Uses wrong tables (error_events)
- `agents/lib/success_logging.py` - Uses wrong tables (success_events)
- `skills/log-execution/execute.py` - ✅ Correct pattern
- `skills/agent-tracking/*/` - All tracking skills

### Configuration
- `.env` - ✅ PG_DSN added
- Database schema - Need to verify all tables

---

## Expected Outcomes

1. **Root Cause Identified**
   - Why agent tables are empty
   - Which integration points are missing
   - What needs to be added/fixed

2. **Working Observability**
   - All agent executions logged
   - Routing decisions captured
   - Quality scores tracked
   - Trend analysis possible

3. **Clean Codebase**
   - Remove/convert analyze scripts
   - Delete old error_logging/success_logging
   - Standardize on AgentExecutionLogger
   - Document logging patterns

---

## Next Session Actions

When context resets, use this plan to:

1. **Start Phase 2**: Database schema audit
2. **Review analyze scripts**: Keep/convert/delete decision
3. **Map logging flow**: Find the gaps
4. **Implement fixes**: Add missing integrations
5. **Validate**: Run tests, check database

**Success = Every agent execution appears in agent_execution_logs with quality scores**
