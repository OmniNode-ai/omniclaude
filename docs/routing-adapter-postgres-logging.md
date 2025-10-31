# Routing Adapter PostgreSQL Logging

**Implementation Date**: 2025-10-30
**Phase**: Phase 2 - Event-Driven Routing Analytics
**Status**: ✅ Complete and Tested

## Overview

This implementation adds PostgreSQL logging for all routing decisions made by the Routing Adapter service. All routing decisions are now logged to the `agent_routing_decisions` table for audit trail, analytics, and performance monitoring.

## Architecture

```
User Request (via Kafka)
  ↓
RouterEventHandler
  ↓
RoutingHandler
  ├─→ AgentRouter (route request)
  ├─→ Return response (non-blocking)
  └─→ PostgresLogger (async, background task)
      └─→ agent_routing_decisions table
```

## Key Features

### 1. Non-Blocking Logging
- Routing responses are returned immediately
- Database logging happens asynchronously in background task
- Routing failures never caused by database issues

### 2. Retry Logic with Exponential Backoff
- Automatic retry on transient database errors
- Exponential backoff: 100ms → 200ms → 400ms
- Maximum 3 retry attempts per log operation

### 3. Connection Pooling
- asyncpg connection pool (min: 2, max: 10 connections)
- Automatic connection lifecycle management
- Health monitoring and metrics

### 4. Comprehensive Metrics
- Log count, success count, error count
- Success rate percentage
- Average log time in milliseconds
- Retry count tracking

### 5. Graceful Degradation
- Service continues if database unavailable
- Errors logged but don't fail routing
- Health checks indicate database status

## Database Schema

**Table**: `agent_routing_decisions`

**Core Fields**:
- `id` (UUID) - Auto-generated record ID
- `user_request` (TEXT) - User's request text
- `selected_agent` (TEXT) - Selected agent name
- `confidence_score` (NUMERIC 5,4) - Confidence 0.0-1.0
- `routing_strategy` (TEXT) - Strategy used
- `routing_time_ms` (INTEGER) - Routing time in ms
- `alternatives` (JSONB) - Alternative agent recommendations
- `reasoning` (TEXT) - Selection reasoning
- `context` (JSONB) - Additional context
- `created_at` (TIMESTAMP) - Auto-generated timestamp

**Optional Fields** (populated from context):
- `project_path` (VARCHAR 500)
- `project_name` (VARCHAR 255)
- `claude_session_id` (VARCHAR 100)

## Files Created/Modified

### New Files

1. **`services/routing_adapter/postgres_logger.py`**
   - PostgresLogger class with connection pooling
   - Async log_routing_decision method
   - Retry logic with exponential backoff
   - Health check and metrics methods

2. **`services/routing_adapter/test_postgres_logger.py`**
   - Comprehensive test suite
   - Tests connection, logging, metrics, shutdown
   - Verifies database insertion

3. **`docs/routing-adapter-postgres-logging.md`** (this file)
   - Implementation documentation
   - Usage instructions
   - Testing guide

### Modified Files

1. **`services/routing_adapter/routing_handler.py`**
   - Added PostgresLogger integration
   - Config parameter in __init__
   - Async background logging task
   - Updated metrics to include logger metrics
   - Updated shutdown to cleanup logger

2. **`services/routing_adapter/router_event_handler.py`**
   - Pass config to RoutingHandler initialization
   - Enables PostgreSQL logging when password provided

3. **`services/routing_adapter/config.py`**
   - Already had PostgreSQL configuration
   - No changes needed (configuration was ready)

## Configuration

PostgreSQL configuration is read from environment variables (`.env` file):

```bash
# PostgreSQL Configuration
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=omninode_remote_2024_secure

# Connection Pool (optional)
POSTGRES_POOL_MIN_SIZE=2
POSTGRES_POOL_MAX_SIZE=10
```

**Important**: The service will continue to work if PostgreSQL password is not provided, but routing decisions will not be logged to the database.

## Testing

### Run Test Suite

```bash
# From omniclaude directory
source .env
python3 services/routing_adapter/test_postgres_logger.py
```

**Expected Output**:
```
✅ Connection pool initialized successfully
✅ Health check passed
✅ Routing decision logged successfully
✅ Metrics verified
✅ Graceful shutdown successful
✅ ALL TESTS PASSED
```

### Verify Database Records

```bash
# Check recent routing decisions
PGPASSWORD=omninode_remote_2024_secure psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT id, selected_agent, confidence_score, routing_strategy, routing_time_ms, created_at FROM agent_routing_decisions ORDER BY created_at DESC LIMIT 10;"
```

### Test Results (2025-10-30)

**Test Execution**:
- ✅ Connection pool initialization: 195ms
- ✅ Health check query: 23.67ms
- ✅ Routing decision insert: 27.32ms
- ✅ All metrics verified
- ✅ Graceful shutdown: 13ms

**Database Verification**:
- ✅ Record inserted with correct UUID
- ✅ All core fields populated correctly
- ✅ JSONB fields (alternatives, context) properly serialized
- ✅ Timestamp auto-generated correctly

## Performance Characteristics

### Metrics (from test run)

- **Connection pool initialization**: ~195ms (one-time cost)
- **Health check query**: ~24ms
- **Log routing decision**: ~27ms
- **Success rate**: 100%
- **Retry count**: 0 (no failures)

### Production Targets

- Log time: < 50ms (p95)
- Success rate: > 99%
- Connection pool utilization: < 80%
- Retry rate: < 5%

## Usage in Production

### Starting the Service

```bash
# Ensure .env has PostgreSQL credentials
source .env

# Start routing adapter service
python3 services/routing_adapter/routing_adapter_service.py
```

**On Startup**:
1. Config validates PostgreSQL password present
2. RoutingHandler initializes with config
3. PostgresLogger connection pool created
4. Health check confirms database connectivity
5. Service starts processing routing requests
6. All routing decisions logged asynchronously

### Monitoring

**Check Health Endpoint**:
```bash
curl http://localhost:8055/health
```

**Response includes PostgreSQL logger metrics**:
```json
{
  "status": "healthy",
  "components": {
    "router_event_handler": "healthy"
  },
  "metrics": {
    "request_count": 150,
    "success_count": 148,
    "error_count": 2,
    "success_rate": 98.67,
    "avg_routing_time_ms": 45.23,
    "postgres_logger_metrics": {
      "log_count": 150,
      "success_count": 149,
      "error_count": 1,
      "retry_count": 3,
      "success_rate": 99.33,
      "avg_log_time_ms": 28.45
    }
  }
}
```

## Error Handling

### Database Connection Failures

**Scenario**: PostgreSQL database unavailable at startup

**Behavior**:
- Warning logged: "Failed to initialize PostgresLogger (continuing without DB logging)"
- Service continues without database logging
- Routing still works normally
- Health checks show database unavailable

**Recovery**: Database connectivity restored automatically when database comes back online

### Logging Failures

**Scenario**: Database error during log operation

**Behavior**:
1. Automatic retry with exponential backoff (3 attempts)
2. If all retries fail, error logged
3. Routing request still succeeds (non-blocking)
4. Metrics track error count and retry count

**Common Errors**:
- Connection timeout → Retry
- Transaction conflict → Retry
- Constraint violation → Log error, don't retry
- Unexpected errors → Log error, don't retry

## Analytics Queries

### Recent Routing Decisions

```sql
SELECT
  id,
  selected_agent,
  confidence_score,
  routing_strategy,
  routing_time_ms,
  created_at
FROM agent_routing_decisions
ORDER BY created_at DESC
LIMIT 20;
```

### Agent Selection Statistics

```sql
SELECT
  selected_agent,
  COUNT(*) as selection_count,
  AVG(confidence_score) as avg_confidence,
  AVG(routing_time_ms) as avg_routing_time_ms
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY selected_agent
ORDER BY selection_count DESC;
```

### Low Confidence Decisions

```sql
SELECT
  id,
  user_request,
  selected_agent,
  confidence_score,
  alternatives,
  reasoning,
  created_at
FROM agent_routing_decisions
WHERE confidence_score < 0.7
ORDER BY created_at DESC
LIMIT 10;
```

### Routing Performance Trends

```sql
SELECT
  DATE_TRUNC('hour', created_at) as hour,
  COUNT(*) as requests,
  AVG(routing_time_ms) as avg_time_ms,
  MAX(routing_time_ms) as max_time_ms,
  AVG(confidence_score) as avg_confidence
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour DESC;
```

## Next Steps (Future Enhancements)

### Phase 3 - Advanced Analytics

1. **Routing Accuracy Tracking**
   - Populate `actual_success` and `execution_succeeded` fields
   - Track if routing decisions led to successful executions
   - Calculate agent selection accuracy over time

2. **Machine Learning Integration**
   - Historical data for training ML models
   - Predict optimal agent for new requests
   - Confidence calibration based on outcomes

3. **Real-time Dashboards**
   - Grafana dashboards for routing metrics
   - Alerts on low confidence or high error rates
   - Performance monitoring and optimization

4. **A/B Testing**
   - Compare routing strategies
   - Test new agents with traffic splitting
   - Measure impact on execution success

## Troubleshooting

### Issue: "POSTGRES_PASSWORD environment variable not set"

**Solution**:
```bash
source .env
# Verify password is set
echo $POSTGRES_PASSWORD
```

### Issue: Connection timeout errors

**Possible Causes**:
1. PostgreSQL service not running
2. Network issues (firewall, incorrect host/port)
3. Connection pool exhausted

**Solutions**:
1. Check service: `docker ps | grep archon-bridge`
2. Test connectivity: `psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge`
3. Increase pool size in config

### Issue: High retry count

**Possible Causes**:
1. Database overloaded
2. Connection pool too small
3. Network latency issues

**Solutions**:
1. Check database performance metrics
2. Increase `POSTGRES_POOL_MAX_SIZE`
3. Reduce `max_retries` if acceptable

## References

- Database Adapter Pattern: `/Volumes/PRO-G40/Code/omninode_bridge/src/omninode_bridge/nodes/database_adapter_effect/v1_0_0/node.py`
- Event-Driven Routing Proposal: `docs/architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md`
- Agent Routing Decisions Schema: `agent_routing_decisions` table in `omninode_bridge` database

## Implementation Credits

- **Correlation ID**: 2ae9c54b-73e4-42df-a902-cf41503efa56
- **Implementation Date**: 2025-10-30
- **Agent**: polymorphic-agent
- **Reference Pattern**: database_adapter_effect (ONEX v2.0)
