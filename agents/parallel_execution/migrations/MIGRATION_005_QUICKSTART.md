# Migration 005: Debug State Management - Quickstart

**Status**: Ready for deployment
**Version**: 1.0.0
**Created**: 2025-10-11

---

## Overview

Migration 005 adds debug loop capabilities to the ONEX agent framework:
- **5 new tables** for state tracking, error/success analysis
- **1 extended table** (agent_transformation_events)
- **3 views** for integrated analysis
- **2 functions** for state capture and reporting

---

## Prerequisites

✅ PostgreSQL 16+ running on localhost:5436
✅ Database: `omninode_bridge`
✅ Migrations 001-004 applied
✅ Schema: `public` (or `agent_observability`)

---

## Apply Migration

### Option 1: Using psql

```bash
# Connect to database
psql -h localhost -p 5436 -U postgres -d omninode_bridge

# Apply migration
\i agents/parallel_execution/migrations/005_debug_state_management.sql

# Verify tables created
\dt debug_*

# Verify views created
\dv debug_*

# Verify functions created
\df capture_state_snapshot
\df get_workflow_debug_summary
```

### Option 2: Using Python

```python
import asyncpg

async def apply_migration():
    conn = await asyncpg.connect(
        host='localhost',
        port=5436,
        database='omninode_bridge',
        user='postgres',
        password='omninode-bridge-postgres-dev-2024'
    )

    # Read migration file
    with open('agents/parallel_execution/migrations/005_debug_state_management.sql') as f:
        migration_sql = f.read()

    # Execute migration
    await conn.execute(migration_sql)
    print("Migration 005 applied successfully!")

    await conn.close()

# Run migration
import asyncio
asyncio.run(apply_migration())
```

---

## Verify Migration

### Check Tables

```sql
-- Verify all 5 new tables exist
SELECT tablename
FROM pg_tables
WHERE tablename LIKE 'debug_%'
ORDER BY tablename;

-- Expected output:
-- debug_error_events
-- debug_error_success_correlation
-- debug_state_snapshots
-- debug_success_events
-- debug_workflow_steps
```

### Check Views

```sql
-- Verify all 3 views exist
SELECT viewname
FROM pg_views
WHERE viewname LIKE 'debug_%'
ORDER BY viewname;

-- Expected output:
-- debug_error_recovery_patterns
-- debug_llm_call_summary
-- debug_workflow_context
```

### Check Functions

```sql
-- Verify functions exist
SELECT proname
FROM pg_proc
WHERE proname IN ('capture_state_snapshot', 'get_workflow_debug_summary');

-- Expected output:
-- capture_state_snapshot
-- get_workflow_debug_summary
```

### Check Extended Table

```sql
-- Verify agent_transformation_events has new columns
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'agent_transformation_events'
AND column_name IN ('state_snapshot_id', 'error_event_id', 'success_event_id');

-- Expected output:
-- state_snapshot_id | uuid
-- error_event_id    | uuid
-- success_event_id  | uuid
```

---

## Rollback Migration

If you need to rollback:

```bash
# Using psql
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -f agents/parallel_execution/migrations/005_rollback_debug_state_management.sql

# Verify rollback
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT tablename FROM pg_tables WHERE tablename LIKE 'debug_%';"
# Should return 0 rows
```

---

## Usage Example

### Python Integration

```python
from debug_state_integration_example import DebugStateManager
from database_integration import DatabaseIntegrationLayer, DatabaseConfig

# Initialize
config = DatabaseConfig.from_env()
db = DatabaseIntegrationLayer(config)
await db.initialize()

debug_mgr = DebugStateManager(db)

# Capture error with state
error_id = await debug_mgr.capture_error_state(
    correlation_id=workflow_id,
    agent_name="my-agent",
    error=exception,
    agent_state={"context": "data"},
    error_severity="high"
)

# Get workflow debug summary
summary = await debug_mgr.get_workflow_debug_summary(workflow_id)
print(f"Errors: {summary['error_count']}, Successes: {summary['success_count']}")

# Analyze recovery patterns
patterns = await debug_mgr.get_recovery_patterns()
for p in patterns:
    print(f"{p['error_type']}: {p['recovery_strategy']} "
          f"({p['success_count']} successes)")
```

### SQL Queries

```sql
-- Get debug context for a workflow
SELECT * FROM debug_workflow_context
WHERE correlation_id = 'YOUR-CORRELATION-ID';

-- Get all errors for a workflow
SELECT error_type, error_severity, error_message, occurred_at
FROM debug_error_events
WHERE correlation_id = 'YOUR-CORRELATION-ID'
ORDER BY occurred_at;

-- Get LLM calls for a workflow (from hook_events)
SELECT tool_name, quality_score, success_classification
FROM debug_llm_call_summary
WHERE correlation_id = 'YOUR-CORRELATION-ID'
ORDER BY call_timestamp;

-- Get recovery patterns
SELECT * FROM debug_error_recovery_patterns
WHERE success_count >= 3
ORDER BY success_count DESC;
```

---

## Performance Targets

| Operation | Target | Actual (verify after deployment) |
|-----------|--------|----------------------------------|
| State snapshot capture | <50ms | TBD |
| Error event query | <100ms | TBD |
| Workflow context aggregation | <200ms | TBD |
| Recovery pattern analysis | <500ms | TBD |

### Performance Verification

```sql
-- Test query performance
EXPLAIN ANALYZE
SELECT * FROM debug_workflow_context
WHERE correlation_id = (
  SELECT correlation_id FROM debug_workflow_steps LIMIT 1
);

-- Should show execution time <200ms
```

---

## Integration Checklist

- [ ] Migration 005 applied successfully
- [ ] All 5 tables created
- [ ] All 3 views created
- [ ] Both functions created
- [ ] agent_transformation_events extended
- [ ] Performance targets verified
- [ ] Python integration tested
- [ ] Example queries tested
- [ ] Rollback procedure tested (optional)

---

## Troubleshooting

### Error: relation "debug_state_snapshots" already exists

**Solution**: Run rollback script first, then re-apply migration.

```bash
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -f agents/parallel_execution/migrations/005_rollback_debug_state_management.sql
```

### Error: foreign key constraint violations

**Solution**: Ensure migrations 001-004 are applied first. Check:

```sql
SELECT version, description FROM schema_migrations ORDER BY version;
-- Should show versions 1, 2, 3, 4
```

### Performance issues

**Solution**: Rebuild statistics and vacuum tables:

```sql
VACUUM ANALYZE debug_state_snapshots;
VACUUM ANALYZE debug_error_events;
VACUUM ANALYZE debug_success_events;
VACUUM ANALYZE debug_workflow_steps;
```

---

## Documentation

- **Full Schema Design**: `DEBUG_LOOP_SCHEMA.md`
- **Migration SQL**: `005_debug_state_management.sql`
- **Rollback SQL**: `005_rollback_debug_state_management.sql`
- **Python Example**: `debug_state_integration_example.py`

---

## Next Steps

After successful migration:

1. **Update agent code** to use DebugStateManager
2. **Add state capture** to error handlers
3. **Track workflow steps** in coordinator
4. **Analyze patterns** using views and functions
5. **Monitor performance** against targets

---

## Support

For issues or questions:
- Check `DEBUG_LOOP_SCHEMA.md` for detailed documentation
- Review `debug_state_integration_example.py` for usage patterns
- Verify prerequisites and migration order

---

**Status**: ✅ Ready for deployment
**Estimated Time**: 5-10 minutes
**Risk Level**: Low (rollback available)
**ONEX Compliance**: ✅ Full compliance
