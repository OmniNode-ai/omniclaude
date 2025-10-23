# Archetypal Node Patterns - Reference Examples

**Date**: 2025-10-22
**Purpose**: Document archetypal node patterns found in omninode_bridge and omniagent for contract-driven generation system

## Overview

Node types in ONEX are **architectural archetypes**, not domain-specific implementations. You don't create multiple Effect nodes per domain - you create **one Effect archetype** (e.g., `DatabaseNode`) that gets reused across workflows.

### The 4 Archetypal Node Types

1. **Effect Node** - External I/O, side effects, API calls
2. **Compute Node** - Pure computation, stateless, no side effects
3. **Reducer Node** - State management, aggregation
4. **Orchestrator Node** - Workflow coordination, handles multiple workflows

---

## Important: Code Standards Context

**The examples documented below are from older implementations and may not be completely up to current ONEX v2.0 standards.**

When implementing the Week 4 generation system:

1. **Use these examples for pattern reference only** - They illustrate architectural patterns and node type characteristics
2. **Update to current ONEX v2.0 standards**:
   - Latest contract patterns and model definitions
   - Current naming conventions (e.g., `Node<Name><Type>` format)
   - Updated base class implementations
   - Modern dependency injection patterns
3. **Validate all generated code against 23 quality gates** (see `quality-gates-spec.yaml`)
4. **Reference latest omnibase_core patterns** for current implementation standards
5. **Apply quality compliance gates** (QC-001 through QC-004) to ensure ONEX architectural compliance

The value of these examples is in understanding **how archetypes work**, not in copying code verbatim.

---

## 1. Effect Node Archetype: Database Adapter

**File**: `/Volumes/PRO-G40/Code/omninode_bridge/src/omninode_bridge/nodes/database_adapter_effect/v1_0_0/node.py`

### Key Characteristics

```python
class NodeBridgeDatabaseAdapterEffect(NodeEffect):
    """
    Effect node for external database operations.

    Characteristics:
    - Inherits from NodeEffect base class
    - Performs external I/O (PostgreSQL operations)
    - Has side effects (INSERT, UPDATE, UPSERT)
    - Uses circuit breaker for resilience
    - Contract-driven dependency injection
    """
```

### What Makes This an Effect Node

1. **External I/O**: Connects to PostgreSQL database
2. **Side Effects**: INSERT/UPDATE/DELETE operations modify external state
3. **Contract-Based**: Uses `ModelContractEffect` for input/output
4. **Dependency Injection**: Resolves dependencies via container
5. **Circuit Breaker**: Handles external system failures gracefully
6. **Event Consumption**: Consumes Kafka events (external system)

### Key Methods

```python
async def initialize(self) -> None:
    """Resolve dependencies and test database connectivity."""
    self._connection_manager = self.container.get_service("postgres_connection_manager")
    self._query_executor = self.container.get_service("postgres_query_executor")
    self._transaction_manager = self.container.get_service("postgres_transaction_manager")

    # Test database connectivity (external system check)
    await self._circuit_breaker.execute(
        self._connection_manager.execute_query, "SELECT 1", []
    )

async def process(
    self, input_data: ModelDatabaseOperationInput
) -> ModelDatabaseOperationOutput:
    """Process database operation (external I/O)."""
    # Routes to appropriate handler based on operation type
    # Executes SQL against PostgreSQL (side effect)
    # Returns operation result
```

### Effect Node Pattern Summary

```python
# Effect Node Template
class NodeXxxEffect(NodeEffect):
    def __init__(self, container: ModelContainer):
        super().__init__(container)
        # External dependencies (resolved via container)
        self._external_client = None
        self._circuit_breaker = None

    async def initialize(self) -> None:
        """Resolve external dependencies and test connectivity."""
        self._external_client = self.container.get_service("external_client")
        self._circuit_breaker = CircuitBreaker(...)
        # Test external system connectivity

    async def process(self, input_data) -> output_data:
        """Perform external I/O operation."""
        # Execute through circuit breaker
        result = await self._circuit_breaker.execute(
            self._external_client.perform_operation, input_data
        )
        return result
```

**Use Cases**: Database operations, API calls, file I/O, message queue publishing, external service integration

---

## 2. Compute Node Archetype: LLM Inference

**File**: `/Volumes/PRO-G40/Code/omniagent/archived/src/omni_agent/workflow/nodes/llm_inference.py`

### Key Characteristics

```python
class LLMInferenceNode(BaseWorkflowNode):
    """
    Compute node for LLM inference.

    Characteristics:
    - Pure computation (input → LLM → output)
    - Stateless (no state modification)
    - No side effects (reads but doesn't write)
    - Can be cached (same input = same output)
    - Performance monitored
    """
```

### What Makes This a Compute Node

1. **Pure Computation**: Takes prompt, returns response
2. **Stateless**: No internal state modification
3. **No Side Effects**: Doesn't write to database, doesn't publish events
4. **Deterministic**: Same input produces similar output (with temperature control)
5. **Cacheable**: Response can be cached for performance
6. **Performance Monitored**: Uses `@monitor_performance` decorator

### Key Methods

```python
@monitor_performance("llm_inference")
@circuit_breaker("ollama_api", ...)
async def _call_ollama_api(
    self, model_name: str, prompt: str, options: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Pure LLM inference call.

    Input: prompt + options
    Process: LLM computation
    Output: response text

    No state changes, no side effects.
    """
    ollama_request = {
        "model": model_name,
        "prompt": prompt,
        "options": options,
        "stream": False,
    }

    response = await self.http_client.post(
        f"{self.ollama_base_url}/api/generate", json=ollama_request
    )

    result = response.json()
    return result  # Pure output, no side effects

async def execute(self, state: WorkflowState) -> Dict[str, Any]:
    """Execute LLM inference computation."""
    result = await self._call_ollama_api(
        model_name=model_name,
        prompt=state["current_prompt"],
        options=model_options,
    )

    # Return computed result (no state mutation)
    return {
        "llm_response": result.get("response", ""),
        "llm_metadata": {...},
    }
```

### Compute Node Pattern Summary

```python
# Compute Node Template
class NodeXxxCompute(NodeCompute):
    """Pure computation node - no side effects, no state changes."""

    async def compute(self, input_data) -> output_data:
        """
        Pure computation: input → transform → output

        Rules:
        - NO database writes
        - NO event publishing
        - NO state modification
        - NO external side effects

        Can:
        - Read from cache
        - Call external APIs for data (read-only)
        - Perform transformations
        - Return computed results
        """
        # Transform input
        result = self._transform(input_data)

        # Return pure output
        return result

    def _transform(self, data):
        """Pure transformation function."""
        # Pure logic here
        return transformed_data
```

**Use Cases**: Validation, hashing, parsing, transformation, LLM inference, calculation, filtering, mapping

---

## 3. Reducer Node Archetype: State Aggregator

**File**: `/Volumes/PRO-G40/Code/omninode_bridge/src/omninode_bridge/nodes/reducer/v1_0_0/node.py`

### Key Characteristics

```python
class NodeBridgeReducer(NodeReducer):
    """
    Reducer node for state aggregation.

    Characteristics:
    - Manages state (aggregation buffer, FSM states)
    - Aggregates data over time (windowing)
    - Uses FSM for state transitions
    - Returns intents for side effects (separation of concerns)
    - Pure computation with deferred I/O
    """
```

### What Makes This a Reducer Node

1. **State Management**: Maintains `_aggregation_buffer` and `_fsm_manager`
2. **Aggregation**: Combines multiple inputs into aggregated state
3. **Streaming**: Processes data streams with windowing
4. **FSM Integration**: Tracks workflow states and transitions
5. **Intent-Based I/O**: Returns intents instead of performing I/O directly
6. **Batch Processing**: Handles large datasets efficiently

### Key Methods

```python
async def execute_reduction(
    self, contract: ModelContractReducer
) -> ModelReducerOutputState:
    """
    Pure metadata aggregation and state reduction.

    PURE FUNCTION - NO I/O OPERATIONS
    Returns intents for side effects.
    """
    # Initialize intents list for deferred side effects
    intents: list[ModelIntent] = []

    # Initialize aggregation state (in-memory)
    aggregated_data: dict[str, dict[str, Any]] = defaultdict(dict)
    fsm_states: dict[str, str] = {}

    # Stream and aggregate data (pure computation)
    async for metadata_batch in self._stream_metadata(contract, batch_size):
        for metadata in metadata_batch:
            # Group by namespace
            namespace = metadata.namespace

            # Update aggregations (in-memory)
            aggregated_data[namespace]["total_stamps"] += 1
            aggregated_data[namespace]["total_size_bytes"] += metadata.file_size

            # Track FSM state (in-memory)
            workflow_id = metadata.workflow_id
            if self._fsm_manager.get_state(workflow_id) is None:
                await self._fsm_manager.initialize_workflow(
                    workflow_id=workflow_id,
                    initial_state=metadata.workflow_state,
                )

            # Store state in output
            fsm_states[str(workflow_id)] = workflow_state

        # Intent: Batch processed event (deferred)
        intents.append(
            ModelIntent(
                intent_type="PublishEvent",
                target="event_bus",
                payload={...},
            )
        )

    # Intent: Persist aggregated state (deferred)
    intents.append(
        ModelIntent(
            intent_type="PersistState",
            target="store_effect",
            payload={"aggregated_data": dict(aggregated_data)},
        )
    )

    # Return aggregation results with intents
    return ModelReducerOutputState(
        aggregations=dict(aggregated_data),
        fsm_states=fsm_states,
        intents=intents,  # Side effects deferred to Effect nodes
    )
```

### FSM State Manager

```python
class FSMStateManager:
    """
    FSM State Manager for Workflow State Tracking.

    Features:
    - State transition validation
    - PostgreSQL persistence (via intents)
    - State recovery
    - Transition history tracking
    """

    async def initialize_workflow(
        self, workflow_id: UUID, initial_state: str = "PENDING"
    ) -> bool:
        """Initialize workflow in FSM."""
        self._state_cache[workflow_id] = {
            "current_state": normalized_state,
            "previous_state": None,
            "transition_count": 0,
            "metadata": metadata or {},
        }
        return True

    async def transition_state(
        self, workflow_id: UUID, from_state: str, to_state: str
    ) -> bool:
        """Transition workflow with validation."""
        # Validate transition
        if not self._validate_transition(from_state, to_state):
            return False

        # Record transition
        self._transition_history[workflow_id].append({
            "from_state": from_state,
            "to_state": to_state,
            "timestamp": datetime.now(UTC),
        })

        # Update state (in-memory)
        self._state_cache[workflow_id]["current_state"] = to_state

        # Persist via intent (deferred)
        await self._persist_state_transition(workflow_id, transition_record)

        return True
```

### Reducer Node Pattern Summary

```python
# Reducer Node Template
class NodeXxxReducer(NodeReducer):
    """State aggregation and management node."""

    def __init__(self, container: ModelContainer):
        super().__init__(container)
        # State management
        self._aggregation_buffer = defaultdict(dict)
        self._fsm_manager = FSMStateManager(container, fsm_config)

    async def execute_reduction(
        self, contract: ModelContractReducer
    ) -> ModelReducerOutputState:
        """
        Pure aggregation - returns intents for I/O.

        Pattern:
        1. Stream input data
        2. Aggregate in memory
        3. Update FSM states (in-memory)
        4. Generate intents for side effects
        5. Return aggregated state + intents
        """
        intents = []
        aggregated_data = defaultdict(dict)

        # Stream and aggregate (pure)
        async for batch in self._stream_data(contract):
            for item in batch:
                # Aggregate (in-memory)
                aggregated_data[key][metric] += item.value

                # Track state (in-memory)
                await self._fsm_manager.transition_state(...)

        # Intent: Persist state (deferred)
        intents.append(ModelIntent(
            intent_type="PersistState",
            target="store_effect",
            payload={"aggregated_data": dict(aggregated_data)},
        ))

        return ModelReducerOutputState(
            aggregations=dict(aggregated_data),
            intents=intents,
        )
```

**Use Cases**: Session management, state aggregation, event sourcing, metrics collection, cache management, workflow state tracking

---

## 4. Orchestrator Node Archetype: Workflow Coordinator

**File**: `/Volumes/PRO-G40/Code/omninode_bridge/src/omninode_bridge/nodes/orchestrator/v1_0_0/node.py`

**IMPORTANT - Modern Architecture Only**:
- **Event-driven only** - No legacy/fallback modes
- **LlamaIndex Workflows required** - All orchestration via `@step` decorators
- **EventBus required** - Kafka integration is mandatory, not optional
- **Clean slate** - No backward compatibility cruft

The reference implementation in omninode_bridge may contain legacy patterns. For new implementations, **use event-driven architecture exclusively**.

### Key Characteristics

```python
class NodeBridgeOrchestrator(NodeOrchestrator, HealthCheckMixin, IntrospectionMixin):
    """
    Bridge Orchestrator for stamping workflow coordination.

    Characteristics:
    - Inherits from NodeOrchestrator base class
    - Coordinates multi-step workflows (OnexTree → Hash → Stamp → Events)
    - Event-driven coordination via EventBus
    - FSM-driven state management
    - Service routing and delegation
    - Dual execution modes (event-driven + legacy fallback)
    - Health monitoring across multiple services
    - Lifecycle management (startup/shutdown)
    """
```

### What Makes This an Orchestrator Node

1. **Workflow Coordination**: Manages multi-step workflows with multiple services
2. **Event-Driven**: Uses EventBus for async coordination with reducer nodes
3. **FSM State Management**: Tracks workflow states (PENDING → PROCESSING → COMPLETED/FAILED)
4. **Service Routing**: Delegates to specialized nodes (OnexTree, MetadataStamping, Reducer)
5. **LlamaIndex Workflows**: Uses event-driven workflow orchestration
6. **Lifecycle Management**: Startup/shutdown hooks for service initialization
7. **Health Monitoring**: Checks multiple service dependencies
8. **Retry Policy**: DAG retry with exponential backoff (max 3 retries)

### Key Methods

```python
def __init__(self, container: ModelContainer):
    """Initialize orchestrator with LlamaIndex Workflow."""
    super().__init__(container)

    # Initialize LlamaIndex Workflow - event-driven only
    self.workflow = StampingWorkflow(
        event_bus=self.event_bus,
        kafka_client=self.kafka_client,
        onextree_client=self.onextree_client,
        metadata_client=self.metadata_client,
        timeout=60.0  # 1 minute timeout
    )

    # Workflow state tracking (FSM)
    self.workflow_fsm_states: dict[str, EnumWorkflowState] = {}

async def execute_orchestration(
    self, contract: ModelContractOrchestrator
) -> ModelStampResponseOutput:
    """
    Execute workflow orchestration via LlamaIndex Workflow.

    Event-driven only - no legacy mode.

    Flow:
    1. Run LlamaIndex Workflow with contract input
    2. Workflow executes stages via @step decorators
    3. Each step publishes events to EventBus (Kafka)
    4. Reducer nodes process events and maintain state
    5. Workflow waits for completion events
    6. Return aggregated results
    """
    # Run LlamaIndex workflow
    result = await self.workflow.run(
        input_data=contract.input_data,
        correlation_id=contract.correlation_id,
        output_directory=contract.output_directory,
    )

    # Convert workflow result to ONEX output
    return ModelStampResponseOutput(
        workflow_id=result["workflow_id"],
        success=result["success"],
        stamp_id=result.get("stamp_id"),
        file_hash=result.get("file_hash"),
        stamped_content=result.get("stamped_content"),
        workflow_state=EnumWorkflowState.COMPLETED if result["success"] else EnumWorkflowState.FAILED,
        processing_time_ms=result.get("duration_ms", 0.0),
    )
```

### Service Routing Methods

```python
async def _route_to_onextree(
    self, step: dict[str, Any], contract: ModelContractOrchestrator, workflow_id: UUID
) -> dict[str, Any]:
    """
    Route to OnexTree service for AI intelligence analysis.

    Uses AsyncOnexTreeClient with 500ms timeout and graceful degradation.
    If OnexTree is unavailable, returns fallback intelligence to continue workflow.
    """
    async with AsyncOnexTreeClient(
        base_url=self.onextree_service_url,
        timeout=timeout_seconds,
        max_retries=1,  # Single retry for fast failure
    ) as client:
        # Get intelligence with correlation tracking
        intelligence_data = await client.get_intelligence(
            context=context,
            include_patterns=True,
            include_relationships=True,
            correlation_id=workflow_id,
        )

        return {
            "step_type": "onextree_intelligence",
            "status": "success",
            "intelligence_data": intelligence_result,
            "intelligence_time_ms": intelligence_time_ms,
        }

async def _route_to_metadata_stamping(
    self, step: dict[str, Any], contract: ModelContractOrchestrator, workflow_id: UUID
) -> dict[str, Any]:
    """
    Route to MetadataStampingService for BLAKE3 hash generation.
    """
    # Generate hash using HTTP client with circuit breaker protection
    hash_result = await self.metadata_client.generate_hash(
        file_data=file_data,
        namespace=self.default_namespace,
        correlation_id=workflow_id,
    )

    return {
        "step_type": "hash_generation",
        "status": "success",
        "file_hash": file_hash,
        "hash_generation_time_ms": hash_generation_time_ms,
    }
```

### FSM State Management

```python
async def _transition_state(
    self, workflow_id: UUID, current: EnumWorkflowState, target: EnumWorkflowState
) -> EnumWorkflowState:
    """
    Transition FSM state with validation.

    Uses FSM subcontract to validate transitions and execute actions.
    """
    # Validate transition is allowed
    if not current.can_transition_to(target):
        raise OnexError(
            error_code=EnumCoreErrorCode.VALIDATION_ERROR,
            message=f"Invalid FSM state transition: {current.value} → {target.value}",
        )

    # Update workflow state
    self.workflow_fsm_states[workflow_id_str] = target

    # Publish state transition event
    await self._publish_event(
        EnumWorkflowEvent.STATE_TRANSITION,
        {
            "workflow_id": workflow_id_str,
            "from_state": current.value,
            "to_state": target.value,
        },
    )

    return target
```

### Event-Driven Coordination

```python
async def _handle_success(
    self, workflow_id: UUID, event: dict[str, Any], start_time: float
) -> ModelStampResponseOutput:
    """
    Handle successful StateCommitted event from reducer.

    Transitions to COMPLETED state and returns aggregated results.
    """
    # Extract payload from StateCommitted event
    payload = event.get("payload", {})
    committed_state = payload.get("state", {})

    # Transition to COMPLETED state
    current_state = await self._transition_state(
        workflow_id, current_state, EnumWorkflowState.COMPLETED
    )

    # Build response from committed state
    return ModelStampResponseOutput(
        stamp_id=committed_state.get("stamp_id", str(uuid4())),
        file_hash=committed_state.get("file_hash", "unknown"),
        workflow_state=current_state,
        workflow_id=workflow_id,
        processing_time_ms=processing_time_ms,
    )

async def _handle_failure(
    self, workflow_id: UUID, event: dict[str, Any], start_time: float, retry_count: int = 0
) -> ModelStampResponseOutput:
    """
    Handle ReducerGaveUp event with DAG retry policy.

    DAG retry policy: max 3 retries with exponential backoff (1s, 2s, 4s).
    """
    max_retries = 3
    if retry_count < max_retries:
        # Calculate exponential backoff delay
        backoff_seconds = 2**retry_count  # 1s, 2s, 4s

        # Wait for backoff period
        await asyncio.sleep(backoff_seconds)

        # Retry workflow - re-publish Action event
        raise OnexError(
            error_code=EnumCoreErrorCode.RETRY_REQUIRED,
            message=f"Workflow failed, retry required: {error_message}",
        )

    # Max retries exceeded - transition to FAILED state
    current_state = await self._transition_state(
        workflow_id, current_state, EnumWorkflowState.FAILED
    )
```

### Lifecycle Management

```python
async def startup(self) -> None:
    """
    Node startup lifecycle hook.

    Initializes container services (including Kafka), publishes introspection data,
    and starts background tasks.
    """
    # Initialize container services (connects KafkaClient if available)
    await self.container.initialize()

    # Initialize EventBus service
    if self.event_bus and not self.event_bus.is_initialized:
        await self.event_bus.initialize()

    # Publish initial introspection broadcast
    await self.publish_introspection(reason="startup")

    # Start introspection background tasks (heartbeat, registry listener)
    await self.start_introspection_tasks(
        enable_heartbeat=True,
        heartbeat_interval_seconds=30,
        enable_registry_listener=True,
    )

async def shutdown(self) -> None:
    """
    Node shutdown lifecycle hook.

    Stops background tasks, disconnects Kafka, and cleans up resources.
    """
    # Stop introspection background tasks
    await self.stop_introspection_tasks()

    # Shutdown EventBus service
    if self.event_bus and self.event_bus.is_initialized:
        await self.event_bus.shutdown()

    # Cleanup container services (disconnects KafkaClient and other services)
    await self.container.cleanup()
```

### Health Check System

```python
def _register_component_checks(self) -> None:
    """
    Register component health checks for orchestrator dependencies.

    Checks:
    - node_runtime: Basic node operational status (critical)
    - metadata_stamping: MetadataStampingService health (critical)
    - onextree: OnexTree intelligence service health (non-critical)
    - kafka: Event publishing health (non-critical, degraded mode available)
    - event_bus: Event-driven coordination health (non-critical, can use legacy mode)
    """
    super()._register_component_checks()

    # Register MetadataStampingService health check (critical)
    self.register_component_check(
        "metadata_stamping",
        self._check_metadata_stamping_health,
        critical=True,
        timeout_seconds=5.0,
    )

    # Register OnexTree health check (non-critical, graceful degradation)
    self.register_component_check(
        "onextree",
        self._check_onextree_health,
        critical=False,
        timeout_seconds=3.0,
    )
```

### Orchestrator Node Pattern Summary

```python
from llama_index.core.workflow import Workflow, step, StartEvent, StopEvent, Event, Context

# Orchestrator Node Template
class NodeXxxOrchestrator(NodeOrchestrator):
    """
    Modern orchestrator using LlamaIndex Workflows.

    IMPORTANT: No legacy mode - event-driven only.
    """

    def __init__(self, container: ModelContainer):
        super().__init__(container)

        # Initialize LlamaIndex Workflow
        self.workflow = XxxWorkflow(
            event_bus=self.event_bus,
            kafka_client=self.kafka_client,
            service_clients={
                "intelligence": self.intelligence_client,
                "processing": self.processing_client,
            },
            timeout=300.0  # 5 minute workflow timeout
        )

        # Workflow state tracking (FSM) - managed by workflow
        self.workflow_fsm_states: dict[str, EnumWorkflowState] = {}

    async def execute_orchestration(
        self, contract: ModelContractOrchestrator
    ) -> ModelOutputState:
        """
        Execute multi-step workflow orchestration via LlamaIndex Workflow.

        Pattern:
        1. Run LlamaIndex Workflow with contract input
        2. Workflow executes @step functions with event routing
        3. Each step publishes events to EventBus
        4. Reducer nodes process events and maintain state
        5. Workflow aggregates results
        6. Return orchestrated output
        """
        # Run workflow
        result = await self.workflow.run(
            input_data=contract.input_data,
            correlation_id=contract.correlation_id,
            metadata=contract.metadata,
        )

        # Convert workflow result to ONEX output
        return ModelOutputState(
            workflow_id=result["workflow_id"],
            success=result["success"],
            output_data=result["output_data"],
            metadata={
                "duration_seconds": result["total_duration_seconds"],
                "steps_executed": result["steps_executed"],
                "quality_score": result.get("quality_score", 1.0),
            }
        )

    async def startup(self) -> None:
        """Initialize EventBus and start background tasks."""
        await self.container.initialize()
        await self.event_bus.initialize()
        await self.start_introspection_tasks()

    async def shutdown(self) -> None:
        """Cleanup EventBus and stop background tasks."""
        await self.stop_introspection_tasks()
        await self.event_bus.shutdown()
        await self.container.cleanup()


# LlamaIndex Workflow Implementation
class XxxWorkflow(Workflow):
    """
    LlamaIndex Workflow for multi-step orchestration.

    All workflow logic lives here - orchestrator node is just a wrapper.
    """

    def __init__(
        self,
        event_bus: EventBusService,
        kafka_client: KafkaClient,
        service_clients: dict[str, Any],
        **kwargs
    ):
        super().__init__(**kwargs)
        self.event_bus = event_bus
        self.kafka_client = kafka_client
        self.service_clients = service_clients

    @step
    async def initialize(
        self, ctx: Context, ev: StartEvent
    ) -> ProcessingEvent:
        """Step 1: Initialize workflow context."""
        # Store workflow context
        ctx.data["workflow_id"] = str(uuid4())
        ctx.data["correlation_id"] = ev.correlation_id
        ctx.data["start_time"] = time.time()

        # Publish workflow started event
        await self._publish_event("WORKFLOW_STARTED", {...})

        return ProcessingEvent(data=ev.input_data)

    @step
    async def process(
        self, ctx: Context, ev: ProcessingEvent
    ) -> ValidationEvent | StopEvent:
        """Step 2: Process data via specialized services."""
        try:
            # Call specialized service
            result = await self.service_clients["processing"].process(ev.data)

            # Publish processing completed event
            await self._publish_event("PROCESSING_COMPLETED", {...})

            return ValidationEvent(result=result)

        except Exception as e:
            # Publish error event
            await self._publish_event("PROCESSING_FAILED", {"error": str(e)})
            return StopEvent(result={"success": False, "error": str(e)})

    @step
    async def validate(
        self, ctx: Context, ev: ValidationEvent
    ) -> StopEvent:
        """Step 3: Validate results and return."""
        # Validate result
        validation_passed = self._validate(ev.result)

        # Calculate total duration
        duration = time.time() - ctx.data["start_time"]

        # Publish completion event
        await self._publish_event("WORKFLOW_COMPLETED", {...})

        return StopEvent(
            result={
                "workflow_id": ctx.data["workflow_id"],
                "success": validation_passed,
                "output_data": ev.result,
                "total_duration_seconds": duration,
                "steps_executed": 3,
            }
        )

    async def _publish_event(self, event_type: str, payload: dict[str, Any]):
        """Publish event to EventBus (Kafka)."""
        if self.event_bus and self.event_bus.is_initialized:
            await self.event_bus.publish_event(
                event_type=event_type,
                payload=payload,
                correlation_id=payload.get("correlation_id"),
            )
```

**Use Cases**: Multi-service workflows, event-driven coordination, service routing, workflow state management, orchestration with retry logic, lifecycle management

---

## LlamaIndex Workflow Integration

**Important**: Orchestrator nodes should leverage **LlamaIndex Workflows** for event-driven orchestration rather than implementing custom workflow logic.

### Why LlamaIndex Workflows?

1. **Event-Driven Architecture**: Natural fit for ONEX event system
2. **Context Preservation**: Built-in state management across workflow steps
3. **Type Safety**: Pydantic-based events with strong typing
4. **Performance**: Async/await with minimal overhead (<1ms event emission)
5. **Parallel Execution**: Built-in support for fan-out/fan-in patterns
6. **Error Handling**: Retry logic, circuit breakers, graceful degradation

### Example: Code Generation Orchestrator Workflow

**File**: `/Volumes/PRO-G40/Code/omninode_bridge/src/omninode_bridge/nodes/codegen_orchestrator/v1_0_0/workflow.py`

```python
from llama_index.core.workflow import (
    Workflow, StartEvent, StopEvent, step, Event, Context
)

# Custom workflow events for stage transitions
class PromptParsedEvent(Event):
    """Event: Prompt parsing complete."""
    requirements: dict[str, Any]

class IntelligenceGatheredEvent(Event):
    """Event: Intelligence gathering complete."""
    intelligence_data: dict[str, Any]

class CodeGeneratedEvent(Event):
    """Event: Code generation complete."""
    generated_files: dict[str, str]

class ValidationCompleteEvent(Event):
    """Event: Validation complete."""
    validation_results: dict[str, Any]

class CodeGenerationWorkflow(Workflow):
    """
    8-stage ONEX node code generation workflow.

    Stages:
    1. Prompt parsing (5s target)
    2. Intelligence gathering (3s target) - RAG query
    3. Contract building (2s target)
    4. Code generation (10-15s target)
    5. Event bus integration (2s target)
    6. Validation (5s target)
    7. Refinement (3s target)
    8. File writing (3s target)
    """

    def __init__(
        self,
        kafka_client: Optional[KafkaClient] = None,
        enable_intelligence: bool = True,
        **kwargs
    ):
        """Initialize workflow with optional Kafka and intelligence."""
        super().__init__(**kwargs)
        self.kafka_client = kafka_client
        self.enable_intelligence = enable_intelligence

    # Stage 1: Prompt Parsing
    @step
    async def parse_prompt(
        self, ctx: Context, ev: StartEvent
    ) -> PromptParsedEvent:
        """Parse natural language prompt and extract requirements."""
        # Initialize context from start event
        gen_ctx = ModelGenerationContext(
            workflow_id=uuid4(),
            correlation_id=ev.correlation_id,
            prompt=ev.prompt,
            output_directory=ev.output_directory,
        )
        gen_ctx.enter_stage(EnumPipelineStage.PROMPT_PARSING)
        await ctx.set("generation_context", gen_ctx)

        # Parse prompt (using LLM)
        requirements = {
            "node_type": self._infer_node_type(ev.prompt),
            "service_name": self._extract_service_name(ev.prompt),
            "operations": self._extract_operations(ev.prompt),
        }

        # Update context
        gen_ctx.parsed_requirements = requirements
        gen_ctx.complete_stage(EnumPipelineStage.PROMPT_PARSING, duration)

        # Publish Kafka event
        await self._publish_stage_completed(gen_ctx, stage, duration)

        return PromptParsedEvent(requirements=requirements)

    # Stage 2: Intelligence Gathering
    @step
    async def gather_intelligence(
        self, ctx: Context, ev: PromptParsedEvent
    ) -> IntelligenceGatheredEvent:
        """Query RAG for relevant patterns and best practices."""
        gen_ctx: ModelGenerationContext = await ctx.get("generation_context")
        gen_ctx.enter_stage(EnumPipelineStage.INTELLIGENCE_GATHERING)

        # Query intelligence with circuit breaker
        if gen_ctx.enable_intelligence:
            intelligence_data, error_code = await self._query_intelligence_with_protection(
                gen_ctx
            )

            # Track warning if degraded
            if error_code:
                gen_ctx.stage_warnings[stage.value].append(
                    f"Intelligence service degraded: {error_code.value}"
                )
        else:
            intelligence_data = {"patterns_found": 0}

        gen_ctx.intelligence_data = intelligence_data
        gen_ctx.complete_stage(stage, duration)

        return IntelligenceGatheredEvent(intelligence_data=intelligence_data)

    # Stage 3: Code Generation
    @step
    async def generate_code(
        self, ctx: Context, ev: IntelligenceGatheredEvent
    ) -> CodeGeneratedEvent:
        """Generate node implementation code."""
        gen_ctx: ModelGenerationContext = await ctx.get("generation_context")

        # Generate code files using LLM with intelligence context
        generated_files = self._generate_code_files(
            requirements=gen_ctx.parsed_requirements,
            intelligence=ev.intelligence_data
        )

        gen_ctx.generated_code = generated_files

        return CodeGeneratedEvent(generated_files=generated_files)

    # Stage 4: Validation
    @step
    async def validate_code(
        self, ctx: Context, ev: CodeGeneratedEvent
    ) -> ValidationCompleteEvent | StopEvent:
        """Run linting, type checking, basic tests."""
        gen_ctx: ModelGenerationContext = await ctx.get("generation_context")

        try:
            # Run validation (ruff, mypy, pytest)
            validation_results = {
                "linting_passed": True,
                "type_checking_passed": True,
                "tests_passed": True,
                "quality_score": 0.85,
            }

            gen_ctx.validation_results = validation_results

            return ValidationCompleteEvent(validation_results=validation_results)

        except Exception as e:
            # Partial success: validation failed but code exists
            if gen_ctx.generated_code:
                # Mark for manual review but continue
                validation_results = {
                    "linting_passed": False,
                    "needs_review": True,
                    "errors": [str(e)],
                }
                return ValidationCompleteEvent(validation_results=validation_results)
            else:
                # Complete failure - stop workflow
                return StopEvent(result={"error": str(e), "success": False})

    # Final Stage: File Writing
    @step
    async def write_files(
        self, ctx: Context, ev: ValidationCompleteEvent
    ) -> StopEvent:
        """Write all generated files to disk."""
        gen_ctx: ModelGenerationContext = await ctx.get("generation_context")

        # Write files to filesystem
        written_files = []
        for filename, content in gen_ctx.generated_code.items():
            filepath = gen_ctx.output_directory / filename
            filepath.write_text(content)
            written_files.append(str(filepath))

        gen_ctx.written_files = written_files

        # Return final result
        return StopEvent(
            result={
                "workflow_id": str(gen_ctx.workflow_id),
                "success": True,
                "total_duration_seconds": gen_ctx.get_total_duration(),
                "generated_files": written_files,
                "quality_score": gen_ctx.quality_score,
                "needs_review": gen_ctx.validation_results.get("needs_review", False),
            }
        )
```

### Key LlamaIndex Workflow Patterns

#### Pattern 1: Context Preservation Across Steps

```python
@step
async def step_one(self, ctx: Context, ev: StartEvent) -> CustomEvent:
    """First step - initialize context."""
    # Store shared state in context
    ctx.data["session_id"] = str(uuid4())
    ctx.data["start_time"] = time.time()

    return CustomEvent(data=ev.input_data)

@step
async def step_two(self, ctx: Context, ev: CustomEvent) -> StopEvent:
    """Second step - access shared context."""
    # Retrieve context from previous step
    session_id = ctx.data["session_id"]
    execution_time = time.time() - ctx.data["start_time"]

    return StopEvent(result={"session_id": session_id, "time": execution_time})
```

#### Pattern 2: Circuit Breaker and Retry Integration

```python
from circuitbreaker import circuit

class ResilientWorkflow(Workflow):
    """Workflow with circuit breaker protection."""

    @step
    @circuit(failure_threshold=5, recovery_timeout=60)
    async def call_external_service(
        self, ctx: Context, ev: RequestEvent
    ) -> ResponseEvent | ErrorEvent:
        """Call external service with circuit breaker."""
        try:
            result = await self._call_service(ev.data)
            return ResponseEvent(data=result)
        except Exception as e:
            return ErrorEvent(error=str(e), recoverable=True)

    @step
    async def handle_error(
        self, ctx: Context, ev: ErrorEvent
    ) -> ResponseEvent | StopEvent:
        """Handle errors with graceful degradation."""
        if ev.recoverable:
            # Retry with exponential backoff
            await asyncio.sleep(2 ** ctx.data.get("retry_count", 0))
            ctx.data["retry_count"] = ctx.data.get("retry_count", 0) + 1

            # Retry or give up
            if ctx.data["retry_count"] < 3:
                return RequestEvent(data=ev.original_data)
            else:
                return StopEvent(result={"error": "Max retries exceeded"})
        else:
            return StopEvent(result={"error": ev.error, "fatal": True})
```

#### Pattern 3: Parallel Execution (Fan-Out/Fan-In)

```python
class ParallelWorkflow(Workflow):
    """Workflow with parallel step execution."""

    @step
    async def fan_out(
        self, ctx: Context, ev: StartEvent
    ) -> list[ProcessingEvent]:
        """Fan out to multiple parallel processing steps."""
        tasks = ev.input_data.get("tasks", [])

        # Create event for each parallel task
        events = [
            ProcessingEvent(
                task_data=task,
                task_id=i,
                correlation_id=f"{ev.correlation_id}_task_{i}"
            )
            for i, task in enumerate(tasks)
        ]

        # Store parallel task count in context
        ctx.data["parallel_task_count"] = len(events)
        ctx.data["completed_results"] = []

        return events  # LlamaIndex handles parallel execution

    @step
    async def process_parallel(
        self, ctx: Context, ev: ProcessingEvent
    ) -> ResultEvent:
        """Process individual parallel task."""
        result = await self._process_task(ev.task_data)
        return ResultEvent(result=result, task_id=ev.task_id)

    @step
    async def fan_in(
        self, ctx: Context, ev: ResultEvent
    ) -> StopEvent | None:
        """Aggregate results when all parallel tasks complete."""
        # Collect result
        results = ctx.data.get("completed_results", [])
        results.append(ev.result)
        ctx.data["completed_results"] = results

        # Check if all tasks complete
        if len(results) < ctx.data["parallel_task_count"]:
            return None  # Wait for more results

        # All tasks complete, return aggregated results
        return StopEvent(
            result={
                "parallel_results": results,
                "total_tasks": len(results),
                "status": "all_completed"
            }
        )
```

### Integrating LlamaIndex Workflows with Orchestrator Nodes

```python
from llama_index.core.workflow import Workflow
from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

class NodeCodegenOrchestrator(NodeOrchestrator):
    """Orchestrator node using LlamaIndex Workflow for code generation."""

    def __init__(self, container: ModelContainer):
        super().__init__(container)

        # Initialize LlamaIndex workflow
        self.workflow = CodeGenerationWorkflow(
            kafka_client=self.kafka_client,
            enable_intelligence=True,
            timeout=300.0  # 5 minute timeout
        )

    async def execute_orchestration(
        self, contract: ModelContractOrchestrator
    ) -> ModelOutputState:
        """Execute orchestration via LlamaIndex workflow."""

        # Run workflow with contract input
        result = await self.workflow.run(
            prompt=contract.input_data["prompt"],
            output_directory=contract.input_data["output_directory"],
            correlation_id=contract.correlation_id,
        )

        # Convert workflow result to ONEX output
        return ModelOutputState(
            workflow_id=result["workflow_id"],
            success=result["success"],
            generated_files=result["generated_files"],
            quality_score=result["quality_score"],
            metadata={
                "duration_seconds": result["total_duration_seconds"],
                "needs_review": result["needs_review"],
            }
        )
```

### Performance Characteristics

**LlamaIndex Workflows Performance** (from `LLAMAINDEX_WORKFLOWS_GUIDE.md`):
- **Event Processing**: 1000+ events/second for simple steps
- **Complex Workflows**: 100-500 workflows/second
- **Event Emission**: p50: 0.1ms, p95: 0.5ms, p99: 1.0ms
- **Step Transition**: p50: 0.5ms, p95: 2.0ms, p99: 5.0ms
- **Context Access**: p50: 0.05ms, p95: 0.2ms, p99: 0.5ms
- **Simple Workflow E2E**: p50: 10ms, p95: 50ms, p99: 100ms (3-5 steps)
- **Complex Workflow E2E**: p50: 100ms, p95: 500ms, p99: 1000ms (10+ steps)

### References

- **LlamaIndex Workflows Guide**: `/Volumes/PRO-G40/Code/omninode_bridge/docs/LLAMAINDEX_WORKFLOWS_GUIDE.md`
- **Production Example**: `/Volumes/PRO-G40/Code/omninode_bridge/src/omninode_bridge/nodes/codegen_orchestrator/v1_0_0/workflow.py`
- **Official Docs**: https://docs.llamaindex.ai/en/stable/understanding/workflows/

---

## Key Insights for Contract-Driven Generation

### 1. Archetypes are Reusable

You **DON'T** generate:
- `NodeUserAuthEffect`, `NodePaymentEffect`, `NodeOrderEffect`
- `NodeUserAuthCompute`, `NodePaymentCompute`, `NodeOrderCompute`

You **DO** generate:
- **One** `DatabaseNode` (Effect) - reused for all database operations
- **One** `ValidationNode` (Compute) - reused for all validation
- **One** `SessionReducerNode` (Reducer) - reused for session management
- **One** `WorkflowOrchestratorNode` (Orchestrator) - handles all workflows

### 2. Domain Logic Lives in Contracts

For "Generate user authentication system":

**Contracts** (domain-specific):
```yaml
# UserAuthRequest.yaml
type: object
properties:
  username: string
  password: string
  mfa_code: string (optional)
```

**Events** (auto-generated from contracts):
```python
class UserAuthRequestedEvent(OnexEnvelopeV1):
    payload: UserAuthRequest

class UserAuthenticatedEvent(OnexEnvelopeV1):
    payload: UserAuthResponse
```

**Workflows** (compose archetypes):
```python
class AuthWorkflow(Workflow):
    @step
    async def validate_input(ctx, ev: UserAuthRequestedEvent):
        return await ValidationNode.execute(ev.payload)  # Compute archetype

    @step
    async def hash_password(ctx, validated_data):
        return await HashingNode.execute(validated_data)  # Compute archetype

    @step
    async def check_database(ctx, hashed_data):
        return await DatabaseNode.execute(hashed_data)  # Effect archetype

    @step
    async def update_session(ctx, auth_result):
        return await SessionReducerNode.execute(auth_result)  # Reducer archetype
```

### 3. Generation Strategy

Instead of generating nodes per domain, generate:

1. **Archetypal Node Library** (once):
   - DatabaseNode, APINode, LoggerNode (Effect)
   - ValidationNode, HashingNode, TransformationNode (Compute)
   - SessionReducerNode, StateReducerNode (Reducer)
   - WorkflowOrchestratorNode (Orchestrator)

2. **Domain Contracts** (per feature):
   - Parse prompt → identify entities
   - Generate Pydantic models for entities
   - Add validation rules

3. **Events from Contracts** (auto-generated):
   - Parse contract signatures
   - Generate OnexEnvelopeV1 wrappers
   - Generate event publishers/handlers

4. **Workflows that Compose Archetypes** (per feature):
   - Identify required steps from prompt
   - Map steps to archetypal nodes
   - Generate workflow with event-driven transitions

---

## Next Steps for Week 4 Implementation

### Option 1: Archetypal Node Library Generator

Build a generator that creates the base archetypal nodes:

**Input**: Node archetype specification (Effect, Compute, Reducer, Orchestrator)

**Output**:
- Effect: DatabaseNode, APINode, KafkaNode, FileNode, LoggerNode
- Compute: ValidationNode, HashingNode, ParserNode, TransformationNode, LLMNode
- Reducer: SessionReducerNode, StateReducerNode, CacheReducerNode, MetricsReducerNode
- Orchestrator: WorkflowOrchestratorNode (handles multiple workflows)

### Option 2: Contract-Driven Workflow Generator

**Input**: High-level prompt ("Generate user authentication system")

**Process**:
1. Analyze prompt → identify contracts (UserAuthRequest, UserAuthResponse, UserAuthError)
2. Generate Pydantic models from identified contracts
3. Auto-generate events from contracts (UserAuthRequestedEvent, etc.)
4. Generate workflow that composes archetypal nodes
5. Generate event handlers that route to workflow

**Output**:
- 3-5 contract files (Pydantic models)
- 3-5 event files (OnexEnvelopeV1 wrappers)
- 1 workflow file (composes archetypes)
- 1 event handler file (routes events)

### Option 3: Full System Generation

Combine both approaches:
1. Generate archetypal node library (if doesn't exist)
2. Generate domain contracts from prompt
3. Generate events from contracts
4. Generate workflows that compose archetypes
5. Validate with 23 quality gates
6. Store patterns for future reuse

---

## File Structure for Generated System

```
generated/
├── archetypes/
│   ├── effects/
│   │   ├── node_database_effect.py
│   │   ├── node_api_effect.py
│   │   └── node_logger_effect.py
│   ├── compute/
│   │   ├── node_validation_compute.py
│   │   ├── node_hashing_compute.py
│   │   └── node_llm_compute.py
│   ├── reducers/
│   │   ├── node_session_reducer.py
│   │   └── node_state_reducer.py
│   └── orchestrators/
│       └── node_workflow_orchestrator.py
├── contracts/
│   ├── user_auth_request.py
│   ├── user_auth_response.py
│   └── user_auth_error.py
├── events/
│   ├── user_auth_requested_event.py
│   ├── user_auth_authenticated_event.py
│   └── user_auth_failed_event.py
├── workflows/
│   └── auth_workflow.py
└── handlers/
    └── auth_event_handlers.py
```

---

## Conclusion

The key insight is that **node types are architectural patterns, not domain entities**. You create a library of reusable archetypal nodes and then compose them via workflows defined by domain-specific contracts and events.

This dramatically simplifies generation:
- Instead of generating 4 nodes per domain (100 nodes for 25 features)
- Generate 15-20 archetypal nodes once (reused across all features)
- Generate contracts, events, and workflows per feature (lightweight generation)

The power is in **composition**, not **multiplication**.
