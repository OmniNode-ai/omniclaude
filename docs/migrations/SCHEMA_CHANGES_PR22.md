# Schema Changes - PR #22

## Overview

This PR introduced schema changes to improve observability and traceability across the OmniClaude agent framework. This document helps migrate existing scripts, queries, and application code to use the updated schema.

**PR**: #22 - Observability Infrastructure Enhancements
**Date**: 2025-11-07
**Impact**: Breaking changes to column names in 3 observability tables
**Correlation ID**: def1bf03-d307-405f-98dd-869cde43179a

---

## Breaking Changes

### 1. agent_transformation_events

#### Field Rename: `confidence_score` → `routing_confidence`

**Impact**: Scripts and queries using `confidence_score` will fail with "column does not exist" error.

**Reason**: Renamed for clarity - this score specifically tracks routing decision confidence, not general agent confidence.

**Migration**:

```sql
-- ❌ OLD (will fail)
SELECT
    target_agent,
    confidence_score,
    transformation_reason
FROM agent_transformation_events
WHERE confidence_score > 0.8;

-- ✅ NEW (correct)
SELECT
    target_agent,
    routing_confidence,
    transformation_reason
FROM agent_transformation_events
WHERE routing_confidence > 0.8;
```

**Code Migration**:

```python
# ❌ OLD
result = cursor.execute(
    "SELECT confidence_score FROM agent_transformation_events WHERE id = %s",
    (event_id,)
)

# ✅ NEW
result = cursor.execute(
    "SELECT routing_confidence FROM agent_transformation_events WHERE id = %s",
    (event_id,)
)
```

**Migration Script** (if needed to update existing code):

```bash
# Find all files using old field name
grep -r "confidence_score" --include="*.py" --include="*.sql" .

# Replace in Python files (review before applying!)
find . -name "*.py" -exec sed -i.bak 's/confidence_score/routing_confidence/g' {} \;

# Replace in SQL files (review before applying!)
find . -name "*.sql" -exec sed -i.bak 's/confidence_score/routing_confidence/g' {} \;
```

---

### 2. agent_execution_logs

#### Field Rename: `start_time` → `started_at`

**Impact**: Time-based queries will fail if using old field name.

**Reason**: Standardized timestamp naming convention across all tables (using `*_at` suffix).

**Migration**:

```sql
-- ❌ OLD (will fail)
SELECT
    agent_name,
    start_time,
    status
FROM agent_execution_logs
WHERE start_time > NOW() - INTERVAL '1 day'
ORDER BY start_time DESC;

-- ✅ NEW (correct)
SELECT
    agent_name,
    started_at,
    status
FROM agent_execution_logs
WHERE started_at > NOW() - INTERVAL '1 day'
ORDER BY started_at DESC;
```

**View Migration**:

```sql
-- ❌ OLD view definition
CREATE VIEW agent_recent_executions AS
SELECT
    correlation_id,
    agent_name,
    start_time,
    duration_ms
FROM agent_execution_logs
WHERE start_time > NOW() - INTERVAL '7 days';

-- ✅ NEW view definition
CREATE VIEW agent_recent_executions AS
SELECT
    correlation_id,
    agent_name,
    started_at,
    duration_ms
FROM agent_execution_logs
WHERE started_at > NOW() - INTERVAL '7 days';
```

**Code Migration**:

```python
# ❌ OLD
logs = db.query(
    "SELECT * FROM agent_execution_logs WHERE start_time > %s",
    (cutoff_time,)
)
start = logs[0]['start_time']

# ✅ NEW
logs = db.query(
    "SELECT * FROM agent_execution_logs WHERE started_at > %s",
    (cutoff_time,)
)
start = logs[0]['started_at']
```

---

### 3. router_performance_metrics

#### Schema Updates

**Changed Fields**:
- Timestamp field standardization: All timing fields now use consistent naming
- Performance timing fields now use microsecond precision (`_us` suffix)
- Confidence breakdown fields added for detailed analysis

**New Schema Structure**:

```sql
-- Key timestamp field
measured_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()

-- Performance timings (microsecond precision)
cache_lookup_us INTEGER          -- Cache lookup time
trigger_matching_us INTEGER      -- Trigger matching time
confidence_scoring_us INTEGER    -- Confidence calculation time
total_routing_time_us INTEGER    -- Total routing time

-- Confidence score breakdown (4 components)
trigger_confidence DECIMAL(5,4)      -- 40% weight
context_confidence DECIMAL(5,4)      -- 30% weight
capability_confidence DECIMAL(5,4)   -- 20% weight
historical_confidence DECIMAL(5,4)   -- 10% weight
```

**Impact**: Queries using old timestamp field names or expecting millisecond precision will break.

**Migration**:

```sql
-- ❌ OLD (if you had custom queries with assumed field names)
SELECT
    metric_type,
    recorded_at,
    routing_time_ms
FROM router_performance_metrics
WHERE recorded_at > NOW() - INTERVAL '1 hour';

-- ✅ NEW (correct field names and precision)
SELECT
    metric_type,
    measured_at,
    total_routing_time_us / 1000.0 as routing_time_ms  -- Convert µs to ms
FROM router_performance_metrics
WHERE measured_at > NOW() - INTERVAL '1 hour';
```

**Confidence Breakdown Migration**:

```sql
-- ✅ NEW: Access detailed confidence components
SELECT
    selected_agent,
    confidence_score,
    trigger_confidence,     -- 40% weight
    context_confidence,     -- 30% weight
    capability_confidence,  -- 20% weight
    historical_confidence   -- 10% weight
FROM router_performance_metrics
WHERE confidence_score > 0.8
ORDER BY measured_at DESC
LIMIT 10;
```

**Performance Analysis Migration**:

```python
# ❌ OLD (if you had millisecond assumptions)
def analyze_routing_performance(metrics):
    for metric in metrics:
        if metric['routing_time_ms'] > 100:  # Slow routing
            print(f"Slow routing: {metric['routing_time_ms']}ms")

# ✅ NEW (microsecond precision)
def analyze_routing_performance(metrics):
    for metric in metrics:
        routing_time_ms = metric['total_routing_time_us'] / 1000.0
        if routing_time_ms > 100:  # Slow routing
            print(f"Slow routing: {routing_time_ms:.2f}ms")
```

---

## Backward Compatibility

### Correlation IDs

✅ **Old correlation IDs remain valid** - No changes to correlation tracking.

```sql
-- ✅ Old correlation IDs work with new schema
SELECT * FROM agent_transformation_events
WHERE correlation_id = '8b57ec39-45b5-467b-939c-dd1439219f69';

SELECT * FROM agent_execution_logs
WHERE correlation_id = '8b57ec39-45b5-467b-939c-dd1439219f69';

SELECT * FROM router_performance_metrics
WHERE correlation_id = '8b57ec39-45b5-467b-939c-dd1439219f69';
```

### Existing Data

✅ **No data migration needed** - Column renames were handled by migrations.

- Existing data remains intact
- Only query updates needed (no data transformation)
- Indexes rebuilt automatically during migration

### Foreign Key Relationships

✅ **All foreign key relationships preserved** - No changes to table relationships.

```sql
-- ✅ Joins still work the same way
SELECT
    ate.target_agent,
    ate.routing_confidence,  -- NEW field name
    ael.started_at,          -- NEW field name
    rpm.measured_at          -- NEW field name
FROM agent_transformation_events ate
JOIN agent_execution_logs ael ON ael.correlation_id = ate.correlation_id
JOIN router_performance_metrics rpm ON rpm.correlation_id = ate.correlation_id
WHERE ate.started_at > NOW() - INTERVAL '1 day';
```

---

## Migration Checklist

Use this checklist to ensure your code is updated:

### Scripts

- [ ] Update trace scripts in `scripts/observability/`
  - [ ] `trace_execution.py` - Update field names
  - [ ] `analyze_routing.py` - Update confidence field
  - [ ] `performance_report.py` - Update timestamp fields
  - [ ] Any custom scripts using these tables

### Dashboard Queries

- [ ] Update Grafana dashboards
  - [ ] Routing performance panel - Use `routing_confidence`
  - [ ] Execution timeline - Use `started_at`
  - [ ] Metrics overview - Use `measured_at`
- [ ] Update custom SQL queries in dashboards
- [ ] Test all dashboard panels after migration

### Monitoring Alerts

- [ ] Update Prometheus/AlertManager rules
  - [ ] Routing confidence alerts - Use new field name
  - [ ] Execution time alerts - Use `started_at`
  - [ ] Performance threshold alerts - Use microsecond precision
- [ ] Test all alerts trigger correctly

### Application Code

- [ ] Update Python code using these tables
  - [ ] ORM models (if any) - Update field names
  - [ ] Raw SQL queries - Update field names
  - [ ] Data access layers - Update field names
- [ ] Update API responses (if fields exposed)
- [ ] Update data serialization code

### Documentation

- [ ] Update API documentation
- [ ] Update schema documentation
- [ ] Update example queries in docs
- [ ] Update troubleshooting guides

### Testing

- [ ] Test with old correlation IDs - Should still work ✅
- [ ] Test all updated queries - Should return data ✅
- [ ] Test dashboard visualizations - Should render correctly ✅
- [ ] Test monitoring alerts - Should trigger as expected ✅
- [ ] Run integration tests - Should pass ✅

---

## Verification Commands

### Verify Schema Changes

```sql
-- Verify agent_transformation_events has routing_confidence
\d agent_transformation_events
-- Should show: routing_confidence | numeric(5,4)

-- Verify agent_execution_logs has started_at
\d agent_execution_logs
-- Should show: started_at | timestamp with time zone

-- Verify router_performance_metrics has measured_at
\d router_performance_metrics
-- Should show: measured_at | timestamp with time zone
```

### Verify Data Integrity

```bash
# Source .env for credentials
source .env

# Test query with new field names
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} << EOF
-- Test all three tables
SELECT
    COUNT(*) as transformation_events,
    MAX(routing_confidence) as max_confidence
FROM agent_transformation_events;

SELECT
    COUNT(*) as execution_logs,
    MAX(started_at) as latest_execution
FROM agent_execution_logs;

SELECT
    COUNT(*) as router_metrics,
    MAX(measured_at) as latest_metric
FROM router_performance_metrics;
EOF
```

### Test with Old Correlation IDs

```bash
# Test that old correlation IDs still work
source .env

# Replace with an actual old correlation ID from your database
OLD_CORR_ID="8b57ec39-45b5-467b-939c-dd1439219f69"

psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} << EOF
-- Should return data if correlation_id exists
SELECT
    'transformation_events' as table_name,
    COUNT(*) as records
FROM agent_transformation_events
WHERE correlation_id = '${OLD_CORR_ID}'
UNION ALL
SELECT
    'execution_logs',
    COUNT(*)
FROM agent_execution_logs
WHERE correlation_id = '${OLD_CORR_ID}'
UNION ALL
SELECT
    'router_metrics',
    COUNT(*)
FROM router_performance_metrics
WHERE correlation_id = '${OLD_CORR_ID}';
EOF
```

---

## Common Migration Errors

### Error 1: Column Does Not Exist

```
ERROR: column "confidence_score" does not exist
LINE 1: SELECT confidence_score FROM agent_transformation_events
               ^
```

**Solution**: Update to use `routing_confidence`

```sql
-- Fix
SELECT routing_confidence FROM agent_transformation_events
```

### Error 2: Column Does Not Exist (start_time)

```
ERROR: column "start_time" does not exist
LINE 1: SELECT start_time FROM agent_execution_logs
               ^
```

**Solution**: Update to use `started_at`

```sql
-- Fix
SELECT started_at FROM agent_execution_logs
```

### Error 3: Unexpected Data Type

```
ERROR: operator does not exist: integer > double precision
HINT: No operator matches the given name and argument types. You might need to add explicit type casts.
```

**Solution**: Account for microsecond precision in router_performance_metrics

```sql
-- ❌ Wrong - comparing microseconds to milliseconds
WHERE total_routing_time_us > 100

-- ✅ Correct - convert or compare appropriately
WHERE total_routing_time_us > 100000  -- 100ms in microseconds
-- OR
WHERE (total_routing_time_us / 1000.0) > 100  -- Convert to ms
```

---

## Rollback Procedure

If you need to rollback these changes (not recommended for production):

```sql
-- WARNING: This will break PR #22 functionality
-- Only use for development/testing rollback

BEGIN;

-- 1. Rename agent_transformation_events field back
ALTER TABLE agent_transformation_events
    RENAME COLUMN routing_confidence TO confidence_score;

-- 2. Rename agent_execution_logs field back
ALTER TABLE agent_execution_logs
    RENAME COLUMN started_at TO start_time;

-- 3. router_performance_metrics - More complex, requires migration rollback
-- See: agents/parallel_execution/migrations/003_create_router_performance_metrics.sql

COMMIT;
```

**Note**: Rollback is NOT recommended. Instead, update your code to use the new field names.

---

## Support

### Getting Help

If you encounter issues during migration:

1. **Check this document** - Most common issues are documented above
2. **Verify schema** - Use `\d table_name` in psql to check current schema
3. **Test queries** - Use the verification commands above
4. **Check logs** - Review application logs for SQL errors
5. **Ask for help** - Create an issue with:
   - Error message (full stack trace)
   - Query that's failing
   - Table schema output (`\d table_name`)

### Migration Timeline

- **Phase 1** (Week of 2025-11-07): Schema changes deployed
- **Phase 2** (Week of 2025-11-11): Legacy field warnings in logs
- **Phase 3** (Week of 2025-11-18): Full migration expected complete

### Related Documentation

- **Observability Architecture**: `docs/observability/AGENT_TRACEABILITY.md`
- **Agent Execution Logging**: `docs/AGENT_EXECUTION_LOGGER_INTEGRATION.md`
- **Database Schema**: `agents/parallel_execution/migrations/`
- **Main CLAUDE.md**: See "Agent Observability & Traceability" section

---

## Summary

### What Changed

| Table | Old Field | New Field | Type | Reason |
|-------|-----------|-----------|------|--------|
| agent_transformation_events | `confidence_score` | `routing_confidence` | DECIMAL(5,4) | Clarity - routing-specific confidence |
| agent_execution_logs | `start_time` | `started_at` | TIMESTAMPTZ | Naming convention standardization |
| router_performance_metrics | Various | `measured_at`, `*_us` fields | TIMESTAMPTZ, INTEGER | Standardization + µs precision |

### What Stayed The Same

✅ Correlation ID tracking - Fully backward compatible
✅ Table relationships - All foreign keys preserved
✅ Existing data - No data migration required
✅ Indexes - Automatically rebuilt during migration

### Migration Effort

- **Low effort**: SQL queries (find/replace field names)
- **Medium effort**: Application code (update ORM models, DAL)
- **Low effort**: Dashboards (update queries in panels)
- **Low effort**: Alerts (update field references)

**Estimated time**: 2-4 hours for typical codebase

---

**Last Updated**: 2025-11-07
**Document Version**: 1.0
**Maintained By**: OmniClaude Observability Team
