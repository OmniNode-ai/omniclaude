# OmniBase Core Compatibility Validator

Automated validation tool for omnibase_core import paths, ONEX patterns, and code quality compliance.

## Purpose

The Compatibility Validator prevents import failures and ensures code quality by validating:

1. **Import Paths** - Verifies all `omnibase_core` imports exist and are importable
2. **ONEX Naming** - Validates Node/Model/Enum naming conventions
3. **Pydantic v2** - Detects Pydantic v1 patterns (`.dict()`, `.json()`, etc.)
4. **Base Classes** - Ensures correct base class inheritance (NodeEffect, NodeCompute, etc.)
5. **Container DI** - Validates ModelONEXContainer dependency injection
6. **Type Hints** - Detects `Any` types and missing return type annotations
7. **Forbidden Patterns** - Catches wildcard imports and other anti-patterns

## Installation

```bash
# No additional dependencies required
poetry install
```

## Quick Start

### Validate a Single File

```bash
# Basic validation
poetry run python tools/compatibility_validator.py --file path/to/file.py

# With JSON output
poetry run python tools/compatibility_validator.py --file path/to/file.py --json

# Strict mode (warnings become errors)
poetry run python tools/compatibility_validator.py --file path/to/file.py --strict
```

### Validate Templates

```bash
# Auto-detects template placeholders and substitutes them
poetry run python tools/compatibility_validator.py --file agents/templates/effect_node_template.py

# Explicit template mode
poetry run python tools/compatibility_validator.py --file mytemplate.py --template-mode
```

### Validate Directory

```bash
# Validate all Python files in directory
poetry run python tools/compatibility_validator.py --directory agents/templates

# Recursive validation
poetry run python tools/compatibility_validator.py --directory agents --recursive

# Custom file pattern
poetry run python tools/compatibility_validator.py --directory src --pattern "node_*.py"
```

## Validation Checks

### 1. Import Path Validation

**What it checks:**
- Imports from `omnibase_core` exist and are importable
- Detects incorrect import paths (common mistakes)
- Validates imported class/function names

**Examples:**

✅ **Valid:**
```python
from omnibase_core.nodes.node_effect import NodeEffect
from omnibase_core.errors.model_onex_error import ModelOnexError
from omnibase_core.models.container.model_onex_container import ModelONEXContainer
```

❌ **Invalid:**
```python
# Incorrect path - should be omnibase_core.nodes.model_effect_input
from omnibase_core.core.node_effect import ModelEffectInput

# Non-existent module
from omnibase_core.nonexistent.module import Something
```

### 2. ONEX Naming Conventions

**What it checks:**
- Node classes follow pattern: `Node<Name><Type>`
- Model classes follow pattern: `Model<Name>`
- Enum classes follow pattern: `Enum<Name>`
- Node type suffix matches base class (Effect, Compute, Reducer, Orchestrator)

**Examples:**

✅ **Valid:**
```python
class NodeUserServiceEffect(NodeEffect):  # Correct: Node + Name + Type
class NodeDataProcessorCompute(NodeCompute):  # Correct
class ModelUserInput(BaseModel):  # Correct: Model + Name
class EnumOperationType(Enum):  # Correct: Enum + Name
```

❌ **Invalid:**
```python
class NodeInvalid:  # Missing type suffix
class NodeUserEffect:  # Missing middle name (should be more descriptive)
class UserService:  # Missing "Node" prefix
class NodeUserServiceCompute(NodeEffect):  # Type mismatch (Compute vs Effect)
```

### 3. Pydantic v2 Compliance

**What it checks:**
- No Pydantic v1 methods: `.dict()`, `.json()`, `.parse_obj()`, `.parse_raw()`, `.schema()`
- Uses Pydantic v2 methods: `.model_dump()`, `.model_dump_json()`, `.model_validate()`, etc.

**Examples:**

✅ **Valid (Pydantic v2):**
```python
from pydantic import BaseModel

class UserModel(BaseModel):
    name: str

user = UserModel(name="test")
data = user.model_dump()  # ✅ Pydantic v2
json_str = user.model_dump_json()  # ✅ Pydantic v2
```

❌ **Invalid (Pydantic v1):**
```python
data = user.dict()  # ❌ Use .model_dump() instead
json_str = user.json()  # ❌ Use .model_dump_json() instead
```

### 4. Base Class Inheritance

**What it checks:**
- Node classes inherit from correct base class
- Base class matches node type suffix

**Examples:**

✅ **Valid:**
```python
from omnibase_core.nodes.node_effect import NodeEffect

class NodeUserServiceEffect(NodeEffect):  # ✅ Effect inherits from NodeEffect
    pass
```

❌ **Invalid:**
```python
class NodeUserServiceEffect:  # ❌ Missing base class
    pass

class NodeUserServiceEffect(NodeCompute):  # ❌ Wrong base class (should be NodeEffect)
    pass
```

### 5. Container-Based Dependency Injection

**What it checks:**
- Node `__init__` methods accept `container: ModelONEXContainer`
- Container is properly type-hinted

**Examples:**

✅ **Valid:**
```python
from omnibase_core.models.container.model_onex_container import ModelONEXContainer

class NodeUserServiceEffect(NodeEffect):
    def __init__(self, container: ModelONEXContainer):
        super().__init__(container)
        self.container = container
```

❌ **Invalid:**
```python
class NodeUserServiceEffect(NodeEffect):
    def __init__(self):  # ❌ Missing container parameter
        pass
```

### 6. Type Hint Validation

**What it checks:**
- Functions have return type annotations (except `__init__`, `__str__`, `__repr__`)
- Avoid `Any` types (ONEX standard: "ZERO TOLERANCE: No Any types")

**Examples:**

✅ **Valid:**
```python
def process_data(data: str) -> str:
    return data.upper()
```

⚠️ **Warnings:**
```python
from typing import Any

def process_data(data: Any) -> Any:  # ⚠️ Avoid Any types
    return data

def process_data(data: str):  # ⚠️ Missing return type
    return data
```

### 7. Forbidden Patterns

**What it checks:**
- Wildcard imports (`from module import *`)
- `Any` type imports

**Examples:**

✅ **Valid:**
```python
from typing import Dict, List, Optional
from pathlib import Path
```

⚠️ **Warnings:**
```python
from typing import *  # ⚠️ Avoid wildcard imports
from typing import Any  # ⚠️ Avoid Any types
```

## Template Mode

The validator automatically detects template files (containing `{PLACEHOLDER}` patterns) and substitutes placeholders before validation.

### Automatic Detection

The validator auto-detects templates when it finds placeholders like:
- `{MICROSERVICE_NAME}`
- `{DOMAIN}`
- `{NODE_TYPE}`
- Any `{UPPERCASE_PATTERN}`

### Supported Placeholders

```python
{MICROSERVICE_NAME}         → "example_service"
{MICROSERVICE_NAME_PASCAL}  → "ExampleService"
{DOMAIN}                    → "example_domain"
{DOMAIN_PASCAL}             → "ExampleDomain"
{NODE_TYPE}                 → "EFFECT"
{BUSINESS_DESCRIPTION}      → "Example business description"
{MIXIN_IMPORTS}             → ""
{MIXIN_INHERITANCE}         → ""
{MIXIN_INITIALIZATION}      → ""
{BUSINESS_LOGIC_STUB}       → "# Business logic"
{OPERATIONS}                → "[]"
{FEATURES}                  → "# Features"
```

### Example

```bash
# Validates template with automatic placeholder substitution
poetry run python tools/compatibility_validator.py --file agents/templates/effect_node_template.py
```

## CLI Options

### Basic Options

| Option | Description |
|--------|-------------|
| `--file PATH` | Validate a single file |
| `--directory PATH` | Validate all files in directory |
| `--recursive` | Recursively validate subdirectories |
| `--pattern PATTERN` | File pattern to match (default: `*.py`) |

### Output Options

| Option | Description |
|--------|-------------|
| `--json` | Output results in JSON format |
| `--strict` | Strict mode (warnings become errors) |

### Validation Options

| Option | Description |
|--------|-------------|
| `--template-mode` | Enable template mode (auto-detect by default) |
| `--omnibase-path PATH` | Path to omnibase_core for import validation |
| `--check-imports` | Only run import validation |
| `--check-patterns` | Only run pattern validation |
| `--check-pydantic` | Only run Pydantic v2 validation |
| `--check-all` | Run all checks (default) |

## JSON Output Format

```json
{
  "total_files": 1,
  "results": [
    {
      "file_path": "path/to/file.py",
      "status": "pass|fail|warning",
      "checks": [
        {
          "type": "import|pattern|pydantic|base_class|di_container|type_hint|naming|forbidden",
          "status": "pass|fail|warning|skip",
          "rule": "rule_name",
          "message": "Description of check result",
          "line": 42,
          "details": "Additional context",
          "suggestion": "How to fix the issue"
        }
      ],
      "summary": {
        "total": 10,
        "passed": 8,
        "failed": 1,
        "warnings": 1,
        "skipped": 0
      },
      "errors": []
    }
  ],
  "overall_summary": {
    "passed": 0,
    "failed": 0,
    "warnings": 1
  }
}
```

## Integration

### CI/CD Integration

```bash
# Add to CI pipeline (exits with code 1 on failure)
poetry run python tools/compatibility_validator.py --directory src --recursive --strict

# Generate JSON report for CI
poetry run python tools/compatibility_validator.py \
  --directory src \
  --recursive \
  --strict \
  --json > validation_report.json
```

### Pre-commit Hook

Add to `.pre-commit-config.yaml`:

```yaml
- repo: local
  hooks:
    - id: omnibase-compat-validator
      name: OmniBase Compatibility Validator
      entry: poetry run python tools/compatibility_validator.py
      language: system
      files: ^(agents|src)/.*\.py$
      args: ['--file']
```

### VS Code Task

Add to `.vscode/tasks.json`:

```json
{
  "label": "Validate OmniBase Compatibility",
  "type": "shell",
  "command": "poetry run python tools/compatibility_validator.py --file ${file}",
  "problemMatcher": [],
  "group": {
    "kind": "test",
    "isDefault": false
  }
}
```

## Performance

- **Single file validation:** <100ms
- **Directory validation (50 files):** <5s
- **Template substitution overhead:** <10ms
- **Import validation:** Cached after first import

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All checks passed |
| `1` | One or more checks failed |
| `1` | Warnings in strict mode |

## Common Issues and Solutions

### Issue: Import Not Found

```
❌ Import not found: omnibase_core.core.node_effect
💡 Suggestion: Use omnibase_core.nodes.model_effect_input/model_effect_output instead
```

**Solution:** Update import path to correct location in omnibase_core.

### Issue: Invalid Node Naming

```
❌ Invalid ONEX node naming: NodeInvalid
💡 Suggestion: Example: NodeUserServiceEffect, NodeDataProcessorCompute
```

**Solution:** Follow pattern `Node<Name><Type>` where Type is Effect, Compute, Reducer, or Orchestrator.

### Issue: Pydantic v1 Pattern

```
❌ Pydantic v1 pattern found: .dict()
💡 Suggestion: Replace with: .model_dump(
```

**Solution:** Replace `.dict()` with `.model_dump()` (Pydantic v2).

### Issue: Missing Container DI

```
⚠️ NodeUserServiceEffect.__init__ missing container DI
💡 Suggestion: Add: def __init__(self, container: ModelONEXContainer):
```

**Solution:** Add container parameter to `__init__` method.

## Examples

### Example 1: Validate Template Before Generation

```bash
# Validate template before generating code
poetry run python tools/compatibility_validator.py \
  --file agents/templates/effect_node_template.py
```

**Output:**
```
================================================================================
File: agents/templates/effect_node_template.py
Status: WARNING
Summary: {'total': 9, 'passed': 8, 'failed': 0, 'warnings': 1, 'skipped': 0}
================================================================================

⚠️  Warnings (1):
  [forbidden] forbidden_pattern
  Line 11: Forbidden pattern: from typing import Any

✅ Passed Checks (8)
```

### Example 2: Validate Generated Code

```bash
# Validate generated node implementation
poetry run python tools/compatibility_validator.py \
  --file output/node_user_service_effect/v1_0_0/node.py \
  --strict
```

### Example 3: Validate All Templates

```bash
# Validate all templates with JSON output
poetry run python tools/compatibility_validator.py \
  --directory agents/templates \
  --json > template_validation.json
```

### Example 4: CI/CD Validation

```bash
# Strict validation for CI/CD (exits 1 on any warning)
poetry run python tools/compatibility_validator.py \
  --directory agents \
  --recursive \
  --strict \
  --json > ci_validation_report.json

# Check exit code
if [ $? -ne 0 ]; then
  echo "❌ Validation failed"
  exit 1
fi
```

## Testing

Run the test suite:

```bash
# Run all validator tests
poetry run pytest tests/test_compatibility_validator.py -v

# Run specific test class
poetry run pytest tests/test_compatibility_validator.py::TestImportValidation -v

# Run with coverage
poetry run pytest tests/test_compatibility_validator.py --cov=tools.compatibility_validator
```

## Development

### Adding New Validation Checks

1. Add check method to `OmniBaseCompatibilityValidator` class
2. Call method in `validate_file()`
3. Add test case to `tests/test_compatibility_validator.py`
4. Update documentation

Example:

```python
def _check_custom_pattern(self, tree: ast.AST, result: ValidationResult) -> None:
    """Check custom pattern"""
    for node in ast.walk(tree):
        # Your validation logic here
        result.checks.append(
            ValidationCheck(
                check_type=CheckType.PATTERN,
                status=CheckStatus.PASS,
                rule="custom_pattern",
                message="Custom pattern validated",
                line_number=node.lineno,
            )
        )
```

### Extending Known Import Paths

Update `VALID_IMPORTS` dictionary in `OmniBaseCompatibilityValidator`:

```python
VALID_IMPORTS = {
    "omnibase_core.nodes.node_effect": ["NodeEffect"],
    "omnibase_core.nodes.new_module": ["NewClass"],  # Add new path
    # ...
}
```

## Troubleshooting

### Validator Not Finding omnibase_core

Ensure omnibase_core is installed:

```bash
poetry install
```

Or specify path explicitly:

```bash
poetry run python tools/compatibility_validator.py \
  --file myfile.py \
  --omnibase-path /path/to/omnibase_core
```

### Template Mode Not Working

Verify placeholders match expected patterns:
- Must be `{UPPERCASE_WITH_UNDERSCORES}`
- Common placeholders are auto-detected
- Use `--template-mode` to force template mode

### Import Validation Failing

Check that:
1. omnibase_core is installed: `poetry show omnibase_core`
2. Import paths are correct (see Valid Imports section)
3. omnibase_core is on the correct branch/version

## Related Tools

- **omnibase_core** - Core framework being validated against
- **pre-commit** - Git hook framework for automatic validation
- **pytest** - Testing framework for validator tests
- **ruff** - Fast Python linter (complementary)
- **mypy** - Static type checker (complementary)

## License

MIT License - See LICENSE file for details

## Contributing

See CONTRIBUTING.md for guidelines on:
- Adding new validation checks
- Reporting bugs
- Submitting pull requests
- Code style requirements

## Support

For issues or questions:
- GitHub Issues: https://github.com/OmniNode-ai/omniclaude/issues
- Documentation: /docs/COMPATIBILITY_VALIDATOR.md
- Tests: /tests/test_compatibility_validator.py
