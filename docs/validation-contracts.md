# Validation Contracts Schema Documentation

**Source**: omnibase-core v0.8.x
**Location**: `omnibase_core/validation/contracts/*.validation.yaml`
**Pydantic Models**: `omnibase_core.models.contracts.subcontracts.model_validator_subcontract`

---

## Overview

Validation contracts are YAML configuration files that define file-based validators in the ONEX ecosystem. They provide:

- File targeting via glob patterns (include/exclude)
- Configurable validation rules with severity levels
- Suppression comment patterns for inline overrides
- Behavior configuration (fail-fast, parallel execution)
- Violation limits and error handling settings

---

## Complete Schema Reference

### Top-Level Structure

```yaml
---
contract_kind: validation_subcontract  # Required: identifies contract type
validation:                            # Required: contains all validator config
  # ... all fields below ...
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `version` | object | Semantic version of the contract |
| `validator_id` | string | Unique identifier for this validator (min 1 char) |
| `validator_name` | string | Human-readable name (min 1 char) |
| `validator_description` | string | Multi-line description of what the validator checks |

### Version Object

```yaml
version:
  major: 1
  minor: 0
  patch: 0
```

### File Targeting Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `target_patterns` | list[string] | `["**/*.py"]` | Glob patterns for files to validate |
| `exclude_patterns` | list[string] | (see below) | Glob patterns to exclude |
| `source_root` | string \| null | `null` | Base path for validation (defaults to cwd) |

**Default exclude_patterns**:
```yaml
exclude_patterns:
  - "**/node_modules/**"
  - "**/__pycache__/**"
  - "**/.venv/**"
  - "**/venv/**"
  - "**/.git/**"
```

### Rules Configuration

```yaml
rules:
  - rule_id: unique_rule_identifier    # Required: unique within contract
    description: |                      # Required: what this rule checks
      Multi-line description of the rule.
    severity: error                     # Optional: debug|info|warning|error|critical|fatal
    enabled: true                       # Optional: whether rule is active (default: true)
    parameters:                         # Optional: rule-specific config
      max_params: 5
      allow_in_tests: true
```

### Rule Schema

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `rule_id` | string | (required) | Unique identifier for the rule |
| `description` | string | (required) | Human-readable description |
| `severity` | enum | `error` | Severity level for violations |
| `enabled` | bool | `true` | Whether rule is active |
| `parameters` | dict | `null` | Rule-specific configuration |

**Parameter Value Types**: `string | int | float | bool | list[string]`

### Severity Levels

| Level | Numeric | Description |
|-------|---------|-------------|
| `debug` | 10 | Detailed diagnostic information |
| `info` | 20 | General operational information |
| `warning` | 30 | Unexpected situation, operation continues |
| `error` | 40 | Operation failed, system continues |
| `critical` | 50 | Serious error, system degraded |
| `fatal` | 60 | Unrecoverable error |

### Suppression Configuration

```yaml
suppression_comments:
  - "# ONEX_EXCLUDE: any_type"
  - "# noqa:"
  - "# type: ignore"
  - "# validator-ok:"
```

**Default suppression patterns**: `["# noqa:", "# type: ignore", "# validator-ok:"]`

**Important**: Suppression is LINE-BASED, not rule-specific. Any matching pattern suppresses ALL violations on that line.

### Behavior Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `severity_default` | enum | `error` | Default severity for rules without explicit severity |
| `fail_on_error` | bool | `true` | Non-zero exit on ERROR+ severity |
| `fail_on_warning` | bool | `false` | Non-zero exit on WARNING+ severity |
| `max_violations` | int | `0` | Stop after N violations (0 = unlimited) |
| `parallel_execution` | bool | `true` | Enable parallel file processing |

**Constraint**: If `fail_on_warning: true`, then `fail_on_error` must also be `true`.

---

## Annotated Example: any_type.validation.yaml

```yaml
---
contract_kind: validation_subcontract
validation:
  # ============================================================================
  # VERSION: Semantic versioning for the contract itself
  # ============================================================================
  version:
    major: 1
    minor: 0
    patch: 0

  # ============================================================================
  # IDENTIFICATION: Unique identifiers and human-readable metadata
  # ============================================================================
  validator_id: any_type                      # Machine identifier (used in filenames, CLI)
  validator_name: Any Type Policy Validator   # Human-readable display name
  validator_description: |                    # Multi-line description
    Enforces strict typing policy by detecting use of Any type.
    Checks for Any imports, annotations, dict[str, Any], and Union[..., Any].
    Supports exemptions via decorators and inline comments.

  # ============================================================================
  # FILE TARGETING: Which files to validate
  # ============================================================================
  target_patterns:
    - "**/*.py"                              # All Python files recursively

  exclude_patterns:
    - "**/node_modules/**"                   # Node.js deps (if present)
    - "**/.git/**"                           # Git internals
    - "**/venv/**"                           # Virtual environments
    - "**/__pycache__/**"                    # Python bytecode
    - "**/archived/**"                       # Archived code
    - "**/tests/**"                          # Test directories
    - "**/*_test.py"                         # Test files (suffix)
    - "**/test_*.py"                         # Test files (prefix)
    - "**/conftest.py"                       # Pytest configuration

  # ============================================================================
  # RULES: Individual validation checks
  # ============================================================================
  rules:
    - rule_id: any_import
      description: Detects 'from typing import Any' statements
      severity: warning                       # Warning only - import isn't usage
      enabled: true

    - rule_id: any_annotation
      description: "Detects Any in type annotations (param: Any, -> Any)"
      severity: error                         # Error - this is actual usage
      enabled: true

    - rule_id: dict_str_any
      description: Detects dict[str, Any] usage
      severity: error
      enabled: true
      parameters:
        allow_in_tests: true                  # Rule-specific parameter

    - rule_id: list_any
      description: Detects list[Any] usage
      severity: warning
      enabled: true

    - rule_id: union_with_any
      description: Detects Union[..., Any] or ... | Any
      severity: error
      enabled: true

  # ============================================================================
  # SUPPRESSION: Inline comment patterns that disable checks
  # ============================================================================
  suppression_comments:
    - "# ONEX_EXCLUDE: any_type"             # Legacy ONEX pattern
    - "# ONEX_EXCLUDE: dict_str_any"         # Legacy specific pattern
    - "# type: ignore"                       # Mypy compatibility
    - "# any-ok:"                            # Preferred: include reason

  # ============================================================================
  # BEHAVIOR: How the validator responds to violations
  # ============================================================================
  severity_default: error                    # Default if rule doesn't specify
  fail_on_error: true                        # Exit non-zero on ERROR+
  fail_on_warning: false                     # Don't fail on warnings alone
  max_violations: 0                          # No limit (check all files)
  parallel_execution: true                   # Enable parallel processing
```

---

## Annotated Example: pydantic_conventions.validation.yaml

```yaml
---
contract_kind: validation_subcontract
validation:
  version:
    major: 1
    minor: 0
    patch: 0

  validator_id: pydantic_conventions
  validator_name: Pydantic Conventions Validator
  validator_description: |
    Enforces Pydantic model configuration standards established in OMN-1301.
    Uses AST-based analysis to ensure models have explicit ConfigDict,
    proper frozen/from_attributes pairing, and follow field definition patterns.

  target_patterns:
    - "**/*.py"

  exclude_patterns:
    - "**/node_modules/**"
    - "**/.git/**"
    - "**/venv/**"
    - "**/__pycache__/**"
    - "**/archived/**"
    - "**/tests/**"
    - "**/*_test.py"
    - "**/test_*.py"
    - "**/conftest.py"
    - "**/scripts/**"                        # Exclude scripts directory

  rules:
    # Rule for missing model_config in Pydantic models
    - rule_id: missing-config
      description: |
        Every Pydantic model needs explicit model_config. Also flags legacy
        class Config: style which should be migrated to model_config = ConfigDict(...).
      severity: error
      enabled: true

    # Rule for empty ConfigDict() - must have at least one option
    - rule_id: empty-config
      description: |
        ConfigDict() with no arguments is forbidden - must have at least one option.
        Empty ConfigDict has ambiguous intent and provides no explicit policy.
      severity: error
      enabled: true

    # Rule for frozen models without from_attributes (pytest-xdist issue)
    - rule_id: frozen-without-from-attributes
      description: |
        frozen=True requires from_attributes=True for pytest-xdist compatibility.
        Without from_attributes=True, pytest-xdist workers may reject valid instances.
      severity: error
      enabled: true

    # Warning rule for contracts missing explicit extra= policy
    - rule_id: contract-missing-extra
      description: |
        Contract models must explicitly declare extra= policy.
      severity: warning                      # Warning because it's a best practice
      enabled: true

    # Warning rule for unnecessary verbosity
    - rule_id: unnecessary-field-default-none
      description: |
        Field(default=None) without other kwargs should be simplified to = None.
      severity: warning
      enabled: true

  suppression_comments:
    - "# ONEX_EXCLUDE: pydantic"
    - "# pydantic-ok:"                       # Preferred with reason
    - "# noqa: pydantic"
    - "# onex: ignore-pydantic-conventions"

  severity_default: error
  # NOTE: fail_on_error is false until existing technical debt is resolved
  fail_on_error: false                       # Temporarily disabled
  fail_on_warning: false
  max_violations: 0
  parallel_execution: true
```

---

## Annotated Example: patterns.validation.yaml

```yaml
---
contract_kind: validation_subcontract
validation:
  version:
    major: 1
    minor: 0
    patch: 0

  validator_id: patterns
  validator_name: ONEX Pattern Validator
  validator_description: |
    Validates code patterns for ONEX compliance including Pydantic model patterns,
    complexity limits, and generic anti-patterns.

  target_patterns:
    - "**/*.py"

  exclude_patterns:
    - "**/node_modules/**"
    - "**/.git/**"
    - "**/venv/**"
    - "**/.venv/**"
    - "**/__pycache__/**"
    - "**/archived/**"
    - "**/examples/**"
    - "**/tests/fixtures/**"

  rules:
    # Model naming convention
    - rule_id: pydantic_model_prefix
      description: Pydantic models must start with 'Model' prefix
      severity: warning
      enabled: true

    # Type correctness
    - rule_id: uuid_field_type
      description: UUID fields should use UUID type, not str
      severity: warning
      enabled: true

    - rule_id: enum_field_type
      description: Category/type/status fields should use enums
      severity: warning
      enabled: true

    # Informational rule (lowest severity for suggestions)
    - rule_id: entity_name_pattern
      description: Fields ending with _name might reference entities
      severity: info                         # Just informational
      enabled: true

    # Code quality rules
    - rule_id: generic_function_name
      description: Avoid overly generic function names like process, handle, execute
      severity: warning
      enabled: true

    # Rules with parameters
    - rule_id: max_parameters
      description: Functions should not have more than 5 parameters
      severity: warning
      enabled: true
      parameters:
        max_params: 5                        # Configurable threshold

    - rule_id: god_class
      description: Classes should not have more than 10 methods
      severity: warning
      enabled: true
      parameters:
        max_methods: 10                      # Configurable threshold

    - rule_id: class_anti_pattern
      description: Avoid generic class name terms like Manager, Handler, Helper
      severity: warning
      enabled: true

    # Disabled rules to avoid overlap with naming_convention validator
    - rule_id: class_pascal_case
      description: Class names should use PascalCase
      severity: warning
      enabled: false                         # Disabled - use naming_convention validator

    - rule_id: function_snake_case
      description: Function names should use snake_case
      severity: warning
      enabled: false                         # Disabled - use naming_convention validator

  suppression_comments:
    - "# ONEX_EXCLUDE:"
    - "# noqa: pattern"
    - "# pattern-ok:"
    - "# type: ignore"

  severity_default: warning                  # Default is warning for this validator
  fail_on_error: true
  fail_on_warning: false
  max_violations: 0
  parallel_execution: true
```

---

## Template Contract for omniclaude2

```yaml
---
contract_kind: validation_subcontract
validation:
  version:
    major: 1
    minor: 0
    patch: 0

  validator_id: YOUR_VALIDATOR_ID
  validator_name: Your Validator Name
  validator_description: |
    Brief description of what this validator checks.
    Can be multiple lines for detailed explanation.

  target_patterns:
    - "**/*.py"

  exclude_patterns:
    - "**/node_modules/**"
    - "**/.git/**"
    - "**/venv/**"
    - "**/.venv/**"
    - "**/__pycache__/**"
    - "**/archived/**"
    - "**/tests/**"
    - "**/test_*.py"
    - "**/*_test.py"
    - "**/conftest.py"

  rules:
    - rule_id: your_rule_id
      description: What this rule checks
      severity: error
      enabled: true

    - rule_id: rule_with_parameters
      description: Rule that has configurable thresholds
      severity: warning
      enabled: true
      parameters:
        threshold: 10
        allow_exceptions: true

  suppression_comments:
    - "# ONEX_EXCLUDE: YOUR_VALIDATOR_ID"
    - "# noqa: YOUR_VALIDATOR_ID"
    - "# YOUR_VALIDATOR_ID-ok:"

  severity_default: error
  fail_on_error: true
  fail_on_warning: false
  max_violations: 0
  parallel_execution: true
```

---

## Validation Rules

The Pydantic model enforces these constraints:

1. **target_patterns must not be empty** - A validator without targets validates nothing
2. **Rule IDs must be unique** - No duplicate rule_id values within a contract
3. **fail_on_warning implies fail_on_error** - Cannot fail on warnings but not errors
4. **Suppression patterns must not be empty strings** - Would match every line
5. **source_root must not contain path traversal** - Security validation for `..`, `//`, etc.

---

## Thread Safety Notes

- `ModelValidatorSubcontract` instances are **immutable** (`frozen=True`)
- Safe to share contract instances across threads
- Validator instances (`ValidatorBase` subclasses) are **NOT thread-safe**
- For parallel execution, create separate validator instances per worker

---

## Available Validators in omnibase-core

| Validator ID | File | Purpose |
|--------------|------|---------|
| `any_type` | `any_type.validation.yaml` | Detects `Any` type usage |
| `pydantic_conventions` | `pydantic_conventions.validation.yaml` | Enforces Pydantic model config standards |
| `patterns` | `patterns.validation.yaml` | Code patterns and complexity |
| `architecture` | `architecture.validation.yaml` | One-model-per-file architecture |
| `naming_convention` | `naming_convention.validation.yaml` | File/class/function naming |
| `enum-governance` | `enum-governance.validation.yaml` | Enum standards |
| `union_usage` | `union_usage.validation.yaml` | Union type patterns |
| `contract_linter` | `contract_linter.validation.yaml` | Contract YAML validation |

---

## Usage

### Programmatic

```python
from pathlib import Path
from omnibase_core.validation.validator_any_type import AnyTypeValidator

validator = AnyTypeValidator()
result = validator.validate(Path("src/"))

if not result.is_valid:
    for issue in result.issues:
        print(f"{issue.file_path}:{issue.line_number}: {issue.message}")
```

### CLI

```bash
# Run any_type validator on src/
python -m omnibase_core.validation.validator_any_type src/

# With custom contract
python -m omnibase_core.validation.validator_any_type src/ --contract my_contract.yaml

# Verbose output
python -m omnibase_core.validation.validator_any_type src/ -v
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (no errors or failing conditions) |
| 1 | Errors found (ERROR or CRITICAL severity) |
| 2 | Warnings found (when `fail_on_warning: true`) |

---

**Last Updated**: 2026-01-23
**omnibase-core Version**: 0.8.x
