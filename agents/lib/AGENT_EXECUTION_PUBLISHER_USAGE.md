# Agent Execution Publisher - Usage Guide

**Location**: `agents/lib/agent_execution_publisher.py`

**Purpose**: Publish agent execution lifecycle events to Kafka for real-time tracking and observability.

## Overview

The `AgentExecutionPublisher` provides a Kafka-based event publisher for tracking agent execution lifecycle events. It follows the OnexEnvelopeV1 structure and partition key policy for consistent event handling.

## Event Types

| Event Type | Topic | Purpose |
|------------|-------|---------|
| `omninode.agent.execution.started.v1` | `omninode.agent.execution.started.v1` | Agent execution begins |
| `omninode.agent.execution.progress.v1` | `omninode.agent.execution.progress.v1` | Agent execution progress update (future) |
| `omninode.agent.execution.completed.v1` | `omninode.agent.execution.completed.v1` | Agent execution finishes successfully (future) |
| `omninode.agent.execution.failed.v1` | `omninode.agent.execution.failed.v1` | Agent execution fails with error (future) |

## Event Schema

### Execution Started Event

**Payload Schema** (from EVENT_ALIGNMENT_PLAN.md):
```json
{
  "agent_name": "string",
  "user_request": "string",
  "correlation_id": "uuid-v7",
  "session_id": "uuid-v7",
  "started_at": "RFC3339",
  "context": {}
}
```

**Complete Envelope** (OnexEnvelopeV1 structure):
```json
{
  "event_type": "omninode.agent.execution.started.v1",
  "event_id": "uuid-v7",
  "timestamp": "RFC3339",
  "tenant_id": "default",
  "namespace": "omninode",
  "source": "omniclaude",
  "correlation_id": "uuid-v7",
  "causation_id": "uuid-v7",
  "schema_ref": "registry://omninode/agent/execution_started/v1",
  "payload": {
    "agent_name": "agent-api-architect",
    "user_request": "Design a REST API for user management",
    "correlation_id": "abc-123-def-456",
    "session_id": "session-789",
    "started_at": "2025-11-13T14:30:00Z",
    "context": {
      "domain": "api_design",
      "previous_agent": "agent-router"
    }
  }
}
```

## Partition Key Policy

**Event Family**: `agent.execution`
**Partition Key**: `correlation_id`
**Reason**: Execution lifecycle ordering - started→progress→completed events maintain temporal sequence
**Cardinality**: Medium (per agent execution, ~100-1000 unique keys/day)

This ensures all events for a single agent execution land on the same Kafka partition, maintaining temporal ordering.

## Usage

### Option 1: Convenience Function (Recommended for One-Off Publishing)

```python
from agents.lib.agent_execution_publisher import publish_execution_started
from uuid import uuid4

# Generate correlation ID and session ID
correlation_id = str(uuid4())
session_id = str(uuid4())

# Publish execution started event
success = await publish_execution_started(
    agent_name="agent-api-architect",
    user_request="Design a REST API for user management",
    correlation_id=correlation_id,
    session_id=session_id,
    context={
        "domain": "api_design",
        "previous_agent": "agent-router",
    },
)

if success:
    print("Event published successfully")
else:
    print("Event publishing failed (gracefully degraded)")
```

### Option 2: Context Manager (Recommended for Multiple Events)

```python
from agents.lib.agent_execution_publisher import AgentExecutionPublisherContext
from uuid import uuid4

correlation_id = str(uuid4())
session_id = str(uuid4())

async with AgentExecutionPublisherContext() as publisher:
    # Publish multiple events with same publisher instance
    await publisher.publish_execution_started(
        agent_name="agent-api-architect",
        user_request="Design a REST API for user management",
        correlation_id=correlation_id,
        session_id=session_id,
        context={"domain": "api_design"},
    )

    # Future: publish progress/completed/failed events
    # await publisher.publish_execution_progress(...)
    # await publisher.publish_execution_completed(...)
```

### Option 3: Manual Lifecycle Management (Advanced)

```python
from agents.lib.agent_execution_publisher import AgentExecutionPublisher
from uuid import uuid4

# Initialize publisher
publisher = AgentExecutionPublisher(
    bootstrap_servers="localhost:9092",
    enable_events=True,
)

try:
    # Start publisher
    await publisher.start()

    # Publish events
    correlation_id = str(uuid4())
    session_id = str(uuid4())

    await publisher.publish_execution_started(
        agent_name="agent-api-architect",
        user_request="Design a REST API for user management",
        correlation_id=correlation_id,
        session_id=session_id,
        context={"domain": "api_design"},
    )

finally:
    # Always stop publisher
    await publisher.stop()
```

## Integration Points

### 1. Agent Workflow Coordinator

```python
from agents.lib.agent_execution_publisher import publish_execution_started
from uuid import uuid4

async def execute_agent_workflow(agent_name: str, user_request: str):
    # Generate IDs
    correlation_id = str(uuid4())
    session_id = str(uuid4())

    # Publish execution started event
    await publish_execution_started(
        agent_name=agent_name,
        user_request=user_request,
        correlation_id=correlation_id,
        session_id=session_id,
        context={
            "workflow_type": "agent_coordination",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    # Execute agent workflow
    # ...
```

### 2. Polymorphic Agent Launcher

```python
from agents.lib.agent_execution_publisher import publish_execution_started
from uuid import uuid4

async def launch_polymorphic_agent(agent_name: str, user_request: str):
    # Generate IDs
    correlation_id = str(uuid4())
    session_id = str(uuid4())

    # Publish execution started event
    await publish_execution_started(
        agent_name=agent_name,
        user_request=user_request,
        correlation_id=correlation_id,
        session_id=session_id,
        context={
            "agent_type": "polymorphic",
            "launcher": "polymorphic_agent_launcher",
        },
    )

    # Launch polymorphic agent
    # ...
```

## Configuration

### Environment Variables

The publisher uses centralized configuration from `config/settings.py`:

```bash
# Required: Kafka bootstrap servers
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092

# Optional: Tenant ID for multi-tenant isolation
TENANT_ID=default

# Optional: Environment (dev/test/prod)
ENVIRONMENT=dev
```

### Feature Flag

To disable event publishing (e.g., for testing):

```python
publisher = AgentExecutionPublisher(
    bootstrap_servers="localhost:9092",
    enable_events=False,  # Disable event publishing
)
```

## Error Handling

The publisher implements **graceful degradation** - it never throws exceptions that would block agent execution:

```python
# Kafka failure does NOT block agent execution
success = await publish_execution_started(
    agent_name="agent-api-architect",
    user_request="Design a REST API",
    correlation_id=correlation_id,
    session_id=session_id,
)

# Agent continues execution regardless of success/failure
if not success:
    logger.warning("Event publishing failed, but continuing execution")

# Continue with agent logic
# ...
```

**Error Scenarios**:
- Kafka broker unreachable → Returns `False`, logs warning
- Producer initialization failure → Returns `False`, logs error
- Publisher not started → Returns `False`, logs debug message
- Events disabled → Returns `False`, no logging

## Performance Characteristics

| Metric | Target | Notes |
|--------|--------|-------|
| Publish time | <10ms p95 | Non-blocking async publish |
| Memory overhead | <10MB | Single producer instance |
| Success rate | >99% | With healthy Kafka cluster |
| Non-blocking | Always | Never blocks agent execution |

## Testing

### Unit Tests

See `agents/tests/test_agent_execution_publisher.py` for comprehensive unit tests.

```bash
# Run all tests
pytest agents/tests/test_agent_execution_publisher.py -v

# Run specific test
pytest agents/tests/test_agent_execution_publisher.py::TestAgentExecutionPublisher::test_publish_execution_started_success -v
```

### Integration Testing

To test with real Kafka broker:

```python
# Set environment variables
os.environ["KAFKA_BOOTSTRAP_SERVERS"] = "localhost:9092"

# Publish event
success = await publish_execution_started(
    agent_name="test-agent",
    user_request="Test request",
    correlation_id=str(uuid4()),
    session_id=str(uuid4()),
)

# Verify event in Kafka (using kafkacat or console consumer)
# kafkacat -b localhost:9092 -t omninode.agent.execution.started.v1 -C
```

## Future Enhancements

### Execution Progress Event (Planned)

```python
await publisher.publish_execution_progress(
    agent_name="agent-api-architect",
    correlation_id=correlation_id,
    progress_percent=50,
    current_step="Generating API endpoints",
    steps_completed=3,
    steps_total=6,
)
```

### Execution Completed Event (Planned)

```python
await publisher.publish_execution_completed(
    agent_name="agent-api-architect",
    correlation_id=correlation_id,
    completed_at="2025-11-13T14:35:00Z",
    result_summary="Successfully generated REST API design",
    artifacts=["api_spec.yaml", "endpoints.md"],
)
```

### Execution Failed Event (Planned)

```python
await publisher.publish_execution_failed(
    agent_name="agent-api-architect",
    correlation_id=correlation_id,
    failed_at="2025-11-13T14:33:00Z",
    error_code="VALIDATION_ERROR",
    error_message="Invalid API specification",
    stack_trace="...",
)
```

## Related Documentation

- **EVENT_ALIGNMENT_PLAN.md** - Complete event alignment plan
- **partition_key_policy.py** - Partition key policy implementation
- **event_validation.py** - Event validation utilities
- **EVENT_BUS_INTEGRATION_GUIDE.md** - Event bus integration standards

## Support

For questions or issues:
1. Review unit tests for usage examples
2. Check Kafka broker connectivity: `kafkacat -L -b localhost:9092`
3. Enable debug logging: `logger.setLevel(logging.DEBUG)`
4. Verify environment variables are set correctly

---

**Created**: 2025-11-13
**Author**: OmniClaude Polymorphic Agent
**Linear Ticket**: OMN-27
**Status**: Production Ready
