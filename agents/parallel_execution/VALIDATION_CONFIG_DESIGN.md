# Validation Configuration System Design

**Version:** 1.0.0
**Status:** Design Phase
**Target:** Phase 5 Code Validation - Parallel Execution Framework

## Table of Contents

1. [Overview](#overview)
2. [Configuration Schema](#configuration-schema)
3. [Rule Categories](#rule-categories)
4. [Implementation Architecture](#implementation-architecture)
5. [Usage Examples](#usage-examples)
6. [Integration Guide](#integration-guide)
7. [Performance Considerations](#performance-considerations)
8. [Migration Path](#migration-path)

---

## Overview

### Purpose

The Validation Configuration System provides a flexible, extensible framework for code quality validation in Phase 5 of the parallel execution workflow. It integrates existing ONEX pre-commit hooks, supports AI quality quorum consensus, and enables intelligent auto-fix capabilities with configurable retry loops.

### Key Features

- **Hierarchical Configuration**: Global → Project → Local overrides
- **Granular Control**: Enable/disable individual rules with custom parameters
- **Severity Levels**: Error, Warning, Info with configurable thresholds
- **AI Quorum Integration**: Multi-model consensus with weighted voting
- **Auto-Fix Capabilities**: Intelligent correction with retry validation
- **Performance Optimized**: Parallel rule execution with caching
- **Extensible**: Plugin architecture for custom rules

### Design Principles

1. **Configuration as Code**: All validation rules versioned and reviewable
2. **Fail Fast**: Critical errors block immediately, warnings accumulate
3. **Developer Experience**: Clear messages, actionable fixes, minimal friction
4. **Production Ready**: Strict CI/CD validation, permissive local development
5. **ONEX Compliance**: Native integration with existing hooks and patterns

---

## Configuration Schema

### File Structure

```
project_root/
├── .validation/
│   ├── rules.yaml              # Main validation configuration
│   ├── quorum.yaml             # AI quorum model configuration
│   ├── overrides/              # Project-specific overrides
│   │   ├── strict.yaml         # CI/CD strict validation
│   │   ├── permissive.yaml     # Development permissive validation
│   │   └── custom.yaml         # Project-specific rules
│   └── plugins/                # Custom rule plugins
│       └── my_custom_rule.py
```

### Schema Version 1.0

```yaml
schema_version: "1.0.0"
config_name: "default"
description: "Default validation configuration for ONEX parallel execution"

# Global validation settings
validation:
  enabled: true
  fail_on_error: true
  fail_on_warning: false
  max_retries: 3
  retry_strategy: "progressive"  # progressive, immediate, exponential

  # Performance settings
  parallel_execution: true
  max_concurrent_rules: 5
  timeout_per_rule_seconds: 30
  cache_results: true
  cache_ttl_seconds: 3600

# Severity level configuration
severity_levels:
  error:
    enabled: true
    block_execution: true
    require_fix: true
  warning:
    enabled: true
    block_execution: false
    require_fix: false
  info:
    enabled: true
    block_execution: false
    require_fix: false

# Rule categories and individual rules
rule_categories:
  onex_compliance:
    enabled: true
    description: "ONEX architecture compliance rules"
    rules:
      - rule_id: "onex-001"
        name: "Single Class Per File"
        enabled: true
        severity: "error"
        description: "Enforce one class per file for ONEX node pattern compliance"
        auto_fix: true
        parameters:
          allow_nested_classes: false
          allow_helper_classes: false
          exceptions: ["__init__.py", "test_*.py"]

      - rule_id: "onex-002"
        name: "Node Naming Convention"
        enabled: true
        severity: "error"
        description: "Validate Node<Name><Type> naming pattern"
        auto_fix: true
        parameters:
          valid_types: ["Effect", "Compute", "Reducer", "Orchestrator"]
          file_pattern: "node_*_{type}.py"
          class_pattern: "Node{Name}{Type}"

      - rule_id: "onex-003"
        name: "Contract Validation"
        enabled: true
        severity: "error"
        description: "Ensure proper contract usage and type annotations"
        auto_fix: false
        parameters:
          require_contracts: true
          valid_contract_bases: ["ModelContractBase", "ModelContractEffect", "ModelContractCompute"]
          enforce_type_hints: true

      - rule_id: "onex-004"
        name: "No Stub Implementations"
        enabled: true
        severity: "error"
        description: "Detect and prevent stub/placeholder implementations"
        auto_fix: false
        parameters:
          stub_patterns:
            - "pass"
            - "NotImplementedError"
            - "TODO"
            - "FIXME"
          allowed_in_abstract: true
          allowed_in_tests: false

  code_quality:
    enabled: true
    description: "General code quality rules"
    rules:
      - rule_id: "quality-001"
        name: "Pydantic Model Validation"
        enabled: true
        severity: "warning"
        description: "Validate Pydantic model definitions and usage"
        auto_fix: true
        parameters:
          require_field_descriptions: true
          enforce_validators: false
          check_default_values: true

      - rule_id: "quality-002"
        name: "Type Annotation Coverage"
        enabled: true
        severity: "warning"
        description: "Ensure comprehensive type annotations"
        auto_fix: false
        parameters:
          min_coverage_percent: 90
          require_return_types: true
          require_parameter_types: true
          exclude_patterns: ["test_*.py", "__init__.py"]

      - rule_id: "quality-003"
        name: "Import Organization"
        enabled: true
        severity: "info"
        description: "Enforce import sorting and organization"
        auto_fix: true
        parameters:
          sort_imports: true
          group_imports: true
          remove_unused: true

  precommit_hooks:
    enabled: true
    description: "Integration with existing ONEX pre-commit hooks"
    inherit_from: ".pre-commit-config.yaml"
    rules:
      - rule_id: "hook-001"
        name: "Pre-commit Hook Execution"
        enabled: true
        severity: "error"
        description: "Run all enabled pre-commit hooks"
        auto_fix: true
        parameters:
          hook_ids: ["all"]  # or specific: ["mypy", "black", "isort"]
          skip_on_no_changes: true
          continue_on_failure: false

  custom_rules:
    enabled: true
    description: "Project-specific custom validation rules"
    plugin_directory: ".validation/plugins"
    rules: []  # Populated by plugin discovery

# AI Quality Quorum Configuration
quorum:
  enabled: true
  description: "Multi-model consensus for code quality validation"

  # Quorum execution settings
  execution:
    mode: "consensus"  # consensus, unanimous, weighted
    min_agreement_threshold: 0.67  # 67% for 2/3 models
    timeout_seconds: 60
    parallel_execution: true

  # Model configuration
  models:
    - model_id: "gemini-flash"
      weight: 1.0
      endpoint: "http://192.168.86.200:11434"
      enabled: true
      specialization: "general_quality"

    - model_id: "codestral"
      weight: 1.5
      endpoint: "http://192.168.86.200:11434"
      enabled: true
      specialization: "code_structure"

    - model_id: "deepseek-lite"
      weight: 2.0
      endpoint: "http://192.168.86.43:11434"
      enabled: true
      specialization: "advanced_patterns"

  # Voting configuration
  voting:
    strategy: "weighted"  # simple, weighted, ranked
    consensus_threshold: 0.80  # 80% confidence for auto-apply
    review_threshold: 0.60     # 60% confidence for suggest with review
    rejection_threshold: 0.40  # Below 40% is rejected

  # Quality assessment criteria
  assessment_criteria:
    - criterion: "onex_compliance"
      weight: 0.30
      description: "ONEX architecture pattern compliance"

    - criterion: "code_quality"
      weight: 0.25
      description: "General code quality and best practices"

    - criterion: "type_safety"
      weight: 0.20
      description: "Type annotation coverage and correctness"

    - criterion: "maintainability"
      weight: 0.15
      description: "Code maintainability and readability"

    - criterion: "performance"
      weight: 0.10
      description: "Performance implications and optimization"

# Auto-fix configuration
auto_fix:
  enabled: true
  max_fix_attempts: 3
  strategy: "progressive"  # progressive, aggressive, conservative

  # Fix generation settings
  generation:
    use_quorum: true
    min_confidence: 0.75
    preserve_semantics: true
    verify_after_fix: true

  # Fix application settings
  application:
    create_backup: true
    backup_directory: ".validation/backups"
    rollback_on_failure: true
    verify_compilation: true

# Reporting configuration
reporting:
  enabled: true
  format: "detailed"  # minimal, standard, detailed, json

  output:
    console: true
    file: ".validation/reports/latest.json"
    archive: true
    archive_directory: ".validation/reports/archive"

  metrics:
    track_performance: true
    track_fix_success_rate: true
    track_quorum_agreement: true

  notifications:
    enabled: false
    on_failure: true
    on_warning: false
    channels: []  # slack, email, webhook

# Integration settings
integration:
  ci_cd:
    enabled: true
    strict_mode: true
    block_on_error: true
    block_on_warning: true

  git_hooks:
    enabled: true
    hook_types: ["pre-commit", "pre-push"]

  ide:
    enabled: true
    real_time_validation: true
    show_inline_errors: true
```

---

## Rule Categories

### 1. ONEX Compliance Rules

**Purpose**: Enforce ONEX architecture patterns and conventions

#### ONEX-001: Single Class Per File
```yaml
rule_id: "onex-001"
category: "onex_compliance"
severity: "error"
auto_fix: true

validation:
  - Check: File contains exactly one class definition
  - Exception: Nested classes within ONEX node classes
  - Exception: Helper dataclasses in model files
  - Exception: Test files (test_*.py)

fix_strategy:
  - Extract additional classes to separate files
  - Maintain import paths and references
  - Update __init__.py exports
  - Preserve docstrings and type hints

quorum_assessment:
  - Architectural compliance: High priority
  - Code organization: Medium priority
  - Maintainability impact: High priority
```

#### ONEX-002: Node Naming Convention
```yaml
rule_id: "onex-002"
category: "onex_compliance"
severity: "error"
auto_fix: true

validation:
  - Pattern: Node<Name><Type> for classes
  - Pattern: node_*_{type}.py for files
  - Valid types: Effect, Compute, Reducer, Orchestrator
  - Consistency check: Class name matches file name

fix_strategy:
  - Rename class to follow convention
  - Rename file to match class name
  - Update all import references
  - Update type annotations and contracts

parameters:
  enforce_suffix: true
  valid_types: ["Effect", "Compute", "Reducer", "Orchestrator"]
  allow_base_classes: true
```

#### ONEX-003: Contract Validation
```yaml
rule_id: "onex-003"
category: "onex_compliance"
severity: "error"
auto_fix: false

validation:
  - All node methods use proper contract types
  - Contract inheritance is correct
  - Type hints reference valid contract models
  - Contract validation in method signatures

fix_strategy:
  - Manual intervention required
  - Suggest correct contract type
  - Provide template for proper usage

parameters:
  require_contracts: true
  enforce_type_hints: true
  valid_contract_bases:
    - ModelContractBase
    - ModelContractEffect
    - ModelContractCompute
    - ModelContractReducer
    - ModelContractOrchestrator
```

#### ONEX-004: No Stub Implementations
```yaml
rule_id: "onex-004"
category: "onex_compliance"
severity: "error"
auto_fix: false

validation:
  - Detect pass statements in concrete implementations
  - Detect NotImplementedError in non-abstract methods
  - Detect TODO/FIXME comments in critical code
  - Verify methods have meaningful implementations

detection_patterns:
  - "^\\s+pass\\s*$"
  - "raise NotImplementedError"
  - "# TODO:"
  - "# FIXME:"
  - "return None  # Not implemented"

exceptions:
  allowed_in_abstract: true
  allowed_in_tests: false
  allowed_in_protocols: true
```

### 2. Code Quality Rules

#### QUALITY-001: Pydantic Model Validation
```yaml
rule_id: "quality-001"
category: "code_quality"
severity: "warning"
auto_fix: true

validation:
  - Field descriptions present
  - Validators properly defined
  - Default values are sensible
  - Config class properly configured

fix_strategy:
  - Add missing field descriptions
  - Suggest validators for complex types
  - Add Config class if missing
  - Fix validator decorators

parameters:
  require_field_descriptions: true
  enforce_validators: false
  check_default_values: true
  require_config_class: false
```

#### QUALITY-002: Type Annotation Coverage
```yaml
rule_id: "quality-002"
category: "code_quality"
severity: "warning"
auto_fix: false

validation:
  - Calculate type annotation coverage
  - Check return type annotations
  - Check parameter type annotations
  - Verify generic type usage

metrics:
  min_coverage_percent: 90
  exclude_patterns: ["test_*.py", "__init__.py"]

reporting:
  show_coverage_report: true
  show_missing_annotations: true
  suggest_type_hints: true
```

#### QUALITY-003: Import Organization
```yaml
rule_id: "quality-003"
category: "code_quality"
severity: "info"
auto_fix: true

validation:
  - Imports are sorted (isort)
  - Imports are grouped (stdlib, third-party, local)
  - Unused imports removed
  - Circular imports detected

fix_strategy:
  - Run isort with project config
  - Remove unused imports
  - Reorganize import groups
  - Add missing __future__ imports

parameters:
  sort_imports: true
  group_imports: true
  remove_unused: true
  line_length: 100
```

### 3. Pre-commit Hook Integration

#### HOOK-001: Pre-commit Hook Execution
```yaml
rule_id: "hook-001"
category: "precommit_hooks"
severity: "error"
auto_fix: true

validation:
  - Execute configured pre-commit hooks
  - Collect hook results and violations
  - Apply auto-fixes from hooks
  - Report hook execution status

execution:
  inherit_from: ".pre-commit-config.yaml"
  hook_ids: ["all"]
  skip_on_no_changes: true
  continue_on_failure: false

integration:
  apply_hook_fixes: true
  preserve_hook_config: true
  merge_hook_reports: true
```

### 4. Custom Rules Support

#### Plugin Architecture
```python
# .validation/plugins/my_custom_rule.py
from validation_framework import ValidationRule, ValidationResult, Severity

class MyCustomRule(ValidationRule):
    """Custom validation rule for project-specific requirements."""

    rule_id = "custom-001"
    category = "custom_rules"
    name = "My Custom Rule"
    description = "Enforce project-specific pattern"
    severity = Severity.WARNING
    auto_fix = True

    def validate(self, file_path: str, content: str) -> ValidationResult:
        """Validate file content against custom rule."""
        violations = []

        # Custom validation logic
        if "bad_pattern" in content:
            violations.append({
                "line": self._find_line_number(content, "bad_pattern"),
                "message": "Bad pattern detected",
                "suggestion": "Use good_pattern instead"
            })

        return ValidationResult(
            rule_id=self.rule_id,
            passed=len(violations) == 0,
            violations=violations
        )

    def auto_fix(self, file_path: str, content: str) -> str:
        """Apply automatic fix to violations."""
        return content.replace("bad_pattern", "good_pattern")
```

---

## Implementation Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Validation Orchestrator                   │
│  - Load configuration hierarchy                              │
│  - Coordinate rule execution                                 │
│  - Manage retry loops                                        │
│  - Generate reports                                          │
└──────────────┬──────────────────────────────┬────────────────┘
               │                              │
    ┌──────────▼──────────┐      ┌───────────▼──────────┐
    │  Config Loader      │      │  Rule Executor       │
    │  - Parse YAML/JSON  │      │  - Parallel exec     │
    │  - Validate schema  │      │  - Timeout handling  │
    │  - Merge overrides  │      │  - Result collection │
    └──────────┬──────────┘      └───────────┬──────────┘
               │                              │
    ┌──────────▼──────────┐      ┌───────────▼──────────┐
    │  Rule Registry      │      │  Quorum Validator    │
    │  - Built-in rules   │      │  - Model management  │
    │  - Plugin discovery │      │  - Consensus voting  │
    │  - Rule metadata    │      │  - Result synthesis  │
    └──────────┬──────────┘      └───────────┬──────────┘
               │                              │
    ┌──────────▼──────────┐      ┌───────────▼──────────┐
    │  Fix Generator      │      │  Report Generator    │
    │  - AI-assisted fix  │      │  - Multiple formats  │
    │  - Template-based   │      │  - Metrics tracking  │
    │  - Verification     │      │  - Archiving         │
    └─────────────────────┘      └──────────────────────┘
```

### Core Classes

#### 1. ValidationOrchestrator

```python
from typing import List, Dict, Optional
from pathlib import Path
from dataclasses import dataclass
from enum import Enum

class ValidationMode(Enum):
    STRICT = "strict"
    PERMISSIVE = "permissive"
    CUSTOM = "custom"

@dataclass
class ValidationContext:
    """Context for validation execution."""
    mode: ValidationMode
    file_paths: List[Path]
    config: Dict
    retry_count: int = 0
    previous_violations: Optional[List] = None

class ValidationOrchestrator:
    """
    Main orchestrator for validation execution.

    Responsibilities:
    - Load and merge configuration hierarchy
    - Coordinate rule execution with parallelization
    - Manage retry loops with progressive strategies
    - Generate comprehensive reports
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        mode: ValidationMode = ValidationMode.STRICT
    ):
        self.config_loader = ConfigLoader()
        self.rule_registry = RuleRegistry()
        self.rule_executor = RuleExecutor()
        self.quorum_validator = QuorumValidator()
        self.fix_generator = FixGenerator()
        self.report_generator = ReportGenerator()

        # Load configuration
        self.config = self._load_config(config_path, mode)

        # Initialize components
        self._initialize_components()

    def validate(
        self,
        file_paths: List[Path],
        context: Optional[ValidationContext] = None
    ) -> ValidationReport:
        """
        Execute validation workflow with retry loop.

        Workflow:
        1. Load and validate configuration
        2. Discover and filter applicable rules
        3. Execute rules in parallel batches
        4. Collect and aggregate results
        5. Run AI quorum validation if enabled
        6. Generate fixes for violations
        7. Apply fixes and retry validation
        8. Generate comprehensive report
        """
        if context is None:
            context = ValidationContext(
                mode=ValidationMode.STRICT,
                file_paths=file_paths,
                config=self.config
            )

        max_retries = self.config.validation.max_retries

        for attempt in range(max_retries + 1):
            # Execute validation
            results = self._execute_validation(file_paths, context)

            # Check if validation passed
            if results.passed:
                return self._generate_report(results, context)

            # If last attempt, return failure
            if attempt == max_retries:
                return self._generate_report(results, context, failed=True)

            # Generate and apply fixes
            fixes = self._generate_fixes(results, context)
            self._apply_fixes(fixes, context)

            # Update context for retry
            context.retry_count = attempt + 1
            context.previous_violations = results.violations

        # Should not reach here
        raise RuntimeError("Validation retry loop exceeded maximum attempts")

    def _execute_validation(
        self,
        file_paths: List[Path],
        context: ValidationContext
    ) -> ValidationResults:
        """Execute all enabled rules against file paths."""
        # Get applicable rules
        rules = self.rule_registry.get_enabled_rules(
            categories=self.config.enabled_categories
        )

        # Execute rules in parallel
        results = self.rule_executor.execute_parallel(
            rules=rules,
            file_paths=file_paths,
            max_concurrent=self.config.validation.max_concurrent_rules
        )

        # Run quorum validation if enabled
        if self.config.quorum.enabled:
            quorum_results = self.quorum_validator.validate(
                results=results,
                context=context
            )
            results = self._merge_results(results, quorum_results)

        return results
```

#### 2. ConfigLoader

```python
from pathlib import Path
from typing import Dict, Any, Optional
import yaml
from jsonschema import validate, ValidationError

class ConfigLoader:
    """
    Configuration loader with hierarchy support.

    Configuration hierarchy (highest to lowest priority):
    1. CLI flags
    2. Local override (.validation/overrides/local.yaml)
    3. Project config (.validation/rules.yaml)
    4. Global defaults (~/.claude/validation/defaults.yaml)
    """

    SCHEMA_VERSION = "1.0.0"

    def __init__(self):
        self.schema = self._load_schema()
        self.cache: Dict[str, Any] = {}

    def load(
        self,
        config_path: Optional[Path] = None,
        mode: ValidationMode = ValidationMode.STRICT,
        overrides: Optional[Dict] = None
    ) -> Dict:
        """Load and merge configuration hierarchy."""
        # Build configuration hierarchy
        configs = []

        # 1. Global defaults
        global_config = self._load_global_defaults()
        if global_config:
            configs.append(global_config)

        # 2. Project config
        if config_path and config_path.exists():
            project_config = self._load_yaml(config_path)
            configs.append(project_config)

        # 3. Mode-specific overrides
        mode_config = self._load_mode_config(mode)
        if mode_config:
            configs.append(mode_config)

        # 4. CLI overrides
        if overrides:
            configs.append(overrides)

        # Merge configurations
        merged = self._merge_configs(configs)

        # Validate against schema
        self._validate_schema(merged)

        return merged

    def _merge_configs(self, configs: List[Dict]) -> Dict:
        """Deep merge configuration dictionaries."""
        result = {}

        for config in configs:
            self._deep_merge(result, config)

        return result

    def _deep_merge(self, base: Dict, override: Dict) -> None:
        """Recursively merge override into base."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value
```

#### 3. RuleExecutor

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict
from pathlib import Path

class RuleExecutor:
    """
    Parallel rule execution engine.

    Features:
    - Parallel execution with configurable concurrency
    - Timeout handling per rule
    - Result caching with TTL
    - Performance metrics tracking
    """

    def __init__(self, max_workers: int = 5):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.cache = ResultCache()
        self.metrics = ExecutionMetrics()

    async def execute_parallel(
        self,
        rules: List[ValidationRule],
        file_paths: List[Path],
        max_concurrent: int = 5
    ) -> ValidationResults:
        """Execute rules in parallel with concurrency limit."""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def execute_with_semaphore(rule: ValidationRule, file_path: Path):
            async with semaphore:
                return await self._execute_rule(rule, file_path)

        # Create tasks for all rule-file combinations
        tasks = []
        for rule in rules:
            for file_path in file_paths:
                # Check cache
                cache_key = self._get_cache_key(rule, file_path)
                if cached := self.cache.get(cache_key):
                    continue

                task = execute_with_semaphore(rule, file_path)
                tasks.append(task)

        # Execute all tasks
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results
        return self._aggregate_results(results)

    async def _execute_rule(
        self,
        rule: ValidationRule,
        file_path: Path
    ) -> RuleResult:
        """Execute single rule with timeout."""
        start_time = time.time()

        try:
            # Read file content
            content = file_path.read_text()

            # Execute rule validation
            result = await asyncio.wait_for(
                rule.validate(file_path, content),
                timeout=rule.timeout_seconds
            )

            # Track metrics
            duration = time.time() - start_time
            self.metrics.record_execution(rule.rule_id, duration, result.passed)

            # Cache result
            cache_key = self._get_cache_key(rule, file_path)
            self.cache.set(cache_key, result)

            return result

        except asyncio.TimeoutError:
            return RuleResult(
                rule_id=rule.rule_id,
                passed=False,
                error=f"Rule execution timeout after {rule.timeout_seconds}s"
            )
        except Exception as e:
            return RuleResult(
                rule_id=rule.rule_id,
                passed=False,
                error=f"Rule execution failed: {str(e)}"
            )
```

#### 4. QuorumValidator

```python
from typing import List, Dict
import asyncio

class QuorumValidator:
    """
    AI Quality Quorum validator for multi-model consensus.

    Features:
    - Weighted voting based on model specialization
    - Confidence threshold-based decisions
    - Parallel model querying
    - Consensus synthesis and reporting
    """

    def __init__(self, config: Dict):
        self.config = config
        self.models = self._initialize_models(config.models)
        self.voting_strategy = VotingStrategy(config.voting)

    async def validate(
        self,
        results: ValidationResults,
        context: ValidationContext
    ) -> QuorumResults:
        """
        Run AI quorum validation on rule results.

        Workflow:
        1. Filter violations requiring quorum review
        2. Query all models in parallel
        3. Collect and normalize responses
        4. Apply voting strategy for consensus
        5. Generate confidence scores and recommendations
        """
        # Filter violations for quorum review
        violations_for_review = self._filter_violations(results)

        if not violations_for_review:
            return QuorumResults(
                enabled=False,
                message="No violations require quorum review"
            )

        # Query models in parallel
        model_responses = await self._query_models(violations_for_review, context)

        # Apply voting strategy
        consensus = self.voting_strategy.calculate_consensus(
            model_responses,
            threshold=self.config.voting.consensus_threshold
        )

        # Generate recommendations
        recommendations = self._generate_recommendations(consensus)

        return QuorumResults(
            enabled=True,
            consensus=consensus,
            recommendations=recommendations,
            model_responses=model_responses
        )

    async def _query_models(
        self,
        violations: List[Violation],
        context: ValidationContext
    ) -> List[ModelResponse]:
        """Query all enabled models in parallel."""
        tasks = []

        for model in self.models:
            if model.enabled:
                task = self._query_model(model, violations, context)
                tasks.append(task)

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter successful responses
        return [r for r in responses if isinstance(r, ModelResponse)]

    async def _query_model(
        self,
        model: QuorumModel,
        violations: List[Violation],
        context: ValidationContext
    ) -> ModelResponse:
        """Query single model for quality assessment."""
        prompt = self._build_assessment_prompt(violations, context)

        try:
            response = await model.query(
                prompt=prompt,
                timeout=self.config.execution.timeout_seconds
            )

            return ModelResponse(
                model_id=model.model_id,
                weight=model.weight,
                assessment=response.assessment,
                confidence=response.confidence,
                recommendations=response.recommendations
            )

        except Exception as e:
            return ModelResponse(
                model_id=model.model_id,
                weight=0.0,
                error=f"Model query failed: {str(e)}"
            )
```

#### 5. FixGenerator

```python
from typing import List, Dict, Optional
from pathlib import Path

class FixGenerator:
    """
    Intelligent fix generation for validation violations.

    Strategies:
    - Template-based fixes for known patterns
    - AI-assisted fixes using quorum recommendations
    - Semantic-preserving transformations
    - Verification before application
    """

    def __init__(self, config: Dict, quorum: Optional[QuorumValidator] = None):
        self.config = config
        self.quorum = quorum
        self.templates = FixTemplates()

    def generate_fixes(
        self,
        results: ValidationResults,
        context: ValidationContext
    ) -> List[ProposedFix]:
        """Generate fixes for all fixable violations."""
        fixes = []

        for violation in results.violations:
            if not violation.rule.auto_fix:
                continue

            # Try template-based fix first
            template_fix = self._try_template_fix(violation)
            if template_fix and template_fix.confidence >= 0.9:
                fixes.append(template_fix)
                continue

            # Try AI-assisted fix if quorum enabled
            if self.config.auto_fix.use_quorum and self.quorum:
                ai_fix = self._generate_ai_fix(violation, context)
                if ai_fix and ai_fix.confidence >= self.config.auto_fix.min_confidence:
                    fixes.append(ai_fix)
                    continue

            # Fallback to simple fix or skip
            if template_fix:
                fixes.append(template_fix)

        return fixes

    def _try_template_fix(self, violation: Violation) -> Optional[ProposedFix]:
        """Attempt template-based fix for common patterns."""
        template = self.templates.get(violation.rule_id)

        if not template:
            return None

        try:
            fixed_content = template.apply(
                content=violation.file_content,
                violation=violation
            )

            return ProposedFix(
                violation=violation,
                strategy="template",
                fixed_content=fixed_content,
                confidence=0.95,
                description=template.description
            )

        except Exception as e:
            return None

    def _generate_ai_fix(
        self,
        violation: Violation,
        context: ValidationContext
    ) -> Optional[ProposedFix]:
        """Generate AI-assisted fix using quorum consensus."""
        # Query quorum for fix recommendation
        quorum_result = self.quorum.get_fix_recommendation(
            violation=violation,
            context=context
        )

        if quorum_result.confidence < self.config.auto_fix.min_confidence:
            return None

        return ProposedFix(
            violation=violation,
            strategy="ai_assisted",
            fixed_content=quorum_result.fixed_content,
            confidence=quorum_result.confidence,
            description=quorum_result.explanation,
            quorum_consensus=quorum_result.consensus
        )
```

---

## Usage Examples

### Example 1: Strict CI/CD Configuration

```yaml
# .validation/overrides/strict.yaml
schema_version: "1.0.0"
config_name: "ci-strict"
description: "Strict validation for CI/CD pipeline"

validation:
  enabled: true
  fail_on_error: true
  fail_on_warning: true  # Block on warnings too
  max_retries: 1  # Limited retries in CI
  retry_strategy: "immediate"

severity_levels:
  error:
    enabled: true
    block_execution: true
    require_fix: true
  warning:
    enabled: true
    block_execution: true  # Warnings block in CI
    require_fix: true
  info:
    enabled: true
    block_execution: false
    require_fix: false

rule_categories:
  onex_compliance:
    enabled: true
    rules:
      - rule_id: "onex-001"
        enabled: true
        severity: "error"
      - rule_id: "onex-002"
        enabled: true
        severity: "error"
      - rule_id: "onex-003"
        enabled: true
        severity: "error"
      - rule_id: "onex-004"
        enabled: true
        severity: "error"

  code_quality:
    enabled: true
    rules:
      - rule_id: "quality-001"
        enabled: true
        severity: "error"  # Upgrade to error in CI
      - rule_id: "quality-002"
        enabled: true
        severity: "error"
        parameters:
          min_coverage_percent: 95  # Stricter in CI

quorum:
  enabled: true
  voting:
    consensus_threshold: 0.90  # Higher threshold for CI
    review_threshold: 0.80
    rejection_threshold: 0.50

auto_fix:
  enabled: false  # No auto-fix in CI, require manual fixes

reporting:
  format: "detailed"
  output:
    console: true
    file: "/tmp/validation-report.json"
  notifications:
    enabled: true
    on_failure: true
    channels: ["slack"]
```

### Example 2: Permissive Development Configuration

```yaml
# .validation/overrides/permissive.yaml
schema_version: "1.0.0"
config_name: "dev-permissive"
description: "Permissive validation for local development"

validation:
  enabled: true
  fail_on_error: false  # Don't block on errors
  fail_on_warning: false
  max_retries: 5  # More retries for auto-fix
  retry_strategy: "progressive"

severity_levels:
  error:
    enabled: true
    block_execution: false  # Don't block, just warn
    require_fix: false
  warning:
    enabled: true
    block_execution: false
    require_fix: false
  info:
    enabled: false  # Skip info level in dev

rule_categories:
  onex_compliance:
    enabled: true
    rules:
      - rule_id: "onex-001"
        enabled: true
        severity: "warning"  # Downgrade to warning
        auto_fix: true
      - rule_id: "onex-004"
        enabled: false  # Allow stubs in dev

  code_quality:
    enabled: true
    rules:
      - rule_id: "quality-002"
        enabled: true
        parameters:
          min_coverage_percent: 70  # Lower threshold

quorum:
  enabled: false  # Disable quorum for speed in dev

auto_fix:
  enabled: true
  strategy: "aggressive"  # More aggressive auto-fix
  generation:
    min_confidence: 0.60  # Lower confidence threshold

reporting:
  format: "minimal"
  output:
    console: true
    file: null  # No file output in dev
```

### Example 3: Custom Project Rules

```yaml
# .validation/overrides/custom.yaml
schema_version: "1.0.0"
config_name: "project-custom"
description: "Custom validation rules for this project"

rule_categories:
  custom_rules:
    enabled: true
    description: "Project-specific validation rules"
    plugin_directory: ".validation/plugins"
    rules:
      - rule_id: "custom-001"
        name: "API Versioning Check"
        enabled: true
        severity: "error"
        description: "Ensure all API endpoints have version prefix"
        auto_fix: false
        parameters:
          version_pattern: "/api/v\\d+/"
          exclude_paths: ["/health", "/metrics"]

      - rule_id: "custom-002"
        name: "Database Migration Validation"
        enabled: true
        severity: "error"
        description: "Validate database migration files"
        auto_fix: false
        parameters:
          migration_directory: "migrations/"
          require_rollback: true
          naming_pattern: "\\d{14}_.*\\.py"

      - rule_id: "custom-003"
        name: "Environment Variable Documentation"
        enabled: true
        severity: "warning"
        description: "Ensure env vars are documented in .env.example"
        auto_fix: true
        parameters:
          env_file: ".env.example"
          check_usage_in: ["*.py", "docker-compose.yml"]
```

### Example 4: Quorum Model Selection

```yaml
# .validation/quorum.yaml
schema_version: "1.0.0"
config_name: "quorum-config"
description: "AI Quality Quorum model configuration"

quorum:
  enabled: true

  execution:
    mode: "weighted"  # Use weighted voting
    min_agreement_threshold: 0.67
    timeout_seconds: 90
    parallel_execution: true

  models:
    # Fast model for general quality checks
    - model_id: "gemini-flash"
      weight: 1.0
      endpoint: "http://192.168.86.200:11434"
      enabled: true
      specialization: "general_quality"
      parameters:
        temperature: 0.1
        max_tokens: 2000

    # Code structure specialist
    - model_id: "codestral"
      weight: 1.5
      endpoint: "http://192.168.86.200:11434"
      enabled: true
      specialization: "code_structure"
      parameters:
        temperature: 0.2
        max_tokens: 3000

    # Advanced pattern recognition
    - model_id: "deepseek-lite"
      weight: 2.0
      endpoint: "http://192.168.86.43:11434"
      enabled: true
      specialization: "advanced_patterns"
      parameters:
        temperature: 0.1
        max_tokens: 4000

    # Optional: Disable specific models
    - model_id: "llama-3.1"
      weight: 1.2
      enabled: false  # Disabled for this config
      specialization: "general_reasoning"

  voting:
    strategy: "weighted"
    consensus_threshold: 0.80
    review_threshold: 0.60
    rejection_threshold: 0.40

    # Weight adjustments by criterion
    criterion_weights:
      onex_compliance: 0.30
      code_quality: 0.25
      type_safety: 0.20
      maintainability: 0.15
      performance: 0.10

  assessment_criteria:
    - criterion: "onex_compliance"
      weight: 0.30
      description: "ONEX architecture pattern compliance"
      questions:
        - "Does code follow ONEX node patterns?"
        - "Are naming conventions correct?"
        - "Are contracts properly used?"

    - criterion: "code_quality"
      weight: 0.25
      description: "General code quality and best practices"
      questions:
        - "Is code well-structured and readable?"
        - "Are best practices followed?"
        - "Is error handling appropriate?"

    - criterion: "type_safety"
      weight: 0.20
      description: "Type annotation coverage and correctness"
      questions:
        - "Are type annotations comprehensive?"
        - "Are generic types used correctly?"
        - "Is type safety maintained?"
```

---

## Integration Guide

### Adding New Rules

#### Step 1: Define Rule Class

```python
# .validation/plugins/my_new_rule.py
from validation_framework import ValidationRule, ValidationResult, Severity
from typing import List
import re

class MyNewRule(ValidationRule):
    """
    Custom validation rule for [specific requirement].

    Validates: [what this rule checks]
    Auto-fix: [whether auto-fix is supported]
    """

    # Rule metadata
    rule_id = "custom-004"
    category = "custom_rules"
    name = "My New Rule"
    description = "Detailed description of what this rule validates"
    severity = Severity.WARNING
    auto_fix = True
    timeout_seconds = 30

    def __init__(self, parameters: dict = None):
        """Initialize rule with optional parameters."""
        super().__init__(parameters)
        self.pattern = parameters.get("pattern", "default_pattern")
        self.exceptions = parameters.get("exceptions", [])

    def validate(self, file_path: Path, content: str) -> ValidationResult:
        """
        Validate file content against rule.

        Args:
            file_path: Path to file being validated
            content: File content as string

        Returns:
            ValidationResult with violations and suggestions
        """
        violations = []

        # Implement validation logic
        matches = re.finditer(self.pattern, content)

        for match in matches:
            line_number = content[:match.start()].count('\n') + 1

            # Check exceptions
            if self._is_exception(file_path, line_number):
                continue

            violations.append({
                "line": line_number,
                "column": match.start() - content.rfind('\n', 0, match.start()),
                "message": f"Pattern violation: {match.group()}",
                "suggestion": "Replace with recommended pattern",
                "severity": self.severity.value
            })

        return ValidationResult(
            rule_id=self.rule_id,
            passed=len(violations) == 0,
            violations=violations,
            metrics={
                "total_matches": len(violations),
                "lines_checked": content.count('\n') + 1
            }
        )

    def auto_fix(self, file_path: Path, content: str) -> str:
        """
        Apply automatic fix to violations.

        Args:
            file_path: Path to file being fixed
            content: Original file content

        Returns:
            Fixed file content
        """
        # Implement fix logic
        fixed_content = re.sub(
            self.pattern,
            self._get_replacement,
            content
        )

        return fixed_content

    def _is_exception(self, file_path: Path, line_number: int) -> bool:
        """Check if violation is in exception list."""
        return any(exc in str(file_path) for exc in self.exceptions)

    def _get_replacement(self, match: re.Match) -> str:
        """Get replacement text for matched pattern."""
        # Implement replacement logic
        return "replacement_text"
```

#### Step 2: Register Rule in Configuration

```yaml
# .validation/rules.yaml
rule_categories:
  custom_rules:
    enabled: true
    plugin_directory: ".validation/plugins"
    rules:
      - rule_id: "custom-004"
        name: "My New Rule"
        enabled: true
        severity: "warning"
        auto_fix: true
        parameters:
          pattern: "my_pattern"
          exceptions: ["test_*.py", "__init__.py"]
```

#### Step 3: Test Rule

```bash
# Test rule on specific file
python -m validation_framework test \
    --rule custom-004 \
    --file path/to/test/file.py

# Test rule with auto-fix
python -m validation_framework test \
    --rule custom-004 \
    --file path/to/test/file.py \
    --auto-fix \
    --dry-run
```

### Customizing Existing Rules

#### Override Rule Parameters

```yaml
# .validation/overrides/local.yaml
rule_categories:
  onex_compliance:
    rules:
      - rule_id: "onex-001"
        parameters:
          allow_nested_classes: true  # Override default
          exceptions:
            - "special_case.py"  # Add exception
```

#### Change Rule Severity

```yaml
# Downgrade error to warning for development
rule_categories:
  code_quality:
    rules:
      - rule_id: "quality-002"
        severity: "warning"  # Was "error" in default config
```

#### Disable Specific Rules

```yaml
# Temporarily disable problematic rule
rule_categories:
  onex_compliance:
    rules:
      - rule_id: "onex-004"
        enabled: false  # Disable stub detection
        reason: "Allowing stubs during prototyping phase"
```

### Per-Project Overrides

#### Create Project-Specific Config

```yaml
# project/.validation/rules.yaml
schema_version: "1.0.0"
config_name: "project-specific"
description: "Validation rules for Project X"

# Inherit from global defaults
inherit_from: "~/.claude/validation/defaults.yaml"

# Project-specific overrides
validation:
  max_retries: 3

rule_categories:
  onex_compliance:
    rules:
      - rule_id: "onex-001"
        parameters:
          exceptions:
            - "legacy/*.py"  # Exclude legacy code

  custom_rules:
    enabled: true
    rules:
      - rule_id: "project-x-001"
        name: "Project X Specific Pattern"
        enabled: true
        severity: "error"
```

### Command-Line Flags

```bash
# Use specific configuration file
python -m validation_framework validate \
    --config .validation/overrides/strict.yaml \
    --files "src/**/*.py"

# Override specific rules
python -m validation_framework validate \
    --disable-rule onex-004 \
    --enable-rule quality-003 \
    --severity quality-001=error

# Control quorum
python -m validation_framework validate \
    --quorum-enabled \
    --quorum-threshold 0.75 \
    --quorum-models gemini-flash,codestral

# Auto-fix options
python -m validation_framework validate \
    --auto-fix \
    --max-retries 5 \
    --fix-strategy aggressive

# Reporting options
python -m validation_framework validate \
    --report-format detailed \
    --report-file validation-report.json \
    --metrics
```

### IDE Integration

#### VS Code Configuration

```json
// .vscode/settings.json
{
  "validation-framework.enabled": true,
  "validation-framework.configFile": ".validation/rules.yaml",
  "validation-framework.lintOnSave": true,
  "validation-framework.autoFixOnSave": false,
  "validation-framework.showInlineErrors": true,
  "validation-framework.severity": {
    "error": "error",
    "warning": "warning",
    "info": "hint"
  },
  "validation-framework.quorum": {
    "enabled": false,  // Disable for IDE (too slow)
    "onDemand": true   // Available via command palette
  }
}
```

#### PyCharm Configuration

```xml
<!-- .idea/validation-framework.xml -->
<component name="ValidationFramework">
  <option name="enabled" value="true" />
  <option name="configFile" value=".validation/rules.yaml" />
  <option name="realTimeValidation" value="true" />
  <option name="autoFix" value="false" />
  <option name="inspectionLevel" value="error" />
</component>
```

---

## Performance Considerations

### Optimization Strategies

#### 1. Parallel Execution

```yaml
validation:
  parallel_execution: true
  max_concurrent_rules: 5  # Balance between speed and resources

  # Performance tuning
  performance:
    thread_pool_size: 8
    async_batch_size: 10
    max_file_size_mb: 5  # Skip very large files
```

#### 2. Result Caching

```yaml
validation:
  cache_results: true
  cache_ttl_seconds: 3600  # 1 hour
  cache_strategy: "file_hash"  # or "timestamp"

  cache_config:
    backend: "redis"  # or "memory", "disk"
    redis_url: "redis://localhost:6379"
    max_cache_size_mb: 100
```

#### 3. Incremental Validation

```yaml
validation:
  incremental: true

  incremental_config:
    track_changes: true
    validate_only_changed: true
    change_detection: "git"  # or "timestamp"
    baseline_commit: "main"
```

#### 4. Rule Execution Optimization

```yaml
rule_categories:
  onex_compliance:
    # Run fast rules first
    execution_order: "complexity"  # or "priority", "alphabetical"

    rules:
      - rule_id: "onex-001"
        priority: 1  # Higher priority runs first
        complexity: "low"  # Complexity estimate

      - rule_id: "onex-003"
        priority: 3
        complexity: "high"
        lazy_evaluation: true  # Skip if earlier rules fail
```

### Performance Benchmarks

```yaml
# Performance targets for validation execution
performance_targets:
  single_file_validation_ms: 100
  full_project_validation_seconds: 30
  quorum_validation_seconds: 60
  auto_fix_generation_ms: 500

  # Scaling targets
  files_per_second: 10
  rules_per_second: 100

  # Resource limits
  max_memory_mb: 500
  max_cpu_percent: 80
```

---

## Migration Path

### Phase 1: Setup and Configuration (Week 1)

**Tasks:**
1. Create `.validation/` directory structure
2. Initialize `rules.yaml` with default configuration
3. Configure `quorum.yaml` with AI model settings
4. Set up plugin directory for custom rules

**Deliverables:**
- Basic configuration files
- Documentation for team
- Initial CI/CD integration

### Phase 2: Rule Implementation (Week 2-3)

**Tasks:**
1. Implement ONEX compliance rules (ONEX-001 to ONEX-004)
2. Implement code quality rules (QUALITY-001 to QUALITY-003)
3. Integrate existing pre-commit hooks (HOOK-001)
4. Create custom project rules as needed

**Deliverables:**
- 10+ validation rules implemented
- Test suite for rules
- Auto-fix templates

### Phase 3: Quorum Integration (Week 4)

**Tasks:**
1. Set up AI model endpoints
2. Implement quorum voting logic
3. Configure consensus thresholds
4. Test multi-model validation

**Deliverables:**
- Working AI quorum system
- Quorum validation reports
- Performance benchmarks

### Phase 4: Auto-Fix and Retry (Week 5)

**Tasks:**
1. Implement fix generator
2. Create fix templates for common violations
3. Build retry loop with progressive strategies
4. Add verification after fixes

**Deliverables:**
- Auto-fix system operational
- Fix success rate >80%
- Comprehensive testing

### Phase 5: CI/CD Integration (Week 6)

**Tasks:**
1. Create strict CI/CD configuration
2. Integrate with GitHub Actions / GitLab CI
3. Set up notification system
4. Configure failure handling

**Deliverables:**
- CI/CD pipeline integration
- Automated validation on PR
- Team training complete

### Rollout Strategy

```yaml
rollout:
  phase_1_teams: ["core_dev"]
  phase_1_rules: ["onex-001", "onex-002"]
  phase_1_severity: "warning"  # Non-blocking

  phase_2_teams: ["all_developers"]
  phase_2_rules: ["all_onex", "quality-001"]
  phase_2_severity: "error"  # Blocking in dev

  phase_3_teams: ["all"]
  phase_3_rules: ["all"]
  phase_3_severity: "error"  # Blocking everywhere
  phase_3_ci: true  # Enable in CI/CD
```

---

## Appendix

### A. Complete Rule Reference

See [VALIDATION_RULES.md](./VALIDATION_RULES.md) for complete documentation of all built-in validation rules.

### B. API Reference

See [VALIDATION_API.md](./VALIDATION_API.md) for detailed API documentation for integrating validation framework into custom tools.

### C. Troubleshooting Guide

See [VALIDATION_TROUBLESHOOTING.md](./VALIDATION_TROUBLESHOOTING.md) for common issues and solutions.

### D. Schema Reference

```yaml
# JSON Schema for validation configuration
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Validation Configuration Schema",
  "version": "1.0.0",
  "type": "object",
  "required": ["schema_version", "validation"],
  "properties": {
    "schema_version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+$"
    },
    "validation": {
      "type": "object",
      "required": ["enabled"],
      "properties": {
        "enabled": {"type": "boolean"},
        "fail_on_error": {"type": "boolean"},
        "fail_on_warning": {"type": "boolean"},
        "max_retries": {"type": "integer", "minimum": 0, "maximum": 10}
      }
    }
  }
}
```

---

## Conclusion

This validation configuration system provides a comprehensive, flexible framework for code quality enforcement in the ONEX parallel execution environment. It balances developer experience with code quality requirements, supports intelligent auto-fix capabilities, and leverages AI quorum for complex validation decisions.

**Key Benefits:**
- **Configurable**: Adapt validation rules to project needs
- **Intelligent**: AI-assisted validation and auto-fix
- **Performant**: Parallel execution with caching
- **Extensible**: Plugin architecture for custom rules
- **Developer-Friendly**: Clear messages and actionable fixes

**Next Steps:**
1. Review and approve design
2. Begin Phase 1 implementation
3. Create reference implementation
4. Pilot with core development team
5. Iterate based on feedback
6. Roll out to full organization
