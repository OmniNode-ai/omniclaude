# omnibase_core Architecture

**Version**: 1.0.0
**Stability**: All node base classes and contract models have INTERFACE LOCKED status
**Location**: `/Users/jonah/Code/omnibase_core`
**Purpose**: Foundation for ONEX 4-node architecture with dependency injection, error handling, and contract-driven development

---

## Overview

omnibase_core provides the foundational building blocks for ONEX (Orchestrator-Node-Effect-eXecution) architecture, implementing a contract-driven, type-safe framework for distributed systems with:

- **4-Node Architecture**: Orchestrator, Reducer, Effect, Compute
- **Dependency Injection**: ModelONEXContainer with service registry
- **Contract-Driven Development**: Type-safe contracts with validation
- **Error Handling**: Structured error model with correlation tracking
- **Lifecycle Management**: Resource initialization and cleanup patterns

---

## Node Base Classes

### 1. NodeOrchestrator (Workflow Coordination)

**Purpose**: Workflow coordination and control flow management
**File**: `src/omnibase_core/nodes/node_orchestrator.py`
**Stability**: v1.0.0 - INTERFACE LOCKED

#### Key Capabilities
- Workflow coordination with control flow
- Thunk emission patterns for deferred execution
- Conditional branching based on runtime state
- Parallel execution coordination
- RSD Workflow Management (ticket lifecycle state transitions)
- Dependency-aware execution ordering
- Batch processing coordination with load balancing
- Error recovery and partial failure handling

#### Method Signatures

```python
class NodeOrchestrator(NodeCoreBase):
    """
    Workflow coordination node for control flow management.

    STABLE INTERFACE v1.0.0 - DO NOT CHANGE without major version bump.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize with ModelONEXContainer dependency injection."""
        super().__init__(container)

        # Configuration (loaded from NodeConfigProvider)
        self.max_concurrent_workflows = 5
        self.default_step_timeout_ms = 30000
        self.action_emission_enabled = True

        # Active workflows tracking (UUID keys)
        self.active_workflows: dict[UUID, ModelOrchestratorInput] = {}
        self.workflow_states: dict[UUID, EnumWorkflowState] = {}

        # Load balancer for operation distribution
        self.load_balancer = ModelLoadBalancer(max_concurrent_operations=20)

        # Action emission registry (UUID keys)
        self.emitted_actions: dict[UUID, list[ModelAction]] = {}

        # Workflow execution semaphore
        self.workflow_semaphore = asyncio.Semaphore(self.max_concurrent_workflows)

        # Conditional functions registry
        self.condition_functions: dict[str, Callable] = {}

    async def process(
        self,
        input_data: ModelOrchestratorInput,
    ) -> ModelOrchestratorOutput:
        """
        REQUIRED: Execute workflow coordination with thunk emission.

        STABLE INTERFACE: This method signature is frozen for code generation.

        Flow:
        1. Validate input
        2. Build dependency graph if enabled
        3. Execute workflow (sequential/parallel/batch mode)
        4. Update workflow state
        5. Return results with metrics
        """

    async def emit_action(
        self,
        action_type: EnumActionType,
        target_node_type: str,
        payload: dict[str, Any],
        dependencies: list[UUID] | None = None,
        priority: int = 1,
        timeout_ms: int = 30000,
        lease_id: UUID | None = None,
        epoch: int = 0,
    ) -> ModelAction:
        """Emit action for deferred execution."""

    def register_condition_function(
        self,
        condition_name: str,
        function: Callable[..., Any],
    ) -> None:
        """Register custom condition function for branching."""
```

#### Execution Modes

1. **Sequential**: `EnumExecutionMode.SEQUENTIAL`
   - Steps execute in order
   - Respects dependency graph if enabled
   - Continues or fails based on failure_strategy

2. **Parallel**: `EnumExecutionMode.PARALLEL`
   - Steps execute in waves based on dependencies
   - Max parallel steps controlled by `max_parallel_steps`
   - Partial failure handling

3. **Batch**: `EnumExecutionMode.BATCH`
   - Groups similar operations
   - Load balancing via ModelLoadBalancer
   - Resource optimization

#### RSD Integration

```python
async def orchestrate_rsd_ticket_lifecycle(
    self,
    ticket_id: UUID,
    current_state: str,
    target_state: str,
    dependency_tickets: list[UUID] | None = None,
) -> dict[str, Any]:
    """
    Orchestrate RSD ticket lifecycle state transitions.

    Creates workflow for transitioning ticket through states while
    respecting dependencies and applying validation at each step.
    """
```

---

### 2. NodeReducer (State Aggregation)

**Purpose**: Data aggregation and state reduction operations
**File**: `src/omnibase_core/nodes/node_reducer.py`
**Stability**: v1.0.0 - INTERFACE LOCKED

#### Key Capabilities
- State aggregation and data transformation
- Reduce operations (fold, accumulate, merge)
- Streaming support for large datasets
- Conflict resolution strategies
- RSD Data Processing (ticket metadata aggregation)
- Priority score normalization and ranking
- Graph dependency resolution and cycle detection
- Status consolidation across ticket collections

#### Method Signatures

```python
class NodeReducer(NodeCoreBase):
    """
    Data aggregation and state reduction node.

    STABLE INTERFACE v1.0.0 - DO NOT CHANGE without major version bump.

    PURE FSM PATTERN: No mutable instance state.
    All state is passed through input/output, side effects emitted as Intents.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """
        Initialize with ModelONEXContainer dependency injection.

        PURE FSM PATTERN: No mutable instance state.
        """
        super().__init__(container)

        # Configuration only (loaded from NodeConfigProvider)
        self.default_batch_size = 1000
        self.max_memory_usage_mb = 512
        self.streaming_buffer_size = 10000

        # Configuration: Legacy attributes for current implementation
        self.reduction_functions: dict[EnumReductionType, Callable] = {}
        self.reduction_metrics: dict[str, dict[str, float]] = {}
        self.active_windows: dict[str, ModelStreamingWindow] = {}

    async def process(
        self,
        input_data: ModelReducerInput[T_Input],
    ) -> ModelReducerOutput[T_Output]:
        """
        REQUIRED: Stream-based reduction with conflict resolution.

        STABLE INTERFACE: This method signature is frozen for code generation.

        Flow:
        1. Validate input
        2. Initialize conflict resolver
        3. Execute reduction (batch/incremental/windowed mode)
        4. Emit Intents for side effects (PURE FSM pattern)
        5. Return results with metrics
        """

    def register_reduction_function(
        self,
        reduction_type: EnumReductionType,
        function: Callable,
    ) -> None:
        """Register custom reduction function."""
```

#### Streaming Modes

1. **Batch**: `EnumStreamingMode.BATCH`
   - Process all data in single operation
   - Fastest for small datasets
   - Simple in-memory processing

2. **Incremental**: `EnumStreamingMode.INCREMENTAL`
   - Process data in batches
   - Memory-efficient for large datasets
   - Configurable batch_size

3. **Windowed**: `EnumStreamingMode.WINDOWED`
   - Time-based window processing
   - Configurable window_size_ms
   - Ideal for time-series data

#### Intent System (PURE FSM)

```python
# Instead of direct side effects, NodeReducer emits Intents
intents: list[ModelIntent] = []

# Intent to log metrics
intents.append(
    ModelIntent(
        intent_type="log_metric",
        target="metrics_service",
        payload={...},
        priority=3,
    )
)

# Intent to log event
intents.append(
    ModelIntent(
        intent_type="log_event",
        target="logging_service",
        payload={...},
        priority=2,
    )
)

# Return with intents for Effect node to execute
return ModelReducerOutput(..., intents=intents)
```

#### RSD Integration

```python
async def aggregate_rsd_tickets(
    self,
    tickets: list[dict[str, Any]],
    group_by: str = "status",
    aggregation_functions: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Aggregate RSD ticket metadata from multiple sources."""

async def normalize_priority_scores(
    self,
    tickets_with_scores: list[dict[str, Any]],
    score_field: str = "priority_score",
    normalization_method: str = "min_max",
) -> list[dict[str, Any]]:
    """Normalize priority scores and create rankings."""

async def resolve_dependency_cycles(
    self,
    dependency_graph: dict[str, list[str]],
) -> dict[str, Any]:
    """Detect and resolve cycles in dependency graphs."""
```

---

### 3. NodeEffect (Side Effect Management)

**Purpose**: Side effect management and external interactions
**File**: `src/omnibase_core/nodes/node_effect.py`
**Stability**: v1.0.0 - INTERFACE LOCKED

#### Key Capabilities
- Side-effect management with external interaction focus
- I/O operation abstraction (file, database, API calls)
- ModelEffectTransaction management for rollback support
- Retry policies and circuit breaker patterns
- Event bus publishing for state changes
- Atomic file operations for data integrity

#### Method Signatures

```python
class NodeEffect(NodeCoreBase):
    """
    Side effect management node for external interactions.

    STABLE INTERFACE v1.0.0 - DO NOT CHANGE without major version bump.

    Thread Safety Warning:
    - Circuit breaker state NOT thread-safe
    - Transactions NOT shareable across threads
    - Create separate instances per thread
    """

    def __init__(
        self,
        container: ModelONEXContainer,
        on_rollback_failure: Callable[[ModelEffectTransaction, list[ModelOnexError]], None] | None = None,
    ) -> None:
        """
        Initialize with ModelONEXContainer dependency injection.

        Args:
            on_rollback_failure: Optional callback for rollback failures
        """
        super().__init__(container)

        # Configuration (loaded from NodeConfigProvider)
        self.default_timeout_ms = 30000
        self.default_retry_delay_ms = 1000
        self.max_concurrent_effects = 10

        # Transaction management
        self.active_transactions: dict[UUID, ModelEffectTransaction] = {}

        # Circuit breakers for external services
        self.circuit_breakers: dict[str, ModelCircuitBreaker] = {}

        # Effect handlers registry
        self.effect_handlers: dict[EnumEffectType, Callable] = {}

        # Semaphore for limiting concurrent effects
        self.effect_semaphore = asyncio.Semaphore(self.max_concurrent_effects)

        # Rollback failure callback
        self.on_rollback_failure = on_rollback_failure

    async def execute_effect(
        self,
        contract: ModelContractEffect,
    ) -> ModelEffectOutput:
        """
        Execute effect based on contract specification.

        REQUIRED INTERFACE: Public method for contract-driven execution.
        """

    async def process(
        self,
        input_data: ModelEffectInput
    ) -> ModelEffectOutput:
        """
        REQUIRED: Execute side effect operation.

        STABLE INTERFACE: This method signature is frozen for code generation.

        Flow:
        1. Validate input
        2. Check circuit breaker
        3. Create transaction if enabled
        4. Execute with retry logic
        5. Commit transaction or rollback on error
        6. Update metrics and circuit breaker
        """

    @asynccontextmanager
    async def transaction_context(
        self,
        operation_id: UUID | None = None
    ) -> AsyncIterator[ModelEffectTransaction]:
        """
        Async context manager for transaction handling.

        Usage:
            async with node.transaction_context() as tx:
                # Perform operations
                # Automatic commit on success, rollback on error
        """
```

#### Transaction Management

```python
class ModelEffectTransaction:
    """Transaction with rollback support."""

    transaction_id: UUID
    state: EnumTransactionState
    operations: list[tuple[str, dict[str, Any], Callable]]

    def add_operation(
        self,
        operation_type: str,
        operation_data: dict[str, Any],
        rollback_func: Callable,
    ) -> None:
        """Add operation with rollback function."""

    async def commit(self) -> None:
        """Commit all operations."""
        self.state = EnumTransactionState.COMMITTED

    async def rollback(self) -> tuple[bool, list[ModelOnexError]]:
        """
        Rollback all operations.

        Returns:
            (success: bool, errors: list[ModelOnexError])
        """
```

#### Built-in Effect Handlers

1. **File Operations**: `EnumEffectType.FILE_OPERATION`
   - Read, write, delete with atomic guarantees
   - Automatic backup for rollback
   - Transaction support

2. **Event Emission**: `EnumEffectType.EVENT_EMISSION`
   - Publish to event bus
   - Non-critical graceful failure
   - Correlation tracking

#### RSD Integration

```python
async def execute_file_operation(
    self,
    operation_type: str,
    file_path: str | Path,
    data: Any | None = None,
    atomic: bool = True,
) -> dict[str, Any]:
    """Execute atomic file operation for work ticket management."""

async def emit_state_change_event(
    self,
    event_type: str,
    payload: dict[str, Any],
    correlation_id: UUID | None = None,
) -> bool:
    """Emit state change event to event bus."""
```

---

### 4. NodeCompute (Pure Computation)

**Purpose**: Pure computational operations with deterministic guarantees
**File**: `src/omnibase_core/nodes/node_compute.py`
**Stability**: v1.0.0 - INTERFACE LOCKED

#### Key Capabilities
- Pure function patterns with no side effects
- Deterministic operation guarantees
- Computational pipeline with parallel processing
- Caching layer for expensive computations
- Algorithm registration and execution

#### Method Signatures

```python
class NodeCompute(NodeCoreBase):
    """
    Pure computation node for deterministic operations.

    STABLE INTERFACE v1.0.0 - DO NOT CHANGE without major version bump.

    Thread Safety Warning:
    - Instance NOT thread-safe due to mutable cache state
    - Use separate instances per thread OR implement cache locking
    - Parallel processing via ThreadPoolExecutor is internally managed
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize with ModelONEXContainer dependency injection."""
        super().__init__(container)

        # Get cache configuration from container
        cache_config = container.compute_cache_config

        # Configuration (loaded from NodeConfigProvider)
        self.max_parallel_workers = 4
        self.cache_ttl_minutes = cache_config.get_ttl_minutes() or 30
        self.performance_threshold_ms = 100.0

        # Initialize caching layer
        self.computation_cache = ModelComputeCache(
            max_size=cache_config.max_size,
            ttl_seconds=cache_config.ttl_seconds,
            eviction_policy=cache_config.eviction_policy,
            enable_stats=cache_config.enable_stats,
        )

        # Thread pool for parallel execution
        self.thread_pool: ThreadPoolExecutor | None = None

        # Computation registry
        self.computation_registry: dict[str, Callable] = {}

    async def process(
        self,
        input_data: ModelComputeInput[T_Input]
    ) -> ModelComputeOutput[T_Output]:
        """
        REQUIRED: Execute pure computation.

        STABLE INTERFACE: This method signature is frozen for code generation.

        Flow:
        1. Validate input
        2. Check cache (if enabled)
        3. Execute computation (sequential or parallel)
        4. Validate performance threshold
        5. Cache result (if enabled)
        6. Return results with metrics
        """

    def register_computation(
        self,
        computation_type: str,
        computation_func: Callable,
    ) -> None:
        """Register custom computation function."""
```

#### Caching Strategy

```python
# Cache key generation
cache_key = f"{computation_type}:{hash(input_data)}"

# Cache lookup
cached_result = self.computation_cache.get(cache_key)
if cached_result is not None:
    return ModelComputeOutput(
        result=cached_result,
        cache_hit=True,
        ...
    )

# Cache storage (after computation)
self.computation_cache.put(cache_key, result, self.cache_ttl_minutes)
```

#### Parallel Execution

```python
# Supports parallel execution for list/tuple inputs
if input_data.parallel_enabled and isinstance(input_data.data, (list, tuple)):
    result = await self._execute_parallel_computation(input_data)
else:
    result = await self._execute_sequential_computation(input_data)
```

---

## Contract Models

### ModelContractBase

**Purpose**: Abstract foundation for all contract models
**File**: `src/omnibase_core/models/contracts/model_contract_base.py`
**Stability**: v1.0.0 - INTERFACE LOCKED

#### Structure

```python
class ModelContractBase(BaseModel, ABC):
    """
    Abstract base for 4-node architecture contract models.

    ZERO TOLERANCE: No Any types allowed in implementation.
    """

    # Interface version
    INTERFACE_VERSION: ClassVar[ModelSemVer] = ModelSemVer(1, 0, 0)

    # Core identification
    name: str  # Unique contract name
    version: ModelSemVer  # Contract version
    description: str  # Human-readable description
    node_type: EnumNodeType  # ORCHESTRATOR/REDUCER/EFFECT/COMPUTE

    # Model specifications
    input_model: str  # Fully qualified input model class name
    output_model: str  # Fully qualified output model class name

    # Performance & lifecycle
    performance: ModelPerformanceRequirements
    lifecycle: ModelLifecycleConfig

    # Dependencies
    dependencies: list[ModelDependency]
    protocol_interfaces: list[str]

    # Validation
    validation_rules: ModelValidationRules

    # Metadata
    author: str | None
    documentation_url: str | None
    tags: list[str]

    @abstractmethod
    def validate_node_specific_config(self) -> None:
        """Each specialized contract must implement."""
```

### ModelContractEffect

**File**: `src/omnibase_core/models/contracts/model_contract_effect.py`

#### Additional Fields

```python
class ModelContractEffect(ModelContractBase):
    """Contract for NodeEffect implementations."""

    # UUID tracking
    correlation_id: UUID = Field(default_factory=uuid4)
    execution_id: UUID = Field(default_factory=uuid4)

    # Infrastructure pattern support
    node_name: str | None
    tool_specification: StructuredData | None
    service_configuration: StructuredData | None
    input_state: StructuredData | None
    output_state: StructuredData | None
    actions: StructuredDataList | None
    infrastructure: StructuredData | None
    infrastructure_services: StructuredData | None

    # Effect-specific configuration
    io_operations: list[ModelIOOperationConfig]
    transaction_management: ModelTransactionConfig
    retry_policies: ModelEffectRetryConfig
    external_services: list[ModelExternalServiceConfig]
    backup_config: ModelBackupConfig

    # Subcontracts (6 types)
    event_type_subcontract: ModelEventTypeSubcontract
    routing_subcontract: ModelRoutingSubcontract
    caching_subcontract: ModelCachingSubcontract
    # ... (state_management, fsm, aggregation)
```

### Contract Usage Pattern

```python
# 1. Define contract
contract = ModelContractEffect(
    name="file_writer_effect",
    version=ModelSemVer(1, 0, 0),
    description="Atomic file write with transaction support",
    node_type=EnumNodeType.EFFECT,
    input_model="ModelEffectInput",
    output_model="ModelEffectOutput",
    io_operations=[
        ModelIOOperationConfig(
            operation_type="file_write",
            atomic=True,
            backup_enabled=True,
        )
    ],
    transaction_management=ModelTransactionConfig(enabled=True),
    retry_policies=ModelEffectRetryConfig(
        max_attempts=3,
        base_delay_ms=1000,
        circuit_breaker_enabled=True,
    ),
)

# 2. Execute via node
container = await create_model_onex_container()
node = NodeEffect(container)
result = await node.execute_effect(contract)
```

---

## Dependency Injection (ModelONEXContainer)

**File**: `src/omnibase_core/models/container/model_onex_container.py`

### Architecture

```python
class ModelONEXContainer:
    """
    Dependency injection container with:
    - Service resolution with caching
    - Observable dependency injection
    - Contract-driven service registration
    - Performance monitoring
    """

    def __init__(
        self,
        enable_performance_cache: bool = False,
        cache_dir: Path | None = None,
        compute_cache_config: ModelComputeCacheConfig | None = None,
        enable_service_registry: bool = True,
    ) -> None:
        """Initialize container with optional optimizations."""

        self._base_container = _BaseModelONEXContainer()
        self.compute_cache_config = compute_cache_config or ModelComputeCacheConfig()
        self._service_cache: dict[str, Any] = {}
        self._service_registry: ServiceRegistry | None = None
```

### Service Resolution

```python
# Async resolution
async def get_service_async(
    self,
    protocol_type: type[T],
    service_name: str | None = None,
    correlation_id: UUID | None = None,
) -> T:
    """
    Resolve service with:
    1. Cache lookup
    2. ServiceRegistry resolution (new DI system)
    3. Legacy resolution fallback
    """

# Sync resolution
def get_service_sync(
    self,
    protocol_type: type[T],
    service_name: str | None = None,
) -> T:
    """Synchronous wrapper around async resolution."""

# Optional resolution
def get_service_optional(
    self,
    protocol_type: type[T],
    service_name: str | None = None,
) -> T | None:
    """Returns None if service unavailable (no exception)."""
```

### Usage Examples

```python
# 1. Create container
container = await create_model_onex_container(
    enable_cache=True,
    compute_cache_config=ModelComputeCacheConfig(
        max_size=1000,
        ttl_seconds=1800,
        eviction_policy="lru",
    ),
)

# 2. Resolve services
logger = await container.get_service_async(ProtocolLogger)
config = container.get_service_optional(NodeConfigProvider)

# 3. Initialize node with container
node = NodeOrchestrator(container)
```

---

## Error Handling (ModelOnexError)

**File**: `src/omnibase_core/models/errors/model_onex_error.py`

### Structure

```python
class ModelOnexError(Exception):
    """
    Exception with Pydantic model integration.

    Provides:
    - Structured error data
    - Correlation tracking
    - CLI exit code mapping
    - Serialization support
    """

    def __init__(
        self,
        message: str,
        error_code: EnumOnexErrorCode | str | None = None,
        status: EnumOnexStatus = EnumOnexStatus.ERROR,
        correlation_id: UUID | None = None,
        timestamp: datetime | None = None,
        **context: Any,
    ) -> None:
        """
        Initialize error with:
        - Auto-generated correlation_id if not provided
        - Timestamp defaulting to now
        - Structured context storage
        """
        super().__init__(message)

        # Store in Pydantic model
        self.model = _ModelOnexErrorData(
            message=message,
            error_code=error_code,
            status=status,
            correlation_id=correlation_id or uuid4(),
            timestamp=timestamp or datetime.now(UTC),
            context=context,
        )
```

### Factory Methods

```python
# With specific correlation ID
error = ModelOnexError.with_correlation_id(
    message="Transaction failed",
    correlation_id=existing_correlation_id,
    error_code=EnumCoreErrorCode.OPERATION_FAILED,
)

# With new correlation ID (returns tuple)
error, correlation_id = ModelOnexError.with_new_correlation_id(
    message="New workflow failed",
    error_code=EnumCoreErrorCode.WORKFLOW_EXECUTION_FAILED,
)

# From existing exception
error = ModelOnexError.from_exception(
    exception=original_exception,
    error_code=EnumCoreErrorCode.DEPENDENCY_UNAVAILABLE,
)
```

### Properties & Methods

```python
# Properties
error.message  # str
error.error_code  # EnumOnexErrorCode | str | None
error.status  # EnumOnexStatus
error.correlation_id  # UUID (never None)
error.timestamp  # datetime | None
error.context  # dict[str, Any]

# CLI exit code
exit_code = error.get_exit_code()  # int

# Serialization
error_dict = error.model_dump()
error_json = error.model_dump_json()

# Deserialization
error = ModelOnexError.from_dict(error_dict)
error = ModelOnexError.from_json(error_json)
```

---

## Core Patterns

### 1. Initialization Lifecycle

All nodes follow this pattern:

```python
class NodeXxx(NodeCoreBase):
    def __init__(self, container: ModelONEXContainer) -> None:
        """
        Initialize node with dependency injection.

        Pattern:
        1. Call super().__init__(container)
        2. Set default configuration
        3. Initialize internal state
        4. Register built-in handlers
        """
        super().__init__(container)

        # Set defaults (overridden in _initialize_node_resources)
        self.config_value = default_value

        # Initialize state
        self.internal_state = {}

        # Register handlers
        self._register_builtin_handlers()

    async def _initialize_node_resources(self) -> None:
        """
        Load configuration from NodeConfigProvider.

        Pattern:
        1. Get optional NodeConfigProvider from container
        2. Load configuration values
        3. Update instance attributes
        4. Initialize resources (thread pools, etc.)
        5. Log initialization
        """
        config = self.container.get_service_optional(NodeConfigProvider)
        if config:
            value = await config.get_performance_config("key", default=default)
            if isinstance(value, expected_type):
                self.config_value = value

    async def _cleanup_node_resources(self) -> None:
        """
        Clean up resources.

        Pattern:
        1. Cancel active operations
        2. Close connections
        3. Shutdown thread pools
        4. Clear caches
        5. Log cleanup
        """
```

### 2. Execute Method Signatures

Each node type has a specific execute signature:

```python
# Orchestrator
async def process(
    self,
    input_data: ModelOrchestratorInput,
) -> ModelOrchestratorOutput:
    """Execute workflow coordination."""

# Reducer
async def process(
    self,
    input_data: ModelReducerInput[T_Input],
) -> ModelReducerOutput[T_Output]:
    """Execute reduction operation."""

# Effect
async def execute_effect(
    self,
    contract: ModelContractEffect,
) -> ModelEffectOutput:
    """Execute effect based on contract."""

async def process(
    self,
    input_data: ModelEffectInput,
) -> ModelEffectOutput:
    """Execute effect operation."""

# Compute
async def process(
    self,
    input_data: ModelComputeInput[T_Input],
) -> ModelComputeOutput[T_Output]:
    """Execute pure computation."""
```

### 3. Error Handling Pattern

```python
async def process(self, input_data: ModelInput) -> ModelOutput:
    start_time = time.time()

    try:
        # 1. Validate input
        self._validate_input(input_data)

        # 2. Execute operation
        result = await self._execute_operation(input_data)

        # 3. Update metrics (success)
        processing_time = (time.time() - start_time) * 1000
        await self._update_metrics(processing_time, success=True)

        return ModelOutput(result=result, ...)

    except Exception as e:
        # 4. Update metrics (failure)
        processing_time = (time.time() - start_time) * 1000
        await self._update_metrics(processing_time, success=False)

        # 5. Raise structured error
        raise ModelOnexError(
            error_code=EnumCoreErrorCode.OPERATION_FAILED,
            message=f"Operation failed: {e}",
            context={
                "node_id": str(self.node_id),
                "operation_id": str(input_data.operation_id),
            },
        ) from e
```

### 4. Dependency Injection Pattern

```python
# Container creation
container = await create_model_onex_container(
    enable_cache=True,
    compute_cache_config=ModelComputeCacheConfig(),
    enable_service_registry=True,
)

# Node initialization
node = NodeEffect(
    container=container,
    on_rollback_failure=handle_rollback_failure,
)

# Service resolution within node
config = self.container.get_service_optional(NodeConfigProvider)
logger = await self.container.get_service_async(ProtocolLogger)
```

---

## Code Examples

### Example 1: Orchestrator Workflow

```python
from omnibase_core.nodes.node_orchestrator import NodeOrchestrator
from omnibase_core.models.model_orchestrator_input import ModelOrchestratorInput
from omnibase_core.enums.enum_orchestrator_types import EnumExecutionMode
from uuid import uuid4

# Create container and node
container = await create_model_onex_container()
orchestrator = NodeOrchestrator(container)

# Define workflow
workflow_input = ModelOrchestratorInput(
    workflow_id=uuid4(),
    steps=[
        {
            "step_id": str(uuid4()),
            "step_name": "Validate Input",
            "execution_mode": EnumExecutionMode.SEQUENTIAL,
            "actions": [
                {
                    "action_type": EnumActionType.COMPUTE,
                    "target_node_type": "NodeCompute",
                    "payload": {"computation_type": "validation"},
                }
            ],
        },
        {
            "step_id": str(uuid4()),
            "step_name": "Process Data",
            "execution_mode": EnumExecutionMode.PARALLEL,
            "actions": [
                {
                    "action_type": EnumActionType.REDUCE,
                    "target_node_type": "NodeReducer",
                    "payload": {"reduction_type": "aggregate"},
                }
            ],
        },
    ],
    execution_mode=EnumExecutionMode.SEQUENTIAL,
    dependency_resolution_enabled=True,
)

# Execute
result = await orchestrator.process(workflow_input)
print(f"Completed {result.steps_completed} steps")
print(f"Emitted {len(result.actions_emitted)} actions")
```

### Example 2: Effect with Transaction

```python
from omnibase_core.nodes.node_effect import NodeEffect
from pathlib import Path

# Create node
container = await create_model_onex_container()
effect_node = NodeEffect(container)

# Use transaction context
async with effect_node.transaction_context() as tx:
    # Write file 1 (adds rollback to transaction)
    result1 = await effect_node.execute_file_operation(
        operation_type="write",
        file_path=Path("/tmp/file1.txt"),
        data="content 1",
        atomic=True,
    )

    # Write file 2 (adds rollback to transaction)
    result2 = await effect_node.execute_file_operation(
        operation_type="write",
        file_path=Path("/tmp/file2.txt"),
        data="content 2",
        atomic=True,
    )

    # Automatic commit on success
    # Automatic rollback on exception (both files deleted)
```

### Example 3: Reducer with Streaming

```python
from omnibase_core.nodes.node_reducer import NodeReducer
from omnibase_core.models.model_reducer_input import ModelReducerInput
from omnibase_core.enums.enum_reducer_types import (
    EnumReductionType,
    EnumStreamingMode,
    EnumConflictResolution,
)

# Create node
container = await create_model_onex_container()
reducer = NodeReducer(container)

# Register custom reduction
def aggregate_tickets(data, input_data, conflict_resolver):
    grouped = {}
    for ticket in data:
        status = ticket["status"]
        if status not in grouped:
            grouped[status] = []
        grouped[status].append(ticket)
    return grouped

reducer.register_reduction_function(
    EnumReductionType.AGGREGATE,
    aggregate_tickets,
)

# Execute with streaming
reduction_input = ModelReducerInput(
    data=large_ticket_list,  # 10,000 tickets
    reduction_type=EnumReductionType.AGGREGATE,
    streaming_mode=EnumStreamingMode.INCREMENTAL,
    batch_size=1000,
    conflict_resolution=EnumConflictResolution.LAST_WRITE_WINS,
)

result = await reducer.process(reduction_input)
print(f"Processed {result.items_processed} items")
print(f"In {result.batches_processed} batches")
```

### Example 4: Compute with Caching

```python
from omnibase_core.nodes.node_compute import NodeCompute
from omnibase_core.models.model_compute_input import ModelComputeInput

# Create node with cache config
container = await create_model_onex_container(
    compute_cache_config=ModelComputeCacheConfig(
        max_size=1000,
        ttl_seconds=1800,
        eviction_policy="lru",
    ),
)
compute = NodeCompute(container)

# First call (cache miss)
compute_input = ModelComputeInput(
    data=[1, 2, 3, 4, 5],
    computation_type="sum_numbers",
    cache_enabled=True,
    parallel_enabled=False,
)

result1 = await compute.process(compute_input)
print(f"First call: {result1.processing_time_ms}ms (cache_hit={result1.cache_hit})")

# Second call (cache hit)
result2 = await compute.process(compute_input)
print(f"Second call: {result2.processing_time_ms}ms (cache_hit={result2.cache_hit})")
# Output: Second call: 0.0ms (cache_hit=True)
```

---

## Key Takeaways

1. **Stability Guarantees**: All node base classes have v1.0.0 INTERFACE LOCKED - breaking changes require major version bump

2. **Dependency Injection**: All nodes receive ModelONEXContainer in constructor for service resolution

3. **Contract-Driven**: ModelContractBase and specialized contracts define node behavior with validation

4. **Error Handling**: ModelOnexError provides structured errors with correlation tracking and CLI exit codes

5. **Lifecycle Management**: Nodes implement `_initialize_node_resources()` and `_cleanup_node_resources()` for resource management

6. **Type Safety**: ZERO TOLERANCE for Any types in production code - all types must be explicit

7. **Performance**: Built-in caching (Compute), transaction rollback (Effect), streaming (Reducer), and parallel execution (Orchestrator)

8. **Thread Safety**: NodeEffect and NodeCompute have thread safety warnings - use separate instances per thread

9. **Pure FSM**: NodeReducer follows PURE FSM pattern - emits Intents instead of direct side effects

10. **RSD Integration**: All nodes have RSD-specific methods for ticket lifecycle, dependency management, and data aggregation

---

**Generated**: 2025-11-09
**For**: Intelligent Context Proxy architecture revision
**Next**: Apply these patterns to context proxy implementation
