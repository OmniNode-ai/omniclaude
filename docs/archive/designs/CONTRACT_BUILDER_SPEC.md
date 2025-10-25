# Contract Builder Specification

**Generated**: 2025-10-21
**Purpose**: Technical specification for Pydantic-based contract generation

---

## Overview

The Contract Builder system replaces string-based contract generation with type-safe Pydantic models from `omnibase_core`. This specification defines how to use omnibase_core contract models to generate YAML contracts for all 4 node types.

---

## Architecture

### Components

```
┌─────────────────────────────────────────┐
│         GenerationPipeline              │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│     ContractBuilderFactory              │
│  - Selects builder by node type         │
│  - Validates builder registration       │
└──────────────┬──────────────────────────┘
               │
       ┌───────┴───────┬───────┬──────────┐
       ▼               ▼       ▼          ▼
┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
│   Effect   │  │  Compute   │  │  Reducer   │  │Orchestrator│
│  Builder   │  │  Builder   │  │  Builder   │  │  Builder   │
└────────────┘  └────────────┘  └────────────┘  └────────────┘
       │               │              │               │
       ▼               ▼              ▼               ▼
┌─────────────────────────────────────────────────────────────┐
│          omnibase_core.models.contracts                     │
│  - ModelContractEffect                                      │
│  - ModelContractCompute                                     │
│  - ModelContractReducer                                     │
│  - ModelContractOrchestrator                                │
└─────────────────────────────────────────────────────────────┘
```

---

## Base Contract Builder

### Interface

```python
from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, TypeVar
from uuid import UUID
from pathlib import Path

from omnibase_core.models.contracts.model_contract_base import ModelContractBase
from pydantic import BaseModel

T_Contract = TypeVar('T_Contract', bound=ModelContractBase)


class ContractBuilder(ABC, Generic[T_Contract]):
    """Base class for all contract builders.

    Provides common functionality for building ONEX contracts from
    parsed prompt data. Subclasses must implement build() method
    for specific contract types.

    Type Parameters:
        T_Contract: Specific contract model type (Effect, Compute, etc.)

    Example:
        ```python
        class EffectContractBuilder(ContractBuilder[ModelContractEffect]):
            def build(self, data: Dict[str, Any]) -> ModelContractEffect:
                return ModelContractEffect(
                    name=data["service_name"],
                    version="1.0.0",
                    description=data["description"],
                    # ... populate all required fields
                )
        ```
    """

    def __init__(self, correlation_id: UUID | None = None) -> None:
        """Initialize builder with optional correlation ID."""
        self.correlation_id = correlation_id or uuid4()

    @abstractmethod
    def build(self, data: Dict[str, Any]) -> T_Contract:
        """Build contract from parsed data.

        Args:
            data: Parsed prompt data containing:
                - node_type: str (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
                - service_name: str (snake_case)
                - domain: str (domain classification)
                - description: str (business description)
                - operations: List[str] (functional requirements)
                - features: List[str] (top features)
                - confidence: float (parsing confidence 0-1)

        Returns:
            Fully populated contract model

        Raises:
            ValueError: If required fields missing
            ValidationError: If contract validation fails
        """
        pass

    def validate_input(self, data: Dict[str, Any]) -> None:
        """Validate input data has required fields.

        Raises:
            ValueError: If required fields missing
        """
        required = ["node_type", "service_name", "domain", "description"]
        missing = [f for f in required if f not in data]

        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

    def to_yaml(self, contract: T_Contract, output_path: Path) -> str:
        """Generate YAML from contract using .to_yaml() method.

        Args:
            contract: Populated contract model
            output_path: Path to write YAML file

        Returns:
            YAML string
        """
        yaml_content = contract.to_yaml()

        # Write to file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(yaml_content)

        return yaml_content

    def _create_base_metadata(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create common metadata for all contracts."""
        return {
            "name": data["service_name"],
            "version": "1.0.0",
            "description": data["description"],
            "domain": data["domain"],
            "node_type": data["node_type"],
        }
```

---

## EFFECT Contract Builder

### Implementation

```python
from typing import Any, Dict, List
from uuid import uuid4

from omnibase_core.models.contracts.model_contract_effect import ModelContractEffect
from omnibase_core.models.contracts.subcontracts.model_io_operation import (
    ModelIOOperation,
    EnumIOOperationType,
)
from omnibase_core.models.core.model_lifecycle import ModelLifecycle, EnumLifecyclePhase
from omnibase_core.models.core.model_dependency import ModelDependency, EnumDependencyType


class EffectContractBuilder(ContractBuilder[ModelContractEffect]):
    """Build EFFECT node contracts.

    EFFECT nodes handle external I/O and side effects:
    - API calls
    - Database operations
    - File I/O
    - Message queues
    """

    def build(self, data: Dict[str, Any]) -> ModelContractEffect:
        """Build EFFECT contract from parsed data."""
        self.validate_input(data)

        # Extract metadata
        base_metadata = self._create_base_metadata(data)

        # Build IO operations from functional requirements
        io_operations = self._build_io_operations(data.get("operations", []))

        # Build lifecycle configuration
        lifecycle = self._build_lifecycle(data)

        # Build dependencies
        dependencies = self._build_dependencies(data)

        # Create contract
        contract = ModelContractEffect(
            name=base_metadata["name"],
            version=base_metadata["version"],
            description=base_metadata["description"],
            node_type="EFFECT",

            # EFFECT-specific fields
            io_operations=io_operations,
            lifecycle=lifecycle,
            dependencies=dependencies,

            # Performance requirements
            timeout_ms=30000,  # 30 second default
            retry_policy={
                "max_retries": 3,
                "backoff_multiplier": 2.0,
                "initial_delay_ms": 100,
            },

            # Monitoring
            enable_metrics=True,
            enable_tracing=True,

            # Metadata
            correlation_id=self.correlation_id,
            tags=[base_metadata["domain"], "autogenerated"],
        )

        return contract

    def _build_io_operations(self, operations: List[str]) -> List[ModelIOOperation]:
        """Build IO operation models from operation descriptions.

        Args:
            operations: List of operation descriptions (e.g., ["create records", "update data"])

        Returns:
            List of IO operation models
        """
        io_ops = []

        for op_desc in operations[:5]:  # Max 5 operations
            # Detect operation type from description
            op_type = self._detect_operation_type(op_desc)

            io_ops.append(
                ModelIOOperation(
                    operation_id=uuid4(),
                    operation_type=op_type,
                    description=op_desc,
                    is_idempotent=op_type in [EnumIOOperationType.READ, EnumIOOperationType.DELETE],
                    timeout_ms=10000,
                    correlation_id=self.correlation_id,
                )
            )

        return io_ops

    def _detect_operation_type(self, description: str) -> EnumIOOperationType:
        """Detect IO operation type from description."""
        desc_lower = description.lower()

        if any(word in desc_lower for word in ["create", "insert", "add", "write", "store"]):
            return EnumIOOperationType.WRITE
        elif any(word in desc_lower for word in ["read", "get", "fetch", "load", "query"]):
            return EnumIOOperationType.READ
        elif any(word in desc_lower for word in ["update", "modify", "change", "edit"]):
            return EnumIOOperationType.UPDATE
        elif any(word in desc_lower for word in ["delete", "remove", "drop"]):
            return EnumIOOperationType.DELETE
        else:
            return EnumIOOperationType.WRITE  # Default

    def _build_lifecycle(self, data: Dict[str, Any]) -> ModelLifecycle:
        """Build lifecycle configuration."""
        return ModelLifecycle(
            phases=[
                EnumLifecyclePhase.INITIALIZE,
                EnumLifecyclePhase.VALIDATE,
                EnumLifecyclePhase.EXECUTE,
                EnumLifecyclePhase.FINALIZE,
            ],
            cleanup_on_error=True,
            rollback_supported=True,
            correlation_id=self.correlation_id,
        )

    def _build_dependencies(self, data: Dict[str, Any]) -> List[ModelDependency]:
        """Build dependency list from external systems."""
        deps = []

        # Detect external systems from description
        external_systems = data.get("external_systems", [])

        for system in external_systems[:3]:  # Max 3 dependencies
            deps.append(
                ModelDependency(
                    dependency_id=uuid4(),
                    name=system.lower(),
                    dependency_type=self._map_system_to_dep_type(system),
                    required=True,
                    version="*",  # Any version
                    correlation_id=self.correlation_id,
                )
            )

        return deps

    def _map_system_to_dep_type(self, system: str) -> EnumDependencyType:
        """Map external system name to dependency type."""
        system_lower = system.lower()

        if "database" in system_lower or "postgres" in system_lower or "sql" in system_lower:
            return EnumDependencyType.DATABASE
        elif "api" in system_lower or "http" in system_lower:
            return EnumDependencyType.EXTERNAL_API
        elif "redis" in system_lower or "cache" in system_lower:
            return EnumDependencyType.CACHE
        elif "kafka" in system_lower or "queue" in system_lower:
            return EnumDependencyType.MESSAGE_QUEUE
        else:
            return EnumDependencyType.EXTERNAL_SERVICE
```

### Required Fields for EFFECT Contracts

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | str | Yes | - | Service name (snake_case) |
| `version` | str | Yes | "1.0.0" | Semantic version |
| `description` | str | Yes | - | Business description |
| `node_type` | str | Yes | "EFFECT" | Must be "EFFECT" |
| `io_operations` | List[ModelIOOperation] | Yes | [] | I/O operations |
| `lifecycle` | ModelLifecycle | Yes | - | Lifecycle configuration |
| `dependencies` | List[ModelDependency] | No | [] | External dependencies |
| `timeout_ms` | int | No | 30000 | Execution timeout |
| `retry_policy` | Dict | No | {...} | Retry configuration |
| `enable_metrics` | bool | No | True | Enable monitoring |
| `correlation_id` | UUID | Yes | uuid4() | Correlation tracking |

---

## COMPUTE Contract Builder

### Implementation

```python
from omnibase_core.models.contracts.model_contract_compute import ModelContractCompute
from omnibase_core.models.contracts.subcontracts.model_caching_subcontract import (
    ModelCachingSubcontract,
    EnumCacheStrategy,
)


class ComputeContractBuilder(ContractBuilder[ModelContractCompute]):
    """Build COMPUTE node contracts.

    COMPUTE nodes handle pure computational operations:
    - Data transformations
    - Calculations
    - Validation logic
    - Filtering and processing
    """

    def build(self, data: Dict[str, Any]) -> ModelContractCompute:
        """Build COMPUTE contract from parsed data."""
        self.validate_input(data)

        base_metadata = self._create_base_metadata(data)

        # Build caching configuration
        caching = self._build_caching_config(data)

        # Create contract
        contract = ModelContractCompute(
            name=base_metadata["name"],
            version=base_metadata["version"],
            description=base_metadata["description"],
            node_type="COMPUTE",

            # COMPUTE-specific fields
            caching_config=caching,
            deterministic=True,  # Assume pure functions
            parallelizable=False,  # Default: sequential

            # Performance requirements
            max_computation_time_ms=10000,  # 10 seconds
            memory_limit_mb=512,

            # Monitoring
            enable_metrics=True,
            enable_profiling=False,

            # Metadata
            correlation_id=self.correlation_id,
            tags=[base_metadata["domain"], "autogenerated"],
        )

        return contract

    def _build_caching_config(self, data: Dict[str, Any]) -> ModelCachingSubcontract:
        """Build caching configuration for COMPUTE nodes."""
        return ModelCachingSubcontract(
            cache_strategy=EnumCacheStrategy.LRU,
            max_cache_size=1000,
            ttl_seconds=3600,  # 1 hour
            cache_key_prefix=data["service_name"],
            enable_cache=True,
            correlation_id=self.correlation_id,
        )
```

---

## REDUCER Contract Builder

### Implementation

```python
from omnibase_core.models.contracts.model_contract_reducer import ModelContractReducer
from omnibase_core.models.contracts.subcontracts.model_fsm_subcontract import (
    ModelFSMSubcontract,
    ModelFSMState,
    ModelFSMTransition,
)
from omnibase_core.models.contracts.subcontracts.model_aggregation_subcontract import (
    ModelAggregationSubcontract,
    EnumAggregationFunction,
)


class ReducerContractBuilder(ContractBuilder[ModelContractReducer]):
    """Build REDUCER node contracts.

    REDUCER nodes handle state aggregation and FSM transitions:
    - Pure state transitions
    - Intent emission (NOT direct execution)
    - Data aggregation
    - State management
    """

    def build(self, data: Dict[str, Any]) -> ModelContractReducer:
        """Build REDUCER contract from parsed data."""
        self.validate_input(data)

        base_metadata = self._create_base_metadata(data)

        # Build FSM configuration
        fsm_config = self._build_fsm_config(data)

        # Build aggregation configuration
        aggregation_config = self._build_aggregation_config(data)

        # Create contract
        contract = ModelContractReducer(
            name=base_metadata["name"],
            version=base_metadata["version"],
            description=base_metadata["description"],
            node_type="REDUCER",

            # REDUCER-specific fields
            fsm_config=fsm_config,
            aggregation_config=aggregation_config,
            emit_intents=True,  # CRITICAL: REDUCER emits intents

            # State management
            state_persistence=True,
            state_snapshot_interval_ms=5000,

            # Performance
            max_state_size_mb=100,
            enable_incremental_processing=True,

            # Metadata
            correlation_id=self.correlation_id,
            tags=[base_metadata["domain"], "autogenerated"],
        )

        return contract

    def _build_fsm_config(self, data: Dict[str, Any]) -> ModelFSMSubcontract:
        """Build FSM configuration for REDUCER."""
        # Simple FSM for POC
        states = [
            ModelFSMState(state_id="INITIAL", is_initial=True, is_final=False),
            ModelFSMState(state_id="PROCESSING", is_initial=False, is_final=False),
            ModelFSMState(state_id="COMPLETED", is_initial=False, is_final=True),
        ]

        transitions = [
            ModelFSMTransition(
                from_state="INITIAL",
                to_state="PROCESSING",
                action="START",
            ),
            ModelFSMTransition(
                from_state="PROCESSING",
                to_state="COMPLETED",
                action="FINISH",
            ),
        ]

        return ModelFSMSubcontract(
            states=states,
            transitions=transitions,
            initial_state="INITIAL",
            correlation_id=self.correlation_id,
        )

    def _build_aggregation_config(self, data: Dict[str, Any]) -> ModelAggregationSubcontract:
        """Build aggregation configuration."""
        return ModelAggregationSubcontract(
            aggregation_functions=[EnumAggregationFunction.SUM, EnumAggregationFunction.COUNT],
            group_by_fields=[],
            window_size_seconds=60,
            correlation_id=self.correlation_id,
        )
```

---

## ORCHESTRATOR Contract Builder

### Implementation

```python
from omnibase_core.models.contracts.model_contract_orchestrator import ModelContractOrchestrator
from omnibase_core.models.contracts.subcontracts.model_routing_subcontract import (
    ModelRoutingSubcontract,
    ModelRoutingRule,
)


class OrchestratorContractBuilder(ContractBuilder[ModelContractOrchestrator]):
    """Build ORCHESTRATOR node contracts.

    ORCHESTRATOR nodes handle workflow coordination:
    - Multi-step workflows
    - Dependency resolution
    - Lease-based actions
    - Error recovery
    """

    def build(self, data: Dict[str, Any]) -> ModelContractOrchestrator:
        """Build ORCHESTRATOR contract from parsed data."""
        self.validate_input(data)

        base_metadata = self._create_base_metadata(data)

        # Build routing configuration
        routing_config = self._build_routing_config(data)

        # Create contract
        contract = ModelContractOrchestrator(
            name=base_metadata["name"],
            version=base_metadata["version"],
            description=base_metadata["description"],
            node_type="ORCHESTRATOR",

            # ORCHESTRATOR-specific fields
            routing_config=routing_config,
            lease_management=True,  # CRITICAL: Orchestrators use leases
            lease_timeout_ms=60000,  # 1 minute

            # Workflow configuration
            max_concurrent_workflows=10,
            enable_parallel_execution=True,
            enable_compensation=True,  # Saga pattern

            # Error handling
            retry_failed_workflows=True,
            max_workflow_retries=2,

            # Metadata
            correlation_id=self.correlation_id,
            tags=[base_metadata["domain"], "autogenerated"],
        )

        return contract

    def _build_routing_config(self, data: Dict[str, Any]) -> ModelRoutingSubcontract:
        """Build routing configuration for ORCHESTRATOR."""
        # Simple routing for POC
        rules = [
            ModelRoutingRule(
                rule_id="default",
                condition="true",  # Always match
                target_node="compute",
                priority=1,
            )
        ]

        return ModelRoutingSubcontract(
            routing_rules=rules,
            default_target="compute",
            enable_load_balancing=False,
            correlation_id=self.correlation_id,
        )
```

---

## Contract Builder Factory

### Implementation

```python
from typing import Dict, Type

class ContractBuilderFactory:
    """Factory for creating contract builders by node type.

    Provides centralized builder selection and registration.
    """

    # Registry of builders
    _builders: Dict[str, Type[ContractBuilder]] = {
        "EFFECT": EffectContractBuilder,
        "COMPUTE": ComputeContractBuilder,
        "REDUCER": ReducerContractBuilder,
        "ORCHESTRATOR": OrchestratorContractBuilder,
    }

    @classmethod
    def create(cls, node_type: str, correlation_id: UUID | None = None) -> ContractBuilder:
        """Create builder for node type.

        Args:
            node_type: Node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
            correlation_id: Optional correlation ID

        Returns:
            Contract builder instance

        Raises:
            ValueError: If node type not supported
        """
        if node_type not in cls._builders:
            raise ValueError(
                f"Unsupported node type: {node_type}. "
                f"Supported types: {', '.join(cls._builders.keys())}"
            )

        builder_class = cls._builders[node_type]
        return builder_class(correlation_id=correlation_id)

    @classmethod
    def register(cls, node_type: str, builder_class: Type[ContractBuilder]) -> None:
        """Register custom builder for node type.

        Args:
            node_type: Node type to register
            builder_class: Builder class to use
        """
        cls._builders[node_type] = builder_class

    @classmethod
    def supported_types(cls) -> List[str]:
        """Get list of supported node types."""
        return list(cls._builders.keys())
```

---

## Usage Examples

### Example 1: Generate EFFECT Contract

```python
from agents.lib.generation.contract_builder_factory import ContractBuilderFactory

# Parsed data from PromptParser
parsed_data = {
    "node_type": "EFFECT",
    "service_name": "postgres_writer",
    "domain": "infrastructure",
    "description": "Write data to PostgreSQL database",
    "operations": ["create records", "update existing data"],
    "features": ["Transaction support", "Retry logic"],
    "external_systems": ["PostgreSQL"],
    "confidence": 0.92,
}

# Create builder
factory = ContractBuilderFactory()
builder = factory.create("EFFECT")

# Build contract
contract = builder.build(parsed_data)

# Generate YAML
yaml_content = builder.to_yaml(contract, Path("contract.yaml"))

print(yaml_content)
```

**Output**:
```yaml
name: postgres_writer
version: 1.0.0
description: Write data to PostgreSQL database
node_type: EFFECT
io_operations:
  - operation_id: 123e4567-e89b-12d3-a456-426614174000
    operation_type: WRITE
    description: create records
    is_idempotent: false
    timeout_ms: 10000
  - operation_id: 223e4567-e89b-12d3-a456-426614174001
    operation_type: UPDATE
    description: update existing data
    is_idempotent: false
    timeout_ms: 10000
lifecycle:
  phases:
    - INITIALIZE
    - VALIDATE
    - EXECUTE
    - FINALIZE
  cleanup_on_error: true
  rollback_supported: true
dependencies:
  - name: postgresql
    dependency_type: DATABASE
    required: true
    version: "*"
timeout_ms: 30000
retry_policy:
  max_retries: 3
  backoff_multiplier: 2.0
  initial_delay_ms: 100
enable_metrics: true
enable_tracing: true
tags:
  - infrastructure
  - autogenerated
```

### Example 2: Generate COMPUTE Contract

```python
parsed_data = {
    "node_type": "COMPUTE",
    "service_name": "price_calculator",
    "domain": "business",
    "description": "Calculate prices with tax and discounts",
    "operations": ["calculate total", "apply discount", "add tax"],
    "confidence": 0.88,
}

builder = factory.create("COMPUTE")
contract = builder.build(parsed_data)
yaml_content = builder.to_yaml(contract, Path("compute_contract.yaml"))
```

---

## Integration with GenerationPipeline

### Updated Stage 3

```python
async def _stage_3_generate_code(
    self,
    analysis_result: SimplePRDAnalysisResult,
    node_type: str,
    service_name: str,
    domain: str,
    output_directory: str,
) -> Tuple[PipelineStage, Dict]:
    """Stage 3: Generate node code using Pydantic contracts."""
    stage = PipelineStage(stage_name="code_generation", status=StageStatus.RUNNING)
    start_ms = time()

    try:
        # NEW: Create contract using builder
        factory = ContractBuilderFactory()
        builder = factory.create(node_type, correlation_id=self.correlation_id)

        # Build contract from parsed data
        parsed_data = {
            "node_type": node_type,
            "service_name": service_name,
            "domain": domain,
            "description": analysis_result.parsed_prd.description,
            "operations": analysis_result.parsed_prd.functional_requirements[:5],
            "features": analysis_result.parsed_prd.features[:3],
            "external_systems": analysis_result.parsed_prd.extracted_keywords,
        }

        contract = builder.build(parsed_data)

        # Generate YAML
        contract_path = Path(output_directory) / f"{service_name}_contract.yaml"
        yaml_content = builder.to_yaml(contract, contract_path)

        # Generate node code from contract (using template engine or AST builder)
        generation_result = await self.template_engine.generate_from_contract(
            contract=contract,
            output_directory=output_directory,
        )

        stage.status = StageStatus.COMPLETED
        return stage, {"generated_files": generation_result, "contract": contract}

    except Exception as e:
        stage.status = StageStatus.FAILED
        stage.error = str(e)
        return stage, {}
```

---

## Validation

### Contract Validation

```python
from pydantic import ValidationError

def validate_contract(contract: ModelContractBase) -> bool:
    """Validate contract against Pydantic schema.

    Returns:
        True if valid, raises ValidationError if invalid
    """
    try:
        # Pydantic automatically validates on construction
        # But we can explicitly validate here
        contract.model_validate(contract.model_dump())
        return True
    except ValidationError as e:
        raise ValueError(f"Contract validation failed: {e}")
```

---

## Appendix: Contract Model Reference

### Available Contract Models (omnibase_core)

| Model | Location | Purpose |
|-------|----------|---------|
| `ModelContractBase` | `omnibase_core.models.contracts.model_contract_base` | Base for all contracts |
| `ModelContractEffect` | `omnibase_core.models.contracts.model_contract_effect` | EFFECT nodes |
| `ModelContractCompute` | `omnibase_core.models.contracts.model_contract_compute` | COMPUTE nodes |
| `ModelContractReducer` | `omnibase_core.models.contracts.model_contract_reducer` | REDUCER nodes |
| `ModelContractOrchestrator` | `omnibase_core.models.contracts.model_contract_orchestrator` | ORCHESTRATOR nodes |

### Available Subcontracts

| Subcontract | Location | Used By |
|-------------|----------|---------|
| `ModelIOOperation` | `omnibase_core.models.contracts.subcontracts.model_io_operation` | EFFECT |
| `ModelCachingSubcontract` | `omnibase_core.models.contracts.subcontracts.model_caching_subcontract` | COMPUTE |
| `ModelFSMSubcontract` | `omnibase_core.models.contracts.subcontracts.model_fsm_subcontract` | REDUCER |
| `ModelAggregationSubcontract` | `omnibase_core.models.contracts.subcontracts.model_aggregation_subcontract` | REDUCER |
| `ModelRoutingSubcontract` | `omnibase_core.models.contracts.subcontracts.model_routing_subcontract` | ORCHESTRATOR |

---

**End of Contract Builder Specification**

**Next Steps**:
1. Review specification with team
2. Implement base `ContractBuilder` class
3. Implement all 4 builder subclasses
4. Create comprehensive tests
5. Integrate with GenerationPipeline
