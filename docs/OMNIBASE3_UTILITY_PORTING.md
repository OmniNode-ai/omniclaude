# omnibase_3 Utility Porting Guide

**Generated**: 2025-10-21
**Purpose**: Guide for porting proven omnibase_3 generation utilities to omniclaude

---

## Overview

This guide provides detailed instructions for extracting and adapting omnibase_3's battle-tested code generation utilities for use in omniclaude. These utilities provide production-grade AST manipulation, contract analysis, and type mapping capabilities.

---

## Utilities to Port

### High Priority (Phase 2)

| Utility | Source LOC | Target LOC | Effort | Value |
|---------|-----------|------------|--------|-------|
| `utility_contract_analyzer.py` | 658 | ~500 | 12h | Critical |
| `utility_ast_builder.py` | 479 | ~400 | 10h | High |
| `utility_type_mapper.py` | 330 | ~250 | 6h | High |
| `utility_enum_generator.py` | 440 | ~350 | 8h | Medium |
| `utility_reference_resolver.py` | 303 | ~250 | 6h | High |

**Total**: ~2200 LOC → ~1750 LOC, 42 hours

### Medium Priority (Phase 3)

| Utility | Source LOC | Effort | Value |
|---------|-----------|--------|-------|
| `utility_schema_composer.py` | 301 | 5h | Medium |
| `utility_schema_loader.py` | 205 | 4h | High |

---

## Import Migration Strategy

### Critical Import Path Updates

All omnibase_3 imports must be updated to omnibase_core or omniclaude equivalents.

#### Base Classes

| omnibase_3 | omniclaude/omnibase_core |
|------------|--------------------------|
| `from omnibase.core.node_base import NodeBase` | `from omnibase_core.core.infrastructure_service_bases import NodeCoreBase` |
| `from omnibase.protocol.protocol_ast_builder import ProtocolASTBuilder` | Remove (not needed for POC) |

#### Container

| omnibase_3 | omniclaude/omnibase_core |
|------------|--------------------------|
| `from omnibase.core.onex_container import ONEXContainer` | `from omnibase_core.models.container.model_onex_container import ModelONEXContainer` |

#### Errors

| omnibase_3 | omniclaude/omnibase_core |
|------------|--------------------------|
| `from omnibase.exceptions import OnexError` | `from omnibase_core.errors.model_onex_error import ModelOnexError` |
| `from omnibase.core.core_error_codes import CoreErrorCode` | `from omnibase_core.errors.error_codes import EnumCoreErrorCode` |

#### Models

| omnibase_3 | omniclaude/omnibase_core |
|------------|--------------------------|
| `from omnibase.model.core.model_schema import ModelSchema` | `from omnibase_core.models.contracts.model_contract_base import ModelContractBase` |
| `from omnibase.model.core.model_semver import ModelSemVer` | `from omnibase_core.primitives.model_semver import ModelSemVer` |

#### Logging

| omnibase_3 | omniclaude/omnibase_core |
|------------|--------------------------|
| `from omnibase.core.core_structured_logging import emit_log_event_sync` | `import logging; logger = logging.getLogger(__name__)` |

---

## Automated Import Migration Script

### Script: `scripts/migrate_imports.py`

```python
#!/usr/bin/env python3
"""Automated import migration from omnibase_3 to omniclaude/omnibase_core."""

import re
from pathlib import Path
from typing import Dict

# Import migration mapping
IMPORT_MIGRATIONS: Dict[str, str] = {
    # Base classes
    "from omnibase.core.node_base import NodeBase": "from omnibase_core.core.infrastructure_service_bases import NodeCoreBase",
    "from omnibase.protocol.protocol_ast_builder import ProtocolASTBuilder": "# Removed: ProtocolASTBuilder not needed",

    # Container
    "from omnibase.core.onex_container import ONEXContainer": "from omnibase_core.models.container.model_onex_container import ModelONEXContainer",

    # Errors
    "from omnibase.exceptions import OnexError": "from omnibase_core.errors.model_onex_error import ModelOnexError",
    "from omnibase.core.core_error_codes import CoreErrorCode": "from omnibase_core.errors.error_codes import EnumCoreErrorCode",

    # Models
    "from omnibase.model.core.model_schema import ModelSchema": "from omnibase_core.models.contracts.model_contract_base import ModelContractBase",
    "from omnibase.model.core.model_semver import ModelSemVer": "from omnibase_core.primitives.model_semver import ModelSemVer",

    # Logging
    "from omnibase.core.core_structured_logging import emit_log_event_sync": "import logging",
}

# Class name migrations
CLASS_MIGRATIONS: Dict[str, str] = {
    "OnexError": "ModelOnexError",
    "CoreErrorCode": "EnumCoreErrorCode",
    "ONEXContainer": "ModelONEXContainer",
    "ModelSchema": "ModelContractBase",
}


def migrate_file(file_path: Path, dry_run: bool = False) -> None:
    """Migrate imports in a single file.

    Args:
        file_path: Path to file to migrate
        dry_run: If True, only show changes without writing
    """
    content = file_path.read_text()
    original_content = content

    # Migrate imports
    for old_import, new_import in IMPORT_MIGRATIONS.items():
        content = content.replace(old_import, new_import)

    # Migrate class names (in code, not imports)
    for old_class, new_class in CLASS_MIGRATIONS.items():
        # Only replace in code, not in import statements
        content = re.sub(
            rf"\b{old_class}\b(?!.*import)",
            new_class,
            content,
        )

    # Remove "Utility" prefix from class names
    content = re.sub(
        r"class\s+Utility([A-Z]\w+)",
        r"class \1",
        content,
    )

    # Update emit_log_event_sync to logger
    content = content.replace(
        "emit_log_event_sync(",
        "logger.info(",
    )

    if content != original_content:
        if dry_run:
            print(f"Would migrate: {file_path}")
            # Show diff
            import difflib
            diff = difflib.unified_diff(
                original_content.splitlines(),
                content.splitlines(),
                fromfile=str(file_path),
                tofile=f"{file_path} (migrated)",
                lineterm="",
            )
            print("\n".join(diff))
        else:
            file_path.write_text(content)
            print(f"Migrated: {file_path}")
    else:
        print(f"No changes: {file_path}")


def migrate_directory(directory: Path, dry_run: bool = False) -> None:
    """Migrate all Python files in directory.

    Args:
        directory: Directory containing files to migrate
        dry_run: If True, only show changes without writing
    """
    for file_path in directory.glob("*.py"):
        migrate_file(file_path, dry_run=dry_run)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate omnibase_3 imports")
    parser.add_argument("path", type=Path, help="File or directory to migrate")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")

    args = parser.parse_args()

    if args.path.is_file():
        migrate_file(args.path, dry_run=args.dry_run)
    elif args.path.is_dir():
        migrate_directory(args.path, dry_run=args.dry_run)
    else:
        print(f"Error: {args.path} is not a file or directory")
```

**Usage**:
```bash
# Dry run (show changes)
python scripts/migrate_imports.py agents/lib/generation/ --dry-run

# Apply migrations
python scripts/migrate_imports.py agents/lib/generation/
```

---

## Detailed Porting Instructions

### 1. Contract Analyzer

#### Source
**File**: `../omnibase_3/src/omnibase/utils/generation/utility_contract_analyzer.py`
**Lines**: 658

#### Target
**File**: `agents/lib/generation/contract_analyzer.py`
**Estimated Lines**: ~500

#### Porting Steps

1. **Copy source file**:
```bash
cp ../omnibase_3/src/omnibase/utils/generation/utility_contract_analyzer.py \
   agents/lib/generation/contract_analyzer.py
```

2. **Run import migration**:
```bash
python scripts/migrate_imports.py agents/lib/generation/contract_analyzer.py
```

3. **Manual adaptations**:

**Remove "Utility" prefix**:
```python
# BEFORE
class UtilityContractAnalyzer:
    def __init__(self, container: ONEXContainer):
        self.container = container

# AFTER
class ContractAnalyzer:
    def __init__(self):
        # Remove container dependency for POC
        self.logger = logging.getLogger(__name__)
```

**Simplify initialization**:
```python
# BEFORE (omnibase_3 - full DI)
def __init__(self, container: ONEXContainer):
    self.container = container
    self.logger = container.logger
    self.schema_loader = container.get_service("ProtocolSchemaLoader")

# AFTER (omniclaude - simplified)
def __init__(self):
    self.logger = logging.getLogger(__name__)
    # No container dependency for POC
```

**Update error handling**:
```python
# BEFORE
raise OnexError(
    error_code=CoreErrorCode.VALIDATION_ERROR,
    message="Contract validation failed",
)

# AFTER
raise ModelOnexError(
    error_code=EnumCoreErrorCode.VALIDATION_ERROR,
    message="Contract validation failed",
)
```

**Remove event bus logging**:
```python
# BEFORE
emit_log_event_sync(
    level="INFO",
    message="Contract loaded successfully",
    context={"contract_name": contract.name},
)

# AFTER
self.logger.info(
    f"Contract loaded successfully: {contract.name}",
    extra={"contract_name": contract.name},
)
```

4. **Update method signatures**:

```python
# BEFORE (uses ModelSchema)
def load_contract(self, contract_path: Path) -> ModelSchema:
    """Load contract YAML and parse to ModelSchema."""
    pass

# AFTER (uses ModelContractBase)
def load_contract(self, contract_path: Path) -> ModelContractBase:
    """Load contract YAML and parse to ModelContractBase."""
    pass
```

5. **Testing**:

```python
# tests/test_contract_analyzer.py
import pytest
from pathlib import Path
from agents.lib.generation.contract_analyzer import ContractAnalyzer


def test_load_valid_contract():
    """Test loading a valid contract."""
    analyzer = ContractAnalyzer()

    contract_path = Path("tests/fixtures/valid_contract.yaml")
    contract = analyzer.load_contract(contract_path)

    assert contract is not None
    assert contract.name == "test_service"
    assert contract.version == "1.0.0"


def test_load_invalid_contract():
    """Test loading invalid contract raises error."""
    analyzer = ContractAnalyzer()

    contract_path = Path("tests/fixtures/invalid_contract.yaml")

    with pytest.raises(ModelOnexError) as exc_info:
        analyzer.load_contract(contract_path)

    assert "validation failed" in str(exc_info.value).lower()
```

---

### 2. AST Builder

#### Source
**File**: `../omnibase_3/src/omnibase/utils/generation/utility_ast_builder.py`
**Lines**: 479

#### Target
**File**: `agents/lib/generation/ast_builder.py`
**Estimated Lines**: ~400

#### Porting Steps

1. **Copy and migrate imports**:
```bash
cp ../omnibase_3/src/omnibase/utils/generation/utility_ast_builder.py \
   agents/lib/generation/ast_builder.py
python scripts/migrate_imports.py agents/lib/generation/ast_builder.py
```

2. **Remove protocol dependencies**:

```python
# BEFORE (omnibase_3 - uses protocol)
class UtilityASTBuilder:
    def __init__(self, container: ONEXContainer):
        self.type_mapper = container.get_service("ProtocolTypeMapper")

# AFTER (omniclaude - direct import)
from .type_mapper import TypeMapper

class ASTBuilder:
    def __init__(self):
        self.type_mapper = TypeMapper()
        self.logger = logging.getLogger(__name__)
```

3. **Update type annotation generation**:

```python
# Core method remains same, just update type imports
def get_type_annotation(self, schema: Dict[str, Any]) -> ast.expr:
    """Generate type annotation AST node.

    Args:
        schema: Field schema definition

    Returns:
        AST expression for type annotation
    """
    # Keep existing logic, but update type mapping
    schema_type = schema.get("type", "string")
    python_type = self.type_mapper.get_python_type(schema_type)

    # Generate AST node
    return ast.Name(id=python_type, ctx=ast.Load())
```

4. **Testing**:

```python
# tests/test_ast_builder.py
import ast
from agents.lib.generation.ast_builder import ASTBuilder


def test_generate_pydantic_model():
    """Test generating Pydantic model AST."""
    builder = ASTBuilder()

    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
        "required": ["name"],
    }

    model_ast = builder.generate_model_class(
        class_name="ModelUser",
        schema=schema,
        base_class="BaseModel",
    )

    # Verify AST structure
    assert isinstance(model_ast, ast.ClassDef)
    assert model_ast.name == "ModelUser"
    assert len(model_ast.bases) == 1

    # Render to Python code
    code = ast.unparse(model_ast)
    assert "class ModelUser(BaseModel):" in code
    assert "name: str" in code
    assert "age: int | None = None" in code
```

---

### 3. Type Mapper

#### Source
**File**: `../omnibase_3/src/omnibase/utils/generation/utility_type_mapper.py`
**Lines**: 330

#### Target
**File**: `agents/lib/generation/type_mapper.py`
**Estimated Lines**: ~250

#### Porting Steps

1. **Copy and migrate**:
```bash
cp ../omnibase_3/src/omnibase/utils/generation/utility_type_mapper.py \
   agents/lib/generation/type_mapper.py
python scripts/migrate_imports.py agents/lib/generation/type_mapper.py
```

2. **Add omnibase_core-specific mappings**:

```python
class TypeMapper:
    """Map schema types to Python types."""

    # Standard type mappings
    TYPE_MAPPINGS = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "array": "List",
        "object": "Dict",
        "null": "None",
    }

    # omnibase_core-specific type mappings
    OMNIBASE_CORE_TYPES = {
        "ModelONEXContainer": "omnibase_core.models.container.model_onex_container.ModelONEXContainer",
        "ModelOnexError": "omnibase_core.errors.model_onex_error.ModelOnexError",
        "EnumCoreErrorCode": "omnibase_core.errors.error_codes.EnumCoreErrorCode",
        "ModelContractBase": "omnibase_core.models.contracts.model_contract_base.ModelContractBase",
        "ModelContractEffect": "omnibase_core.models.contracts.model_contract_effect.ModelContractEffect",
        "ModelContractCompute": "omnibase_core.models.contracts.model_contract_compute.ModelContractCompute",
        "ModelContractReducer": "omnibase_core.models.contracts.model_contract_reducer.ModelContractReducer",
        "ModelContractOrchestrator": "omnibase_core.models.contracts.model_contract_orchestrator.ModelContractOrchestrator",
    }

    # Format-based type mappings
    FORMAT_MAPPINGS = {
        "date-time": "datetime",
        "date": "date",
        "time": "time",
        "uuid": "UUID",
        "email": "str",  # Could use pydantic.EmailStr
        "uri": "str",
        "hostname": "str",
    }

    def get_python_type(self, schema_type: str, schema_format: str | None = None) -> str:
        """Get Python type from schema type.

        Args:
            schema_type: Schema type (string, integer, etc.)
            schema_format: Optional format specifier (date-time, uuid, etc.)

        Returns:
            Python type string
        """
        # Check format first
        if schema_format and schema_format in self.FORMAT_MAPPINGS:
            return self.FORMAT_MAPPINGS[schema_format]

        # Check omnibase_core types
        if schema_type in self.OMNIBASE_CORE_TYPES:
            return self.OMNIBASE_CORE_TYPES[schema_type]

        # Check standard mappings
        return self.TYPE_MAPPINGS.get(schema_type, "Any")
```

3. **Zero tolerance for `Any`**:

```python
def get_python_type(self, schema_type: str, schema_format: str | None = None) -> str:
    """Get Python type, never return 'Any'."""
    python_type = self._resolve_type(schema_type, schema_format)

    if python_type == "Any":
        raise ValueError(
            f"Cannot map schema type '{schema_type}' to Python type. "
            f"Zero tolerance for 'Any' types."
        )

    return python_type
```

---

### 4. Enum Generator

#### Source
**File**: `../omnibase_3/src/omnibase/utils/generation/utility_enum_generator.py`
**Lines**: 440

#### Target
**File**: `agents/lib/generation/enum_generator.py`
**Estimated Lines**: ~350

#### Porting Steps

1. **Copy and migrate**:
```bash
cp ../omnibase_3/src/omnibase/utils/generation/utility_enum_generator.py \
   agents/lib/generation/enum_generator.py
python scripts/migrate_imports.py agents/lib/generation/enum_generator.py
```

2. **Update naming convention**:

```python
class EnumGenerator:
    """Generate enum classes from schema definitions."""

    def generate_enum_name(self, base_name: str) -> str:
        """Generate enum name following ONEX naming convention.

        Args:
            base_name: Base name (e.g., "status", "operation_type")

        Returns:
            Enum name with "Enum" prefix (e.g., "EnumStatus", "EnumOperationType")
        """
        # Convert to PascalCase
        pascal_name = "".join(word.capitalize() for word in base_name.split("_"))

        # Add "Enum" prefix
        return f"Enum{pascal_name}"

    def generate_enum_class(
        self,
        enum_name: str,
        enum_values: List[str],
        enum_type: str = "str",
    ) -> ast.ClassDef:
        """Generate enum class AST.

        Args:
            enum_name: Enum class name (must start with "Enum")
            enum_values: List of enum values
            enum_type: Base enum type ("str" or "int")

        Returns:
            AST ClassDef for enum
        """
        if not enum_name.startswith("Enum"):
            raise ValueError(f"Enum name must start with 'Enum': {enum_name}")

        # Generate class AST
        bases = [
            ast.Name(id=enum_type, ctx=ast.Load()),
            ast.Name(id="Enum", ctx=ast.Load()),
        ]

        body = []

        # Add docstring
        docstring = ast.Expr(value=ast.Constant(value=f"{enum_name} enumeration."))
        body.append(docstring)

        # Add enum members
        for value in enum_values:
            # Convert to UPPER_SNAKE_CASE
            member_name = value.upper().replace(" ", "_").replace("-", "_")

            # Create assignment
            assignment = ast.Assign(
                targets=[ast.Name(id=member_name, ctx=ast.Store())],
                value=ast.Constant(value=value),
            )
            body.append(assignment)

        return ast.ClassDef(
            name=enum_name,
            bases=bases,
            body=body,
            decorator_list=[],
            keywords=[],
        )
```

3. **Testing**:

```python
# tests/test_enum_generator.py
import ast
from agents.lib.generation.enum_generator import EnumGenerator


def test_generate_enum_class():
    """Test enum class generation."""
    generator = EnumGenerator()

    enum_ast = generator.generate_enum_class(
        enum_name="EnumStatus",
        enum_values=["active", "inactive", "pending"],
        enum_type="str",
    )

    # Render to Python code
    code = ast.unparse(enum_ast)

    assert "class EnumStatus(str, Enum):" in code
    assert "ACTIVE = 'active'" in code
    assert "INACTIVE = 'inactive'" in code
    assert "PENDING = 'pending'" in code


def test_enum_name_validation():
    """Test enum name must start with 'Enum'."""
    generator = EnumGenerator()

    with pytest.raises(ValueError) as exc_info:
        generator.generate_enum_class(
            enum_name="Status",  # Missing "Enum" prefix
            enum_values=["active"],
        )

    assert "must start with 'Enum'" in str(exc_info.value)
```

---

### 5. Reference Resolver

#### Source
**File**: `../omnibase_3/src/omnibase/utils/generation/utility_reference_resolver.py`
**Lines**: 303

#### Target
**File**: `agents/lib/generation/reference_resolver.py`
**Estimated Lines**: ~250

#### Porting Steps

1. **Copy and migrate**:
```bash
cp ../omnibase_3/src/omnibase/utils/generation/utility_reference_resolver.py \
   agents/lib/generation/reference_resolver.py
python scripts/migrate_imports.py agents/lib/generation/reference_resolver.py
```

2. **Simplify reference resolution**:

```python
class ReferenceResolver:
    """Resolve $ref references in contracts."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.resolved_refs: Dict[str, Any] = {}  # Cache

    def resolve_references(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve all $ref references in contract.

        Args:
            contract: Contract dictionary with potential $ref fields

        Returns:
            Contract with all $ref references resolved

        Raises:
            ValueError: If circular reference detected
        """
        return self._resolve_recursive(contract, path=[])

    def _resolve_recursive(
        self,
        obj: Any,
        path: List[str],
    ) -> Any:
        """Recursively resolve references.

        Args:
            obj: Object to resolve (dict, list, or scalar)
            path: Current resolution path (for circular detection)

        Returns:
            Object with references resolved
        """
        if isinstance(obj, dict):
            # Check for $ref
            if "$ref" in obj:
                ref_path = obj["$ref"]

                # Check for circular reference
                if ref_path in path:
                    raise ValueError(
                        f"Circular reference detected: {' -> '.join(path + [ref_path])}"
                    )

                # Resolve reference
                resolved = self._load_reference(ref_path)

                # Recursively resolve the loaded reference
                return self._resolve_recursive(resolved, path + [ref_path])

            # Resolve all dict values
            return {
                key: self._resolve_recursive(value, path)
                for key, value in obj.items()
            }

        elif isinstance(obj, list):
            # Resolve all list items
            return [self._resolve_recursive(item, path) for item in obj]

        else:
            # Scalar value, return as-is
            return obj

    def _load_reference(self, ref_path: str) -> Any:
        """Load reference from path.

        Args:
            ref_path: Reference path (e.g., "contracts/model_user.yaml#/User")

        Returns:
            Loaded reference content
        """
        # Check cache
        if ref_path in self.resolved_refs:
            return self.resolved_refs[ref_path]

        # Parse ref_path
        if "#" in ref_path:
            file_path, json_pointer = ref_path.split("#", 1)
        else:
            file_path = ref_path
            json_pointer = ""

        # Load file
        import yaml
        from pathlib import Path

        full_path = Path(file_path)
        content = yaml.safe_load(full_path.read_text())

        # Navigate JSON pointer
        if json_pointer:
            for part in json_pointer.strip("/").split("/"):
                content = content[part]

        # Cache result
        self.resolved_refs[ref_path] = content

        return content
```

---

## Testing Strategy

### Unit Tests

Create comprehensive unit tests for each ported utility:

```bash
poetry run pytest tests/test_contract_analyzer.py -v --cov
poetry run pytest tests/test_ast_builder.py -v --cov
poetry run pytest tests/test_type_mapper.py -v --cov
poetry run pytest tests/test_enum_generator.py -v --cov
poetry run pytest tests/test_reference_resolver.py -v --cov
```

**Coverage Target**: >90% for all utilities

### Integration Tests

Test utilities working together:

```python
# tests/test_generation_integration.py
def test_full_generation_pipeline():
    """Test complete generation pipeline with all utilities."""
    # 1. Load contract
    analyzer = ContractAnalyzer()
    contract = analyzer.load_contract(Path("tests/fixtures/effect_contract.yaml"))

    # 2. Resolve references
    resolver = ReferenceResolver()
    resolved_contract = resolver.resolve_references(contract)

    # 3. Generate AST
    builder = ASTBuilder()
    model_ast = builder.generate_model_class(
        class_name="ModelEffectInput",
        schema=resolved_contract["definitions"]["InputState"],
    )

    # 4. Render to Python code
    code = ast.unparse(model_ast)

    # 5. Verify code compiles
    compile(code, "<string>", "exec")

    # 6. Verify code is syntactically correct
    ast.parse(code)
```

---

## Validation Checklist

After porting each utility:

- [ ] All imports migrated to omnibase_core/omniclaude
- [ ] "Utility" prefix removed from class names
- [ ] Container dependencies removed (or simplified)
- [ ] Event bus logging replaced with standard logging
- [ ] Error handling uses `ModelOnexError`
- [ ] Unit tests created with >90% coverage
- [ ] Integration tests pass
- [ ] Code passes mypy type checking
- [ ] Code passes ruff linting
- [ ] Documentation added
- [ ] Performance benchmarks meet targets

---

## Performance Targets

| Utility | Operation | Target Time | Test Method |
|---------|-----------|-------------|-------------|
| ContractAnalyzer | Load contract | <100ms | Load 10KB YAML |
| ASTBuilder | Generate model class | <50ms | 10 fields |
| TypeMapper | Map type | <1ms | Single type |
| EnumGenerator | Generate enum class | <20ms | 10 values |
| ReferenceResolver | Resolve reference | <50ms | 3 levels deep |

---

## Common Pitfalls & Solutions

### Pitfall 1: Missing Type Hints

**Problem**: omnibase_3 uses `Any` extensively
**Solution**: Add proper type hints during porting

```python
# BEFORE (omnibase_3)
def process_schema(self, schema):
    return self._do_work(schema)

# AFTER (omniclaude)
def process_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
    return self._do_work(schema)
```

### Pitfall 2: Container Dependency

**Problem**: omnibase_3 utilities expect `ONEXContainer`
**Solution**: Remove or simplify for POC

```python
# BEFORE (omnibase_3)
class UtilityTypeMapper:
    def __init__(self, container: ONEXContainer):
        self.logger = container.logger

# AFTER (omniclaude)
class TypeMapper:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
```

### Pitfall 3: Event Bus Logging

**Problem**: omnibase_3 uses structured event logging
**Solution**: Replace with standard Python logging

```python
# BEFORE (omnibase_3)
emit_log_event_sync(
    level="INFO",
    message="Processing complete",
    context={"count": 10},
)

# AFTER (omniclaude)
self.logger.info(
    "Processing complete",
    extra={"count": 10},
)
```

### Pitfall 4: Protocol Dependencies

**Problem**: omnibase_3 uses protocol-based DI
**Solution**: Use direct imports for POC

```python
# BEFORE (omnibase_3)
self.type_mapper = container.get_service("ProtocolTypeMapper")

# AFTER (omniclaude)
from .type_mapper import TypeMapper
self.type_mapper = TypeMapper()
```

---

## Appendix: Quick Reference

### Files to Create

```
agents/lib/generation/
├── contract_analyzer.py          # 658 LOC → ~500 LOC
├── ast_builder.py                # 479 LOC → ~400 LOC
├── type_mapper.py                # 330 LOC → ~250 LOC
├── enum_generator.py             # 440 LOC → ~350 LOC
└── reference_resolver.py         # 303 LOC → ~250 LOC

tests/
├── test_contract_analyzer.py
├── test_ast_builder.py
├── test_type_mapper.py
├── test_enum_generator.py
└── test_reference_resolver.py
```

### Total Effort

| Task | Effort |
|------|--------|
| Copy and run migration script | 2h |
| Manual adaptations | 20h |
| Testing | 12h |
| Integration | 6h |
| Documentation | 2h |
| **Total** | **42h** |

---

**End of omnibase_3 Utility Porting Guide**

**Key Takeaways**:
- Use automated import migration script
- Remove "Utility" prefix from class names
- Simplify container dependencies
- Replace event logging with standard logging
- Add comprehensive tests (>90% coverage)
- Verify performance targets met

**Next Steps**:
1. Run import migration script
2. Port ContractAnalyzer first (highest priority)
3. Test thoroughly before porting next utility
4. Integrate with GenerationPipeline after all utilities ported
