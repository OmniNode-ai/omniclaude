# MVP Event Bus Integration - Design Document

**Goal**: Enable generated ONEX nodes to automatically join the event bus, publish introspection events, and register with Consul for service discovery.

**Status**: Design Phase
**Target**: MVP completion (estimated 1-2 days)
**Current Pipeline**: 7 stages (PRD → Intelligence → Contract → Generation → Validation → Refinement → File Writing)

---

## 1. Architecture Overview

### Current State (omniclaude)
```
User Prompt
    ↓
[Stage 1] PRD Analysis
[Stage 1.5] Intelligence Gathering
[Stage 2] Contract Building + Quorum
[Stage 3] Business Logic Generation
[Stage 4] Template Generation (85% quality)
[Stage 5] Validation
[Stage 5.5] AI Refinement (85% → 95%+)
[Stage 6] File Writing
    ↓
Generated Node (95%+ quality, but no event bus integration)
```

### MVP Target State
```
User Prompt
    ↓
[Stages 1-4] ... (existing pipeline)
[Stage 4.5] 🆕 Event Bus Integration Wiring
    ├─ Add event bus initialization code
    ├─ Add introspection publishing
    ├─ Add startup script
    └─ Add environment configuration
[Stages 5-6] ... (existing stages)
    ↓
Production-Ready Node (auto-joins event bus + Consul registration)
```

---

## 2. Omniarchon Event Bus Pattern Analysis

### 2.1 Node Initialization Pattern (from `node_intelligence_adapter_effect.py`)

```python
class NodeIntelligenceAdapterEffect:
    def __init__(
        self,
        service_url: str = "http://archon-intelligence:8053",
        bootstrap_servers: str = "omninode-bridge-redpanda:9092",
        consumer_config: Optional[ModelKafkaConsumerConfig] = None,
    ):
        # Kafka infrastructure
        self.event_publisher: Optional[EventPublisher] = None
        self.kafka_consumer: Optional[Consumer] = None
        self._event_consumption_task: Optional[asyncio.Task] = None

        # Lifecycle state
        self.is_running = False
        self._shutdown_event = asyncio.Event()

        # Metrics
        self.metrics = {
            "events_consumed": 0,
            "events_processed": 0,
            "events_failed": 0,
            ...
        }

    async def initialize(self) -> None:
        """Initialize Kafka consumer and event publisher."""
        # Step 1: Create Kafka consumer
        consumer_conf = {
            "bootstrap.servers": self.consumer_config.bootstrap_servers,
            "group.id": self.consumer_config.group_id,
            "auto.offset.reset": self.consumer_config.auto_offset_reset,
            "enable.auto.commit": self.consumer_config.enable_auto_commit,
            "client.id": f"intelligence-adapter-{uuid4().hex[:8]}",
        }
        self.kafka_consumer = Consumer(consumer_conf)

        # Step 2: Subscribe to topics
        self.kafka_consumer.subscribe(self.consumer_config.topics)

        # Step 3: Initialize event publisher
        self.event_publisher = EventPublisher(
            bootstrap_servers=self.bootstrap_servers,
            service_name="archon-intelligence",
            instance_id=f"intelligence-adapter-{uuid4().hex[:8]}",
            max_retries=3,
            enable_dlq=True,
        )

        # Step 4: Publish introspection event (INFERRED - need to verify)
        # await self._publish_introspection_event()

        # Step 5: Start background consumption loop
        self._event_consumption_task = asyncio.create_task(
            self._consume_events_loop()
        )

        self.is_running = True

    async def shutdown(self) -> None:
        """Graceful shutdown with offset commit."""
        self._shutdown_event.set()
        if self._event_consumption_task:
            await asyncio.wait_for(self._event_consumption_task, timeout=30.0)
        if self.kafka_consumer:
            self.kafka_consumer.commit()
            self.kafka_consumer.close()
        if self.event_publisher:
            await self.event_publisher.close()
```

**Key Pattern**: Node has `initialize()` and `shutdown()` lifecycle methods that manage event bus connection.

---

## 3. Required Components for Generated Nodes

### 3.1 EventPublisher Integration

**From**: `/Volumes/PRO-G40/Code/omniarchon/python/src/events/publisher/event_publisher.py`

```python
class EventPublisher:
    """Base event publisher with retry, circuit breaker, and validation."""

    def __init__(
        self,
        bootstrap_servers: str,
        service_name: str,
        instance_id: str,
        max_retries: int = 3,
        enable_dlq: bool = True,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.service_name = service_name
        self.instance_id = instance_id

        # Kafka producer
        self.producer = Producer({
            'bootstrap.servers': bootstrap_servers,
            'client.id': f"{service_name}-{instance_id}",
        })

        # Metrics
        self.events_published = 0
        self.publish_failures = 0

    async def publish(
        self,
        event_type: str,
        payload: dict,
        correlation_id: UUID,
        topic: Optional[str] = None,
    ) -> bool:
        """Publish event with retry and validation."""
        envelope = ModelEventEnvelope(
            event_type=event_type,
            correlation_id=correlation_id,
            payload=payload,
            source=ModelEventSource(
                service_name=self.service_name,
                instance_id=self.instance_id,
            ),
            metadata=ModelEventMetadata(...),
        )

        # Publish to Kafka
        topic = topic or self._derive_topic(event_type)
        self.producer.produce(topic, value=envelope.model_dump_json())
        self.producer.flush()

        return True
```

### 3.2 Introspection Event Pattern

**From**: `omnibase_core/mixins/mixin_introspection_publisher.py`

```python
class MixinIntrospectionPublisher:
    """Mixin for introspection publishing capabilities."""

    def _publish_introspection_event(self) -> None:
        """Publish NODE_INTROSPECTION_EVENT for automatic service discovery."""
        introspection_data = self._gather_introspection_data()

        introspection_event = ModelNodeIntrospectionEvent.create_from_node_info(
            node_id=self._node_id,
            node_name=introspection_data.node_name,
            version=introspection_data.version,
            actions=introspection_data.capabilities.actions,
            protocols=introspection_data.capabilities.protocols,
            metadata=introspection_data.capabilities.metadata,
            tags=introspection_data.tags,
            health_endpoint=introspection_data.health_endpoint,
            correlation_id=uuid4(),
        )

        self.event_bus.publish(introspection_event)
```

**Introspection Event Structure**:
```python
class ModelNodeIntrospectionEvent(BaseModel):
    node_id: UUID
    node_name: str                  # e.g., "NodePostgresqlWriterEffect"
    version: str                    # e.g., "1.0.0"
    capabilities: ModelNodeCapabilities
        actions: List[str]          # e.g., ["execute_effect", "validate_input"]
        protocols: List[str]        # e.g., ["http", "kafka"]
        metadata: Dict[str, Any]    # e.g., {"node_type": "effect", "domain": "database"}
    tags: List[str]                # e.g., ["postgresql", "database", "writer"]
    health_endpoint: str           # e.g., "/health"
    correlation_id: UUID
```

**Registry/Consul Integration** (INFERRED):
- Registry service listens for `NODE_INTROSPECTION_EVENT`
- Extracts node metadata (name, version, capabilities, health endpoint)
- Registers node in Consul with service discovery metadata
- Enables other services to discover and invoke the node

---

## 4. Stage 4.5: Event Bus Integration Template

### 4.1 What to Generate

For each generated node, add:

#### A. Event Bus Initialization Code (in `__init__`)
```python
class Node{Name}{Type}:
    def __init__(self, config: ModelConfig, ...):
        # Existing initialization
        ...

        # 🆕 Event bus infrastructure
        self.event_publisher: Optional[EventPublisher] = None
        self._bootstrap_servers = os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS",
            "omninode-bridge-redpanda:9092"
        )
        self._service_name = "{service_name}"
        self._instance_id = f"{node_name}-{uuid4().hex[:8]}"
        self._node_id = uuid4()

        # Lifecycle state
        self.is_running = False
        self._shutdown_event = asyncio.Event()
```

#### B. Initialize Method
```python
    async def initialize(self) -> None:
        """Initialize event bus connection and publish introspection event."""
        # Initialize event publisher
        self.event_publisher = EventPublisher(
            bootstrap_servers=self._bootstrap_servers,
            service_name=self._service_name,
            instance_id=self._instance_id,
            max_retries=3,
            enable_dlq=True,
        )

        logger.info(f"Event publisher initialized | service={self._service_name}")

        # Publish introspection event for Consul registration
        await self._publish_introspection_event()

        self.is_running = True
        logger.info(f"Node {self._service_name} initialized and registered")

    def _publish_introspection_event(self) -> None:
        """Publish NODE_INTROSPECTION_EVENT for service discovery."""
        introspection_event = ModelNodeIntrospectionEvent(
            node_id=self._node_id,
            node_name="{NodeName}{Type}",
            version="{version}",
            capabilities=ModelNodeCapabilities(
                actions=["execute_{node_type}", "validate_input"],
                protocols=["http", "kafka"],
                metadata={
                    "node_type": "{node_type}",
                    "domain": "{domain}",
                    "service_name": "{service_name}",
                },
            ),
            tags=["{domain}", "{node_type}", "{service_name}"],
            health_endpoint="/health",
            correlation_id=uuid4(),
        )

        self.event_publisher.publish(
            event_type="omninode.discovery.node_introspection.v1",
            payload=introspection_event.model_dump(),
            correlation_id=introspection_event.correlation_id,
        )

        logger.info(f"Published introspection event | node_id={self._node_id}")

    async def shutdown(self) -> None:
        """Graceful shutdown with cleanup."""
        logger.info(f"Shutting down {self._service_name}...")

        self._shutdown_event.set()
        self.is_running = False

        if self.event_publisher:
            await self.event_publisher.close()

        logger.info(f"{self._service_name} shutdown complete")
```

#### C. Startup Script (`start_node.py`)
```python
#!/usr/bin/env python3
"""
Startup script for {NodeName}{Type}

Initializes node and connects to event bus for service discovery.
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from node import Node{Name}{Type}
from models.model_{name}_config import Model{Name}Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Main startup routine."""
    # Load configuration
    config = Model{Name}Config(
        # Load from environment or defaults
    )

    # Create node instance
    node = Node{Name}{Type}(config=config)

    # Initialize event bus connection
    await node.initialize()

    logger.info(f"✅ {node._service_name} started and registered with Consul")
    logger.info(f"   Node ID: {node._node_id}")
    logger.info(f"   Instance ID: {node._instance_id}")

    # Setup signal handlers for graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, initiating shutdown...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait for shutdown signal
    await shutdown_event.wait()

    # Graceful shutdown
    await node.shutdown()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
```

#### D. Environment Configuration (`.env.template`)
```bash
# Event Bus Configuration
KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092
KAFKA_CONSUMER_GROUP={service_name}_consumers
KAFKA_AUTO_OFFSET_RESET=latest

# Service Configuration
SERVICE_NAME={service_name}
SERVICE_VERSION={version}
SERVICE_PORT=8000

# Logging
LOG_LEVEL=INFO
```

#### E. Docker Compose Entry (optional)
```yaml
  node-{service_name}-{node_type}:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      - KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092
      - SERVICE_NAME={service_name}
    depends_on:
      - omninode-bridge-redpanda
      - consul
    networks:
      - omninode-network
```

---

## 5. Orchestrator/Reducer Event Bus Patterns

### 5.1 Orchestrator Pattern (from `workflow_node.py`)

**Key Differences from Effect Nodes**:
1. Uses **LlamaIndex Workflows** for event-driven orchestration
2. Uses **ModelONEXContainer** for dependency injection
3. Uses **KafkaClient** instead of EventPublisher
4. Publishes workflow completion events

```python
class NodeBridgeWorkflowOrchestrator(Workflow):
    """LlamaIndex Workflow-based orchestrator."""

    def __init__(
        self,
        container: ModelONEXContainer,
        timeout: int = 60,
        verbose: bool = True,
    ):
        """Initialize with ONEX container."""
        super().__init__(timeout=timeout, verbose=verbose)

        self.container = container
        self.kafka_broker_url = container.config.get(
            "kafka_broker_url", "localhost:9092"
        )

        # Get KafkaClient from container
        self.kafka_client = container.get_service("kafka_client")

        if self.kafka_client is None:
            from services.kafka_client import KafkaClient

            self.kafka_client = KafkaClient(
                bootstrap_servers=self.kafka_broker_url,
                enable_dead_letter_queue=True,
                max_retry_attempts=3,
                timeout_seconds=30,
            )
            container.register_service("kafka_client", self.kafka_client)

    @step
    async def validate_input(self, event: StartEvent) -> ValidationCompletedEvent:
        """Validate input and initialize context."""
        # Validation logic
        return ValidationCompletedEvent(...)

    @step
    async def complete_workflow(self, event: PersistenceCompletedEvent) -> StopEvent:
        """Publish workflow completion event."""
        # Publish to Kafka
        await self.kafka_client.publish_event(
            topic="omninode.bridge.workflow.completed.v1",
            event_type="WORKFLOW_COMPLETED",
            payload={
                "workflow_id": self.correlation_id,
                "result": event.result,
            },
        )

        return StopEvent(result=event.result)
```

**Orchestrator Template Requirements**:
- Inherit from `LlamaIndex.Workflow`
- Accept `ModelONEXContainer` in `__init__`
- Use `@step` decorator for workflow steps
- Publish completion events via `KafkaClient`
- Maintain workflow context with correlation ID

### 5.2 Reducer Pattern (from omninode_bridge)

**Reducer Characteristics**:
1. Aggregates multiple events into state
2. Persists aggregated state
3. Publishes state change events
4. Typically subscribes to multiple topics

```python
class NodeAggregationReducer:
    """Reducer node for state aggregation."""

    def __init__(
        self,
        container: ModelONEXContainer,
        topics: List[str],
        aggregation_window_ms: int = 5000,
    ):
        """Initialize reducer with event subscriptions."""
        self.container = container
        self.topics = topics
        self.aggregation_window_ms = aggregation_window_ms

        # State management
        self.aggregated_state: Dict[str, Any] = {}
        self.event_buffer: List[Any] = []

        # Kafka infrastructure
        self.kafka_client = container.get_service("kafka_client")
        self.event_consumer = None

    async def initialize(self) -> None:
        """Initialize Kafka consumer and start aggregation loop."""
        # Subscribe to multiple topics
        self.event_consumer = await self.kafka_client.create_consumer(
            topics=self.topics,
            group_id=f"reducer-{self.__class__.__name__}",
        )

        # Start aggregation loop
        self._aggregation_task = asyncio.create_task(
            self._aggregation_loop()
        )

        # Publish introspection event
        await self._publish_introspection_event()

    async def _aggregation_loop(self) -> None:
        """Consume events and aggregate state."""
        while not self._shutdown_event.is_set():
            # Consume events
            events = await self.event_consumer.poll(
                timeout_ms=self.aggregation_window_ms
            )

            # Aggregate
            for event in events:
                await self._reduce_event(event)

            # Publish aggregated state
            if self.aggregated_state:
                await self._publish_state_update()

    async def _reduce_event(self, event: Any) -> None:
        """Reduce event into aggregated state."""
        # Aggregation logic (sum, count, merge, etc.)
        pass

    async def _publish_state_update(self) -> None:
        """Publish aggregated state change event."""
        await self.kafka_client.publish_event(
            topic="omninode.reducer.state_updated.v1",
            event_type="STATE_UPDATED",
            payload={
                "aggregate_id": self.aggregate_id,
                "state": self.aggregated_state,
                "event_count": len(self.event_buffer),
            },
        )
```

**Reducer Template Requirements**:
- Multiple topic subscriptions
- Event buffering and aggregation window
- State persistence logic
- State change event publishing
- Aggregation loop with graceful shutdown

---

## 6. Implementation Plan

### Phase 1: Template Additions (4-6 hours)
1. **Create event bus template snippets**:
   - `event_bus_init_effect.py.jinja2` - Effect node initialization
   - `event_bus_init_orchestrator.py.jinja2` - Orchestrator node initialization
   - `event_bus_init_reducer.py.jinja2` - Reducer node initialization
   - `event_bus_lifecycle.py.jinja2` - initialize/shutdown methods
   - `introspection_event.py.jinja2` - introspection publishing
   - `startup_script.py.jinja2` - node startup script

2. **Update existing templates by node type**:

   **Effect Nodes**:
   - Add EventPublisher field to `__init__`
   - Add `initialize()` and `shutdown()` methods
   - Add `_publish_introspection_event()` method

   **Compute Nodes** (optional event bus):
   - Minimal event integration (optional)
   - Can be invoked synchronously or via events

   **Orchestrator Nodes**:
   - Inherit from `LlamaIndex.Workflow`
   - Add `ModelONEXContainer` to `__init__`
   - Add `KafkaClient` initialization
   - Add workflow completion event publishing
   - Add `@step` decorator to workflow steps

   **Reducer Nodes**:
   - Add multi-topic subscription logic
   - Add event buffer and aggregation window
   - Add `_aggregation_loop()` method
   - Add state persistence logic
   - Add state change event publishing

3. **Add Stage 4.5 to pipeline** (`generation_pipeline.py:800-900`):
   ```python
   async def _stage_4_5_event_bus_integration(
       self,
       generation_result: Dict[str, Any],
       parsed_data: Dict[str, Any],
   ) -> Tuple[PipelineStage, Dict[str, Any]]:
       """Stage 4.5: Add event bus integration to generated node."""
       # Inject event bus code into node.py
       # Generate startup script
       # Generate .env.template
       # Return updated generation_result
   ```

### Phase 2: Testing (2-3 hours)
1. **Unit tests**: Test event bus code generation
2. **Integration test**: Generate PostgreSQL writer node
3. **E2E test**:
   - Start Redpanda (Kafka)
   - Start Registry service
   - Generate and start node
   - Verify introspection event published
   - Verify Consul registration
   - Verify node responds to health checks

### Phase 3: Self-Hosting (4-6 hours)
1. **Generate generation pipeline nodes**:
   - NodePRDAnalyzerCompute
   - NodeIntelligenceGathererEffect
   - NodeContractBuilderCompute
   - NodeCodeGeneratorEffect
   - NodeValidatorCompute
   - NodeCodeRefinerEffect
   - NodeFileWriterEffect

2. **Wire event-driven pipeline**:
   - Subscribe to `NODE_GENERATION_REQUESTED` events
   - Publish `NODE_GENERATION_COMPLETED` events
   - Each stage becomes a separate node

3. **Deploy next-gen pipeline**:
   - Deploy generated nodes to Kubernetes
   - Configure event routing
   - Validate self-hosted generation works

---

## 6. Success Criteria

### MVP (1-2 days)
- [ ] Generated nodes have `initialize()` and `shutdown()` methods
- [ ] Nodes publish introspection events on startup
- [ ] Startup script generated automatically
- [ ] Can generate PostgreSQL writer node that auto-registers
- [ ] Node appears in Consul after startup

### Self-Hosting (Additional 1 week)
- [ ] All 7 pipeline stages converted to ONEX nodes
- [ ] Event-driven pipeline generates nodes
- [ ] Self-hosted pipeline generates next version of itself
- [ ] Performance parity with monolithic pipeline (<10s generation)

---

## 7. Dependencies

### Required Infrastructure
- ✅ Redpanda (Kafka) - already in omniarchon
- ✅ Consul - already in omniarchon
- ✅ EventPublisher - already in omniarchon
- ❓ Registry Service - need to verify exists

### Required Libraries (add to pyproject.toml)
```toml
[tool.poetry.dependencies]
confluent-kafka = "^2.3.0"
```

### Required Models (copy from omniarchon)
- `ModelEventEnvelope`
- `ModelNodeIntrospectionEvent`
- `ModelNodeCapabilities`

---

## 8. Open Questions

1. **Does omniarchon registry service listen for NODE_INTROSPECTION_EVENT?**
   - Need to verify registry service implementation
   - Confirm event type and topic naming

2. **What's the Consul registration format?**
   - What metadata fields are required?
   - How does service discovery query work?

3. **Do we need MixinIntrospectionPublisher or inline implementation?**
   - Mixin requires omnibase_core dependency
   - Inline gives us full control and no external deps

4. **Should Stage 4.5 run before or after Stage 5 (validation)?**
   - Before: Event bus code gets validated and refined
   - After: Keeps validation focused on core logic

**Recommendation**: Run Stage 4.5 BEFORE Stage 5, so event bus code is validated and refined.

---

## 9. Next Steps

1. **Verify omniarchon registry service** - confirm introspection event handling
2. **Create template snippets** - event bus initialization code
3. **Implement Stage 4.5** - event bus integration pipeline stage
4. **Test with PostgreSQL writer** - end-to-end MVP validation
5. **Commit MVP** - Stage 4.5 event bus integration v1.0

**Estimated Timeline**: 1-2 days for MVP, 1 week for self-hosting

---

## 10. Long-Term Vision: Self-Hosting

Once MVP is complete, we can decompose the generation pipeline into 7 ONEX nodes:

```
[User Prompt]
    ↓ (publish NODE_GENERATION_REQUESTED event)
    ↓
[NodePRDAnalyzerCompute]
    ↓ (publish PRD_ANALYZED event)
    ↓
[NodeIntelligenceGathererEffect]
    ↓ (publish INTELLIGENCE_GATHERED event)
    ↓
[NodeContractBuilderCompute]
    ↓ (publish CONTRACT_BUILT event)
    ↓
[NodeCodeGeneratorEffect]
    ↓ (publish CODE_GENERATED event)
    ↓
[NodeValidatorCompute]
    ↓ (publish VALIDATION_COMPLETED event)
    ↓
[NodeCodeRefinerEffect]
    ↓ (publish CODE_REFINED event)
    ↓
[NodeFileWriterEffect]
    ↓ (publish NODE_GENERATION_COMPLETED event)
    ↓
[Generated ONEX Node] (auto-registers with Consul)
```

**The system generates the next generation of itself.** 🚀

---

**Document Status**: Design Complete - Ready for Implementation Review
**Next Action**: Review with user, then implement Stage 4.5
