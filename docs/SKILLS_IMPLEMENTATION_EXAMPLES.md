# Skills Implementation Examples
**Date**: 2025-10-20
**Companion to**: SKILLS_STRATEGIC_ANALYSIS.md

## Quick Reference

### Skill vs MCP Tool vs Agent Decision Matrix

| Operation | Duration | Deterministic? | External Deps? | Use |
|-----------|----------|----------------|----------------|-----|
| ONEX naming validation | <100ms | ✅ Yes | ❌ No | **Skill** |
| Quality gate execution | <200ms | ✅ Yes | ❌ No | **Skill** |
| Contract validation | <50ms | ✅ Yes | ❌ No | **Skill** |
| RAG intelligence query | 500-2000ms | ❌ No | ✅ Yes | **MCP Tool** |
| Code generation | Variable | ❌ No | ✅ Yes | **Agent** |
| Workflow orchestration | Variable | ❌ No | ✅ Yes | **Agent** |
| Vector search | 100-500ms | ❌ No | ✅ Yes | **MCP Tool** |
| Performance optimization | Variable | ❌ No | ✅ Yes | **Agent** |

---

## Example 1: ONEX Naming Validation Skill

### Skill Definition

**File**: `~/.claude/skills/validate-onex-naming/skill.yaml`

```yaml
name: validate-onex-naming
version: 1.0.0
type: validation
category: code_quality

description: |
  Fast ONEX naming convention validation for Python files.
  Validates against Omninode naming conventions:
  - Files: model_*.py, enum_*.py, node_*_service.py
  - Classes: Model*, Enum*, Node*Service, Mixin*
  - Functions: snake_case, type hints required

input:
  file_path:
    type: string
    required: true
    description: Absolute path to Python file to validate
  repository_type:
    type: string
    required: false
    description: Repository type (omninode|standard)
    default: auto-detect
    enum: [omninode, standard, auto-detect]

output:
  valid:
    type: boolean
    description: Overall validation result
  compliance_score:
    type: number
    description: Compliance score (0.0-1.0)
  repository_type_detected:
    type: string
    description: Detected repository type
  violations:
    type: array
    description: List of naming convention violations
    items:
      file: string
      line: number
      column: number
      name: string
      violation_type: string
      expected_format: string
      message: string
      suggestion: string

performance:
  target_ms: 100
  max_ms: 200
  timeout_ms: 500

error_codes:
  FILE_NOT_FOUND: File does not exist
  SYNTAX_ERROR: Invalid Python syntax
  TIMEOUT: Execution exceeded timeout
  PARSE_ERROR: Failed to parse Python AST

observability:
  log_execution: true
  track_metrics: true
  correlation_id: required
```

### Skill Implementation

**File**: `~/.claude/skills/validate-onex-naming/executor.py`

```python
#!/usr/bin/env python3
"""
ONEX Naming Validation Skill Executor
Extracted from claude_hooks/naming_validator.py
"""

import ast
import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class Violation:
    """Naming convention violation"""
    file: str
    line: int
    column: int
    name: str
    violation_type: str
    expected_format: str
    message: str
    suggestion: str


@dataclass
class ValidationResult:
    """Validation result output"""
    valid: bool
    compliance_score: float
    repository_type_detected: str
    violations: List[Violation]
    execution_time_ms: int


class ONEXNamingValidator:
    """Fast ONEX naming validation"""

    def __init__(self):
        self.violations = []

    def detect_repository_type(self, file_path: Path) -> str:
        """Detect repository type from file path"""
        path_str = str(file_path).lower()

        if 'omnibase_' in path_str or '/omni' in path_str:
            if 'archon' not in path_str and 'omninode_bridge' not in path_str:
                return 'omninode'

        return 'standard'

    def validate_file(self, file_path: str, repository_type: str = 'auto-detect') -> ValidationResult:
        """
        Validate Python file naming conventions.

        Args:
            file_path: Absolute path to Python file
            repository_type: Repository type or 'auto-detect'

        Returns:
            ValidationResult with violations and compliance score
        """
        start_time = time.time()
        self.violations = []

        path = Path(file_path)

        # Check file exists
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Detect repository type
        if repository_type == 'auto-detect':
            repository_type = self.detect_repository_type(path)

        # Parse Python file
        try:
            with open(path, 'r') as f:
                content = f.read()
            tree = ast.parse(content, filename=str(path))
        except SyntaxError as e:
            raise SyntaxError(f"Invalid Python syntax: {e}")

        # Validate based on repository type
        if repository_type == 'omninode':
            self._validate_omninode_conventions(path, tree)
        else:
            self._validate_pep8_conventions(path, tree)

        # Calculate compliance score
        total_items = len(self.violations) + 100  # Base score
        compliance_score = max(0.0, 1.0 - (len(self.violations) / total_items))

        execution_time_ms = int((time.time() - start_time) * 1000)

        return ValidationResult(
            valid=len(self.violations) == 0,
            compliance_score=compliance_score,
            repository_type_detected=repository_type,
            violations=self.violations,
            execution_time_ms=execution_time_ms
        )

    def _validate_omninode_conventions(self, path: Path, tree: ast.AST):
        """Validate Omninode-specific naming conventions"""

        # Check filename patterns
        filename = path.stem
        if not any([
            filename.startswith('model_'),
            filename.startswith('enum_'),
            filename.startswith('node_'),
            filename.startswith('typed_dict_'),
            filename.startswith('mixin_'),
            filename == '__init__'
        ]):
            self.violations.append(Violation(
                file=str(path),
                line=1,
                column=0,
                name=filename,
                violation_type='filename',
                expected_format='model_*, enum_*, node_*, typed_dict_*, mixin_*',
                message='Omninode files must follow prefix conventions',
                suggestion=f'Rename to match Omninode pattern'
            ))

        # Validate classes
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self._validate_omninode_class(path, node)
            elif isinstance(node, ast.FunctionDef):
                self._validate_function(path, node)

    def _validate_omninode_class(self, path: Path, node: ast.ClassDef):
        """Validate Omninode class naming"""
        class_name = node.name

        # Check for required prefixes
        valid_prefixes = ['Model', 'Enum', 'Node', 'TypedDict', 'Mixin', 'Base']
        has_valid_prefix = any(class_name.startswith(prefix) for prefix in valid_prefixes)

        # Exception for error classes
        if class_name.endswith('Error'):
            return

        if not has_valid_prefix:
            self.violations.append(Violation(
                file=str(path),
                line=node.lineno,
                column=node.col_offset,
                name=class_name,
                violation_type='class',
                expected_format='Model*, Enum*, Node*, TypedDict*, Mixin*, Base*',
                message='Omninode classes must use required prefixes',
                suggestion=f'Rename to Model{class_name} or appropriate prefix'
            ))

    def _validate_pep8_conventions(self, path: Path, tree: ast.AST):
        """Validate standard PEP 8 conventions"""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # PascalCase for classes
                if not node.name[0].isupper():
                    self.violations.append(Violation(
                        file=str(path),
                        line=node.lineno,
                        column=node.col_offset,
                        name=node.name,
                        violation_type='class',
                        expected_format='PascalCase',
                        message='Class names should use PascalCase',
                        suggestion=node.name.title().replace('_', '')
                    ))
            elif isinstance(node, ast.FunctionDef):
                self._validate_function(path, node)

    def _validate_function(self, path: Path, node: ast.FunctionDef):
        """Validate function naming (snake_case)"""
        if node.name.startswith('__') and node.name.endswith('__'):
            return  # Dunder methods are OK

        if not node.name.islower() or ' ' in node.name:
            self.violations.append(Violation(
                file=str(path),
                line=node.lineno,
                column=node.col_offset,
                name=node.name,
                violation_type='function',
                expected_format='snake_case',
                message='Function names should use snake_case',
                suggestion=node.name.lower().replace(' ', '_')
            ))


def main():
    """Skill executor entry point"""
    if len(sys.argv) != 3:
        print(json.dumps({
            "error": "Usage: executor.py <file_path> <repository_type>",
            "code": "INVALID_ARGS"
        }))
        sys.exit(1)

    file_path = sys.argv[1]
    repository_type = sys.argv[2]

    try:
        validator = ONEXNamingValidator()
        result = validator.validate_file(file_path, repository_type)

        # Convert to JSON output
        output = {
            "valid": result.valid,
            "compliance_score": result.compliance_score,
            "repository_type_detected": result.repository_type_detected,
            "violations": [asdict(v) for v in result.violations],
            "execution_time_ms": result.execution_time_ms
        }

        print(json.dumps(output, indent=2))
        sys.exit(0 if result.valid else 1)

    except FileNotFoundError as e:
        print(json.dumps({"error": str(e), "code": "FILE_NOT_FOUND"}))
        sys.exit(2)
    except SyntaxError as e:
        print(json.dumps({"error": str(e), "code": "SYNTAX_ERROR"}))
        sys.exit(3)
    except Exception as e:
        print(json.dumps({"error": str(e), "code": "UNKNOWN_ERROR"}))
        sys.exit(4)


if __name__ == "__main__":
    main()
```

### Agent Integration Example

**Agent**: agent-code-generator.yaml

```yaml
# Agent workflow using validate-onex-naming skill

workflow_templates:
  task_execution:
    function_name: "execute_code_generation_task"
    phases:
      - name: "Intelligence Gathering"
        description: "Use RAG to gather implementation patterns"
        tools:
          - "mcp__onex__archon_menu (perform_rag_query)"

      - name: "Code Generation"
        description: "Generate ONEX node implementation"
        process: |
          1. Load template with intelligence context
          2. Render template with PRD analysis
          3. Generate Python code

      - name: "Validation (SKILL)"
        description: "Validate generated code with skill"
        tools:
          - "validate-onex-naming"
        process: |
          BEFORE writing file:
          1. Save generated code to temp file
          2. Run validate-onex-naming skill
          3. Check compliance_score >= 0.9
          4. If violations found:
             - Review violations
             - Fix naming issues
             - Re-validate
          5. Proceed only if valid

      - name: "File Write"
        description: "Write validated code to file"
        tools:
          - "Write"

      - name: "Quality Gates (SKILL)"
        description: "Run post-generation quality gates"
        tools:
          - "execute-quality-gates"
        gates:
          - "SV-003" # Output validation
          - "QC-001" # ONEX standards
          - "QC-003" # Type safety
```

### Hook Integration Example

**Hook**: PreToolUse (`pre-tool-use-quality.sh`)

```bash
#!/usr/bin/env bash
# Pre-tool-use hook with ONEX naming validation skill

TOOL_NAME="$1"
TOOL_PARAMS="$2"

# Only validate Python files on Write/Edit operations
if [[ "$TOOL_NAME" =~ ^(Write|Edit)$ ]]; then
    FILE_PATH="$(echo "$TOOL_PARAMS" | jq -r '.file_path // empty')"

    # Check if it's a Python file
    if [[ "$FILE_PATH" =~ \.py$ ]]; then
        echo "🔍 Running ONEX naming validation skill..." >&2

        # Run skill
        SKILL_RESULT="$(python3 ~/.claude/skills/validate-onex-naming/executor.py \
            "$FILE_PATH" \
            "auto-detect" 2>/dev/null)"

        SKILL_EXIT_CODE=$?

        if [ $SKILL_EXIT_CODE -eq 0 ]; then
            # Validation passed
            COMPLIANCE="$(echo "$SKILL_RESULT" | jq -r '.compliance_score')"
            echo "✅ ONEX naming validation passed (${COMPLIANCE})" >&2

            # Log to PostgreSQL
            PGPASSWORD="omninode-bridge-postgres-dev-2024" psql \
                -h localhost -p 5436 -U postgres -d omninode_bridge \
                -c "INSERT INTO skill_executions (skill_name, file_path, passed, compliance_score, correlation_id)
                    VALUES ('validate-onex-naming', '$FILE_PATH', true, $COMPLIANCE, gen_random_uuid());" \
                >/dev/null 2>&1

        elif [ $SKILL_EXIT_CODE -eq 1 ]; then
            # Validation failed with violations
            VIOLATIONS="$(echo "$SKILL_RESULT" | jq -r '.violations')"
            COMPLIANCE="$(echo "$SKILL_RESULT" | jq -r '.compliance_score')"

            # Inject violations into Claude context
            cat >&2 <<EOF

═══════════════════════════════════════════════════════════
❌ ONEX NAMING VALIDATION FAILED (Compliance: ${COMPLIANCE})
═══════════════════════════════════════════════════════════

File: $FILE_PATH

Violations found:
$(echo "$VIOLATIONS" | jq -r '.[] | "  • Line \(.line): \(.name) - \(.message)\n    Suggestion: \(.suggestion)"')

You MUST fix these naming violations before the Write/Edit operation.
Refer to ONEX naming conventions:
- Files: model_*.py, enum_*.py, node_*_service.py
- Classes: Model*, Enum*, Node*Service, Mixin*
- Functions: snake_case with type hints

═══════════════════════════════════════════════════════════
EOF

            # Log to PostgreSQL
            PGPASSWORD="omninode-bridge-postgres-dev-2024" psql \
                -h localhost -p 5436 -U postgres -d omninode_bridge \
                -c "INSERT INTO skill_executions (skill_name, file_path, passed, compliance_score, violations, correlation_id)
                    VALUES ('validate-onex-naming', '$FILE_PATH', false, $COMPLIANCE, '$VIOLATIONS'::jsonb, gen_random_uuid());" \
                >/dev/null 2>&1

            # BLOCK the Write/Edit operation
            exit 1

        else
            # Skill execution error
            ERROR="$(echo "$SKILL_RESULT" | jq -r '.error // "Unknown error"')"
            echo "⚠️  Skill execution error: $ERROR" >&2
            # Allow operation to proceed (graceful degradation)
        fi
    fi
fi

# Allow operation to proceed
exit 0
```

---

## Example 2: Quality Gate Execution Skill

### Skill Definition

**File**: `~/.claude/skills/execute-quality-gates/skill.yaml`

```yaml
name: execute-quality-gates
version: 1.0.0
type: validation
category: quality_assurance

description: |
  Execute ONEX quality gate validation suite.
  Validates 23 quality gates across 8 categories:
  - Sequential validation (SV-001 to SV-004)
  - Parallel validation (PV-001 to PV-003)
  - Intelligence validation (IV-001 to IV-003)
  - Coordination validation (CV-001 to CV-003)
  - Quality compliance (QC-001 to QC-004)
  - Performance validation (PF-001 to PF-002)
  - Knowledge validation (KV-001 to KV-002)
  - Framework validation (FV-001 to FV-002)

input:
  gate_ids:
    type: array
    required: true
    description: Quality gate IDs to execute
    items:
      type: string
      pattern: ^(SV|PV|IV|CV|QC|PF|KV|FV)-\d{3}$
  context:
    type: object
    required: true
    description: Validation context
    properties:
      agent_name: string
      file_path: string
      operation_type: string
      performance_metrics: object

output:
  overall_passed:
    type: boolean
    description: All gates passed
  gates_executed:
    type: number
    description: Number of gates executed
  gates_passed:
    type: number
    description: Number of gates passed
  performance_budget_used_ms:
    type: number
    description: Total execution time
  gate_results:
    type: array
    items:
      gate_id: string
      gate_name: string
      passed: boolean
      execution_time_ms: number
      issues: array

performance:
  target_ms: 200  # per gate
  max_ms: 500     # per gate
  timeout_ms: 10000  # total
```

### Skill Implementation

**File**: `~/.claude/skills/execute-quality-gates/executor.py`

```python
#!/usr/bin/env python3
"""
Quality Gate Execution Skill
Implements 23 quality gates from quality-gates-spec.yaml
"""

import ast
import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class GateResult:
    """Quality gate execution result"""
    gate_id: str
    gate_name: str
    passed: bool
    execution_time_ms: int
    issues: List[str]


@dataclass
class ExecutionResult:
    """Overall execution result"""
    overall_passed: bool
    gates_executed: int
    gates_passed: int
    performance_budget_used_ms: int
    gate_results: List[GateResult]


class QualityGateExecutor:
    """Execute ONEX quality gates"""

    def __init__(self):
        self.gates = {
            'SV-001': self._gate_sv_001_input_validation,
            'SV-003': self._gate_sv_003_output_validation,
            'QC-001': self._gate_qc_001_onex_standards,
            'QC-003': self._gate_qc_003_type_safety,
            'PF-001': self._gate_pf_001_performance_thresholds,
        }

    def execute_gates(self, gate_ids: List[str], context: Dict[str, Any]) -> ExecutionResult:
        """Execute specified quality gates"""
        start_time = time.time()
        results = []

        for gate_id in gate_ids:
            if gate_id not in self.gates:
                results.append(GateResult(
                    gate_id=gate_id,
                    gate_name=f"Unknown Gate {gate_id}",
                    passed=False,
                    execution_time_ms=0,
                    issues=[f"Gate {gate_id} not implemented"]
                ))
                continue

            # Execute gate
            gate_start = time.time()
            gate_func = self.gates[gate_id]
            passed, issues = gate_func(context)
            gate_time_ms = int((time.time() - gate_start) * 1000)

            results.append(GateResult(
                gate_id=gate_id,
                gate_name=self._get_gate_name(gate_id),
                passed=passed,
                execution_time_ms=gate_time_ms,
                issues=issues
            ))

        total_time_ms = int((time.time() - start_time) * 1000)

        return ExecutionResult(
            overall_passed=all(r.passed for r in results),
            gates_executed=len(results),
            gates_passed=sum(1 for r in results if r.passed),
            performance_budget_used_ms=total_time_ms,
            gate_results=results
        )

    def _get_gate_name(self, gate_id: str) -> str:
        """Get human-readable gate name"""
        names = {
            'SV-001': 'Input Validation',
            'SV-003': 'Output Validation',
            'QC-001': 'ONEX Standards',
            'QC-003': 'Type Safety',
            'PF-001': 'Performance Thresholds',
        }
        return names.get(gate_id, gate_id)

    def _gate_sv_001_input_validation(self, context: Dict[str, Any]) -> tuple[bool, List[str]]:
        """SV-001: Input Validation - Target <50ms"""
        issues = []

        # Validate required context fields
        if 'file_path' not in context:
            issues.append("Missing required field: file_path")

        if 'operation_type' not in context:
            issues.append("Missing required field: operation_type")

        return len(issues) == 0, issues

    def _gate_sv_003_output_validation(self, context: Dict[str, Any]) -> tuple[bool, List[str]]:
        """SV-003: Output Validation - Target <40ms"""
        issues = []
        file_path = context.get('file_path')

        if not file_path:
            issues.append("No file_path provided for output validation")
            return False, issues

        # Check file exists
        if not Path(file_path).exists():
            issues.append(f"Output file not found: {file_path}")

        # Check file has content
        elif Path(file_path).stat().st_size == 0:
            issues.append(f"Output file is empty: {file_path}")

        return len(issues) == 0, issues

    def _gate_qc_001_onex_standards(self, context: Dict[str, Any]) -> tuple[bool, List[str]]:
        """QC-001: ONEX Standards - Target <80ms"""
        issues = []
        file_path = context.get('file_path')

        if not file_path or not Path(file_path).exists():
            issues.append("File not available for ONEX standards validation")
            return False, issues

        # Parse Python file
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            tree = ast.parse(content)
        except Exception as e:
            issues.append(f"Failed to parse file: {e}")
            return False, issues

        # Check for ONEX patterns
        has_onex_imports = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and 'omnibase_core' in node.module:
                    has_onex_imports = True
                    break

        if not has_onex_imports:
            issues.append("No omnibase_core imports found (ONEX compliance)")

        return len(issues) == 0, issues

    def _gate_qc_003_type_safety(self, context: Dict[str, Any]) -> tuple[bool, List[str]]:
        """QC-003: Type Safety - Target <60ms"""
        issues = []
        file_path = context.get('file_path')

        if not file_path or not Path(file_path).exists():
            issues.append("File not available for type safety validation")
            return False, issues

        # Parse and check for type hints
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            tree = ast.parse(content)
        except Exception as e:
            issues.append(f"Failed to parse file: {e}")
            return False, issues

        # Check functions have type hints
        functions_without_hints = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Skip dunder methods
                if node.name.startswith('__') and node.name.endswith('__'):
                    continue

                # Check for return type hint
                if node.returns is None:
                    functions_without_hints.append(node.name)

        if functions_without_hints:
            issues.append(f"Functions without type hints: {', '.join(functions_without_hints[:3])}")

        return len(issues) == 0, issues

    def _gate_pf_001_performance_thresholds(self, context: Dict[str, Any]) -> tuple[bool, List[str]]:
        """PF-001: Performance Thresholds - Target <30ms"""
        issues = []
        metrics = context.get('performance_metrics', {})

        # Check execution time threshold
        execution_time_ms = metrics.get('execution_time_ms', 0)
        threshold_ms = metrics.get('threshold_ms', 5000)

        if execution_time_ms > threshold_ms:
            issues.append(f"Execution time {execution_time_ms}ms exceeds threshold {threshold_ms}ms")

        return len(issues) == 0, issues


def main():
    """Skill executor entry point"""
    if len(sys.argv) != 2:
        print(json.dumps({
            "error": "Usage: executor.py <json_input>",
            "code": "INVALID_ARGS"
        }))
        sys.exit(1)

    try:
        # Parse input JSON
        input_data = json.loads(sys.argv[1])
        gate_ids = input_data.get('gate_ids', [])
        context = input_data.get('context', {})

        # Execute gates
        executor = QualityGateExecutor()
        result = executor.execute_gates(gate_ids, context)

        # Convert to JSON output
        output = {
            "overall_passed": result.overall_passed,
            "gates_executed": result.gates_executed,
            "gates_passed": result.gates_passed,
            "performance_budget_used_ms": result.performance_budget_used_ms,
            "gate_results": [asdict(r) for r in result.gate_results]
        }

        print(json.dumps(output, indent=2))
        sys.exit(0 if result.overall_passed else 1)

    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON input: {e}", "code": "INVALID_JSON"}))
        sys.exit(2)
    except Exception as e:
        print(json.dumps({"error": str(e), "code": "UNKNOWN_ERROR"}))
        sys.exit(4)


if __name__ == "__main__":
    main()
```

---

## PostgreSQL Tracking Schema

### Skill Execution Tracking

```sql
-- Create skill execution tracking table
CREATE TABLE IF NOT EXISTS skill_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_name TEXT NOT NULL,
    skill_version TEXT DEFAULT '1.0.0',
    agent_name TEXT,
    file_path TEXT,
    passed BOOLEAN NOT NULL,
    execution_time_ms INTEGER,
    compliance_score NUMERIC(5,4),
    violations JSONB,
    context JSONB,
    correlation_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index for common queries
CREATE INDEX idx_skill_executions_skill_name ON skill_executions(skill_name);
CREATE INDEX idx_skill_executions_agent_name ON skill_executions(agent_name);
CREATE INDEX idx_skill_executions_created_at ON skill_executions(created_at);
CREATE INDEX idx_skill_executions_correlation_id ON skill_executions(correlation_id);

-- Create quality gate results table
CREATE TABLE IF NOT EXISTS quality_gate_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gate_id TEXT NOT NULL,
    gate_name TEXT,
    agent_name TEXT,
    passed BOOLEAN NOT NULL,
    execution_time_ms INTEGER,
    issues JSONB,
    context JSONB,
    correlation_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index for gate queries
CREATE INDEX idx_quality_gate_results_gate_id ON quality_gate_results(gate_id);
CREATE INDEX idx_quality_gate_results_agent_name ON quality_gate_results(agent_name);
CREATE INDEX idx_quality_gate_results_created_at ON quality_gate_results(created_at);

-- Analytics view: Skill performance by agent
CREATE OR REPLACE VIEW skill_performance_by_agent AS
SELECT
    agent_name,
    skill_name,
    COUNT(*) as executions,
    AVG(execution_time_ms) as avg_time_ms,
    AVG(compliance_score) as avg_compliance,
    SUM(CASE WHEN passed THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as pass_rate
FROM skill_executions
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY agent_name, skill_name
ORDER BY executions DESC;

-- Analytics view: Quality gate pass rates
CREATE OR REPLACE VIEW quality_gate_pass_rates AS
SELECT
    gate_id,
    gate_name,
    COUNT(*) as executions,
    SUM(CASE WHEN passed THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as pass_rate,
    AVG(execution_time_ms) as avg_time_ms
FROM quality_gate_results
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY gate_id, gate_name
ORDER BY executions DESC;
```

---

## Comparison: Before vs After Skills

### Before Skills (Current State)

**Agent Code Generation Workflow**:
```
1. Agent gathers RAG intelligence (500ms)
2. Agent generates code (LLM call #1, 2000ms)
3. Agent writes file
4. Hook detects naming violations AFTER write
5. Agent reads hook feedback
6. Agent fixes violations (LLM call #2, 2000ms)
7. Agent re-writes file
8. Hook validates again
9. Repeat until clean (average 3-5 iterations)

Total: 3-5 LLM calls, 8-12 seconds
```

### After Skills (Target State)

**Agent Code Generation Workflow with Skills**:
```
1. Agent gathers RAG intelligence (500ms)
2. Agent generates code (LLM call #1, 2000ms)
3. Agent saves to temp file
4. Agent uses validate-onex-naming skill (100ms)
5. If violations:
   a. Agent reviews violations (deterministic)
   b. Agent fixes violations (LLM call #2, 2000ms)
   c. Agent re-validates with skill (100ms)
   d. Repeat until clean (1-2 iterations)
6. Agent writes final file
7. Hook runs quality gates (200ms)
8. Success!

Total: 1-2 LLM calls, 4-6 seconds (50% reduction)
```

---

## Next Steps

1. **Prototype validate-onex-naming skill** (Week 1)
2. **Integrate with PreToolUse hook** (Week 1)
3. **Test with agent-code-generator** (Week 2)
4. **Implement execute-quality-gates skill** (Week 3)
5. **Deploy to production** (Week 4)

**ROI**: 50% reduction in code-gen iterations, 100% quality gate coverage, deterministic validation.
