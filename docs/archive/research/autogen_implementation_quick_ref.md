# Autogen Implementation Quick Reference

**For**: Developers implementing the adapted generation system
**Source**: omnibase_3 autogen analysis
**Target**: omniclaude autonomous node generation

---

## Key Files to Extract

### Priority 1: Must Have (Core algorithms)

```
SOURCE                                          TARGET                                      LOC   Adaptation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/omnibase_3/src/omnibase/utils/generation/
├── utility_ast_builder.py                     → ast_builder.py                            479   Medium
├── utility_type_mapper.py                     → type_mapper.py                            330   Low
├── utility_enum_generator.py                  → enum_generator.py                         440   Low
└── tool_contract_driven_generator/../node.py  → node_generator.py                         550   High
```

### Priority 2: Enhanced Functionality

```
SOURCE                                          TARGET                                      LOC   Adaptation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/omnibase_3/src/omnibase/utils/generation/
├── utility_contract_analyzer.py               → contract_analyzer.py                      658   High
├── utility_reference_resolver.py              → reference_resolver.py                     303   Medium
└── tool_ast_generator/../node.py              → structure_generator.py                    280   Medium
```

---

## Critical Code Patterns

### Pattern 1: AST Model Generation

**Source**: `utility_ast_builder.py:generate_model_class()`

```python
# ORIGINAL (omnibase_3)
def generate_model_class(self, class_name: str, schema: ModelSchema) -> ast.ClassDef:
    bases = [ast.Name(id="BaseModel", ctx=ast.Load())]
    body = [ast.Expr(value=ast.Constant(value=docstring))]

    for field_name, field_schema in schema.properties.items():
        field_def = self.create_field_definition(field_name, field_schema, is_required)
        body.append(field_def)

    return ast.ClassDef(name=class_name, bases=bases, body=body, ...)

# ADAPTED (omniclaude)
def generate_model_class(self, class_name: str, schema: SchemaDefinition) -> ast.ClassDef:
    # CHANGE 1: Use omnibase_core.models.SchemaDefinition instead of ModelSchema
    # CHANGE 2: Update base class naming to align with ONEX patterns
    bases = [ast.Name(id="ModelContractBase", ctx=ast.Load())]  # Updated base

    # KEEP: Same AST generation logic
    body = [ast.Expr(value=ast.Constant(value=docstring))]
    for field_name, field_schema in schema.properties.items():
        field_def = self.create_field_definition(field_name, field_schema)
        body.append(field_def)

    return ast.ClassDef(name=class_name, bases=bases, body=body, ...)
```

**Adaptation Points**:
- ✏️ Update schema type: `ModelSchema` → `SchemaDefinition`
- ✏️ Update base class: `BaseModel` → appropriate ONEX base
- ✅ Keep AST generation logic unchanged

### Pattern 2: Type Annotation Generation

**Source**: `utility_type_mapper.py:get_type_string_from_schema()`

```python
# ORIGINAL (omnibase_3)
def get_type_string_from_schema(self, schema: ModelSchema) -> str:
    if schema.schema_type == "string":
        if schema.format == "date-time":
            return "datetime"
        elif schema.format == "uuid":
            return "UUID"
    # ... more mappings

# ADAPTED (omniclaude)
from omnibase_core.types import TypeMapping

def get_type_string_from_schema(self, schema: SchemaDefinition) -> str:
    # CHANGE: Use omnibase_core type mapping
    type_mapper = TypeMapping()

    if schema.schema_type == "string":
        if schema.format == "date-time":
            return type_mapper.get_datetime_type()  # Returns proper ONEX datetime type
        elif schema.format == "uuid":
            return type_mapper.get_uuid_type()      # Returns proper ONEX UUID type

    # KEEP: Same logic, different type resolution
```

**Adaptation Points**:
- ✏️ Use `omnibase_core.types.TypeMapping` for type resolution
- ✏️ Ensure datetime returns `datetime` (not string)
- ✏️ Ensure UUID returns `UUID` (not string)
- ✅ Keep format detection logic

### Pattern 3: Enum Detection

**Source**: `utility_enum_generator.py:discover_enums_from_contract()`

```python
# ORIGINAL & ADAPTED (Same logic)
def discover_enums_from_contract(self, contract_data: dict) -> List[EnumInfo]:
    enums = []
    definitions = contract_data.get("definitions", {})

    for name, schema in definitions.items():
        # KEY PATTERN: Detect enums by type=string + enum array
        if schema.get("type") == "string" and "enum" in schema:
            enum_values = schema["enum"]
            enums.append(EnumInfo(name=name, values=enum_values))

    return enums

# ✅ No changes needed - pure logic, no dependencies
```

**Adaptation Points**:
- ✅ **No changes needed** - Pure algorithmic logic
- ✅ Just update import paths for `EnumInfo` type

---

## Import Migration Map

### Critical Imports to Update

```python
# ORIGINAL (omnibase_3)                     # ADAPTED (omniclaude)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Base classes
from omnibase.core.node_base               → from omnibase_core.base.node_base
from omnibase.core.onex_container          → from omnibase_core.container

# Error handling
from omnibase.exceptions                   → from omnibase_core.exceptions
from omnibase.core.core_error_codes        → from omnibase_core.errors.codes

# Logging
from omnibase.core.core_structured_logging → from omnibase_core.logging

# Models
from omnibase.model.core.model_schema      → from omnibase_core.models.schema
from omnibase.model.core.model_semver      → from omnibase_core.models.semver

# Protocols
from omnibase.protocol.protocol_*          → from omnibase_core.protocols.*

# Utils (internal - create new)
from omnibase.utils.generation.*           → from omniclaude.core.generation.*
```

---

## Contract Format Alignment

### ONEX Node Contract (omnibase_3 format)

```yaml
# ORIGINAL
tool_specification:
  main_tool_class: "ToolExample"
  registry_class: "RegistryExample"
  business_logic_pattern: "pure_functional"

definitions:
  ModelExample:
    type: object
    properties:
      field_name:
        type: string
```

### ONEX Node Contract (omniclaude format - TO BE DEFINED)

```yaml
# ADAPTED (align with omnibase_core)
node_specification:
  node_class: "NodeExampleEffect"           # Updated naming
  node_type: "effect"                       # Explicit type
  contract_pattern: "effect_contract"       # Pattern reference

definitions:
  ModelExampleEffect:                       # Follow naming convention
    type: object
    properties:
      field_name:
        type: string
```

**Adaptation Required**:
- ✏️ Rename `tool_specification` → `node_specification`
- ✏️ Update class naming: `ToolExample` → `NodeExampleEffect`
- ✏️ Add explicit node type classification
- ✏️ Align model naming conventions

---

## Common Adaptation Patterns

### Pattern: Update Class Constructor

```python
# ORIGINAL
class ToolContractDrivenGenerator:
    def __init__(self, container: ONEXContainer):
        self.container = container
        self._node_version = self.container.get_node_version()

# ADAPTED
class NodeGenerator(NodeBase):  # Inherit from omnibase_core NodeBase
    def __init__(self, container):
        super().__init__(container)  # Call parent init
        self.container = container
        # Node version now from parent class
```

### Pattern: Update Error Handling

```python
# ORIGINAL
from omnibase.exceptions import OnexError
from omnibase.core.core_error_codes import CoreErrorCode

raise OnexError("Error message", CoreErrorCode.VALIDATION_ERROR)

# ADAPTED
from omnibase_core.exceptions import OnexError
from omnibase_core.errors.codes import ErrorCode

raise OnexError("Error message", ErrorCode.VALIDATION_ERROR)
```

### Pattern: Update Logging

```python
# ORIGINAL
from omnibase.core.core_structured_logging import emit_log_event_sync as emit_log
from omnibase.enums.enum_log_level import LogLevelEnum

emit_log(LogLevelEnum.INFO, "Message", {"context": "data"})

# ADAPTED
from omnibase_core.logging import log

log.info("Message", context="data")  # Simpler API
```

---

## Testing Strategy

### Unit Tests (Per Phase)

```python
# test_ast_builder.py
def test_generate_model_class():
    """Test AST generation for basic model."""
    builder = ASTBuilder()
    schema = SchemaDefinition(
        schema_type="object",
        properties={"name": {"type": "string"}}
    )

    ast_class = builder.generate_model_class("ModelExample", schema)

    assert ast_class.name == "ModelExample"
    assert len(ast_class.body) > 1  # Has fields beyond docstring
    # Validate AST structure
```

### Integration Tests (After Phase 2)

```python
# test_node_generator.py
def test_generate_from_contract():
    """Test complete generation from contract."""
    generator = NodeGenerator(container)
    contract_path = "test_contracts/example_effect.yaml"

    result = generator.generate_from_contract(contract_path)

    assert result.models_generated > 0
    assert result.enums_generated >= 0
    # Validate generated code structure
```

### End-to-End Tests (After Phase 3)

```python
# test_generation_pipeline.py
def test_full_pipeline():
    """Test complete pipeline execution."""
    pipeline = GenerationPipeline()

    pipeline.execute(
        contract_path="test_contracts/example.yaml",
        output_dir="/tmp/generated"
    )

    # Verify generated files exist
    assert Path("/tmp/generated/node_example_effect.py").exists()
    # Verify imports are valid
    # Verify code compiles
```

---

## Validation Checklist

After each phase:

### Phase 1: Core Utilities

- [ ] AST builder generates valid Python AST
- [ ] Type mapper handles all basic types (str, int, float, bool)
- [ ] Type mapper handles complex types (List, Dict, Optional)
- [ ] Type mapper detects datetime/UUID formats
- [ ] Enum generator detects enums from contracts
- [ ] Enum generator generates valid enum classes
- [ ] All imports updated to omnibase_core
- [ ] All tests passing (80%+ coverage)

### Phase 2: Generator Tool

- [ ] Loads and parses contracts
- [ ] Generates models from definitions
- [ ] Generates enums from string+enum fields
- [ ] Creates proper AST nodes
- [ ] Handles $ref references
- [ ] Proper error handling with OnexError
- [ ] Integrates Phase 1 utilities
- [ ] Tests passing (70%+ coverage)

### Phase 3: Pipeline

- [ ] Validates contracts before generation
- [ ] Orchestrates generator execution
- [ ] Writes files to correct locations
- [ ] Proper file naming conventions
- [ ] Imports are correct and resolvable
- [ ] Generated code compiles without errors
- [ ] CLI interface functional
- [ ] End-to-end test passing

---

## Quick Command Reference

```bash
# Phase 1: Test utilities
pytest tests/core/generation/test_ast_builder.py
pytest tests/core/generation/test_type_mapper.py
pytest tests/core/generation/test_enum_generator.py

# Phase 2: Test generator
pytest tests/generation/test_node_generator.py

# Phase 3: Test pipeline
pytest tests/generation/test_pipeline.py

# Full test suite
pytest tests/generation/ -v --cov=omniclaude.core.generation

# Generate example node (after Phase 3)
python -m omniclaude.generation.pipeline generate \
  --contract contracts/example_effect.yaml \
  --output src/nodes/example/

# Validate generated node
python src/nodes/example/node_example_effect.py --validate
```

---

## Common Pitfalls

### ❌ Pitfall 1: Direct Copy-Paste

**Wrong**:
```python
# Copying omnibase_3 code directly
from omnibase.core.node_base import NodeBase  # Won't work!
```

**Right**:
```python
# Update all imports first
from omnibase_core.base.node_base import NodeBase
```

### ❌ Pitfall 2: Ignoring Type Differences

**Wrong**:
```python
# Assuming ModelSchema works the same
schema = ModelSchema(...)  # Different class in omnibase_core!
```

**Right**:
```python
# Use omnibase_core equivalent
schema = SchemaDefinition(...)
```

### ❌ Pitfall 3: Skipping Contract Alignment

**Wrong**:
```yaml
# Using omnibase_3 contract format directly
tool_specification:  # Won't work with omnibase_core!
  main_tool_class: "ToolExample"
```

**Right**:
```yaml
# Align with new contract format
node_specification:
  node_class: "NodeExampleEffect"
  node_type: "effect"
```

---

## Success Metrics

**Phase 1 Complete When**:
- ✅ All 4 core utilities adapted and tested
- ✅ 80%+ test coverage
- ✅ No omnibase_3 imports remaining
- ✅ Successfully generates AST for simple model

**Phase 2 Complete When**:
- ✅ Generator produces valid models from contracts
- ✅ Handles enums, references, complex types
- ✅ Proper error handling and logging
- ✅ 70%+ test coverage
- ✅ Successfully generates node from test contract

**Phase 3 Complete When**:
- ✅ Full pipeline generates deployable node
- ✅ Generated code compiles and runs
- ✅ CLI interface functional
- ✅ Documentation complete
- ✅ At least one real node generated successfully

---

**Quick Ref Complete** - Ready for implementation.
