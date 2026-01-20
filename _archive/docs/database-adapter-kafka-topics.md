# Database Adapter Kafka Topics Documentation

**Service**: `database-adapter-effect`
**Version**: 1.0.0
**Contract File**: `/contracts/effects/database_adapter_effect.yaml`
**Node Implementation**: `nodes/database_adapter_effect/v1_0_0/node.py`

## Overview

The Database Adapter Effect Node is an event-driven service that consumes Kafka events from bridge orchestrator, reducer, and registry nodes, and persists workflow data to PostgreSQL with ACID compliance.

**Key Features**:
- Event-driven architecture with Kafka consumption
- Circuit breaker pattern for database resilience
- Dead Letter Queue (DLQ) for failed messages
- At-least-once delivery semantics
- Optimistic concurrency control

## Kafka Configuration

### Consumer Group

```yaml
consumer_group: database-adapter-effect-group
```

### Event Envelope

```yaml
event_envelope: OnexEnvelopeV1
```

### Auto-Commit

```yaml
auto_commit: false
max_poll_records: 100
```

**Safe Offset Commit Strategy**:
1. Process each message in batch
2. Track successful vs failed messages per partition
3. Send failed messages to DLQ
4. Commit offsets ONLY for successfully processed messages
5. Failed messages without DLQ write are NOT committed (will be redelivered)

## Consumed Topics

The database adapter subscribes to 7 topics from the bridge orchestration layer:

### 1. Workflow Events

#### `dev.omninode-bridge.orchestrator.workflow-started.v1`

**Event Type**: `workflow-started`
**Operation**: INSERT new workflow execution record
**Database Table**: `workflow_executions`
**Handler**: `_persist_workflow_execution()`

**Payload Schema**:
```json
{
  "event_type": "workflow-started",
  "correlation_id": "uuid",
  "workflow_execution_data": {
    "correlation_id": "uuid",
    "workflow_type": "string",
    "current_state": "string",
    "namespace": "string",
    "started_at": "timestamp",
    "metadata": {}
  }
}
```

**SQL Operation**:
```sql
INSERT INTO workflow_executions (
    correlation_id, workflow_type, current_state, namespace,
    started_at, metadata
) VALUES ($1, $2, $3, $4, $5, $6)
RETURNING id
```

---

#### `dev.omninode-bridge.orchestrator.workflow-completed.v1`

**Event Type**: `workflow-completed`
**Operation**: UPDATE workflow execution with completion status
**Database Table**: `workflow_executions`
**Handler**: `_persist_workflow_execution()`

**Payload Schema**:
```json
{
  "event_type": "workflow-completed",
  "correlation_id": "uuid",
  "workflow_execution_data": {
    "correlation_id": "uuid",
    "current_state": "string",
    "completed_at": "timestamp",
    "execution_time_ms": "integer",
    "metadata": {}
  }
}
```

**SQL Operation**:
```sql
UPDATE workflow_executions
SET current_state = $1,
    completed_at = $2,
    execution_time_ms = $3,
    metadata = $4,
    updated_at = NOW()
WHERE correlation_id = $5
RETURNING id
```

---

#### `dev.omninode-bridge.orchestrator.workflow-failed.v1`

**Event Type**: `workflow-failed`
**Operation**: UPDATE workflow execution with error information
**Database Table**: `workflow_executions`
**Handler**: `_persist_workflow_execution()`

**Payload Schema**:
```json
{
  "event_type": "workflow-failed",
  "correlation_id": "uuid",
  "workflow_execution_data": {
    "correlation_id": "uuid",
    "current_state": "string",
    "completed_at": "timestamp",
    "execution_time_ms": "integer",
    "error_message": "string",
    "metadata": {}
  }
}
```

**SQL Operation**:
```sql
UPDATE workflow_executions
SET current_state = $1,
    completed_at = $2,
    execution_time_ms = $3,
    error_message = $4,
    metadata = $5,
    updated_at = NOW()
WHERE correlation_id = $6
RETURNING id
```

---

### 2. Step Events

#### `dev.omninode-bridge.orchestrator.step-completed.v1`

**Event Type**: `step-completed`
**Operation**: INSERT workflow step history (append-only)
**Database Table**: `workflow_steps`
**Handler**: `_persist_workflow_step()`

**Payload Schema**:
```json
{
  "event_type": "step-completed",
  "correlation_id": "uuid",
  "workflow_step_data": {
    "workflow_id": "uuid",
    "step_name": "string",
    "step_status": "string",
    "execution_time_ms": "integer",
    "metadata": {}
  }
}
```

**Implementation Status**: Phase 2, Agent 2

---

### 3. Metadata Events

#### `dev.omninode-bridge.orchestrator.stamp-created.v1`

**Event Type**: `stamp-created`
**Operation**: INSERT metadata stamp audit record (append-only)
**Database Table**: `metadata_stamps`
**Handler**: `_persist_metadata_stamp()`

**Payload Schema**:
```json
{
  "event_type": "stamp-created",
  "correlation_id": "uuid",
  "metadata_stamp_data": {
    "file_path": "string",
    "stamp_type": "string",
    "stamp_data": {},
    "created_at": "timestamp"
  }
}
```

**Implementation Status**: Phase 2, Agent 5

---

### 4. State Events

#### `dev.omninode-bridge.reducer.state-aggregation-completed.v1`

**Event Type**: `state-aggregation-completed`
**Operation**: UPSERT bridge aggregation state
**Database Table**: `bridge_states`
**Handler**: `_persist_bridge_state()`

**Payload Schema**:
```json
{
  "event_type": "state-aggregation-completed",
  "correlation_id": "uuid",
  "bridge_state_data": {
    "bridge_id": "uuid",
    "aggregation_data": {},
    "counters": {},
    "metadata": {}
  }
}
```

**SQL Operation** (UPSERT with ON CONFLICT):
```sql
INSERT INTO bridge_states (bridge_id, aggregation_data, counters, metadata)
VALUES ($1, $2, $3, $4)
ON CONFLICT (bridge_id) DO UPDATE
SET aggregation_data = EXCLUDED.aggregation_data,
    counters = EXCLUDED.counters,
    metadata = EXCLUDED.metadata,
    updated_at = NOW()
```

**Implementation Status**: Phase 2, Agent 3

---

### 5. FSM Events

#### `dev.omninode-bridge.orchestrator.state-transition.v1` (from Orchestrator)
#### `dev.omninode-bridge.reducer.state-transition.v1` (from Reducer)

**Event Type**: `state-transition`
**Operation**: INSERT FSM state transition record (append-only audit log)
**Database Table**: `fsm_transitions`
**Handler**: `_persist_fsm_transition()`

**Payload Schema**:
```json
{
  "event_type": "state-transition",
  "correlation_id": "uuid",
  "fsm_transition_data": {
    "entity_id": "uuid",
    "entity_type": "string",
    "from_state": "string",
    "to_state": "string",
    "transition_event": "string",
    "transition_data": {},
    "created_at": "timestamp"
  }
}
```

**SQL Operation**:
```sql
INSERT INTO fsm_transitions (
    transition_id, entity_id, correlation_id, entity_type,
    from_state, to_state, transition_event, metadata,
    transition_timestamp
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
RETURNING transition_id, transition_timestamp;
```

**Implementation Status**: ✅ Implemented (Phase 2, Agent 4)

---

### 6. Heartbeat Events

#### `dev.omninode-bridge.registry.node-heartbeat.v1`

**Event Type**: `node-heartbeat`
**Operation**: UPDATE node heartbeat timestamp
**Database Table**: `node_registrations`
**Handler**: `_update_node_heartbeat()`

**Payload Schema**:
```json
{
  "event_type": "node-heartbeat",
  "correlation_id": "uuid",
  "node_heartbeat_data": {
    "node_id": "uuid",
    "node_type": "string",
    "health_status": "string",
    "last_heartbeat": "timestamp"
  }
}
```

**SQL Operation**:
```sql
UPDATE node_registrations
SET last_heartbeat = NOW(),
    health_status = $1,
    updated_at = NOW()
WHERE node_id = $2
```

**Implementation Status**: Phase 2, Agent 6

---

## Topic Naming Convention

**Format**: `{env}.{tenant}.{context}.{class}.{event_type}.{version}`

**Example**: `dev.omninode-bridge.orchestrator.workflow-started.v1`

**Components**:
- `env`: Environment (dev, staging, prod)
- `tenant`: Tenant identifier (omninode-bridge)
- `context`: Service context (orchestrator, reducer, registry)
- `class`: Event class (evt)
- `event_type`: Specific event (workflow-started, step-completed, etc.)
- `version`: API version (v1)

**Event Type Extraction** (line 2065 in node.py):
```python
topic_parts = topic.split(".")
if len(topic_parts) >= 5:
    event_type = topic_parts[4]  # Extract event_type segment (5th position)
```

---

## Dead Letter Queue (DLQ)

**DLQ Topic Suffix**: `.dlq`

**Example DLQ Topics**:
- `dev.omninode-bridge.orchestrator.workflow-started.v1.dlq`
- `dev.omninode-bridge.orchestrator.workflow-failed.v1.dlq`

**DLQ Message Format**:
```json
{
  "original_message": {},
  "original_topic": "string",
  "original_partition": "integer",
  "original_offset": "integer",
  "original_timestamp": "timestamp",
  "error_type": "string",
  "error_message": "string",
  "error_context": {},
  "failed_at": "timestamp",
  "retry_count": "integer"
}
```

**DLQ Metrics**:
- `_dlq_message_count`: Total messages sent to DLQ
- `_dlq_by_error_type`: DLQ messages grouped by error type

**DLQ Configuration** (line 144-145):
```python
self._dlq_topic_suffix = ".dlq"
self._dlq_enabled = True  # Enable DLQ by default for safety
```

---

## Event Processing Flow

### 1. Event Consumption Loop

**Method**: `_consume_events_loop()` (line 1889)

```
1. Kafka consumer polls for messages (batch_timeout_ms: 1000)
2. For each message:
   a. Extract correlation_id and event payload
   b. Route event to appropriate handler
   c. Execute database operation
   d. Track success/failure
3. Calculate safe offsets (only successful messages)
4. Commit offsets to Kafka
5. Send failed messages to DLQ
```

### 2. Event Routing

**Method**: `_route_event_to_operation()` (line 2041)

```
1. Extract event_type from topic (5th segment)
2. Build ModelDatabaseOperationInput based on event_type
3. Call process() method with operation input
4. Log success/failure
```

**Routing Map**:
| Event Type | Operation Type | Handler Method |
|------------|---------------|----------------|
| workflow-started | INSERT | _persist_workflow_execution |
| workflow-completed | UPDATE | _persist_workflow_execution |
| workflow-failed | UPDATE | _persist_workflow_execution |
| step-completed | INSERT | _persist_workflow_step |
| state-transition | INSERT | _persist_fsm_transition |
| state-aggregation-completed | UPSERT | _persist_bridge_state |
| stamp-created | INSERT | _persist_metadata_stamp |
| node-heartbeat | UPDATE | _update_node_heartbeat |

### 3. Database Operation Execution

**Method**: `process()` (line 498)

```
1. Input validation (SecurityValidator)
2. Route to operation handler based on operation_type
3. Execute with circuit breaker protection
4. Track metrics (execution time, throughput)
5. Log operation completion
6. Return ModelDatabaseOperationOutput
```

---

## Circuit Breaker Configuration

**Implementation**: `DatabaseCircuitBreaker` (line 296)

```python
self._circuit_breaker = DatabaseCircuitBreaker(
    failure_threshold=5,      # Open after 5 consecutive failures
    timeout_seconds=60,       # Wait 60s before retry
    half_open_max_calls=3,    # Allow 3 test calls in HALF_OPEN
    half_open_success_threshold=2  # Close after 2 successes
)
```

**States**:
- **CLOSED**: Normal operation, requests flow through
- **OPEN**: Circuit is tripped, all requests fail fast
- **HALF_OPEN**: Testing recovery, limited requests allowed

**Failure Handling**:
1. Database operation fails
2. Circuit breaker increments failure count
3. If failure_threshold reached, circuit opens
4. Subsequent requests fail immediately (no database calls)
5. After timeout_seconds, circuit enters HALF_OPEN
6. Test calls allowed (up to half_open_max_calls)
7. If half_open_success_threshold met, circuit closes

---

## Performance Characteristics

### Performance Targets

| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| Database operations (p95) | <10ms | >20ms | >50ms |
| Event processing (p95) | <50ms | >100ms | >200ms |
| Throughput | 1000+ events/sec | <500 events/sec | <100 events/sec |
| Connection pool efficiency | >90% | <80% | <60% |
| Circuit breaker state | CLOSED | HALF_OPEN | OPEN |

### Metrics Collection

**Method**: `get_metrics()` (line 1479)

**Metrics Categories**:
1. **Operation Counters**: persist_workflow_execution count, etc.
2. **Performance Stats**: avg, min, max, p95, p99 execution times
3. **Circuit Breaker Metrics**: state, failure count, success count
4. **Error Rates**: total errors, error rate %
5. **Throughput**: operations per second (60-second sliding window)
6. **DLQ Metrics**: total messages sent, messages by error type

**Metrics Caching**: 5-second TTL (line 188)

---

## Database Tables

### workflow_executions

**Operations**: INSERT, UPDATE, SELECT

**Schema** (inferred from code):
```sql
CREATE TABLE workflow_executions (
    id SERIAL PRIMARY KEY,
    correlation_id UUID NOT NULL UNIQUE,
    workflow_type VARCHAR NOT NULL,
    current_state VARCHAR NOT NULL,
    namespace VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    execution_time_ms INTEGER,
    error_message TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### workflow_steps

**Operations**: INSERT, SELECT

**Implementation Status**: Phase 2, Agent 2

### bridge_states

**Operations**: UPSERT, SELECT

**Implementation Status**: Phase 2, Agent 3

### fsm_transitions

**Operations**: INSERT, SELECT

**Schema**:
```sql
CREATE TABLE fsm_transitions (
    transition_id UUID PRIMARY KEY,
    entity_id UUID NOT NULL,
    correlation_id UUID NOT NULL,
    entity_type VARCHAR NOT NULL,
    from_state VARCHAR NOT NULL,
    to_state VARCHAR NOT NULL,
    transition_event VARCHAR NOT NULL,
    metadata JSONB,
    transition_timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Implementation Status**: ✅ Implemented

### metadata_stamps

**Operations**: INSERT, SELECT

**Implementation Status**: Phase 2, Agent 5

### node_registrations

**Operations**: UPDATE, INSERT, SELECT

**Implementation Status**: Phase 2, Agent 6

---

## Health Checks

**Method**: `get_health_status()` (line 1339)

**Health Check Components**:
1. **Database connectivity**: SELECT 1 query (with circuit breaker)
2. **Connection pool status**: available/in-use counts
3. **Circuit breaker state**: CLOSED/OPEN/HALF_OPEN
4. **Database version**: PostgreSQL version query
5. **Node uptime**: Time since initialization

**Performance Target**: <50ms per health check

**Health Status Values**:
- `HEALTHY`: All systems operational
- `DEGRADED`: High connection pool utilization (>80%) or HALF_OPEN circuit breaker
- `UNHEALTHY`: Database unreachable or circuit breaker OPEN

---

## Error Handling

### Error Codes

| Error Code | Description | Severity |
|------------|-------------|----------|
| DATABASE_CONNECTION_FAILED | PostgreSQL connection failed | critical |
| DATABASE_OPERATION_FAILED | Database operation failed | error |
| TRANSACTION_ROLLBACK | Transaction rolled back | warning |
| VALIDATION_ERROR | Input validation failed | error |
| CIRCUIT_BREAKER_OPEN | Circuit breaker open | warning |

### Retry Policy

```yaml
retry_policy:
  max_attempts: 3
  backoff_multiplier: 1.5
  timeout_ms: 60000  # 1 minute
```

### Fallback Strategy

```yaml
fallback_strategy: graceful_degradation
```

**Behavior**:
- Failed messages sent to DLQ
- Offsets NOT committed for failed messages
- Circuit breaker prevents cascading failures
- Graceful degradation maintains availability

---

## Example Integration

### Publishing Events (from Bridge Orchestrator)

```python
from omninode_bridge.infrastructure.kafka import KafkaProducerWrapper

# Create producer
producer = KafkaProducerWrapper()
await producer.start()

# Publish workflow-started event
await producer.publish_event(
    event_type="workflow-started",
    payload={
        "correlation_id": str(uuid4()),
        "workflow_execution_data": {
            "correlation_id": str(uuid4()),
            "workflow_type": "data_ingestion",
            "current_state": "started",
            "namespace": "omninode.services.metadata",
            "started_at": datetime.now(UTC).isoformat(),
            "metadata": {}
        }
    }
)
```

### Consuming Events (Database Adapter)

```python
# Automatic consumption via background task
# Started in initialize() method (line 391)

# Background event consumption loop
self._event_consumption_task = asyncio.create_task(
    self._consume_events_loop()
)

# Events automatically routed to database operations
# No manual consumption required
```

---

## References

- **Contract File**: `/contracts/effects/database_adapter_effect.yaml`
- **Node Implementation**: `nodes/database_adapter_effect/v1_0_0/node.py`
- **Registry**: `nodes/database_adapter_effect/v1_0_0/registry/registry_bridge_database_adapter.py`
- **Kafka Infrastructure**: `infrastructure/kafka/kafka_consumer_wrapper.py`
- **PostgreSQL Client**: `services/postgres_client.py`

---

**Last Updated**: 2025-10-30
**Correlation ID**: 9e416a8e-a6ba-446b-aa17-1362f68ab911
