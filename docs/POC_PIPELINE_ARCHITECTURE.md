# POC Pipeline Architecture: Autonomous Node Generation

**Phase**: 1.3 Planning (Design Only)
**Generated**: 2025-10-21
**Status**: Design Complete - Ready for Implementation
**Scope**: Phase 1 POC (EFFECT nodes only)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [Pipeline Stages](#pipeline-stages)
4. [Data Flow](#data-flow)
5. [Event Contracts](#event-contracts)
6. [Validation Gates](#validation-gates)
7. [File Generation Patterns](#file-generation-patterns)
8. [Error Handling Strategy](#error-handling-strategy)
9. [Success Criteria](#success-criteria)
10. [Implementation Readiness](#implementation-readiness)

---

## Executive Summary

### Purpose

Design a **minimal viable pipeline** that autonomously generates fully working ONEX EFFECT nodes from natural language prompts. This POC validates the core concept before scaling to all node types and advanced features.

### Key Constraints

**IN SCOPE** (Phase 1 POC):
- ✅ Prompt → EFFECT node generation
- ✅ Basic validation (imports, syntax, ONEX naming)
- ✅ File writing to correct directory structure
- ✅ Success/failure reporting
- ✅ Synchronous execution (simple, testable)

**OUT OF SCOPE** (Defer to Phase 2+):
- ❌ Contract-driven generation (Phase 2)
- ❌ AST-based model generation (Phase 3)
- ❌ Event bus async execution (Phase 4)
- ❌ Multi-node type support (Phase 1 = EFFECT only)
- ❌ UI/CLI interface (manual execution OK)

### Design Principles

1. **KISS**: Keep it simple - no over-engineering
2. **Fail Fast**: Validate early, fail explicitly
3. **Reuse**: Leverage existing `omninode_template_engine.py`
4. **Testable**: Every stage independently testable
5. **Observable**: Clear logging at each step

---

## Architecture Overview

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     AUTONOMOUS NODE GENERATION POC               │
└─────────────────────────────────────────────────────────────────┘

Input: Natural Language Prompt
   ↓
┌──────────────────────────────────────────────────────────────────┐
│ STAGE 1: Prompt Parsing                                          │
│ - Extract node metadata (name, purpose, operations)              │
│ - Validate prompt completeness                                   │
│ - Create SimplePRDAnalysisResult                                 │
│ Duration: ~5s                                                    │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│ STAGE 2: Pre-Generation Validation                               │
│ - Check omnibase_core import paths (fix #1 from Option C)        │
│ - Validate template availability                                 │
│ - Check output directory writability                             │
│ Duration: ~2s                                                    │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│ STAGE 3: Code Generation                                         │
│ - Load EFFECT template (from cache if available)                 │
│ - Render template with context                                   │
│ - Generate models, enums, contracts, manifests                   │
│ Duration: ~10-15s                                                │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│ STAGE 4: Post-Generation Validation                              │
│ - Syntax check (AST parsing)                                     │
│ - Import resolution check                                        │
│ - ONEX naming convention check                                   │
│ - Pydantic model validation                                      │
│ Duration: ~5s                                                    │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│ STAGE 5: File Writing                                            │
│ - Create directory structure                                     │
│ - Write node files                                               │
│ - Write models, contracts, manifests                             │
│ - Generate __init__.py exports                                   │
│ Duration: ~3s                                                    │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│ STAGE 6: Compilation Testing (Optional)                          │
│ - Run `poetry run mypy` on generated node                        │
│ - Check for type errors                                          │
│ Duration: ~10s (optional, can be async)                          │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
Output: GenerationResult (success/failure + metadata)
```

**Total Duration**: ~35-40 seconds (well under 2-minute target)

### Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     GenerationPipeline (NEW)                     │
│  - Orchestrates all stages                                       │
│  - Handles errors at each stage                                  │
│  - Emits events (logs for POC, Kafka in Phase 4)                 │
└─────────────────────────────────────────────────────────────────┘
         │
         │  uses
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   PromptParser (NEW)                             │
│  - Extract metadata from natural language                        │
│  - Keyword-based heuristics (POC)                                │
│  - LLM-based parsing (Phase 2+)                                  │
└─────────────────────────────────────────────────────────────────┘
         │
         │  uses
         ▼
┌─────────────────────────────────────────────────────────────────┐
│              OmnibaseCoreValidator (NEW)                         │
│  - Validate import paths exist                                   │
│  - Check base classes available                                  │
│  - Prevent generation failures                                   │
└─────────────────────────────────────────────────────────────────┘
         │
         │  uses
         ▼
┌─────────────────────────────────────────────────────────────────┐
│           OmninodeTemplateEngine (EXISTING)                      │
│  - Load and cache templates                                      │
│  - Render with context                                           │
│  - Generate additional files                                     │
└─────────────────────────────────────────────────────────────────┘
         │
         │  uses
         ▼
┌─────────────────────────────────────────────────────────────────┐
│              PostGenerationValidator (NEW)                       │
│  - AST syntax check                                              │
│  - Import resolution                                             │
│  - ONEX naming compliance                                        │
│  - Type safety check                                             │
└─────────────────────────────────────────────────────────────────┘
         │
         │  uses
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 FileWriter (NEW)                                 │
│  - Create directory structure                                    │
│  - Write files atomically                                        │
│  - Track written paths                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Stages

### Stage 1: Prompt Parsing

**Purpose**: Extract structured data from natural language prompt

**Input**:
```python
prompt: str = "Create EFFECT node for PostgreSQL database write operations"
```

**Processing**:
1. **Node Type Detection**:
   - Keyword matching: "EFFECT", "database", "write"
   - Default to EFFECT for POC

2. **Service Name Extraction**:
   - Regex: `r"for\s+(\w+)"` → "PostgreSQL"
   - Snake case conversion → "postgres_writer"

3. **Domain Classification**:
   - Keywords → domain mapping
   - Example: "database" → "infrastructure"

4. **Operation Detection**:
   - EFFECT defaults: ["create", "read", "update", "delete"]
   - Can be overridden by prompt keywords

**Output**:
```python
@dataclass
class ParsedPromptData:
    node_type: str = "EFFECT"
    service_name: str = "postgres_writer"
    domain: str = "infrastructure"
    description: str = "PostgreSQL database write operations"
    operations: List[str] = ["create", "update", "delete"]
    features: List[str] = ["Feature 1", "Feature 2", "Feature 3"]
    external_systems: List[str] = ["PostgreSQL"]
    confidence_score: float = 0.85
```

**Validation**:
- `service_name` is not empty
- `node_type` is valid ("EFFECT" for POC)
- `description` has minimum length (10 chars)

**Error Handling**:
- Raise `ValidationError` if required fields missing
- Log warnings for low confidence scores (<0.7)

---

### Stage 2: Pre-Generation Validation

**Purpose**: Validate environment before code generation

**Checks**:

1. **Import Path Validation**:
```python
CRITICAL_IMPORTS = [
    "omnibase_core.nodes.node_effect.NodeEffect",
    "omnibase_core.errors.model_onex_error.ModelOnexError",
    "omnibase_core.errors.error_codes.EnumCoreErrorCode",
    "omnibase_core.models.container.model_onex_container.ModelONEXContainer",
]

for import_path in CRITICAL_IMPORTS:
    module_path, class_name = import_path.rsplit(".", 1)
    module = import_module(module_path)
    assert hasattr(module, class_name), f"{class_name} not found"
```

2. **Template Availability**:
```python
template_path = templates_dir / "effect_node_template.py"
assert template_path.exists(), f"Template not found: {template_path}"
```

3. **Output Directory**:
```python
output_dir = Path(output_directory)
assert output_dir.is_dir() or output_dir.parent.is_dir(), "Invalid output path"
```

**Output**:
```python
@dataclass
class ValidationResult:
    passed: bool
    errors: List[str]
    warnings: List[str]
    timestamp: datetime
```

**Error Handling**:
- Fail fast if critical imports missing
- Suggest fixes (e.g., "Run `poetry install omnibase_core`")

---

### Stage 3: Code Generation

**Purpose**: Generate node implementation from template

**Process**:

1. **Prepare Context**:
```python
context = {
    "DOMAIN": "infrastructure",
    "MICROSERVICE_NAME": "postgres_writer",
    "MICROSERVICE_NAME_PASCAL": "PostgresWriter",
    "NODE_TYPE": "EFFECT",
    "BUSINESS_DESCRIPTION": "PostgreSQL database write operations",
    "REPOSITORY_NAME": "omniclaude",
    "OPERATIONS": ["create", "update", "delete"],
    "FEATURES": ["Feature 1", "Feature 2", "Feature 3"],
}
```

2. **Template Rendering**:
```python
template = templates["EFFECT"]
node_content = template.render(context)
```

3. **Additional File Generation**:
```python
generated_files = {
    "v1_0_0/node.py": node_content,
    "v1_0_0/models/model_postgres_writer_input.py": input_model,
    "v1_0_0/models/model_postgres_writer_output.py": output_model,
    "v1_0_0/models/model_postgres_writer_config.py": config_model,
    "v1_0_0/enums/enum_postgres_writer_operation_type.py": enum,
    "v1_0_0/contract.yaml": contract_yaml,
    "node.manifest.yaml": node_manifest,
    "v1_0_0/version.manifest.yaml": version_manifest,
    "v1_0_0/__init__.py": version_init,
    "v1_0_0/models/__init__.py": models_init,
    "v1_0_0/enums/__init__.py": enums_init,
}
```

**Output**:
```python
@dataclass
class GeneratedCode:
    main_node_file: str
    additional_files: Dict[str, str]
    context: Dict[str, Any]
    generation_time_ms: int
```

**Error Handling**:
- Catch template rendering errors (missing placeholders)
- Log rendering warnings

---

### Stage 4: Post-Generation Validation

**Purpose**: Validate generated code quality

**Checks**:

1. **Syntax Validation** (AST parsing):
```python
import ast

for file_path, code in generated_files.items():
    if file_path.endswith(".py"):
        try:
            ast.parse(code)
        except SyntaxError as e:
            raise ValidationError(f"Syntax error in {file_path}: {e}")
```

2. **Import Resolution** (static analysis):
```python
import_pattern = r"^from\s+([\w\.]+)\s+import\s+([\w,\s]+)"
for match in re.finditer(import_pattern, code, re.MULTILINE):
    module_path = match.group(1)
    # Try to import (without executing code)
    try:
        import_module(module_path)
    except ImportError:
        warnings.append(f"Import may fail: {module_path}")
```

3. **ONEX Naming Convention**:
```python
class_pattern = r"class\s+(Node\w+(Effect|Compute|Reducer|Orchestrator))"
matches = re.findall(class_pattern, code)
assert len(matches) > 0, "Node class not found or incorrect naming"

# Verify suffix (not prefix)
for class_name, suffix in matches:
    assert class_name.endswith(suffix), f"Incorrect suffix: {class_name}"
```

4. **Pydantic Model Validation**:
```python
model_pattern = r"class\s+(Model\w+)\(BaseModel\)"
matches = re.findall(model_pattern, code)
# Verify Field() usage, validators, etc.
```

**Output**:
```python
@dataclass
class ValidationReport:
    syntax_valid: bool
    imports_valid: bool
    naming_compliant: bool
    pydantic_valid: bool
    errors: List[str]
    warnings: List[str]
    suggestions: List[str]
```

**Error Handling**:
- Fail if syntax errors found
- Warn on potential import failures
- Continue with warnings for non-critical issues

---

### Stage 5: File Writing

**Purpose**: Write validated code to filesystem

**Process**:

1. **Directory Structure Creation**:
```python
output_path = Path(output_directory)
node_path = output_path / "node_infrastructure_postgres_writer_effect"
node_path.mkdir(parents=True, exist_ok=True)

# Create subdirectories
(node_path / "v1_0_0").mkdir(exist_ok=True)
(node_path / "v1_0_0" / "models").mkdir(exist_ok=True)
(node_path / "v1_0_0" / "enums").mkdir(exist_ok=True)
```

2. **Atomic File Writing**:
```python
for relative_path, content in generated_files.items():
    full_path = node_path / relative_path

    # Write to temporary file first
    temp_path = full_path.with_suffix(".tmp")
    temp_path.write_text(content)

    # Atomic rename
    temp_path.rename(full_path)
```

3. **Path Tracking**:
```python
written_paths = [
    node_path / relative_path
    for relative_path in generated_files.keys()
]
```

**Output**:
```python
@dataclass
class WrittenFiles:
    node_directory: Path
    main_file: Path
    all_files: List[Path]
    total_bytes: int
```

**Error Handling**:
- Rollback on write failure (delete temp files)
- Verify disk space before writing
- Handle permission errors gracefully

---

### Stage 6: Compilation Testing (Optional)

**Purpose**: Verify generated code compiles

**Process**:

1. **Type Checking** (mypy):
```bash
poetry run mypy {node_path}/v1_0_0/node.py --strict
```

2. **Import Test**:
```python
# Add to Python path
sys.path.insert(0, str(node_path.parent))

# Try to import
try:
    module = import_module(f"{node_path.name}.v1_0_0.node")
    node_class = getattr(module, f"Node{service_name_pascal}Effect")
except ImportError as e:
    raise CompilationError(f"Import failed: {e}")
```

**Output**:
```python
@dataclass
class CompilationResult:
    mypy_passed: bool
    import_passed: bool
    mypy_output: str
    mypy_error_count: int
    import_error: Optional[str]
```

**Error Handling**:
- **NOT BLOCKING**: Compilation errors don't fail the pipeline
- Report errors for manual review
- Suggest fixes if patterns detected

---

## Data Flow

### Complete Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                         INPUT LAYER                               │
└──────────────────────────────────────────────────────────────────┘

Natural Language Prompt
{
  "text": "Create EFFECT node for PostgreSQL database write operations",
  "requested_by": "user",
  "timestamp": "2025-10-21T10:00:00Z"
}

                    ↓

┌──────────────────────────────────────────────────────────────────┐
│                    PARSING LAYER                                  │
└──────────────────────────────────────────────────────────────────┘

ParsedPromptData
{
  "node_type": "EFFECT",
  "service_name": "postgres_writer",
  "domain": "infrastructure",
  "description": "PostgreSQL database write operations",
  "operations": ["create", "update", "delete"],
  "confidence": 0.85
}

                    ↓

┌──────────────────────────────────────────────────────────────────┐
│                 VALIDATION LAYER (PRE)                            │
└──────────────────────────────────────────────────────────────────┘

ValidationResult
{
  "passed": true,
  "imports_valid": true,
  "templates_available": true,
  "output_writable": true,
  "warnings": []
}

                    ↓

┌──────────────────────────────────────────────────────────────────┐
│                 GENERATION LAYER                                  │
└──────────────────────────────────────────────────────────────────┘

GeneratedCode
{
  "main_node_file": "#!/usr/bin/env python3\n...",
  "additional_files": {
    "models/model_postgres_writer_input.py": "...",
    "models/model_postgres_writer_output.py": "...",
    ...
  },
  "context": {...},
  "generation_time_ms": 12450
}

                    ↓

┌──────────────────────────────────────────────────────────────────┐
│               VALIDATION LAYER (POST)                             │
└──────────────────────────────────────────────────────────────────┘

ValidationReport
{
  "syntax_valid": true,
  "imports_valid": true,
  "naming_compliant": true,
  "errors": [],
  "warnings": ["Unused import in line 23"]
}

                    ↓

┌──────────────────────────────────────────────────────────────────┐
│                   FILE WRITING LAYER                              │
└──────────────────────────────────────────────────────────────────┘

WrittenFiles
{
  "node_directory": "/path/to/node_infrastructure_postgres_writer_effect",
  "main_file": "/path/to/.../v1_0_0/node.py",
  "all_files": [...],
  "total_bytes": 45678
}

                    ↓

┌──────────────────────────────────────────────────────────────────┐
│                 COMPILATION LAYER (OPTIONAL)                      │
└──────────────────────────────────────────────────────────────────┘

CompilationResult
{
  "mypy_passed": true,
  "import_passed": true,
  "mypy_output": "Success: no issues found",
  "mypy_error_count": 0
}

                    ↓

┌──────────────────────────────────────────────────────────────────┐
│                        OUTPUT LAYER                               │
└──────────────────────────────────────────────────────────────────┘

GenerationResult
{
  "success": true,
  "node_type": "EFFECT",
  "service_name": "postgres_writer",
  "domain": "infrastructure",
  "output_path": "/path/to/node_infrastructure_postgres_writer_effect",
  "files_written": [...],
  "validation_passed": true,
  "compilation_passed": true,
  "duration_seconds": 38.5,
  "correlation_id": "uuid-here"
}
```

---

## Event Contracts

### Event Schema (For Future Event Bus)

See `schemas/pipeline_events.yaml` for complete event definitions.

**Event Flow**:
```
PromptSubmitted → ValidationStarted → ValidationCompleted →
GenerationStarted → GenerationCompleted → WritingStarted →
WritingCompleted → CompilationStarted → CompilationCompleted →
PipelineCompleted
```

**Event Structure** (Common Fields):
```yaml
event_id: UUID
event_type: str  # "PromptSubmitted", "GenerationCompleted", etc.
correlation_id: UUID  # Trace entire pipeline
timestamp: datetime
stage: str  # "parsing", "validation", "generation", etc.
status: str  # "started", "in_progress", "completed", "failed"
payload: Dict[str, Any]  # Stage-specific data
```

**Error Events**:
```yaml
event_type: "ValidationFailed" | "GenerationFailed" | "WritingFailed"
payload:
  error_code: str
  error_message: str
  error_context: Dict[str, Any]
  recovery_suggestions: List[str]
```

---

## Validation Gates

### Gate Hierarchy

```
┌──────────────────────────────────────────────────────────────────┐
│                    VALIDATION GATES                               │
│  BLOCKING (pipeline fails) vs WARNING (continue with notes)       │
└──────────────────────────────────────────────────────────────────┘

PRE-GENERATION GATES (BLOCKING):
  ✓ G1: Prompt has minimum required info
  ✓ G2: Node type is valid (EFFECT only for POC)
  ✓ G3: Service name is valid identifier
  ✓ G4: Critical imports exist in omnibase_core
  ✓ G5: Templates are available
  ✓ G6: Output directory is writable

GENERATION GATES (WARNING):
  ⚠ G7: Context has all expected fields
  ⚠ G8: Template rendering completes without warnings

POST-GENERATION GATES (BLOCKING):
  ✓ G9: Generated code has valid Python syntax
  ✓ G10: Node class follows naming convention (suffix-based)
  ✓ G11: All imports are resolvable
  ✓ G12: Pydantic models are well-formed

COMPILATION GATES (WARNING):
  ⚠ G13: MyPy type checking passes (0 errors)
  ⚠ G14: Import test succeeds
```

### Gate Definitions

#### G1: Prompt Completeness
```python
def validate_prompt_completeness(prompt: str) -> ValidationResult:
    """Ensure prompt has minimum information."""
    checks = {
        "length": len(prompt) >= 10,
        "has_verb": any(verb in prompt.lower() for verb in ["create", "build", "generate"]),
        "has_context": len(prompt.split()) >= 5,
    }

    if not all(checks.values()):
        return ValidationResult(
            passed=False,
            errors=["Prompt too short or missing context"],
            suggestions=["Include: action verb, service name, purpose"]
        )

    return ValidationResult(passed=True)
```

#### G4: Critical Imports Exist
```python
def validate_critical_imports() -> ValidationResult:
    """Validate omnibase_core imports before generation."""
    failures = []

    for import_path in CRITICAL_IMPORTS:
        try:
            module_path, class_name = import_path.rsplit(".", 1)
            module = import_module(module_path)

            if not hasattr(module, class_name):
                failures.append(f"{class_name} not found in {module_path}")
        except ImportError as e:
            failures.append(f"Cannot import {module_path}: {e}")

    if failures:
        return ValidationResult(
            passed=False,
            errors=failures,
            suggestions=["Run: poetry install omnibase_core", "Check omnibase_core version"]
        )

    return ValidationResult(passed=True)
```

#### G9: Python Syntax Valid
```python
def validate_syntax(code: str, file_path: str) -> ValidationResult:
    """Validate generated code syntax."""
    try:
        ast.parse(code)
        return ValidationResult(passed=True)
    except SyntaxError as e:
        return ValidationResult(
            passed=False,
            errors=[f"Syntax error in {file_path} line {e.lineno}: {e.msg}"],
            context={"line": e.lineno, "offset": e.offset, "text": e.text}
        )
```

#### G10: ONEX Naming Convention
```python
def validate_onex_naming(code: str, node_type: str) -> ValidationResult:
    """Validate suffix-based naming (NOT prefix)."""
    # Find class definition
    class_pattern = rf"class\s+(Node\w+{node_type})\("
    match = re.search(class_pattern, code)

    if not match:
        return ValidationResult(
            passed=False,
            errors=[f"Node class not found or incorrect naming (must end with '{node_type}')"],
            suggestions=[f"Example: class NodePostgresWriter{node_type}(Node{node_type}Service)"]
        )

    class_name = match.group(1)

    # Verify suffix (not prefix)
    if not class_name.endswith(node_type):
        return ValidationResult(
            passed=False,
            errors=[f"Incorrect naming: '{class_name}' should end with '{node_type}'"],
            suggestions=[f"WRONG: class {node_type}PostgresWriter | CORRECT: class NodePostgresWriter{node_type}"]
        )

    return ValidationResult(passed=True)
```

---

## File Generation Patterns

### Directory Structure (ONEX Standard)

```
node_infrastructure_postgres_writer_effect/
├── node.manifest.yaml                    # Node-level metadata (Tier 2)
└── v1_0_0/                               # Version directory
    ├── __init__.py                       # Version exports
    ├── node.py                           # Main node implementation
    ├── contract.yaml                     # ONEX contract definition
    ├── version.manifest.yaml             # Version-specific metadata (Tier 3)
    ├── models/
    │   ├── __init__.py
    │   ├── model_postgres_writer_input.py
    │   ├── model_postgres_writer_output.py
    │   ├── model_postgres_writer_config.py
    │   └── model_postgres_writer_effect_contract.py
    └── enums/
        ├── __init__.py
        └── enum_postgres_writer_operation_type.py
```

### File Templates (Simplified for POC)

#### node.py
```python
#!/usr/bin/env python3
"""
NodePostgresWriterEffect - EFFECT node for PostgreSQL database write operations

ONEX Compliance:
- Suffix-based naming: Node<Name>Effect ✓
- Container-based DI ✓
- Strong typing (no Any types) ✓
"""

from typing import Dict, Any
from omnibase_core.nodes.node_effect import NodeEffect
from omnibase_core.models.container.model_onex_container import ModelONEXContainer
from omnibase_core.errors.model_onex_error import ModelOnexError
from omnibase_core.errors.error_codes import EnumCoreErrorCode

from .models.model_postgres_writer_input import ModelPostgresWriterInput
from .models.model_postgres_writer_output import ModelPostgresWriterOutput
from .models.model_postgres_writer_config import ModelPostgresWriterConfig


class NodePostgresWriterEffect(NodeEffect):
    """EFFECT node for PostgreSQL database write operations."""

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize with dependency injection."""
        super().__init__(container)
        self.logger = container.logger
        self.config = ModelPostgresWriterConfig()

    async def execute_effect(
        self,
        input_data: ModelPostgresWriterInput
    ) -> ModelPostgresWriterOutput:
        """
        Execute PostgreSQL write operation.

        Args:
            input_data: Validated input data

        Returns:
            Operation result with metadata

        Raises:
            ModelOnexError: If operation fails
        """
        try:
            # TODO: Implement PostgreSQL write logic
            # Based on requirements:
            # - Create records
            # - Update records
            # - Delete records

            return ModelPostgresWriterOutput(
                success=True,
                result_data={"status": "completed"},
                correlation_id=input_data.correlation_id
            )

        except Exception as e:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"PostgreSQL write failed: {str(e)}",
                context={"operation": input_data.operation_type}
            ) from e
```

#### model_postgres_writer_input.py
```python
#!/usr/bin/env python3
"""Input model for postgres_writer node."""

from typing import Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field


class ModelPostgresWriterInput(BaseModel):
    """Input envelope for PostgreSQL writer operations."""

    operation_type: str = Field(
        ...,
        description="Type of operation to perform",
        pattern="^(create|update|delete)$"
    )

    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Operation parameters"
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )

    correlation_id: UUID = Field(
        ...,
        description="Request correlation ID"
    )

    class Config:
        """Pydantic configuration."""
        validate_assignment = True
        extra = "forbid"  # Reject unknown fields
```

---

## Error Handling Strategy

### Error Classification

```
┌──────────────────────────────────────────────────────────────────┐
│                     ERROR HIERARCHY                               │
└──────────────────────────────────────────────────────────────────┘

Level 1: USER ERRORS (fixable by user)
  - InvalidPromptError: Prompt too short/vague
  - InvalidNodeTypeError: Unsupported node type

Level 2: ENVIRONMENT ERRORS (fixable by setup)
  - MissingDependencyError: omnibase_core not installed
  - TemplateNotFoundError: Template files missing
  - OutputDirectoryError: Cannot write to output

Level 3: GENERATION ERRORS (bugs in pipeline)
  - TemplateRenderError: Template rendering failed
  - ValidationError: Generated code invalid
  - FileWriteError: Cannot write files

Level 4: SYSTEM ERRORS (infrastructure issues)
  - OutOfMemoryError: System resources exhausted
  - PermissionError: Filesystem permissions
```

### Error Recovery Matrix

| Error Type | Retry? | Rollback? | User Action |
|------------|--------|-----------|-------------|
| InvalidPromptError | No | N/A | Rephrase prompt |
| MissingDependencyError | No | N/A | Install dependencies |
| TemplateNotFoundError | No | N/A | Check installation |
| TemplateRenderError | No | Yes | Report bug |
| ValidationError | No | Yes | Report bug |
| FileWriteError | Yes (3x) | Yes | Check permissions |
| OutOfMemoryError | No | Yes | Free up resources |

### Error Response Format

```python
@dataclass
class ErrorResponse:
    """Structured error response."""
    error_code: str  # "INVALID_PROMPT", "MISSING_DEPENDENCY", etc.
    error_message: str
    error_level: str  # "user", "environment", "generation", "system"
    correlation_id: UUID
    timestamp: datetime
    stage_failed: str  # "parsing", "validation", "generation", etc.
    context: Dict[str, Any]
    suggestions: List[str]
    recovery_possible: bool

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging/events."""
        return asdict(self)
```

### Rollback Strategy

```python
class GenerationPipeline:
    def __init__(self):
        self.written_files: List[Path] = []
        self.temp_files: List[Path] = []

    async def rollback(self, stage: str):
        """Rollback changes on failure."""
        self.logger.warning(f"Rolling back changes from stage: {stage}")

        # Delete written files
        for file_path in self.written_files:
            if file_path.exists():
                file_path.unlink()
                self.logger.debug(f"Deleted: {file_path}")

        # Delete temp files
        for file_path in self.temp_files:
            if file_path.exists():
                file_path.unlink()

        # Delete empty directories
        # (implementation details...)

        self.logger.info("Rollback complete")
```

---

## Success Criteria

### Functional Success Criteria

1. **Generation Completeness**:
   - ✅ All required files generated (node.py, models, enums, contracts, manifests)
   - ✅ Directory structure matches ONEX standards
   - ✅ All __init__.py files created with correct exports

2. **Code Quality**:
   - ✅ Generated code has valid Python syntax (AST parsing succeeds)
   - ✅ All imports resolve successfully
   - ✅ ONEX naming conventions followed (suffix-based)
   - ✅ Pydantic models are well-formed

3. **ONEX Compliance**:
   - ✅ Node class inherits from NodeEffect
   - ✅ Uses ModelONEXContainer for DI
   - ✅ Error handling uses ModelOnexError
   - ✅ Type hints on all methods

### Performance Success Criteria

1. **Latency**:
   - ✅ Total generation time < 2 minutes (target: ~35-40 seconds)
   - ✅ Prompt parsing < 5 seconds
   - ✅ Code generation < 15 seconds
   - ✅ Validation < 5 seconds
   - ✅ File writing < 3 seconds

2. **Resource Usage**:
   - ✅ Memory usage < 500 MB
   - ✅ CPU usage spikes acceptable (short-lived)
   - ✅ Disk I/O minimal (batch writes)

### Quality Success Criteria

1. **Type Safety**:
   - ✅ `poetry run mypy` passes with 0 errors
   - ✅ No `Any` types in generated code (ZERO TOLERANCE)
   - ✅ All Pydantic models have field descriptions

2. **Compilability**:
   - ✅ Generated code can be imported
   - ✅ No circular dependencies
   - ✅ All protocols satisfied

### Acceptance Criteria

**POC is considered SUCCESSFUL if**:

```python
def test_poc_acceptance():
    """POC acceptance test."""
    pipeline = GenerationPipeline()

    # Test Case 1: Basic EFFECT node
    result = pipeline.generate_from_prompt(
        prompt="Create EFFECT node for PostgreSQL database write operations",
        output_dir=Path("test_output")
    )

    # Assertions
    assert result.success == True
    assert result.node_type == "EFFECT"
    assert result.service_name == "postgres_writer"
    assert len(result.files_written) >= 10  # All required files
    assert result.duration_seconds < 120    # < 2 minutes
    assert result.validation_passed == True

    # Verify compilation
    node_file = result.output_path / "v1_0_0" / "node.py"
    assert node_file.exists()

    # Verify mypy passes
    mypy_result = subprocess.run(
        ["poetry", "run", "mypy", str(node_file)],
        capture_output=True
    )
    assert mypy_result.returncode == 0  # No type errors

    # Verify import works
    sys.path.insert(0, str(result.output_path.parent))
    from node_infrastructure_postgres_writer_effect.v1_0_0.node import NodePostgresWriterEffect

    # Verify ONEX naming
    assert NodePostgresWriterEffect.__name__.endswith("Effect")

    print("✅ POC ACCEPTANCE TEST PASSED")
```

---

## Implementation Readiness

### Prerequisites

**Before Implementation Starts**:
- ✅ This design document approved
- ✅ Import bugs in template_engine.py documented (lines 476, 502)
- ✅ omnibase_core available and installed
- ✅ Templates available in agents/templates/
- ✅ Test environment ready

### Implementation Tasks

See `docs/POC_IMPLEMENTATION_TASKS.md` for detailed task breakdown.

**High-Level Phases**:
1. **Phase 1.1**: Fix template import bugs (4-6 hours)
2. **Phase 1.2**: Create validators (3-4 hours)
3. **Phase 1.3**: Build pipeline (10-12 hours)
4. **Phase 1.4**: Testing & validation (3-4 hours)

**Total Effort**: 20-26 hours

### Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Template import bugs block generation | HIGH | CRITICAL | Fix in Phase 1.1 (first task) |
| Prompt parsing inaccuracy | MEDIUM | LOW | Use conservative defaults |
| File write permissions | LOW | MEDIUM | Validate before generation |
| MyPy failures on generated code | MEDIUM | LOW | Make compilation gate non-blocking |

### Next Steps

1. ✅ Review and approve this architecture document
2. 📋 Create detailed implementation tasks
3. 🔧 Set up development environment
4. 🚀 Begin Phase 1.1 (fix template imports)
5. 📊 Track progress against success criteria

---

## Appendix A: Event Schemas

See `schemas/pipeline_events.yaml` for complete event definitions.

## Appendix B: Validation Gate Specifications

See above sections for detailed gate definitions.

## Appendix C: Example Flows

See `docs/POC_EXAMPLE_FLOWS.md` for:
- Successful generation example
- Validation failure example
- Error handling example
- Rollback example

---

**Document Version**: 1.0
**Status**: Design Complete - Ready for Implementation
**Next Review**: After Phase 1.1 completion
