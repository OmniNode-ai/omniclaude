# Generation Pipeline - Autonomous Node Generation POC

**Phase**: 1.3 Implementation (POC)
**Status**: Complete - Ready for Integration
**Version**: 1.0.0

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Pipeline Stages](#pipeline-stages)
4. [Validation Gates](#validation-gates)
5. [Usage](#usage)
6. [Configuration](#configuration)
7. [Error Handling](#error-handling)
8. [Performance](#performance)
9. [Testing](#testing)
10. [Integration](#integration)

---

## Overview

The Generation Pipeline orchestrates autonomous node generation from natural language prompts. It implements a robust 6-stage pipeline with 14 validation gates to ensure production-quality ONEX-compliant code generation.

### Key Features

- **6-Stage Pipeline**: Parsing → Pre-Validation → Generation → Post-Validation → Writing → Compilation
- **14 Validation Gates**: Comprehensive quality checks at each stage
- **ONEX Compliance**: Strict adherence to ONEX architectural patterns
- **Fail-Fast**: Blocking gates halt execution on critical failures
- **Rollback Support**: Automatic cleanup on pipeline failures
- **Performance Optimized**: Target <40s for successful generation

### Design Principles

1. **KISS**: Simple, straightforward implementation
2. **Fail Fast**: Validate early, fail explicitly with clear messages
3. **Reuse**: Leverages existing `OmniNodeTemplateEngine`
4. **Testable**: Every stage independently testable
5. **Observable**: Comprehensive logging and progress tracking

---

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     GenerationPipeline                          │
│  - Orchestrates all stages                                      │
│  - Handles errors and rollback                                  │
│  - Emits progress events                                        │
└─────────────────────────────────────────────────────────────────┘
         │
         │  uses
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   PRDAnalyzer                             │
│  - Extract metadata from natural language                       │
│  - Keyword-based heuristics (POC)                               │
└─────────────────────────────────────────────────────────────────┘
         │
         │  uses
         ▼
┌─────────────────────────────────────────────────────────────────┐
│           OmniNodeTemplateEngine (EXISTING)                      │
│  - Load and cache templates                                     │
│  - Render with context                                          │
│  - Generate additional files                                    │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
Natural Language Prompt
   ↓
Stage 1: Prompt Parsing (5s)
   ├─ G7: Prompt completeness (WARNING)
   └─ G8: Context completeness (WARNING)
   ↓
Stage 2: Pre-Generation Validation (2s)
   ├─ G1: Prompt completeness (BLOCKING)
   ├─ G2: Node type valid (BLOCKING)
   ├─ G3: Service name valid (BLOCKING)
   ├─ G4: Critical imports exist (BLOCKING)
   ├─ G5: Templates available (BLOCKING)
   └─ G6: Output directory writable (BLOCKING)
   ↓
Stage 3: Code Generation (10-15s)
   ↓
Stage 4: Post-Generation Validation (5s)
   ├─ G9: Python syntax valid (BLOCKING)
   ├─ G10: ONEX naming convention (BLOCKING)
   ├─ G11: Import resolution (BLOCKING)
   └─ G12: Pydantic model structure (BLOCKING)
   ↓
Stage 5: File Writing (3s)
   ↓
Stage 6: Compilation Testing (10s) [OPTIONAL]
   ├─ G13: MyPy type checking (WARNING)
   └─ G14: Import test (WARNING)
   ↓
PipelineResult (success/failure + metadata)
```

---

## Pipeline Stages

### Stage 1: Prompt Parsing

**Duration**: ~5 seconds
**Purpose**: Extract structured data from natural language prompt

**Processing**:
1. Convert prompt to PRD format
2. Analyze PRD using `PRDAnalyzer`
3. Extract node type, service name, domain
4. Calculate confidence score

**Validation Gates**:
- **G7**: Prompt completeness check (WARNING)
- **G8**: Context has expected fields (WARNING)

**Output**:
```python
{
    "parsed_data": {
        "node_type": "EFFECT",
        "service_name": "postgres_writer",
        "domain": "infrastructure",
        "description": "PostgreSQL database write operations",
        "operations": ["create", "update", "delete"],
        "features": ["Feature 1", "Feature 2", "Feature 3"],
        "confidence": 0.85
    },
    "analysis_result": PRDAnalysisResult(...)
}
```

---

### Stage 1.5: Intelligence Gathering (NEW!)

**Duration**: ~3-5 seconds
**Purpose**: Analyze and gather best practices for the node being generated

The pipeline now includes an intelligence gathering stage that analyzes:
- **Best practices** for the node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
- **Domain-specific patterns** (database, API, file, etc.)
- **Common operations** and error scenarios
- **Performance targets** and optimization strategies

**Intelligence Sources**:
1. **Built-in Pattern Library**: Curated best practices for each node type
2. **RAG Integration** (optional): Query Archon MCP for contextual patterns
3. **Codebase Analysis**: Learn from existing production nodes

**Results Injected Into Generated Code**:
- ✅ Production-ready best practices in docstrings
- ✅ Pattern-specific code stubs (connection pooling, circuit breaker, etc.)
- ✅ Domain-appropriate error handling
- ✅ Performance optimization TODOs

**Intelligence Context Structure**:
```python
{
    "node_type_patterns": List[str],        # General patterns for node type
    "domain_best_practices": List[str],     # Domain-specific patterns
    "common_operations": List[str],         # Expected operations (e.g., CRUD)
    "required_mixins": List[str],           # Mixins to include
    "performance_targets": Dict[str, Any],  # Performance expectations
    "error_scenarios": List[str]            # Common error cases
}
```

**Example Intelligence for Database EFFECT Node**:
```python
intelligence_context = {
    "node_type_patterns": [
        "Implement connection pooling for resource management",
        "Use circuit breaker pattern for resilience",
        "Apply retry logic with exponential backoff"
    ],
    "domain_best_practices": [
        "Use prepared statements to prevent SQL injection",
        "Wrap operations in transactions for ACID compliance",
        "Implement connection timeout and health checks"
    ],
    "common_operations": ["create", "read", "update", "delete"],
    "required_mixins": ["MixinRetry", "MixinCircuitBreaker"],
    "performance_targets": {"max_latency_ms": 100},
    "error_scenarios": ["connection_timeout", "deadlock", "constraint_violation"]
}
```

**No Validation Gates** (intelligence gathering is informational only)

---

### Stage 2: Pre-Generation Validation

**Duration**: ~2 seconds
**Purpose**: Validate environment before code generation

**Validation Gates** (ALL BLOCKING):

#### G1: Prompt Completeness
- Checks: `node_type`, `service_name`, `domain`, `description` all present
- Failure: Missing required fields
- Suggestion: Provide complete prompt information

#### G2: Node Type Valid
- Checks: Node type is supported (POC: EFFECT only)
- Failure: Invalid or unsupported node type
- Suggestion: Use EFFECT for POC

#### G3: Service Name Valid
- Checks: Service name is valid Python identifier (snake_case)
- Failure: Invalid naming (PascalCase, numbers at start, etc.)
- Suggestion: Use snake_case Python identifier

#### G4: Critical Imports Exist
- Checks: All required omnibase_core imports are available
- Critical Imports:
  - `omnibase_core.nodes.node_effect.NodeEffect`
  - `omnibase_core.errors.model_onex_error.ModelOnexError`
  - `omnibase_core.errors.error_codes.EnumCoreErrorCode`
  - `omnibase_core.models.container.model_onex_container.ModelONEXContainer`
- Failure: Missing critical imports
- Suggestion: Run `poetry install omnibase_core`

#### G5: Templates Available
- Checks: Template exists for node type
- Failure: Template not found
- Suggestion: Check template directory

#### G6: Output Directory Writable
- Checks: Output directory exists and is writable
- Failure: Cannot write to output directory
- Suggestion: Check permissions or create directory

---

### Stage 3: Code Generation

**Duration**: ~10-15 seconds
**Purpose**: Generate node implementation from templates

**Processing**:
1. Prepare context for template rendering
2. Load template for node type
3. Render main node file
4. Generate additional files (models, enums, contracts, manifests)
5. Write files to output directory

**Generated Files**:
```
node_infrastructure_postgres_writer_effect/
├── node.manifest.yaml                    # Node-level metadata
└── v1_0_0/                               # Version directory
    ├── __init__.py                       # Version exports
    ├── node.py                           # Main node implementation
    ├── contract.yaml                     # ONEX contract definition
    ├── version.manifest.yaml             # Version-specific metadata
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

**No Validation Gates** (gates G7-G8 are in Stage 1)

---

### Stage 4: Post-Generation Validation

**Duration**: ~5 seconds
**Purpose**: Validate generated code quality

**Validation Gates** (ALL BLOCKING):

#### G9: Python Syntax Valid
- Checks: Generated code has valid Python syntax via AST parsing
- Failure: Syntax errors in generated code
- Suggestion: Report bug in template engine

#### G10: ONEX Naming Convention
- Checks: Node class follows suffix-based naming (e.g., `NodeMyServiceEffect`, NOT `EffectMyService`)
- Pattern: `class Node<Name><Type>(...)`
- Failure: Incorrect naming or missing node class
- Suggestion: Class name must end with node type

#### G11: Import Resolution
- Checks: All imports are resolvable (static check)
- Failure: Old/wrong import paths detected
- Example: `omnibase_core.core.node_effect` (WRONG) vs `omnibase_core.nodes.node_effect` (CORRECT)
- Suggestion: Update import paths

#### G12: Pydantic Model Structure
- Checks: Pydantic models are well-formed
- Failures:
  - Old Pydantic v1 patterns (`.dict()` instead of `.model_dump()`)
  - Missing `Config` class or `model_config`
- Suggestion: Use Pydantic v2 patterns

---

### Stage 5: File Writing

**Duration**: ~3 seconds
**Purpose**: Write generated files to filesystem

**Processing**:
1. Verify output directory exists
2. Verify all files were written by template engine
3. Track written files for potential rollback
4. Return file paths

**Features**:
- Files are already written by template engine in Stage 3
- This stage verifies successful writes
- Tracks files for rollback on later failures

---

### Stage 6: Compilation Testing (Optional)

**Duration**: ~10 seconds
**Purpose**: Verify generated code compiles

**Validation Gates** (ALL WARNING - non-blocking):

#### G13: MyPy Type Checking
- Checks: `poetry run mypy <node_file>` passes with 0 errors
- Failure: Type errors detected
- Impact: WARNING (does not fail pipeline)
- Timeout: 30 seconds

#### G14: Import Test
- Checks: Generated node can be imported successfully
- Process:
  1. Add output directory to Python path
  2. Import node module
  3. Verify node class exists
- Failure: Import errors
- Impact: WARNING (does not fail pipeline)

**Configuration**:
- Enabled by default
- Can be disabled: `GenerationPipeline(enable_compilation_testing=False)`

---

## Validation Gates

### Gate Hierarchy

```
BLOCKING (pipeline fails) vs WARNING (continue with notes)

Pre-Generation (6 BLOCKING):
  ✓ G1: Prompt has minimum required info
  ✓ G2: Node type is valid (EFFECT only for POC)
  ✓ G3: Service name is valid identifier
  ✓ G4: Critical imports exist in omnibase_core
  ✓ G5: Templates are available
  ✓ G6: Output directory is writable

Parsing (2 WARNING):
  ⚠ G7: Prompt completeness check
  ⚠ G8: Context has expected fields

Post-Generation (4 BLOCKING):
  ✓ G9: Generated code has valid Python syntax
  ✓ G10: Node class follows naming convention (suffix-based)
  ✓ G11: All imports are resolvable
  ✓ G12: Pydantic models are well-formed

Compilation (2 WARNING):
  ⚠ G13: MyPy type checking passes (0 errors)
  ⚠ G14: Import test succeeds
```

### Gate Performance Target

- **Target**: <200ms per gate
- **Actual**: Most gates <50ms, import checks ~100ms
- **Total validation overhead**: <2s across all 14 gates

---

## Usage

### Basic Usage

```python
import asyncio
from agents.lib.generation_pipeline import GenerationPipeline

async def main():
    # Initialize pipeline
    pipeline = GenerationPipeline(enable_compilation_testing=True)

    # Execute generation
    result = await pipeline.execute(
        prompt="Create EFFECT node for PostgreSQL database write operations",
        output_directory="/path/to/output"
    )

    # Check result
    if result.success:
        print(f"✅ Generation successful!")
        print(f"   Node Type: {result.node_type}")
        print(f"   Service: {result.service_name}")
        print(f"   Files: {len(result.generated_files)}")
        print(f"   Duration: {result.duration_seconds:.2f}s")
    else:
        print(f"❌ Generation failed: {result.error_summary}")
        for gate in result.get_failed_gates():
            print(f"   - {gate.gate_id}: {gate.message}")

asyncio.run(main())
```

### Advanced Usage

```python
from agents.lib.generation_pipeline import GenerationPipeline
from agents.lib.omninode_template_engine import OmniNodeTemplateEngine
from uuid import uuid4

async def advanced_generation():
    # Create custom template engine with caching
    template_engine = OmniNodeTemplateEngine(enable_cache=True)

    # Initialize pipeline with custom engine
    pipeline = GenerationPipeline(
        template_engine=template_engine,
        enable_compilation_testing=False  # Disable for faster execution
    )

    # Execute with correlation ID for tracking
    correlation_id = uuid4()
    result = await pipeline.execute(
        prompt="Create EFFECT node for Redis caching operations",
        output_directory="/path/to/output",
        correlation_id=correlation_id
    )

    # Detailed result analysis
    print(result.to_summary())

    # Stage-by-stage breakdown
    for stage in result.stages:
        print(f"\nStage: {stage.stage_name}")
        print(f"  Status: {stage.status}")
        print(f"  Duration: {stage.duration_ms}ms")
        print(f"  Gates: {len(stage.validation_gates)}")

        for gate in stage.validation_gates:
            status_icon = "✅" if gate.status == "pass" else "⚠️" if gate.status == "warning" else "❌"
            print(f"    {status_icon} {gate.gate_id}: {gate.name} ({gate.duration_ms}ms)")
```

### Prompt Examples

**Good Prompts**:
```
✅ "Create EFFECT node for PostgreSQL database write operations"
✅ "Build EFFECT node for Redis cache management with TTL support"
✅ "Generate EFFECT node for Kafka message publishing to user-events topic"
```

**Poor Prompts** (will trigger warnings):
```
⚠️ "node" (too short, lacks context)
⚠️ "database" (missing operation details)
⚠️ "create something" (vague, lacks specifics)
```

---

## Configuration

### Pipeline Configuration

```python
pipeline = GenerationPipeline(
    template_engine=None,  # Use default or provide custom
    enable_compilation_testing=True  # Enable Stage 6
)
```

### Template Engine Configuration

```python
from agents.lib.omninode_template_engine import OmniNodeTemplateEngine

template_engine = OmniNodeTemplateEngine(
    enable_cache=True  # Enable template caching for 50% perf improvement
)

# Get cache statistics
stats = template_engine.get_cache_stats()
print(f"Cache hits: {stats['hits']}")
print(f"Cache hit rate: {stats['hit_rate']:.1%}")
```

### Environment Variables

No environment variables required for basic operation. Template engine uses configuration from:
```python
from agents.lib.version_config import get_config

config = get_config()
# config.template_directory
# config.postgres_host, etc.
```

---

## Error Handling

### Error Types

**Level 1: User Errors** (fixable by user):
- `InvalidPromptError`: Prompt too short/vague (G7)
- `InvalidNodeTypeError`: Unsupported node type (G2)
- `InvalidServiceNameError`: Invalid Python identifier (G3)

**Level 2: Environment Errors** (fixable by setup):
- `MissingDependencyError`: omnibase_core not installed (G4)
- `TemplateNotFoundError`: Template files missing (G5)
- `OutputDirectoryError`: Cannot write to output (G6)

**Level 3: Generation Errors** (bugs in pipeline):
- `SyntaxError`: Generated code invalid (G9)
- `NamingConventionError`: ONEX naming violated (G10)
- `ImportError`: Import paths incorrect (G11)

**Level 4: System Errors** (infrastructure issues):
- `TimeoutError`: Compilation testing timeout
- `PermissionError`: Filesystem permissions

### Error Recovery

```python
result = await pipeline.execute(prompt, output_dir)

if not result.success:
    # Get failed gates
    failed_gates = result.get_failed_gates()

    for gate in failed_gates:
        if gate.gate_id == "G2":
            print("❌ Invalid node type. POC supports EFFECT only.")
        elif gate.gate_id == "G4":
            print("❌ Missing dependencies. Run: poetry install omnibase_core")
        elif gate.gate_id == "G9":
            print(f"❌ Syntax error: {gate.message}")
            print("   This is a bug in the template engine. Please report.")

    # Check if rollback occurred
    if result.error_summary:
        print(f"Rollback triggered: {result.error_summary}")
```

### Rollback Mechanism

When a pipeline stage fails:
1. All written files are tracked in `pipeline.written_files`
2. On failure, `pipeline._rollback()` is called automatically
3. All tracked files are deleted
4. Temporary files are cleaned up
5. Empty directories are removed

**Note**: Rollback is best-effort. Manual cleanup may be needed if process is terminated.

---

## Performance

### Performance Targets

| Stage | Target | Typical |
|-------|--------|---------|
| Prompt Parsing | <5s | ~3s |
| Pre-Validation | <2s | ~1s |
| Code Generation | <15s | ~10s |
| Post-Validation | <5s | ~3s |
| File Writing | <3s | ~1s |
| Compilation (optional) | <10s | ~8s |
| **Total** | **<40s** | **~26s** |

### Validation Gate Performance

| Gate | Target | Typical |
|------|--------|---------|
| G1-G6 (Pre) | <200ms each | <50ms |
| G7-G8 (Parse) | <200ms each | <30ms |
| G9 (Syntax) | <200ms | ~100ms |
| G10 (Naming) | <200ms | ~30ms |
| G11 (Imports) | <200ms | ~50ms |
| G12 (Models) | <200ms | ~100ms |
| G13 (MyPy) | N/A (WARNING) | ~8s |
| G14 (Import Test) | N/A (WARNING) | ~500ms |

### Optimization Tips

1. **Disable Compilation Testing** for faster iteration:
   ```python
   pipeline = GenerationPipeline(enable_compilation_testing=False)
   # Saves ~10s per run
   ```

2. **Enable Template Caching**:
   ```python
   template_engine = OmniNodeTemplateEngine(enable_cache=True)
   # 50% improvement on repeated generations
   ```

3. **Reuse Pipeline Instance**:
   ```python
   pipeline = GenerationPipeline()
   # Reuse for multiple generations
   for prompt in prompts:
       result = await pipeline.execute(prompt, output_dir)
   ```

---

## Testing

### Running Tests

```bash
# Run all tests
pytest tests/test_generation_pipeline.py -v

# Run specific test categories
pytest tests/test_generation_pipeline.py -k "gate" -v        # Validation gates
pytest tests/test_generation_pipeline.py -k "stage" -v       # Pipeline stages
pytest tests/test_generation_pipeline.py -k "integration" -v # Integration tests

# Run with coverage
pytest tests/test_generation_pipeline.py --cov=agents.lib.generation_pipeline --cov-report=html
```

### Test Coverage

- **Unit Tests**: 50+ tests covering all validation gates and helper methods
- **Integration Tests**: End-to-end pipeline execution with mocks
- **Performance Tests**: Validation gate and pipeline performance benchmarks
- **Coverage**: >90% code coverage

### Test Categories

1. **Pipeline Models Tests**: Pydantic model validation
2. **Validation Gates Tests**: All 14 gates tested individually
3. **Helper Methods Tests**: Prompt parsing, domain extraction, etc.
4. **Stage Tests**: Each stage tested independently
5. **Integration Tests**: Full pipeline execution
6. **Performance Tests**: Timing and efficiency benchmarks

---

## Integration

### Integration with Agent Framework

```python
from agents.lib.generation_pipeline import GenerationPipeline

class AgentNodeGenerator:
    def __init__(self):
        self.pipeline = GenerationPipeline()

    async def generate_from_ticket(self, ticket_id: str):
        # Fetch ticket description
        ticket = await self.fetch_ticket(ticket_id)

        # Generate node
        result = await self.pipeline.execute(
            prompt=ticket.description,
            output_directory=f"./generated/ticket_{ticket_id}"
        )

        # Log result
        if result.success:
            await self.log_success(ticket_id, result)
        else:
            await self.log_failure(ticket_id, result)

        return result
```

### Integration with Archon MCP

```python
from agents.lib.generation_pipeline import GenerationPipeline

async def archon_node_generation_endpoint(request: dict):
    pipeline = GenerationPipeline()

    result = await pipeline.execute(
        prompt=request["prompt"],
        output_directory=request["output_dir"],
        correlation_id=request.get("correlation_id")
    )

    return {
        "success": result.success,
        "node_type": result.node_type,
        "service_name": result.service_name,
        "files": result.generated_files,
        "duration_seconds": result.duration_seconds,
        "validation_passed": result.validation_passed,
        "compilation_passed": result.compilation_passed,
        "error_summary": result.error_summary
    }
```

### Monitoring & Observability

```python
import logging
from agents.lib.generation_pipeline import GenerationPipeline

# Configure logging
logging.basicConfig(level=logging.INFO)

pipeline = GenerationPipeline()

result = await pipeline.execute(prompt, output_dir)

# Log metrics
logger.info(f"Pipeline completed: {result.status}")
logger.info(f"Duration: {result.duration_seconds:.2f}s")
logger.info(f"Stages: {len(result.stages)}")
logger.info(f"Files: {len(result.generated_files)}")

# Track failed gates
for gate in result.get_failed_gates():
    logger.error(f"Gate {gate.gate_id} failed: {gate.message}")

# Track warning gates
for gate in result.get_warning_gates():
    logger.warning(f"Gate {gate.gate_id} warning: {gate.message}")
```

---

## Appendix A: Validation Gate Reference

### Complete Gate Specifications

| Gate ID | Name | Type | Stage | Target (ms) | Description |
|---------|------|------|-------|-------------|-------------|
| G1 | Prompt Completeness | BLOCKING | 2 | <50 | All required fields present |
| G2 | Node Type Valid | BLOCKING | 2 | <50 | Node type supported (EFFECT) |
| G3 | Service Name Valid | BLOCKING | 2 | <50 | Valid Python identifier |
| G4 | Critical Imports Exist | BLOCKING | 2 | <100 | omnibase_core available |
| G5 | Templates Available | BLOCKING | 2 | <50 | Template for node type exists |
| G6 | Output Directory Writable | BLOCKING | 2 | <50 | Can write to output |
| G7 | Prompt Completeness Check | WARNING | 1 | <30 | Prompt has sufficient info |
| G8 | Context Completeness | WARNING | 1 | <30 | Context has expected fields |
| G9 | Python Syntax Valid | BLOCKING | 4 | <100 | AST parsing succeeds |
| G10 | ONEX Naming Convention | BLOCKING | 4 | <50 | Suffix-based naming |
| G11 | Import Resolution | BLOCKING | 4 | <50 | No old import paths |
| G12 | Pydantic Model Structure | BLOCKING | 4 | <100 | Pydantic v2 patterns |
| G13 | MyPy Type Checking | WARNING | 6 | N/A | MyPy passes (optional) |
| G14 | Import Test | WARNING | 6 | ~500 | Node can be imported |

---

## Appendix B: Generated File Structure

### Complete Directory Layout

```
node_{domain}_{service_name}_{type}/
├── node.manifest.yaml                    # Tier 2: Node-level metadata
│   ├── schema_version
│   ├── name
│   ├── uuid
│   ├── author
│   ├── created_at
│   ├── description
│   ├── capabilities
│   ├── protocols_supported
│   ├── dependencies
│   ├── x_extensions (version management)
│   ├── execution_mode
│   ├── testing
│   ├── security_context
│   └── logging_config
│
└── v1_0_0/                               # Version directory
    ├── __init__.py                       # Version exports
    ├── node.py                           # Main node implementation
    │   ├── Imports from omnibase_core
    │   ├── Node class (suffix-based naming)
    │   ├── execute_<type> method
    │   └── Error handling with ModelOnexError
    │
    ├── contract.yaml                     # Tier 1: ONEX contract
    │   ├── contract_version
    │   ├── node_name
    │   ├── node_type
    │   ├── input_model
    │   ├── output_model
    │   ├── actions
    │   ├── dependencies
    │   ├── performance
    │   ├── event_type
    │   ├── subcontracts
    │   └── validation_rules
    │
    ├── version.manifest.yaml             # Tier 3: Version metadata
    │   ├── version
    │   ├── status
    │   ├── release_date
    │   ├── implementation
    │   ├── validation
    │   ├── deployment
    │   ├── security
    │   ├── api_surface
    │   └── quality_metrics
    │
    ├── models/
    │   ├── __init__.py
    │   ├── model_{service}_input.py      # Input model (Pydantic)
    │   ├── model_{service}_output.py     # Output model (Pydantic)
    │   ├── model_{service}_config.py     # Config model (Pydantic)
    │   └── model_{service}_{type}_contract.py  # Contract model
    │
    └── enums/
        ├── __init__.py
        └── enum_{service}_operation_type.py  # Operation enum
```

---

## Document Version

- **Version**: 1.0.0
- **Status**: Complete
- **Last Updated**: 2025-10-21
- **Next Review**: After POC validation
