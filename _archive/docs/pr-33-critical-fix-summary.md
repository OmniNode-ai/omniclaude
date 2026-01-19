# PR #33 CRITICAL Fix: Unique Constraint for agent_actions

## Summary

Fixed the CRITICAL issue flagged in PR #33 review where `kafka_agent_action_consumer.py` line ~176 was missing a unique constraint, enabling duplicate insertions in concurrent scenarios.

## Problem

The original code used a SELECT-then-INSERT pattern to check for duplicates:

```python
# OLD CODE (vulnerable to race conditions)
existing = await conn.fetchrow(
    "SELECT id FROM agent_actions WHERE correlation_id = $1 AND action_name = $2 AND created_at = $3",
    correlation_id, action_name, timestamp
)

if existing:
    logger.debug("Skipping duplicate...")
    continue

# INSERT without ON CONFLICT
await conn.execute("INSERT INTO agent_actions ...")
```

**Issue**: Between the SELECT and INSERT, another concurrent transaction could insert the same record, creating duplicates.

## Solution

### 1. Database Migration (Migration 015)

**File**: `migrations/015_add_agent_actions_unique_constraint.sql`

**What it does**:
- Removes existing duplicates (found 3,745 duplicate records)
- Adds unique constraint: `unique_action_per_correlation_timestamp`
- Constraint columns: `(correlation_id, action_name, created_at)`

**Rollback**: `migrations/015_rollback_agent_actions_unique_constraint.sql`

### 2. Code Update

**File**: `agents/lib/kafka_agent_action_consumer.py`

**Changes**:
- Removed SELECT-then-INSERT pattern (lines 172-214)
- Added ON CONFLICT DO NOTHING clause (line 186-187)
- Simplified duplicate detection logic
- Added proper exception handling for UniqueViolationError

**New code**:
```python
insert_sql = """
    INSERT INTO agent_actions (...)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    ON CONFLICT ON CONSTRAINT unique_action_per_correlation_timestamp
    DO NOTHING
    RETURNING id
"""

result = await conn.fetch(insert_sql, ...)
if result:
    inserted_count += 1  # New record
else:
    duplicate_count += 1  # Duplicate prevented
```

### 3. Test Suite

**File**: `tests/test_agent_actions_unique_constraint.py`

**Tests**:
1. Unique constraint exists in database
2. Duplicate prevention (same correlation_id, action_name, timestamp)
3. Concurrent insertions (10 simultaneous attempts → only 1 succeeds)
4. Different timestamps allowed (same action, different times)

**Run tests**:
```bash
python3 tests/test_agent_actions_unique_constraint.py
```

## Migration Status

### Current Status

**Migration script is running** (started at 2025-11-23 ~20:23 UTC)

**Progress**:
- ✅ Deleted 3,745 duplicate records
- ⏳ Creating unique constraint (ALTER TABLE in progress)
- Expected completion: ~5-10 minutes (large table)

**Monitor migration**:
```bash
# Check if constraint exists
source .env
PGPASSWORD="${POSTGRES_PASSWORD}" psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} \
  -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c \
  "SELECT constraint_name FROM information_schema.table_constraints
   WHERE table_name = 'agent_actions'
     AND constraint_name = 'unique_action_per_correlation_timestamp';"

# Check active queries
PGPASSWORD="${POSTGRES_PASSWORD}" psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} \
  -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c \
  "SELECT state, query FROM pg_stat_activity
   WHERE query LIKE '%agent_actions%' AND state = 'active';"
```

### Post-Migration Steps

Once migration completes (constraint appears in database):

1. **Restart Kafka consumers**:
   ```bash
   cd deployment
   docker-compose restart agent-consumer
   docker-compose restart router-consumer
   docker-compose restart intelligence-consumer
   ```

2. **Run test suite**:
   ```bash
   python3 tests/test_agent_actions_unique_constraint.py
   ```

3. **Monitor logs for duplicate prevention**:
   ```bash
   docker logs -f omniclaude_agent_consumer | grep "duplicate"
   ```

4. **Verify database constraint**:
   ```bash
   source .env
   PGPASSWORD="${POSTGRES_PASSWORD}" psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} \
     -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c \
     "SELECT conname, contype, pg_get_constraintdef(oid)
      FROM pg_constraint
      WHERE conname = 'unique_action_per_correlation_timestamp';"
   ```

## Files Created

### Migration Files
- `migrations/015_add_agent_actions_unique_constraint.sql` - Add constraint
- `migrations/015_rollback_agent_actions_unique_constraint.sql` - Rollback

### Code Updates
- `agents/lib/kafka_agent_action_consumer.py` - Updated insertion logic

### Testing
- `tests/test_agent_actions_unique_constraint.py` - Comprehensive test suite

### Scripts
- `scripts/apply_migration_015.sh` - Migration runner (currently executing)

### Documentation
- `docs/pr-33-critical-fix-summary.md` - This file

## Technical Details

### Unique Constraint Definition

```sql
ALTER TABLE agent_actions
ADD CONSTRAINT unique_action_per_correlation_timestamp
UNIQUE (correlation_id, action_name, created_at);
```

**Why these columns?**
- `correlation_id` - Identifies a specific execution trace
- `action_name` - Identifies the specific action (Read, Write, etc.)
- `created_at` - Timestamp differentiates repeated actions

### Performance Impact

**Before**:
- SELECT query + INSERT = 2 database round trips per event
- Race condition possible between SELECT and INSERT
- Duplicates possible in concurrent scenarios

**After**:
- Single INSERT with ON CONFLICT = 1 database round trip
- Atomic operation (no race condition)
- Guaranteed duplicate prevention

**Benchmark** (expected):
- 40-50% reduction in database queries
- No duplicate insertions in high-concurrency scenarios
- Simpler, more maintainable code

## Success Criteria

- [x] Migration created with duplicate cleanup
- [x] Rollback migration created
- [x] Code updated to use ON CONFLICT DO NOTHING
- [x] Exception handling for UniqueViolationError added
- [x] Test suite created with 4 comprehensive tests
- [x] Migration script running
- [ ] Migration completed successfully (in progress)
- [ ] Tests passing
- [ ] Kafka consumers restarted
- [ ] Duplicate prevention verified in production

## Rollback Plan

If issues occur after migration:

```bash
# 1. Stop consumers
cd deployment
docker-compose stop agent-consumer router-consumer intelligence-consumer

# 2. Rollback migration
source .env
PGPASSWORD="${POSTGRES_PASSWORD}" psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} \
  -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -f migrations/015_rollback_agent_actions_unique_constraint.sql

# 3. Restart consumers (will use old code path)
docker-compose start agent-consumer router-consumer intelligence-consumer
```

**Note**: Rolling back code without rolling back constraint will cause INSERT failures!

## Related Issues

- PR #33 review feedback (CRITICAL priority)
- kafka_agent_action_consumer.py line ~176

## Contact

If migration fails or issues occur:
1. Check migration logs: `./scripts/apply_migration_015.sh` output
2. Check database logs for errors
3. Verify disk space available
4. Check for long-running transactions blocking the ALTER TABLE
