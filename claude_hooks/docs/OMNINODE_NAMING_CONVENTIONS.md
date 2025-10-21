# Omninode/Omnibase Naming Conventions

**Version**: 1.0.0
**Based on**: omnibase_core codebase analysis (508 files, 98% adherence)
**Last Updated**: 2025-09-30

## Overview

This document defines the official naming conventions for Omninode/Omnibase projects, derived from comprehensive analysis of the omnibase_core codebase. These conventions are enforced by the quality enforcement system pre-commit hooks.

**Why These Conventions?**

The Omninode project uses highly consistent, prefix-based naming patterns that provide:
- **Instant Recognition**: Class prefixes indicate purpose at a glance
- **Organizational Clarity**: File naming patterns match class patterns
- **Type Safety**: Clear naming aids IDE autocomplete and type checking
- **Codebase Consistency**: 98% adherence across 508 analyzed files

---

## Table of Contents

1. [Python Naming Conventions](#python-naming-conventions)
2. [File Naming Patterns](#file-naming-patterns)
3. [Class Naming Patterns](#class-naming-patterns)
4. [Function and Method Naming](#function-and-method-naming)
5. [Variable Naming](#variable-naming)
6. [Constants and Enum Values](#constants-and-enum-values)
7. [Special Patterns](#special-patterns)
8. [Examples](#examples)
9. [Enforcement](#enforcement)

---

## Python Naming Conventions

### Summary Table

| Element | Convention | Adherence | Example |
|---------|-----------|-----------|---------|
| **Model Files** | `model_*.py` | 93% | `model_task_data.py` |
| **Enum Files** | `enum_*.py` | 99% | `enum_status.py` |
| **TypedDict Files** | `typed_dict_*.py` | 100% | `typed_dict_result_kwargs.py` |
| **Model Classes** | `Model<Name>` | 100% | `ModelTaskData` |
| **Enum Classes** | `Enum<Name>` | 100% | `EnumStatus` |
| **Functions** | `snake_case` | 100% | `execute_effect()` |
| **Variables** | `snake_case` | 100% | `correlation_id` |
| **Constants** | `UPPER_SNAKE_CASE` | 100% | `MAX_FILE_SIZE` |

---

## File Naming Patterns

### Models

**Pattern**: `model_<descriptive_name>.py`
**Adherence**: 93% (313/336 files)

Files containing Pydantic `BaseModel` subclasses should use the `model_` prefix.

**Examples**:
```
✅ model_task_data.py
✅ model_contract_base.py
✅ model_field_accessor.py
✅ model_result_factory.py
✅ model_configuration_base.py

❌ task_data.py          # Missing model_ prefix
❌ TaskDataModel.py      # Wrong case
```

**Rationale**: The `model_` prefix provides immediate recognition of Pydantic model files in the codebase, matching the class naming pattern.

---

### Enums

**Pattern**: `enum_<descriptive_name>.py`
**Adherence**: 99% (124/125 files)

Files containing `Enum` subclasses should use the `enum_` prefix.

**Examples**:
```
✅ enum_status.py
✅ enum_node_type.py
✅ enum_execution_status.py
✅ enum_validation_severity.py

❌ status.py              # Missing enum_ prefix
❌ StatusEnum.py          # Wrong case
```

**Rationale**: Clear separation of enum definitions from other code, matching the class naming pattern.

---

### TypedDicts

**Pattern**: `typed_dict_<descriptive_name>.py`
**Adherence**: 100% (15/15 files)

Files containing `TypedDict` definitions should use the `typed_dict_` prefix.

**Examples**:
```
✅ typed_dict_result_factory_kwargs.py
✅ typed_dict_debug_info_data.py
✅ typed_dict_cli_input_dict.py
✅ typed_dict_field_value.py

❌ result_kwargs.py       # Missing typed_dict_ prefix
```

**Rationale**: TypedDicts are type-safe dictionary structures with specific structure, deserving distinct naming.

---

### Utility and Service Files

**Pattern**: `<descriptive_name>.py` (snake_case, no prefix)
**Used for**: Utility functions, helper modules, services

**Examples**:
```
✅ uuid_utilities.py
✅ validation_utils.py
✅ safe_yaml_loader.py
✅ model_field_converter.py
```

**Rationale**: Utility files use descriptive snake_case names focusing on their purpose rather than structure.

---

## Class Naming Patterns

### Model Classes (Pydantic BaseModel)

**Pattern**: `Model<DescriptiveName>` (PascalCase with "Model" prefix)
**Adherence**: 100% (371/371 classes)

All Pydantic `BaseModel` subclasses **must** start with the "Model" prefix.

**Examples**:
```python
✅ class ModelTaskData(BaseModel):
    """Task data model for validation operations."""
    pass

✅ class ModelContractBase(BaseModel):
    """Base contract model."""
    pass

✅ class ModelFieldAccessor(BaseModel):
    """Generic field accessor with dot notation."""
    pass

❌ class TaskData(BaseModel):           # Missing Model prefix
❌ class taskData(BaseModel):           # Wrong case
❌ class DataModel(BaseModel):          # Wrong prefix placement
```

**Rationale**: The 100% adherence in the codebase demonstrates this is a critical convention. The "Model" prefix provides:
- Instant recognition of Pydantic models
- Clear distinction from dataclasses and other classes
- Consistent autocomplete grouping in IDEs

---

### Enum Classes

**Pattern**: `Enum<DescriptiveName>` (PascalCase with "Enum" prefix)
**Adherence**: 100% (137/137 classes)

All `Enum` subclasses **must** start with the "Enum" prefix and inherit from `(str, Enum)`.

**Examples**:
```python
✅ class EnumTaskStatus(str, Enum):
    """Task status enumeration."""
    TODO = "todo"
    DOING = "doing"
    REVIEW = "review"
    DONE = "done"

✅ class EnumNodeType(str, Enum):
    """Node type enumeration."""
    EFFECT = "effect"
    COMPUTE = "compute"
    REDUCER = "reducer"
    ORCHESTRATOR = "orchestrator"

❌ class TaskStatus(str, Enum):         # Missing Enum prefix
❌ class StatusEnum(str, Enum):         # Wrong prefix placement
```

**Rationale**: The "Enum" prefix ensures clear identification of enumeration types, with 100% adherence showing this is non-negotiable.

---

### TypedDict Classes

**Pattern**: `TypedDict<DescriptiveName>` (PascalCase with "TypedDict" prefix)
**Adherence**: 100%

TypedDict classes should start with the "TypedDict" prefix for clarity.

**Examples**:
```python
✅ class TypedDictResultFactoryKwargs(TypedDict):
    """Keyword arguments for result factory."""
    success: bool
    value: Any

✅ class TypedDictPerformanceMetricData(TypedDict):
    """Performance metric data structure."""
    metric_name: str
    value: Union[int, float]

❌ class ResultKwargs(TypedDict):       # Missing TypedDict prefix
```

**Rationale**: Clear distinction from Pydantic models and standard dicts.

---

### Base Classes

**Pattern**: `Base<Name>` (PascalCase with "Base" prefix)
**Used for**: Abstract base classes

**Examples**:
```python
✅ class BaseCollection(ABC):
    """Base collection class."""
    pass

✅ class BaseFactory(ABC):
    """Base factory class."""
    pass
```

**Rationale**: Standard Python convention for abstract base classes.

---

### Node Service Classes

**Pattern**: `Node<Type>Service` (PascalCase with "Node" prefix and "Service" suffix)

ONEX Four-Node Architecture service classes follow a specific pattern that identifies the node type.

**Examples**:
```python
✅ class NodeEffectService:
    """EFFECT node base class for external interactions."""
    async def execute_effect(self, contract):
        pass

✅ class NodeComputeService:
    """COMPUTE node base class for data processing."""
    async def execute_compute(self, contract):
        pass

✅ class NodeReducerService:
    """REDUCER node base class for state management."""
    async def execute_reduction(self, contract):
        pass

✅ class NodeOrchestratorService:
    """ORCHESTRATOR node base class for workflow coordination."""
    async def execute_orchestration(self, contract):
        pass

❌ class EffectNode:              # Wrong - missing Service suffix
❌ class EffectNodeService:       # Wrong - incorrect order
❌ class NodeEffect:              # Wrong - missing Service suffix
```

**File Naming**:
```
✅ node_effect_service.py
✅ node_compute_service.py
✅ node_reducer_service.py
✅ node_orchestrator_service.py

❌ effect_service.py          # Missing node_ prefix
❌ node_effect.py             # Missing _service suffix
```

**Rationale**: Clear identification of ONEX architecture nodes with consistent naming across the four-node system.

---

### Protocol Classes

**Pattern**: `<Name>` or `Protocol<Name>` (PascalCase, mixed convention)

Protocol classes use a flexible naming pattern:
- **Simple capability names** for common protocols: `Serializable`, `Configurable`, `Identifiable`
- **Protocol prefix** for complex protocols: `ProtocolMetadataProvider`, `ProtocolValidatable`

**Examples**:
```python
# ✅ Simple capability names (preferred for common protocols)
class Serializable(Protocol):
    """Serialization capability."""
    def serialize(self) -> dict[str, Any]: ...

class Configurable(Protocol):
    """Configuration capability."""
    def configure(self, **kwargs: Any) -> bool: ...

class Identifiable(Protocol):
    """Identification capability."""
    def get_id(self) -> str: ...

class Nameable(Protocol):
    """Naming capability."""
    def get_name(self) -> str: ...

# ✅ Protocol prefix for complex protocols
class ProtocolMetadataProvider(Protocol):
    """Complex metadata provisioning protocol."""
    def get_metadata(self) -> dict[str, Any]: ...
    def set_metadata(self, metadata: dict[str, Any]) -> None: ...

class ProtocolValidatable(Protocol):
    """Complex validation protocol."""
    def validate(self) -> bool: ...
    def get_validation_errors(self) -> list[str]: ...

❌ class serializable(Protocol):     # Wrong case
❌ class SerializableProtocol:       # Wrong - suffix instead of prefix
```

**Rationale**: Simple protocols get simple names, complex protocols get descriptive prefixes. This matches actual codebase patterns with mixed conventions based on complexity.

---

### Subcontract Classes

**Pattern**: `Model<Type>Subcontract` (PascalCase with "Model" prefix and "Subcontract" suffix)

Subcontracts are specialized contract models for specific behaviors within the ONEX architecture.

**Examples**:
```python
✅ class ModelAggregationSubcontract(BaseModel):
    """Subcontract for data aggregation operations."""
    aggregation_type: str
    aggregation_config: dict[str, Any]

✅ class ModelFSMSubcontract(BaseModel):
    """Finite State Machine subcontract."""
    state_machine: dict[str, Any]
    initial_state: str

✅ class ModelCachingSubcontract(BaseModel):
    """Caching behavior subcontract."""
    cache_config: dict[str, Any]
    cache_ttl: int

✅ class ModelRoutingSubcontract(BaseModel):
    """Request routing subcontract."""
    routing_rules: list[dict[str, Any]]

❌ class AggregationSubcontract(BaseModel):     # Missing Model prefix
❌ class SubcontractAggregation(BaseModel):     # Wrong suffix placement
```

**File Naming**:
```
✅ model_aggregation_subcontract.py
✅ model_fsm_subcontract.py
✅ model_caching_subcontract.py
✅ model_routing_subcontract.py

❌ aggregation_subcontract.py     # Missing model_ prefix
❌ subcontract_aggregation.py     # Wrong order
```

**Rationale**: Subcontracts are specialized models, so they follow the Model prefix convention with a Subcontract suffix for clarity.

---

### Mixin Classes

**Pattern**: `Mixin<Capability>` (PascalCase with "Mixin" prefix)

Mixin classes provide reusable capabilities through composition.

**Examples**:
```python
✅ class MixinNodeService:
    """Service integration and lifecycle management."""
    def get_service(self, service_name: str):
        pass

✅ class MixinHealthCheck:
    """Health monitoring and status reporting."""
    def check_health(self) -> bool:
        pass

✅ class MixinEventDrivenNode:
    """Event-based processing and handling."""
    def handle_event(self, event):
        pass

✅ class MixinLogging:
    """Logging capabilities."""
    def log(self, message: str, level: str):
        pass

❌ class NodeServiceMixin:         # Wrong - suffix instead of prefix
❌ class HealthCheckMixin:         # Wrong - suffix instead of prefix
```

**Rationale**: Mixin prefix clearly identifies classes that provide reusable behavior through composition, following Python mixin conventions.

---

### General Service Classes

**Pattern**: `<Name>Service` or descriptive names (no strict pattern)

General service classes (not ONEX nodes) use descriptive names, often with Service suffix.

**Examples**:
```python
✅ class SimplifiedSessionManager:
    """Session manager service."""
    pass

✅ class DatabaseConnectionPool:
    """Database connection pooling."""
    pass

✅ class EventBus:
    """Event bus for pub/sub."""
    pass
```

**Rationale**: General services have flexible naming focused on clarity and purpose.

---

### Exception Classes

**Pattern**: `<Context>Error` (PascalCase with "Error" suffix)

**Examples**:
```python
✅ class ValidationError(OnexError):
    """Validation error."""
    pass

✅ class ContractValidationError(OnexError):
    """Contract validation error."""
    pass

✅ class EffectNodeError(NodeOperationError):
    """Error in EFFECT node operations."""
    pass

❌ class ValidationException(OnexError):  # Use Error, not Exception
❌ class ErrorValidation(OnexError):      # Wrong suffix placement
```

**Rationale**: Standard Python exception naming with context-specific prefix.

---

### Dataclass Classes

**Pattern**: `<DescriptiveName>` (PascalCase, no prefix)

Dataclasses do not require prefixes as they serve different purposes from Pydantic models.

**Examples**:
```python
✅ @dataclass
class ValidationResult:
    """Validation result data."""
    success: bool
    errors: list[str]

✅ @dataclass
class DuplicationInfo:
    """Duplication information."""
    signature_hash: str
    protocols: list[ModelProtocolInfo]
```

**Rationale**: Dataclasses are lightweight data holders, distinct from Pydantic models.

---

## Function and Method Naming

### All Functions and Methods

**Pattern**: `snake_case`
**Adherence**: 100%

All functions and methods use snake_case without exception.

**Examples**:
```python
✅ def execute_effect(self, contract: ModelContractEffect):
    """Execute EFFECT node operation."""
    pass

✅ def validate_contract(self, contract: ModelContractBase):
    """Validate contract data."""
    pass

✅ def get_field(self, path: str):
    """Get field using dot notation."""
    pass

❌ def ExecuteEffect(self, contract):     # Wrong case
❌ def executeEffect(self, contract):     # Use snake_case, not camelCase
```

---

### Private Methods

**Pattern**: `_<verb>_<noun>` (snake_case with leading underscore)

**Examples**:
```python
✅ def _validate_input(self, data):
    """Validate input data (private)."""
    pass

✅ def _handle_error(self, error):
    """Handle error (private)."""
    pass

✅ def _build_result(self, **kwargs):
    """Build result object (private)."""
    pass
```

**Rationale**: Leading underscore indicates internal/private methods.

---

### Node Operation Methods

**Pattern**: `execute_<node_type>` or `execute_<operation>`

Special pattern for ONEX node operations.

**Examples**:
```python
✅ async def execute_effect(self, contract: ModelContractEffect):
    """Execute EFFECT node operation."""
    pass

✅ async def execute_compute(self, contract: ModelContractCompute):
    """Execute computational processing."""
    pass

✅ async def execute_reduction(self, contract: ModelContractReducer):
    """Execute data reduction."""
    pass
```

**Rationale**: Consistent naming for ONEX architecture node operations.

---

### Validation Methods

**Pattern**: `validate_<target>` or `_validate_<target>` (private)

**Examples**:
```python
✅ def validate_contract(self, contract):
    """Validate contract data."""
    pass

✅ def _validate_input_data(self, data):
    """Validate input data (private)."""
    pass

✅ @validator("title")
def validate_title(cls, v):
    """Validate title field."""
    return v
```

**Rationale**: Clear indication of validation logic.

---

### Common Verb Patterns

```python
get_*           # Retrieval methods (get_field, get_name, get_value)
set_*           # Setter methods (set_field, set_name, set_value)
has_*           # Boolean check methods (has_field, has_permission)
is_*            # Boolean state methods (is_valid, is_enabled)
validate_*      # Validation methods (validate_contract, validate_input)
execute_*       # Execution methods (execute_effect, execute_workflow)
create_*        # Factory methods (create_empty, create_with_data)
register_*      # Registration methods (register_builder, register_handler)
```

---

## Variable Naming

### Instance Variables and Parameters

**Pattern**: `snake_case`
**Adherence**: 100%

All instance variables, local variables, and parameters use snake_case.

**Examples**:
```python
✅ class ModelTaskData(BaseModel):
    task_title: str
    task_order: int
    correlation_id: UUID
    created_at: datetime

✅ def execute_effect(self, contract: ModelContractEffect, correlation_id: UUID):
    task_data = contract.task_data
    config_value = self.get_config_value()
    return result
```

**Never use camelCase for variables** in Python code.

---

### Special Variable: correlation_id

**Pattern**: `correlation_id` (always this exact name)
**Adherence**: Universal standard

The correlation ID is **always** named `correlation_id` throughout the codebase.

**Examples**:
```python
✅ correlation_id: UUID
✅ self.correlation_id
✅ contract.correlation_id

❌ correlationId        # Wrong case
❌ corr_id             # Wrong abbreviation
❌ correlation_uuid    # Wrong suffix
```

**Rationale**: Universal consistency for tracing and debugging.

---

### Configuration Variables

**Pattern**: `<purpose>_config`

**Examples**:
```python
✅ algorithm_config: ModelAlgorithmConfig
✅ retry_config: ModelEffectRetryConfig
✅ performance_config: ModelAggregationPerformance
```

**Rationale**: Clear indication of configuration objects.

---

### Type Variables

**Pattern**: PascalCase (often ending with "Type")

**Examples**:
```python
✅ T = TypeVar("T")  # Success type
✅ E = TypeVar("E")  # Error type
✅ ModelType = TypeVar("ModelType", bound=BaseModel)
✅ SerializableType = TypeVar("SerializableType", bound=Serializable)
```

**Rationale**: Type variables follow PascalCase convention to distinguish from regular variables.

---

## Constants and Enum Values

### Module-Level Constants

**Pattern**: `UPPER_SNAKE_CASE`
**Adherence**: 100%

**Examples**:
```python
✅ MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
✅ DEFAULT_TIMEOUT = 300  # 5 minutes
✅ VALIDATION_TIMEOUT = 300
✅ LEGACY_ENUM_STATUS_VALUES = {...}

❌ maxFileSize = 50 * 1024 * 1024    # Wrong case
❌ Max_File_Size = 50 * 1024 * 1024  # Wrong case
```

**Rationale**: Standard Python convention for constants.

---

### Enum Values

**Pattern**: `UPPER_SNAKE_CASE` for names, `lowercase` for string values
**Adherence**: 100%

**Examples**:
```python
✅ class EnumTaskStatus(str, Enum):
    TODO = "todo"
    DOING = "doing"
    REVIEW = "review"
    DONE = "done"
    IN_PROGRESS = "in_progress"

✅ class EnumNodeType(str, Enum):
    EFFECT = "effect"
    COMPUTE = "compute"
    REDUCER = "reducer"
    ORCHESTRATOR = "orchestrator"

❌ class EnumTaskStatus(str, Enum):
    Todo = "todo"              # Wrong case for enum member
    doing = "doing"            # Wrong case for enum member
```

**Rationale**: Enum members use UPPER_SNAKE_CASE, values use lowercase with underscores for readability.

---

## Special Patterns

### One Model Per File Rule

**Rule**: Each file should contain exactly one primary model class.

**Examples**:
```python
# ✅ Good: model_task_data.py
class ModelTaskData(BaseModel):
    """Primary model in this file."""
    pass

# Supporting classes in same file are allowed
class TaskStatus(str, Enum):
    """Supporting enum."""
    TODO = "todo"

# ❌ Bad: multiple primary models in one file
class ModelTaskData(BaseModel):
    pass

class ModelProjectData(BaseModel):  # Should be in model_project_data.py
    pass
```

**Rationale**: Improves code organization and reduces file complexity.

---

### Result Pattern

**Pattern**: Use `ModelResult[T, E]` for error handling

**Examples**:
```python
✅ def get_field(self, path: str) -> ModelResult[ModelSchemaValue, str]:
    """Get field using dot notation."""
    try:
        value = self._get_field_internal(path)
        return ModelResult.ok(value)
    except Exception as e:
        return ModelResult.err(f"Error: {e}")
```

**Rationale**: Type-safe error handling without exceptions.

---

### Factory Pattern

**Pattern**: Factory classes use `Model*Factory` naming

**Examples**:
```python
✅ class ModelResultFactory(ModelGenericFactory[T]):
    """Factory for creating result models."""
    pass

✅ class ModelCapabilityFactory:
    """Factory for creating capability instances."""
    pass
```

**Rationale**: Clear identification of factory classes.

---

## Examples

### Complete Model Example

```python
"""
Task Data Model

Pydantic model for task validation operations.
File: model_task_data.py
"""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field
from enum import Enum


class EnumTaskStatus(str, Enum):
    """Task status enumeration."""
    TODO = "todo"
    DOING = "doing"
    REVIEW = "review"
    DONE = "done"


class ModelTaskData(BaseModel):
    """
    Task data model for validation operations.

    Example:
        task = ModelTaskData(
            task_title="Implement feature",
            task_order=10,
            status=EnumTaskStatus.TODO,
            correlation_id=uuid4()
        )
    """

    # Instance variables (snake_case)
    task_title: str = Field(..., min_length=1, max_length=200)
    task_order: int = Field(0, ge=0, le=100)
    status: EnumTaskStatus
    correlation_id: UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)
    assignee: Optional[str] = None

    # Configuration
    model_config = {
        "extra": "ignore",
        "validate_assignment": True,
    }

    # Public methods (snake_case)
    def validate_business_rules(self) -> bool:
        """Validate business rules."""
        if self.task_order > 80 and not self.assignee:
            return False
        return True

    def get_task_title(self) -> str:
        """Get task title."""
        return self.task_title

    # Private methods (_snake_case)
    def _normalize_title(self, title: str) -> str:
        """Normalize task title."""
        return title.strip()

    # Class methods
    @classmethod
    def create_default(cls) -> "ModelTaskData":
        """Create default task."""
        return cls(
            task_title="New Task",
            status=EnumTaskStatus.TODO,
            correlation_id=uuid4()
        )


# Constants (UPPER_SNAKE_CASE)
MAX_TASK_TITLE_LENGTH = 200
DEFAULT_TASK_ORDER = 0

# Export
__all__ = ["ModelTaskData", "EnumTaskStatus", "MAX_TASK_TITLE_LENGTH"]
```

---

### Complete Service Example

```python
"""
Session Manager Service

Manages MCP session state with expiration.
File: mcp_session_manager.py
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional


class SimplifiedSessionManager:
    """
    Simplified MCP session manager.

    Tracks session IDs and handles expiration.
    """

    def __init__(self, timeout: int = 3600):
        """
        Initialize session manager.

        Args:
            timeout: Session expiration time in seconds (default: 1 hour)
        """
        # Instance variables (snake_case)
        self.sessions: dict[str, datetime] = {}
        self.timeout = timeout

    # Public methods (snake_case)
    def create_session(self) -> str:
        """Create a new session and return its ID."""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = datetime.now()
        return session_id

    def validate_session(self, session_id: str) -> bool:
        """Validate a session ID and update last seen time."""
        if session_id not in self.sessions:
            return False

        last_seen = self.sessions[session_id]
        if datetime.now() - last_seen > timedelta(seconds=self.timeout):
            del self.sessions[session_id]
            return False

        self.sessions[session_id] = datetime.now()
        return True

    def get_active_session_count(self) -> int:
        """Get count of active sessions."""
        self.cleanup_expired_sessions()
        return len(self.sessions)

    # Private methods (_snake_case)
    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions and return count removed."""
        now = datetime.now()
        expired = []

        for session_id, last_seen in self.sessions.items():
            if now - last_seen > timedelta(seconds=self.timeout):
                expired.append(session_id)

        for session_id in expired:
            del self.sessions[session_id]

        return len(expired)


# Constants (UPPER_SNAKE_CASE)
DEFAULT_SESSION_TIMEOUT = 3600

# Global instance
_session_manager: Optional[SimplifiedSessionManager] = None


def get_session_manager() -> SimplifiedSessionManager:
    """Get the global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SimplifiedSessionManager()
    return _session_manager
```

---

## Enforcement

### Pre-commit Hook

The naming conventions are automatically enforced by pre-commit hooks using the `naming_validator.py` module.

**How it works**:
1. Before each commit, all Python files are analyzed
2. Violations are reported with suggestions
3. Commit is blocked if violations are found
4. Developer fixes violations and re-commits

**Example Violation**:
```
model_task_data.py:10:0: class 'TaskData' should be Model<Name> (PascalCase with Model prefix)
(Omninode BaseModel classes must start with 'Model' prefix (100% adherence), use 'ModelTaskData' instead)
```

---

### Quality Scoring

Files are scored based on naming convention adherence:

```python
NAMING_QUALITY_WEIGHTS = {
    "file_naming_adherence": 0.15,      # 15% weight
    "class_naming_adherence": 0.25,     # 25% weight (critical)
    "function_naming_adherence": 0.20,  # 20% weight
    "variable_naming_adherence": 0.15,  # 15% weight
    "constant_naming_adherence": 0.10,  # 10% weight
    "docstring_presence": 0.10,         # 10% weight
    "type_annotation_coverage": 0.05,   # 5% weight
}
```

Target: **95%+ adherence** for production code.

---

### Monitoring Violations

The quality enforcer provides dedicated violation tracking to monitor naming convention issues across your codebase.

#### Violations Log

**Location**: `~/.claude/hooks/logs/violations.log`

This log file records all naming convention violations in a simple one-line-per-file format:

```
[2025-09-30T11:30:45Z] omnibase_core/models/user.py - 3 violations: ModelUser (line 6), ModelProfile (line 11), get_user_name (line 15)
[2025-09-30T11:31:12Z] omnimcp/tools/helper.py - 1 violation: calculate_total (line 42)
[2025-09-30T11:32:05Z] omniplan/tasks/processor.py - 2 violations: TaskData (line 8), processTask (line 23)
```

**Features**:
- One line per file with violations
- Includes timestamp (UTC), file path, violation count, and affected names with line numbers
- Automatic log rotation when size exceeds 10MB
- Shows first 5 violations per file (indicates "... and N more" if additional violations exist)

#### Violations Summary

**Location**: `~/.claude/hooks/logs/violations_summary.json`

Structured JSON summary tracking violations over time:

```json
{
  "last_updated": "2025-09-30T11:30:45Z",
  "total_violations_today": 12,
  "files_with_violations": [
    {
      "path": "omnibase_core/models/user.py",
      "violations": 3,
      "timestamp": "2025-09-30T11:30:45Z",
      "suggestions": ["ModelUser", "ModelProfile", "get_user_name"]
    }
  ]
}
```

**Features**:
- Keeps last 100 violation events (configurable)
- Resets daily counter at midnight UTC
- Includes suggested corrections for each violation
- Machine-readable format for analytics and reporting

#### Real-Time Monitoring

Watch violations as they occur:

```bash
# Monitor violations in real-time
tail -f ~/.claude/hooks/logs/violations.log

# Or use the helper script
./bin/watch-violations.sh
```

#### Violations Summary Report

View today's violation summary with statistics:

```bash
# Display formatted summary (requires jq)
./bin/violations-summary.sh

# Or view raw JSON
cat ~/.claude/hooks/logs/violations_summary.json | jq
```

The summary script shows:
- Last update timestamp
- Total violations today
- Recent files with violations (last 10)
- Top 10 most common suggestions
- Quick access to watching live violations

#### Configuration

Configure violation logging in `config.yaml`:

```yaml
logging:
  violations_log: "~/.claude/hooks/logs/violations.log"
  violations_summary: "~/.claude/hooks/logs/violations_summary.json"
  max_violations_history: 100  # Keep last 100 violations
  max_size_mb: 10  # Log rotation threshold
```

#### Helper Scripts

**Location**: `/claude-hooks-backup/bin/`

1. **`watch-violations.sh`**: Real-time violation monitoring
   ```bash
   ./bin/watch-violations.sh
   # Displays violations as they occur
   # Press Ctrl+C to stop
   ```

2. **`violations-summary.sh`**: Daily summary report
   ```bash
   ./bin/violations-summary.sh
   # Shows formatted statistics and top suggestions
   # Requires jq: brew install jq
   ```

#### Example Output

**Violations Log** (`tail -f ~/.claude/hooks/logs/violations.log`):
```
[2025-09-30T11:30:45Z] omnibase_core/models/user.py - 3 violations: User (line 6), Profile (line 11), getUserName (line 15)
[2025-09-30T11:31:12Z] omnimcp/tools/helper.py - 1 violation: calculateTotal (line 42)
```

**Summary Report** (`./bin/violations-summary.sh`):
```
======================================================================
Violations Summary
======================================================================

Last Updated: 2025-09-30T11:32:05Z
Total Violations Today: 6

Recent Files with Violations:
------------------------------
  • omnibase_core/models/user.py - 3 violations at 2025-09-30T11:30:45Z
  • omnimcp/tools/helper.py - 1 violation at 2025-09-30T11:31:12Z
  • omniplan/tasks/processor.py - 2 violations at 2025-09-30T11:32:05Z

Top Suggestions:
-----------------
  • ModelUser (3x)
  • calculate_total (2x)
  • ModelTaskData (1x)

======================================================================
Full summary: ~/.claude/hooks/logs/violations_summary.json
Watch live: ./bin/watch-violations.sh
======================================================================
```

---

## Auto-Detection

### Repository Type Auto-Detection

The naming validator automatically detects the repository type to apply the appropriate conventions:

- **Omninode repositories**: Enforces Omninode-specific conventions (Model* prefix, etc.)
- **Other repositories**: Uses standard PEP 8 conventions

**Detection Rules**:

1. **Omninode Repository Patterns**:
   - Path contains `omnibase_` (case-insensitive)
     - Examples: `/path/to/omnibase_core/`, `/home/user/OMNIBASE_SPI/`
   - Path contains `/omni` followed by lowercase letter
     - Examples: `/path/to/omniauth/`, `/home/user/omnitools/`

2. **Non-Omninode Repository Patterns** (use standard PEP 8):
   - Path contains `Archon` - uses standard PEP 8
   - Path contains `omninode_bridge` - **explicitly excluded** from Omninode conventions
     - The omninode_bridge repository uses standard PEP 8, not Omninode conventions
     - Example: `/path/to/omninode_bridge/sync.py` uses standard PascalCase (no Model prefix)
   - Any other path - uses standard PEP 8

**Examples**:

```python
# In /path/to/omnibase_core/models.py (Omninode repo)
class User(BaseModel):  # ❌ Violation: needs Model prefix
    username: str

class ModelUser(BaseModel):  # ✅ Valid: has Model prefix
    username: str

# In /path/to/Archon/models.py (Non-Omninode repo)
class User(BaseModel):  # ✅ Valid: standard PEP 8 (PascalCase)
    username: str

class ModelUser(BaseModel):  # ✅ Also valid: PascalCase
    username: str

# In /path/to/omninode_bridge/models.py (Excluded from Omninode conventions)
class User(BaseModel):  # ✅ Valid: uses standard PEP 8 (no Model prefix needed)
    username: str

class SyncStatus(BaseModel):  # ✅ Valid: standard PascalCase
    is_synced: bool
```

### Validation Modes

The validator supports three modes:

1. **`auto` (default)**: Auto-detect repository type
   ```python
   validator = NamingValidator(validation_mode="auto")
   # Automatically detects Omninode vs standard repos
   ```

2. **`omninode`**: Force Omninode conventions
   ```python
   validator = NamingValidator(validation_mode="omninode")
   # Always enforces Model* prefix, etc.
   ```

3. **`pep8`**: Force standard PEP 8
   ```python
   validator = NamingValidator(validation_mode="pep8")
   # Always uses standard PEP 8 conventions
   ```

### Standard PEP 8 Conventions (Non-Omninode)

When auto-detection identifies a non-Omninode repository, these conventions apply:

**Classes**: PascalCase (no prefix requirement)
```python
✅ class User(BaseModel):
    username: str

✅ class TaskManager:
    pass
```

**Functions**: snake_case
```python
✅ def execute_task():
    pass
```

**Variables**: snake_case
```python
✅ task_data = {}
✅ is_enabled = True
```

**Constants**: UPPER_SNAKE_CASE
```python
✅ MAX_FILE_SIZE = 1024
✅ DEFAULT_TIMEOUT = 300
```

### Configuration Override

You can override the auto-detection in code:

```python
# In quality_enforcer.py
validator = NamingValidator(
    language="python",
    validation_mode="omninode"  # Force Omninode conventions
)
```

Or set environment variables:
```bash
# Force Omninode mode globally
export NAMING_VALIDATION_MODE="omninode"

# Force PEP 8 mode globally
export NAMING_VALIDATION_MODE="pep8"
```

### Detection Examples

**Omninode Repository Detection**:
```python
# These paths are detected as Omninode repositories:
✅ /path/to/omnibase_core/models.py
✅ /home/user/OMNIBASE_SPI/utils.py
✅ /path/to/omniauth/service.py
✅ /home/user/omnitools/helpers.py
```

**Non-Omninode Repository Detection**:
```python
# These paths are detected as standard PEP 8 repositories:
✅ /path/to/Archon/models.py
✅ /home/user/django-app/models.py
✅ /usr/local/lib/python/test.py
✅ /projects/my-blog/api.py
```

### Same Code, Different Validation

The same code will be validated differently based on repository detection:

```python
from pydantic import BaseModel

class User(BaseModel):
    username: str
```

**In Omninode repo** (`/path/to/omnibase_core/models.py`):
```
❌ VIOLATION: class 'User' should be Model<Name>
   (Omninode BaseModel classes must start with 'Model' prefix)
   Suggestion: ModelUser
```

**In Archon repo** (`/path/to/Archon/models.py`):
```
✅ VALID: PascalCase class name follows PEP 8
```

---

## Quick Reference

### Cheat Sheet

```
FILES:
  Models             → model_*.py
  Enums              → enum_*.py
  TypedDicts         → typed_dict_*.py
  Node Services      → node_<type>_service.py
  Subcontracts       → model_*_subcontract.py
  Utils              → descriptive_name.py

CLASSES:
  Pydantic models    → ModelXxx (PascalCase)
  Enums              → EnumXxx (PascalCase)
  TypedDicts         → TypedDictXxx (PascalCase)
  Protocols          → Xxx or ProtocolXxx (mixed pattern)
  Node Services      → Node<Type>Service (ONEX nodes)
  Subcontracts       → Model<Type>Subcontract
  Mixins             → Mixin<Capability>
  Base classes       → BaseXxx (PascalCase)
  General Services   → <Name>Service or descriptive
  Exceptions         → <Context>Error

FUNCTIONS/METHODS:
  All functions      → function_name (snake_case)
  Private            → _function_name (leading underscore)
  Node operations    → execute_<node_type>
  Validation         → validate_<target>

VARIABLES:
  Instance/local     → variable_name (snake_case)
  Type variables     → TypeName (PascalCase)
  Constants          → CONSTANT_NAME (UPPER_SNAKE_CASE)
  Enum members       → MEMBER_NAME (UPPER_SNAKE_CASE)

SPECIAL:
  Correlation ID     → correlation_id (always exact)
  Config vars        → <purpose>_config
```

---

## Rationale Summary

These conventions are not arbitrary - they are derived from actual codebase analysis showing:

- **98% overall adherence** across 508 Python files
- **100% adherence** for critical patterns (Model prefix, Enum prefix, functions)
- **93-100% adherence** for file naming patterns

The high consistency demonstrates these conventions work well at scale and should be maintained for new code.

Key benefits:
1. **Predictability**: Developers know where to find things
2. **IDE Support**: Autocomplete groups related items
3. **Code Review**: Violations are obvious
4. **Onboarding**: New developers learn patterns quickly
5. **Tooling**: Automated validation is reliable

---

## References

- **Documentation Analysis**: `/claude-hooks-backup/docs/OMNINODE-CONVENTIONS-DOCUMENTATION.md`
- **Code Analysis**: `/claude-hooks-backup/docs/OMNINODE-CONVENTIONS-CODEANALYSIS.md`
- **Validator Implementation**: `/claude-hooks-backup/lib/validators/naming_validator.py`

---

**Questions or Exceptions?**

If you believe you have a valid exception to these conventions, document the reasoning in your code and discuss with the team. Conventions should serve the code, not constrain it unnecessarily.
