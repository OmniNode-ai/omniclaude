# Omnibase Core Node Paradigm - Comprehensive Study
**Generated**: 2025-10-21
**Source**: omnibase_core v2.0+ (doc_fixes branch)
**Purpose**: Autonomous code generation reference

## Table of Contents
1. [Overview](#overview)
2. [Node Architecture](#node-architecture)
3. [Naming Conventions](#naming-conventions)
4. [File Structure](#file-structure)
5. [Code Generation Requirements](#code-generation-requirements)
6. [Mandatory Patterns](#mandatory-patterns)
7. [Type Safety](#type-safety)
8. [Contract System](#contract-system)
9. [Examples](#examples)
10. [Validation Checklist](#validation-checklist)
11. [Breaking Changes](#breaking-changes)

---

## Overview

### What is omnibase_core?

Omnibase_core is the foundational framework for ONEX (ONEX Four-Node Architecture), providing base classes, dependency injection, and essential models for building scalable microservices.

**Key Principles**:
- **4-Node Architecture**: EFFECT → COMPUTE → REDUCER → ORCHESTRATOR
- **Protocol-Driven DI**: `container.get_service("ProtocolName")` pattern
- **Zero Boilerplate**: Base classes eliminate 80+ lines per node
- **Type Safety**: Full Pydantic validation with generic typing
- **Poetry-First**: ALL Python commands use `poetry run`

### Repository Structure
```
omnibase_core/
├── src/omnibase_core/
│   ├── core/                           # Core framework
│   │   ├── infrastructure_service_bases.py  # Unified 4-node exports
│   │   ├── node_effect_service.py
│   │   ├── node_compute_service.py
│   │   ├── node_reducer_service.py
│   │   ├── node_orchestrator_service.py
│   │   └── onex_container.py
│   ├── nodes/                          # Node implementations
│   │   ├── node_compute.py
│   │   ├── node_effect.py
│   │   ├── node_reducer.py
│   │   └── node_orchestrator.py
│   ├── models/                         # Data models
│   │   ├── core/
│   │   ├── container/
│   │   └── contracts/
│   ├── enums/                          # Enumerations
│   └── errors/                         # Error handling
├── docs/                               # Documentation
│   ├── INDEX.md
│   ├── guides/node-building/           # Node tutorials
│   ├── architecture/                   # Architecture docs
│   └── reference/templates/            # Node templates
└── tests/
```

---

## Node Architecture

### The Four Node Types

#### 1. **EFFECT Node**
**Purpose**: External I/O and side effects

**Characteristics**:
- API calls, database operations, file I/O
- Side effects allowed
- Idempotency important
- Connection pooling and retry logic
- Thread-unsafe by default

**When to Use**:
- Reading/writing to database
- Calling external APIs
- File system operations
- Message queue interactions

**Base Class**: `NodeEffectService` or `NodeEffect` (from `omnibase_core.core.infrastructure_service_bases`)

**Example**:
```python
from omnibase_core.core.infrastructure_service_bases import NodeEffectService

class NodeDatabaseWriterEffect(NodeEffectService):
    """EFFECT node for database write operations."""

    async def execute_effect(self, contract: ModelContractEffect) -> ModelEffectOutput:
        """Execute database write with retry logic."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute(contract.query, contract.parameters)
        return ModelEffectOutput(result=result, success=True)
```

---

#### 2. **COMPUTE Node**
**Purpose**: Pure computational operations

**Characteristics**:
- No side effects (pure functions preferred)
- Deterministic: same input → same output
- Caching for expensive operations
- Parallel processing support
- Thread-unsafe (cache state is mutable)

**When to Use**:
- Data transformation
- Calculations and algorithms
- Validation logic
- Filtering and processing

**Base Class**: `NodeComputeService` or `NodeCompute`

**Example**:
```python
from omnibase_core.core.infrastructure_service_bases import NodeComputeService

class NodePriceCalculatorCompute(NodeComputeService):
    """COMPUTE node for price calculations."""

    async def execute_compute(self, contract: ModelContractCompute) -> ModelComputeOutput:
        """Calculate price with tax and discounts."""
        subtotal = sum(item.price * item.qty for item in contract.input_data)
        tax = subtotal * 0.08
        total = subtotal + tax

        return ModelComputeOutput(
            result={"subtotal": subtotal, "tax": tax, "total": total},
            processing_time_ms=5.2,
            cache_hit=False
        )
```

---

#### 3. **REDUCER Node**
**Purpose**: State aggregation and pure FSM transitions

**Characteristics**:
- Pure FSM pattern: `δ(state, action) → (new_state, intents[])`
- **Intent-based side effects**: Emit intents instead of executing effects
- Data aggregation without direct side effects
- Incremental and streaming processing
- Transactional consistency

**When to Use**:
- Aggregating data from multiple sources
- State management with FSM transitions
- Summarizing or consolidating results
- Grouping and categorization

**Base Class**: `NodeReducerService` or `NodeReducer`

**CRITICAL**: Reducers must emit **ModelIntent** for side effects, NOT execute them directly.

**Example**:
```python
from omnibase_core.core.infrastructure_service_bases import NodeReducerService
from omnibase_core.models.model_intent import ModelIntent, EnumIntentType

class NodeOrderProcessingReducer(NodeReducerService):
    """Pure FSM Reducer with intent emission."""

    async def execute_reduction(self, contract: ModelContractReducer) -> ModelReducerOutput:
        """Execute pure state transition with intent emission."""
        current_state = await self._load_current_state(contract)

        # Pure state transition
        transition_result = self._apply_fsm_transition(
            current_state,
            contract.action,
            contract.payload
        )

        # Return new state + intents (NOT direct side effects!)
        return ModelReducerOutput(
            aggregated_data=transition_result.new_state,
            intents=transition_result.intents  # Effect node executes these
        )
```

### Coordination Pattern: Intent Publisher Mixin

**Purpose**: Allows REDUCER/COMPUTE/ORCHESTRATOR nodes to publish events while maintaining ONEX purity.

**Pattern** (Conceptual - actual implementation in omnibase_core may differ):
```python
# NOTE: Class names and imports shown are conceptual
# Consult omnibase_core documentation for actual implementation

class NodeMetricsAggregatorReducer(NodeReducer, IntentPublisherMixin):
    """REDUCER with intent-based event publishing."""

    def __init__(self, container):
        super().__init__(container)
        self._init_intent_publisher(container)  # Initialize mixin

    async def execute_reduction(self, events):
        # Pure aggregation (no I/O)
        metrics = self._aggregate_metrics(events)

        # Coordination I/O via intent (not direct publishing)
        await self.publish_event_intent(
            target_topic="metrics.processed",
            target_key=str(metrics.id),
            event=MetricsEvent(data=metrics)
        )

        return metrics
```

**When to Use**:
- ✅ REDUCER nodes need to publish aggregated results
- ✅ COMPUTE nodes need to publish computed results
- ✅ ORCHESTRATOR nodes need coordination events
- ❌ EFFECT nodes (they perform I/O directly)

**Architecture Benefits**:
- **ONEX Compliance**: Node logic stays pure (no direct I/O)
- **Testability**: Intent building is deterministic and mockable
- **Flexibility**: Can swap message brokers without changing node logic
- **Observability**: All coordination intents logged and traceable

**Note**: This pattern is implemented in omninode_bridge and will be available in omnibase_core. Consult the latest omnibase_core documentation for current class names and import paths.

---

#### 4. **ORCHESTRATOR Node**
**Purpose**: Workflow coordination and dependency management

**Characteristics**:
- Coordinates multiple nodes
- Sequential or parallel execution
- Dependency resolution
- Error recovery and compensation
- Lease-based single-writer semantics

**When to Use**:
- Multi-step workflows
- Coordinating multiple services
- Complex business processes
- Saga patterns and compensating transactions

**Base Class**: `NodeOrchestratorService` or `NodeOrchestrator`

**CRITICAL**: Orchestrators issue **ModelAction** with lease validation, NOT generic thunks.

**Example**:
```python
from omnibase_core.core.infrastructure_service_bases import NodeOrchestratorService
from omnibase_core.models.model_action import ModelAction, EnumActionType

class NodeUserRegistrationOrchestrator(NodeOrchestratorService):
    """Orchestrate user registration workflow."""

    async def execute_orchestration(self, contract: ModelContractOrchestrator):
        """Coordinate multi-step registration with lease management."""
        # Acquire exclusive lease
        lease = await self._acquire_workflow_lease(contract.workflow_id)

        try:
            # Issue actions with lease proof
            validate_action = ModelAction(
                action_type=EnumActionType.DELEGATE_TASK,
                lease_id=lease.lease_id,
                epoch=lease.epoch,
                target_node="compute",
                command_payload={"operation": "validate_user"}
            )

            # Execute with lease validation
            result = await self._execute_validated_action(validate_action)
            return result
        finally:
            await self._release_workflow_lease(lease)
```

---

## Naming Conventions

### **CRITICAL**: SUFFIX-Based Naming (Not Prefix!)

**❌ WRONG** (Prefix):
```python
class EffectDatabaseWriter:      # WRONG!
class ComputePriceCalculator:    # WRONG!
```

**✅ CORRECT** (Suffix):
```python
class NodeDatabaseWriterEffect:       # ✓ Correct
class NodePriceCalculatorCompute:     # ✓ Correct
class NodeMetricsAggregatorReducer:   # ✓ Correct
class NodeWorkflowCoordinatorOrchestrator: # ✓ Correct
```

### File Naming Patterns

| Pattern | Example | Convention |
|---------|---------|------------|
| **Node Classes** | `NodeDatabaseWriterEffect` | `Node<Name><Type>` |
| **Node Files** | `node_database_writer_effect.py` | `node_*_<type>.py` |
| **Models** | `ModelUserProfile` | `Model<Name>` |
| **Model Files** | `model_user_profile.py` | `model_<name>.py` |
| **Enums** | `EnumUserStatus` | `Enum<Name>` |
| **Enum Files** | `enum_user_status.py` | `enum_<name>.py` |
| **Contracts** | `ModelContractEffect` | `ModelContract<Type>` |
| **Contract Files** | `model_contract_effect.py` | `model_contract_<type>.py` |

### Node Type Suffixes (MANDATORY)

| Node Type | Suffix | Example |
|-----------|--------|---------|
| EFFECT | `Effect` | `NodeApiClientEffect` |
| COMPUTE | `Compute` | `NodeDataTransformerCompute` |
| REDUCER | `Reducer` | `NodeStateAggregatorReducer` |
| ORCHESTRATOR | `Orchestrator` | `NodePipelineOrchestratorOrchestrator` |

---

## File Structure

### Recommended Node Module Structure

```
{repository}/
├── src/{repository}/
│   └── nodes/
│       └── node_{domain}_{service}_<type>/
│           └── v1_0_0/
│               ├── __init__.py
│               ├── node.py                    # Main node implementation
│               ├── config.py                  # Configuration models
│               ├── contracts/
│               │   ├── __init__.py
│               │   ├── <type>_contract.py
│               │   └── subcontracts/
│               │       ├── input_subcontract.yaml
│               │       ├── output_subcontract.yaml
│               │       └── config_subcontract.yaml
│               ├── models/
│               │   ├── __init__.py
│               │   ├── model_{domain}_{service}_input.py
│               │   ├── model_{domain}_{service}_output.py
│               │   └── model_{domain}_{service}_config.py
│               ├── enums/
│               │   ├── __init__.py
│               │   └── enum_{domain}_{service}_operation_type.py
│               ├── utils/
│               │   └── # Helper utilities
│               └── manifest.yaml
└── tests/{repository}/
    └── nodes/node_{domain}_{service}_<type>/
        └── v1_0_0/
            ├── test_node.py
            ├── test_config.py
            └── test_models.py
```

**Example**: `node_payment_processor_compute/v1_0_0/`

---

## Code Generation Requirements

### What MUST Be Generated

1. **Node Class**
   - Inherit from correct base class
   - Implement required methods
   - Initialize with `ModelONEXContainer`
   - Add type hints (full generic typing)

2. **Input Model**
   - Inherit from `BaseModel` (Pydantic)
   - Define all required fields
   - Add validators for business logic
   - Include correlation_id field

3. **Output Model**
   - Inherit from `BaseModel`
   - Define result structure
   - Include success/error fields
   - Add performance metrics

4. **Configuration Model**
   - Inherit from `BaseNodeConfig` (if available) or `BaseModel`
   - Environment-specific factory methods
   - Validation rules

5. **Operation Type Enum**
   - Inherit from `str, Enum`
   - Define all operation types
   - Helper methods for categorization

6. **YAML Subcontracts** (3 required)
   - `input_subcontract.yaml`
   - `output_subcontract.yaml`
   - `config_subcontract.yaml`

7. **Manifest File**
   - `manifest.yaml` with metadata, dependencies, API specs

### What's Inherited (DON'T Generate)

- Base initialization logic (from `NodeCoreBase`)
- Container management
- Logging infrastructure
- Error handling decorators (use `@standard_error_handling`)
- Protocol-based dependency injection

---

## Mandatory Patterns

### 1. Initialization Pattern

```python
from omnibase_core.infrastructure.node_core_base import NodeCoreBase
from omnibase_core.models.container.model_onex_container import ModelONEXContainer

class NodeMyServiceCompute(NodeCoreBase):
    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize with dependency injection."""
        super().__init__(container)  # MANDATORY

        # Get dependencies from container
        self.logger = container.logger
        self.config = container.compute_cache_config

        # Initialize business-specific components
        self._setup_business_logic()
```

**✅ ALWAYS**:
- Call `super().__init__(container)` first
- Use container for dependency resolution
- Type hint the `container` parameter

**❌ NEVER**:
- Create dependencies manually
- Skip `super().__init__()`
- Use `isinstance()` checks for protocols

---

### 2. Error Handling Pattern

```python
from omnibase_core.errors.model_onex_error import ModelOnexError
from omnibase_core.errors.error_codes import EnumCoreErrorCode
from omnibase_core.decorators.error_handling import standard_error_handling

class NodeMyServiceCompute(NodeCoreBase):
    @standard_error_handling  # RECOMMENDED: Eliminates boilerplate
    async def process(self, input_data):
        """Process with automatic error handling."""
        if validation_fails:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="Validation failed",
                context={"field": "email", "value": input_value}
            )
```

**✅ ALWAYS**:
- Use `ModelOnexError` (not generic `Exception`)
- Include error codes from enums
- Chain exceptions: `raise ModelOnexError(...) from original_error`
- Use `@standard_error_handling` decorator

**❌ NEVER**:
- Raise generic `Exception`
- Swallow exceptions silently
- Return error states instead of raising

---

### 3. Async Method Pattern

```python
async def process(
    self,
    input_data: ModelComputeInput[T_Input]
) -> ModelComputeOutput[T_Output]:
    """
    Process computation with type-safe interface.

    Args:
        input_data: Validated input data

    Returns:
        Computation results with metadata

    Raises:
        ValidationError: If input validation fails
        ModelOnexError: If computation fails
    """
    # Validate input
    self._validate_input(input_data)

    # Execute computation
    result = await self._execute_computation(input_data)

    # Return typed output
    return ModelComputeOutput(
        result=result,
        success=True,
        correlation_id=input_data.correlation_id
    )
```

**✅ ALWAYS**:
- Use `async def` for I/O operations
- Add comprehensive docstrings (Google style)
- Type hint inputs and outputs
- Include correlation_id in all operations

---

### 4. Type Safety Pattern

```python
from typing import Generic, TypeVar
from pydantic import BaseModel

T_Input = TypeVar('T_Input', bound=BaseModel)
T_Output = TypeVar('T_Output', bound=BaseModel)

class NodeMyServiceCompute(
    NodeComputeService[
        ModelMyServiceComputeInput,     # Input type
        ModelMyServiceComputeOutput,    # Output type
        MyServiceComputeConfig          # Config type
    ]
):
    """Fully typed node with generic parameters."""
```

**✅ ALWAYS**:
- Use generic types for flexibility
- Bound TypeVars to `BaseModel`
- Specify all generic parameters

---

### 5. Caching Pattern (COMPUTE Nodes)

```python
from omnibase_core.models.infrastructure import ModelComputeCache

class NodeMyServiceCompute(NodeComputeService):
    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)

        # Initialize cache with container config
        cache_config = container.compute_cache_config
        self.computation_cache = ModelComputeCache(
            max_size=cache_config.max_size,
            ttl_seconds=cache_config.ttl_seconds
        )

    async def process(self, input_data):
        # Check cache
        cache_key = self._generate_cache_key(input_data)
        cached = self.computation_cache.get(cache_key)

        if cached:
            return ModelComputeOutput(result=cached, cache_hit=True)

        # Compute and cache
        result = await self._compute(input_data)
        self.computation_cache.set(cache_key, result)

        return ModelComputeOutput(result=result, cache_hit=False)
```

---

### 6. Intent Emission Pattern (REDUCER Nodes)

```python
from omnibase_core.models.model_intent import ModelIntent, EnumIntentType
from uuid import uuid4

class NodeMyServiceReducer(NodeReducerService):
    async def execute_reduction(self, contract: ModelContractReducer):
        """Execute pure FSM transition with intent emission."""
        # Pure state computation
        new_state = self._calculate_new_state(contract)

        # Emit intents for side effects (DON'T execute them!)
        intents = [
            ModelIntent(
                intent_id=uuid4(),
                intent_type=EnumIntentType.DATABASE_WRITE,
                target="orders_table",
                payload={"operation": "insert", "data": new_state},
                correlation_id=contract.correlation_id
            )
        ]

        return ModelReducerOutput(
            aggregated_data=new_state,
            intents=intents  # Effect node will execute these
        )
```

**✅ ALWAYS** (for REDUCER):
- Emit `ModelIntent` for all side effects
- Keep state transitions pure
- Let EFFECT nodes execute intents

**❌ NEVER** (for REDUCER):
- Execute database writes directly
- Call external APIs
- Perform I/O operations

---

### 7. Action Issuance Pattern (ORCHESTRATOR Nodes)

```python
from omnibase_core.models.model_action import ModelAction, EnumActionType
from uuid import uuid4

class NodeMyServiceOrchestrator(NodeOrchestratorService):
    async def execute_orchestration(self, contract):
        """Orchestrate with lease-based actions."""
        # Acquire lease
        lease = await self._acquire_workflow_lease(contract.workflow_id)

        try:
            # Issue action with lease proof
            action = ModelAction(
                action_id=uuid4(),
                action_type=EnumActionType.DELEGATE_TASK,
                lease_id=lease.lease_id,  # Proves ownership
                epoch=lease.epoch,        # Optimistic concurrency
                target_node="compute",
                command_payload={"task": "validate"},
                correlation_id=contract.correlation_id
            )

            # Execute with validation
            result = await self._execute_validated_action(action)
            return result
        finally:
            await self._release_workflow_lease(lease)
```

**✅ ALWAYS** (for ORCHESTRATOR):
- Acquire lease before issuing actions
- Include lease_id and epoch in actions
- Release lease in finally block

**❌ NEVER** (for ORCHESTRATOR):
- Use generic callbacks/thunks
- Skip lease validation
- Share actions across workflows

---

## Type Safety

### Pydantic Model Patterns

**All models MUST inherit from `BaseModel`**:

```python
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any
from uuid import UUID

class ModelMyServiceInput(BaseModel):
    """Input model with validation."""

    operation_type: str = Field(
        description="Type of operation to perform",
        regex="^(create|update|delete)$"
    )

    data: Dict[str, Any] = Field(
        description="Operation data"
    )

    correlation_id: UUID = Field(
        description="Request correlation ID"
    )

    optional_field: Optional[str] = Field(
        default=None,
        description="Optional parameter"
    )

    @validator('data')
    def validate_data(cls, v, values):
        """Custom validation logic."""
        if not v:
            raise ValueError("Data cannot be empty")
        return v

    class Config:
        """Pydantic configuration."""
        validate_assignment = True
        extra = "forbid"  # Reject unknown fields
```

**Key Requirements**:
- Use `Field()` for all fields with descriptions
- Add `@validator` for complex validation
- Set `extra = "forbid"` to reject unknown fields
- Always include `correlation_id: UUID`

---

## Contract System

### Contract Structure

All ONEX operations use typed contracts:

```python
from omnibase_core.models.contracts.model_contract_effect import ModelContractEffect
from omnibase_core.models.contracts.model_contract_compute import ModelContractCompute
from omnibase_core.models.contracts.model_contract_reducer import ModelContractReducer
from omnibase_core.models.contracts.model_contract_orchestrator import ModelContractOrchestrator
```

### Subcontract Types (6 types)

1. **FSM Subcontract**: Finite state machine transitions
2. **Event Type Subcontract**: Event processing definitions
3. **Aggregation Subcontract**: Data aggregation rules
4. **State Management Subcontract**: State persistence
5. **Routing Subcontract**: Message routing
6. **Caching Subcontract**: Cache strategies

**Example**:
```python
from omnibase_core.models.contracts.subcontracts.model_aggregation_subcontract import ModelAggregationSubcontract

aggregation = ModelAggregationSubcontract(
    aggregation_functions=[...],
    data_grouping=ModelDataGrouping(...),
    performance_config=ModelAggregationPerformance(...),
    correlation_id=uuid4()
)
```

---

## Examples

### Complete COMPUTE Node Example

```python
"""Price calculator COMPUTE node."""

from typing import Any, Dict
from uuid import UUID
import time

from pydantic import BaseModel, Field
from omnibase_core.core.infrastructure_service_bases import NodeComputeService
from omnibase_core.models.container.model_onex_container import ModelONEXContainer
from omnibase_core.errors.model_onex_error import ModelOnexError
from omnibase_core.errors.error_codes import EnumCoreErrorCode

# Input Model
class ModelPriceCalculatorInput(BaseModel):
    """Input for price calculation."""
    items: list[Dict[str, Any]] = Field(description="Cart items")
    discount_code: str | None = Field(default=None, description="Discount code")
    correlation_id: UUID = Field(description="Request correlation ID")

# Output Model
class ModelPriceCalculatorOutput(BaseModel):
    """Output from price calculation."""
    subtotal: float = Field(description="Subtotal before tax/discount")
    discount: float = Field(description="Discount amount")
    tax: float = Field(description="Tax amount")
    total: float = Field(description="Final total")
    correlation_id: UUID
    processing_time_ms: float
    success: bool = True

# Node Implementation
class NodePriceCalculatorCompute(NodeComputeService):
    """COMPUTE node for price calculations."""

    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)
        self.tax_rate = 0.08  # 8% tax

    async def process(
        self,
        input_data: ModelPriceCalculatorInput
    ) -> ModelPriceCalculatorOutput:
        """Calculate price with tax and discounts."""
        start = time.time()

        try:
            # Pure computation - no side effects
            subtotal = sum(
                item.get('price', 0) * item.get('quantity', 1)
                for item in input_data.items
            )

            discount = self._calculate_discount(
                subtotal,
                input_data.discount_code
            )

            tax = (subtotal - discount) * self.tax_rate
            total = subtotal - discount + tax

            return ModelPriceCalculatorOutput(
                subtotal=subtotal,
                discount=discount,
                tax=tax,
                total=total,
                correlation_id=input_data.correlation_id,
                processing_time_ms=(time.time() - start) * 1000,
                success=True
            )

        except Exception as e:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.COMPUTATION_ERROR,
                message=f"Price calculation failed: {str(e)}",
                context={"items_count": len(input_data.items)}
            ) from e

    def _calculate_discount(self, subtotal: float, code: str | None) -> float:
        """Calculate discount amount."""
        if not code:
            return 0.0

        # Simple discount logic
        discounts = {
            "SAVE10": subtotal * 0.10,
            "SAVE20": subtotal * 0.20
        }
        return discounts.get(code, 0.0)
```

---

## Validation Checklist

### Pre-Generation Checklist

- [ ] Determine correct node type (EFFECT/COMPUTE/REDUCER/ORCHESTRATOR)
- [ ] Define clear input/output contracts
- [ ] Identify all operation types
- [ ] Plan configuration requirements
- [ ] Define validation rules

### Code Generation Checklist

- [ ] **Naming**: Suffix-based (`Node<Name><Type>`)
- [ ] **File Structure**: Correct directory hierarchy
- [ ] **Inheritance**: Correct base class
- [ ] **Initialization**: `super().__init__(container)` called
- [ ] **Type Hints**: All methods have type annotations
- [ ] **Docstrings**: Google-style docstrings for all public methods
- [ ] **Error Handling**: `ModelOnexError` with proper codes
- [ ] **Correlation IDs**: Included in all models
- [ ] **Pydantic Models**: `BaseModel` inheritance
- [ ] **Validators**: Field validators where needed
- [ ] **Config Class**: `validate_assignment=True`, `extra="forbid"`

### Node-Specific Checks

**EFFECT Node**:
- [ ] Connection pooling implemented
- [ ] Retry logic for transient failures
- [ ] Idempotency keys used
- [ ] External service error handling

**COMPUTE Node**:
- [ ] Pure functions (no side effects)
- [ ] Caching layer initialized
- [ ] Performance metrics tracked
- [ ] Parallel processing support (if needed)

**REDUCER Node**:
- [ ] Pure FSM transitions
- [ ] Intent emission (NOT direct execution)
- [ ] State immutability preserved
- [ ] Transactional consistency

**ORCHESTRATOR Node**:
- [ ] Lease acquisition/release
- [ ] Action validation (lease_id + epoch)
- [ ] Dependency resolution
- [ ] Error compensation logic

### Post-Generation Checklist

- [ ] Run `poetry run mypy` for type checking
- [ ] Run `poetry run pytest` for tests
- [ ] Run `poetry run black` for formatting
- [ ] Validate contract YAML files
- [ ] Check manifest.yaml completeness

---

## Breaking Changes from Old Patterns

### 1. Container-Based DI (NEW)

**Old**:
```python
class NodeMyService:
    def __init__(self, logger, db_pool, cache):
        self.logger = logger
        self.db_pool = db_pool
        self.cache = cache
```

**New**:
```python
class NodeMyService(NodeCoreBase):
    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)
        self.logger = container.logger
        self.db_pool = container.get_service("ProtocolDatabasePool")
```

---

### 2. Suffix-Based Naming (NEW)

**Old**: `EffectDatabaseWriter` (prefix)
**New**: `NodeDatabaseWriterEffect` (suffix)

---

### 3. Pure FSM with Intents (REDUCER)

**Old** (Direct side effects):
```python
class NodeMyReducer:
    async def execute_reduction(self, contract):
        new_state = self._calculate(contract)
        await self.db.insert("orders", new_state)  # ❌ WRONG
        return new_state
```

**New** (Intent emission):
```python
class NodeMyReducer(NodeReducerService):
    async def execute_reduction(self, contract):
        new_state = self._calculate(contract)
        intents = [
            ModelIntent(intent_type=EnumIntentType.DATABASE_WRITE, ...)
        ]
        return ModelReducerOutput(
            aggregated_data=new_state,
            intents=intents  # ✅ CORRECT
        )
```

---

### 4. Structured Actions (ORCHESTRATOR)

**Old** (Generic thunks):
```python
class GenericThunk:
    def __init__(self, callback):
        self.callback = callback  # ❌ NOT serializable, no ownership
```

**New** (Structured actions with lease):
```python
action = ModelAction(
    action_type=EnumActionType.UPDATE_STATE,
    lease_id=lease.lease_id,  # ✅ Ownership proof
    epoch=current_epoch,      # ✅ Optimistic concurrency
    target_node="reducer",
    command_payload={...}
)
```

---

### 5. Poetry-First Development

**Old**:
```bash
python -m pytest tests/
pip install package-name
```

**New**:
```bash
poetry run pytest tests/
poetry add package-name
```

**Critical**: ALL Python commands MUST use `poetry run`.

---

## Additional Resources

### Documentation Locations

- **Main Docs**: `/Volumes/PRO-G40/Code/omnibase_core/docs/INDEX.md`
- **Node Building**: `/Volumes/PRO-G40/Code/omnibase_core/docs/guides/node-building/README.md`
- **Templates**: `/Volumes/PRO-G40/Code/omnibase_core/docs/reference/templates/`
- **Architecture**: `/Volumes/PRO-G40/Code/omnibase_core/docs/architecture/ONEX_FOUR_NODE_ARCHITECTURE.md`
- **Error Handling**: `/Volumes/PRO-G40/Code/omnibase_core/docs/conventions/ERROR_HANDLING_BEST_PRACTICES.md`

### Example Implementations

- **COMPUTE**: `/Volumes/PRO-G40/Code/omnibase_core/src/omnibase_core/nodes/node_compute.py`
- **EFFECT**: `/Volumes/PRO-G40/Code/omnibase_core/src/omnibase_core/nodes/node_effect.py`
- **REDUCER**: `/Volumes/PRO-G40/Code/omnibase_core/src/omnibase_core/nodes/node_reducer.py`
- **ORCHESTRATOR**: `/Volumes/PRO-G40/Code/omnibase_core/src/omnibase_core/nodes/node_orchestrator.py`

### Key Concepts to Remember

1. **4-Node Architecture**: EFFECT → COMPUTE → REDUCER → ORCHESTRATOR
2. **Suffix-Based Naming**: `Node<Name><Type>` (e.g., `NodePriceCalculatorCompute`)
3. **Container-Based DI**: `container.get_service("ProtocolName")`
4. **Pure Reducers**: Emit intents, don't execute side effects
5. **Structured Actions**: Use `ModelAction` with lease validation
6. **Type Safety**: Full Pydantic validation with generic typing
7. **Poetry-First**: All commands use `poetry run`

---

**End of Document**

This comprehensive guide provides everything needed for autonomous code generation of ONEX-compliant nodes in omnibase_core v2.0+.
