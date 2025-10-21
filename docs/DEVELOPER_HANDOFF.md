# Developer Handoff: Autonomous Node Generation Platform

**Document Type**: Developer Guide & Practical Reference
**Audience**: Developers using, maintaining, or extending the platform
**Last Updated**: 2025-10-21
**Version**: 1.0.0

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [System Overview](#system-overview)
3. [How to Use the Platform](#how-to-use-the-platform)
4. [Code Organization](#code-organization)
5. [Testing Guide](#testing-guide)
6. [Troubleshooting](#troubleshooting)
7. [Extension Guide](#extension-guide)
8. [Deployment Guide](#deployment-guide)
9. [Maintenance Guide](#maintenance-guide)
10. [FAQ](#faq)

---

## Quick Start

### Prerequisites

```bash
# Required
- Python 3.12+
- Poetry 1.8+
- omnibase_core (latest)

# Optional
- mypy (type checking)
- ruff (linting)
```

### Installation

```bash
# 1. Clone repository
cd /Volumes/PRO-G40/Code/omniclaude

# 2. Install dependencies
poetry install

# 3. Verify installation
poetry run python cli/generate_node.py --help

# Expected output:
# usage: generate_node.py [-h] [--interactive] [--prompt PROMPT] ...
```

### Generate Your First Node (30 seconds)

```bash
# Direct mode (recommended for automation)
poetry run python cli/generate_node.py \
    "Create EFFECT node for PostgreSQL writes" \
    --output ./output

# Interactive mode (recommended for beginners)
poetry run python cli/generate_node.py --interactive

# Expected output (40 seconds later):
# ✅ Node generated successfully!
# 📁 Output: ./output/node_infrastructure_postgres_writer_effect/
# 📄 Files: 12 files created
# ⚡ Duration: 40.2 seconds
```

### Verify Generated Node

```bash
# Check generated files
ls -la ./output/node_infrastructure_postgres_writer_effect/

# Expected structure:
# node.manifest.yaml
# v1_0_0/
#   ├── node.py
#   ├── contract.yaml
#   ├── models/
#   └── enums/

# Run type checking
poetry run mypy ./output/node_infrastructure_postgres_writer_effect/v1_0_0/node.py

# Expected: Success: no issues found
```

---

## System Overview

### Architecture at a Glance

```
User Input → CLI → Pipeline → Contract Builder → Code Generation → Files

Responsibilities:
├─ CLI: User interaction, argument parsing
├─ Pipeline: Orchestration, error handling
├─ Contract Builder: Type-safe Pydantic contracts
├─ Code Generation: AST-based Python code
└─ File Writer: Atomic file operations
```

### Key Components

| Component | File | LOC | Purpose |
|-----------|------|-----|---------|
| **CLI** | `cli/generate_node.py` | 358 | User interface |
| **Pipeline** | `agents/lib/generation_pipeline.py` | 1,231 | Orchestration |
| **Parser** | `agents/lib/prompt_parser.py` | 480 | NLP parsing |
| **Builders** | `agents/lib/generation/contract_builder_*.py` | ~1,357 | Contracts |
| **Utilities** | `agents/lib/generation/*.py` | ~1,780 | Code gen |
| **Validator** | `agents/lib/compatibility_validator.py` | 858 | Validation |
| **Writer** | `tools/node_gen/file_writer.py` | ~300 | File I/O |

### Data Flow

```
Natural Language → ParsedPromptData → ModelContract → AST → Python Code → Files
```

---

## How to Use the Platform

### Usage Mode 1: Direct CLI

**Best for**: Automation, scripts, CI/CD pipelines

```bash
# Basic usage
poetry run python cli/generate_node.py \
    "Create EFFECT node for Redis cache operations"

# With options
poetry run python cli/generate_node.py \
    --prompt "Create COMPUTE node for data transformation" \
    --output ./custom_output \
    --debug \
    --no-compile

# Options explained:
# --prompt: Natural language description
# --output: Output directory (default: ./output)
# --debug: Verbose logging
# --no-compile: Skip mypy type checking
```

### Usage Mode 2: Interactive Mode

**Best for**: Learning, exploration, manual generation

```bash
poetry run python cli/generate_node.py --interactive

# You'll be prompted:
# Enter prompt: Create REDUCER node for event aggregation
# Output directory [./output]:
# Compile check? [Y/n]:
```

### Usage Mode 3: Programmatic API

**Best for**: Integration with other tools

```python
from agents.lib.generation_pipeline import GenerationPipeline
from pathlib import Path

# Initialize pipeline
pipeline = GenerationPipeline(compile_check=True)

# Generate node
result = await pipeline.execute(
    prompt="Create EFFECT node for S3 uploads",
    output_directory=str(Path("./output"))
)

# Check result
if result.success:
    print(f"✅ Generated: {result.node_path}")
    print(f"📄 Files: {len(result.files_written)}")
else:
    print(f"❌ Failed: {result.error_message}")
```

### Prompt Engineering Tips

**Good Prompts** (clear, specific):
```
✅ "Create EFFECT node for PostgreSQL database writes"
✅ "Create COMPUTE node for JSON data transformation"
✅ "Create REDUCER node for user event aggregation"
✅ "Create ORCHESTRATOR node for payment workflow"
```

**Bad Prompts** (vague, ambiguous):
```
❌ "Create node"
❌ "I need something for data"
❌ "Help me with databases"
```

**Prompt Template**:
```
Create <NODE_TYPE> node for <SERVICE_PURPOSE>

Where:
- NODE_TYPE: EFFECT | COMPUTE | REDUCER | ORCHESTRATOR
- SERVICE_PURPOSE: Clear description of what the node does
```

---

## Code Organization

### Directory Structure

```
omniclaude/
├── agents/
│   ├── lib/
│   │   ├── generation_pipeline.py          # Main orchestrator
│   │   ├── prompt_parser.py                # NLP parsing
│   │   ├── compatibility_validator.py      # Validation
│   │   └── generation/                     # Code generation
│   │       ├── __init__.py
│   │       ├── contract_builder.py         # Base builder
│   │       ├── contract_builder_*.py       # Specialized builders
│   │       ├── contract_builder_factory.py # Factory pattern
│   │       ├── contract_validator.py       # Contract validation
│   │       ├── ast_builder.py              # AST generation
│   │       ├── contract_analyzer.py        # Contract parsing
│   │       ├── enum_generator.py           # Enum generation
│   │       ├── type_mapper.py              # Type mapping
│   │       └── reference_resolver.py       # $ref resolution
│   └── templates/
│       ├── effect_node_template.py         # EFFECT template
│       ├── compute_node_template.py        # COMPUTE template
│       ├── reducer_node_template.py        # REDUCER template
│       └── orchestrator_node_template.py   # ORCHESTRATOR template
├── cli/
│   ├── generate_node.py                    # CLI entry point
│   └── lib/
│       └── cli_handler.py                  # Abstraction layer
├── tests/
│   ├── generation/                         # Generation tests
│   ├── integration/                        # Integration tests
│   └── cli/                                # CLI tests
├── docs/
│   ├── CLI_USAGE.md                        # User guide
│   ├── PROJECT_COMPLETION_SUMMARY.md       # Executive summary
│   ├── TECHNICAL_COMPLETION_REPORT.md      # Technical details
│   └── DEVELOPER_HANDOFF.md                # This document
└── pyproject.toml                          # Dependencies
```

### Key Files to Know

**1. `cli/generate_node.py`** (358 LOC)
- Entry point for CLI usage
- Argument parsing
- Progress display
- Error handling

**2. `agents/lib/generation_pipeline.py`** (1,231 LOC)
- 6-stage pipeline orchestration
- 14 validation gates
- Rollback mechanism
- Event emission

**3. `agents/lib/generation/contract_builder_factory.py`** (143 LOC)
- Factory for selecting contract builder
- Node type detection
- Builder registration

**4. `agents/lib/generation/ast_builder.py`** (429 LOC)
- Python AST generation
- Type-safe code generation
- Import management

**5. `agents/lib/compatibility_validator.py`** (858 LOC)
- AST-based syntax validation
- Import resolution
- ONEX naming compliance

---

## Testing Guide

### Running Tests

```bash
# All tests (263+ tests, ~2-3 minutes)
poetry run pytest

# Specific test file
poetry run pytest tests/generation/test_prompt_parser.py

# Specific test
poetry run pytest tests/generation/test_prompt_parser.py::test_parse_effect_node

# With coverage
poetry run pytest --cov=agents --cov=cli

# Fast tests only (skip integration)
poetry run pytest -m "not integration"

# Integration tests only
poetry run pytest -m integration
```

### Writing Tests

**Unit Test Template**:
```python
# tests/generation/test_my_component.py

import pytest
from agents.lib.generation.my_component import MyComponent


class TestMyComponent:
    """Test suite for MyComponent."""

    @pytest.fixture
    def component(self):
        """Fixture for component instance."""
        return MyComponent()

    def test_basic_functionality(self, component):
        """Test basic functionality."""
        result = component.do_something("input")

        assert result is not None
        assert result.success is True

    def test_error_handling(self, component):
        """Test error handling."""
        with pytest.raises(ValueError):
            component.do_something(None)
```

**Integration Test Template**:
```python
# tests/integration/test_full_generation.py

import pytest
from pathlib import Path
from agents.lib.generation_pipeline import GenerationPipeline


@pytest.mark.integration
class TestFullGeneration:
    """Integration tests for full generation flow."""

    @pytest.mark.asyncio
    async def test_generate_effect_node(self, tmp_path):
        """Test generating EFFECT node end-to-end."""
        pipeline = GenerationPipeline(compile_check=False)

        result = await pipeline.execute(
            prompt="Create EFFECT node for test",
            output_directory=str(tmp_path)
        )

        assert result.success is True
        assert len(result.files_written) >= 10
        assert (tmp_path / result.node_directory / "v1_0_0" / "node.py").exists()
```

### Test Fixtures

**Common fixtures** (in `tests/conftest.py`):

```python
@pytest.fixture
def sample_prompt():
    """Sample prompt for testing."""
    return "Create EFFECT node for PostgreSQL writes"


@pytest.fixture
def parsed_data():
    """Pre-parsed prompt data."""
    return ParsedPromptData(
        node_type="EFFECT",
        service_name="postgres_writer",
        domain="infrastructure",
        confidence=0.92
    )


@pytest.fixture
def tmp_output_dir(tmp_path):
    """Temporary output directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir
```

---

## Troubleshooting

### ⚠️ CRITICAL KNOWN ISSUES (Must Be Aware Of)

**Platform Status**: Template generation is **90% functional** but has **2 critical bugs** that affect all generated code.

---

#### 🔴 Critical Bug #1: Lowercase Boolean Values (BLOCKS COMPILATION)

**Symptoms**:
```python
# Generated code contains:
is_persistent_service: bool = Field(
    default=false,  # ❌ NameError: name 'false' is not defined
    description="..."
)
```

**Root Cause**: Template engine in `agents/lib/omninode_template_engine.py` (lines 707-708) uses `.lower()` instead of `.capitalize()` for Python booleans

**Impact**: **Every generated node will fail to compile** until manually fixed

**Workaround** (temporary):
1. Generate node as usual
2. Open `v1_0_0/models/model_*_effect_contract.py`
3. Manually change `false` → `False` and `true` → `True`
4. Run `mypy` to verify fixes

**Permanent Fix** (requires code change):
```python
# File: agents/lib/omninode_template_engine.py, lines 707-708

# Current (WRONG):
IS_PERSISTENT_SERVICE=str(is_persistent).lower(),  # Outputs "false"
REQUIRES_EXTERNAL_DEPS=str(requires_external_deps).lower(),  # Outputs "true"

# Fixed (CORRECT):
IS_PERSISTENT_SERVICE=str(is_persistent).capitalize(),  # Outputs "False"
REQUIRES_EXTERNAL_DEPS=str(requires_external_deps).capitalize(),  # Outputs "True"
```

**Evidence**: See `TEST_RESULTS.md`, lines 136-178

---

#### 🟠 Critical Bug #2: Missing Mixin Imports (BLOCKS VALIDATION)

**Symptoms**:
```python
# Generated code contains:
from omnibase_core.mixins.mixineventbus import MixinEventBus  # ❌ ModuleNotFoundError
from omnibase_core.mixins.mixinretry import MixinRetry        # ❌ ModuleNotFoundError
```

**Root Cause**: Template engine generates mixin imports that don't exist in omnibase_core yet

**Impact**: Generated code fails validation gate G11 (import resolution)

**Workaround** (temporary):
1. Generate node as usual
2. Open `v1_0_0/node.py`
3. Comment out or remove mixin imports (lines 22-23)
4. Remove mixin references from class definition

**Permanent Fix** (requires code change):
```python
# File: agents/lib/omninode_template_engine.py, lines 344-353

def _generate_mixin_imports(self, mixins: List[str]) -> str:
    """Generate mixin import statements"""
    if not mixins:
        return ""

    # TODO: Enable when omnibase_core supports mixins
    # For now, return empty string to avoid import errors
    return ""  # ✅ TEMPORARY FIX: Disable mixin imports
```

**Evidence**: See `TEST_RESULTS.md`, lines 72-91

---

#### ⚠️ Minor Issue #3: Wildcard Imports (Style Warning)

**Symptoms**: Generated `__init__.py` files contain wildcard imports
**Impact**: Style violation, not critical
**Workaround**: Accept as-is or manually replace with explicit imports

---

#### ⚠️ Minor Issue #4: Any Type Imports (Style Warning)

**Symptoms**: Template imports `Any` type even when not used
**Impact**: Style violation, not critical
**Workaround**: Accept as-is or manually remove unused imports

---

### Common Issues

#### Issue 1: "Import Error: omnibase_core not found"

**Symptoms**:
```
ImportError: cannot import name 'NodeEffect' from 'omnibase_core.nodes.node_effect'
```

**Solutions**:
```bash
# 1. Install omnibase_core
poetry add omnibase_core

# 2. Verify installation
poetry run python -c "from omnibase_core.nodes.node_effect import NodeEffect; print('OK')"

# 3. Check Python version
python --version  # Should be 3.12+
```

#### Issue 2: "Validation Gate G10 Failed: Incorrect naming"

**Symptoms**:
```
ValidationError: Node class not found or incorrect naming (must end with 'EFFECT')
```

**Cause**: Generated node class doesn't follow suffix-based naming

**Solutions**:
```python
# WRONG: Prefix-based (old ONEX pattern)
class EffectPostgresWriter(NodeEffect):
    pass

# CORRECT: Suffix-based (current ONEX pattern)
class NodePostgresWriterEffect(NodeEffect):
    pass
```

**Fix**: Update template or check for corrupted cache

#### Issue 3: "Generation timeout (>120s)"

**Symptoms**:
```
TimeoutError: Generation exceeded 120 seconds
```

**Solutions**:
```bash
# 1. Skip optional compilation (saves ~10s)
poetry run python cli/generate_node.py --no-compile "prompt"

# 2. Check system resources
top  # Ensure CPU/memory available

# 3. Clear cache
rm -rf ~/.cache/omniclaude/

# 4. Run with debug mode
poetry run python cli/generate_node.py --debug "prompt"
```

#### Issue 4: "Pydantic validation error"

**Symptoms**:
```
pydantic.error_wrappers.ValidationError: 1 validation error for ModelContractEffect
```

**Solutions**:
```bash
# 1. Check Pydantic version
poetry show pydantic  # Should be v2.x

# 2. Update dependencies
poetry update pydantic

# 3. Clear __pycache__
find . -name "__pycache__" -exec rm -rf {} +

# 4. Verify template syntax
poetry run mypy agents/templates/effect_node_template.py
```

#### Issue 5: "Permission denied when writing files"

**Symptoms**:
```
PermissionError: [Errno 13] Permission denied: './output/node_...'
```

**Solutions**:
```bash
# 1. Check output directory permissions
ls -ld ./output

# 2. Create with correct permissions
mkdir -p ./output
chmod 755 ./output

# 3. Use absolute path
poetry run python cli/generate_node.py --output /tmp/output "prompt"

# 4. Check disk space
df -h
```

### Debug Mode

**Enable debug logging**:
```bash
# CLI debug mode
poetry run python cli/generate_node.py --debug "prompt"

# Programmatic debug
import logging
logging.basicConfig(level=logging.DEBUG)

pipeline = GenerationPipeline(compile_check=False)
```

**Debug output shows**:
- Each pipeline stage entry/exit
- Validation gate results
- Template rendering warnings
- File write operations
- Performance timings

### Performance Debugging

**Profile generation**:
```python
import cProfile
import pstats
from agents.lib.generation_pipeline import GenerationPipeline

# Profile execution
profiler = cProfile.Profile()
profiler.enable()

pipeline = GenerationPipeline()
result = await pipeline.execute("prompt", "./output")

profiler.disable()

# Print stats
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 slowest functions
```

---

## Intelligence Gathering System

### How It Works

The platform now includes an intelligence gathering system that analyzes best practices and patterns before generating code.

**1. Pattern Library**: Built-in best practices for each node type
   - Location: `agents/lib/intelligence_gatherer.py`
   - Format: `Dict[node_type, Dict[domain, List[str]]]`

**2. RAG Integration** (Optional):
   - Queries Archon MCP for contextual patterns
   - Falls back to pattern library if unavailable

**3. Intelligence Context**:
   - `node_type_patterns`: General patterns for node type
   - `domain_best_practices`: Domain-specific patterns
   - `common_operations`: Expected operations (e.g., CRUD)
   - `required_mixins`: Mixins to include
   - `performance_targets`: Performance expectations
   - `error_scenarios`: Common error cases

### Adding New Patterns

Edit `agents/lib/intelligence_gatherer.py`:

```python
def _load_pattern_library(self) -> Dict[str, Any]:
    return {
        "EFFECT": {
            "database": [
                "Implement connection pooling for resource management",
                "Use prepared statements to prevent SQL injection",
                "Wrap operations in transactions for ACID compliance",
            ],
            "your_domain": [
                "Your best practice here",
                "Another pattern",
            ],
        },
    }
```

### Casing Preservation (Fixed!)

Service names now preserve original casing:

**Before** (Incorrect):
```bash
# Input: "PostgresCRUD" → Output: "PostgresCRUD" ❌
# Actually generated: "postgrescrud" (all lowercase)
```

**After** (Correct):
```bash
# Input: "PostgresCRUD" → Output: "PostgresCRUD" ✅
# Input: "RestAPI" → Output: "RestAPI" ✅
# Input: "postgres_crud" → Output: "PostgresCrud" ✅
```

**How It Works**:
- Acronym detection: Preserves CRUD, API, SQL, HTTP, REST, JSON, XML, UUID, etc.
- Mixed-case preservation: Maintains original casing from input
- PascalCase conversion: Converts snake_case to PascalCase while preserving acronyms

**No more all-lowercase conversion!**

---

## Extension Guide

### Adding a New Node Type

**Example**: Add `MONITOR` node type

**Step 1: Create template**
```python
# agents/templates/monitor_node_template.py

MONITOR_NODE_TEMPLATE = """
#!/usr/bin/env python3
from omnibase_core.nodes.node_monitor import NodeMonitor

class Node{{MICROSERVICE_NAME_PASCAL}}Monitor(NodeMonitor):
    '''{{BUSINESS_DESCRIPTION}}'''

    async def execute_monitoring(self, input_data):
        # Monitoring logic here
        pass
"""
```

**Step 2: Create contract builder**
```python
# agents/lib/generation/contract_builder_monitor.py

from agents.lib.generation.contract_builder import ContractBuilder
from omnibase_core.models.contracts import ModelContractMonitor

class MonitorContractBuilder(ContractBuilder):
    """Build ModelContractMonitor."""

    def build_contract(self, parsed_data: ParsedPromptData) -> ModelContractMonitor:
        return ModelContractMonitor(
            name=parsed_data.service_name,
            version="1.0.0",
            node_type="MONITOR",
            monitoring_config={...}
        )
```

**Step 3: Register in factory**
```python
# agents/lib/generation/contract_builder_factory.py

from agents.lib.generation.contract_builder_monitor import MonitorContractBuilder

class ContractBuilderFactory:
    BUILDERS = {
        "EFFECT": EffectContractBuilder,
        "COMPUTE": ComputeContractBuilder,
        "REDUCER": ReducerContractBuilder,
        "ORCHESTRATOR": OrchestratorContractBuilder,
        "MONITOR": MonitorContractBuilder,  # NEW
    }
```

**Step 4: Update parser**
```python
# agents/lib/prompt_parser.py

VALID_NODE_TYPES = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR", "MONITOR"]
```

**Step 5: Add tests**
```python
# tests/generation/test_contract_builder_monitor.py

def test_build_monitor_contract():
    builder = MonitorContractBuilder()
    parsed = ParsedPromptData(node_type="MONITOR", ...)

    contract = builder.build_contract(parsed)

    assert contract.node_type == "MONITOR"
    assert contract.monitoring_config is not None
```

### Adding a New Validation Gate

**Example**: Add G15 for security validation

**Step 1: Implement gate**
```python
# agents/lib/compatibility_validator.py

def validate_security_compliance(self, code: str) -> ValidationResult:
    """
    G15: Validate security best practices.

    Checks:
    - No hardcoded secrets
    - Proper input sanitization
    - SQL injection prevention
    """
    issues = []

    # Check for hardcoded secrets
    if re.search(r'password\s*=\s*["\']', code, re.IGNORECASE):
        issues.append("Possible hardcoded password")

    # Check for SQL injection
    if re.search(r'f"SELECT.*\{', code):
        issues.append("Possible SQL injection vulnerability")

    if issues:
        return ValidationResult(
            passed=False,
            errors=issues,
            suggestions=["Use environment variables for secrets",
                        "Use parameterized queries"]
        )

    return ValidationResult(passed=True)
```

**Step 2: Add to pipeline**
```python
# agents/lib/generation_pipeline.py

async def _stage_4_post_validation(self, ...):
    # Existing gates G9-G12
    ...

    # New gate G15
    security_result = self.validator.validate_security_compliance(code)
    if not security_result.passed:
        raise ValidationError(f"G15 failed: {security_result.errors}")
```

**Step 3: Add tests**
```python
# tests/generation/test_compatibility_validator.py

def test_g15_security_validation():
    validator = CompatibilityValidator()

    # Should fail
    bad_code = 'password = "secret123"'
    result = validator.validate_security_compliance(bad_code)
    assert result.passed is False

    # Should pass
    good_code = 'password = os.environ["PASSWORD"]'
    result = validator.validate_security_compliance(good_code)
    assert result.passed is True
```

### Adding a New Utility

**Example**: Add `DependencyResolver` utility

```python
# agents/lib/generation/dependency_resolver.py

from typing import List, Dict, Any
from pathlib import Path


class DependencyResolver:
    """
    Resolve and order node dependencies.

    Features:
    - Topological sort
    - Circular dependency detection
    - Dependency graph visualization
    """

    def resolve_dependencies(
        self,
        contracts: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Resolve dependency order.

        Returns:
            List of node names in execution order
        """
        graph = self._build_graph(contracts)
        return self._topological_sort(graph)

    def _build_graph(self, contracts):
        # Build dependency graph
        pass

    def _topological_sort(self, graph):
        # Sort graph
        pass
```

**Integration**:
```python
# agents/lib/generation_pipeline.py

from agents.lib.generation.dependency_resolver import DependencyResolver

class GenerationPipeline:
    def __init__(self):
        self.dependency_resolver = DependencyResolver()

    async def resolve_multi_node_order(self, prompts: List[str]):
        # Use resolver for multi-node generation
        pass
```

---

## Deployment Guide

### Production Deployment Checklist

**Pre-Deployment**:
```bash
# 1. Run all tests
poetry run pytest

# 2. Type checking
poetry run mypy agents/ cli/

# 3. Linting
poetry run ruff check agents/ cli/

# 4. Security scan (optional)
poetry run bandit -r agents/ cli/

# 5. Dependency audit
poetry run pip-audit

# 6. Performance benchmarks
poetry run pytest tests/test_performance.py
```

**Deployment Steps**:
```bash
# 1. Build package
poetry build

# 2. Upload to artifact repository
# (depends on your infrastructure)

# 3. Deploy to production environment
poetry install --only main  # No dev dependencies

# 4. Verify installation
poetry run python cli/generate_node.py --version

# 5. Smoke test
poetry run python cli/generate_node.py "Create EFFECT node for test"
```

### Configuration

**Environment Variables**:
```bash
# Required
export OMNIBASE_CORE_PATH=/path/to/omnibase_core

# Optional
export OMNICLAUDE_LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
export OMNICLAUDE_CACHE_DIR=/var/cache/omniclaude
export OMNICLAUDE_TEMPLATE_DIR=/custom/templates
export OMNICLAUDE_OUTPUT_DIR=/default/output
```

**Configuration File** (future enhancement):
```yaml
# ~/.omniclaude/config.yaml

generation:
  compile_check: true
  timeout_seconds: 120
  default_output_dir: ./output

validation:
  strict_mode: true
  custom_gates:
    - G15_security

performance:
  cache_enabled: true
  parallel_generation: false  # Phase 3 feature
```

---

## Maintenance Guide

### Regular Maintenance Tasks

**Daily**:
- Monitor generation success rate
- Check error logs for patterns
- Clear old output directories

**Weekly**:
- Review performance metrics
- Update dependencies (security patches)
- Run full test suite

**Monthly**:
- Review and update templates
- Analyze generation patterns
- Optimize slow paths
- Update documentation

### Monitoring

**Key Metrics to Track**:
```python
# Generation success rate
success_rate = successful_generations / total_attempts

# Average generation time
avg_time = sum(generation_times) / len(generation_times)

# Validation failure rate
failure_rate = validation_failures / total_generations

# Most common node types
node_type_distribution = Counter(generated_node_types)
```

**Log Analysis**:
```bash
# Find failed generations
grep "Pipeline failed" logs/*.log

# Find slow generations (>60s)
grep "duration_seconds.*[6-9][0-9]" logs/*.log

# Find validation failures
grep "ValidationError" logs/*.log

# Count by node type
grep "node_type" logs/*.log | cut -d: -f2 | sort | uniq -c
```

### Updating Templates

**Process**:
1. Modify template in `agents/templates/`
2. Test template changes
3. Update template tests
4. Generate sample nodes
5. Verify ONEX compliance
6. Deploy updated templates

**Template Testing**:
```bash
# Generate node from updated template
poetry run python cli/generate_node.py "test prompt"

# Verify ONEX compliance
poetry run mypy output/node_*/v1_0_0/node.py

# Run integration tests
poetry run pytest tests/integration/
```

---

## FAQ

### Q: How long does generation take?
**A**: ~40 seconds on average (target <120s). Breakdown:
- Parsing: ~5s
- Generation: ~12s
- Validation: ~10s
- File writing: ~3s
- Compilation (optional): ~10s

### Q: Can I generate multiple nodes at once?
**A**: Not yet (Phase 3 feature). Current workaround:
```bash
for prompt in "${prompts[@]}"; do
    poetry run python cli/generate_node.py "$prompt"
done
```

### Q: How do I customize generated code?
**A**: Three options:
1. Modify templates in `agents/templates/`
2. Post-process generated code
3. Use prompts to guide generation ("with Redis caching")

### Q: What node types are supported?
**A**: 4 types:
- EFFECT: Side effects, I/O operations
- COMPUTE: Pure transformations
- REDUCER: State aggregation, intent emission
- ORCHESTRATOR: Workflow coordination

### Q: Can I use this in CI/CD?
**A**: Yes! Example:
```yaml
# .github/workflows/generate-nodes.yml
- name: Generate nodes
  run: |
    poetry run python cli/generate_node.py \
      "Create EFFECT node for $SERVICE" \
      --output ./generated \
      --no-compile
```

### Q: How do I report bugs?
**A**: Create an issue with:
- Prompt used
- Error message
- Debug output (`--debug`)
- Environment (Python version, omnibase_core version)

### Q: Can I extend the system?
**A**: Yes! See [Extension Guide](#extension-guide) for:
- Adding node types
- Adding validation gates
- Adding utilities

### Q: What's the difference between Phase 1 and Phase 2?
**A**: See `PHASE_1_VS_PHASE_2.md` for detailed comparison. Summary:
- Phase 1: POC, EFFECT only, string templates
- Phase 2: Production, 4 types, Pydantic contracts

### Q: Is there a GUI?
**A**: Not yet (Phase 5 feature). Current options:
- CLI (direct or interactive mode)
- Programmatic API (Python)

### Q: How do I migrate existing nodes?
**A**: Currently no auto-migration. Manual process:
1. Extract requirements from existing node
2. Generate new node with same requirements
3. Copy business logic
4. Test and validate

---

## Additional Resources

### Documentation
- **User Guide**: `CLI_USAGE.md` - How to use the CLI
- **Architecture**: `POC_PIPELINE_ARCHITECTURE.md` - System design
- **Technical Report**: `TECHNICAL_COMPLETION_REPORT.md` - Deep dive
- **Completion Summary**: `PROJECT_COMPLETION_SUMMARY.md` - Executive overview

### Code Examples
- **Simple Generation**: See "Quick Start" section
- **Programmatic Usage**: See "Usage Mode 3"
- **Custom Extensions**: See "Extension Guide"
- **Testing Examples**: See "Testing Guide"

### Support
- **Issues**: File GitHub issue with debug output
- **Questions**: Review this document and FAQ
- **Feature Requests**: Propose via GitHub issue
- **Security**: Email security@ (do not file public issue)

---

## Getting Help

**If you're stuck**:
1. Check [Troubleshooting](#troubleshooting) section
2. Review [FAQ](#faq)
3. Run with `--debug` for verbose output
4. Check logs in `./logs/` directory
5. File an issue with reproducible example

**If you want to contribute**:
1. Read [Extension Guide](#extension-guide)
2. Review code organization
3. Write tests for new features
4. Follow ONEX coding standards
5. Submit PR with description

---

**This platform is designed to be developer-friendly. If something is unclear or difficult, please let us know!**

---

**Document Version**: 1.0.0
**Last Updated**: 2025-10-21
**Maintained By**: OmniClaude Core Team
**Next Review**: After Phase 3 features added
