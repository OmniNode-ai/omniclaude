# omnibase_spi Protocol Layer

**Research Date**: 2025-11-09
**Repository**: `/Users/jonah/Code/omnibase_spi`
**Purpose**: Document Kafka event schemas, protocol definitions, and event-driven communication patterns

---

## Executive Summary

**omnibase_spi** is a pure protocol interface repository defining service contracts for the ONEX distributed orchestration framework. It provides **176 protocols** across **22 specialized domains** with strict architectural purity and **zero implementation dependencies**.

**Key Capabilities**:
- Event-driven workflow orchestration with FSM states and event sourcing
- Kafka/Redpanda adapter pattern for distributed messaging
- Standardized event envelopes with correlation tracking
- Request-response patterns via async events
- Complete namespace isolation from implementation packages

---

## Repository Overview

### Architecture Principles

1. **Protocol-First Design** - All services defined through Python `Protocol` interfaces
2. **Namespace Isolation** - Complete separation from implementation packages
3. **Zero Implementation Dependencies** - Pure contracts only (typing-extensions only)
4. **Runtime Type Safety** - Full `@runtime_checkable` protocol support
5. **Event Sourcing** - Sequence numbers, causation tracking, replay capabilities

### Statistics

- **Total Protocols**: 176 protocol files
- **Domain Coverage**: 22 specialized domains
- **Type Definitions**: 14 comprehensive type modules
- **Python Support**: 3.11, 3.12, 3.13
- **Package Version**: 0.2.0

### Key Protocol Domains

| Domain | Protocol Count | Purpose |
|--------|----------------|---------|
| **Event Bus** | 14 protocols | Distributed messaging infrastructure |
| **Container Management** | 14 protocols | Dependency injection, lifecycle management |
| **Workflow Orchestration** | 12 protocols | Event-driven FSM coordination |
| **MCP Integration** | 14 protocols | Multi-subsystem tool coordination |
| **Memory Management** | 14 protocols | Workflow state persistence |
| **Advanced** | 14 protocols | Adaptive chunking, AST building, contract analysis |
| **Types** | 14 protocols | Core types, contracts, error objects, envelopes |
| **Core System** | 13 protocols | Logging, health monitoring, error handling |
| **Networking** | 6 protocols | HTTP, Kafka, circuit breakers |
| **File Handling** | 8 protocols | File processing, type detection |
| **Validation** | 10 protocols | Input validation, schema compliance |
| **ONEX** | 9 protocols | Node types (Effect/Compute/Reducer/Orchestrator) |
| **Plus 10 more** | 30+ protocols | CLI, Discovery, LLM, Semantic, Security, Storage, etc. |

---

## Event Bus Architecture

### Core Event Bus Protocols

**Location**: `src/omnibase_spi/protocols/event_bus/`

#### 1. ProtocolEventBus

**File**: `protocol_event_bus.py`

```python
@runtime_checkable
class ProtocolEventBus(Protocol):
    """
    ONEX event bus protocol for distributed messaging infrastructure.

    Implements:
    - Environment isolation (dev, staging, prod)
    - Node group mini-meshes
    - Kafka/Redpanda adapter pattern
    - Standardized topic naming and headers
    """

    @property
    def adapter(self) -> ProtocolKafkaEventBusAdapter: ...

    @property
    def environment(self) -> str: ...

    @property
    def group(self) -> str: ...

    async def publish(
        self,
        topic: str,
        key: bytes | None,
        value: bytes,
        headers: "ProtocolEventBusHeaders | None" = None,
    ) -> None: ...

    async def subscribe(
        self,
        topic: str,
        group_id: str,
        on_message: Callable[["ProtocolEventMessage"], Awaitable[None]],
    ) -> Callable[[], Awaitable[None]]: ...
```

**Key Methods**:
- `publish()` - Send event to topic with optional headers
- `subscribe()` - Register async message handler, returns unsubscribe callback
- `broadcast_to_environment()` - Send to all nodes in environment
- `send_to_group()` - Send to specific node group
- `close()` - Graceful shutdown with message flush

#### 2. ProtocolEventBusHeaders

**File**: `protocol_event_bus.py`

```python
@runtime_checkable
class ProtocolEventBusHeaders(Protocol):
    """
    Standardized headers for ONEX event bus messages.

    Enforces strict interoperability across all agents and prevents
    integration failures from header naming inconsistencies.

    ID Format Specifications:
    - UUID format: "550e8400-e29b-41d4-a716-446655440000" (32 hex + hyphens)
    - OpenTelemetry Trace ID: "4bf92f3577b34da6a3ce929d0e0e4736" (32 hex, no hyphens)
    - OpenTelemetry Span ID: "00f067aa0ba902b7" (16 hex, no hyphens)
    """

    @property
    def content_type(self) -> str: ...

    @property
    def correlation_id(self) -> UUID: ...

    @property
    def message_id(self) -> UUID: ...

    @property
    def timestamp(self) -> "ProtocolDateTime": ...

    @property
    def source(self) -> str: ...

    @property
    def event_type(self) -> str: ...

    @property
    def schema_version(self) -> "ProtocolSemVer": ...

    # Optional distributed tracing
    @property
    def trace_id(self) -> str | None: ...

    @property
    def span_id(self) -> str | None: ...

    @property
    def parent_span_id(self) -> str | None: ...

    # Optional routing/retry metadata
    @property
    def priority(self) -> Literal["low", "normal", "high", "critical"] | None: ...

    @property
    def routing_key(self) -> str | None: ...

    @property
    def partition_key(self) -> str | None: ...

    @property
    def retry_count(self) -> int | None: ...

    @property
    def max_retries(self) -> int | None: ...

    @property
    def ttl_seconds(self) -> int | None: ...
```

**Header Categories**:
- **Required Headers**: content_type, correlation_id, message_id, timestamp, source, event_type, schema_version
- **Distributed Tracing**: trace_id, span_id, parent_span_id, operation_name (OpenTelemetry compatible)
- **Routing Metadata**: destination, routing_key, partition_key, priority
- **Retry/Expiry**: retry_count, max_retries, ttl_seconds

#### 3. ProtocolEventMessage

**File**: `protocol_event_bus_types.py`

```python
@runtime_checkable
class ProtocolEventMessage(Protocol):
    """
    Protocol for ONEX event bus message objects.

    Defines the contract that all event message implementations must satisfy
    for Kafka/RedPanda compatibility following ONEX Messaging Design.
    """

    topic: str
    key: MessageKey  # bytes | None
    value: bytes
    headers: "ProtocolEventHeaders"
    offset: str | None
    partition: int | None

    async def ack(self) -> None: ...
```

**Message Structure**:
- `topic` - Kafka topic name (follows naming conventions)
- `key` - Optional partition key for ordering
- `value` - Serialized event payload (JSON bytes)
- `headers` - Standardized event headers
- `offset` - Kafka offset (for tracking)
- `partition` - Kafka partition number
- `ack()` - Acknowledge message processing (commits offset)

#### 4. ProtocolEventEnvelope

**File**: `protocol_event_envelope.py`

```python
@runtime_checkable
class ProtocolEventEnvelope(Protocol, Generic[T]):
    """
    Protocol defining the minimal interface for event envelopes.

    This protocol allows mixins to type-hint envelope parameters without
    importing the concrete ModelEventEnvelope class, breaking circular dependencies.
    """

    async def get_payload(self) -> T:
        """Get the wrapped event payload."""
        ...
```

**Purpose**: Minimal interface for event envelopes to break circular import dependencies

---

## Topic Naming Conventions

### Pattern: `{environment}.{service}.{domain}.{action}.{version}`

**Examples from omniclaude**:

#### Intelligence Events
```
dev.archon-intelligence.intelligence.code-analysis-requested.v1
dev.archon-intelligence.intelligence.code-analysis-completed.v1
dev.archon-intelligence.intelligence.code-analysis-failed.v1
```

#### Agent Routing Events
```
agent.routing.requested.v1
agent.routing.completed.v1
agent.routing.failed.v1
```

### Topic Naming Rules

1. **Environment Prefix** (optional): `dev`, `staging`, `prod`
2. **Service Name**: Source service identifier (e.g., `archon-intelligence`, `agent`)
3. **Domain**: Functional area (e.g., `intelligence`, `routing`, `database`)
4. **Action**: Event action (e.g., `requested`, `completed`, `failed`, `created`, `updated`)
5. **Version**: Semantic version (e.g., `v1`, `v2`)

**Topic Isolation Patterns**:
- Environment isolation: `{env}-{topic}` (e.g., "prod-user-events")
- Node group isolation: `{group}-{topic}` (e.g., "auth-user-events")
- Combined: `{env}-{group}-{topic}` (e.g., "prod-auth-user-events")

---

## Event Envelope Structure

### Standard Event Envelope

**From omniclaude**: `ModelRoutingEventEnvelope` (Pydantic implementation)

```python
class ModelRoutingEventEnvelope(BaseModel, Generic[TPayload]):
    """
    Event envelope for routing events.

    Wraps routing payloads with metadata for Kafka event bus.
    Follows the same pattern as database events for consistency.
    """

    event_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique event identifier (UUID string, auto-generated)",
    )
    event_type: str = Field(
        ...,
        description="Event type (e.g., AGENT_ROUTING_REQUESTED|COMPLETED|FAILED)",
    )
    correlation_id: str = Field(
        ...,
        description="Request correlation ID for tracing (UUID string)",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="Event timestamp (ISO 8601, auto-generated)",
    )
    service: str = Field(
        ...,
        min_length=1,
        description="Source service name",
    )
    payload: Union[TPayload, Dict[str, Any]] = Field(
        ...,
        description="Event payload (request/response/error)",
    )
    version: str = Field(
        default="v1",
        description="Event schema version",
    )
```

**Example JSON Structure**:

```json
{
  "event_id": "def-456",
  "event_type": "AGENT_ROUTING_REQUESTED",
  "correlation_id": "abc-123",
  "timestamp": "2025-10-30T14:30:00Z",
  "service": "polymorphic-agent",
  "payload": {
    "user_request": "optimize my database queries",
    "correlation_id": "abc-123",
    "context": {"domain": "database_optimization"},
    "options": {
      "max_recommendations": 3,
      "min_confidence": 0.7,
      "routing_strategy": "enhanced_fuzzy_matching",
      "timeout_ms": 5000
    },
    "timeout_ms": 5000
  },
  "version": "v1"
}
```

### Envelope Components

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | UUID string | Yes (auto) | Unique event identifier, auto-generated |
| `event_type` | String | Yes | Event type constant (UPPERCASE_SNAKE_CASE) |
| `correlation_id` | UUID string | Yes | Request correlation ID for tracing across events |
| `timestamp` | ISO 8601 string | Yes (auto) | Event creation timestamp, auto-generated |
| `service` | String | Yes | Source service name (originator) |
| `payload` | Object/Dict | Yes | Event-specific payload (typed or generic dict) |
| `version` | String | Yes (default: v1) | Event schema version for compatibility |

---

## Request-Response Pattern via Events

### Async Request-Response Flow

**Pattern**: Publish request → Wait for correlated response → Timeout fallback

**Example from omniclaude**: `IntelligenceEventClient`

```python
class IntelligenceEventClient:
    """
    Kafka client for intelligence event publishing and consumption.

    Provides request-response pattern with correlation tracking,
    timeout handling, and graceful fallback for intelligence operations.
    """

    # Topic names
    TOPIC_REQUEST = "dev.archon-intelligence.intelligence.code-analysis-requested.v1"
    TOPIC_COMPLETED = "dev.archon-intelligence.intelligence.code-analysis-completed.v1"
    TOPIC_FAILED = "dev.archon-intelligence.intelligence.code-analysis-failed.v1"

    async def request_pattern_discovery(
        self,
        source_path: str,
        language: str,
        timeout_ms: int = 5000,
    ) -> Dict[str, Any]:
        """
        Request pattern discovery via Kafka event.

        Flow:
        1. Generate correlation_id
        2. Publish to TOPIC_REQUEST
        3. Wait for TOPIC_COMPLETED or TOPIC_FAILED
        4. Return result or raise TimeoutError
        """
        correlation_id = str(uuid4())

        # Create request envelope
        envelope = {
            "event_id": str(uuid4()),
            "event_type": "CODE_ANALYSIS_REQUESTED",
            "correlation_id": correlation_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "omniclaude",
            "payload": {
                "operation_type": "PATTERN_EXTRACTION",
                "source_path": source_path,
                "language": language,
                "options": {
                    "limit": 50,
                    "include_patterns": True,
                    "include_metrics": False,
                },
                "timeout_ms": timeout_ms,
            },
            "version": "v1",
        }

        # Publish request
        await self._producer.send_and_wait(
            self.TOPIC_REQUEST,
            value=json.dumps(envelope).encode("utf-8"),
            key=correlation_id.encode("utf-8"),
        )

        # Wait for response (consumer stores in _pending_requests)
        try:
            result = await asyncio.wait_for(
                self._pending_requests[correlation_id],
                timeout=timeout_ms / 1000.0,
            )
            return result
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Pattern discovery request timed out after {timeout_ms}ms"
            )
```

### Request-Response Components

1. **Correlation ID Tracking**:
   - Generate unique correlation_id (UUID)
   - Use as Kafka message key (for ordering/partitioning)
   - Store future/promise in `_pending_requests` dict
   - Consumer matches response correlation_id to pending request

2. **Topic Trio Pattern**:
   - **Request Topic**: `*.requested.v1` - Client publishes request
   - **Success Topic**: `*.completed.v1` - Service publishes success response
   - **Failure Topic**: `*.failed.v1` - Service publishes error response

3. **Timeout Handling**:
   - `asyncio.wait_for()` with configurable timeout (default 5000ms)
   - Graceful fallback on timeout (caller handles)
   - Future cleanup on timeout to prevent memory leaks

4. **Consumer Background Task**:
   - Long-running consumer task polls response topics
   - Matches `correlation_id` from response to pending request
   - Resolves future with result or rejects with error
   - Auto-cleanup on client shutdown

---

## Event Publishing Patterns

### 1. Simple Event Publishing

**Protocol**: `ProtocolEventPublisher`

```python
@runtime_checkable
class ProtocolEventPublisher(Protocol):
    """
    Protocol for event publishers with reliability features.

    Defines contract for publishing events with:
    - Retry logic with exponential backoff
    - Circuit breaker to prevent cascading failures
    - Event validation before publishing
    - Correlation ID tracking
    - Dead letter queue (DLQ) routing
    - Metrics tracking
    """

    async def publish(
        self,
        event_type: str,
        payload: Any,
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
        metadata: Optional[Dict[str, "ContextValue"]] = None,
        topic: Optional[str] = None,
        partition_key: Optional[str] = None,
    ) -> bool:
        """
        Publish event to Kafka with retry and circuit breaker.

        Args:
            event_type: Fully-qualified event type (e.g., "omninode.codegen.request.validate.v1")
            payload: Event payload (dict or Pydantic model)
            correlation_id: Optional correlation ID (generated if not provided)
            causation_id: Optional causation ID for event sourcing
            metadata: Optional event metadata
            topic: Optional topic override (defaults to event_type)
            partition_key: Optional partition key for ordering

        Returns:
            True if published successfully, False otherwise

        Raises:
            RuntimeError: If circuit breaker is open
        """
        ...
```

**Usage Example**:

```python
from omnibase_spi.protocols.event_bus import ProtocolEventPublisher

# Get publisher implementation
publisher: ProtocolEventPublisher = create_event_publisher(
    bootstrap_servers="redpanda:9092",
    service_name="my-service",
    instance_id="instance-123"
)

# Publish event
success = await publisher.publish(
    event_type="omninode.my_domain.event.something_happened.v1",
    payload={"key": "value"},
    correlation_id="correlation-123"
)

# Get metrics
metrics = await publisher.get_metrics()
print(f"Published: {metrics['events_published']}")

# Clean shutdown
await publisher.close()
```

### 2. Circuit Breaker Pattern

**Circuit Breaker States**:
- **Closed**: Normal operation, events published
- **Open**: Threshold failures exceeded, prevents additional publish attempts
- **Half-Open**: Automatic retry after timeout period

**Dead Letter Queue (DLQ)**:
- Failed events (after max retries) routed to DLQ topics
- Topic naming: `{original_topic}.dlq`
- Error metadata attached for debugging

---

## Kafka Adapter Protocols

### ProtocolKafkaAdapter

**File**: `protocol_kafka_adapter.py`

```python
@runtime_checkable
class ProtocolKafkaAdapter(Protocol):
    """
    Protocol for Kafka event bus adapter implementations.

    Provides Kafka-specific configuration and connection management protocols
    along with the core event bus adapter interface.
    """

    @property
    def bootstrap_servers(self) -> str: ...

    @property
    def environment(self) -> str: ...

    @property
    def group(self) -> str: ...

    @property
    def config(self) -> ProtocolKafkaConfig | None: ...

    @property
    def kafka_config(self) -> ProtocolKafkaConfig: ...

    async def build_topic_name(self, topic: str) -> str: ...

    # Core event bus adapter interface methods
    async def publish(
        self,
        topic: str,
        key: bytes | None,
        value: bytes,
        headers: EventBusHeaders,
    ) -> None: ...

    async def subscribe(
        self,
        topic: str,
        group_id: str,
        on_message: Callable[["ProtocolEventMessage"], Awaitable[None]],
    ) -> Callable[[], Awaitable[None]]: ...

    async def close(self) -> None: ...
```

### ProtocolKafkaConfig

```python
@runtime_checkable
class ProtocolKafkaConfig(Protocol):
    """Protocol for Kafka configuration parameters."""

    security_protocol: str
    sasl_mechanism: str
    sasl_username: str | None
    sasl_password: str | None
    ssl_cafile: str | None
    auto_offset_reset: str
    enable_auto_commit: bool
    session_timeout_ms: int
    request_timeout_ms: int
```

### ProtocolKafkaClient

**File**: `protocol_kafka_client.py`

```python
@runtime_checkable
class ProtocolKafkaClient(Protocol):
    """
    Protocol interface for Kafka client implementations.

    Provides standardized interface for Kafka producer/consumer operations
    that can be implemented by different Kafka client libraries.
    """

    async def start(self) -> None:
        """Start the Kafka client and establish connections."""
        ...

    async def stop(self) -> None:
        """Stop the Kafka client and clean up resources."""
        ...

    async def send_and_wait(
        self, topic: str, value: bytes, key: bytes | None = None
    ) -> None:
        """
        Send a message to Kafka and wait for acknowledgment.

        Args:
            topic: Target topic for the message
            value: Message payload as bytes
            key: Optional message key for partitioning (default: None)

        Raises:
            ProducerError: If message production fails
            TimeoutError: If acknowledgment times out
        """
        ...

    def bootstrap_servers(self) -> list[str]: ...
```

---

## Event Types and Schemas

### Event Type Categories

**From omnibase_spi**: `protocol_event_bus_types.py`

#### 1. Generic Events

```python
@runtime_checkable
class ProtocolEvent(Protocol):
    """Protocol for event objects."""

    event_type: str
    event_data: dict[str, "ProtocolEventData"]
    correlation_id: UUID
    timestamp: "ProtocolDateTime"
    source: str

    async def validate_event(self) -> bool: ...
```

#### 2. Agent Events

```python
@runtime_checkable
class ProtocolAgentEvent(Protocol):
    """Protocol for agent event objects."""

    agent_id: str
    event_type: Literal["created", "started", "stopped", "error", "heartbeat"]
    timestamp: "ProtocolDateTime"
    correlation_id: UUID
    metadata: dict[str, "ContextValue"]

    async def validate_agent_event(self) -> bool: ...
```

#### 3. Work Result Events

```python
@runtime_checkable
class ProtocolWorkResult(Protocol):
    """Protocol for work result objects."""

    work_ticket_id: str
    result_type: Literal["success", "failure", "timeout", "cancelled"]
    result_data: dict[str, "ContextValue"]
    execution_time_ms: int
    error_message: str | None
    metadata: dict[str, "ContextValue"]

    async def validate_work_result(self) -> bool: ...
```

#### 4. Progress Update Events

```python
@runtime_checkable
class ProtocolProgressUpdate(Protocol):
    """Protocol for progress update objects."""

    work_item_id: str
    progress_percentage: float
    status_message: str
    estimated_completion: "ProtocolDateTime | None"
    metadata: dict[str, "ContextValue"]

    async def validate_progress_update(self) -> bool: ...
```

### Event Data Types

```python
@runtime_checkable
class ProtocolEventData(Protocol):
    """Protocol for event data values supporting validation and serialization."""

    async def validate_for_transport(self) -> bool: ...

@runtime_checkable
class ProtocolEventStringData(ProtocolEventData, Protocol):
    """Protocol for string-based event data."""
    value: str

@runtime_checkable
class ProtocolEventStringListData(ProtocolEventData, Protocol):
    """Protocol for string list event data."""
    value: list[str]

@runtime_checkable
class ProtocolEventStringDictData(ProtocolEventData, Protocol):
    """Protocol for string dictionary event data."""
    value: dict[str, "ContextValue"]
```

---

## Event Serialization

### JSON Serialization (Standard)

**From omniclaude examples**:

```python
# Request envelope serialization
envelope = ModelRoutingEventEnvelope.create_request(
    user_request="optimize my database queries",
    correlation_id="abc-123",
    context={"domain": "database_optimization"}
)

# Serialize to JSON bytes
event_json = envelope.model_dump_json().encode("utf-8")

# Publish to Kafka
await producer.send_and_wait(
    topic="agent.routing.requested.v1",
    value=event_json,
    key=correlation_id.encode("utf-8")
)
```

**Response envelope deserialization**:

```python
# Consume from Kafka
async for msg in consumer:
    # Deserialize JSON bytes
    envelope_dict = json.loads(msg.value.decode("utf-8"))

    # Validate and parse
    envelope = ModelRoutingEventEnvelope(**envelope_dict)

    # Extract payload
    response_payload = envelope.payload

    # Match correlation ID
    if envelope.correlation_id == pending_correlation_id:
        # Resolve pending request
        future.set_result(response_payload)

    # Acknowledge message
    await msg.ack()
```

### Pydantic Model Serialization

**Advantages**:
- Type validation on serialization/deserialization
- JSON schema generation
- Clear error messages for invalid data
- Auto-conversion (datetime → ISO 8601 string)

**Example**:

```python
from pydantic import BaseModel, Field
from datetime import datetime, UTC
from uuid import uuid4

class MyEventPayload(BaseModel):
    operation: str
    entity_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

# Create envelope
envelope = ModelEventEnvelope(
    event_type="MY_EVENT",
    correlation_id=str(uuid4()),
    service="my-service",
    payload=MyEventPayload(
        operation="create",
        entity_id="entity-123",
        metadata={"source": "api"}
    )
)

# Serialize
json_bytes = envelope.model_dump_json().encode("utf-8")

# Deserialize
envelope_loaded = ModelEventEnvelope(**json.loads(json_bytes))
payload_typed: MyEventPayload = envelope_loaded.payload
```

---

## Dead Letter Queue (DLQ) Handling

### ProtocolDLQHandler

**File**: `protocol_dlq_handler.py`

```python
@runtime_checkable
class ProtocolDLQHandler(Protocol):
    """
    Protocol for Dead Letter Queue (DLQ) management.

    Handles failed events that exceeded max retries, providing:
    - DLQ routing and storage
    - Reprocessing capabilities
    - Error analysis and reporting
    """

    async def send_to_dlq(
        self,
        original_topic: str,
        message: "ProtocolEventMessage",
        error: Exception,
        retry_count: int,
    ) -> None:
        """
        Send failed event to DLQ.

        Args:
            original_topic: Original topic where event failed
            message: Failed event message
            error: Exception that caused failure
            retry_count: Number of retry attempts
        """
        ...

    async def reprocess_dlq_messages(
        self,
        dlq_topic: str,
        handler: Callable[["ProtocolEventMessage"], Awaitable[bool]],
        max_retries: int = 3,
    ) -> dict[str, int]:
        """
        Reprocess messages from DLQ.

        Args:
            dlq_topic: DLQ topic to reprocess
            handler: Message handler function
            max_retries: Maximum retry attempts per message

        Returns:
            Statistics: {"processed": N, "succeeded": M, "failed": K}
        """
        ...
```

**DLQ Topic Naming**: `{original_topic}.dlq`

**Example**:
- Original: `agent.routing.requested.v1`
- DLQ: `agent.routing.requested.v1.dlq`

---

## Schema Registry Integration

### ProtocolSchemaRegistry

**File**: `protocol_schema_registry.py`

```python
@runtime_checkable
class ProtocolSchemaRegistry(Protocol):
    """
    Protocol for schema registry integration.

    Provides event schema validation and versioning support.
    """

    async def register_schema(
        self,
        subject: str,
        schema: dict[str, Any],
        schema_type: str = "JSON",
    ) -> int:
        """
        Register event schema.

        Args:
            subject: Schema subject (typically topic name)
            schema: JSON schema definition
            schema_type: Schema type (JSON, AVRO, PROTOBUF)

        Returns:
            Schema ID
        """
        ...

    async def get_schema(
        self,
        schema_id: int,
    ) -> dict[str, Any]:
        """Retrieve schema by ID."""
        ...

    async def validate_message(
        self,
        message: bytes,
        schema_id: int,
    ) -> bool:
        """Validate message against schema."""
        ...
```

---

## Real-World Event Examples

### 1. Intelligence Code Analysis Events

**From omniclaude**:

**Request Event** (`dev.archon-intelligence.intelligence.code-analysis-requested.v1`):

```json
{
  "event_id": "8b57ec39-45b5-467b-939c-dd1439219f69",
  "event_type": "CODE_ANALYSIS_REQUESTED",
  "correlation_id": "abc-123",
  "timestamp": "2025-10-27T14:30:00Z",
  "service": "omniclaude",
  "payload": {
    "operation_type": "PATTERN_EXTRACTION",
    "collection_name": "execution_patterns",
    "options": {
      "limit": 50,
      "include_patterns": true,
      "include_metrics": false
    },
    "timeout_ms": 5000
  },
  "version": "v1"
}
```

**Response Event** (`dev.archon-intelligence.intelligence.code-analysis-completed.v1`):

```json
{
  "event_id": "def-456",
  "event_type": "CODE_ANALYSIS_COMPLETED",
  "correlation_id": "abc-123",
  "timestamp": "2025-10-27T14:30:00.450Z",
  "service": "archon-intelligence",
  "payload": {
    "patterns": [
      {
        "name": "Node State Management Pattern",
        "file_path": "node_state_manager_effect.py",
        "confidence": 0.95,
        "node_types": ["EFFECT", "REDUCER"],
        "use_cases": ["State persistence", "Transaction management"]
      }
    ],
    "query_time_ms": 450,
    "total_count": 120
  },
  "version": "v1"
}
```

### 2. Agent Routing Events

**Request Event** (`agent.routing.requested.v1`):

```json
{
  "event_id": "ghi-789",
  "event_type": "AGENT_ROUTING_REQUESTED",
  "correlation_id": "routing-123",
  "timestamp": "2025-10-30T14:30:00Z",
  "service": "polymorphic-agent",
  "payload": {
    "user_request": "optimize my database queries",
    "correlation_id": "routing-123",
    "context": {"domain": "database_optimization"},
    "options": {
      "max_recommendations": 3,
      "min_confidence": 0.7,
      "routing_strategy": "enhanced_fuzzy_matching",
      "timeout_ms": 5000
    },
    "timeout_ms": 5000
  },
  "version": "v1"
}
```

**Response Event** (`agent.routing.completed.v1`):

```json
{
  "event_id": "jkl-012",
  "event_type": "AGENT_ROUTING_COMPLETED",
  "correlation_id": "routing-123",
  "timestamp": "2025-10-30T14:30:00.045Z",
  "service": "agent-router-service",
  "payload": {
    "correlation_id": "routing-123",
    "recommendations": [
      {
        "agent_name": "database-optimization-agent",
        "confidence": 0.92,
        "reasoning": "Specialized in query optimization with 95% success rate",
        "capabilities": ["query_analysis", "index_optimization", "execution_plan_review"],
        "priority": 1
      }
    ],
    "routing_metadata": {
      "routing_time_ms": 45,
      "cache_hit": false,
      "candidates_evaluated": 5,
      "routing_strategy": "enhanced_fuzzy_matching"
    }
  },
  "version": "v1"
}
```

---

## Event Versioning Strategy

### Semantic Versioning for Events

**Version Format**: `v{major}.{minor}` (e.g., `v1`, `v1.1`, `v2`)

**Version Incrementing Rules**:
- **Major version** (`v1` → `v2`): Breaking changes (remove fields, change types, rename fields)
- **Minor version** (`v1` → `v1.1`): Backward-compatible additions (new optional fields)

**Examples**:

```python
# Breaking change: New major version
# v1 → v2
{
  "event_type": "AGENT_ROUTING_REQUESTED",  # Changed field name
  "user_query": "...",  # Renamed from user_request
  "timeout_seconds": 5  # Changed from timeout_ms to timeout_seconds
}

# Backward-compatible addition: Minor version
# v1 → v1.1
{
  "event_type": "AGENT_ROUTING_REQUESTED",
  "user_request": "...",
  "timeout_ms": 5000,
  "priority": "normal"  # New optional field (backward-compatible)
}
```

### Topic Versioning

**Topic names include version suffix**: `agent.routing.requested.v1`

**Migration Strategy**:
1. Deploy `v2` consumer alongside `v1` consumer
2. Gradually migrate publishers to `v2` topic
3. Monitor `v1` topic traffic
4. Retire `v1` consumer when traffic reaches zero
5. Archive `v1` topic after retention period

---

## Validation and Compliance

### SPI Validation Framework

**From omnibase_spi**: `scripts/validation/comprehensive_spi_validator.py`

**16 Comprehensive Validation Rules**:

| Rule | Description | Auto-Fix |
|------|-------------|----------|
| **SPI001** | No Protocol `__init__` methods | ❌ |
| **SPI002** | Protocol naming conventions (must start with "Protocol") | ❌ |
| **SPI003** | `@runtime_checkable` decorator enforcement | ✅ |
| **SPI004** | Protocol method bodies (ellipsis only) | ✅ |
| **SPI005** | Async I/O operations | ❌ |
| **SPI006** | Proper Callable types | ❌ |
| **SPI007** | No concrete classes in SPI | ❌ |
| **SPI008** | No standalone functions | ❌ |
| **SPI009** | ContextValue usage patterns | ❌ |
| **SPI010** | Duplicate protocol detection | ❌ |
| **SPI011** | Protocol name conflicts | ❌ |
| **SPI012** | Namespace isolation | ❌ |
| **SPI013** | Forward reference typing | ✅ |
| **SPI014** | Protocol documentation | ❌ |
| **SPI015** | Method type annotations | ❌ |
| **SPI016** | SPI implementation purity | ❌ |

**Usage**:

```bash
# Run comprehensive validation
python scripts/validation/comprehensive_spi_validator.py src/

# Apply automatic fixes
python scripts/validation/comprehensive_spi_validator.py src/ --fix

# Generate JSON report for CI/CD
python scripts/validation/comprehensive_spi_validator.py src/ --json-report

# Pre-commit integration mode (faster)
python scripts/validation/comprehensive_spi_validator.py --pre-commit
```

### Namespace Isolation Rules

**Allowed Imports**:
- ✅ `from omnibase_spi.protocols.types import ...`
- ✅ `from omnibase_spi.protocols.core import ...`
- ✅ `from omnibase_spi.protocols.event_bus import ...`

**Forbidden Imports**:
- ❌ `from omnibase_spi.model import ...`
- ❌ `from omnibase_spi.core import ...`
- ❌ `from omnibase.* import ...` (external omnibase modules)

**Validation**:

```bash
# Quick namespace check
grep -r "from omnibase\." src/ | grep -v "from omnibase_spi.protocols"
# Should return no results

# Run namespace isolation tests
poetry run pytest tests/test_protocol_imports.py -v
```

---

## Integration Patterns

### 1. Event Bus Adapter Implementation

**Example**: Kafka Adapter for Event Bus

```python
from omnibase_spi.protocols.event_bus import (
    ProtocolKafkaEventBusAdapter,
    ProtocolEventBusHeaders,
    ProtocolEventMessage,
)
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer

class KafkaEventBusAdapter(ProtocolKafkaEventBusAdapter):
    """Kafka implementation of event bus adapter protocol."""

    def __init__(
        self,
        bootstrap_servers: str,
        environment: str = "dev",
        group: str = "default",
    ):
        self._bootstrap_servers = bootstrap_servers
        self._environment = environment
        self._group = group
        self._producer = None
        self._consumers = {}

    async def publish(
        self,
        topic: str,
        key: bytes | None,
        value: bytes,
        headers: ProtocolEventBusHeaders,
    ) -> None:
        """Publish event to Kafka topic."""
        # Build full topic name with environment/group prefix
        full_topic = await self.build_topic_name(topic)

        # Convert headers to Kafka format
        kafka_headers = [
            ("content_type", headers.content_type.encode("utf-8")),
            ("correlation_id", str(headers.correlation_id).encode("utf-8")),
            ("message_id", str(headers.message_id).encode("utf-8")),
            ("timestamp", headers.timestamp.isoformat().encode("utf-8")),
            ("source", headers.source.encode("utf-8")),
            ("event_type", headers.event_type.encode("utf-8")),
            ("schema_version", str(headers.schema_version).encode("utf-8")),
        ]

        # Add optional headers
        if headers.trace_id:
            kafka_headers.append(("trace_id", headers.trace_id.encode("utf-8")))

        # Publish to Kafka
        await self._producer.send_and_wait(
            topic=full_topic,
            key=key,
            value=value,
            headers=kafka_headers,
        )

    async def subscribe(
        self,
        topic: str,
        group_id: str,
        on_message: Callable[[ProtocolEventMessage], Awaitable[None]],
    ) -> Callable[[], Awaitable[None]]:
        """Subscribe to Kafka topic with async message handler."""
        full_topic = await self.build_topic_name(topic)

        # Create consumer
        consumer = AIOKafkaConsumer(
            full_topic,
            bootstrap_servers=self._bootstrap_servers,
            group_id=group_id,
            auto_offset_reset="earliest",
        )

        await consumer.start()
        self._consumers[full_topic] = consumer

        # Background consumer task
        async def consume():
            try:
                async for msg in consumer:
                    # Wrap in ProtocolEventMessage
                    event_msg = KafkaEventMessage(msg)
                    await on_message(event_msg)
            finally:
                await consumer.stop()

        task = asyncio.create_task(consume())

        # Return unsubscribe callback
        async def unsubscribe():
            task.cancel()
            await consumer.stop()

        return unsubscribe

    async def build_topic_name(self, topic: str) -> str:
        """Build full topic name with environment/group prefix."""
        return f"{self._environment}.{self._group}.{topic}"
```

### 2. Event Publisher Implementation

**Example**: Reliable Event Publisher with Circuit Breaker

```python
from omnibase_spi.protocols.event_bus import ProtocolEventPublisher
from typing import Any, Dict, Optional

class ReliableEventPublisher(ProtocolEventPublisher):
    """Event publisher with retry, circuit breaker, and DLQ."""

    def __init__(
        self,
        kafka_client: ProtocolKafkaClient,
        max_retries: int = 3,
        circuit_breaker_threshold: int = 5,
    ):
        self._kafka_client = kafka_client
        self._max_retries = max_retries
        self._circuit_breaker_threshold = circuit_breaker_threshold
        self._failure_count = 0
        self._circuit_open = False
        self._metrics = {
            "events_published": 0,
            "events_failed": 0,
            "events_sent_to_dlq": 0,
        }

    async def publish(
        self,
        event_type: str,
        payload: Any,
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        topic: Optional[str] = None,
        partition_key: Optional[str] = None,
    ) -> bool:
        """Publish event with retry and circuit breaker."""
        if self._circuit_open:
            raise RuntimeError("Circuit breaker is open")

        # Create event envelope
        envelope = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "correlation_id": correlation_id or str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "my-service",
            "payload": payload,
            "version": "v1",
        }

        # Retry loop
        for attempt in range(self._max_retries):
            try:
                await self._kafka_client.send_and_wait(
                    topic=topic or event_type,
                    value=json.dumps(envelope).encode("utf-8"),
                    key=(partition_key or correlation_id).encode("utf-8"),
                )

                self._metrics["events_published"] += 1
                self._failure_count = 0  # Reset on success
                return True

            except Exception as e:
                self._failure_count += 1

                if self._failure_count >= self._circuit_breaker_threshold:
                    self._circuit_open = True

                if attempt == self._max_retries - 1:
                    # Send to DLQ
                    await self._send_to_dlq(envelope, e)
                    self._metrics["events_sent_to_dlq"] += 1
                    return False

                # Exponential backoff
                await asyncio.sleep(2 ** attempt)

        self._metrics["events_failed"] += 1
        return False
```

---

## Performance Characteristics

### Kafka/Redpanda Performance

**From omniclaude documentation**:

| Metric | Target | Critical |
|--------|--------|----------|
| **Request-Response Latency** | <100ms p95 | >500ms |
| **Event Durability** | Persistent storage | N/A |
| **Throughput** | 100+ req/s | <10 req/s |
| **Timeout** | 5000ms default | N/A |
| **Memory Overhead** | <20MB per client | >100MB |
| **Success Rate** | >95% | <80% |

**Kafka Topic Retention**:
- Default: 7 days (168 hours)
- Configurable per topic
- Compaction available for key-based retention

**Consumer Lag Monitoring**:
- Monitor `consumer_lag` metric
- Alert if lag > 10,000 messages
- Auto-scale consumers on high lag

---

## Best Practices

### 1. Event Design

✅ **DO**:
- Use descriptive event types (UPPERCASE_SNAKE_CASE)
- Include correlation_id in all events
- Auto-generate event_id and timestamp
- Use semantic versioning (v1, v2)
- Validate payloads before publishing

❌ **DON'T**:
- Hardcode timestamps or IDs
- Omit correlation tracking
- Change event structure without versioning
- Send large payloads (>1MB) via events
- Use events for synchronous RPC calls

### 2. Topic Design

✅ **DO**:
- Follow naming convention: `{env}.{service}.{domain}.{action}.{version}`
- Use trio pattern: `requested`, `completed`, `failed`
- Partition by correlation_id for ordering
- Set retention based on use case
- Monitor topic growth

❌ **DON'T**:
- Create topics dynamically in production
- Use overly generic topic names
- Skip environment prefixes
- Forget version suffixes

### 3. Error Handling

✅ **DO**:
- Implement timeout handling (default: 5000ms)
- Use DLQ for failed events
- Log correlation_id in errors
- Implement circuit breaker pattern
- Graceful degradation on failures

❌ **DON'T**:
- Retry indefinitely without backoff
- Silently drop failed events
- Ignore timeout errors
- Block on event publishing

### 4. Monitoring

✅ **DO**:
- Track publish/consume metrics
- Monitor consumer lag
- Alert on circuit breaker opens
- Trace correlation_id across services
- Monitor DLQ message counts

❌ **DON'T**:
- Ignore consumer lag warnings
- Skip correlation tracking
- Miss DLQ monitoring
- Forget to track success rates

---

## Related Documentation

### omnibase_spi Repository

- **README**: `/Users/jonah/Code/omnibase_spi/README.md` - Complete protocol documentation
- **CLAUDE.md**: `/Users/jonah/Code/omnibase_spi/CLAUDE.md` - Development guidelines
- **API Reference**: `docs/api-reference/README.md` - All 176 protocols
- **Validation**: `scripts/validation/` - SPI compliance tools

### omniclaude Integration

- **CLAUDE.md**: Event bus architecture and Kafka topics
- **Intelligence Event Client**: `agents/lib/intelligence_event_client.py`
- **Routing Adapter**: `services/routing_adapter/schemas/`
- **Event Flow Docs**: `docs/architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md`

### External References

- **Kafka Documentation**: https://kafka.apache.org/documentation/
- **Redpanda Documentation**: https://docs.redpanda.com/
- **OpenTelemetry**: https://opentelemetry.io/docs/concepts/signals/traces/
- **Pydantic**: https://docs.pydantic.dev/latest/

---

## Appendix: Protocol File Locations

### Event Bus Protocols

```
src/omnibase_spi/protocols/event_bus/
├── __init__.py
├── protocol_dlq_handler.py
├── protocol_event_bus_context_manager.py
├── protocol_event_bus_in_memory.py
├── protocol_event_bus_mixin.py
├── protocol_event_bus_service.py
├── protocol_event_bus_types.py
├── protocol_event_bus.py
├── protocol_event_envelope_impl.py
├── protocol_event_envelope.py
├── protocol_event_orchestrator.py
├── protocol_event_publisher.py
├── protocol_kafka_adapter.py
├── protocol_redpanda_adapter.py
└── protocol_schema_registry.py
```

### Type Protocols

```
src/omnibase_spi/protocols/types/
├── protocol_core_types.py
├── protocol_event_bus_types.py
├── protocol_onex_error.py
├── protocol_contract.py
└── ...
```

### Networking Protocols

```
src/omnibase_spi/protocols/networking/
├── protocol_kafka_client.py
├── protocol_kafka_extended.py
└── ...
```

---

**End of Document**
