> ⚠️ **DEPRECATED**: This document describes the old agent execution framework (`agents/lib/`). The current architecture uses the emit daemon via Unix socket (`emit_client_wrapper.py`). Kept because it is referenced by `plugins/onex/agents/configs/polymorphic-agent.yaml`.

---

# Agent Action Logging Implementation

## Overview

Comprehensive agent action logging system that captures all agent tool calls, decisions, errors, and successes for complete observability and debugging.

**Status**: ✅ **IMPLEMENTED** (2025-11-06)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent Execution                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Agent Code                                          │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ Tool     │  │ Decision │  │ Error    │          │   │
│  │  │ Call     │  │          │  │          │          │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘          │   │
│  │       │             │             │                 │   │
│  │       └─────────────┴─────────────┘                 │   │
│  │                     │                                │   │
│  │              ┌──────▼──────┐                         │   │
│  │              │ ActionLogger │                        │   │
│  │              └──────┬───────┘                        │   │
│  └─────────────────────┼─────────────────────────────────┘   │
│                        │                                     │
│                        ▼                                     │
│              ┌──────────────────┐                            │
│              │ Action Event     │                            │
│              │ Publisher        │                            │
│              └──────┬───────────┘                            │
└─────────────────────┼─────────────────────────────────────────┘
                      │
                      ▼
            ┌──────────────────┐
            │ Kafka Topic      │
            │ agent-actions    │
            └──────┬───────────┘
                   │
                   ▼
         ┌──────────────────────┐
         │ Agent Actions        │
         │ Consumer             │
         │ (consumers/          │
         │  agent_actions_      │
         │  consumer.py)        │
         └──────┬───────────────┘
                │
                ▼
      ┌──────────────────────────┐
      │ PostgreSQL               │
      │ agent_actions table      │
      │ - correlation_id         │
      │ - action_type            │
      │ - action_name            │
      │ - action_details (JSONB) │
      │ - duration_ms            │
      │ - project_path           │
      │ - created_at             │
      └──────────────────────────┘
```

## Components Implemented

### 1. Action Event Publisher (`agents/lib/action_event_publisher.py`)

**Purpose**: Publishes agent action events to Kafka with graceful degradation

**Features**:
- ✅ Non-blocking async publishing
- ✅ Automatic producer connection management
- ✅ JSON serialization with datetime handling
- ✅ Correlation ID tracking
- ✅ Graceful degradation (logs error but doesn't fail execution)
- ✅ Support for tool calls, decisions, errors, and success events

**API**:
```python
from action_event_publisher import (
    publish_action_event,
    publish_tool_call,
    publish_decision,
    publish_error,
    publish_success
)

# Publish tool call
await publish_tool_call(
    agent_name="agent-researcher",
    tool_name="Read",
    tool_parameters={"file_path": "/path/to/file.py"},
    tool_result={"line_count": 100},
    correlation_id=correlation_id,
    duration_ms=45
)

# Publish decision
await publish_decision(
    agent_name="agent-router",
    decision_name="select_agent",
    decision_context={"candidates": ["agent-a", "agent-b"]},
    decision_result={"selected": "agent-a", "confidence": 0.92}
)

# Publish error
await publish_error(
    agent_name="agent-researcher",
    error_type="ImportError",
    error_message="Module 'foo' not found",
    error_context={"file": "/path/to/file.py", "line": 15}
)
```

### 2. Action Logger (`agents/lib/action_logger.py`)

**Purpose**: Convenient wrapper for action logging with automatic timing and correlation ID management

**Features**:
- ✅ Context manager for automatic timing
- ✅ Automatic correlation ID management
- ✅ Project context tracking
- ✅ Error handling and logging
- ✅ Graceful degradation

**API**:
```python
from action_logger import ActionLogger

# Initialize logger
logger = ActionLogger(
    agent_name="agent-researcher",
    correlation_id="abc-123",
    project_name="omniclaude"
)

# Log tool call with context manager (automatic timing)
async with logger.tool_call("Read", {"file_path": "/path/to/file.py"}) as action:
    result = await read_file("/path/to/file.py")
    action.set_result({"line_count": len(result)})

# Log tool call manually
await logger.log_tool_call(
    tool_name="Write",
    tool_parameters={"file_path": "/path/to/output.py"},
    tool_result={"success": True},
    duration_ms=30
)

# Log decision
await logger.log_decision(
    decision_name="select_agent",
    decision_context={"candidates": ["agent-a", "agent-b"]},
    decision_result={"selected": "agent-a"}
)

# Log error
await logger.log_error(
    error_type="ImportError",
    error_message="Module 'foo' not found"
)

# Log success
await logger.log_success(
    success_name="task_completed",
    success_details={"files_processed": 5}
)
```

### 3. Consumer Integration

**Consumer**: `consumers/agent_actions_consumer.py` (already exists)

**Features**:
- ✅ Multi-topic subscription (agent-actions, onex.evt.omniclaude.routing-decision.v1, etc.)
- ✅ Batch processing (100 events or 1 second intervals)
- ✅ Dead letter queue for failed messages
- ✅ Graceful shutdown
- ✅ Idempotency handling
- ✅ Automatic file operation traceability logging

**Consumer subscribes to**:
- `agent-actions` - Action events from publishers
- `onex.evt.omniclaude.routing-decision.v1` - Routing decisions
- `agent-transformation-events` - Agent transformations
- `router-performance-metrics` - Performance metrics
- `agent-detection-failures` - Detection failures
- `agent-execution-logs` - Execution lifecycle

### 4. Database Schema

**Table**: `agent_actions`

```sql
CREATE TABLE agent_actions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    correlation_id UUID NOT NULL,
    agent_name TEXT NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('tool_call', 'decision', 'error', 'success')),
    action_name TEXT NOT NULL,
    action_details JSONB DEFAULT '{}'::jsonb,
    debug_mode BOOLEAN NOT NULL DEFAULT true,
    duration_ms INTEGER,
    project_path TEXT,
    project_name TEXT,
    working_directory TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agent_actions_correlation_id ON agent_actions(correlation_id);
CREATE INDEX idx_agent_actions_agent_name ON agent_actions(agent_name);
CREATE INDEX idx_agent_actions_action_type ON agent_actions(action_type);
CREATE INDEX idx_agent_actions_created_at ON agent_actions(created_at DESC);
```

## Usage Patterns

### Pattern 1: Context Manager (Recommended)

```python
from action_logger import ActionLogger

logger = ActionLogger(
    agent_name="agent-researcher",
    correlation_id=correlation_id
)

# Automatic timing and error handling
async with logger.tool_call("Read", {"file_path": "..."}) as action:
    result = await execute_tool()
    action.set_result(result)
```

**Benefits**:
- ✅ Automatic timing (duration_ms calculated automatically)
- ✅ Automatic error capture (exceptions logged as failures)
- ✅ Clean, readable code

### Pattern 2: Manual Logging

```python
from action_logger import ActionLogger

logger = ActionLogger(agent_name="agent-researcher")

# Manual timing
start_time = time.time()
result = await execute_tool()
duration_ms = int((time.time() - start_time) * 1000)

await logger.log_tool_call(
    tool_name="Write",
    tool_parameters={"file_path": "..."},
    tool_result=result,
    duration_ms=duration_ms
)
```

**Use when**: You need more control over timing or error handling

### Pattern 3: One-Off Action

```python
from action_logger import log_action

# Quick one-off action without creating logger instance
await log_action(
    agent_name="agent-quick-task",
    action_type="tool_call",
    action_name="Grep",
    action_details={"pattern": "TODO", "matches": 42},
    correlation_id=correlation_id
)
```

**Use when**: You need to log a single action quickly

## Testing

### 1. Integration Example

```bash
python agents/lib/action_logging_example.py
```

**What it does**:
- Demonstrates all action logging patterns
- Shows tool calls, decisions, errors, and successes
- Tests context manager and manual logging
- Tests sequential and batch operations

### 2. Publishing Test

```bash
KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092 \
python tests/test_action_publishing.py
```

**What it does**:
- Tests Kafka publishing without database dependency
- Verifies all action types can be published
- Tests graceful degradation

### 3. End-to-End Test

```bash
source .env
python tests/test_action_logging_e2e.py
```

**What it does**:
- Publishes test actions to Kafka
- Waits for consumer to process
- Queries database to verify persistence
- Validates correlation IDs and action details

**Requirements**:
- Kafka running and accessible
- PostgreSQL running and accessible
- Consumer running (`agent_actions_consumer.py`)
- `POSTGRES_PASSWORD` set in environment

## Querying Action Data

### Basic Queries

```sql
-- Recent actions
SELECT * FROM agent_actions
ORDER BY created_at DESC
LIMIT 20;

-- Actions by correlation ID (trace agent execution)
SELECT
    action_type, action_name, duration_ms,
    action_details, created_at
FROM agent_actions
WHERE correlation_id = 'abc-123'
ORDER BY created_at ASC;

-- Tool call statistics
SELECT
    action_name,
    COUNT(*) as call_count,
    AVG(duration_ms) as avg_duration_ms,
    MAX(duration_ms) as max_duration_ms
FROM agent_actions
WHERE action_type = 'tool_call'
GROUP BY action_name
ORDER BY call_count DESC;

-- Error analysis
SELECT
    agent_name,
    action_name,
    action_details->>'error_message' as error_message,
    COUNT(*) as error_count
FROM agent_actions
WHERE action_type = 'error'
GROUP BY agent_name, action_name, error_message
ORDER BY error_count DESC;

-- Agent activity summary
SELECT
    agent_name,
    COUNT(*) as total_actions,
    COUNT(*) FILTER (WHERE action_type = 'tool_call') as tool_calls,
    COUNT(*) FILTER (WHERE action_type = 'decision') as decisions,
    COUNT(*) FILTER (WHERE action_type = 'error') as errors,
    AVG(duration_ms) as avg_duration_ms
FROM agent_actions
GROUP BY agent_name
ORDER BY total_actions DESC;
```

### Using View (if implemented)

```sql
-- Recent debug traces with action timeline
SELECT * FROM recent_debug_traces
ORDER BY trace_started DESC
LIMIT 10;
```

## Integration Checklist

To add action logging to an agent:

- [ ] Import ActionLogger from `agents/lib/action_logger`
- [ ] Initialize logger with agent name and correlation ID
- [ ] Wrap tool calls with `async with logger.tool_call()` context manager
- [ ] Log decisions with `await logger.log_decision()`
- [ ] Log errors with `await logger.log_error()`
- [ ] Log successes with `await logger.log_success()`
- [ ] Pass correlation ID through agent lifecycle
- [ ] Test that actions appear in `agent_actions` table

## Configuration

### Environment Variables

```bash
# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092  # Kafka broker address

# PostgreSQL configuration (for consumer)
POSTGRES_HOST=<postgres-host>
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<your_password>

# Consumer configuration
KAFKA_GROUP_ID=agent-observability-postgres
BATCH_SIZE=100
BATCH_TIMEOUT_MS=1000
```

### Kafka Topics

**Topic**: `agent-actions`

**Partitions**: Use correlation_id as partition key for ordering

**Retention**: Configured in Kafka (typically 7 days)

**Consumer Group**: `agent-observability-postgres`

## Error Handling

### Graceful Degradation

The action logging system **never fails agent execution**:

1. **Kafka unavailable**: Logs warning, returns False, execution continues
2. **Network error**: Logs error, returns False, execution continues
3. **Serialization error**: Logs error, returns False, execution continues
4. **Producer error**: Logs error, returns False, execution continues

**Example**:
```python
# This will never raise an exception
success = await logger.log_tool_call(...)
if not success:
    # Kafka unavailable, but agent continues normally
    logger.warning("Action logging unavailable")
```

### Consumer Resilience

**Features**:
- Retry with exponential backoff (3 retries max)
- Dead letter queue for poison messages
- Automatic connection recovery
- Graceful shutdown on SIGTERM/SIGINT

## Monitoring

### Consumer Health Check

```bash
curl http://localhost:8080/health
# {"status": "healthy", "consumer": "running"}

curl http://localhost:8080/metrics
# {
#   "uptime_seconds": 3600,
#   "messages_consumed": 1234,
#   "messages_inserted": 1230,
#   "messages_failed": 4,
#   ...
# }
```

### Kafka Topic Monitoring

```bash
# Check topic messages
kcat -C -b <kafka-bootstrap-servers>:9092 -t agent-actions -o beginning

# Check consumer lag
docker exec omninode-bridge-redpanda rpk group describe agent-observability-postgres
```

### Database Monitoring

```sql
-- Check recent activity
SELECT
    COUNT(*) as total_actions,
    MAX(created_at) as last_action,
    COUNT(DISTINCT correlation_id) as unique_executions
FROM agent_actions
WHERE created_at > NOW() - INTERVAL '1 hour';

-- Check action distribution
SELECT
    action_type,
    COUNT(*) as count
FROM agent_actions
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY action_type;
```

## Performance Considerations

### Action Logger

- **Overhead**: ~1-2ms per action (non-blocking async)
- **Memory**: Minimal (events serialized immediately)
- **Network**: Batched by Kafka producer (10ms linger)

### Consumer

- **Throughput**: 100+ actions/second
- **Batch size**: 100 events or 1 second timeout
- **Latency**: <500ms from publish to database persistence

### Database

- **Indexes**: Optimized for common queries (correlation_id, agent_name, created_at)
- **Cleanup**: Automatic cleanup of debug logs >30 days (call `cleanup_old_debug_logs()`)

## Known Issues

### Kafka Connection Issues

**Issue**: When connecting to remote Kafka (<kafka-bootstrap-servers>:9092), the broker may return an internal address (<kafka-bootstrap-servers>:9092) that's not accessible.

**Workaround**: Ensure Kafka advertised listeners are properly configured, or use Docker network for cross-container communication.

**Impact**: Action logging will gracefully degrade and log warnings, but won't prevent agent execution.

### Consumer Not Running

**Issue**: If consumer is not running, events will accumulate in Kafka topic but won't be persisted to database.

**Detection**: Check consumer health endpoint or query database for recent actions.

**Fix**: Start consumer with `python consumers/agent_actions_consumer.py`

## Future Enhancements

- [ ] Add support for nested actions (parent/child relationships)
- [ ] Add action replay capability
- [ ] Add real-time action streaming dashboard
- [ ] Add action filtering by project/agent/type
- [ ] Add action aggregation metrics
- [ ] Add action anomaly detection
- [ ] Add action performance regression detection

## See Also

- `migrations/005_create_agent_actions_table.sql` - Database schema
- `consumers/agent_actions_consumer.py` - Consumer implementation
- `docs/observability/AGENT_TRACEABILITY.md` - Overall traceability architecture
- `docs/observability/DATA_FLOW_ANALYSIS.md` - Data flow and gaps analysis
