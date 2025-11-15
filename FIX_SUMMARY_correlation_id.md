# Fix Summary: correlation_id NULL Constraint Violation

**Issue ID**: 6e121289-333c-47c9-a708-cc670675f055
**Priority**: CRITICAL (blocking event processing)
**Status**: ✅ FIXED
**Date**: 2025-11-15

---

## Problem

Agent routing decisions were failing to insert into the `agent_routing_decisions` table due to a NOT NULL constraint violation on the `correlation_id` column.

### Error Message

```
psycopg2.errors.NotNullViolation: null value in column "correlation_id" of relation "agent_routing_decisions" violates not-null constraint

Failing row: correlation_id is NULL (position 2)
BUT metadata contains: {"correlation_id": "16b9740f-cc5f-4950-b9cd-5e33fb807da2"}
```

### Root Cause

The `_insert_routing_decisions()` method in `consumers/agent_actions_consumer.py` was:
1. ❌ Missing `correlation_id` from the INSERT column list
2. ❌ Not extracting `correlation_id` from event data
3. ❌ Not populating `correlation_id` in the batch data tuple

This caused the database to receive NULL for correlation_id, violating the NOT NULL constraint.

---

## Solution

### Changes Made

**File**: `consumers/agent_actions_consumer.py`
**Method**: `_insert_routing_decisions()` (lines 671-732)

1. **Added `correlation_id` to INSERT column list** (line 677)
   ```sql
   INSERT INTO agent_routing_decisions (
       id, correlation_id, project_name, user_request, ...
   ```

2. **Implemented correlation_id extraction logic** (lines 690-710)
   - Tries top-level `event.get("correlation_id")` first
   - Falls back to `event.get("metadata", {}).get("correlation_id")`
   - Converts string to UUID if needed
   - Generates new UUID if missing or invalid
   - Logs warnings for missing/invalid values

3. **Added correlation_id to batch_data tuple** (line 715)
   ```python
   batch_data.append((
       event_id,
       correlation_id,  # ✅ Now populated
       event.get("project_name"),
       ...
   ))
   ```

### Pattern Followed

The fix follows the same pattern as `_insert_transformation_events()` (lines 753-761), which already correctly handles correlation_id extraction and UUID conversion.

---

## Validation

### 1. Syntax Validation
```bash
✅ Syntax check passed
✅ Column count: 12
✅ Placeholder count: 12
✅ Counts match: True
✅ correlation_id is column 2: True
```

### 2. Logic Testing
All test scenarios passed:
- ✅ Extract from top-level field (preferred path)
- ✅ Extract from metadata field (fallback for failing events)
- ✅ Generate new UUID if missing
- ✅ Generate new UUID if invalid format

### 3. Deployment
```bash
✅ Container rebuilt successfully
✅ Consumer restarted: omniclaude_agent_consumer
✅ No new constraint violations after restart
✅ Consumer subscribed to all topics including agent-routing-decisions
```

---

## Impact

### Before Fix
- ❌ Agent routing decisions failed to persist to database
- ❌ constraint violation errors in logs
- ❌ Events sent to DLQ (dead letter queue)
- ❌ Lost traceability for routing decisions

### After Fix
- ✅ correlation_id properly extracted from events
- ✅ Handles both top-level and metadata locations
- ✅ No more constraint violations
- ✅ Routing decisions successfully persisted
- ✅ Full traceability maintained

---

## Edge Cases Handled

1. **correlation_id at top level** (preferred)
   - Standard event structure with correlation_id as direct field
   - Most common case

2. **correlation_id in metadata** (fallback)
   - Handles events where correlation_id is nested in metadata
   - This was the failing case from the error message

3. **Missing correlation_id** (generate)
   - Generates new UUID if correlation_id is completely missing
   - Logs warning for visibility

4. **Invalid UUID format** (generate)
   - Handles malformed UUID strings
   - Generates new UUID and logs warning

---

## Verification Steps

To verify the fix is working:

```bash
# 1. Check consumer logs for errors
docker logs --tail 100 omniclaude_agent_consumer 2>&1 | grep -i "error\|correlation"

# 2. Check for successful routing decision inserts
docker logs --tail 100 omniclaude_agent_consumer 2>&1 | grep "agent-routing-decisions"

# 3. Query database for recent routing decisions
source .env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT id, correlation_id, selected_agent, created_at FROM agent_routing_decisions ORDER BY created_at DESC LIMIT 10;"

# 4. Verify no NULL correlation_id values
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT COUNT(*) FROM agent_routing_decisions WHERE correlation_id IS NULL;"
# Should return 0
```

---

## Related Files

- **Fixed**: `consumers/agent_actions_consumer.py` (lines 671-732)
- **Test**: `test_correlation_id_fix.py` (validation script)
- **Container**: `omniclaude_agent_consumer` (restarted)
- **Service**: `agent-observability-consumer` (docker-compose service name)

---

## Success Criteria

All criteria met:

- ✅ correlation_id extracted from event metadata
- ✅ correlation_id populated in agent_routing_decisions.correlation_id column
- ✅ No more NOT NULL constraint violations
- ✅ Existing events continue to work
- ✅ Edge cases handled gracefully (missing/invalid correlation_id)
- ✅ Warnings logged for missing/invalid values
- ✅ Consumer running without errors
- ✅ Full backward compatibility maintained

---

## Monitoring

**Watch for**:
- Warnings about missing correlation_id (may indicate upstream issues)
- Warnings about invalid UUID formats (may indicate data quality issues)

**Metrics to track**:
- Routing decision insert success rate (should be 100%)
- correlation_id NULL count (should remain 0)
- DLQ message rate for agent-routing-decisions (should drop to 0)

---

## Follow-up Actions

**Optional improvements** (not blocking):

1. **Standardize event structure** - Ensure all routing decision events have correlation_id at top level
2. **Upstream validation** - Add correlation_id validation at event producer level
3. **Monitoring dashboard** - Add metric for correlation_id extraction warnings
4. **Documentation update** - Document expected event structure for routing decisions

---

**Fix completed**: 2025-11-15
**Deployed**: ✅ Consumer restarted with fix
**Tested**: ✅ All scenarios validated
**Impact**: CRITICAL issue resolved - event processing unblocked
