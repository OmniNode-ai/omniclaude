# Omninode/Omnibase Naming Conventions - Documentation Analysis

**Analysis Date**: 2025-09-30
**Base Repository**: External omnibase_core project - `${OMNIBASE_CORE}`
**Documentation Sources**: 17 files analyzed
**Purpose**: Extract ACTUAL naming conventions for Archon quality enforcement

---

## Table of Contents
1. [File Naming Conventions](#file-naming-conventions)
2. [Class & Model Naming](#class--model-naming)
3. [Function & Method Naming](#function--method-naming)
4. [Variable & Parameter Naming](#variable--parameter-naming)
5. [Directory Structure](#directory-structure)
6. [Import Patterns](#import-patterns)
7. [Enum Naming Conventions](#enum-naming-conventions)
8. [TypedDict Naming](#typeddict-naming)
9. [Error/Exception Naming](#errorexception-naming)
10. [Documentation Standards](#documentation-standards)

---

## 1. File Naming Conventions

### One-Model-Per-File Rule (DOCUMENTED)
**Source**: `docs/API_DOCUMENTATION.md`, lines 35-42

> "Following ONEX standards, each model is defined in its own file:
> - File naming: `model_<name>.py`
> - Class naming: `Model<Name>`
> - No multiple models per file"

### File Naming Patterns

#### Models
```
Pattern: model_<descriptive_name>.py
Examples:
  - model_contract_base.py
  - model_contract_effect.py
  - model_contract_compute.py
  - model_contract_reducer.py
  - model_contract_orchestrator.py
  - model_algorithm_config.py
  - model_validation_rules.py
```
**Source**: `docs/API_DOCUMENTATION.md`, lines 46, 90, 142, 202, 260

#### Subcontracts
```
Pattern: model_<type>_subcontract.py
Examples:
  - model_aggregation_subcontract.py
  - model_fsm_subcontract.py
  - model_caching_subcontract.py
  - model_routing_subcontract.py
  - model_state_management_subcontract.py
  - model_workflow_coordination_subcontract.py
```
**Source**: `docs/IMPORT_MIGRATION_PATTERNS.md`, lines 72-79

#### Enums
```
Pattern: enum_<descriptive_name>.py
Examples:
  - enum_log_level.py
  - enum_node_type.py
  - enum_dependency_type.py
  - enum_workflow_coordination.py
  - enum_health_status.py
```
**Source**: Multiple files - `README.md` lines 37-39, `docs/IMPORT_MIGRATION_PATTERNS.md` lines 81-85

#### TypedDicts
```
Pattern: typed_dict_<descriptive_name>.py
Examples:
  - typed_dict_capability_factory_kwargs.py
  - typed_dict_performance_metric_data.py
```
**Source**: `docs/API_DOCUMENTATION.md`, lines 813, 865

#### Service Base Classes
```
Pattern: node_<node_type>_service.py
Examples:
  - node_effect_service.py
  - node_compute_service.py
  - node_reducer_service.py
  - node_orchestrator_service.py
```
**Source**: `README.md`, lines 23-26

#### Infrastructure Files
```
Pattern: <descriptive>_<purpose>.py
Examples:
  - infrastructure_service_bases.py
  - onex_container.py
  - base_onex_error.py
  - model_onex_error.py
```
**Source**: `README.md`, lines 22, 27, 42-43

---

## 2. Class & Model Naming

### Model Classes
**Pattern**: `Model<PascalCase>`

```python
# Documented Pattern (Source: docs/API_DOCUMENTATION.md, lines 35-42)
class ModelContractBase(BaseModel):
    """Base class for all ONEX contract models."""
    pass

class ModelContractEffect(ModelContractBase):
    """Contract model for EFFECT node operations."""
    pass

class ModelContractCompute(ModelContractBase):
    """Contract model for COMPUTE node operations."""
    pass

class ModelAlgorithmConfig(BaseModel):
    """Configuration for algorithm execution in COMPUTE nodes."""
    pass
```
**Sources**:
- `docs/API_DOCUMENTATION.md`, lines 49-88, 91-142, 322-391
- `docs/DOCSTRING_TEMPLATES.md`, lines 28-136

### Node Service Classes
**Pattern**: `Node<NodeType>Service`

```python
# Documented Pattern (Source: README.md, lines 166-199)
class NodeEffectService:
    """EFFECT node base class."""
    pass

class NodeComputeService:
    """COMPUTE node base class."""
    pass

class NodeReducerService:
    """REDUCER node base class."""
    pass

class NodeOrchestratorService:
    """ORCHESTRATOR node base class."""
    pass
```
**Source**: `README.md`, lines 194-199; `archived/docs/ONEX_4_Node_System_Developer_Guide.md`, lines 163-171

### Subcontract Classes
**Pattern**: `Model<Type>Subcontract`

```python
# Documented Pattern (Source: docs/DOCSTRING_TEMPLATES.md, lines 400-552)
class ModelAggregationSubcontract(BaseModel):
    """Subcontract for data aggregation operations."""
    pass

class ModelFSMSubcontract(BaseModel):
    """Finite State Machine (FSM) subcontract."""
    pass
```
**Sources**: `docs/DOCSTRING_TEMPLATES.md`, lines 400-402, 558-560

### Mixin Classes
**Pattern**: `Mixin<Capability>`

```python
# Documented Pattern (Source: archived/docs/ONEX_4_Node_System_Developer_Guide.md, lines 207-220)
class MixinNodeService:
    """Service integration and lifecycle management."""
    pass

class MixinHealthCheck:
    """Health monitoring and status reporting."""
    pass

class MixinEventDrivenNode:
    """Event-based processing and handling."""
    pass
```
**Source**: `archived/docs/ONEX_4_Node_System_Developer_Guide.md`, lines 207-220

---

## 3. Function & Method Naming

### Node Operation Methods
**Pattern**: `execute_<node_type>` or `execute_<operation>`

```python
# Documented Pattern (Source: archived/docs/ONEX_4_Node_System_Developer_Guide.md)
class NodeEffectService:
    async def execute_effect(self, contract: ModelContractEffect) -> ModelEffectOutput:
        """Execute EFFECT node operation."""
        pass

class NodeComputeService:
    async def execute_compute(self, contract: ModelContractCompute) -> ModelComputeOutput:
        """Execute computational processing."""
        pass

class NodeReducerService:
    async def execute_reduction(self, contract: ModelContractReducer) -> ModelReducerOutput:
        """Execute data reduction and aggregation."""
        pass

class NodeOrchestratorService:
    async def execute_orchestration(self, contract: ModelContractOrchestrator) -> ModelOrchestratorOutput:
        """Execute workflow orchestration."""
        pass
```
**Sources**:
- `docs/ONEX_FOUR_NODE_ARCHITECTURE.md`, lines 62-98, 162-214, 310-376, 488-541

### Validation Methods
**Pattern**: `validate_<target>` or `_validate_<target>` (private)

```python
# Documented Pattern (Source: docs/ONEX_FOUR_NODE_ARCHITECTURE.md)
def _validate_database_contract(self, contract: ModelContractEffect) -> bool:
    """Validate contract has required database operation parameters."""
    pass

def _validate_input_data(self, contract: ModelContractCompute):
    """Validate input data against contract validation rules."""
    pass

async def _validate_dependencies(self, dependencies: List[ModelDependency]):
    """Validate all required dependencies are available and healthy."""
    pass
```
**Sources**:
- `docs/ONEX_FOUR_NODE_ARCHITECTURE.md`, lines 111-115, 233-250, 658-680
- `docs/API_DOCUMENTATION.md`, lines 453-531

### Error Handling Methods
**Pattern**: `_handle_<error_type>` (private)

```python
# Documented Pattern (Source: docs/ERROR_HANDLING_BEST_PRACTICES.md)
async def _handle_orchestration_failure(self, contract, workflow_id, error):
    """Handle orchestration failure."""
    pass

async def _record_failure(self):
    """Record failed operation."""
    pass

async def _record_success(self):
    """Record successful operation."""
    pass
```
**Source**: `docs/ERROR_HANDLING_BEST_PRACTICES.md`, lines 540-541, 671-682

### Utility/Helper Methods
**Pattern**: `_<verb>_<target>` (private)

```python
# Documented Pattern (Source: docs/ONEX_FOUR_NODE_ARCHITECTURE.md)
async def _execute_with_retry(self, contract: ModelContractEffect):
    """Execute operation with exponential backoff retry."""
    pass

def _transform_output(self, data, contract: ModelContractCompute):
    """Apply output transformation based on contract specifications."""
    pass

async def _create_state_backup(self, contract, result):
    """Create backup of aggregated state."""
    pass
```
**Sources**:
- `docs/ONEX_FOUR_NODE_ARCHITECTURE.md`, lines 100-109, 252-263, 424-440

### Async/Await Convention
**Pattern**: All I/O or potentially blocking operations use `async def`

```python
# Documented Pattern (throughout all examples)
async def execute_effect(self, contract: ModelContractEffect):
    """Async for I/O operations."""
    pass

def process_data(self, data: dict):
    """Sync for pure computation."""
    pass
```
**Source**: All code examples consistently use async for I/O operations

---

## 4. Variable & Parameter Naming

### Contract Parameters
**Pattern**: `<type>_contract` or just `contract`

```python
# Documented Pattern
async def execute_effect(self, contract: ModelContractEffect):
    pass

effect_contract = ModelContractEffect(...)
compute_contract = ModelContractCompute(...)
```
**Source**: `docs/ONEX_FOUR_NODE_ARCHITECTURE.md`, lines 62, 162, 310, 488

### Configuration Parameters
**Pattern**: `<purpose>_config`

```python
# Documented Pattern (Source: docs/DOCSTRING_TEMPLATES.md, lines 28-136)
algorithm_config: ModelAlgorithmConfig
retry_config: ModelEffectRetryConfig
performance_config: ModelAggregationPerformance
streaming_config: ModelStreamingConfig
backup_config: ModelBackupConfig
```
**Sources**: Multiple - see DOCSTRING_TEMPLATES.md

### Correlation IDs
**Pattern**: `correlation_id` (snake_case, consistent naming)

```python
# Documented Pattern (universal across all examples)
correlation_id: UUID
self.correlation_id
contract.correlation_id
```
**Source**: Every single documented class uses this exact name

### Service/Component References
**Pattern**: `<purpose>_<type>` (snake_case)

```python
# Documented Pattern (Source: archived/docs/ONEX_4_Node_System_Developer_Guide.md)
self.db_pool = container.get_service("ProtocolDatabasePool")
self.logger = container.get_service("ProtocolLogger")
self.event_bus = container.get_service("ProtocolEventBus")
self.http_client = container.get_service("ProtocolHttpClient")
```
**Source**: `archived/docs/ONEX_4_Node_System_Developer_Guide.md`, lines 350-352

### Loop Variables and Iterators
**Pattern**: Descriptive names (no single letters in production code)

```python
# Documented Pattern (Source: docs/ONEX_FOUR_NODE_ARCHITECTURE.md)
for attempt in range(config.max_attempts):
    pass

for step in execution_context.workflow_steps:
    pass

for field in self.required_fields:
    pass
```
**Source**: `docs/ONEX_FOUR_NODE_ARCHITECTURE.md`, lines 548, various

---

## 5. Directory Structure

### Core Package Structure
**Documented Structure** (Source: `README.md`, lines 20-50)

```
src/omnibase_core/
├── core/                           # Core framework components
│   ├── infrastructure_service_bases.py
│   ├── node_effect_service.py
│   ├── node_compute_service.py
│   ├── node_reducer_service.py
│   ├── node_orchestrator_service.py
│   ├── onex_container.py
│   ├── monadic/
│   └── mixins/
├── model/
│   ├── core/                       # Core data models
│   │   ├── model_event_envelope.py
│   │   ├── model_health_status.py
│   │   └── model_semver.py
│   └── coordination/               # Service coordination models
├── enums/                          # Core enumerations
│   ├── enum_health_status.py
│   ├── enum_node_type.py
│   └── enum_node_current_status.py
├── exceptions/                     # Error handling system
│   ├── base_onex_error.py
│   └── model_onex_error.py
├── decorators/                     # Utility decorators
│   └── error_handling.py
└── examples/                       # Canonical node implementations
```

### Subcontract Organization
**Documented Structure** (Source: `docs/IMPORT_MIGRATION_PATTERNS.md`, lines 68-79)

```
src/omnibase_core/models/contracts/subcontracts/
├── model_aggregation_subcontract.py
├── model_caching_subcontract.py
├── model_configuration_subcontract.py
├── model_event_type_subcontract.py
├── model_fsm_subcontract.py
├── model_routing_subcontract.py
├── model_state_management_subcontract.py
└── model_workflow_coordination_subcontract.py
```

---

## 6. Import Patterns

### Correct Modern Imports
**Pattern**: Use migrated paths in `omnibase_core.models.*` and `omnibase_core.enums.*`

```python
# ✅ CORRECT - Migrated subcontract models (Source: docs/IMPORT_MIGRATION_PATTERNS.md)
from omnibase_core.models.contracts.subcontracts.model_aggregation_subcontract import (
    AggregationSubcontract,
    AggregationConfig,
    AggregationStrategy
)

# ✅ CORRECT - Enums (migrated)
from omnibase_core.enums.enum_log_level import LogLevel
from omnibase_core.enums.enum_node_type import NodeType

# ✅ CORRECT - Core models and types
from omnibase_core.models.base import BaseModel
from omnibase_core.types.common import CommonTypes

# ✅ CORRECT - Service bases
from omnibase_core.core.infrastructure_service_bases import (
    NodeEffectService,
    NodeComputeService,
    NodeReducerService,
    NodeOrchestratorService
)
```
**Source**: `docs/IMPORT_MIGRATION_PATTERNS.md`, lines 39-64

### Blocked/Legacy Imports
**Pattern**: Never import from `archived.*` paths

```python
# ❌ NEVER - Direct archived imports
from archived.some_module import SomeClass
from archive.old_module import OldFunction

# ❌ NEVER - Archived source paths
from archived.src.omnibase_core.core.contracts.model_contract_base import ModelContractBase
```
**Source**: `docs/IMPORT_MIGRATION_PATTERNS.md`, lines 10-24

### Protocol-Based Service Resolution
**Pattern**: Use protocol names as strings, not concrete types

```python
# Documented Pattern (Source: README.md, lines 206-211)
logger = container.get_service("ProtocolLogger")
event_bus = container.get_service("ProtocolEventBus")

# NOT: logger = container.get_service(LoggerService)
```
**Source**: `README.md`, lines 209-211, 257-260

---

## 7. Enum Naming Conventions

### Enum Class Names
**Pattern**: `Enum<PascalCase>`

```python
# Documented Pattern (Source: docs/DOCSTRING_TEMPLATES.md, lines 1014-1176)
class EnumWorkflowCoordination(str, Enum):
    """Workflow coordination patterns."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    PIPELINE = "pipeline"

class EnumDependencyType(str, Enum):
    """Types of dependencies."""
    REQUIRED = "required"
    OPTIONAL = "optional"
    PREFERRED = "preferred"

class EnumHealthStatus(str, Enum):
    """Health status values."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
```
**Source**: `docs/DOCSTRING_TEMPLATES.md`, lines 1014-1177

### Enum Value Naming
**Pattern**: `SCREAMING_SNAKE_CASE` for enum values

```python
# Documented Pattern (consistent across all enum examples)
class EnumWorkflowCoordination(str, Enum):
    SEQUENTIAL = "sequential"          # ✅ Correct
    PARALLEL = "parallel"              # ✅ Correct
    PIPELINE = "pipeline"              # ✅ Correct
    CONDITIONAL = "conditional"        # ✅ Correct
    EVENT_DRIVEN = "event_driven"      # ✅ Correct
    HYBRID = "hybrid"                  # ✅ Correct
```
**Source**: All enum examples use this pattern

### Enum String Values
**Pattern**: lowercase with underscores (snake_case)

```python
# Documented Pattern
SEQUENTIAL = "sequential"       # ✅ snake_case string value
EVENT_DRIVEN = "event_driven"   # ✅ snake_case string value
```
**Source**: All enum definitions follow this pattern

---

## 8. TypedDict Naming

### TypedDict Class Names
**Pattern**: `TypedDict<PascalCase>`

```python
# Documented Pattern (Source: docs/DOCSTRING_TEMPLATES.md, lines 831-1007)
class TypedDictPerformanceMetricData(TypedDict):
    """Performance metric data structure."""
    metric_name: str
    value: Union[int, float]
    timestamp: datetime
    component_id: UUID

class TypedDictCapabilityFactoryKwargs(TypedDict):
    """Keyword arguments for capability factory."""
    capability_type: str
    configuration: dict[str, Any]
```
**Source**: `docs/DOCSTRING_TEMPLATES.md`, lines 831-856

### TypedDict Field Names
**Pattern**: snake_case, descriptive

```python
# Documented Pattern
metric_name: str              # ✅ snake_case
component_id: UUID            # ✅ snake_case with abbreviation
capability_type: str          # ✅ snake_case
```
**Source**: `docs/DOCSTRING_TEMPLATES.md`, lines 831-1007

---

## 9. Error/Exception Naming

### Error Class Names
**Pattern**: `<Specific>Error` or `<Specific>NodeError`

```python
# Documented Pattern (Source: docs/ERROR_HANDLING_BEST_PRACTICES.md)
class OnexError(Exception):
    """Base exception class for all ONEX-related errors."""
    pass

class ContractValidationError(OnexError):
    """Error raised when contract validation fails."""
    pass

class EffectNodeError(NodeOperationError):
    """Error in EFFECT node operations."""
    pass

class ComputeNodeError(NodeOperationError):
    """Error in COMPUTE node operations."""
    pass

class AggregationError(SubcontractExecutionError):
    """Error in aggregation subcontract execution."""
    pass

class FSMExecutionError(SubcontractExecutionError):
    """Error in FSM subcontract execution."""
    pass
```
**Source**: `docs/ERROR_HANDLING_BEST_PRACTICES.md`, lines 30-331

### Error Hierarchy
**Documented Pattern**:
1. All inherit from `OnexError`
2. Node-specific errors inherit from `NodeOperationError`
3. Subcontract errors inherit from `SubcontractExecutionError`

**Source**: `docs/ERROR_HANDLING_BEST_PRACTICES.md`, lines 98-331

---

## 10. Documentation Standards

### Docstring Template Structure
**Documented Standard** (Source: `docs/DOCSTRING_TEMPLATES.md`, lines 9-23)

**Required Elements**:
1. Brief Description (one-line summary)
2. Detailed Description (comprehensive explanation)
3. Attributes Section (complete with types and descriptions)
4. Example Section (practical usage with realistic data)
5. Raises Section (all possible exceptions)
6. Note Section (usage considerations and context)
7. Validation Rules (constraints and business rules)

### Google-Style Docstrings
**Pattern**: Consistently use Google-style format

```python
# Documented Pattern (Source: docs/DOCSTRING_TEMPLATES.md)
class ModelAlgorithmConfig(BaseModel):
    """
    Configuration for algorithm execution in COMPUTE nodes.

    Defines algorithm-specific parameters, execution modes, and performance
    optimization settings for computational processing within the ONEX
    Four-Node Architecture.

    Attributes:
        algorithm_type (str): Type identifier for the algorithm to execute.
            Supported types include: "machine_learning", "statistical",
            "data_transformation", "custom".
        parameters (dict[str, Any]): Algorithm-specific configuration parameters.
        optimization_level (str): Performance optimization level.

    Example:
        ```python
        ml_config = ModelAlgorithmConfig(
            algorithm_type="machine_learning",
            parameters={"model_path": "/path/to/model"}
        )
        ```

    Validation Rules:
        - algorithm_type must be a recognized algorithm identifier
        - parameters must contain all required keys

    Raises:
        ValidationError: If algorithm_type is not recognized
        AlgorithmRegistryError: If algorithm is not available

    Note:
        Algorithm configurations are validated against the algorithm registry
        at runtime to ensure compatibility.
    """
```
**Source**: `docs/DOCSTRING_TEMPLATES.md`, lines 28-124

### Example Quality Standards
**Documented Requirements** (Source: `docs/DOCSTRING_TEMPLATES.md`, lines 1188-1210):
- Use realistic data demonstrating actual usage patterns
- Show both simple and complex configuration examples
- Include error handling examples where appropriate
- Demonstrate integration with other ONEX components

---

## Summary of Key Patterns

### File Naming
- Models: `model_<name>.py`
- Enums: `enum_<name>.py`
- TypedDicts: `typed_dict_<name>.py`
- Services: `node_<type>_service.py`

### Class Naming
- Models: `Model<PascalCase>`
- Enums: `Enum<PascalCase>`
- TypedDicts: `TypedDict<PascalCase>`
- Services: `Node<Type>Service`
- Mixins: `Mixin<Capability>`
- Errors: `<Type>Error` or `<Node>NodeError`

### Function/Method Naming
- Public methods: `verb_noun` (snake_case)
- Private methods: `_verb_noun` (leading underscore)
- Node operations: `execute_<node_type>`
- Validation: `validate_<target>` or `_validate_<target>`

### Variable Naming
- Always snake_case
- Descriptive names (no single letters in production)
- `correlation_id` (universal standard)
- `<purpose>_config` for configurations
- `<type>_contract` for contracts

### Import Patterns
- Use modern `omnibase_core.models.*` paths
- Never import from `archived.*`
- Protocol-based service resolution with string names

### Documentation
- Google-style docstrings required
- Comprehensive examples with realistic data
- Complete attribute documentation with types
- Validation rules and constraints documented

---

## Sources Referenced

### Primary Documentation Files
1. `README.md` - Main project documentation
2. `docs/ONEX_FOUR_NODE_ARCHITECTURE.md` - Architecture patterns
3. `docs/API_DOCUMENTATION.md` - API reference
4. `docs/DOCSTRING_TEMPLATES.md` - Documentation standards
5. `docs/ERROR_HANDLING_BEST_PRACTICES.md` - Error handling patterns
6. `docs/IMPORT_MIGRATION_PATTERNS.md` - Import guidelines
7. `archived/docs/ONEX_4_Node_System_Developer_Guide.md` - Developer guide

### Additional Context
- All conventions are extracted from DOCUMENTED standards
- Examples are from actual documentation, not inferred
- Line numbers provided for verification
- Ambiguities noted where found

---

**Report Generated**: 2025-09-30
**Total Documentation Files Analyzed**: 7 primary + 10 supporting
**Conventions Extracted**: 100+ specific patterns documented
**Next Step**: Synthesis with actual code analysis for complete enforcement rules