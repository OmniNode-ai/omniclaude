# POC Example Flows: Autonomous Node Generation

**Phase**: 1 (POC)
**Generated**: 2025-10-21
**Purpose**: Document example execution flows for success and failure scenarios

---

## Table of Contents

1. [Successful Generation Flow](#successful-generation-flow)
2. [Validation Failure Flow](#validation-failure-flow)
3. [Generation Error Flow](#generation-error-flow)
4. [Rollback Example](#rollback-example)
5. [Edge Cases](#edge-cases)

---

## Successful Generation Flow

### Scenario: Generate EFFECT Node from Prompt

**Input**:
```python
from agents.lib.generation_pipeline import GenerationPipeline
from pathlib import Path

pipeline = GenerationPipeline()

result = pipeline.generate_from_prompt(
    prompt="Create EFFECT node for PostgreSQL database write operations",
    output_dir=Path("/Users/developer/projects/omniclaude/src/nodes")
)
```

### Execution Trace

```
┌─────────────────────────────────────────────────────────────────┐
│                  PIPELINE EXECUTION TRACE                        │
└─────────────────────────────────────────────────────────────────┘

[2025-10-21 10:00:00.000] INFO: Pipeline started
  Correlation ID: 7c9e6679-7425-40de-944b-e07fc1f90ae7

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 1: PROMPT PARSING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[10:00:00.123] INFO: Starting prompt parsing
  Prompt: "Create EFFECT node for PostgreSQL database write operations"

[10:00:00.234] DEBUG: Detected node type: EFFECT
  Confidence: 0.95
  Keywords matched: ["EFFECT", "database", "write"]

[10:00:00.345] DEBUG: Extracted service name: postgres_writer
  Source: "PostgreSQL" → "postgres_writer"

[10:00:00.456] DEBUG: Detected domain: infrastructure
  Keywords: ["database", "PostgreSQL"]

[10:00:00.567] DEBUG: Extracted operations: ["create", "update", "delete"]
  Default EFFECT operations applied

[10:00:00.678] INFO: Parsing completed
  Duration: 678ms

  Parsed Data:
    node_type: EFFECT
    service_name: postgres_writer
    domain: infrastructure
    description: PostgreSQL database write operations
    confidence: 0.85

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 2: PRE-GENERATION VALIDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[10:00:01.789] INFO: Starting pre-generation validation

[10:00:01.890] DEBUG: Gate G1: Prompt completeness
  ✓ PASSED (length: 56 chars, has verb, has context)

[10:00:01.901] DEBUG: Gate G2: Node type valid
  ✓ PASSED (node_type: EFFECT, in supported types)

[10:00:01.912] DEBUG: Gate G3: Service name valid
  ✓ PASSED (service_name: postgres_writer, valid identifier)

[10:00:02.123] DEBUG: Gate G4: Critical imports exist
  ✓ Checking: omnibase_core.nodes.node_effect.NodeEffect
  ✓ Checking: omnibase_core.errors.model_onex_error.ModelOnexError
  ✓ Checking: omnibase_core.errors.error_codes.EnumCoreErrorCode
  ✓ Checking: omnibase_core.models.container.model_onex_container.ModelONEXContainer
  ✓ PASSED (all 7 imports valid)

[10:00:02.234] DEBUG: Gate G5: Templates available
  ✓ PASSED (effect_node_template.py found, 12.3 KB)

[10:00:02.345] DEBUG: Gate G6: Output directory writable
  ✓ PASSED (output_dir exists, writable)

[10:00:02.456] INFO: Pre-validation completed
  Duration: 667ms
  Gates checked: 6
  Gates passed: 6
  Gates failed: 0

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 3: CODE GENERATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[10:00:02.567] INFO: Starting code generation

[10:00:02.678] DEBUG: Loading EFFECT template
  Template: effect_node_template.py
  Cache hit: true

[10:00:02.789] DEBUG: Preparing template context
  Context keys: DOMAIN, MICROSERVICE_NAME, NODE_TYPE, ...

[10:00:03.890] DEBUG: Rendering main node file
  Template: effect_node_template.py
  Context: {MICROSERVICE_NAME: postgres_writer, ...}

[10:00:04.901] DEBUG: Generating input model
  File: models/model_postgres_writer_input.py

[10:00:05.012] DEBUG: Generating output model
  File: models/model_postgres_writer_output.py

[10:00:06.123] DEBUG: Generating config model
  File: models/model_postgres_writer_config.py

[10:00:07.234] DEBUG: Generating operation enum
  File: enums/enum_postgres_writer_operation_type.py

[10:00:08.345] DEBUG: Generating contract YAML
  File: contract.yaml

[10:00:09.456] DEBUG: Generating node manifest
  File: node.manifest.yaml

[10:00:10.567] DEBUG: Generating version manifest
  File: v1_0_0/version.manifest.yaml

[10:00:11.678] DEBUG: Generating __init__ files
  Files: v1_0_0/__init__.py, models/__init__.py, enums/__init__.py

[10:00:12.789] INFO: Code generation completed
  Duration: 10.222s
  Files generated: 11
  Total bytes: 45,678

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 4: POST-GENERATION VALIDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[10:00:12.890] INFO: Starting post-generation validation

[10:00:13.901] DEBUG: Gate G9: Syntax validation
  ✓ Validating: v1_0_0/node.py (AST parse successful)
  ✓ Validating: models/model_postgres_writer_input.py (AST parse successful)
  ✓ Validating: models/model_postgres_writer_output.py (AST parse successful)
  ✓ PASSED (all 8 Python files valid syntax)

[10:00:14.012] DEBUG: Gate G10: ONEX naming convention
  ✓ Found class: NodePostgresWriterEffect
  ✓ Suffix correct: ends with 'Effect'
  ✓ PASSED (naming compliant)

[10:00:14.123] DEBUG: Gate G11: Import resolution
  ✓ Checking: from omnibase_core.nodes.node_effect import NodeEffect
  ✓ Checking: from omnibase_core.errors.model_onex_error import ModelOnexError
  ✓ All imports resolvable
  ✓ PASSED (all imports valid)

[10:00:14.234] DEBUG: Gate G12: Pydantic model structure
  ✓ ModelPostgresWriterInput has Config class
  ✓ ModelPostgresWriterOutput has Config class
  ✓ All models use Field() descriptors
  ✓ PASSED (Pydantic models well-formed)

[10:00:14.345] INFO: Post-validation completed
  Duration: 1.455s
  Gates checked: 4
  Gates passed: 4
  Gates failed: 0
  Warnings: 0

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 5: FILE WRITING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[10:00:14.456] INFO: Starting file writing
  Output directory: /Users/developer/projects/omniclaude/src/nodes

[10:00:14.567] DEBUG: Creating directory structure
  ✓ Created: node_infrastructure_postgres_writer_effect/
  ✓ Created: node_infrastructure_postgres_writer_effect/v1_0_0/
  ✓ Created: node_infrastructure_postgres_writer_effect/v1_0_0/models/
  ✓ Created: node_infrastructure_postgres_writer_effect/v1_0_0/enums/

[10:00:14.678] DEBUG: Writing file: node.manifest.yaml (2.3 KB)
[10:00:14.789] DEBUG: Writing file: v1_0_0/node.py (8.5 KB)
[10:00:14.890] DEBUG: Writing file: v1_0_0/contract.yaml (4.2 KB)
[10:00:15.001] DEBUG: Writing file: v1_0_0/version.manifest.yaml (3.1 KB)
[10:00:15.112] DEBUG: Writing file: v1_0_0/models/model_postgres_writer_input.py (1.8 KB)
[10:00:15.223] DEBUG: Writing file: v1_0_0/models/model_postgres_writer_output.py (1.6 KB)
[10:00:15.334] DEBUG: Writing file: v1_0_0/models/model_postgres_writer_config.py (1.2 KB)
[10:00:15.445] DEBUG: Writing file: v1_0_0/enums/enum_postgres_writer_operation_type.py (0.8 KB)
[10:00:15.556] DEBUG: Writing file: v1_0_0/__init__.py (0.3 KB)
[10:00:15.667] DEBUG: Writing file: v1_0_0/models/__init__.py (0.4 KB)
[10:00:15.778] DEBUG: Writing file: v1_0_0/enums/__init__.py (0.2 KB)

[10:00:15.889] INFO: File writing completed
  Duration: 1.433s
  Files written: 11
  Total bytes: 45,678
  Directory: /Users/developer/projects/omniclaude/src/nodes/node_infrastructure_postgres_writer_effect

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 6: COMPILATION TESTING (OPTIONAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[10:00:16.000] INFO: Starting compilation testing

[10:00:16.111] DEBUG: Running mypy type check
  Command: poetry run mypy v1_0_0/node.py --strict

[10:00:26.222] INFO: MyPy completed
  Exit code: 0
  Errors: 0
  Warnings: 0
  Output: "Success: no issues found in 1 source file"

[10:00:26.333] DEBUG: Testing import
  Module: node_infrastructure_postgres_writer_effect.v1_0_0.node
  Class: NodePostgresWriterEffect

[10:00:26.444] INFO: Import test completed
  Success: true
  Class loaded: NodePostgresWriterEffect

[10:00:26.555] INFO: Compilation testing completed
  Duration: 10.555s
  MyPy passed: true
  Import passed: true

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PIPELINE COMPLETED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[10:00:26.666] INFO: Pipeline execution completed successfully

  Total duration: 26.666 seconds
  Correlation ID: 7c9e6679-7425-40de-944b-e07fc1f90ae7

  Stage Breakdown:
    Parsing:         0.678s (2.5%)
    Pre-validation:  0.667s (2.5%)
    Generation:      10.222s (38.3%)
    Post-validation: 1.455s (5.5%)
    Writing:         1.433s (5.4%)
    Compilation:     10.555s (39.6%)
    Overhead:        1.656s (6.2%)

  Output:
    Node type: EFFECT
    Service name: postgres_writer
    Domain: infrastructure
    Output path: /Users/developer/projects/omniclaude/src/nodes/node_infrastructure_postgres_writer_effect
    Files written: 11
    Validation passed: ✓
    Compilation passed: ✓

  Success: true
```

### Output Result

```python
result = {
    "success": True,
    "node_type": "EFFECT",
    "service_name": "postgres_writer",
    "domain": "infrastructure",
    "output_path": "/Users/developer/projects/omniclaude/src/nodes/node_infrastructure_postgres_writer_effect",
    "files_written": [
        "/Users/developer/projects/omniclaude/src/nodes/node_infrastructure_postgres_writer_effect/node.manifest.yaml",
        "/Users/developer/projects/omniclaude/src/nodes/node_infrastructure_postgres_writer_effect/v1_0_0/node.py",
        "/Users/developer/projects/omniclaude/src/nodes/node_infrastructure_postgres_writer_effect/v1_0_0/contract.yaml",
        # ... 8 more files
    ],
    "validation_passed": True,
    "compilation_passed": True,
    "duration_seconds": 26.666,
    "correlation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "stage_durations": {
        "parsing_ms": 678,
        "pre_validation_ms": 667,
        "generation_ms": 10222,
        "post_validation_ms": 1455,
        "writing_ms": 1433,
        "compilation_ms": 10555
    }
}
```

### Generated File Structure

```
node_infrastructure_postgres_writer_effect/
├── node.manifest.yaml
└── v1_0_0/
    ├── __init__.py
    ├── node.py
    ├── contract.yaml
    ├── version.manifest.yaml
    ├── models/
    │   ├── __init__.py
    │   ├── model_postgres_writer_input.py
    │   ├── model_postgres_writer_output.py
    │   └── model_postgres_writer_config.py
    └── enums/
        ├── __init__.py
        └── enum_postgres_writer_operation_type.py
```

---

## Validation Failure Flow

### Scenario: Missing Dependency (omnibase_core)

**Input**:
```python
result = pipeline.generate_from_prompt(
    prompt="Create EFFECT node for Redis cache operations",
    output_dir=Path("/tmp/test_output")
)
```

**Environment**: `omnibase_core` not installed or wrong version

### Execution Trace

```
┌─────────────────────────────────────────────────────────────────┐
│              PIPELINE EXECUTION WITH VALIDATION FAILURE          │
└─────────────────────────────────────────────────────────────────┘

[2025-10-21 11:00:00.000] INFO: Pipeline started
  Correlation ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 1: PROMPT PARSING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[11:00:00.123] INFO: Parsing completed
  Duration: 623ms

  Parsed Data:
    node_type: EFFECT
    service_name: redis_cache
    domain: infrastructure
    description: Redis cache operations
    confidence: 0.82

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 2: PRE-GENERATION VALIDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[11:00:00.234] INFO: Starting pre-generation validation

[11:00:00.345] DEBUG: Gate G1: Prompt completeness
  ✓ PASSED

[11:00:00.456] DEBUG: Gate G2: Node type valid
  ✓ PASSED

[11:00:00.567] DEBUG: Gate G3: Service name valid
  ✓ PASSED

[11:00:00.678] DEBUG: Gate G4: Critical imports exist
  ✗ Checking: omnibase_core.nodes.node_effect.NodeEffect
    ERROR: No module named 'omnibase_core'

[11:00:00.789] ERROR: Gate G4 FAILED
  Gate: Critical imports exist
  Error: ModuleNotFoundError: No module named 'omnibase_core'

[11:00:00.890] ERROR: Pre-validation failed
  Failed gate: G4
  Error code: MISSING_DEPENDENCY
  Duration: 656ms

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PIPELINE FAILED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[11:00:00.901] ERROR: Pipeline execution failed

  Failed stage: pre_validation
  Error code: MISSING_DEPENDENCY
  Error message: omnibase_core module not found

  Suggestions:
    - Run: poetry install omnibase_core
    - Check omnibase_core version >=2.0
    - Verify virtual environment is activated

  Rollback: not performed (no files written yet)

  Duration: 0.901 seconds
```

### Output Result

```python
result = {
    "success": False,
    "error": {
        "error_code": "MISSING_DEPENDENCY",
        "error_message": "omnibase_core module not found",
        "failed_stage": "pre_validation",
        "failed_gate": "G4",
        "error_context": {
            "import_path": "omnibase_core.nodes.node_effect",
            "exception": "ModuleNotFoundError: No module named 'omnibase_core'"
        },
        "suggestions": [
            "Run: poetry install omnibase_core",
            "Check omnibase_core version >=2.0",
            "Verify virtual environment is activated"
        ],
        "recovery_possible": True,
        "rollback_performed": False
    },
    "correlation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "duration_seconds": 0.901
}
```

---

## Generation Error Flow

### Scenario: Template Rendering Failure

**Input**:
```python
result = pipeline.generate_from_prompt(
    prompt="Create EFFECT node for payment processor",
    output_dir=Path("/tmp/test_output")
)
```

**Issue**: Template has missing placeholder

### Execution Trace

```
┌─────────────────────────────────────────────────────────────────┐
│            PIPELINE EXECUTION WITH GENERATION ERROR              │
└─────────────────────────────────────────────────────────────────┘

[2025-10-21 12:00:00.000] INFO: Pipeline started
  Correlation ID: 9876-5432-1098-7654

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 1: PROMPT PARSING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[12:00:00.567] INFO: Parsing completed
  Duration: 567ms

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 2: PRE-GENERATION VALIDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[12:00:01.234] INFO: Pre-validation completed
  All gates passed

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 3: CODE GENERATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[12:00:01.345] INFO: Starting code generation

[12:00:01.456] DEBUG: Loading EFFECT template

[12:00:01.567] DEBUG: Preparing template context
  Context: {
    MICROSERVICE_NAME: payment_processor,
    NODE_TYPE: EFFECT,
    ...
  }

[12:00:02.678] ERROR: Template rendering failed
  Template: effect_node_template.py
  Error: KeyError: 'MISSING_PLACEHOLDER'
  Line: 45

[12:00:02.789] ERROR: Code generation failed
  Error code: TEMPLATE_RENDER_ERROR
  Error: Missing placeholder in template: MISSING_PLACEHOLDER
  Duration: 1.444s

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PIPELINE FAILED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[12:00:02.890] ERROR: Pipeline execution failed

  Failed stage: generation
  Error code: TEMPLATE_RENDER_ERROR
  Error message: Missing placeholder in template: MISSING_PLACEHOLDER

  Error context:
    template: effect_node_template.py
    line: 45
    context_keys: [MICROSERVICE_NAME, NODE_TYPE, DOMAIN, ...]
    missing_key: MISSING_PLACEHOLDER

  Suggestions:
    - Check template file for placeholder correctness
    - Verify all placeholders are defined in context
    - Report issue to template maintainers

  Rollback: not performed (no files written yet)

  Duration: 2.890 seconds
```

### Output Result

```python
result = {
    "success": False,
    "error": {
        "error_code": "TEMPLATE_RENDER_ERROR",
        "error_message": "Missing placeholder in template: MISSING_PLACEHOLDER",
        "failed_stage": "generation",
        "error_context": {
            "template": "effect_node_template.py",
            "line": 45,
            "context_keys": ["MICROSERVICE_NAME", "NODE_TYPE", "DOMAIN"],
            "missing_key": "MISSING_PLACEHOLDER"
        },
        "suggestions": [
            "Check template file for placeholder correctness",
            "Verify all placeholders are defined in context",
            "Report issue to template maintainers"
        ],
        "recovery_possible": False,
        "rollback_performed": False
    },
    "correlation_id": "9876-5432-1098-7654",
    "duration_seconds": 2.890
}
```

---

## Rollback Example

### Scenario: File Write Failure (Disk Full)

**Input**:
```python
result = pipeline.generate_from_prompt(
    prompt="Create EFFECT node for file storage operations",
    output_dir=Path("/tmp/test_output")
)
```

**Issue**: Disk full during file writing

### Execution Trace

```
┌─────────────────────────────────────────────────────────────────┐
│          PIPELINE EXECUTION WITH ROLLBACK                        │
└─────────────────────────────────────────────────────────────────┘

[2025-10-21 13:00:00.000] INFO: Pipeline started
  Correlation ID: aabbccdd-1122-3344-5566-778899aabbcc

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGES 1-4: SUCCESS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[13:00:14.567] INFO: All validation passed, proceeding to file writing

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 5: FILE WRITING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[13:00:14.678] INFO: Starting file writing

[13:00:14.789] DEBUG: Creating directory structure
  ✓ Created: node_infrastructure_file_storage_effect/
  ✓ Created: node_infrastructure_file_storage_effect/v1_0_0/
  ✓ Created: node_infrastructure_file_storage_effect/v1_0_0/models/
  ✓ Created: node_infrastructure_file_storage_effect/v1_0_0/enums/

[13:00:14.890] DEBUG: Writing file: node.manifest.yaml
  ✓ Written: 2.3 KB

[13:00:15.001] DEBUG: Writing file: v1_0_0/node.py
  ✓ Written: 8.5 KB

[13:00:15.112] DEBUG: Writing file: v1_0_0/contract.yaml
  ✓ Written: 4.2 KB

[13:00:15.223] DEBUG: Writing file: v1_0_0/version.manifest.yaml
  ✗ FAILED: OSError: [Errno 28] No space left on device

[13:00:15.334] ERROR: File write failed
  File: v1_0_0/version.manifest.yaml
  Error: OSError: [Errno 28] No space left on device

[13:00:15.445] WARNING: Initiating rollback
  Files written so far: 3
  Files to delete: 3

[13:00:15.556] DEBUG: Rollback: Deleting node.manifest.yaml
[13:00:15.667] DEBUG: Rollback: Deleting v1_0_0/node.py
[13:00:15.778] DEBUG: Rollback: Deleting v1_0_0/contract.yaml

[13:00:15.889] DEBUG: Rollback: Deleting empty directories
  Deleted: node_infrastructure_file_storage_effect/v1_0_0/models/
  Deleted: node_infrastructure_file_storage_effect/v1_0_0/enums/
  Deleted: node_infrastructure_file_storage_effect/v1_0_0/
  Deleted: node_infrastructure_file_storage_effect/

[13:00:16.000] INFO: Rollback complete
  Files deleted: 3
  Directories removed: 4

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PIPELINE FAILED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[13:00:16.111] ERROR: Pipeline execution failed

  Failed stage: writing
  Error code: DISK_FULL
  Error message: No space left on device

  Suggestions:
    - Free up disk space
    - Use different output directory
    - Check disk quotas

  Rollback: PERFORMED
    Files deleted: 3
    Directories removed: 4
    Cleanup successful: ✓

  Duration: 16.111 seconds
```

### Output Result

```python
result = {
    "success": False,
    "error": {
        "error_code": "DISK_FULL",
        "error_message": "No space left on device",
        "failed_stage": "writing",
        "failed_file": "v1_0_0/version.manifest.yaml",
        "error_context": {
            "files_written_before_failure": 3,
            "total_files_planned": 11,
            "bytes_written": 15000,
            "error": "OSError: [Errno 28] No space left on device"
        },
        "suggestions": [
            "Free up disk space",
            "Use different output directory",
            "Check disk quotas"
        ],
        "recovery_possible": True,
        "rollback_performed": True,
        "rollback_details": {
            "files_deleted": 3,
            "directories_removed": 4,
            "cleanup_successful": True
        }
    },
    "correlation_id": "aabbccdd-1122-3344-5566-778899aabbcc",
    "duration_seconds": 16.111
}
```

---

## Edge Cases

### Edge Case 1: Ambiguous Prompt

**Input**:
```python
result = pipeline.generate_from_prompt(
    prompt="Create node for data",
    output_dir=Path("/tmp/test")
)
```

**Issue**: Prompt lacks specificity

**Result**:
```
[WARNING] Low confidence parsing
  Confidence: 0.42 (below 0.7 threshold)
  Defaults applied:
    - node_type: EFFECT (default)
    - service_name: data (generic)
    - domain: general
    - operations: [create, read, update, delete]

[INFO] Generation will proceed with defaults
  User should verify generated code matches intent
```

### Edge Case 2: Invalid Service Name

**Input**:
```python
result = pipeline.generate_from_prompt(
    prompt="Create EFFECT node for my-service-name",
    output_dir=Path("/tmp/test")
)
```

**Issue**: Service name has hyphens (invalid Python identifier)

**Result**:
```
[DEBUG] Sanitizing service name
  Original: my-service-name
  Sanitized: my_service_name
  Reason: Python identifiers cannot contain hyphens

[INFO] Using sanitized service name: my_service_name
```

### Edge Case 3: Unsupported Node Type (POC)

**Input**:
```python
result = pipeline.generate_from_prompt(
    prompt="Create COMPUTE node for price calculation",
    output_dir=Path("/tmp/test")
)
```

**Issue**: POC only supports EFFECT nodes

**Result**:
```
[ERROR] Validation failed
  Gate: G2 (Node type valid)
  Error: COMPUTE nodes not supported in POC
  Supported: [EFFECT]

[INFO] Suggestions:
  - Change prompt to request EFFECT node
  - Wait for Phase 2 for COMPUTE support
```

### Edge Case 4: Output Directory Already Exists

**Input**:
```python
result = pipeline.generate_from_prompt(
    prompt="Create EFFECT node for postgres_writer",
    output_dir=Path("/tmp/test")
)
# Run again with same prompt
```

**Issue**: Node directory already exists

**Result**:
```
[WARNING] Output directory exists
  Path: /tmp/test/node_infrastructure_postgres_writer_effect
  Action: Overwrite (default)

[INFO] Existing files will be overwritten
  Backup recommendation: Create backup before proceeding

[DEBUG] Overwriting existing files...
```

---

## Summary

### Success Indicators

✅ All validation gates passed
✅ Code generated successfully
✅ Files written to correct structure
✅ MyPy type check passes (0 errors)
✅ Import test succeeds
✅ ONEX naming conventions followed
✅ Total duration < 2 minutes

### Failure Patterns

❌ Missing dependencies → Pre-validation failure
❌ Template errors → Generation failure
❌ Disk issues → Writing failure with rollback
❌ Syntax errors → Post-validation failure
❌ Type errors → Compilation warning (not blocking)

### Recovery Actions

| Failure Type | Recovery Action | Automatic? |
|--------------|-----------------|------------|
| Missing dependency | Install omnibase_core | Manual |
| Invalid prompt | Rephrase prompt | Manual |
| Template error | Fix template or report bug | Manual |
| Disk full | Free space or change directory | Manual |
| Write failure | Rollback performed automatically | Automatic |
| Syntax error | Report bug (should not happen) | N/A |

---

**Document Version**: 1.0
**Status**: Complete
**Purpose**: Reference for expected pipeline behavior
