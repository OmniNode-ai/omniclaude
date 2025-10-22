# OmniNode Bridge Reusable Node Catalog

**Research Date**: 2025-10-22
**Purpose**: Catalog of reusable classes, patterns, and dependencies for ONEX node generation
**Source Repository**: `/Volumes/PRO-G40/Code/omninode_bridge`

---

## Table of Contents

1. [Base Node Classes (omnibase_core)](#1-base-node-classes-omnibase_core)
2. [Mixins (Reusable Components)](#2-mixins-reusable-components)
3. [Service Patterns](#3-service-patterns)
4. [Model Patterns](#4-model-patterns)
5. [Directory Structure Conventions](#5-directory-structure-conventions)
6. [Import Patterns](#6-import-patterns)
7. [Usage Examples by Node Type](#7-usage-examples-by-node-type)

---

## 1. Base Node Classes (omnibase_core)

All ONEX nodes inherit from base classes in the `omnibase_core` package (external dependency).

### 1.1 NodeEffect

**Import Path**: `from omnibase_core.nodes.node_effect import NodeEffect`

**Purpose**: Side effect management node for external interactions (I/O, database, API calls)

**Key Capabilities**:
- Transaction management with rollback support (`ModelEffectTransaction`)
- Retry policies with exponential backoff
- Circuit breaker patterns for failure handling
- Atomic file operations
- Event bus integration

**Stability**: v1.0.0 (stable interface - breaking changes require major version bump)

**Required Method**:
```python
async def execute_effect(self, contract: ModelContractEffect) -> ModelEffectOutput:
    """Execute side effect operation."""
    pass
```

**Key Attributes**:
- `container: ModelONEXContainer` - Dependency injection container
- `active_transactions: dict[UUID, ModelEffectTransaction]` - Active transaction tracking
- `circuit_breakers: dict[str, ModelCircuitBreaker]` - Circuit breaker instances
- `effect_semaphore: asyncio.Semaphore` - Concurrency control

**Example Usage**:
```python
from omnibase_core.nodes.node_effect import NodeEffect
from omnibase_core.models.container.model_onex_container import ModelONEXContainer

class NodeDatabaseWriterEffect(NodeEffect):
    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)
        # Initialize dependencies

    async def execute_effect(self, contract: ModelContractEffect) -> ModelEffectOutput:
        async with self.transaction_manager.begin() as tx:
            # Perform database write
            result = await self._write_data(contract.input_data)
            return ModelEffectOutput(success=True, data=result)
```

---

### 1.2 NodeOrchestrator

**Import Path**: `from omnibase_core.nodes.node_orchestrator import NodeOrchestrator`

**Purpose**: Workflow coordination and control flow management

**Key Capabilities**:
- Workflow coordination with control flow
- Action emission patterns for deferred execution (thunks)
- Conditional branching based on runtime state
- Parallel execution coordination with load balancing
- Dependency-aware execution ordering
- Error recovery and partial failure handling

**Stability**: v1.0.0 (stable interface)

**Required Method**:
```python
async def execute_orchestration(self, contract: ModelContractOrchestrator) -> ModelOrchestratorOutput:
    """Coordinate workflow execution."""
    pass
```

**Key Attributes**:
- `active_workflows: dict[UUID, ModelOrchestratorInput]` - Active workflow tracking
- `workflow_states: dict[UUID, EnumWorkflowState]` - State tracking
- `load_balancer: ModelLoadBalancer` - Load balancing for parallel execution
- `emitted_actions: dict[UUID, list[ModelAction]]` - Emitted actions (thunks)

**Example Usage**:
```python
from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

class NodeWorkflowCoordinatorOrchestrator(NodeOrchestrator):
    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)

    async def execute_orchestration(self, contract: ModelContractOrchestrator) -> ModelOrchestratorOutput:
        # Coordinate multi-step workflow
        workflow_id = uuid4()
        steps = self._plan_workflow(contract)

        # Execute steps with dependency management
        results = await self._execute_steps(steps, workflow_id)

        return ModelOrchestratorOutput(workflow_id=workflow_id, results=results)
```

---

### 1.3 NodeReducer

**Import Path**: `from omnibase_core.nodes.node_reducer import NodeReducer`

**Purpose**: Aggregation, persistence, and state management

**Key Capabilities**:
- Streaming data aggregation with async processing
- Windowed aggregation strategies (tumbling, sliding, session)
- State persistence and recovery
- Conflict resolution with optimistic concurrency control
- Memory-efficient aggregation with backpressure

**Stability**: v1.0.0 (stable interface)

**Required Method**:
```python
async def execute_reduction(self, contract: ModelContractReducer) -> ModelReducerOutput:
    """Execute reduction operation."""
    pass
```

**Key Attributes**:
- `aggregation_state: dict[str, Any]` - In-memory aggregation state
- `window_manager: WindowManager` - Windowing strategy manager
- `conflict_resolver: ModelConflictResolver` - Conflict resolution strategy

**Example Usage**:
```python
from omnibase_core.nodes.node_reducer import NodeReducer

class NodeMetricsAggregatorReducer(NodeReducer):
    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)

    async def execute_reduction(self, contract: ModelContractReducer) -> ModelReducerOutput:
        # Aggregate streaming data
        async for batch in self._stream_data(contract.input_stream):
            aggregated = await self._aggregate_batch(batch)
            await self._persist_state(aggregated)

        return ModelReducerOutput(final_state=self.aggregation_state)
```

---

### 1.4 NodeCompute

**Import Path**: `from omnibase_core.nodes.node_compute import NodeCompute`

**Purpose**: Pure computation and transformation (no side effects)

**Key Capabilities**:
- Pure functional transformations
- Caching with TTL and invalidation strategies
- Algorithm optimization and performance monitoring
- Deterministic computation (same input = same output)

**Stability**: v1.0.0 (stable interface)

**Required Method**:
```python
async def execute_compute(self, contract: ModelContractCompute) -> ModelComputeOutput:
    """Execute pure computation."""
    pass
```

**Key Attributes**:
- `compute_cache: ModelComputeCache` - Result caching
- `performance_monitor: PerformanceMonitor` - Performance tracking

**Example Usage**:
```python
from omnibase_core.nodes.node_compute import NodeCompute

class NodeDataTransformerCompute(NodeCompute):
    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)

    async def execute_compute(self, contract: ModelContractCompute) -> ModelComputeOutput:
        # Pure transformation
        transformed_data = self._transform(contract.input_data)
        return ModelComputeOutput(result=transformed_data)
```

---

## 2. Mixins (Reusable Components)

Mixins provide cross-cutting functionality that can be composed with any node type.

### 2.1 HealthCheckMixin

**Import Path**: `from omninode_bridge.nodes.mixins.health_mixin import HealthCheckMixin, HealthStatus`

**Purpose**: Comprehensive health checking for ONEX nodes

**Key Features**:
- Component-level health checks (database, kafka, external services)
- Status reporting (HEALTHY, DEGRADED, UNHEALTHY, UNKNOWN)
- Docker HEALTHCHECK compatibility
- Prometheus metrics integration
- Async and sync health check methods

**Usage Pattern**:
```python
from omninode_bridge.nodes.mixins.health_mixin import HealthCheckMixin, HealthStatus

class NodeBridgeOrchestrator(NodeOrchestrator, HealthCheckMixin):
    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)
        self.initialize_health_checks()

    def _register_component_checks(self):
        """Register custom health checks."""
        self.register_component_check(
            "metadata_stamping",
            self._check_metadata_stamping_health,
            is_critical=True
        )
        self.register_component_check(
            "kafka",
            self._check_kafka_health,
            is_critical=True
        )

    async def _check_metadata_stamping_health(self) -> ComponentHealth:
        """Check metadata stamping service health."""
        try:
            # Perform health check
            response = await self._http_client.get(f"{self.service_url}/health")
            if response.status_code == 200:
                return ComponentHealth(
                    name="metadata_stamping",
                    status=HealthStatus.HEALTHY,
                    message="Service operational"
                )
        except Exception as e:
            return ComponentHealth(
                name="metadata_stamping",
                status=HealthStatus.UNHEALTHY,
                message=f"Service unavailable: {e}"
            )
```

**Key Methods**:
- `initialize_health_checks()` - Initialize health checking system
- `register_component_check(name, check_fn, is_critical)` - Register component check
- `async check_health()` - Perform all health checks
- `get_health_status()` - Get overall health status
- `to_http_response()` - Convert to HTTP health check response

**Health Status Enum**:
```python
class HealthStatus(Enum):
    HEALTHY = "healthy"      # All components operational
    DEGRADED = "degraded"    # Some non-critical failures
    UNHEALTHY = "unhealthy"  # Critical components failing
    UNKNOWN = "unknown"      # Cannot determine status
```

---

### 2.2 IntrospectionMixin

**Import Path**: `from omninode_bridge.nodes.mixins.introspection_mixin import IntrospectionMixin`

**Purpose**: Node introspection and self-reporting capabilities

**Key Features**:
- Performance-optimized with caching (TTL-based)
- Module-level caching for expensive imports
- Lazy loading with memoization
- FSM state discovery with caching
- Resource usage tracking (CPU, memory, I/O)

**Performance Optimizations**:
- General cache TTL: 60 seconds
- Current state cache TTL: 30 seconds
- Default heartbeat interval: 30 seconds
- Registry listener interval: 60 seconds

**Usage Pattern**:
```python
from omninode_bridge.nodes.mixins.introspection_mixin import IntrospectionMixin

class NodeBridgeOrchestrator(NodeOrchestrator, IntrospectionMixin):
    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)

    async def initialize(self):
        """Initialize node with introspection."""
        await super().initialize()

        # Start introspection heartbeat
        await self.start_introspection_heartbeat(interval_seconds=30)

    async def get_node_info(self) -> dict[str, Any]:
        """Get comprehensive node information."""
        return {
            "node_id": self.node_id,
            "node_type": "orchestrator",
            "current_state": await self.get_current_state(),
            "supported_states": self.get_supported_states(),
            "resource_usage": self.get_resource_usage(),
            "performance_metrics": self.get_performance_metrics()
        }
```

**Key Methods**:
- `async start_introspection_heartbeat(interval_seconds)` - Start periodic reporting
- `async get_current_state()` - Get current FSM state (cached)
- `get_supported_states()` - Get supported FSM states (cached)
- `get_resource_usage()` - Get CPU/memory/I/O usage (requires psutil)
- `get_performance_metrics()` - Get performance statistics

**Introspection Envelope**:
```python
class IntrospectionEnvelope:
    node_id: str
    node_type: str
    timestamp: str
    reason: str  # "heartbeat", "startup", "shutdown", "state_change"
    data: dict[str, Any]
    correlation_id: Optional[str]
```

---

## 3. Service Patterns

### 3.1 EventBusService

**Import Path**: `from omninode_bridge.services.event_bus import EventBusService`

**Purpose**: Event-driven coordination via Kafka

**Key Features**:
- Event publishing with OnexEnvelopeV1 wrapping
- Event subscription with correlation filtering
- Timeout-based event waiting
- Health monitoring and connection management
- Prometheus metrics integration

**Dependencies**:
- `KafkaClient` - Kafka event streaming
- `ModelOnexEnvelopeV1` - Event envelope wrapper

**Usage Pattern**:
```python
from omninode_bridge.services.event_bus import EventBusService
from omninode_bridge.services.kafka_client import KafkaClient

# Initialize
kafka_client = KafkaClient(bootstrap_servers="localhost:29092")
event_bus = EventBusService(kafka_client, node_id="orchestrator", namespace="dev")

# Initialize and start
await event_bus.initialize()

# Publish action event
await event_bus.publish_action_event(
    correlation_id=workflow_id,
    action_data={"operation": "stamp", "file_path": "/path/to/file"}
)

# Wait for completion event
result = await event_bus.wait_for_completion(
    correlation_id=workflow_id,
    timeout_seconds=30
)

# Cleanup
await event_bus.shutdown()
```

**Key Methods**:
- `async initialize()` - Initialize event bus (connect to Kafka)
- `async shutdown()` - Shutdown event bus
- `async publish_action_event(correlation_id, action_data)` - Publish action
- `async wait_for_completion(correlation_id, timeout_seconds)` - Wait for result
- `async subscribe_to_topic(topic, callback)` - Subscribe to events

**Prometheus Metrics**:
- `event_bus_published_total` - Total events published (by event_type)
- `event_bus_consumed_total` - Total events consumed (by event_type)
- `event_bus_timeout_total` - Total event wait timeouts
- `event_bus_wait_time_ms` - Event wait time distribution

---

### 3.2 KafkaClient

**Import Path**: `from omninode_bridge.services.kafka_client import KafkaClient`

**Purpose**: Async Kafka client with resilience patterns

**Key Features**:
- Dead letter queue (DLQ) for failed messages
- Retry with exponential backoff
- Circuit breaker pattern
- Performance optimization (compression, batching, buffering)
- Environment-aware configuration (development/staging/production)

**Configuration Parameters**:
```python
kafka_client = KafkaClient(
    bootstrap_servers="localhost:29092",
    enable_dead_letter_queue=True,
    dead_letter_topic_suffix=".dlq",
    max_retry_attempts=3,
    retry_backoff_base=1.0,
    timeout_seconds=30,
    # Performance tuning
    compression_type="lz4",  # None, gzip, snappy, lz4, zstd
    batch_size=16384,        # Bytes
    linger_ms=10,            # Milliseconds
    buffer_memory=67108864,  # 64MB
    max_request_size=1048576 # 1MB
)
```

**Environment-Based Defaults**:

| Parameter | Development | Staging | Production |
|-----------|-------------|---------|------------|
| compression_type | None | gzip | lz4 |
| linger_ms | 0 | 5 | 10 |
| buffer_memory | 16MB | 32MB | 64MB |
| max_request_size | 256KB | 512KB | 1MB |

**Usage Pattern**:
```python
from omninode_bridge.services.kafka_client import KafkaClient

# Initialize
kafka_client = KafkaClient(bootstrap_servers="localhost:29092")

# Connect
await kafka_client.connect()

# Publish event
await kafka_client.publish(
    topic="workflow.events.v1",
    event={"type": "workflow_started", "workflow_id": str(workflow_id)},
    key=str(workflow_id)
)

# Subscribe to topic
consumer = await kafka_client.create_consumer(
    topics=["workflow.events.v1"],
    group_id="orchestrator-group"
)

# Consume messages
async for message in consumer:
    event = message.value
    # Process event

# Cleanup
await kafka_client.disconnect()
```

**Key Methods**:
- `async connect()` - Connect to Kafka
- `async disconnect()` - Disconnect from Kafka
- `async publish(topic, event, key)` - Publish event
- `async create_consumer(topics, group_id)` - Create consumer
- `is_connected` - Check connection status

**Resilience Features**:
- Dead letter queue for failed messages (automatic retry and DLQ publishing)
- Circuit breaker with exponential backoff
- Automatic topic creation
- Message deduplication tracking

---

### 3.3 PostgresClient

**Import Path**: `from omninode_bridge.services.postgres_client import PostgresClient`

**Purpose**: PostgreSQL connection management with connection pooling

**Key Features**:
- Connection pooling with asyncpg
- Transaction management
- Query execution with prepared statements
- Health checking
- Automatic reconnection on failure

**Usage Pattern**:
```python
from omninode_bridge.services.postgres_client import PostgresClient

# Initialize
postgres_client = PostgresClient(
    host="localhost",
    port=5432,
    database="omninode_bridge",
    user="postgres",
    password="password",
    min_pool_size=10,
    max_pool_size=20
)

# Connect
await postgres_client.connect()

# Execute query
result = await postgres_client.execute(
    "SELECT * FROM workflows WHERE id = $1",
    workflow_id
)

# Execute in transaction
async with postgres_client.transaction() as tx:
    await tx.execute("INSERT INTO workflows (id, state) VALUES ($1, $2)", workflow_id, "running")
    await tx.execute("INSERT INTO workflow_steps (workflow_id, step) VALUES ($1, $2)", workflow_id, "step1")
    # Auto-commit on success, auto-rollback on exception

# Cleanup
await postgres_client.disconnect()
```

---

### 3.4 CanonicalStoreService

**Import Path**: `from omninode_bridge.services.canonical_store import CanonicalStoreService`

**Purpose**: State persistence with optimistic concurrency control

**Key Features**:
- Optimistic concurrency control with version tracking
- Conflict detection and resolution
- Event publishing (StateCommitted, StateConflict)
- PostgreSQL-backed persistence

**Usage Pattern**:
```python
from omninode_bridge.services.canonical_store import CanonicalStoreService

# Initialize
canonical_store = CanonicalStoreService(postgres_client, kafka_client)

# Try to commit state
result = await canonical_store.try_commit(
    workflow_key="workflow-123",
    expected_version=5,
    state_prime={"status": "completed", "result": "success"}
)

if isinstance(result, EventStateCommitted):
    # Success - state persisted
    print(f"State committed with version {result.new_version}")
elif isinstance(result, EventStateConflict):
    # Conflict - version mismatch
    print(f"Conflict: expected {expected_version}, actual {result.actual_version}")
```

---

## 4. Model Patterns

### 4.1 ModelONEXContainer

**Import Path**: `from omnibase_core.models.container.model_onex_container import ModelONEXContainer`

**Purpose**: Dependency injection container for ONEX nodes

**Key Features**:
- Service resolution with caching and logging
- Observable dependency injection with event emission
- Contract-driven automatic service registration
- Workflow orchestration support
- Performance monitoring and caching
- ServiceRegistry integration

**Usage Pattern**:
```python
from omnibase_core.models.container.model_onex_container import ModelONEXContainer

# Create container
container = ModelONEXContainer(
    enable_performance_cache=True,
    enable_service_registry=True
)

# Register services
container.register_service("postgres_client", postgres_client)
container.register_service("kafka_client", kafka_client)
container.register_service("event_bus", event_bus)

# Set configuration
container.config = {
    "metadata_stamping_service_url": "http://metadata-stamping:8053",
    "onextree_service_url": "http://onextree:8058",
    "onextree_timeout_ms": 500.0
}

# Resolve services in nodes
class NodeBridgeOrchestrator(NodeOrchestrator):
    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)

        # Resolve dependencies
        self.kafka_client = container.resolve("kafka_client")
        self.event_bus = container.resolve("event_bus")

        # Access configuration
        self.service_url = container.config.get("metadata_stamping_service_url")
```

**Key Methods**:
- `register_service(name, instance)` - Register service instance
- `resolve(service_name)` - Resolve service by name
- `config` - Configuration dictionary (get/set)

**Performance Metrics**:
- `total_resolutions` - Total service resolutions
- `cache_hit_rate` - Service cache hit rate
- `avg_resolution_time_ms` - Average resolution time
- `error_rate` - Resolution error rate
- `active_services` - Number of active services

---

### 4.2 Contract Models

All ONEX nodes use contract models for input/output specification.

#### ModelContractEffect

**Import Path**: `from omnibase_core.models.contracts.model_contract_effect import ModelContractEffect`

**Purpose**: Contract for Effect nodes (side effects)

**Key Fields**:
```python
class ModelContractEffect(BaseModel):
    name: str                    # Contract name
    version: str                 # Semantic version
    description: str             # Human-readable description
    node_type: Literal["effect"] # Node type

    # Effect-specific
    effect_type: EnumEffectType  # I/O, database, API, file, etc.
    retry_config: Optional[ModelEffectRetryConfig]
    transaction_config: Optional[ModelTransactionConfig]
    external_service_config: Optional[ModelExternalServiceConfig]
```

#### ModelContractOrchestrator

**Import Path**: `from omnibase_core.models.contracts.model_contract_orchestrator import ModelContractOrchestrator`

**Purpose**: Contract for Orchestrator nodes (workflow coordination)

**Key Fields**:
```python
class ModelContractOrchestrator(BaseModel):
    name: str
    version: str
    description: str
    node_type: Literal["orchestrator"]

    # Orchestrator-specific
    workflow_config: Optional[ModelWorkflowConfig]
    branching_config: Optional[ModelBranchingConfig]
    action_emission_config: Optional[ModelActionEmissionConfig]
    parallel_config: Optional[ModelParallelConfig]
```

#### ModelContractReducer

**Import Path**: `from omnibase_core.models.contracts.model_contract_reducer import ModelContractReducer`

**Purpose**: Contract for Reducer nodes (aggregation)

**Key Fields**:
```python
class ModelContractReducer(BaseModel):
    name: str
    version: str
    description: str
    node_type: Literal["reducer"]

    # Reducer-specific
    aggregation_subcontract: Optional[ModelAggregationSubcontract]
    state_management_subcontract: Optional[ModelStateManagementSubcontract]
    fsm_subcontract: Optional[ModelFSMSubcontract]
    streaming_config: Optional[ModelStreamingConfig]
```

#### ModelContractCompute

**Import Path**: `from omnibase_core.models.contracts.model_contract_compute import ModelContractCompute`

**Purpose**: Contract for Compute nodes (pure computation)

**Key Fields**:
```python
class ModelContractCompute(BaseModel):
    name: str
    version: str
    description: str
    node_type: Literal["compute"]

    # Compute-specific
    algorithm_config: Optional[ModelAlgorithmConfig]
    caching_config: Optional[ModelCachingConfig]
    performance_requirements: Optional[ModelPerformanceRequirements]
```

---

### 4.3 Event Models

#### BaseEvent

**Import Path**: `from omninode_bridge.models.events import BaseEvent`

**Purpose**: Base event model for all events

**Structure**:
```python
class BaseEvent(BaseModel):
    id: UUID                      # Unique event identifier
    type: EventType               # Event category
    event: str                    # Specific event name
    service: str                  # Source service name
    timestamp: datetime           # Event timestamp
    correlation_id: Optional[UUID] # Request correlation ID
    metadata: dict[str, Any]      # Event metadata
    payload: dict[str, Any]       # Event-specific data
```

#### ServiceLifecycleEvent

**Import Path**: `from omninode_bridge.models.events import ServiceLifecycleEvent`

**Purpose**: Service lifecycle events (startup, shutdown, health checks)

**Event Types**:
- `STARTUP` - Service starting
- `SHUTDOWN` - Service shutting down
- `HEALTH_CHECK` - Health check performed
- `REGISTRATION` - Service registered
- `DEREGISTRATION` - Service deregistered
- `READY` - Service ready to accept requests
- `ERROR` - Service error occurred

**Example**:
```python
event = ServiceLifecycleEvent(
    event=ServiceEventType.STARTUP,
    service="orchestrator",
    service_version="1.0.0",
    environment="production",
    instance_id="orchestrator-1",
    health_status="healthy",
    dependencies={"postgres": "connected", "kafka": "connected"}
)
```

#### ModelOnexEnvelopeV1

**Import Path**: `from omninode_bridge.nodes.registry.v1_0_0.models.model_onex_envelope_v1 import ModelOnexEnvelopeV1`

**Purpose**: Standard event envelope for all Kafka events

**Structure**:
```python
class ModelOnexEnvelopeV1(BaseModel):
    envelope_version: str = "v1"
    event_id: UUID
    event_type: str
    correlation_id: UUID
    timestamp: datetime
    source_node_id: str
    payload: dict[str, Any]
```

---

## 5. Directory Structure Conventions

All nodes in omninode_bridge follow a consistent directory structure:

```
nodes/
├── <node_name>_<type>/              # e.g., database_adapter_effect
│   ├── __init__.py
│   └── v1_0_0/                      # Semantic versioning
│       ├── __init__.py
│       ├── node.py                  # Main node implementation
│       ├── main.py                  # Standalone entry point (optional)
│       ├── main_standalone.py       # Standalone service (optional)
│       ├── contract.yaml            # Contract specification
│       ├── models/                  # Node-specific models
│       │   ├── __init__.py
│       │   ├── inputs/              # Input models
│       │   │   ├── __init__.py
│       │   │   └── model_*_input.py
│       │   ├── outputs/             # Output models
│       │   │   ├── __init__.py
│       │   │   └── model_*_output.py
│       │   ├── entities/            # Domain entities
│       │   │   ├── __init__.py
│       │   │   └── model_*.py
│       │   └── events/              # Event models
│       │       ├── __init__.py
│       │       └── model_*_event.py
│       └── enums/                   # Enumerations
│           ├── __init__.py
│           └── enum_*.py
```

**Key Conventions**:
- Nodes are organized by type suffix: `*_effect`, `*_orchestrator`, `*_reducer`, `*_compute`
- Semantic versioning with `v1_0_0` directory structure
- `node.py` contains main node class
- `contract.yaml` defines node contract (inputs, outputs, subcontracts)
- Models organized by category (inputs, outputs, entities, events)
- Enums in separate `enums/` directory

---

## 6. Import Patterns

### 6.1 Standard Import Structure

All nodes follow this import pattern:

```python
#!/usr/bin/env python3
"""
Node<Name><Type> - <Brief Description>.

<Detailed description>

ONEX v2.0 Compliance:
- Suffix-based naming: Node<Name><Type>
- Import from omnibase_core infrastructure
- Subcontract composition for <list subcontracts>
- ModelONEXContainer for dependency injection
- Strong typing (no Any types except where needed for flexibility)
"""

# Standard library imports
import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

# Third-party imports
from pydantic import BaseModel, Field

# omnibase_core imports (base classes and infrastructure)
from omnibase_core import EnumCoreErrorCode, ModelOnexError
from omnibase_core.enums.enum_log_level import EnumLogLevel as LogLevel
from omnibase_core.logging.structured import emit_log_event_sync as emit_log_event
from omnibase_core.models.container.model_onex_container import ModelONEXContainer
from omnibase_core.models.contracts.model_contract_<type> import ModelContract<Type>
from omnibase_core.nodes.node_<type> import Node<Type>

# Aliases for compatibility
OnexError = ModelOnexError

# omninode_bridge service imports
from ....services.event_bus import EventBusService
from ....services.kafka_client import KafkaClient

# Mixin imports
from ...mixins.health_mixin import HealthCheckMixin, HealthStatus
from ...mixins.introspection_mixin import IntrospectionMixin

# Node-specific model imports
from .models.enum_* import Enum*
from .models.model_*_input import Model*Input
from .models.model_*_output import Model*Output
```

### 6.2 Relative Import Depth

From node directory (`nodes/<node_name>/<type>/v1_0_0/`):

- Services: `from ....services.<service_name> import <Class>`
- Mixins: `from ...mixins.<mixin_name> import <Mixin>`
- Shared models: `from ....models.<model_name> import <Model>`
- Node models: `from .models.<category>.<model_name> import <Model>`

---

## 7. Usage Examples by Node Type

### 7.1 Effect Node Example

**Real Implementation**: `NodeBridgeRegistry` (Registry Effect)

```python
from omnibase_core.nodes.node_effect import NodeEffect
from omnibase_core.models.container.model_onex_container import ModelONEXContainer
from omnibase_core.models.contracts.model_contract_effect import ModelContractEffect
from omninode_bridge.nodes.mixins.health_mixin import HealthCheckMixin

class NodeBridgeRegistry(NodeEffect, HealthCheckMixin):
    """
    Registry Effect for node discovery and dual registration.

    Listens for introspection events and performs dual registration
    in Consul and PostgreSQL.
    """

    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)

        # Resolve dependencies
        self.kafka_client = container.resolve("kafka_client")
        self.postgres_client = container.resolve("postgres_client")

        # Configuration
        self.consul_url = container.config.get("consul_url", "http://consul:8500")

        # Initialize health checks
        self.initialize_health_checks()

    def _register_component_checks(self):
        """Register health checks for dependencies."""
        self.register_component_check("kafka", self._check_kafka_health, is_critical=True)
        self.register_component_check("postgres", self._check_postgres_health, is_critical=True)
        self.register_component_check("consul", self._check_consul_health, is_critical=False)

    async def execute_effect(self, contract: ModelContractEffect):
        """Execute registration effect."""
        # Listen for introspection events
        async for event in self.kafka_client.consume("node-introspection.v1"):
            await self._register_node(event)

    async def _register_node(self, event):
        """Dual registration in Consul and PostgreSQL."""
        # Extract node info from event
        node_id = event.payload["node_id"]
        node_type = event.payload["node_type"]

        # Register in Consul (service discovery)
        await self._register_in_consul(node_id, node_type)

        # Register in PostgreSQL (tool registry)
        await self._register_in_postgres(node_id, node_type)
```

**Key Patterns**:
- Extends `NodeEffect` and `HealthCheckMixin`
- Resolves dependencies from container
- Implements `execute_effect()` method
- Uses Kafka for event-driven operation
- Dual persistence (Consul + PostgreSQL)

---

### 7.2 Orchestrator Node Example

**Real Implementation**: `NodeBridgeOrchestrator` (Stamping Workflow)

```python
from omnibase_core.nodes.node_orchestrator import NodeOrchestrator
from omnibase_core.models.container.model_onex_container import ModelONEXContainer
from omninode_bridge.services.event_bus import EventBusService
from omninode_bridge.nodes.mixins.health_mixin import HealthCheckMixin
from omninode_bridge.nodes.mixins.introspection_mixin import IntrospectionMixin

class NodeBridgeOrchestrator(NodeOrchestrator, HealthCheckMixin, IntrospectionMixin):
    """
    Bridge Orchestrator for stamping workflow coordination.

    Coordinates multi-step workflows:
    1. Receive stamp request
    2. Route to OnexTree for intelligence (optional)
    3. Execute BLAKE3 hash generation
    4. Create stamp with namespace support
    5. Publish events to Kafka
    6. Transition FSM state
    7. Return stamped content
    """

    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)

        # Resolve dependencies
        self.event_bus: EventBusService = container.resolve("event_bus")
        self.kafka_client = container.resolve("kafka_client")

        # Configuration
        self.metadata_stamping_service_url = container.config.get(
            "metadata_stamping_service_url",
            "http://metadata-stamping:8053"
        )
        self.onextree_service_url = container.config.get(
            "onextree_service_url",
            "http://onextree:8058"
        )
        self.onextree_timeout_ms = container.config.get("onextree_timeout_ms", 500.0)

        # Initialize mixins
        self.initialize_health_checks()

    async def execute_orchestration(self, contract: ModelContractOrchestrator):
        """Coordinate stamping workflow."""
        workflow_id = uuid4()

        # Step 1: Validate input
        await self._validate_stamp_request(contract.input_data)

        # Step 2: Optional OnexTree intelligence
        intelligence = None
        if contract.config.get("enable_intelligence", False):
            intelligence = await self._gather_intelligence(contract.input_data)

        # Step 3: Execute stamping workflow
        result = await self._execute_workflow(workflow_id, contract.input_data, intelligence)

        # Step 4: Publish completion event
        await self.event_bus.publish_action_event(
            correlation_id=workflow_id,
            action_data={"status": "completed", "result": result}
        )

        return ModelOrchestratorOutput(workflow_id=workflow_id, result=result)

    async def _execute_workflow(self, workflow_id, input_data, intelligence):
        """Execute multi-step workflow with FSM state transitions."""
        # Transition: PENDING → PROCESSING
        await self._transition_state(workflow_id, "PENDING", "PROCESSING")

        try:
            # Call metadata stamping service
            stamp_result = await self._call_stamping_service(input_data)

            # Transition: PROCESSING → COMPLETED
            await self._transition_state(workflow_id, "PROCESSING", "COMPLETED")

            return stamp_result

        except Exception as e:
            # Transition: PROCESSING → FAILED
            await self._transition_state(workflow_id, "PROCESSING", "FAILED")
            raise
```

**Key Patterns**:
- Extends `NodeOrchestrator`, `HealthCheckMixin`, `IntrospectionMixin`
- Uses `EventBusService` for event-driven coordination
- FSM state management for workflow tracking
- Optional intelligence gathering integration
- Multi-step workflow orchestration with error handling

---

### 7.3 Reducer Node Example

**Real Implementation**: `NodeBridgeReducer` (Metadata Aggregator)

```python
from omnibase_core.nodes.node_reducer import NodeReducer
from omnibase_core.models.container.model_onex_container import ModelONEXContainer
from omninode_bridge.nodes.mixins.health_mixin import HealthCheckMixin

class NodeBridgeReducer(NodeReducer, HealthCheckMixin):
    """
    Bridge Reducer for stamping metadata aggregation.

    Reduces stamping metadata across workflows, manages FSM state persistence,
    and computes aggregation statistics.
    """

    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)

        # Resolve dependencies
        self.postgres_client = container.resolve("postgres_client")
        self.kafka_client = container.resolve("kafka_client")

        # Aggregation state
        self.namespace_aggregations = defaultdict(lambda: {
            "total_stamps": 0,
            "success_count": 0,
            "failure_count": 0,
            "avg_duration_ms": 0.0
        })

        # Initialize health checks
        self.initialize_health_checks()

    async def execute_reduction(self, contract: ModelContractReducer):
        """Execute reduction operation."""
        # Stream data from Kafka
        async for event in self._stream_workflow_events():
            # Aggregate by namespace
            namespace = event.get("namespace", "default")
            await self._aggregate_event(namespace, event)

            # Persist aggregated state periodically
            if self._should_persist():
                await self._persist_aggregations()

    async def _aggregate_event(self, namespace: str, event: dict):
        """Aggregate single event into namespace statistics."""
        agg = self.namespace_aggregations[namespace]

        # Update counts
        agg["total_stamps"] += 1
        if event.get("status") == "success":
            agg["success_count"] += 1
        else:
            agg["failure_count"] += 1

        # Update rolling average duration
        duration = event.get("duration_ms", 0)
        n = agg["total_stamps"]
        agg["avg_duration_ms"] = (
            (agg["avg_duration_ms"] * (n - 1) + duration) / n
        )

    async def _persist_aggregations(self):
        """Persist aggregated state to PostgreSQL."""
        async with self.postgres_client.transaction() as tx:
            for namespace, agg in self.namespace_aggregations.items():
                await tx.execute(
                    """
                    INSERT INTO namespace_aggregations (namespace, total_stamps, success_count, failure_count, avg_duration_ms)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (namespace) DO UPDATE
                    SET total_stamps = EXCLUDED.total_stamps,
                        success_count = EXCLUDED.success_count,
                        failure_count = EXCLUDED.failure_count,
                        avg_duration_ms = EXCLUDED.avg_duration_ms
                    """,
                    namespace, agg["total_stamps"], agg["success_count"],
                    agg["failure_count"], agg["avg_duration_ms"]
                )
```

**Key Patterns**:
- Extends `NodeReducer` and `HealthCheckMixin`
- Streaming aggregation with async iteration
- In-memory state with periodic persistence
- Namespace-based aggregation (multi-tenancy)
- Rolling average calculation
- Transaction management for atomic persistence

---

### 7.4 Store Effect Node Example (Pure Reducer Pattern)

**Real Implementation**: `NodeStoreEffect` (CQRS Write Path)

```python
from omnibase_core.nodes.node_effect import NodeEffect
from omnibase_core.models.container.model_onex_container import ModelONEXContainer
from omninode_bridge.services.canonical_store import CanonicalStoreService

class NodeStoreEffect(NodeEffect):
    """
    Store Effect Node - Pure persistence layer for workflow state.

    Implements Effect side of Pure Reducer pattern with optimistic
    concurrency control.

    Event Flow:
    1. ReducerService publishes PersistState event → Kafka
    2. NodeStoreEffect subscribes and receives event
    3. Calls canonical_store.try_commit()
    4. Publishes StateCommitted or StateConflict result
    5. Records metrics
    """

    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)

        # Resolve dependencies
        self._postgres_client = container.resolve("postgres_client")
        self._kafka_client = container.resolve("kafka_client")

        # Create canonical store service
        self._canonical_store = CanonicalStoreService(
            self._postgres_client,
            self._kafka_client
        )

        # Metrics
        self.metrics = ModelStoreEffectMetrics()

        # Topics
        self.persist_state_topic = "persist-state.v1"
        self.state_result_topic = "state-result.v1"

    async def execute_effect(self, contract: ModelContractEffect):
        """Execute persistence effect."""
        # Subscribe to PersistState events
        async for event in self._kafka_client.consume(self.persist_state_topic):
            await self._handle_persist_state(event)

    async def _handle_persist_state(self, event: ModelPersistStateEvent):
        """Handle PersistState event."""
        start_time = time.time()

        try:
            # Try to commit state with optimistic concurrency control
            result = await self._canonical_store.try_commit(
                workflow_key=event.workflow_key,
                expected_version=event.expected_version,
                state_prime=event.state_prime
            )

            # Publish result event
            await self._publish_result(result)

            # Record metrics
            duration_ms = (time.time() - start_time) * 1000
            if isinstance(result, EventStateCommitted):
                self.metrics.record_success(duration_ms)
            elif isinstance(result, EventStateConflict):
                self.metrics.record_conflict(duration_ms)

        except Exception as e:
            # Record error metric
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_error(duration_ms)
            raise

    async def _publish_result(self, result):
        """Publish StateCommitted or StateConflict result."""
        await self._kafka_client.publish(
            topic=self.state_result_topic,
            event=result.dict(),
            key=result.workflow_key
        )
```

**Key Patterns**:
- Separates pure reduction (Reducer) from persistence (Effect)
- Event-driven with Kafka (PersistState → StateCommitted/StateConflict)
- Delegates to `CanonicalStoreService` for optimistic concurrency control
- Comprehensive metrics tracking (latency, success/conflict/error rates)
- Performance targets: <10ms p95, >1000 ops/sec, >95% success rate

---

## Summary of Reusable Components

### Import as Dependencies (DO NOT GENERATE)

| Component | Import Path | When to Use |
|-----------|-------------|-------------|
| **Base Classes** | | |
| NodeEffect | `omnibase_core.nodes.node_effect` | All Effect nodes |
| NodeOrchestrator | `omnibase_core.nodes.node_orchestrator` | All Orchestrator nodes |
| NodeReducer | `omnibase_core.nodes.node_reducer` | All Reducer nodes |
| NodeCompute | `omnibase_core.nodes.node_compute` | All Compute nodes |
| **Mixins** | | |
| HealthCheckMixin | `omninode_bridge.nodes.mixins.health_mixin` | All nodes needing health checks |
| IntrospectionMixin | `omninode_bridge.nodes.mixins.introspection_mixin` | All nodes needing self-reporting |
| **Services** | | |
| EventBusService | `omninode_bridge.services.event_bus` | Event-driven coordination |
| KafkaClient | `omninode_bridge.services.kafka_client` | Kafka event streaming |
| PostgresClient | `omninode_bridge.services.postgres_client` | PostgreSQL persistence |
| CanonicalStoreService | `omninode_bridge.services.canonical_store` | Optimistic concurrency control |
| **Models** | | |
| ModelONEXContainer | `omnibase_core.models.container.model_onex_container` | Dependency injection |
| ModelContractEffect | `omnibase_core.models.contracts.model_contract_effect` | Effect node contracts |
| ModelContractOrchestrator | `omnibase_core.models.contracts.model_contract_orchestrator` | Orchestrator contracts |
| ModelContractReducer | `omnibase_core.models.contracts.model_contract_reducer` | Reducer contracts |
| ModelContractCompute | `omnibase_core.models.contracts.model_contract_compute` | Compute contracts |
| BaseEvent | `omninode_bridge.models.events` | Event models |
| ModelOnexEnvelopeV1 | `omninode_bridge.nodes.registry.v1_0_0.models` | Event envelope wrapper |

### Generate for Each Node (Node-Specific)

| Component | Pattern | When to Generate |
|-----------|---------|------------------|
| Input Models | `model_*_input.py` | Node-specific input data structures |
| Output Models | `model_*_output.py` | Node-specific output data structures |
| Entity Models | `model_*.py` in entities/ | Domain entities for the node |
| Event Models | `model_*_event.py` | Node-specific event types |
| Enumerations | `enum_*.py` | Node-specific enums (states, types, etc.) |
| Contract YAML | `contract.yaml` | Node contract specification |
| Main Node File | `node.py` | Main node implementation class |

---

## Next Steps for Node Generation

1. **Analyze User Prompt** → Extract node type, name, purpose, dependencies
2. **Select Base Class** → Effect, Orchestrator, Reducer, or Compute
3. **Select Mixins** → HealthCheckMixin, IntrospectionMixin (if needed)
4. **Identify Service Dependencies** → KafkaClient, PostgresClient, EventBusService, etc.
5. **Generate Node-Specific Models** → Inputs, outputs, entities, events, enums
6. **Generate Contract YAML** → Contract specification with subcontracts
7. **Generate Main Node File** → Implement node class with proper imports
8. **Validate Compliance** → ONEX v2.0 patterns, naming conventions, strong typing

---

**End of Catalog**
