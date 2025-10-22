# Omnibase_3 Quick Reference Guide

**Last Updated**: 2025-10-22

## 🚀 Quick Start Imports

```python
# Essential imports for any ONEX node
from omnibase.core.core_errors import OnexError, CoreErrorCode
from omnibase.core.node_core_base import NodeCoreBase
from omnibase.core.core_uuid_service import UUIDService
from omnibase.enums.enum_node_type import EnumNodeType
from omnibase.enums.enum_onex_status import EnumOnexStatus
from omnibase.core.onex_container import ONEXContainer
```

---

## 📦 Import Categories

### ✅ Always Import (Core Infrastructure)

| Component | Import Path | Purpose |
|-----------|-------------|---------|
| OnexError | `omnibase.core.core_errors` | Exception handling |
| CoreErrorCode | `omnibase.core.core_errors` | Error code enum (200+ codes) |
| NodeCoreBase | `omnibase.core.node_core_base` | Base class for all nodes |
| UUIDService | `omnibase.core.core_uuid_service` | UUID generation |
| EnumNodeType | `omnibase.enums.enum_node_type` | COMPUTE/EFFECT/REDUCER/ORCHESTRATOR |
| EnumOnexStatus | `omnibase.enums.enum_onex_status` | SUCCESS/ERROR/WARNING/etc. |

### 🔧 Node-Specific Imports

| Node Type | Contract Import | Base Class Import |
|-----------|----------------|-------------------|
| **Effect** | `omnibase.core.model_contract_effect.ModelContractEffect` | `omnibase.core.node_effect.NodeEffect` |
| **Compute** | `omnibase.core.model_contract_compute.ModelContractCompute` | `omnibase.core.node_compute.NodeCompute` |
| **Reducer** | `omnibase.core.model_contract_reducer.ModelContractReducer` | `omnibase.core.node_reducer.NodeReducer` |
| **Orchestrator** | `omnibase.core.model_contract_orchestrator.ModelContractOrchestrator` | `omnibase.core.node_orchestrator.NodeOrchestrator` |

### 📝 Common Utility Imports

| Utility | Import Path | Use Case |
|---------|-------------|----------|
| emit_log_event | `omnibase.core.core_structured_logging` | Structured logging |
| LogLevelEnum | `omnibase.enums.enum_log_level` | Log levels (INFO/ERROR/DEBUG/etc.) |
| ModelSemVer | `omnibase.core.models.model_semver` | Version management |
| ONEXContainer | `omnibase.core.onex_container` | Dependency injection |

---

## 🎯 Error Codes Quick Reference

### Categories (Most Common)

| Range | Category | Examples |
|-------|----------|----------|
| 001-020 | Validation | INVALID_PARAMETER, VALIDATION_FAILED |
| 021-040 | File System | FILE_NOT_FOUND, PERMISSION_DENIED |
| 041-060 | Configuration | INVALID_CONFIGURATION, CONFIGURATION_PARSE_ERROR |
| 061-080 | Registry | REGISTRY_NOT_FOUND, DUPLICATE_REGISTRATION |
| 081-100 | Runtime | OPERATION_FAILED, TIMEOUT, RESOURCE_UNAVAILABLE |
| 131-140 | Database | DATABASE_CONNECTION_ERROR, DATABASE_QUERY_ERROR |
| 161-180 | Intelligence | NO_SUITABLE_PROVIDER, RATE_LIMIT_ERROR |

### Usage

```python
from omnibase.core.core_errors import OnexError, CoreErrorCode

# Validation error
raise OnexError(
    message="Invalid node type",
    error_code=CoreErrorCode.INVALID_PARAMETER,
    context={"parameter": "node_type", "value": "INVALID"}
)

# Operation failed
raise OnexError(
    message="Database query failed",
    error_code=CoreErrorCode.DATABASE_QUERY_ERROR,
    cause=original_exception
)
```

---

## 🏗️ Node Template Structure

### Effect Node Template

```python
"""
Node{Name}Effect - {description}
"""

from omnibase.core.core_errors import OnexError, CoreErrorCode
from omnibase.core.node_effect import NodeEffect
from omnibase.core.model_contract_effect import ModelContractEffect
from omnibase.core.core_uuid_service import UUIDService
from omnibase.core.onex_container import ONEXContainer
from omnibase.enums.enum_node_type import EnumNodeType

from pydantic import BaseModel


class ModelInput{Name}(BaseModel):
    """Input model for {name} effect."""
    field1: str
    field2: int


class ModelOutput{Name}(BaseModel):
    """Output model for {name} effect."""
    result: str
    status: str


class Node{Name}Effect(NodeEffect):
    """Effect node for {description}."""

    def __init__(self, container: ONEXContainer) -> None:
        super().__init__(container)
        self.node_type = EnumNodeType.EFFECT

    async def execute_effect(
        self,
        contract: ModelContractEffect
    ) -> ModelOutput{Name}:
        """Execute {name} effect operation."""
        try:
            # Implementation
            return ModelOutput{Name}(
                result="success",
                status="completed"
            )
        except Exception as e:
            raise OnexError(
                message=f"Effect execution failed: {e}",
                error_code=CoreErrorCode.OPERATION_FAILED,
                cause=e
            )
```

### Compute Node Template

```python
"""
Node{Name}Compute - {description}
"""

from omnibase.core.core_errors import OnexError, CoreErrorCode
from omnibase.core.node_compute import NodeCompute
from omnibase.core.model_contract_compute import ModelContractCompute
from omnibase.core.onex_container import ONEXContainer
from omnibase.enums.enum_node_type import EnumNodeType

from pydantic import BaseModel


class ModelInput{Name}(BaseModel):
    """Input model for {name} computation."""
    data: list[int]


class ModelOutput{Name}(BaseModel):
    """Output model for {name} computation."""
    result: int


class Node{Name}Compute(NodeCompute):
    """Compute node for {description}."""

    def __init__(self, container: ONEXContainer) -> None:
        super().__init__(container)
        self.node_type = EnumNodeType.COMPUTE

    async def execute_compute(
        self,
        contract: ModelContractCompute
    ) -> ModelOutput{Name}:
        """Execute pure computation."""
        try:
            # Pure computation - no side effects
            return ModelOutput{Name}(result=42)
        except Exception as e:
            raise OnexError(
                message=f"Computation failed: {e}",
                error_code=CoreErrorCode.OPERATION_FAILED,
                cause=e
            )
```

---

## 🔑 Key Patterns

### 1. Error Handling

```python
# Entry point (auto-generates correlation_id)
try:
    result = operation()
except ValueError as e:
    raise OnexError(
        message="Validation failed",
        error_code=CoreErrorCode.VALIDATION_ERROR,
        cause=e
    )

# With existing correlation_id
raise OnexError.with_correlation_id(
    message="Processing failed",
    correlation_id=correlation_id,
    error_code=CoreErrorCode.OPERATION_FAILED
)
```

### 2. UUID Generation

```python
from omnibase.core.core_uuid_service import UUIDService

# Generate correlation ID
correlation_id = UUIDService.generate_correlation_id()

# Generate event ID
event_id = UUIDService.generate_event_id()

# Validate UUID
is_valid = UUIDService.is_valid_uuid(value)
```

### 3. Structured Logging

```python
from omnibase.core.core_structured_logging import emit_log_event_sync as emit_log_event
from omnibase.enums.enum_log_level import LogLevelEnum

emit_log_event(
    level=LogLevelEnum.INFO,
    message="Operation completed",
    event_type="operation_complete",
    correlation_id=correlation_id,
    data={"duration_ms": 150}
)
```

---

## 📋 ONEX Naming Conventions

### File Naming (SUFFIX-based)

| Type | Pattern | Example |
|------|---------|---------|
| **Class** | `Node<Name><Type>` | `NodeDatabaseWriterEffect` |
| **File** | `node_*_<type>.py` | `node_database_writer_effect.py` |
| **Model** | `Model<Name>` | `ModelDatabaseConnection` |
| **Enum** | `Enum<Name>` | `EnumNodeType` |
| **Contract** | `ModelContract<Type>` | `ModelContractEffect` |

### Method Signatures

| Node Type | Method Signature |
|-----------|-----------------|
| **Effect** | `async def execute_effect(self, contract: ModelContractEffect) -> Any` |
| **Compute** | `async def execute_compute(self, contract: ModelContractCompute) -> Any` |
| **Reducer** | `async def execute_reduction(self, contract: ModelContractReducer) -> Any` |
| **Orchestrator** | `async def execute_orchestration(self, contract: ModelContractOrchestrator) -> Any` |

---

## 🧪 Testing Patterns

### Mock Container

```python
import pytest
from unittest.mock import Mock, MagicMock
from omnibase.core.onex_container import ONEXContainer

@pytest.fixture
def mock_container():
    """Mock container for testing."""
    container = Mock(spec=ONEXContainer)
    container.get_service = MagicMock()
    return container
```

### Test Error Handling

```python
def test_error_handling(mock_container):
    """Test OnexError propagation."""
    node = NodeMyOperation(mock_container)

    with pytest.raises(OnexError) as exc_info:
        node.process(invalid_input)

    assert exc_info.value.error_code == CoreErrorCode.VALIDATION_ERROR
    assert exc_info.value.correlation_id is not None
```

---

## 🔍 Debugging Checklist

When encountering issues:

- ✅ Check correlation_id is being generated/passed correctly
- ✅ Verify error_code is from `CoreErrorCode` enum
- ✅ Ensure `OnexError` includes `cause` for exception chaining
- ✅ Validate input/output models with Pydantic
- ✅ Check contract YAML syntax and structure
- ✅ Verify node type matches contract type
- ✅ Ensure container dependencies are resolved

---

## 📚 Additional Resources

- **Full Documentation**: `OMNIBASE3_IMPORTABLE_DEPENDENCIES.md`
- **Source**: `/Volumes/PRO-G40/Code/omnibase_3/src/omnibase/`
- **Core Module**: `omnibase_3/src/omnibase/core/`
- **Enums**: `omnibase_3/src/omnibase/enums/`

---

## 💡 Common Mistakes to Avoid

| ❌ Don't Do This | ✅ Do This Instead |
|-----------------|-------------------|
| `def process(self, data: Any)` | `def process(self, data: ModelInputData)` |
| `correlation_id = str(uuid4())` | `correlation_id = UUIDService.generate_correlation_id()` |
| `raise Exception("Error")` | `raise OnexError(message="Error", error_code=CoreErrorCode.OPERATION_FAILED)` |
| Hardcoded exit codes | Use `CLIAdapter.exit_with_error(error)` |
| Manual error serialization | Use `error.model_dump_json()` |

---

**End of Quick Reference** - See full documentation for detailed usage and advanced patterns.
