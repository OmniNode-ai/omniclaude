# Omninode Naming Conventions - SPI Analysis & Core Comparison

**Generated**: 2025-09-30
**Codebase**: omnibase_spi (with comparison to omnibase_core)
**Base Path**: External omnibase_spi project - `${OMNIBASE_SPI}/src/omnibase_spi`
**Files Analyzed**: 95 Python files (SPI) vs 508 files (Core)

---

## Executive Summary

This report documents the **actual naming conventions** used in the omnibase_spi codebase and provides comprehensive comparison with omnibase_core conventions. The analysis reveals fundamentally different architectural approaches:

- **omnibase_spi**: Pure interface layer using Protocols (420 protocols, 65 Literal types)
- **omnibase_core**: Implementation layer using Models, Enums, and TypedDicts

### Key Statistics

| Category | SPI | Core | Pattern Match |
|----------|-----|------|---------------|
| **Total Files** | 95 | 508 | N/A |
| **Protocol Files** | 83 (87%) | Mixed | Protocol-first vs Model-first |
| **Protocol Classes** | 420 (100%) | Mixed | 100% consistent |
| **Literal Types** | 65 (100%) | 0 | SPI replaces Enums |
| **Model Classes** | 0 | 371 (100%) | Architectural separation |
| **Enum Classes** | 0 | 137 (100%) | Architectural separation |
| **TypedDict Classes** | 0 | 15 (100%) | Architectural separation |
| **Async Methods** | 990 | N/A | Heavy async in SPI |
| **Sync Methods** | 449 | N/A | Property methods |
| **@property Decorators** | 222 | N/A | Protocol attributes |

**Overall Adherence**:
- **SPI**: 100% Protocol* naming consistency, 87% protocol_*.py file naming
- **Core**: 98% overall consistency with Model*/Enum*/TypedDict* naming

---

## 1. File Naming Patterns

### 1.1 SPI Protocol Files

**Pattern**: `protocol_<descriptive_name>.py`

**Statistics**:
- Total SPI files: 95
- Protocol files: 83 (87%)
- Init files: 12 (13%)
- Pattern adherence: **87%**

**Examples**:
```
✅ protocol_onex_node.py
✅ protocol_memory_base.py
✅ protocol_core_types.py
✅ protocol_event_bus.py
✅ protocol_cache_service.py
✅ protocol_workflow_orchestration_types.py
✅ protocol_mcp_discovery.py
✅ protocol_container_service.py
```

**Directory Organization**:
```
src/omnibase_spi/protocols/
├── core/                  # Core system protocols (43 files)
│   ├── protocol_onex_node.py
│   ├── protocol_cache_service.py
│   ├── protocol_logger.py
│   └── ...
├── types/                 # Type definitions (7 files)
│   ├── protocol_core_types.py
│   ├── protocol_memory_types.py
│   └── ...
├── memory/               # Memory protocols (9 files)
├── event_bus/            # Event bus protocols (8 files)
├── mcp/                  # MCP protocols (7 files)
├── container/            # Container protocols (3 files)
├── validation/           # Validation protocols (5 files)
├── workflow_orchestration/ # Workflow protocols (4 files)
└── file_handling/        # File handling protocols (2 files)
```

**Key Observations**:
- **Strict consistency**: All non-init files follow `protocol_*.py` pattern
- **Domain-driven organization**: Protocols grouped by functional domain
- **Type separation**: Dedicated `types/` subdirectory for shared type protocols
- **No implementation files**: Pure interface definitions only

---

### 1.2 Core Implementation Files (Comparison)

**Patterns**: `model_*.py` (93%), `enum_*.py` (99%), `typed_dict_*.py` (100%)

**Statistics**:
- Total Core files: 508
- Model files: 336 (93%)
- Enum files: 125 (99%)
- TypedDict files: 15 (100%)

**Examples**:
```
✅ model_field_accessor.py          (SPI: N/A - implementation)
✅ model_result_factory.py           (SPI: N/A - implementation)
✅ enum_uri_type.py                  (SPI: Literal types instead)
✅ enum_validation_severity.py       (SPI: LiteralValidationSeverity)
✅ typed_dict_result_factory_kwargs.py (SPI: Protocol parameters)
```

**Architectural Difference**:
| Aspect | SPI | Core |
|--------|-----|------|
| **Purpose** | Define interfaces | Provide implementations |
| **Primary Type** | Protocol | Model (Pydantic BaseModel) |
| **Enum Approach** | Literal types | Enum classes |
| **Type Safety** | Structural typing | Nominal typing |
| **File Count** | 95 (lightweight) | 508 (comprehensive) |

---

## 2. Class Naming Patterns

### 2.1 SPI Protocol Classes

**Pattern**: `Protocol<DescriptiveName>` (PascalCase with "Protocol" prefix)

**Statistics**:
- Total protocol classes: 420
- Following pattern: 420 (100%)
- Pattern adherence: **100%**

**Examples**:
```python
✅ class ProtocolOnexNode(Protocol):
✅ class ProtocolCacheService(Protocol, Generic[T]):
✅ class ProtocolMemoryBase(Protocol):
✅ class ProtocolEventBus(Protocol):
✅ class ProtocolContextValue(Protocol):
✅ class ProtocolNodeMetadata(Protocol):
✅ class ProtocolHealthMonitor(Protocol):
✅ class ProtocolConfigurationManager(Protocol):
✅ class ProtocolCircuitBreaker(Protocol):
✅ class ProtocolRetryable(Protocol):
```

**Key Observations**:
- **100% consistency** with `Protocol` prefix
- All use `@runtime_checkable` decorator
- All inherit from `Protocol`
- Many use `Generic[T]` for type parameters
- Clear marker interfaces with sentinel attributes

**Naming Sub-patterns**:
```python
ProtocolOnex*          # ONEX system protocols
Protocol*Service       # Service interface protocols
Protocol*Provider      # Provider/factory protocols
Protocol*Manager       # Management protocols
Protocol*Base          # Base/fundamental protocols
Protocol*Metadata      # Metadata structure protocols
Protocol*Config        # Configuration protocols
Protocol*Request       # Request/response protocols
Protocol*Result        # Result/outcome protocols
```

**Protocol Inheritance Patterns**:
```python
# Simple protocols
class ProtocolContextValue(Protocol): ...

# Composite protocols
class ProtocolContextStringValue(ProtocolContextValue, Protocol): ...

# Generic protocols
class ProtocolCacheService(Protocol, Generic[T]): ...

# Memory protocol hierarchy
class ProtocolMemoryRequest(Protocol): ...
class ProtocolBatchMemoryStoreRequest(ProtocolMemoryRequest, Protocol): ...
```

---

### 2.2 Core Model Classes (Comparison)

**Pattern**: `Model<DescriptiveName>` (PascalCase with "Model" prefix)

**Statistics**:
- Total model classes: 371
- Following pattern: 371 (100%)
- Pattern adherence: **100%**

**Examples**:
```python
✅ class ModelFieldAccessor(BaseModel):           # SPI: ProtocolField*
✅ class ModelResult(BaseModel, Generic[T, E]):   # SPI: ProtocolResult*
✅ class ModelOnexUri(BaseModel):                 # SPI: ProtocolOnex*
✅ class ModelNodeInfo(BaseModel):                # SPI: ProtocolNodeMetadata
```

**Key Difference**:
```python
# Core: Concrete implementation with validation
class ModelNodeInfo(BaseModel):
    node_id: str
    node_type: str
    metadata: dict[str, Any]

    @field_validator('node_id')
    def validate_node_id(cls, v):
        # Implementation logic
        return v

# SPI: Interface definition only
@runtime_checkable
class ProtocolNodeMetadata(Protocol):
    node_id: str
    node_type: str
    metadata: dict[str, "ContextValue"]

    async def validate_node_metadata(self) -> bool: ...
    def is_complete(self) -> bool: ...
```

---

### 2.3 SPI Literal Types (Enum Replacement)

**Pattern**: `Literal<Category>` (PascalCase with "Literal" prefix)

**Statistics**:
- Total Literal types: 65
- Following pattern: 65 (100%)
- Pattern adherence: **100%**

**Examples**:
```python
✅ LiteralLogLevel = Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "FATAL"]
✅ LiteralNodeType = Literal["COMPUTE", "EFFECT", "REDUCER", "ORCHESTRATOR"]
✅ LiteralHealthStatus = Literal["healthy", "degraded", "unhealthy", "critical", "unknown"]
✅ LiteralMemoryAccessLevel = Literal["public", "private", "internal", "restricted", "confidential"]
✅ LiteralValidationLevel = Literal["BASIC", "STANDARD", "COMPREHENSIVE", "PARANOID"]
✅ LiteralOperationStatus = Literal["success", "failed", "in_progress", "cancelled", "pending"]
✅ LiteralConnectionState = Literal["disconnected", "connecting", "connected", "reconnecting", "failed"]
✅ LiteralCircuitBreakerState = Literal["closed", "open", "half_open"]
```

**Key Observations**:
- **100% consistency** with `Literal` prefix
- Type-safe string literals instead of Enum classes
- Values use lowercase/snake_case (e.g., "degraded", "half_open")
- Upper case for severity levels (e.g., "CRITICAL", "COMPREHENSIVE")
- More lightweight than Enum classes
- Better for protocol definitions (serialization-friendly)

**Naming Sub-patterns**:
```python
Literal*Status         # Status types (health, operation, connection)
Literal*Level          # Level/severity types
Literal*Type           # Type classification
Literal*Mode           # Mode/strategy types
Literal*Strategy       # Strategy selection types
Literal*State          # State machine states
```

---

### 2.4 Core Enum Classes (Comparison)

**Pattern**: `Enum<DescriptiveName>` (PascalCase with "Enum" prefix)

**Statistics**:
- Total enum classes: 137
- Following pattern: 137 (100%)
- Pattern adherence: **100%**

**Examples**:
```python
✅ class EnumValidationSeverity(str, Enum):       # SPI: LiteralValidationSeverity
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

✅ class EnumNodeStatus(str, Enum):               # SPI: LiteralNodeStatus
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    PENDING = "pending"
```

**Key Difference**:
```python
# Core: Full Enum class with methods
class EnumValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    def is_critical(self) -> bool:
        return self == self.ERROR

# SPI: Simple Literal type
LiteralValidationSeverity = Literal["error", "warning", "info"]
```

**Comparison Table**:
| Aspect | SPI Literal | Core Enum |
|--------|-------------|-----------|
| **Syntax** | `Literal["a", "b"]` | `class Enum*: A = "a"` |
| **Methods** | No | Yes |
| **Validation** | Type checker | Runtime |
| **Serialization** | Direct string | `.value` needed |
| **Protocol Use** | Ideal | Compatible |
| **Weight** | Lightweight | Full class |

---

### 2.5 Special Protocol Patterns in SPI

#### Marker Protocols

Protocols with sentinel attributes for runtime type checking:

```python
@runtime_checkable
class ProtocolSupportedMetadataType(Protocol):
    """Marker protocol for metadata compatibility."""
    __omnibase_metadata_type_marker__: Literal[True]

    def __str__(self) -> str: ...
    async def validate_for_metadata(self) -> bool: ...

@runtime_checkable
class ProtocolNodeInfoLike(Protocol):
    """Marker protocol for node information compatibility."""
    __omnibase_node_info_marker__: Literal[True]

@runtime_checkable
class ProtocolIdentifiable(Protocol):
    """Marker protocol for objects with ID."""
    __omnibase_identifiable_marker__: Literal[True]

    @property
    def id(self) -> str: ...
```

**Key Observations**:
- Sentinel attributes use `__omnibase_*_marker__` pattern
- Type-safe runtime checking
- Clear interface contracts
- Compatible with structural typing

---

## 3. Method Naming Patterns

### 3.1 SPI Protocol Methods

**Patterns**: snake_case, heavy use of `async def`, verb-first naming

**Statistics**:
- Async methods: 990 (69%)
- Sync methods: 449 (31%)
- Property decorators: 222
- Total method definitions: 1,439

**Async Method Examples**:
```python
async def validate_node_metadata(self) -> bool: ...
async def get_value(self, key: str) -> ContextValue: ...
async def update_value(self, key: str, value: ContextValue) -> None: ...
async def get_node_config(self) -> "ProtocolNodeConfiguration": ...
async def get_input_model(self) -> type[Any]: ...
async def get_output_model(self) -> type[Any]: ...
async def execute(self) -> object: ...
async def is_connectable(self) -> bool: ...
async def validate_for_context(self) -> bool: ...
```

**Sync Method Examples** (mostly property methods):
```python
def has_key(self, key: str) -> bool: ...
def is_complete(self) -> bool: ...
def is_valid(self) -> bool: ...
def is_healthy(self) -> bool: ...
def serialize(self) -> dict[str, object]: ...
def to_dict(self) -> dict[str, "ContextValue"]: ...
def model_dump(self) -> dict[str, ...]: ...
```

**Property Examples**:
```python
@property
def keys(self) -> list[str]: ...

@property
def id(self) -> str: ...

@property
def name(self) -> str: ...

@property
def embedding(self) -> list[float] | None: ...

@property
def metadata_keys(self) -> list[str]: ...
```

**Method Naming Conventions**:
```python
# Validation methods
async def validate_*() -> bool: ...          # 150+ occurrences
async def is_*() -> bool: ...                # 100+ occurrences

# Data access methods
async def get_*() -> ...: ...                # 200+ occurrences
def has_*() -> bool: ...                     # 50+ occurrences

# State modification methods
async def update_*() -> None: ...
async def set_*() -> None: ...
def add_*() -> None: ...

# Serialization methods
def serialize*() -> dict: ...
def to_dict() -> dict: ...
def model_dump() -> dict: ...

# Lifecycle methods
async def execute() -> ...: ...
async def run() -> ...: ...
def configure() -> None: ...
```

**Key Observations**:
- **69% async methods**: Heavy async/await usage in SPI
- **Validation-heavy**: ~150 `validate_*` methods
- **Property-based attributes**: 222 properties for protocol attributes
- **Clear verb prefixes**: get_, set_, update_, validate_, is_, has_
- **Boolean methods**: Use `is_*` and `has_*` patterns consistently

---

### 3.2 Core Method Patterns (Comparison)

Core methods focus on implementation logic while SPI focuses on interface contracts:

```python
# Core: Implementation with logic
class ModelNodeInfo(BaseModel):
    def validate_node_id(self) -> bool:
        # Actual validation implementation
        return len(self.node_id) > 0

# SPI: Interface definition only
@runtime_checkable
class ProtocolNodeMetadata(Protocol):
    async def validate_node_metadata(self) -> bool: ...  # No implementation
```

---

## 4. Type Annotation Patterns

### 4.1 SPI Type Annotations

**Forward References** (Heavy use in SPI):
```python
async def get_value(self, key: str) -> "ContextValue": ...
metadata: dict[str, "ContextValue"]
context: "ProtocolErrorContext"
```

**Generic Protocols**:
```python
class ProtocolCacheService(Protocol, Generic[T]):
    async def get(self, key: str) -> T | None: ...
    async def set(self, key: str, value: T) -> None: ...
```

**Union Types**:
```python
value: int | float
timestamp: "ProtocolDateTime | None"
error: "ProtocolErrorInfo | None"
```

**Complex Return Types**:
```python
def model_dump(self) -> dict[str, str | int | float | bool | list[...] | dict[...]]: ...
```

**Key Observations**:
- Heavy use of forward references to avoid circular imports
- Type aliases for complex types (e.g., `ContextValue`)
- Union types with None for optional values
- Generic protocols for reusability

---

### 4.2 Core Type Annotations (Comparison)

**Concrete Types**:
```python
# Core uses concrete types
field: ModelFieldAccessor
result: ModelResult[str, Exception]

# SPI uses protocol types
field: "ProtocolField"
result: "ProtocolNodeResult"
```

---

## 5. Import and Organization Patterns

### 5.1 SPI Import Patterns

**TYPE_CHECKING Pattern** (Strict in SPI):
```python
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

LiteralHealthStatus = Literal[...]

@runtime_checkable
class ProtocolHealthMonitor(Protocol):
    last_check: "datetime"  # Forward reference
```

**__init__.py Exports**:
```python
# Explicit exports for protocols
from .protocol_memory_base import ProtocolMemoryBase
from .protocol_memory_operations import ProtocolMemoryOperations

__all__ = [
    "ProtocolMemoryBase",
    "ProtocolMemoryOperations",
]
```

**Key Observations**:
- Strict TYPE_CHECKING usage to minimize import overhead
- All protocols are runtime_checkable
- Forward references for circular dependency prevention
- Clean __all__ definitions for public API

---

### 5.2 Core Import Patterns (Comparison)

**Direct Imports**:
```python
# Core uses direct imports
from omnibase_core.models import ModelFieldAccessor, ModelResult
from omnibase_core.enums import EnumValidationSeverity

# SPI uses forward references
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnibase_spi.protocols import ProtocolField
```

---

## 6. Documentation Patterns

### 6.1 SPI Documentation

**Protocol Docstrings** (Comprehensive):
```python
@runtime_checkable
class ProtocolOnexNode(Protocol):
    """
    Protocol for ONEX node implementations.

    All ONEX nodes must implement these methods to be compatible with the
    dynamic node loading system and container orchestration.

    This protocol defines the standard interface that node_loader.py expects
    when loading and validating nodes.

    Key Features:
        - Standard execution interface
        - Configuration metadata access
        - Input/output type definitions
        - Runtime compatibility validation

    Breaking Changes (v2.0):
        - get_input_type() → get_input_model() for clarity
        - get_output_type() → get_output_model() for clarity

    Migration Guide:
        For existing implementations, rename your methods:
        ```python
        # Old (v1.x)
        def get_input_type(self) -> type[Any]: ...

        # New (v2.0+)
        def get_input_model(self) -> type[Any]: ...
        ```
    """
```

**Method Documentation**:
```python
async def validate_node_metadata(self) -> bool:
    """Validate node metadata for completeness and correctness."""
    ...

def is_complete(self) -> bool:
    """Check if all required metadata fields are present."""
    ...
```

**Key Observations**:
- Very comprehensive protocol docstrings
- Usage examples included
- Breaking change documentation
- Migration guides provided
- Clear key features lists

---

## 7. Special SPI-Specific Conventions

### 7.1 Protocol Suffix Variations

**Context-Based Suffixes**:
```python
# Value protocols
ProtocolContextValue
ProtocolContextStringValue
ProtocolContextNumericValue

# Config protocols
ProtocolConfigValue
ProtocolConfigurable

# Result protocols
ProtocolNodeResult
ProtocolStorageResult
ProtocolBatchOperationResult

# Request/Response protocols
ProtocolMemoryRequest
ProtocolMemoryResponse
ProtocolBatchMemoryStoreRequest
```

---

### 7.2 Protocol Composition Patterns

**Inheritance Hierarchies**:
```python
# Base protocol
class ProtocolMemoryRequest(Protocol): ...

# Specialized protocols
class ProtocolBatchMemoryStoreRequest(ProtocolMemoryRequest, Protocol): ...
class ProtocolEmbeddingRequest(ProtocolMemoryRequest, Protocol): ...
class ProtocolConsolidationRequest(ProtocolMemoryRequest, Protocol): ...
```

**Mixin Patterns**:
```python
# Key-value store base
class ProtocolKeyValueStore(Protocol):
    @property
    def keys(self) -> list[str]: ...
    async def get_value(self, key: str) -> str | None: ...
    def has_key(self, key: str) -> bool: ...

# Specialized stores
class ProtocolMemoryMetadata(ProtocolKeyValueStore, Protocol): ...
class ProtocolWorkflowConfiguration(ProtocolKeyValueStore, Protocol): ...
```

---

### 7.3 Type Safety Patterns

**Sentinel Marker Pattern**:
```python
# Marker protocol for runtime type checking
@runtime_checkable
class ProtocolSupportedMetadataType(Protocol):
    __omnibase_metadata_type_marker__: Literal[True]  # Sentinel

    def __str__(self) -> str: ...
    async def validate_for_metadata(self) -> bool: ...

# Usage
def store_metadata(key: str, value: "ProtocolSupportedMetadataType"):
    if not isinstance(value, ProtocolSupportedMetadataType):
        raise TypeError("Value not compatible with metadata system")
    metadata_store[key] = str(value)
```

**Type Alias Pattern**:
```python
# Convenient type aliases
ContextValue = ProtocolContextValue
ProtocolDateTime = datetime
```

---

## 8. Comparison Table: SPI vs Core

### 8.1 High-Level Comparison

| Aspect | omnibase_spi | omnibase_core |
|--------|--------------|---------------|
| **Purpose** | Interface definitions | Concrete implementations |
| **Files** | 95 | 508 |
| **Primary Type** | Protocol (420) | Model (371) |
| **Enum Strategy** | Literal types (65) | Enum classes (137) |
| **TypedDict** | 0 | 15 |
| **Async Usage** | Heavy (69% of methods) | Moderate |
| **File Naming** | protocol_*.py (87%) | model_*.py (93%), enum_*.py (99%) |
| **Class Naming** | Protocol* (100%) | Model*/Enum*/TypedDict* (100%) |
| **Documentation** | Very comprehensive | Comprehensive |
| **Type Checking** | Structural (Protocol) | Nominal (Pydantic) |

---

### 8.2 Naming Pattern Mapping

| Core Pattern | SPI Equivalent | Notes |
|--------------|----------------|-------|
| `model_*.py` | `protocol_*.py` | Files |
| `enum_*.py` | `protocol_*_types.py` | Types file with Literals |
| `typed_dict_*.py` | N/A | Uses Protocol parameters |
| `Model*` | `Protocol*` | Classes |
| `Enum*` | `Literal*` | Type definitions |
| `TypedDict*` | Protocol with typed attributes | Structural typing |
| `def method()` | `async def method()` | Heavy async in SPI |
| `@field_validator` | `async def validate_*()` | Protocol methods |

---

### 8.3 Design Philosophy Differences

| Aspect | SPI Philosophy | Core Philosophy |
|--------|----------------|-----------------|
| **Typing** | Structural (duck typing) | Nominal (class-based) |
| **Validation** | Interface contracts | Runtime validation |
| **Coupling** | Loose (interfaces) | Tighter (implementations) |
| **Dependencies** | Minimal | Full (Pydantic, etc.) |
| **Extensibility** | Plugin-friendly | Inheritance-based |
| **Performance** | Lightweight | Heavier (validation) |
| **Use Case** | Plugin interfaces, APIs | Data models, business logic |

---

## 9. Statistical Summary

### 9.1 SPI Statistics

```
Files:
  - Total: 95
  - protocol_*.py: 83 (87%)
  - __init__.py: 12 (13%)

Classes:
  - Protocol classes: 420 (100% with Protocol* prefix)
  - Literal types: 65 (100% with Literal* prefix)
  - Model/Enum/TypedDict: 0 (architectural separation)

Methods:
  - Async methods: 990 (69%)
  - Sync methods: 449 (31%)
  - Properties: 222
  - Total: 1,439 method signatures

Naming Adherence:
  - File naming: 87% (protocol_*.py)
  - Class naming: 100% (Protocol*, Literal*)
  - Method naming: 100% (snake_case)
  - Overall: 96% consistency
```

### 9.2 Core Statistics (Comparison)

```
Files:
  - Total: 508
  - model_*.py: 336 (93%)
  - enum_*.py: 125 (99%)
  - typed_dict_*.py: 15 (100%)

Classes:
  - Model classes: 371 (100% with Model* prefix)
  - Enum classes: 137 (100% with Enum* prefix)
  - TypedDict classes: 15 (100% with TypedDict* prefix)
  - Protocol classes: Mixed (some with prefix, some without)

Naming Adherence:
  - File naming: 93-100% by category
  - Class naming: 100% (Model*, Enum*, TypedDict*)
  - Method naming: 100% (snake_case)
  - Overall: 98% consistency
```

---

## 10. Recommendations for Unified Enforcement

### 10.1 File Naming Rules

**For SPI**:
```python
# ✅ CORRECT
protocol_onex_node.py          # Protocol definition file
protocol_memory_base.py        # Base protocol file
protocol_core_types.py         # Types with Literals

# ❌ INCORRECT
onex_node.py                   # Missing protocol_ prefix
memory.py                      # Too generic
types.py                       # Should be protocol_*_types.py
```

**For Core**:
```python
# ✅ CORRECT
model_node_info.py             # Model implementation
enum_node_status.py            # Enum definition
typed_dict_kwargs.py           # TypedDict definition

# ❌ INCORRECT
node_info.py                   # Missing model_ prefix
status.py                      # Missing enum_ prefix
kwargs.py                      # Missing typed_dict_ prefix
```

---

### 10.2 Class Naming Rules

**For SPI**:
```python
# ✅ CORRECT - Protocols
@runtime_checkable
class ProtocolOnexNode(Protocol): ...

@runtime_checkable
class ProtocolCacheService(Protocol, Generic[T]): ...

# ✅ CORRECT - Literals
LiteralNodeType = Literal["COMPUTE", "EFFECT", "REDUCER", "ORCHESTRATOR"]
LiteralHealthStatus = Literal["healthy", "degraded", "unhealthy"]

# ❌ INCORRECT
class OnexNode(Protocol): ...              # Missing Protocol prefix
NodeType = Literal["COMPUTE", ...]         # Missing Literal prefix
```

**For Core**:
```python
# ✅ CORRECT
class ModelNodeInfo(BaseModel): ...
class EnumNodeStatus(str, Enum): ...
class TypedDictKwargs(TypedDict): ...

# ❌ INCORRECT
class NodeInfo(BaseModel): ...             # Missing Model prefix
class NodeStatus(str, Enum): ...           # Missing Enum prefix
class Kwargs(TypedDict): ...               # Missing TypedDict prefix
```

---

### 10.3 Method Naming Rules

**For SPI Protocols**:
```python
# ✅ CORRECT
async def validate_node_metadata(self) -> bool: ...
async def get_value(self, key: str) -> ContextValue: ...
def is_complete(self) -> bool: ...
def has_key(self, key: str) -> bool: ...

@property
def keys(self) -> list[str]: ...

# ❌ INCORRECT
def validateNodeMetadata(self) -> bool: ...    # camelCase
def GetValue(self, key: str) -> ...: ...       # PascalCase
```

---

### 10.4 Cross-Project Consistency Rules

**Rule 1: Architectural Separation**
- **SPI**: Only Protocol classes, Literal types
- **Core**: Only Model, Enum, TypedDict classes
- **Never mix**: Models should never be in SPI, Protocols should be minimal in Core

**Rule 2: Naming Prefixes**
- **Protocol definitions**: Always use `Protocol*` prefix in SPI
- **Implementations**: Always use `Model*` prefix in Core
- **Type constraints**: Use `Literal*` in SPI, `Enum*` in Core

**Rule 3: File Organization**
- **SPI**: `protocol_<domain>_<type>.py` (e.g., `protocol_memory_base.py`)
- **Core**: `model_<name>.py`, `enum_<name>.py`, `typed_dict_<name>.py`

**Rule 4: Import Patterns**
- **SPI**: Use TYPE_CHECKING and forward references aggressively
- **Core**: Direct imports are acceptable for implementations

---

### 10.5 Pre-commit Hook Validation Rules

**For SPI Validation**:
```python
# File naming check
if file.startswith("src/omnibase_spi/protocols/"):
    assert file.endswith("__init__.py") or file.startswith("protocol_"), \
        f"SPI file must be __init__.py or start with protocol_: {file}"

# Class naming check
if "class " in line and "Protocol)" in line:
    assert "class Protocol" in line, \
        f"Protocol classes must start with Protocol: {line}"

# Literal type check
if "= Literal[" in line:
    assert line.strip().startswith("Literal"), \
        f"Literal types must start with Literal: {line}"

# No Models/Enums in SPI
assert "class Model" not in content, "Models not allowed in SPI"
assert "class Enum" not in content, "Enums not allowed in SPI (use Literal)"
```

**For Core Validation**:
```python
# File naming check
if file.startswith("src/omnibase_core/models/"):
    assert file.startswith("model_") or file == "__init__.py"

if file.startswith("src/omnibase_core/enums/"):
    assert file.startswith("enum_") or file == "__init__.py"

# Class naming check
if "class Model" in line:
    assert re.match(r"class Model[A-Z]", line), \
        f"Model classes must use PascalCase with Model prefix: {line}"

if "class Enum" in line:
    assert re.match(r"class Enum[A-Z]", line), \
        f"Enum classes must use PascalCase with Enum prefix: {line}"
```

---

## 11. Example: Unified Naming Across Projects

### 11.1 Node Metadata Example

**SPI (Interface)**:
```python
# File: src/omnibase_spi/protocols/core/protocol_node_metadata.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class ProtocolNodeMetadata(Protocol):
    """Protocol for ONEX node metadata objects."""

    node_id: str
    node_type: str
    metadata: dict[str, "ContextValue"]

    async def validate_node_metadata(self) -> bool: ...
    def is_complete(self) -> bool: ...
```

**Core (Implementation)**:
```python
# File: src/omnibase_core/models/model_node_metadata.py
from pydantic import BaseModel, field_validator

class ModelNodeMetadata(BaseModel):
    """Implementation of node metadata."""

    node_id: str
    node_type: str
    metadata: dict[str, Any]

    @field_validator('node_id')
    def validate_node_id(cls, v):
        if not v:
            raise ValueError("node_id cannot be empty")
        return v

    async def validate_node_metadata(self) -> bool:
        """Actual validation implementation."""
        return bool(self.node_id and self.node_type)

    def is_complete(self) -> bool:
        """Check completeness."""
        return bool(self.node_id and self.node_type and self.metadata)
```

---

### 11.2 Status Example

**SPI (Literal Type)**:
```python
# File: src/omnibase_spi/protocols/types/protocol_core_types.py
LiteralNodeStatus = Literal["active", "inactive", "error", "pending"]

@runtime_checkable
class ProtocolNodeWithStatus(Protocol):
    status: LiteralNodeStatus
```

**Core (Enum Implementation)**:
```python
# File: src/omnibase_core/enums/enum_node_status.py
from enum import Enum

class EnumNodeStatus(str, Enum):
    """Node status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    PENDING = "pending"

    def is_operational(self) -> bool:
        """Check if node is operational."""
        return self in (self.ACTIVE, self.PENDING)
```

---

## 12. Architectural Insights

### 12.1 Why SPI Uses Protocols

**Advantages**:
1. **Loose Coupling**: Implementations can be swapped without changing interfaces
2. **Plugin Architecture**: Third-party plugins can implement interfaces
3. **Structural Typing**: Compatible with duck typing
4. **Lightweight**: No runtime overhead from inheritance
5. **Clear Contracts**: Explicit interface definitions
6. **Multiple Implementations**: Easy to provide alternative implementations

**Trade-offs**:
1. **No Default Implementations**: Must implement everything
2. **Limited Type Checking**: Structural typing is less strict
3. **Documentation Burden**: Must document expected behavior clearly

---

### 12.2 Why Core Uses Models

**Advantages**:
1. **Validation**: Built-in Pydantic validation
2. **Serialization**: Automatic JSON/dict conversion
3. **Type Safety**: Nominal typing with runtime checks
4. **Rich Functionality**: Methods, properties, validators
5. **IDE Support**: Better autocomplete and type hints

**Trade-offs**:
1. **Heavier**: More runtime overhead
2. **Tighter Coupling**: Harder to swap implementations
3. **Dependencies**: Requires Pydantic and other libraries

---

### 12.3 SPI vs Core: Complementary Design

The two codebases are designed to work together:

```
┌─────────────────────────────────────────┐
│         Application Layer               │
│  (Uses Core implementations)            │
│                                         │
│  from omnibase_core.models import      │
│      ModelNodeInfo                      │
│  node = ModelNodeInfo(...)              │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│           SPI Layer                     │
│  (Defines interfaces)                   │
│                                         │
│  from omnibase_spi.protocols import    │
│      ProtocolNodeMetadata               │
│  def process(node: ProtocolNodeMetadata)│
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│        Plugin Layer                     │
│  (Alternative implementations)          │
│                                         │
│  class CustomNode:                      │
│      # Implements ProtocolNodeMetadata  │
│      pass                                │
└─────────────────────────────────────────┘
```

---

## 13. Conclusion

### Key Findings

1. **100% Protocol Consistency in SPI**: Every protocol class uses `Protocol*` prefix
2. **Literal vs Enum**: SPI uses Literal types (65), Core uses Enum classes (137)
3. **Architectural Purity**: SPI has 0 Models/Enums/TypedDicts, Core has 523
4. **File Naming**: 87% adherence in SPI (protocol_*.py), 93-100% in Core
5. **Method Patterns**: SPI has 69% async methods, heavy validation focus
6. **Documentation**: Both codebases have excellent documentation

### Recommendations

**For Enforcement**:
1. Add pre-commit hooks to validate naming patterns
2. Use AST parsing to check class prefixes
3. Validate file naming conventions
4. Check for architectural violations (e.g., Models in SPI)

**For Consistency**:
1. Maintain strict prefix patterns: Protocol* in SPI, Model*/Enum* in Core
2. Use Literal types in SPI, Enum classes in Core
3. Keep architectural separation: interfaces vs implementations
4. Follow established patterns for new code

**For Documentation**:
1. Continue comprehensive protocol docstrings
2. Include usage examples and migration guides
3. Document breaking changes clearly
4. Maintain consistency in documentation style

---

## Appendix: Complete Pattern Reference

### SPI Patterns

```python
# Files
protocol_<name>.py

# Classes
class Protocol<Name>(Protocol): ...
Literal<Category> = Literal[...]

# Methods
async def validate_*() -> bool: ...
async def get_*() -> ...: ...
def is_*() -> bool: ...
def has_*() -> bool: ...

@property
def <attribute>() -> ...: ...

# Marker Protocols
__omnibase_*_marker__: Literal[True]
```

### Core Patterns

```python
# Files
model_<name>.py
enum_<name>.py
typed_dict_<name>.py

# Classes
class Model<Name>(BaseModel): ...
class Enum<Name>(str, Enum): ...
class TypedDict<Name>(TypedDict): ...

# Methods
def <method_name>(self) -> ...: ...

@field_validator('<field>')
def validate_<field>(cls, v): ...

@property
def <property>(self) -> ...: ...
```

---

**Report Complete**
**Analysis Date**: 2025-09-30
**Total Patterns Documented**: 50+
**Statistical Confidence**: High (95+ files analyzed per codebase)