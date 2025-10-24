# Omnibase_3 Importable Dependencies Guide

**Research Date**: 2025-10-22
**Source Repository**: `../omnibase_3`
**Target**: OmniClaude Node Generation System

## Overview

This document identifies core dependencies from omnibase_3 that should be **imported** rather than regenerated when building ONEX-compliant nodes. These provide the foundation for error handling, contracts, base classes, and utilities.

---

## Core Error Handling System

### 1. OnexError Exception Framework

**Location**: `omnibase.core.core_errors`

**Key Components**:

```python
from omnibase.core.core_errors import (
    OnexError,           # Main exception class with Pydantic integration
    CoreErrorCode,       # Comprehensive error code enum
    ModelOnexError,      # Pydantic model for error serialization
    CLIAdapter,          # CLI exit code handling
)
```

**Features**:
- ✅ **UUID Integration**: Auto-generates correlation IDs via `UUIDService`
- ✅ **Pydantic Validation**: Structured error models with validation
- ✅ **CLI Exit Codes**: Maps `EnumOnexStatus` to standard exit codes (0-6)
- ✅ **Error Code Registry**: Component-specific error code management
- ✅ **Exception Chaining**: Maintains cause tracking for debugging

**Error Code Categories** (200+ predefined codes):
- **001-020**: Validation errors (INVALID_PARAMETER, VALIDATION_FAILED, etc.)
- **021-040**: File system errors (FILE_NOT_FOUND, PERMISSION_DENIED, etc.)
- **041-060**: Configuration errors (INVALID_CONFIGURATION, etc.)
- **061-080**: Registry errors (REGISTRY_NOT_FOUND, DUPLICATE_REGISTRATION, etc.)
- **081-100**: Runtime errors (OPERATION_FAILED, TIMEOUT, RESOURCE_UNAVAILABLE, etc.)
- **101-120**: Test errors (TEST_SETUP_FAILED, TEST_ASSERTION_FAILED, etc.)
- **121-140**: Import/dependency errors (MODULE_NOT_FOUND, DEPENDENCY_UNAVAILABLE, etc.)
- **131-140**: Database errors (DATABASE_CONNECTION_ERROR, etc.)
- **141-160**: Implementation errors (METHOD_NOT_IMPLEMENTED, etc.)
- **161-180**: Intelligence processing errors (NO_SUITABLE_PROVIDER, RATE_LIMIT_ERROR, etc.)
- **181-200**: System health errors (SERVICE_START_FAILED, SECURITY_VIOLATION, etc.)

**Usage Pattern**:

```python
from omnibase.core.core_errors import OnexError, CoreErrorCode

# Entry point pattern (auto-generates correlation ID)
raise OnexError(
    message="Invalid parameter provided",
    error_code=CoreErrorCode.INVALID_PARAMETER,
    context={"parameter": "node_type", "value": "INVALID"}
)

# Internal processing pattern (with existing correlation ID)
raise OnexError.with_correlation_id(
    message="Processing failed",
    correlation_id=existing_uuid,
    error_code=CoreErrorCode.OPERATION_FAILED
)
```

### 2. Simplified OnexError (Alternative)

**Location**: `omnibase.core.onex_error`

**Simpler version** for basic error handling without full Pydantic integration:

```python
from omnibase.core.onex_error import OnexError, CoreErrorCode

raise OnexError(
    code=CoreErrorCode.VALIDATION_ERROR,
    message="Invalid input",
    details={"field": "name"},
    cause=original_exception
)
```

---

## Contract Architecture

### 1. Base Contract Models

**Location**: `omnibase.core.model_contract_base`

```python
from omnibase.core.model_contract_base import (
    ModelContractBase,           # Abstract foundation for all contracts
    ModelPerformanceRequirements,  # SLA specifications
    ModelLifecycleConfig,         # Lifecycle management
    ModelValidationRules,         # Validation constraints
)
```

**Features**:
- Contract identification and versioning
- Node type classification with `EnumNodeType`
- Input/output model specifications
- Performance requirements and SLA tracking
- Lifecycle management configuration

### 2. Specialized Contract Models

**Effect Contracts**: `omnibase.core.model_contract_effect`
```python
from omnibase.core.model_contract_effect import (
    ModelContractEffect,      # Effect node contracts
    ModelIOOperationConfig,   # I/O operation specs
    ModelDependencySpec,      # Dependency specifications
)
```

**Compute Contracts**: `omnibase.core.model_contract_compute`
**Reducer Contracts**: `omnibase.core.model_contract_reducer`
**Orchestrator Contracts**: `omnibase.core.model_contract_orchestrator`

### 3. Subcontracts (6 Types)

**Location**: `omnibase.core.subcontracts`

```python
from omnibase.core.subcontracts import (
    ModelFSMSubcontract,               # Finite State Machine
    ModelEventTypeSubcontract,         # Event type definitions
    ModelAggregationSubcontract,       # Data aggregation patterns
    ModelStateManagementSubcontract,   # State persistence
    ModelRoutingSubcontract,           # Routing logic
    ModelCachingSubcontract,           # Caching strategies
)
```

---

## Node Base Classes

### 1. NodeCoreBase (Foundation)

**Location**: `omnibase.core.node_core_base`

```python
from omnibase.core.node_core_base import NodeCoreBase
```

**Features**:
- Container-based dependency injection (`ONEXContainer`)
- Protocol resolution without isinstance checks
- Event emission for lifecycle transitions
- Performance monitoring and metrics collection
- Contract loading and validation
- Lifecycle: `initialize → process → complete → cleanup`

**Core Metrics Tracked**:
- `initialization_time_ms`
- `total_operations`
- `avg_processing_time_ms`
- `error_count`
- `success_count`

### 2. Specialized Node Base Classes

**Location**: `omnibase.core`

```python
from omnibase.core.node_compute import NodeCompute
from omnibase.core.node_effect import NodeEffect
from omnibase.core.node_reducer import NodeReducer
from omnibase.core.node_orchestrator import NodeOrchestrator
```

**Usage**: Inherit from these when generating specialized nodes.

---

## Enums (120+ Definitions)

### Critical Enums

**Location**: `omnibase.enums`

```python
from omnibase.enums.enum_node_type import EnumNodeType
from omnibase.enums.enum_onex_status import EnumOnexStatus
from omnibase.enums.enum_log_level import LogLevelEnum
from omnibase.enums.enum_event_type import EnumEventType
```

**EnumNodeType** (4-node architecture):
```python
class EnumNodeType(str, Enum):
    COMPUTE = "COMPUTE"
    EFFECT = "EFFECT"
    REDUCER = "REDUCER"
    ORCHESTRATOR = "ORCHESTRATOR"
```

**EnumOnexStatus** (Standard statuses):
```python
class EnumOnexStatus(str, Enum):
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"
    FIXED = "fixed"
    PARTIAL = "partial"
    INFO = "info"
    UNKNOWN = "unknown"
```

**Common Enums to Import**:
- `enum_execution_mode` - Execution modes (SYNC, ASYNC, PARALLEL, etc.)
- `enum_validation_severity` - Validation severity levels
- `enum_health_status` - Node health status
- `enum_operation_status` - Operation status tracking
- `enum_file_type` - File type classification

---

## Utilities & Services

### 1. UUID Service

**Location**: `omnibase.core.core_uuid_service`

```python
from omnibase.core.core_uuid_service import UUIDService

# Generate correlation IDs
correlation_id = UUIDService.generate_correlation_id()

# Generate event IDs
event_id = UUIDService.generate_event_id()

# Validate UUIDs
is_valid = UUIDService.is_valid_uuid(some_value)

# Convert between string and UUID
uuid_str = UUIDService.to_string(uuid_obj)
uuid_obj = UUIDService.from_string(uuid_str)
```

### 2. ONEXContainer (Dependency Injection)

**Location**: `omnibase.core.onex_container`

```python
from omnibase.core.onex_container import ONEXContainer

# Used for dependency injection in NodeCoreBase
container = ONEXContainer()
```

### 3. Logging & Structured Events

**Location**: `omnibase.core.core_structured_logging`

```python
from omnibase.core.core_structured_logging import emit_log_event_sync as emit_log_event
from omnibase.enums.enum_log_level import LogLevelEnum

# Emit structured log events
emit_log_event(
    level=LogLevelEnum.INFO,
    message="Operation completed",
    event_type="operation_complete",
    correlation_id=correlation_id,
    data={"duration_ms": 150}
)
```

---

## Models (Core Data Structures)

### Contract Models

**Location**: `omnibase.core.models`

```python
from omnibase.core.models.model_semver import ModelSemVer
from omnibase.core.models.model_onex_envelope import ModelOnexEnvelope
from omnibase.core.models.model_onex_reply import ModelOnexReply
from omnibase.core.models.model_service import ModelService
from omnibase.core.models.model_contract_cache import ModelContractCache
```

**SemVer Model**:
```python
from omnibase.core.models.model_semver import ModelSemVer

version = ModelSemVer(major=1, minor=0, patch=0)
```

---

## Import Guidelines

### ✅ **ALWAYS IMPORT** (Never Regenerate)

1. **Error System**:
   - `OnexError`, `CoreErrorCode` - Exception handling
   - `ModelOnexError` - Pydantic error models
   - `CLIAdapter` - CLI exit code mapping

2. **Base Contracts**:
   - `ModelContractBase` - Contract foundation
   - `ModelPerformanceRequirements` - SLA specs
   - `ModelLifecycleConfig` - Lifecycle management
   - All subcontract models

3. **Node Base Classes**:
   - `NodeCoreBase` - Core foundation
   - `NodeCompute`, `NodeEffect`, `NodeReducer`, `NodeOrchestrator`

4. **Enums**:
   - `EnumNodeType` - 4-node architecture types
   - `EnumOnexStatus` - Standard status codes
   - `LogLevelEnum` - Logging levels

5. **Services & Utilities**:
   - `UUIDService` - UUID generation
   - `ONEXContainer` - Dependency injection
   - `emit_log_event` - Structured logging

### ⚠️ **IMPORT WITH CAUTION** (May Need Regeneration)

1. **Node-Specific Models**:
   - Tool-specific models in `omnibase.tools/**/models/` - Often need regeneration
   - Workflow models - May be project-specific

2. **Infrastructure Services**:
   - Database adapters - May need project-specific configuration
   - External service clients - May have different endpoints

### ❌ **NEVER IMPORT** (Always Regenerate)

1. **Business Logic**:
   - Node implementations (`execute_*` methods)
   - Tool-specific processing logic
   - Workflow orchestration implementations

2. **Project-Specific Code**:
   - Custom validators
   - Application-specific models
   - Custom error codes (extend `CoreErrorCode` instead)

---

## Usage in Node Generation

### Template Pattern

```python
"""
Generated Node: {node_name}
Type: {node_type}
"""

# IMPORTS - Always import these
from omnibase.core.core_errors import OnexError, CoreErrorCode
from omnibase.core.node_core_base import NodeCoreBase
from omnibase.core.model_contract_{node_type_lower} import ModelContract{NodeType}
from omnibase.core.core_uuid_service import UUIDService
from omnibase.enums.enum_node_type import EnumNodeType
from omnibase.enums.enum_onex_status import EnumOnexStatus

# GENERATED CODE - Node-specific implementation
class Node{Name}{NodeType}(NodeCoreBase):
    """Generated {node_type} node implementation."""

    def __init__(self, container: ONEXContainer) -> None:
        super().__init__(container)
        self.contract: ModelContract{NodeType} = None

    async def process(self, input_data: Any) -> Any:
        """Node-specific processing logic."""
        try:
            # Business logic here
            return result
        except Exception as e:
            raise OnexError(
                message=f"Processing failed: {e}",
                error_code=CoreErrorCode.OPERATION_FAILED,
                cause=e
            )
```

---

## Dependency Management

### pyproject.toml Requirements

```toml
[tool.poetry.dependencies]
python = ">=3.11,<3.13"
pyyaml = "^6.0.0"
jsonschema = "^4.21.1"
pydantic = "^2.0.0"
typer = "^0.12.3"
typing-extensions = "^4.13.2"
```

### Local Development

For development, you can reference `omnibase_3` locally:

```toml
[tool.poetry.dependencies]
omnibase_core = { path = "../omnibase_3", develop = true }
```

Or via git for specific branch:

```toml
[tool.poetry.dependencies]
omnibase_core = { git = "https://github.com/yourorg/omnibase_3.git", branch = "doc_fixes" }
```

---

## Key Architectural Patterns

### 1. Error Handling Pattern

```python
# Entry point (auto-generates correlation_id)
try:
    result = perform_operation()
except ValueError as e:
    raise OnexError(
        message="Invalid value provided",
        error_code=CoreErrorCode.VALIDATION_ERROR,
        cause=e
    )

# Internal processing (with correlation_id)
try:
    result = internal_operation()
except Exception as e:
    raise OnexError.with_correlation_id(
        message="Internal operation failed",
        correlation_id=correlation_id,
        error_code=CoreErrorCode.OPERATION_FAILED,
        cause=e
    )
```

### 2. Contract Loading Pattern

```python
async def _load_contract(self) -> None:
    """Load and validate contract from YAML."""
    try:
        contract_path = Path(f"contracts/{self.__class__.__name__}.yaml")
        if contract_path.exists():
            contract_data = yaml.safe_load(contract_path.read_text())
            self.contract = ModelContractEffect(**contract_data)
    except Exception as e:
        raise OnexError(
            message=f"Contract loading failed: {e}",
            error_code=CoreErrorCode.CONFIGURATION_PARSE_ERROR,
            cause=e
        )
```

### 3. Dependency Injection Pattern

```python
class NodeMyOperationEffect(NodeCoreBase):
    def __init__(self, container: ONEXContainer) -> None:
        super().__init__(container)

        # Resolve dependencies from container
        self.db_adapter = container.get_service("database_adapter")
        self.logger = container.get_service("logger")
```

---

## Common Pitfalls to Avoid

### ❌ **Anti-Pattern**: Using `Any` types

```python
# BAD
def process(self, input_data: Any) -> Any:
    pass
```

### ✅ **Correct**: Strong typing with Pydantic

```python
# GOOD
from pydantic import BaseModel

class ModelInputData(BaseModel):
    field1: str
    field2: int

def process(self, input_data: ModelInputData) -> ModelOutputData:
    pass
```

### ❌ **Anti-Pattern**: Manual correlation ID generation

```python
# BAD
correlation_id = str(uuid.uuid4())
```

### ✅ **Correct**: Use UUIDService

```python
# GOOD
from omnibase.core.core_uuid_service import UUIDService

correlation_id = UUIDService.generate_correlation_id()
```

### ❌ **Anti-Pattern**: Generic exception handling

```python
# BAD
try:
    operation()
except Exception as e:
    raise Exception(str(e))
```

### ✅ **Correct**: OnexError with proper error codes

```python
# GOOD
try:
    operation()
except Exception as e:
    raise OnexError(
        message=f"Operation failed: {e}",
        error_code=CoreErrorCode.OPERATION_FAILED,
        cause=e
    )
```

---

## Testing with Imported Dependencies

### Mock Pattern for Tests

```python
import pytest
from unittest.mock import Mock, MagicMock
from omnibase.core.onex_container import ONEXContainer
from omnibase.core.core_errors import OnexError, CoreErrorCode

@pytest.fixture
def mock_container():
    """Create mock container for testing."""
    container = Mock(spec=ONEXContainer)
    container.get_service = MagicMock()
    return container

def test_node_error_handling(mock_container):
    """Test proper error handling with OnexError."""
    node = NodeMyOperation(mock_container)

    with pytest.raises(OnexError) as exc_info:
        node.process(invalid_input)

    assert exc_info.value.error_code == CoreErrorCode.VALIDATION_ERROR
    assert exc_info.value.correlation_id is not None
```

---

## References

- **omnibase_3 Repository**: `../omnibase_3`
- **Core Module**: `omnibase_3/src/omnibase/core/`
- **Enums**: `omnibase_3/src/omnibase/enums/`
- **Models**: `omnibase_3/src/omnibase/core/models/`
- **Subcontracts**: `omnibase_3/src/omnibase/core/subcontracts/`

---

## Summary Checklist

When generating ONEX-compliant nodes:

- ✅ Import `OnexError` and `CoreErrorCode` for error handling
- ✅ Import `NodeCoreBase` or specialized node base class
- ✅ Import appropriate contract model (`ModelContractEffect`, etc.)
- ✅ Import `UUIDService` for correlation ID generation
- ✅ Import `EnumNodeType` and `EnumOnexStatus`
- ✅ Import `emit_log_event` for structured logging
- ✅ Use Pydantic models for strong typing
- ✅ Follow ONEX naming conventions (suffix-based)
- ✅ Implement lifecycle methods (`initialize`, `process`, `cleanup`)
- ✅ Track metrics and performance

**Result**: Consistent, maintainable, ONEX-compliant nodes with proper error handling, contracts, and dependency management.
