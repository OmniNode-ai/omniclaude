# Phase 4 Test Infrastructure - Developer Guide

## Quick Start

### Running All Phase 4 Tests

```bash
# Run all Phase 4 tests
poetry run pytest agents/tests/test_phase4_integration.py \
                  agents/tests/test_node_type_generation.py \
                  agents/tests/test_generation_validation.py \
                  agents/tests/test_generation_performance.py -v

# Run with coverage
poetry run pytest agents/tests/test_phase4_integration.py \
                  agents/tests/test_node_type_generation.py \
                  agents/tests/test_generation_validation.py \
                  agents/tests/test_generation_performance.py \
                  --cov=agents/lib/simple_prd_analyzer \
                  --cov=agents/lib/omninode_template_engine \
                  --cov-report=term-missing \
                  --cov-report=html
```

### Running Specific Test Suites

```bash
# Integration tests only
poetry run pytest agents/tests/test_phase4_integration.py -v

# Node type tests only
poetry run pytest agents/tests/test_node_type_generation.py -v

# Validation tests only
poetry run pytest agents/tests/test_generation_validation.py -v

# Performance tests only
poetry run pytest agents/tests/test_generation_performance.py -v
```

### Running Individual Tests

```bash
# Single test
poetry run pytest agents/tests/test_phase4_integration.py::TestPhase4Integration::test_full_generation_pipeline_effect_node -v

# All tests in a class
poetry run pytest agents/tests/test_node_type_generation.py::TestEffectNodeGeneration -v
```

## Test Infrastructure Overview

### Directory Structure

```
agents/tests/
├── fixtures/
│   ├── __init__.py
│   └── phase4_fixtures.py          # Sample PRDs, mock data, expected outputs
├── utils/
│   ├── __init__.py
│   └── generation_test_helpers.py  # Test utilities and validation helpers
├── test_phase4_integration.py      # Full pipeline integration tests
├── test_node_type_generation.py    # Node-specific generation tests
├── test_generation_validation.py   # ONEX compliance and validation tests
├── test_generation_performance.py  # Performance benchmarks
├── PHASE4_TEST_SUMMARY.md          # Test results and coverage report
└── PHASE4_TEST_README.md           # This file
```

## Test Fixtures

### Available Sample PRDs

The `phase4_fixtures.py` module provides comprehensive test data:

```python
from agents.tests.fixtures.phase4_fixtures import (
    # PRD Content
    EFFECT_NODE_PRD,
    COMPUTE_NODE_PRD,
    REDUCER_NODE_PRD,
    ORCHESTRATOR_NODE_PRD,

    # Pre-created Analysis Results
    EFFECT_ANALYSIS_RESULT,
    COMPUTE_ANALYSIS_RESULT,
    REDUCER_ANALYSIS_RESULT,
    ORCHESTRATOR_ANALYSIS_RESULT,

    # Organized by Node Type
    NODE_TYPE_FIXTURES,

    # Helper Function
    create_mock_analysis_result,
)
```

### Using Fixtures in Your Tests

```python
import pytest
from agents.tests.fixtures import EFFECT_NODE_PRD, EFFECT_ANALYSIS_RESULT

@pytest.mark.asyncio
async def test_my_generator():
    # Use pre-created analysis result
    analysis = EFFECT_ANALYSIS_RESULT

    # Or create custom mock
    from agents.tests.fixtures import create_mock_analysis_result
    custom_analysis = create_mock_analysis_result(
        EFFECT_NODE_PRD,
        "EFFECT",
        mixins=["MixinEventBus"],
        external_systems=["PostgreSQL"]
    )
```

## Test Utilities

### YAML Validation

```python
from agents.tests.utils import parse_generated_yaml, validate_contract_schema

# Parse YAML
contract = parse_generated_yaml(yaml_string)

# Validate schema
is_valid, errors = validate_contract_schema(contract)
```

### Python Code Validation

```python
from agents.tests.utils import (
    parse_generated_python,
    check_type_annotations,
    check_for_any_types,
)

# Parse Python code
tree, errors = parse_generated_python(code_string)

# Check type annotations
is_valid, violations = check_type_annotations(tree)

# Check for Any types (ONEX violation)
is_valid, violations = check_for_any_types(code_string)
```

### ONEX Naming Validation

```python
from agents.tests.utils import validate_onex_naming, validate_class_naming

# Validate filename
is_valid, error = validate_onex_naming("node_user_management_effect.py")

# Validate class name
is_valid, error = validate_class_naming("NodeUserManagementEffect", "node")
```

### Code Comparison

```python
from agents.tests.utils import compare_generated_code

# Compare code
diff = compare_generated_code(expected_code, actual_code)
if diff:
    print(diff)
```

## Writing New Tests

### Integration Test Template

```python
import pytest
import tempfile
from pathlib import Path
from agents.lib.simple_prd_analyzer import SimplePRDAnalyzer
from agents.lib.omninode_template_engine import OmniNodeTemplateEngine
from agents.tests.fixtures import EFFECT_NODE_PRD

@pytest.mark.asyncio
async def test_my_integration():
    """Test description"""
    # 1. Analyze PRD
    analyzer = SimplePRDAnalyzer()
    analysis = await analyzer.analyze_prd(EFFECT_NODE_PRD)

    # 2. Generate node
    engine = OmniNodeTemplateEngine()

    with tempfile.TemporaryDirectory() as temp_dir:
        result = await engine.generate_node(
            analysis_result=analysis,
            node_type="EFFECT",
            microservice_name="test_service",
            domain="test",
            output_directory=temp_dir
        )

        # 3. Validate
        assert result is not None
        assert Path(result["main_file"]).exists()
```

### Validation Test Template

```python
from agents.tests.utils import parse_generated_python, check_type_annotations

def test_my_validation():
    """Test validation logic"""
    code = """
    def my_function(param: str) -> int:
        return len(param)
    """

    tree, errors = parse_generated_python(code)
    assert tree is not None

    is_valid, violations = check_type_annotations(tree)
    assert is_valid
```

### Performance Test Template

```python
import pytest
import time

@pytest.mark.asyncio
async def test_my_performance():
    """Test performance benchmark"""
    start_time = time.time()

    # Your code here
    result = await my_function()

    end_time = time.time()
    latency_ms = (end_time - start_time) * 1000

    assert latency_ms < 1000, f"Too slow: {latency_ms}ms"
```

## Test Categories

### Integration Tests (`test_phase4_integration.py`)

**Purpose**: Test full pipeline from PRD to generated code

**Test Classes**:
- `TestPhase4Integration`: Main integration tests
- `TestGenerationArtifacts`: File and directory validation

**Key Tests**:
- `test_full_generation_pipeline_effect_node`: Complete EFFECT node generation
- `test_multiple_node_types_generation`: All four node types
- `test_concurrent_generation`: Parallel generation
- `test_error_handling_empty_prd`: Error scenarios

### Node Type Tests (`test_node_type_generation.py`)

**Purpose**: Test node-specific generation logic

**Test Classes**:
- `TestEffectNodeGeneration`: EFFECT node tests
- `TestComputeNodeGeneration`: COMPUTE node tests
- `TestReducerNodeGeneration`: REDUCER node tests
- `TestOrchestratorNodeGeneration`: ORCHESTRATOR node tests
- `TestNodeTypeComparison`: Cross-node validation

**Key Tests**:
- `test_effect_node_has_required_methods`: Method validation
- `test_compute_node_pure_computation`: COMPUTE characteristics
- `test_all_node_types_have_unique_characteristics`: Differentiation

### Validation Tests (`test_generation_validation.py`)

**Purpose**: Test ONEX compliance and code quality

**Test Classes**:
- `TestONEXCompliance`: Naming convention validation
- `TestTypeSafety`: Type annotation validation
- `TestContractValidation`: YAML schema validation
- `TestEnumSerialization`: Enum JSON serialization
- `TestMixinValidation`: Mixin compatibility
- `TestQualityMetrics`: Code quality checks

**Key Tests**:
- `test_onex_naming_valid_files`: File naming
- `test_contract_schema_validation_valid`: Contract YAML
- `test_generated_code_no_any_types`: Type safety

### Performance Tests (`test_generation_performance.py`)

**Purpose**: Performance benchmarks and optimization

**Test Classes**:
- `TestGenerationLatency`: Latency measurements
- `TestParallelGenerationSpeedup`: Parallel optimization
- `TestMemoryUsage`: Memory profiling
- `TestScalability`: Load testing
- `TestCachingOptimizations`: Cache effectiveness
- `TestBenchmarks`: Comprehensive benchmarks

**Key Tests**:
- `test_prd_analysis_latency`: Analysis speed
- `test_full_pipeline_latency`: End-to-end speed
- `test_parallel_vs_sequential_generation`: Speedup measurement

## Coverage Goals

### Target Coverage

- **Core Generators**: >90% line coverage
- **Test Utilities**: >85% line coverage
- **Integration Paths**: 100% critical path coverage

### Current Coverage

```
simple_prd_analyzer.py:         95%
omninode_template_engine.py:    97%
generation_test_helpers.py:     77%
phase4_fixtures.py:            100%
```

### Viewing Coverage Reports

```bash
# Generate HTML coverage report
poetry run pytest agents/tests/test_phase4_*.py \
    --cov=agents/lib/simple_prd_analyzer \
    --cov=agents/lib/omninode_template_engine \
    --cov-report=html

# Open report
open htmlcov/index.html
```

## Troubleshooting

### Common Issues

**Issue**: `ModuleNotFoundError: No module named 'omnibase_core'`

**Solution**: Run tests with poetry to use the correct virtual environment:
```bash
poetry run pytest agents/tests/test_phase4_integration.py
```

**Issue**: `ModuleNotFoundError: No module named 'psutil'`

**Solution**: Memory usage tests require psutil. Either install it or skip those tests:
```bash
poetry add psutil --group dev
# or
poetry run pytest -k "not memory_usage"
```

**Issue**: Tests are slow

**Solution**: Run tests in parallel:
```bash
poetry run pytest agents/tests/test_phase4_*.py -n auto
```

### Test Failures

**Expected Failures**: Some tests may fail due to:
- Metadata format differences (not critical)
- Method naming conventions evolving
- Optional features not yet implemented

**Skipped Tests**: Some tests are skipped when:
- Features are not yet enforced (e.g., strict ONEX naming)
- Performance targets are aspirational

## Best Practices

### DO

✅ Use fixtures from `phase4_fixtures.py` for consistency
✅ Use utilities from `generation_test_helpers.py` for validation
✅ Write descriptive test names and docstrings
✅ Test both happy paths and error cases
✅ Use `tempfile.TemporaryDirectory()` for file operations
✅ Clean up resources in tests

### DON'T

❌ Hardcode expected outputs (use fixtures)
❌ Skip error handling tests
❌ Ignore performance benchmarks
❌ Leave TODO comments without tracking
❌ Test implementation details (test behavior)

## Next Steps

1. **Fix Minor Test Failures**: Address the 8 failing tests
2. **Add Missing Generators**: Contract, Model, and Enum generators
3. **Increase Utility Coverage**: Get test helpers to >90%
4. **CI/CD Integration**: Add to continuous integration pipeline
5. **Performance Baselines**: Establish regression detection

## Resources

- **Test Summary**: `PHASE4_TEST_SUMMARY.md`
- **Fixtures**: `agents/tests/fixtures/phase4_fixtures.py`
- **Utilities**: `agents/tests/utils/generation_test_helpers.py`

---

*Last Updated: 2025-10-15*
*Test Infrastructure Version: 1.0*
