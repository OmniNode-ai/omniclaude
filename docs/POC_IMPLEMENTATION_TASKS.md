# POC Implementation Tasks: Autonomous Node Generation

**Phase**: 1 (POC Execution)
**Generated**: 2025-10-21
**Status**: Ready for Implementation
**Total Estimated Effort**: 20-26 hours

---

## Table of Contents

1. [Task Overview](#task-overview)
2. [Phase 1.1: Fix Template Import Bugs](#phase-11-fix-template-import-bugs)
3. [Phase 1.2: Create Validators](#phase-12-create-validators)
4. [Phase 1.3: Build Pipeline](#phase-13-build-pipeline)
5. [Phase 1.4: Testing & Validation](#phase-14-testing--validation)
6. [Dependencies Matrix](#dependencies-matrix)
7. [Testing Strategy](#testing-strategy)
8. [Acceptance Criteria](#acceptance-criteria)

---

## Task Overview

### High-Level Phases

```
┌────────────────────────────────────────────────────────────────┐
│                     POC IMPLEMENTATION                          │
└────────────────────────────────────────────────────────────────┘

Phase 1.1: Fix Template Import Bugs (4-6 hours) 🔴 CRITICAL
  ├── Task 1.1.1: Audit current import paths
  ├── Task 1.1.2: Fix ModelEffectInput/Output imports
  ├── Task 1.1.3: Update Pydantic v2 migrations
  └── Task 1.1.4: Test template rendering

Phase 1.2: Create Validators (3-4 hours) 🔴 HIGH
  ├── Task 1.2.1: Create OmnibaseCoreValidator
  ├── Task 1.2.2: Create PostGenerationValidator
  └── Task 1.2.3: Test validation logic

Phase 1.3: Build Pipeline (10-12 hours) 🔴 HIGH
  ├── Task 1.3.1: Create PromptParser
  ├── Task 1.3.2: Create FileWriter
  ├── Task 1.3.3: Create GenerationPipeline orchestrator
  ├── Task 1.3.4: Integrate template engine
  └── Task 1.3.5: Add error handling & rollback

Phase 1.4: Testing & Validation (3-4 hours) 🟡 MEDIUM
  ├── Task 1.4.1: Unit tests for each component
  ├── Task 1.4.2: Integration tests for end-to-end flow
  ├── Task 1.4.3: Acceptance tests (real generation)
  └── Task 1.4.4: Performance benchmarks

Total: 20-26 hours
```

---

## Phase 1.1: Fix Template Import Bugs

**Priority**: 🔴 CRITICAL
**Duration**: 4-6 hours
**Blocking**: ALL subsequent work

### Task 1.1.1: Audit Current Import Paths

**Objective**: Identify all incorrect import paths in templates

**Steps**:
1. Open `/Volumes/PRO-G40/Code/omniclaude/agents/lib/omninode_template_engine.py`
2. Search for all imports from `omnibase_core`
3. Cross-reference with actual omnibase_core structure
4. Document incorrect paths

**Deliverable**:
```markdown
# Import Path Audit Report

## WRONG Imports (Current):
- Line 476: from omnibase_core.core.node_effect import ModelEffectInput
- Line 502: from omnibase_core.core.node_effect import ModelEffectOutput
- Line 16: from omnibase_core.errors import OnexError  # Should be ModelOnexError

## CORRECT Imports (Target):
- from omnibase_core.nodes.node_effect import NodeEffect
- from omnibase_core.errors.model_onex_error import ModelOnexError
- from omnibase_core.errors.error_codes import EnumCoreErrorCode
- from omnibase_core.models.container.model_onex_container import ModelONEXContainer

## Missing Model Classes:
- ModelEffectInput: Does NOT exist in omnibase_core
- ModelEffectOutput: Does NOT exist in omnibase_core
→ DECISION: Generate these models as part of node generation
```

**Estimated Time**: 1 hour

---

### Task 1.1.2: Fix ModelEffectInput/Output Imports

**Objective**: Update template engine to generate I/O models instead of importing them

**Current Code** (WRONG):
```python
# Line 476
from omnibase_core.core.node_effect import ModelEffectInput

# Line 502
from omnibase_core.core.node_effect import ModelEffectOutput
```

**Updated Code** (CORRECT):
```python
# Remove imports from omnibase_core (they don't exist)
# Instead, generate models as part of node generation

def _generate_input_model(
    self, microservice_name: str, analysis_result: SimplePRDAnalysisResult
) -> str:
    """Generate input model (NOT import from omnibase_core)."""
    pascal_name = self._to_pascal_case(microservice_name)

    return f'''#!/usr/bin/env python3
"""
Input model for {microservice_name} node
"""

from typing import Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field

class Model{pascal_name}Input(BaseModel):
    """Input envelope for {microservice_name} operations"""

    operation_type: str = Field(..., description="Type of operation to perform")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Operation parameters")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    correlation_id: UUID = Field(..., description="Request correlation ID")

    class Config:
        """Pydantic configuration."""
        validate_assignment = True
        extra = "forbid"
'''
```

**Testing**:
```python
# Test generated input model
engine = OmninodeTemplateEngine()
input_model = engine._generate_input_model("postgres_writer", analysis_result)

# Verify:
assert "class ModelPostgresWriterInput(BaseModel):" in input_model
assert "correlation_id: UUID" in input_model
assert "extra = \"forbid\"" in input_model
```

**Estimated Time**: 2 hours

---

### Task 1.1.3: Update Pydantic v2 Migrations

**Objective**: Replace `.dict()` with `.model_dump()` everywhere

**Files to Update**:
- `agents/templates/effect_node_template.py` (line 96)
- `agents/templates/compute_node_template.py` (line 96)
- `agents/templates/reducer_node_template.py` (line 105)
- `agents/templates/orchestrator_node_template.py` (line 105)

**Changes**:
```python
# BEFORE (Pydantic v1):
input_dict = input_data.dict()

# AFTER (Pydantic v2):
input_dict = input_data.model_dump()
```

**Search & Replace**:
```bash
# Find all .dict() calls
grep -rn "\.dict()" agents/templates/

# Replace with .model_dump()
sed -i '' 's/\.dict()/\.model_dump()/g' agents/templates/*.py
```

**Testing**:
```python
# Verify all templates use Pydantic v2
for template_file in Path("agents/templates").glob("*.py"):
    content = template_file.read_text()
    assert ".dict()" not in content, f"{template_file} still uses .dict()"
    assert ".model_dump()" in content or "BaseModel" not in content
```

**Estimated Time**: 1 hour

---

### Task 1.1.4: Test Template Rendering

**Objective**: Verify all templates render without errors

**Test Script**:
```python
#!/usr/bin/env python3
"""Test template rendering after import fixes."""

from agents.lib.omninode_template_engine import OmninodeTemplateEngine
from agents.lib.simple_prd_analyzer import SimplePRDAnalysisResult

def test_template_rendering():
    """Test all templates render correctly."""
    engine = OmninodeTemplateEngine()

    # Create mock analysis result
    analysis_result = SimplePRDAnalysisResult(
        node_type="EFFECT",
        service_name="test_service",
        domain="test_domain",
        description="Test service",
        # ... other fields
    )

    # Test EFFECT template
    result = engine.generate_node(
        analysis_result=analysis_result,
        node_type="EFFECT",
        microservice_name="test_service",
        domain="test_domain",
        output_directory="/tmp/test_output"
    )

    # Assertions
    assert result["success"]
    assert len(result["generated_files"]) >= 10
    assert Path(result["main_file"]).exists()

    # Verify imports are correct
    main_file_content = Path(result["main_file"]).read_text()
    assert "from omnibase_core.nodes.node_effect import NodeEffect" in main_file_content
    assert "from omnibase_core.core.node_effect" not in main_file_content  # OLD PATH

    print("✅ Template rendering test PASSED")

if __name__ == "__main__":
    test_template_rendering()
```

**Estimated Time**: 1-2 hours

---

## Phase 1.2: Create Validators

**Priority**: 🔴 HIGH
**Duration**: 3-4 hours
**Dependencies**: None (can run parallel to 1.1)

### Task 1.2.1: Create OmnibaseCoreValidator

**Objective**: Validate omnibase_core imports before generation

**File**: `agents/lib/omnibase_core_validator.py`

**Implementation**:
```python
#!/usr/bin/env python3
"""
OmnibaseCoreValidator - Validate omnibase_core imports before code generation.

Prevents generation failures by checking critical imports exist.
"""

from importlib import import_module
from typing import Dict, List
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ImportValidationResult:
    """Result of import validation."""
    import_path: str
    exists: bool
    error_message: str | None = None


class OmnibaseCoreValidator:
    """Validate omnibase_core imports before code generation."""

    CRITICAL_IMPORTS = [
        "omnibase_core.nodes.node_effect.NodeEffect",
        "omnibase_core.nodes.node_compute.NodeCompute",
        "omnibase_core.nodes.node_reducer.NodeReducer",
        "omnibase_core.nodes.node_orchestrator.NodeOrchestrator",
        "omnibase_core.errors.model_onex_error.ModelOnexError",
        "omnibase_core.errors.error_codes.EnumCoreErrorCode",
        "omnibase_core.models.container.model_onex_container.ModelONEXContainer",
    ]

    def validate_all_imports(self) -> Dict[str, ImportValidationResult]:
        """Validate all critical imports exist."""
        results = {}
        for import_path in self.CRITICAL_IMPORTS:
            results[import_path] = self._validate_import(import_path)
        return results

    def _validate_import(self, import_path: str) -> ImportValidationResult:
        """Validate single import path."""
        try:
            module_path, class_name = import_path.rsplit(".", 1)
            module = import_module(module_path)

            if not hasattr(module, class_name):
                return ImportValidationResult(
                    import_path=import_path,
                    exists=False,
                    error_message=f"Class '{class_name}' not found in module '{module_path}'"
                )

            return ImportValidationResult(import_path=import_path, exists=True)

        except ImportError as e:
            return ImportValidationResult(
                import_path=import_path,
                exists=False,
                error_message=str(e)
            )

    def get_failing_imports(self) -> List[str]:
        """Get list of imports that fail validation."""
        results = self.validate_all_imports()
        return [path for path, result in results.items() if not result.exists]

    def raise_if_invalid(self) -> None:
        """Raise exception if any critical imports are invalid."""
        failing = self.get_failing_imports()
        if failing:
            raise ValueError(
                f"Critical omnibase_core imports are invalid:\n" +
                "\n".join(f"  ❌ {path}" for path in failing) +
                "\n\nSuggestions:\n" +
                "  - Run: poetry install omnibase_core\n" +
                "  - Check omnibase_core version >=2.0"
            )

    def get_validation_report(self) -> Dict[str, any]:
        """Get detailed validation report."""
        results = self.validate_all_imports()
        failing = [r for r in results.values() if not r.exists]
        passing = [r for r in results.values() if r.exists]

        return {
            "total_checked": len(results),
            "passing": len(passing),
            "failing": len(failing),
            "success_rate": len(passing) / len(results) if results else 0.0,
            "failing_imports": [r.import_path for r in failing],
            "details": results
        }


if __name__ == "__main__":
    # CLI usage
    validator = OmnibaseCoreValidator()
    report = validator.get_validation_report()

    print(f"✓ Passing: {report['passing']}/{report['total_checked']}")
    print(f"✗ Failing: {report['failing']}/{report['total_checked']}")

    if report['failing'] > 0:
        print("\nFailing imports:")
        for import_path in report['failing_imports']:
            print(f"  ❌ {import_path}")
        exit(1)
    else:
        print("\n✅ All imports valid")
        exit(0)
```

**Testing**:
```python
def test_omnibase_core_validator():
    """Test validator catches import issues."""
    validator = OmnibaseCoreValidator()

    # Should pass if omnibase_core installed
    report = validator.get_validation_report()
    assert report['success_rate'] == 1.0, f"Failed: {report['failing_imports']}"

    # Test invalid import
    validator.CRITICAL_IMPORTS.append("nonexistent.module.Class")
    try:
        validator.raise_if_invalid()
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "nonexistent.module.Class" in str(e)
```

**Estimated Time**: 1.5-2 hours

---

### Task 1.2.2: Create PostGenerationValidator

**Objective**: Validate generated code quality

**File**: `agents/lib/post_generation_validator.py`

**Implementation**:
```python
#!/usr/bin/env python3
"""
PostGenerationValidator - Validate generated code quality.

Checks:
- Syntax (AST parsing)
- ONEX naming conventions
- Import resolution
- Pydantic model structure
"""

import ast
import re
from typing import Dict, List, Any
from dataclasses import dataclass
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class ValidationReport:
    """Validation report."""
    syntax_valid: bool
    imports_valid: bool
    naming_compliant: bool
    pydantic_valid: bool
    errors: List[str]
    warnings: List[str]
    suggestions: List[str]


class PostGenerationValidator:
    """Validate generated code quality."""

    def validate_generated_code(
        self,
        generated_files: Dict[str, str],
        node_type: str
    ) -> ValidationReport:
        """
        Validate all generated code.

        Args:
            generated_files: Dict of {file_path: content}
            node_type: Expected node type (EFFECT, COMPUTE, etc.)

        Returns:
            Validation report
        """
        errors = []
        warnings = []
        suggestions = []

        syntax_valid = True
        imports_valid = True
        naming_compliant = True
        pydantic_valid = True

        # Validate each Python file
        for file_path, code in generated_files.items():
            if not file_path.endswith(".py"):
                continue

            # Check 1: Syntax
            syntax_result = self._validate_syntax(code, file_path)
            if not syntax_result["valid"]:
                syntax_valid = False
                errors.extend(syntax_result["errors"])

            # Check 2: ONEX Naming
            naming_result = self._validate_onex_naming(code, node_type, file_path)
            if not naming_result["valid"]:
                naming_compliant = False
                errors.extend(naming_result["errors"])
                suggestions.extend(naming_result["suggestions"])

            # Check 3: Import Resolution
            import_result = self._validate_imports(code, file_path)
            if not import_result["valid"]:
                imports_valid = False
                warnings.extend(import_result["warnings"])

            # Check 4: Pydantic Models
            pydantic_result = self._validate_pydantic_models(code, file_path)
            if not pydantic_result["valid"]:
                pydantic_valid = False
                warnings.extend(pydantic_result["warnings"])

        return ValidationReport(
            syntax_valid=syntax_valid,
            imports_valid=imports_valid,
            naming_compliant=naming_compliant,
            pydantic_valid=pydantic_valid,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions
        )

    def _validate_syntax(self, code: str, file_path: str) -> Dict[str, Any]:
        """Validate Python syntax via AST."""
        try:
            ast.parse(code)
            return {"valid": True, "errors": []}
        except SyntaxError as e:
            return {
                "valid": False,
                "errors": [
                    f"Syntax error in {file_path} line {e.lineno}: {e.msg}"
                ]
            }

    def _validate_onex_naming(
        self,
        code: str,
        node_type: str,
        file_path: str
    ) -> Dict[str, Any]:
        """Validate ONEX naming conventions (suffix-based)."""
        # Find node class
        class_pattern = rf"class\s+(Node\w+{node_type})\("
        match = re.search(class_pattern, code)

        if not match:
            # Check if this file should have a node class
            if "node.py" not in file_path:
                return {"valid": True, "errors": [], "suggestions": []}

            return {
                "valid": False,
                "errors": [
                    f"Node class not found in {file_path} or incorrect naming"
                ],
                "suggestions": [
                    f"Class name must end with '{node_type}' (suffix, not prefix)",
                    f"Example: class NodeMyService{node_type}(Node{node_type}Service)"
                ]
            }

        class_name = match.group(1)

        # Verify suffix (not prefix)
        if not class_name.endswith(node_type):
            return {
                "valid": False,
                "errors": [
                    f"Incorrect naming: '{class_name}' should end with '{node_type}'"
                ],
                "suggestions": [
                    f"WRONG: class {node_type}MyService",
                    f"CORRECT: class NodeMyService{node_type}"
                ]
            }

        return {"valid": True, "errors": [], "suggestions": []}

    def _validate_imports(self, code: str, file_path: str) -> Dict[str, Any]:
        """Validate import statements (static check)."""
        warnings = []

        # Find all import statements
        import_pattern = r"^from\s+([\w\.]+)\s+import"
        for match in re.finditer(import_pattern, code, re.MULTILINE):
            module_path = match.group(1)

            # Check for old (wrong) import paths
            if "omnibase_core.core.node_" in module_path:
                warnings.append(
                    f"Old import path detected in {file_path}: {module_path}"
                    + " (should use omnibase_core.nodes.node_*)"
                )

        return {
            "valid": len(warnings) == 0,
            "warnings": warnings
        }

    def _validate_pydantic_models(
        self,
        code: str,
        file_path: str
    ) -> Dict[str, Any]:
        """Validate Pydantic model structure."""
        warnings = []

        # Check for old Pydantic v1 patterns
        if ".dict()" in code:
            warnings.append(
                f"Pydantic v1 pattern in {file_path}: .dict() should be .model_dump()"
            )

        # Check for BaseModel usage
        if "class Model" in code and "BaseModel" in code:
            # Verify Config class
            if "class Config:" not in code:
                warnings.append(
                    f"Pydantic model in {file_path} missing Config class"
                )

        return {
            "valid": len(warnings) == 0,
            "warnings": warnings
        }


if __name__ == "__main__":
    # CLI usage
    import sys

    if len(sys.argv) < 2:
        print("Usage: python post_generation_validator.py <node_directory>")
        sys.exit(1)

    node_dir = Path(sys.argv[1])
    generated_files = {}

    # Load all Python files
    for py_file in node_dir.rglob("*.py"):
        generated_files[str(py_file)] = py_file.read_text()

    # Validate
    validator = PostGenerationValidator()
    report = validator.validate_generated_code(generated_files, node_type="EFFECT")

    # Print report
    print(f"Syntax: {'✅' if report.syntax_valid else '❌'}")
    print(f"Imports: {'✅' if report.imports_valid else '⚠️'}")
    print(f"Naming: {'✅' if report.naming_compliant else '❌'}")
    print(f"Pydantic: {'✅' if report.pydantic_valid else '⚠️'}")

    if report.errors:
        print("\nErrors:")
        for error in report.errors:
            print(f"  ❌ {error}")

    if report.warnings:
        print("\nWarnings:")
        for warning in report.warnings:
            print(f"  ⚠️ {warning}")

    sys.exit(0 if not report.errors else 1)
```

**Estimated Time**: 1.5-2 hours

---

### Task 1.2.3: Test Validation Logic

**Objective**: Ensure validators catch all expected issues

**Test Cases**:
```python
def test_post_generation_validator():
    """Test post-generation validator."""
    validator = PostGenerationValidator()

    # Test Case 1: Valid code
    valid_code = {
        "node.py": '''
class NodeTestServiceEffect(NodeEffect):
    async def execute_effect(self, input_data):
        return input_data.model_dump()
        '''
    }
    report = validator.validate_generated_code(valid_code, "Effect")
    assert report.syntax_valid
    assert report.naming_compliant

    # Test Case 2: Syntax error
    invalid_syntax = {
        "node.py": "class NodeTest("  # Incomplete
    }
    report = validator.validate_generated_code(invalid_syntax, "Effect")
    assert not report.syntax_valid

    # Test Case 3: Wrong naming (prefix instead of suffix)
    wrong_naming = {
        "node.py": "class EffectTestService(NodeEffect): pass"
    }
    report = validator.validate_generated_code(wrong_naming, "Effect")
    assert not report.naming_compliant

    # Test Case 4: Old Pydantic pattern
    old_pydantic = {
        "model.py": '''
class ModelTest(BaseModel):
    def to_dict(self):
        return self.dict()  # OLD
        '''
    }
    report = validator.validate_generated_code(old_pydantic, "Effect")
    assert len(report.warnings) > 0
```

**Estimated Time**: 0.5-1 hour

---

## Phase 1.3: Build Pipeline

**Priority**: 🔴 HIGH
**Duration**: 10-12 hours
**Dependencies**: Phase 1.1, 1.2

### Task 1.3.1: Create PromptParser

**Objective**: Extract structured data from natural language prompts

**File**: `agents/lib/prompt_parser.py`

**Implementation**: See architecture document for full implementation.

**Key Methods**:
- `parse_prompt(prompt: str) -> ParsedPromptData`
- `_detect_node_type(prompt: str) -> str`
- `_extract_service_name(prompt: str) -> str`
- `_extract_domain(prompt: str) -> str`
- `_extract_operations(prompt: str, node_type: str) -> List[str]`

**Estimated Time**: 3-4 hours

---

### Task 1.3.2: Create FileWriter

**Objective**: Write generated files to filesystem with atomic operations

**File**: `agents/lib/file_writer.py`

**Key Features**:
- Atomic file writes (temp → rename)
- Directory structure creation
- Rollback on failure
- Path tracking

**Estimated Time**: 2-3 hours

---

### Task 1.3.3: Create GenerationPipeline Orchestrator

**Objective**: Orchestrate all pipeline stages

**File**: `agents/lib/generation_pipeline.py`

**Key Methods**:
- `generate_from_prompt(prompt: str, output_dir: Path) -> GenerationResult`
- `_stage_1_parse_prompt(prompt: str) -> ParsedPromptData`
- `_stage_2_pre_validate() -> ValidationResult`
- `_stage_3_generate_code(parsed_data: ParsedPromptData) -> GeneratedCode`
- `_stage_4_post_validate(generated_code: GeneratedCode) -> ValidationReport`
- `_stage_5_write_files(generated_code: GeneratedCode, output_dir: Path) -> WrittenFiles`
- `_stage_6_compile_test(written_files: WrittenFiles) -> CompilationResult`

**Estimated Time**: 3-4 hours

---

### Task 1.3.4: Integrate Template Engine

**Objective**: Connect pipeline to existing template engine

**Changes Required**:
- Adapter layer for `SimplePRDAnalysisResult`
- Context preparation from `ParsedPromptData`
- Error translation

**Estimated Time**: 1-2 hours

---

### Task 1.3.5: Add Error Handling & Rollback

**Objective**: Handle failures gracefully with rollback

**Features**:
- Try-except at each stage
- Rollback written files on failure
- Structured error responses
- Recovery suggestions

**Estimated Time**: 1-2 hours

---

## Phase 1.4: Testing & Validation

**Priority**: 🟡 MEDIUM
**Duration**: 3-4 hours
**Dependencies**: Phase 1.3

### Task 1.4.1: Unit Tests

**Files to Test**:
- `test_prompt_parser.py`
- `test_omnibase_core_validator.py`
- `test_post_generation_validator.py`
- `test_file_writer.py`

**Coverage Target**: >80%

**Estimated Time**: 1.5-2 hours

---

### Task 1.4.2: Integration Tests

**Test**: Full end-to-end pipeline

```python
def test_pipeline_end_to_end():
    """Test complete pipeline flow."""
    pipeline = GenerationPipeline()

    result = pipeline.generate_from_prompt(
        prompt="Create EFFECT node for PostgreSQL database write operations",
        output_dir=Path("/tmp/test_generation")
    )

    assert result.success
    assert result.node_type == "EFFECT"
    assert result.service_name == "postgres_writer"
    assert len(result.files_written) >= 10
```

**Estimated Time**: 1-1.5 hours

---

### Task 1.4.3: Acceptance Tests

**Objective**: Verify POC acceptance criteria

**Test Cases**:
1. Generate EFFECT node from prompt
2. Verify all files created
3. Run `poetry run mypy` (0 errors)
4. Import generated node
5. Verify ONEX naming compliance

**Estimated Time**: 0.5-1 hour

---

### Task 1.4.4: Performance Benchmarks

**Metrics**:
- Total generation time < 2 minutes
- Prompt parsing < 5 seconds
- Code generation < 15 seconds
- Validation < 5 seconds
- File writing < 3 seconds

**Estimated Time**: 0.5-1 hour

---

## Dependencies Matrix

```
Task Dependencies:

1.1.1 (Audit) → 1.1.2 (Fix Imports)
1.1.2 → 1.1.3 (Pydantic v2)
1.1.3 → 1.1.4 (Test Templates)

1.2.1 (Validator) ⊥ 1.1.* (Independent)
1.2.2 (Post Validator) ⊥ 1.1.* (Independent)
1.2.3 (Test Validators) → 1.2.1 + 1.2.2

1.3.1 (Parser) → 1.1.4 (Templates ready)
1.3.2 (FileWriter) → 1.1.4
1.3.3 (Pipeline) → 1.3.1 + 1.3.2 + 1.2.*
1.3.4 (Integration) → 1.3.3
1.3.5 (Error Handling) → 1.3.4

1.4.1 (Unit Tests) → 1.3.*
1.4.2 (Integration Tests) → 1.4.1
1.4.3 (Acceptance) → 1.4.2
1.4.4 (Performance) → 1.4.3

Critical Path: 1.1.1 → 1.1.2 → 1.1.3 → 1.1.4 → 1.3.1 → 1.3.3 → 1.4.2
Duration: ~4-6h + 3h + 3h + 1.5h = 11.5-13.5 hours
```

---

## Testing Strategy

### Unit Testing

**Framework**: pytest
**Coverage**: >80%

**Files**:
```
tests/
├── unit/
│   ├── test_prompt_parser.py
│   ├── test_omnibase_core_validator.py
│   ├── test_post_generation_validator.py
│   ├── test_file_writer.py
│   └── test_generation_pipeline.py
├── integration/
│   └── test_pipeline_e2e.py
└── acceptance/
    └── test_poc_acceptance.py
```

### Integration Testing

**Scenarios**:
1. **Happy Path**: Valid prompt → successful generation
2. **Invalid Prompt**: Missing info → validation failure
3. **Missing Dependencies**: omnibase_core not installed → pre-validation failure
4. **Write Failure**: No permissions → rollback
5. **Compilation Failure**: Generated code has type errors → warning (not blocking)

### Acceptance Testing

**POC Success Criteria**:
```python
def test_poc_acceptance():
    """POC acceptance test."""
    pipeline = GenerationPipeline()

    # Generate EFFECT node
    result = pipeline.generate_from_prompt(
        prompt="Create EFFECT node for PostgreSQL database write operations",
        output_dir=Path("test_output")
    )

    # Verify success
    assert result.success == True
    assert result.duration_seconds < 120  # < 2 minutes

    # Verify files
    node_file = result.output_path / "v1_0_0" / "node.py"
    assert node_file.exists()

    # Verify compilation
    mypy_result = subprocess.run(
        ["poetry", "run", "mypy", str(node_file)],
        capture_output=True
    )
    assert mypy_result.returncode == 0

    # Verify import
    sys.path.insert(0, str(result.output_path.parent))
    from node_infrastructure_postgres_writer_effect.v1_0_0.node import NodePostgresWriterEffect

    # Verify ONEX naming
    assert NodePostgresWriterEffect.__name__.endswith("Effect")
```

---

## Acceptance Criteria

### Functional Criteria

- [ ] Generate EFFECT node from natural language prompt
- [ ] All required files generated (node.py, models, enums, contracts, manifests)
- [ ] Directory structure matches ONEX standards
- [ ] Generated code has valid Python syntax
- [ ] All imports resolve successfully
- [ ] ONEX naming conventions followed (suffix-based)
- [ ] Pydantic models well-formed with validators
- [ ] Error handling uses ModelOnexError
- [ ] Type hints on all methods

### Performance Criteria

- [ ] Total generation time < 2 minutes
- [ ] Prompt parsing < 5 seconds
- [ ] Code generation < 15 seconds
- [ ] Validation < 5 seconds
- [ ] File writing < 3 seconds
- [ ] Memory usage < 500 MB

### Quality Criteria

- [ ] `poetry run mypy` passes with 0 errors
- [ ] No `Any` types in generated code
- [ ] All Pydantic models have field descriptions
- [ ] Generated code can be imported
- [ ] No circular dependencies
- [ ] Unit test coverage >80%

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Template import bugs remain | Phase 1.1 fixes this FIRST |
| Prompt parsing inaccuracy | Use conservative defaults, accept manual input |
| File write permissions | Validate before generation, rollback on failure |
| MyPy failures | Make compilation gate non-blocking |
| Timeline overrun | Parallel execution of 1.1 and 1.2 |

---

## Timeline (Gantt Chart)

```
Week 1:
Mon   [████████] 1.1.1-1.1.2 (Audit + Fix Imports)
Tue   [████████] 1.1.3-1.1.4 (Pydantic v2 + Test Templates)
Wed   [████████] 1.2.1-1.2.2 (Validators)
Thu   [████████] 1.3.1 (PromptParser)
Fri   [████████] 1.3.2 (FileWriter)

Week 2:
Mon   [████████] 1.3.3 (Pipeline Orchestrator)
Tue   [████████] 1.3.4-1.3.5 (Integration + Error Handling)
Wed   [████████] 1.4.1-1.4.2 (Testing)
Thu   [████████] 1.4.3-1.4.4 (Acceptance + Performance)
Fri   [✓✓✓✓✓✓✓✓] POC COMPLETE

Total: ~20-26 hours over 2 weeks
```

---

**Next Steps**:
1. Review and approve this implementation plan
2. Set up development environment
3. Begin Phase 1.1.1 (Audit import paths)
4. Track progress against task list

---

**Document Version**: 1.0
**Status**: Ready for Implementation
**Owner**: Development Team
