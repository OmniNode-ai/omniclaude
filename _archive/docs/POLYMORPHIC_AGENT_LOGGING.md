# Polymorphic Agent Logging Pattern

**Complete agent observability with Kafka-based event streaming for full replay capability**

## Overview

The Polymorphic Agent logging system provides complete observability of agent actions through Kafka event streaming. This architecture enables:

- **Full Replay Capability**: Complete audit trail with time-travel debugging
- **Non-Blocking Performance**: <5ms publish latency per event
- **Multiple Consumers**: Same events power DB persistence, analytics dashboards, and ML pattern extraction
- **Horizontal Scalability**: Kafka handles 1M+ events/sec
- **Fault Tolerance**: Events persisted even if consumers temporarily fail

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Polymorphic Agent                           │
│  (Routes, Transforms, Executes with logging at each stage)     │
└────────────┬────────────────────────────────────────────────────┘
             │
             │ Publishes events via Kafka skills (<5ms each)
             │
             ├──→ agent-actions (DEBUG mode)
             ├──→ agent-routing-decisions
             ├──→ agent-transformation-events
             └──→ router-performance-metrics
                  │
                  ▼
         ┌────────────────────┐
         │   Kafka Cluster    │
         │  (Redpanda/Kafka)  │
         │   localhost:29092  │
         └────────┬───────────┘
                  │
                  │ Multiple consumers process events in parallel
                  │
         ┌────────┴───────────────────────────────────────┐
         │                                                 │
         ▼                                                 ▼
┌─────────────────┐                            ┌──────────────────┐
│ Database Writer │                            │ Analytics Engine │
│  (PostgreSQL)   │                            │  (Dashboards)    │
└─────────────────┘                            └──────────────────┘
         │                                                 │
         ▼                                                 ▼
┌─────────────────┐                            ┌──────────────────┐
│ agent_actions   │                            │ Real-time Metrics│
│ routing_decisions│                           │ Pattern Analysis │
│ transformation_events│                       │ Alerting System  │
│ performance_metrics│                         │                  │
└─────────────────┘                            └──────────────────┘
```

## Event Types

### 1. Agent Actions (agent-actions topic)

**When to Log**: During DEBUG mode execution for detailed tracing

**Skill**: `log-agent-action/execute_kafka.py`

**Fields**:
- `correlation_id`: Trace ID for complete workflow tracking
- `agent_name`: Agent performing the action
- `action_type`: tool_call | decision | error | success
- `action_name`: Specific action name
- `action_details`: JSON object with action-specific data
- `debug_mode`: Always true for this topic
- `duration_ms`: Action duration (optional)
- `timestamp`: ISO 8601 timestamp

**Example**:
```bash
python3 ~/.claude/skills/agent-tracking/log-agent-action/execute_kafka.py \
  --agent "polymorphic-agent" \
  --action-type "decision" \
  --action-name "route_to_specialized_agent" \
  --details '{"selected_agent":"agent-performance","confidence":0.92}' \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81" \
  --duration-ms 45
```

### 2. Routing Decisions (agent-routing-decisions topic)

**When to Log**: Immediately after selecting which agent should handle the task

**Skill**: `log-routing-decision/execute_kafka.py`

**Fields**:
- `correlation_id`: Trace ID
- `user_request`: Original user request text
- `selected_agent`: Agent name selected
- `confidence_score`: Confidence 0.0-1.0
- `alternatives`: JSON array of alternative agents considered
- `reasoning`: Why this agent was selected
- `routing_strategy`: Strategy used (e.g., enhanced_fuzzy_matching)
- `context`: JSON object with additional context
- `routing_time_ms`: Time taken for routing decision
- `timestamp`: ISO 8601 timestamp

**Example**:
```bash
python3 ~/.claude/skills/agent-tracking/log-routing-decision/execute_kafka.py \
  --agent "agent-performance" \
  --confidence 0.92 \
  --strategy "enhanced_fuzzy_matching" \
  --latency-ms 45 \
  --user-request "optimize my database queries" \
  --reasoning "High confidence match on 'optimize' and 'performance' triggers" \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81"
```

### 3. Transformation Events (agent-transformation-events topic)

**When to Log**: After routing decision, before executing as target agent

**Skill**: `log-transformation/execute_kafka.py`

**Fields**:
- `correlation_id`: Trace ID
- `source_agent`: Source agent name (e.g., "polymorphic-agent")
- `target_agent`: Target agent name
- `transformation_reason`: Why transformation occurred
- `confidence_score`: Routing confidence (0.0-1.0, optional)
- `transformation_duration_ms`: Time taken to transform
- `success`: Whether transformation succeeded (true/false)
- `timestamp`: ISO 8601 timestamp

**Example**:
```bash
python3 ~/.claude/skills/agent-tracking/log-transformation/execute_kafka.py \
  --from-agent "polymorphic-agent" \
  --to-agent "agent-performance" \
  --success true \
  --duration-ms 85 \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81" \
  --reason "High confidence match on 'optimize' and 'performance' triggers" \
  --confidence 0.92
```

### 4. Performance Metrics (router-performance-metrics topic)

**When to Log**: After completing routing decision (regardless of cache hit/miss)

**Skill**: `log-performance-metrics/execute_kafka.py`

**Fields**:
- `correlation_id`: Trace ID
- `query_text`: User request text
- `routing_duration_ms`: Routing time (0-999ms)
- `cache_hit`: Whether result was from cache
- `trigger_match_strategy`: Strategy used (optional)
- `confidence_components`: JSON breakdown of confidence scoring (optional)
- `candidates_evaluated`: Number of agents considered
- `timestamp`: ISO 8601 timestamp

**Example**:
```bash
python3 ~/.claude/skills/agent-tracking/log-performance-metrics/execute_kafka.py \
  --query "optimize my database queries" \
  --duration-ms 45 \
  --cache-hit false \
  --candidates 5 \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81" \
  --strategy "enhanced_fuzzy_matching"
```

## Complete Agent Execution Logging Pattern

### Standard Routing Workflow

When the polymorphic agent routes a request, follow this sequence:

```bash
# 1. Generate correlation ID (done once per request)
CORRELATION_ID=$(uuidgen)

# 2. Start timing routing decision
START_TIME=$(date +%s%N)

# 3. Analyze request and select agent
# ... (routing logic)

# 4. Calculate routing duration
END_TIME=$(date +%s%N)
ROUTING_TIME_MS=$(( ($END_TIME - $START_TIME) / 1000000 ))

# 5. Log routing decision (→ agent-routing-decisions topic)
python3 ~/.claude/skills/agent-tracking/log-routing-decision/execute_kafka.py \
  --agent "agent-performance" \
  --confidence 0.92 \
  --strategy "enhanced_fuzzy_matching" \
  --latency-ms $ROUTING_TIME_MS \
  --user-request "optimize my database queries" \
  --reasoning "High confidence match on 'optimize' and 'performance' triggers" \
  --correlation-id "$CORRELATION_ID"

# 6. Log transformation event (→ agent-transformation-events topic)
python3 ~/.claude/skills/agent-tracking/log-transformation/execute_kafka.py \
  --from-agent "polymorphic-agent" \
  --to-agent "agent-performance" \
  --success true \
  --duration-ms $ROUTING_TIME_MS \
  --correlation-id "$CORRELATION_ID" \
  --reason "High confidence match on 'optimize' and 'performance' triggers" \
  --confidence 0.92

# 7. Log performance metrics (→ router-performance-metrics topic)
python3 ~/.claude/skills/agent-tracking/log-performance-metrics/execute_kafka.py \
  --query "optimize my database queries" \
  --duration-ms $ROUTING_TIME_MS \
  --cache-hit false \
  --candidates 5 \
  --correlation-id "$CORRELATION_ID" \
  --strategy "enhanced_fuzzy_matching"

# 8. Display identity banner and execute as selected agent
# ... (agent execution)
```

**Total Overhead**: ~15ms for all 3 Kafka events (vs ~200ms+ for direct DB writes)

### DEBUG Mode Detailed Logging

When `DEBUG=true`, also log individual actions:

```bash
# Log tool calls
python3 ~/.claude/skills/agent-tracking/log-agent-action/execute_kafka.py \
  --agent "polymorphic-agent" \
  --action-type "tool_call" \
  --action-name "read_file" \
  --details '{"file_path":"/path/to/file.py","lines_read":150}' \
  --correlation-id "$CORRELATION_ID" \
  --duration-ms 12

# Log decisions
python3 ~/.claude/skills/agent-tracking/log-agent-action/execute_kafka.py \
  --agent "polymorphic-agent" \
  --action-type "decision" \
  --action-name "select_optimal_strategy" \
  --details '{"strategy":"parallel_execution","reason":"independent_tasks"}' \
  --correlation-id "$CORRELATION_ID" \
  --duration-ms 5

# Log errors
python3 ~/.claude/skills/agent-tracking/log-agent-action/execute_kafka.py \
  --agent "polymorphic-agent" \
  --action-type "error" \
  --action-name "file_read_failed" \
  --details '{"error":"FileNotFoundError","file_path":"/missing/file.py"}' \
  --correlation-id "$CORRELATION_ID"

# Log success milestones
python3 ~/.claude/skills/agent-tracking/log-agent-action/execute_kafka.py \
  --agent "polymorphic-agent" \
  --action-type "success" \
  --action-name "task_completed" \
  --details '{"tasks_completed":5,"quality_score":0.95}' \
  --correlation-id "$CORRELATION_ID" \
  --duration-ms 1234
```

## Event Replay and Analysis

### Reconstructing Complete Execution Traces

Using correlation_id, you can reconstruct the complete execution:

```sql
-- Get all events for a specific execution
SELECT
    'routing' as event_type,
    created_at,
    selected_agent,
    confidence_score,
    routing_time_ms
FROM agent_routing_decisions
WHERE context->>'correlation_id' = 'ad12146a-b7d0-4a47-86bf-7ec298ce2c81'

UNION ALL

SELECT
    'transformation' as event_type,
    created_at,
    target_agent,
    confidence_score,
    transformation_duration_ms
FROM agent_transformation_events
WHERE context->>'correlation_id' = 'ad12146a-b7d0-4a47-86bf-7ec298ce2c81'

UNION ALL

SELECT
    'performance' as event_type,
    created_at,
    NULL,
    NULL,
    routing_duration_ms
FROM router_performance_metrics
WHERE context->>'correlation_id' = 'ad12146a-b7d0-4a47-86bf-7ec298ce2c81'

UNION ALL

SELECT
    'action' as event_type,
    created_at,
    agent_name,
    NULL,
    duration_ms
FROM agent_actions
WHERE correlation_id = 'ad12146a-b7d0-4a47-86bf-7ec298ce2c81'

ORDER BY created_at;
```

### Time-Travel Debugging

Replay events from Kafka to analyze historical behavior:

```bash
# Consume events from beginning of topic
kafka-console-consumer \
  --bootstrap-server localhost:29092 \
  --topic agent-routing-decisions \
  --from-beginning \
  --property print.key=true \
  --property print.timestamp=true
```

## Performance Impact

| Operation | Latency | Impact |
|-----------|---------|--------|
| Single Kafka publish | <5ms | Non-blocking |
| 3-event routing sequence | ~15ms | Minimal overhead |
| Direct DB write (sync) | 20-100ms | 5-20x slower |
| Complete DEBUG logging | 20-30ms | Still non-blocking |

**Key Insights**:
- Kafka logging is **5-20x faster** than direct DB writes
- Logging never blocks agent execution
- Failed publishes are logged but don't break workflows
- Multiple consumers process same events in parallel

## Kafka Consumer Architecture

### Database Writer Consumer

**File**: `/Volumes/PRO-G40/Code/omniclaude/consumers/agent_actions_consumer.py`

**Topics Consumed**:
- `agent-actions`
- `agent-routing-decisions`
- `agent-transformation-events`
- `router-performance-metrics`

**Features**:
- Batch processing (100 events or 1 second intervals)
- Dead letter queue for failed messages
- Idempotency handling (duplicate detection)
- Graceful shutdown on SIGTERM
- Health check endpoint (http://localhost:8080/health)

**Starting the Consumer**:
```bash
# Set environment variables
export KAFKA_BROKERS=localhost:29092
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5436
export POSTGRES_DATABASE=omninode_bridge

# Run consumer
python3 /Volumes/PRO-G40/Code/omniclaude/consumers/agent_actions_consumer.py
```

### Consumer Health Monitoring

```bash
# Check consumer health
curl http://localhost:8080/health

# Check consumer metrics
curl http://localhost:8080/metrics
```

**Expected Health Response**:
```json
{
  "status": "healthy",
  "consumer": "running"
}
```

**Expected Metrics Response**:
```json
{
  "uptime_seconds": 3600,
  "messages_consumed": 1500,
  "messages_inserted": 1485,
  "messages_failed": 15,
  "batches_processed": 20,
  "avg_batch_processing_ms": 45.2,
  "messages_per_second": 0.42,
  "last_commit_time": "2025-10-23T10:30:00Z"
}
```

## Configuration

### Environment Variables

**Kafka Configuration**:
- `KAFKA_BROKERS`: Comma-separated Kafka brokers (default: `localhost:9092`)
- `KAFKA_ENABLE_LOGGING`: Enable Kafka event logging (default: `true`)

**Database Configuration** (for consumers):
- `POSTGRES_HOST`: PostgreSQL host (default: `localhost`)
- `POSTGRES_PORT`: PostgreSQL port (default: `5436`)
- `POSTGRES_DATABASE`: Database name (default: `omninode_bridge`)
- `POSTGRES_USER`: Database user (default: `postgres`)
- `POSTGRES_PASSWORD`: Database password

**Debug Configuration**:
- `DEBUG`: Enable DEBUG mode for detailed action logging (default: `false`)

### Database Schema

**agent_routing_decisions**:
```sql
CREATE TABLE agent_routing_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_request TEXT,
    selected_agent TEXT NOT NULL,
    confidence_score NUMERIC(5,4) NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 1),
    alternatives JSONB DEFAULT '[]',
    reasoning TEXT,
    routing_strategy TEXT NOT NULL,
    context JSONB DEFAULT '{}',
    routing_time_ms INTEGER NOT NULL CHECK (routing_time_ms >= 0),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**agent_transformation_events**:
```sql
CREATE TABLE agent_transformation_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_agent TEXT NOT NULL,
    target_agent TEXT NOT NULL,
    transformation_reason TEXT,
    confidence_score NUMERIC(5,4) CHECK (confidence_score >= 0 AND confidence_score <= 1),
    transformation_duration_ms INTEGER NOT NULL CHECK (transformation_duration_ms >= 0),
    success BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**router_performance_metrics**:
```sql
CREATE TABLE router_performance_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text TEXT NOT NULL,
    routing_duration_ms INTEGER NOT NULL CHECK (routing_duration_ms >= 0 AND routing_duration_ms < 1000),
    cache_hit BOOLEAN NOT NULL DEFAULT false,
    trigger_match_strategy TEXT,
    confidence_components JSONB DEFAULT '{}',
    candidates_evaluated INTEGER NOT NULL CHECK (candidates_evaluated >= 0),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**agent_actions**:
```sql
CREATE TABLE agent_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    correlation_id UUID NOT NULL,
    agent_name TEXT NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('tool_call', 'decision', 'error', 'success')),
    action_name TEXT NOT NULL,
    action_details JSONB DEFAULT '{}',
    debug_mode BOOLEAN DEFAULT true,
    duration_ms INTEGER CHECK (duration_ms >= 0),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Best Practices

### 1. Always Use Correlation IDs

Generate once per request and pass through all logging calls:

```bash
CORRELATION_ID=$(uuidgen)
# Use same CORRELATION_ID for all events in this execution
```

### 2. Log in Sequence

Follow the standard order:
1. Routing decision
2. Transformation event
3. Performance metrics
4. (Optional) Detailed actions in DEBUG mode

### 3. Include Context

Always provide reasoning and context for better analysis:

```bash
--reasoning "High confidence match on 'optimize' and 'performance' triggers"
--alternatives '["agent-api","agent-debug"]'
```

### 4. Handle Failures Gracefully

Logging failures should never break workflows:

```bash
# Skills return exit code 1 on failure but don't throw exceptions
if ! log_result=$(python3 ~/.claude/skills/...); then
    echo "Warning: Logging failed (non-critical)" >&2
    # Continue execution
fi
```

### 5. Use Kafka for Production

Always prefer Kafka version (`execute_kafka.py`) over direct DB (`execute.py`):

- **Production**: Use Kafka for async, non-blocking logging
- **Development**: Use direct DB for simpler setup
- **Testing**: Use direct DB for immediate verification

## Monitoring and Alerting

### Key Metrics to Track

1. **Consumer Lag**: How far behind consumers are
2. **Publish Success Rate**: % of successful Kafka publishes
3. **Message Throughput**: Messages/second consumed
4. **Processing Latency**: Time from publish to DB insert
5. **Error Rate**: Failed messages / total messages

### Sample Monitoring Queries

```sql
-- Routing success rate over last hour
SELECT
    COUNT(*) as total_routes,
    AVG(confidence_score) as avg_confidence,
    AVG(routing_time_ms) as avg_routing_time_ms
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '1 hour';

-- Transformation success rate
SELECT
    success,
    COUNT(*) as count,
    AVG(transformation_duration_ms) as avg_duration_ms
FROM agent_transformation_events
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY success;

-- Cache effectiveness
SELECT
    cache_hit,
    COUNT(*) as count,
    AVG(routing_duration_ms) as avg_duration_ms
FROM router_performance_metrics
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY cache_hit;
```

## Troubleshooting

### Kafka Not Available

If Kafka is unavailable, skills will fail with error:

```json
{
  "success": false,
  "error": "Failed to publish to Kafka",
  "fallback": "Consider implementing direct DB fallback"
}
```

**Solution**: Use direct DB versions temporarily:
- `execute.py` instead of `execute_kafka.py`

### Consumer Not Processing Events

**Check consumer health**:
```bash
curl http://localhost:8080/health
```

**Check Kafka topics**:
```bash
kafka-topics --bootstrap-server localhost:29092 --list
```

**Check consumer logs**:
```bash
tail -f /path/to/consumer/logs
```

### Database Connection Issues

**Verify PostgreSQL connection**:
```bash
psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"
```

**Check table exists**:
```bash
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT COUNT(*) FROM agent_routing_decisions"
```

## Summary

The Polymorphic Agent logging system provides:

✅ **Complete Observability**: Every routing decision, transformation, and action logged
✅ **Full Replay Capability**: Kafka event stream enables time-travel debugging
✅ **Non-Blocking Performance**: <5ms overhead per event, <15ms for full routing sequence
✅ **Fault Tolerance**: Events persisted even if consumers fail
✅ **Horizontal Scalability**: Handles 1M+ events/sec
✅ **Multiple Consumers**: Same events power DB, analytics, and ML pattern extraction

**Recommendation**: Always use Kafka-based skills (`execute_kafka.py`) for production deployments to maximize performance and enable full replay capability.
