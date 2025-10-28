# Migration 011: Add execution_succeeded Column

## Overview

Replaces the poorly-named `actual_success` column with the clearer `execution_succeeded` column in the `agent_routing_decisions` table.

## Problem

The `actual_success` column name is unclear:
- Too generic - success of what?
- "actual" prefix is ambiguous without context
- Doesn't clearly indicate this tracks execution outcome vs routing quality
- Hard to understand in isolation

## Solution

Add new `execution_succeeded` boolean column that clearly indicates:
- Whether the selected agent successfully completed the task execution
- NULL = outcome not yet determined
- TRUE = agent successfully completed the task
- FALSE = agent failed to complete the task

## Database Changes

### New Column
```sql
execution_succeeded BOOLEAN DEFAULT NULL
```

### New Indexes
```sql
-- Simple index for filtering by execution outcome
idx_routing_decisions_execution_succeeded

-- Composite index for agent success rate queries
idx_routing_decisions_agent_execution_succeeded (selected_agent, execution_succeeded, created_at DESC)
```

### Data Migration
All existing `actual_success` values are copied to `execution_succeeded`.

## Backward Compatibility

The `actual_success` column is **kept** during this migration for backward compatibility. It will be deprecated in a future migration after:
1. All omnidash code is updated to use `execution_succeeded`
2. All logging/tracking code is updated
3. Production deployment is verified

## Usage

### Apply Migration
```bash
PGPASSWORD='***REDACTED***' psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -f agents/parallel_execution/migrations/011_add_execution_succeeded_column.sql
```

### Verify Migration
```bash
# Check column exists
PGPASSWORD='***REDACTED***' psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "\d agent_routing_decisions" | grep execution_succeeded

# Check indexes created
PGPASSWORD='***REDACTED***' psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "\di idx_routing_decisions_execution_succeeded"

# Verify data copied correctly
PGPASSWORD='***REDACTED***' psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT
    COUNT(*) as total,
    COUNT(actual_success) as old_column_not_null,
    COUNT(execution_succeeded) as new_column_not_null,
    COUNT(CASE WHEN actual_success = execution_succeeded THEN 1 END) as matching_values
  FROM agent_routing_decisions;"
```

### Rollback Migration
```bash
PGPASSWORD='***REDACTED***' psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -f agents/parallel_execution/migrations/011_rollback_execution_succeeded_column.sql
```

## Impact

### Database
- **Performance**: Minimal - two new indexes, but column is boolean (small footprint)
- **Storage**: ~1 byte per row (boolean column)
- **Queries**: No impact until code updated to use new column

### Omnidash
Must update:
1. `shared/intelligence-schema.ts` - Add `executionSucceeded` field
2. `server/alert-helpers.ts` - Update `getSuccessRate()` to use new column

### Logging/Tracking
No immediate impact - existing logging continues to use `actual_success` until updated.

## Testing

### Test Data Integrity
```sql
-- Should return 0 mismatches
SELECT COUNT(*)
FROM agent_routing_decisions
WHERE actual_success IS NOT NULL
  AND execution_succeeded IS NOT NULL
  AND actual_success != execution_succeeded;
```

### Test Index Performance
```sql
-- Should use new index
EXPLAIN ANALYZE
SELECT selected_agent, COUNT(*) as successes
FROM agent_routing_decisions
WHERE execution_succeeded = TRUE
  AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY selected_agent;
```

## Next Steps

After this migration:

1. **Update omnidash code** to use `executionSucceeded` instead of `actualSuccess`
2. **Update logging code** in agent tracking skills to populate `execution_succeeded`
3. **Deprecate `actual_success`** in documentation
4. **Schedule removal migration** (Migration 012) to drop `actual_success` column after validation period

## Related Files

- Forward migration: `011_add_execution_succeeded_column.sql`
- Rollback migration: `011_rollback_execution_succeeded_column.sql`
- Omnidash schema: `/Volumes/PRO-G40/Code/omnidash/shared/intelligence-schema.ts`
- Alert helpers: `/Volumes/PRO-G40/Code/omnidash/server/alert-helpers.ts`

## Author

Migration created 2025-10-28 in response to omnidash error and user feedback that "actual_success" is a terrible column name.
