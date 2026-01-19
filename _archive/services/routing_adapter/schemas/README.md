# Agent Routing Event Schemas

**Status**: ✅ COMPLETE (Schemas Defined)
**Next Step**: Implement routing adapter service
**Created**: 2025-10-30
**Reference**: `database_event_client.py` (proven event-driven pattern)

---

## Overview

Pydantic models for agent routing events via Kafka. These schemas define the contract between:
- **Agents** (request routing decisions)
- **agent-router-service** (provide routing recommendations)

**Event-Driven Architecture**:
```
Agent
  ↓ (publish)
agent.routing.requested.v1
  ↓ (consume)
agent-router-service
  ↓ (publish)
agent.routing.completed.v1 OR agent.routing.failed.v1
  ↓ (consume)
Agent
```

---

## Schemas

### 1. ModelRoutingRequest

**Purpose**: Agent routing request payload
**Topic**: `agent.routing.requested.v1`
**Published By**: Agents (polymorphic-agent, etc.)

**Structure**:
```python
{
  "user_request": "optimize my database queries",
  "correlation_id": "abc-123",
  "context": {
    "domain": "database_optimization",
    "previous_agent": "agent-api-architect",
    "current_file": "api/database.py"
  },
  "options": {
    "max_recommendations": 3,
    "min_confidence": 0.7,
    "routing_strategy": "enhanced_fuzzy_matching",
    "timeout_ms": 5000
  },
  "timeout_ms": 5000
}
```

**Validation**:
- `user_request`: Non-empty string (1-10000 chars)
- `correlation_id`: Valid UUID string
- `timeout_ms`: 1000-30000ms

### 2. ModelRoutingResponse

**Purpose**: Routing recommendations with confidence scores
**Topic**: `agent.routing.completed.v1`
**Published By**: agent-router-service

**Structure**:
```python
{
  "correlation_id": "abc-123",
  "recommendations": [
    {
      "agent_name": "agent-performance",
      "agent_title": "Performance Optimization Specialist",
      "confidence": {
        "total": 0.92,
        "trigger_score": 0.95,
        "context_score": 0.90,
        "capability_score": 0.88,
        "historical_score": 0.95,
        "explanation": "High confidence match on 'optimize' triggers"
      },
      "reason": "Strong trigger match with 'optimize' keyword",
      "definition_path": "/path/to/agent.yaml",
      "alternatives": ["agent-database-architect"]
    }
  ],
  "routing_metadata": {
    "routing_time_ms": 45,
    "cache_hit": false,
    "candidates_evaluated": 5,
    "routing_strategy": "enhanced_fuzzy_matching",
    "service_version": "1.0.0"
  },
  "selected_agent": "agent-performance"
}
```

**Validation**:
- `recommendations`: At least 1, sorted by confidence (highest first)
- All confidence scores: 0.0-1.0

### 3. ModelRoutingError

**Purpose**: Routing failure information
**Topic**: `agent.routing.failed.v1`
**Published By**: agent-router-service

**Structure**:
```python
{
  "correlation_id": "abc-123",
  "error_code": "REGISTRY_LOAD_FAILED",
  "error_message": "Failed to load agent registry: file not found",
  "error_details": {
    "file_path": "/path/to/registry.yaml",
    "exception_type": "FileNotFoundError"
  },
  "fallback_recommendation": {
    "agent_name": "polymorphic-agent",
    "reason": "Fallback due to routing failure",
    "confidence": 0.5
  },
  "retry_after_ms": 1000,
  "timestamp": "2025-10-30T14:30:00Z"
}
```

**Error Codes**:
- `REGISTRY_LOAD_FAILED`: Failed to load agent registry
- `REGISTRY_PARSE_FAILED`: Failed to parse YAML definitions
- `ROUTING_TIMEOUT`: Routing exceeded timeout
- `NO_AGENTS_AVAILABLE`: No agents match criteria
- `INVALID_REQUEST`: Request validation failed
- `SERVICE_UNAVAILABLE`: Service temporarily unavailable
- `INTERNAL_ERROR`: Unexpected internal error

### 4. ModelRoutingEventEnvelope

**Purpose**: Wraps all events with metadata
**Topics**: All routing topics
**Published By**: Both agents and agent-router-service

**Structure**:
```python
{
  "event_id": "def-456",
  "event_type": "AGENT_ROUTING_REQUESTED",
  "correlation_id": "abc-123",
  "timestamp": "2025-10-30T14:30:00Z",
  "service": "polymorphic-agent",
  "payload": { ... ModelRoutingRequest ... },
  "version": "v1"
}
```

**Event Types**:
- `AGENT_ROUTING_REQUESTED`
- `AGENT_ROUTING_COMPLETED`
- `AGENT_ROUTING_FAILED`

---

## Kafka Topics

Defined in `topics.py`:

```python
from routing_adapter.schemas.topics import TOPICS

TOPICS.REQUEST    # "agent.routing.requested.v1"
TOPICS.COMPLETED  # "agent.routing.completed.v1"
TOPICS.FAILED     # "agent.routing.failed.v1"
```

**Topic Configuration**:
- **Partitions**: 3 (parallel processing)
- **Replication Factor**: 1 (dev environment)
- **Retention**: 7 days (168 hours)
- **Compression**: gzip

---

## Usage Examples

### Publishing Routing Request

```python
from routing_adapter.schemas import (
    ModelRoutingEventEnvelope,
    ModelRoutingRequest
)
from routing_adapter.schemas.topics import TOPICS
from aiokafka import AIOKafkaProducer
import json

# Create request
envelope = ModelRoutingEventEnvelope.create_request(
    user_request="optimize my database queries",
    correlation_id="abc-123",
    context={"domain": "database_optimization"},
    options={
        "max_recommendations": 3,
        "min_confidence": 0.7
    }
)

# Publish to Kafka
producer = AIOKafkaProducer(
    bootstrap_servers="localhost:9092",
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)
await producer.start()

await producer.send(TOPICS.REQUEST, envelope.model_dump())
```

### Consuming Routing Response

```python
from routing_adapter.schemas import ModelRoutingEventEnvelope
from routing_adapter.schemas.topics import TOPICS
from aiokafka import AIOKafkaConsumer
import json

# Subscribe to response topics
consumer = AIOKafkaConsumer(
    TOPICS.COMPLETED,
    TOPICS.FAILED,
    bootstrap_servers="localhost:9092",
    group_id="polymorphic-agent",
    value_deserializer=lambda m: json.loads(m.decode("utf-8"))
)
await consumer.start()

# Consume responses
async for msg in consumer:
    envelope = ModelRoutingEventEnvelope(**msg.value)

    if envelope.event_type == "AGENT_ROUTING_COMPLETED":
        response = envelope.payload  # ModelRoutingResponse
        selected_agent = response.recommendations[0].agent_name
        confidence = response.recommendations[0].confidence.total
        print(f"Selected: {selected_agent} (confidence: {confidence})")

    elif envelope.event_type == "AGENT_ROUTING_FAILED":
        error = envelope.payload  # ModelRoutingError
        print(f"Routing failed: {error.error_code} - {error.error_message}")

        # Use fallback if provided
        if error.fallback_recommendation:
            fallback = error.fallback_recommendation.agent_name
            print(f"Using fallback: {fallback}")
```

### Request-Response Pattern

```python
import asyncio
from uuid import uuid4

# Create correlation ID for tracking
correlation_id = str(uuid4())

# 1. Create pending request future
pending_requests = {}
future = asyncio.Future()
pending_requests[correlation_id] = future

# 2. Publish request
envelope = ModelRoutingEventEnvelope.create_request(
    user_request="optimize my database queries",
    correlation_id=correlation_id
)
await producer.send(TOPICS.REQUEST, envelope.model_dump())

# 3. Wait for response with timeout
try:
    result = await asyncio.wait_for(future, timeout=5.0)
    print(f"Selected agent: {result['agent_name']}")
except asyncio.TimeoutError:
    print("Routing request timeout")

# 4. Consumer resolves future when response arrives
async for msg in consumer:
    envelope = ModelRoutingEventEnvelope(**msg.value)
    if envelope.correlation_id in pending_requests:
        future = pending_requests.pop(envelope.correlation_id)

        if envelope.event_type == "AGENT_ROUTING_COMPLETED":
            response = envelope.payload
            future.set_result({
                "agent_name": response.recommendations[0].agent_name,
                "confidence": response.recommendations[0].confidence.total
            })
        elif envelope.event_type == "AGENT_ROUTING_FAILED":
            error = envelope.payload
            future.set_exception(
                RuntimeError(f"{error.error_code}: {error.error_message}")
            )
```

---

## Validation Examples

### Valid Request

```python
from routing_adapter.schemas import ModelRoutingRequest

# Valid
request = ModelRoutingRequest(
    user_request="optimize my database queries",
    correlation_id="a2f33abd-34c2-4d63-bfe7-2cb14ded13fd"
)

# Valid with context
request = ModelRoutingRequest(
    user_request="optimize my database queries",
    correlation_id="a2f33abd-34c2-4d63-bfe7-2cb14ded13fd",
    context={"domain": "database_optimization"},
    timeout_ms=3000
)
```

### Invalid Request (ValidationError)

```python
# Invalid: empty user_request
request = ModelRoutingRequest(
    user_request="",  # ValidationError: must not be empty
    correlation_id="abc-123"
)

# Invalid: bad correlation_id
request = ModelRoutingRequest(
    user_request="optimize queries",
    correlation_id="not-a-uuid"  # ValidationError: must be valid UUID
)

# Invalid: timeout out of range
request = ModelRoutingRequest(
    user_request="optimize queries",
    correlation_id="abc-123",
    timeout_ms=500  # ValidationError: must be >= 1000ms
)
```

### Valid Response

```python
from routing_adapter.schemas import (
    ModelRoutingResponse,
    ModelAgentRecommendation,
    ModelRoutingConfidence,
    ModelRoutingMetadata
)

response = ModelRoutingResponse(
    correlation_id="abc-123",
    recommendations=[
        ModelAgentRecommendation(
            agent_name="agent-performance",
            agent_title="Performance Optimization Specialist",
            confidence=ModelRoutingConfidence(
                total=0.92,
                trigger_score=0.95,
                context_score=0.90,
                capability_score=0.88,
                historical_score=0.95,
                explanation="High confidence match"
            ),
            reason="Strong trigger match",
            definition_path="/path/to/agent.yaml"
        )
    ],
    routing_metadata=ModelRoutingMetadata(
        routing_time_ms=45,
        cache_hit=False,
        candidates_evaluated=5,
        routing_strategy="enhanced_fuzzy_matching"
    )
)
```

### Valid Error

```python
from routing_adapter.schemas import (
    ModelRoutingError,
    ModelFallbackRecommendation,
    ErrorCodes
)

error = ModelRoutingError(
    correlation_id="abc-123",
    error_code=ErrorCodes.ROUTING_TIMEOUT,
    error_message="Routing decision exceeded 5000ms timeout",
    error_details={"requested_timeout": 5000},
    fallback_recommendation=ModelFallbackRecommendation(
        agent_name="polymorphic-agent",
        reason="Fallback due to timeout"
    ),
    retry_after_ms=1000
)
```

---

## Testing

### Unit Tests

```python
import pytest
from routing_adapter.schemas import (
    ModelRoutingRequest,
    ModelRoutingEventEnvelope
)

def test_routing_request_validation():
    """Test routing request validation."""
    # Valid request
    request = ModelRoutingRequest(
        user_request="optimize my database",
        correlation_id="a2f33abd-34c2-4d63-bfe7-2cb14ded13fd"
    )
    assert request.user_request == "optimize my database"

    # Invalid: empty user_request
    with pytest.raises(ValueError):
        ModelRoutingRequest(
            user_request="",
            correlation_id="abc-123"
        )

    # Invalid: bad UUID
    with pytest.raises(ValueError):
        ModelRoutingRequest(
            user_request="optimize",
            correlation_id="not-a-uuid"
        )

def test_event_envelope():
    """Test event envelope creation."""
    envelope = ModelRoutingEventEnvelope.create_request(
        user_request="optimize my database",
        correlation_id="abc-123"
    )

    assert envelope.event_type == "AGENT_ROUTING_REQUESTED"
    assert envelope.correlation_id == "abc-123"
    assert envelope.payload.user_request == "optimize my database"
```

### Integration Tests

See `test_routing_event_client.py` (to be created in next phase).

---

## Next Steps

1. ✅ **Schemas Defined** (this document)
2. ⏳ **Create routing_event_client.py** - Client for agents to request routing
3. ⏳ **Create agent-router-service** - Service to process routing requests
4. ⏳ **Integration Tests** - End-to-end event flow validation
5. ⏳ **Update Polymorphic Agent** - Use event-driven routing

---

## Related Documentation

- **Proposal**: `docs/architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md`
- **Reference Implementation**: `agents/lib/database_event_client.py`
- **Database Events**: `docs/database-adapter-kafka-topics.md`
- **Architecture Comparison**: `docs/architecture/ROUTING_ARCHITECTURE_COMPARISON.md`

---

## Schema Versions

- **v1** (2025-10-30): Initial schema definition
  - ModelRoutingRequest
  - ModelRoutingResponse
  - ModelRoutingError
  - ModelRoutingEventEnvelope

Future versions will follow semantic versioning in topic names:
- `agent.routing.requested.v2` (breaking changes)
- `agent.routing.requested.v1.1` (backward-compatible additions)

---

**Status**: ✅ Schemas complete and ready for service implementation
**Correlation ID**: 50cc9c90-35e6-48cd-befd-91ee3ce4b2b1
