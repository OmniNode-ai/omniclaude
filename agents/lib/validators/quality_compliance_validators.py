#!/usr/bin/env python3
"""
Quality Compliance Validators - ONEX Agent Framework.

Implements 4 quality compliance gates:
- QC-001: ONEX Standards - Verify ONEX architectural compliance
- QC-002: Anti-YOLO Compliance - Ensure systematic approach methodology
- QC-003: Type Safety - Validate strong typing and type compliance
- QC-004: Error Handling - Verify proper error usage and exception chaining

ONEX v2.0 Compliance:
- BaseQualityGate subclass pattern
- Pydantic result models
- AST parsing for code analysis
- Performance targets: QC <100ms per gate
"""

import ast
import re
from pathlib import Path
from typing import Any, Literal, cast

from ..models.model_quality_gate import EnumQualityGate, ModelQualityGateResult
from .base_quality_gate import BaseQualityGate


# Type alias for status literal
StatusLiteral = Literal["passed", "failed", "skipped"]


class ONEXStandardsValidator(BaseQualityGate):
    """
    QC-001: ONEX Standards Validator.

    Verifies ONEX architectural compliance including:
    - Naming conventions (NodeXxxEffect, ModelXxx, EnumXxx)
    - Node type patterns (Effect/Compute/Reducer/Orchestrator)
    - File structure and organization
    - ONEX v2.0 architectural patterns

    Performance Target: 80ms
    """

    def __init__(self) -> None:
        """Initialize ONEX standards validator."""
        super().__init__(EnumQualityGate.ONEX_STANDARDS)

        # ONEX naming patterns
        self.node_pattern = re.compile(
            r"^Node[A-Z][a-zA-Z]+(Effect|Compute|Reducer|Orchestrator)$"
        )
        self.model_pattern = re.compile(r"^Model[A-Z][a-zA-Z]+$")
        self.enum_pattern = re.compile(r"^Enum[A-Z][a-zA-Z]+$")
        self.file_node_pattern = re.compile(
            r"^node_[a-z_]+_(effect|compute|reducer|orchestrator)\.py$"
        )
        self.file_model_pattern = re.compile(r"^model_[a-z_]+\.py$")
        self.file_enum_pattern = re.compile(r"^enum_[a-z_]+\.py$")

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Validate ONEX standards compliance.

        Expected context keys:
        - code: str | Path - Code to validate (string or file path)
        - file_path: Optional[str] - File path for file structure validation
        - strict: bool - Strict mode (default: True)

        Returns:
            ModelQualityGateResult with validation outcome
        """
        issues: list[str] = []
        warnings: list[str] = []

        # Extract code from context
        code = context.get("code", "")
        file_path = context.get("file_path")
        strict = context.get("strict", True)

        # Load code from file if path provided
        if isinstance(code, Path):
            # Explicit Path object
            file_path = str(code)
            code = code.read_text(encoding="utf-8")
        elif isinstance(code, str) and not (
            "\n" in code or "class " in code or "def " in code
        ):
            # Might be a file path (doesn't have code markers)
            path = Path(code)
            if path.exists() and path.is_file():
                file_path = str(path)
                code = path.read_text(encoding="utf-8")

        if not code or len(code) < 5:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="Code file not found or code is empty",
                metadata={"issues": ["No code provided for validation"]},
            )

        # Parse code with AST
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Syntax error in code: {e}",
                metadata={"issues": [f"Syntax error: {e}"]},
            )

        # Check file naming conventions
        if file_path:
            self._check_file_naming(Path(file_path), issues, warnings)

        # Check class naming conventions
        self._check_class_naming(tree, issues, warnings, strict)

        # Check node type compliance
        self._check_node_types(tree, issues, warnings)

        # Determine status
        status: StatusLiteral
        if issues:
            status = "failed"
            message = f"ONEX standards violations: {len(issues)} issues found"
        elif warnings:
            status = "passed"
            message = f"ONEX standards passed with {len(warnings)} warnings"
        else:
            status = "passed"
            message = "ONEX standards validation passed"

        return ModelQualityGateResult(
            gate=self.gate,
            status=status,
            execution_time_ms=0,  # Will be updated by execute_with_timing
            message=message,
            metadata={
                "issues": issues,
                "warnings": warnings,
                "file_path": file_path,
                "total_classes": len(
                    [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
                ),
            },
        )

    def _check_file_naming(
        self, file_path: Path, issues: list[str], warnings: list[str]
    ) -> None:
        """Check file naming conventions."""
        filename = file_path.name

        # Check node files
        if filename.startswith("node_"):
            if not self.file_node_pattern.match(filename):
                issues.append(
                    f"Node file '{filename}' doesn't match pattern 'node_*_(effect|compute|reducer|orchestrator).py'"
                )

        # Check model files
        elif filename.startswith("model_"):
            if not self.file_model_pattern.match(filename):
                warnings.append(
                    f"Model file '{filename}' doesn't match pattern 'model_*.py'"
                )

        # Check enum files
        elif filename.startswith("enum_"):
            if not self.file_enum_pattern.match(filename):
                warnings.append(
                    f"Enum file '{filename}' doesn't match pattern 'enum_*.py'"
                )

    def _check_class_naming(
        self, tree: ast.AST, issues: list[str], warnings: list[str], strict: bool
    ) -> None:
        """Check class naming conventions."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name

                # Check node classes
                if class_name.startswith("Node"):
                    if not self.node_pattern.match(class_name):
                        issues.append(
                            f"Node class '{class_name}' doesn't match pattern 'Node<Name><Type>'"
                        )

                # Check model classes
                elif class_name.startswith("Model"):
                    if not self.model_pattern.match(class_name):
                        warnings.append(
                            f"Model class '{class_name}' should match pattern 'Model<Name>'"
                        )

                # Check enum classes
                elif class_name.startswith("Enum"):
                    if not self.enum_pattern.match(class_name):
                        warnings.append(
                            f"Enum class '{class_name}' should match pattern 'Enum<Name>'"
                        )

    def _check_node_types(
        self, tree: ast.AST, issues: list[str], warnings: list[str]
    ) -> None:
        """Check node type compliance (Effect/Compute/Reducer/Orchestrator)."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name

                if class_name.startswith("Node"):
                    # Check if node has proper type suffix
                    if not any(
                        class_name.endswith(suffix)
                        for suffix in ["Effect", "Compute", "Reducer", "Orchestrator"]
                    ):
                        issues.append(
                            f"Node class '{class_name}' must end with Effect/Compute/Reducer/Orchestrator"
                        )

                    # Check for corresponding execute method
                    methods = [
                        m.name for m in node.body if isinstance(m, ast.FunctionDef)
                    ]

                    if (
                        class_name.endswith("Effect")
                        and "execute_effect" not in methods
                    ):
                        warnings.append(
                            f"Node '{class_name}' should implement execute_effect method"
                        )
                    elif (
                        class_name.endswith("Compute")
                        and "execute_compute" not in methods
                    ):
                        warnings.append(
                            f"Node '{class_name}' should implement execute_compute method"
                        )
                    elif (
                        class_name.endswith("Reducer")
                        and "execute_reduction" not in methods
                    ):
                        warnings.append(
                            f"Node '{class_name}' should implement execute_reduction method"
                        )
                    elif (
                        class_name.endswith("Orchestrator")
                        and "execute_orchestration" not in methods
                    ):
                        warnings.append(
                            f"Node '{class_name}' should implement execute_orchestration method"
                        )


class AntiYOLOComplianceValidator(BaseQualityGate):
    """
    QC-002: Anti-YOLO Compliance Validator.

    Ensures systematic approach methodology:
    - All workflow stages executed (no skipping)
    - Planning stage completed before execution
    - Proper error handling (no silent failures)
    - Quality gates not bypassed
    - Systematic approach evidence

    Performance Target: 30ms
    """

    def __init__(self) -> None:
        """Initialize anti-YOLO compliance validator."""
        super().__init__(EnumQualityGate.ANTI_YOLO_COMPLIANCE)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Validate anti-YOLO compliance.

        Expected context keys:
        - workflow_stages: list[str] - Completed workflow stages
        - required_stages: list[str] - Required stages for this workflow
        - planning_completed: bool - Whether planning stage was completed
        - quality_gates_executed: list[str] - Quality gates that were executed
        - skipped_stages: list[str] - Stages that were explicitly skipped

        Returns:
            ModelQualityGateResult with validation outcome
        """
        issues: list[str] = []
        warnings: list[str] = []

        workflow_stages = context.get("workflow_stages", [])
        required_stages = context.get("required_stages", [])
        planning_completed = context.get("planning_completed", False)
        quality_gates_executed = context.get("quality_gates_executed", [])
        skipped_stages = context.get("skipped_stages", [])

        # Check if planning was completed
        if not planning_completed and "planning" in required_stages:
            issues.append("Planning stage not completed before execution")

        # Check for skipped stages
        if skipped_stages:
            for stage in skipped_stages:
                if stage in required_stages:
                    issues.append(f"Required stage '{stage}' was skipped")
                else:
                    warnings.append(f"Optional stage '{stage}' was skipped")

        # Check if all required stages were executed
        missing_stages = [s for s in required_stages if s not in workflow_stages]
        if missing_stages:
            issues.append(f"Missing required stages: {', '.join(missing_stages)}")

        # Check quality gates execution
        if not quality_gates_executed:
            warnings.append("No quality gates executed - systematic validation missing")

        # Check workflow stage ordering
        expected_order = ["planning", "execution", "validation", "completion"]
        actual_order = [s for s in expected_order if s in workflow_stages]

        if len(actual_order) >= 2:
            for i in range(len(actual_order) - 1):
                current_stage = actual_order[i]
                next_stage = actual_order[i + 1]
                current_idx = expected_order.index(current_stage)
                next_idx = expected_order.index(next_stage)

                if next_idx < current_idx:
                    warnings.append(
                        f"Stage ordering issue: '{next_stage}' executed before '{current_stage}'"
                    )

        # Determine status
        status: StatusLiteral
        if issues:
            status = "failed"
            message = f"Anti-YOLO violations: {len(issues)} issues found"
        elif warnings:
            status = "passed"
            message = f"Anti-YOLO compliance passed with {len(warnings)} warnings"
        else:
            status = "passed"
            message = "Anti-YOLO compliance validation passed"

        return ModelQualityGateResult(
            gate=self.gate,
            status=status,
            execution_time_ms=0,
            message=message,
            metadata={
                "issues": issues,
                "warnings": warnings,
                "workflow_stages": workflow_stages,
                "required_stages": required_stages,
                "quality_gates_executed": quality_gates_executed,
            },
        )


class TypeSafetyValidator(BaseQualityGate):
    """
    QC-003: Type Safety Validator.

    Validates strong typing and type compliance:
    - Type hints on all functions/methods
    - Pydantic models for data validation
    - No `type: ignore` without justification
    - Type correctness (no Any overuse)
    - Generic types used appropriately

    Performance Target: 60ms
    """

    def __init__(self) -> None:
        """Initialize type safety validator."""
        super().__init__(EnumQualityGate.TYPE_SAFETY)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Validate type safety compliance.

        Expected context keys:
        - code: str | Path - Code to validate
        - allow_any: bool - Allow Any type usage (default: False)
        - min_type_coverage: float - Minimum type coverage ratio (default: 0.9)

        Returns:
            ModelQualityGateResult with validation outcome
        """
        issues: list[str] = []
        warnings: list[str] = []

        # Extract code from context
        code = context.get("code", "")
        allow_any = context.get("allow_any", False)
        min_type_coverage = context.get("min_type_coverage", 0.9)

        # Load code from file if path provided
        if isinstance(code, Path):
            code = code.read_text(encoding="utf-8")
        elif isinstance(code, str) and not (
            "\n" in code or "class " in code or "def " in code
        ):
            path = Path(code)
            if path.exists() and path.is_file():
                code = path.read_text(encoding="utf-8")

        if not code:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="No code provided for validation",
                metadata={"issues": ["No code provided"]},
            )

        # Parse code with AST
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Syntax error in code: {e}",
                metadata={"issues": [f"Syntax error: {e}"]},
            )

        # Check type hints on functions/methods
        type_stats = self._check_type_hints(tree, issues, warnings)

        # Check for type: ignore comments
        self._check_type_ignore(code, issues, warnings)

        # Check for Any overuse
        if not allow_any:
            self._check_any_usage(tree, warnings)

        # Calculate type coverage
        total_functions = type_stats["total_functions"]
        typed_functions = type_stats["typed_functions"]
        type_coverage = (
            typed_functions / total_functions if total_functions > 0 else 1.0
        )

        if type_coverage < min_type_coverage:
            issues.append(
                f"Type coverage {type_coverage:.1%} below minimum {min_type_coverage:.1%}"
            )

        # Determine status
        status: StatusLiteral
        if issues:
            status = "failed"
            message = f"Type safety violations: {len(issues)} issues found"
        elif warnings:
            status = "passed"
            message = f"Type safety passed with {len(warnings)} warnings"
        else:
            status = "passed"
            message = "Type safety validation passed"

        return ModelQualityGateResult(
            gate=self.gate,
            status=status,
            execution_time_ms=0,
            message=message,
            metadata={
                "issues": issues,
                "warnings": warnings,
                "type_coverage": type_coverage,
                "total_functions": total_functions,
                "typed_functions": typed_functions,
            },
        )

    def _check_type_hints(
        self, tree: ast.AST, issues: list[str], warnings: list[str]
    ) -> dict[str, int]:
        """Check type hints on functions and methods."""
        total_functions = 0
        typed_functions = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Skip magic methods and private methods in coverage calculation
                if node.name.startswith("__") and node.name.endswith("__"):
                    continue

                total_functions += 1

                # Check return type annotation
                has_return_type = node.returns is not None

                # Check argument type annotations
                args_with_types = 0
                _total_args = len(node.args.args)

                # Skip 'self' and 'cls' arguments
                args_to_check = [
                    arg for arg in node.args.args if arg.arg not in ("self", "cls")
                ]

                for arg in args_to_check:
                    if arg.annotation is not None:
                        args_with_types += 1

                # Function is typed if it has return type and all args are typed
                if has_return_type and (
                    len(args_to_check) == 0 or args_with_types == len(args_to_check)
                ):
                    typed_functions += 1
                else:
                    if not has_return_type:
                        warnings.append(
                            f"Function '{node.name}' missing return type annotation"
                        )
                    if args_with_types < len(args_to_check):
                        warnings.append(
                            f"Function '{node.name}' has {len(args_to_check) - args_with_types} untyped arguments"
                        )

        return {
            "total_functions": total_functions,
            "typed_functions": typed_functions,
        }

    def _check_type_ignore(
        self, code: str, issues: list[str], warnings: list[str]
    ) -> None:
        """Check for type: ignore comments."""
        type_ignore_pattern = re.compile(r"#\s*type:\s*ignore(?:\[([^\]]+)\])?")

        for i, line in enumerate(code.splitlines(), start=1):
            match = type_ignore_pattern.search(line)
            if match:
                error_codes = match.group(1)
                if not error_codes:
                    warnings.append(
                        f"Line {i}: type: ignore without specific error code - consider adding error code"
                    )
                else:
                    # Check if there's a justification comment
                    if "  #" not in line.split("type: ignore")[1]:
                        warnings.append(
                            f"Line {i}: type: ignore without justification comment"
                        )

    def _check_any_usage(self, tree: ast.AST, warnings: list[str]) -> None:
        """Check for Any type overuse."""
        any_usage_count = 0

        for node in ast.walk(tree):
            # Check for Any in annotations
            if isinstance(node, (ast.FunctionDef, ast.arg)):
                annotation = getattr(node, "annotation", None) or getattr(
                    node, "returns", None
                )
                if annotation and self._contains_any(annotation):
                    any_usage_count += 1

        if any_usage_count > 0:
            warnings.append(
                f"Found {any_usage_count} uses of Any type - consider using more specific types"
            )

    def _contains_any(self, node: ast.AST) -> bool:
        """Check if an annotation contains 'Any'."""
        if isinstance(node, ast.Name) and node.id == "Any":
            return True

        # Check subscript like Dict[str, Any]
        if isinstance(node, ast.Subscript):
            return (
                self._contains_any(node.value)
                or (
                    isinstance(node.slice, ast.Tuple)
                    and any(self._contains_any(elt) for elt in node.slice.elts)
                )
                or (
                    not isinstance(node.slice, ast.Tuple)
                    and self._contains_any(node.slice)
                )
            )

        return False


class ErrorHandlingValidator(BaseQualityGate):
    """
    QC-004: Error Handling Validator.

    Verifies proper error usage and exception chaining:
    - Custom exceptions used appropriately
    - Exception chaining (raise ... from e)
    - Descriptive error messages
    - Finally blocks for cleanup
    - No bare except: clauses

    Performance Target: 40ms
    """

    def __init__(self) -> None:
        """Initialize error handling validator."""
        super().__init__(EnumQualityGate.ERROR_HANDLING)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Validate error handling compliance.

        Expected context keys:
        - code: str | Path - Code to validate
        - require_exception_chaining: bool - Require 'from' in exceptions (default: True)
        - allow_bare_except: bool - Allow bare except clauses (default: False)

        Returns:
            ModelQualityGateResult with validation outcome
        """
        issues: list[str] = []
        warnings: list[str] = []

        # Extract code from context
        code = context.get("code", "")
        require_exception_chaining = context.get("require_exception_chaining", True)
        allow_bare_except = context.get("allow_bare_except", False)

        # Load code from file if path provided
        if isinstance(code, Path):
            code = code.read_text(encoding="utf-8")
        elif isinstance(code, str) and not (
            "\n" in code or "class " in code or "def " in code
        ):
            path = Path(code)
            if path.exists() and path.is_file():
                code = path.read_text(encoding="utf-8")

        if not code:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="No code provided for validation",
                metadata={"issues": ["No code provided"]},
            )

        # Parse code with AST
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Syntax error in code: {e}",
                metadata={"issues": [f"Syntax error: {e}"]},
            )

        # Check exception handling patterns
        self._check_bare_except(tree, issues, allow_bare_except)
        self._check_exception_chaining(tree, warnings, require_exception_chaining)
        self._check_finally_blocks(tree, warnings)

        # Determine status
        status: StatusLiteral
        if issues:
            status = "failed"
            message = f"Error handling violations: {len(issues)} issues found"
        elif warnings:
            status = "passed"
            message = f"Error handling passed with {len(warnings)} warnings"
        else:
            status = "passed"
            message = "Error handling validation passed"

        return ModelQualityGateResult(
            gate=self.gate,
            status=status,
            execution_time_ms=0,
            message=message,
            metadata={
                "issues": issues,
                "warnings": warnings,
            },
        )

    def _check_bare_except(
        self, tree: ast.AST, issues: list[str], allow_bare_except: bool
    ) -> None:
        """Check for bare except clauses."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None and not allow_bare_except:
                    issues.append(
                        f"Bare except clause found at line {node.lineno} - specify exception type"
                    )

    def _check_exception_chaining(
        self, tree: ast.AST, warnings: list[str], require_chaining: bool
    ) -> None:
        """Check for exception chaining with 'from'."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise):
                # Check if raising inside an except block
                if self._is_in_except_handler(node, tree) and node.cause is None:
                    if require_chaining and node.exc is not None:
                        warnings.append(
                            f"Exception raised at line {node.lineno} without chaining (consider 'from')"
                        )

    def _check_finally_blocks(self, tree: ast.AST, warnings: list[str]) -> None:
        """Check for proper cleanup in finally blocks."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                has_finally = len(node.finalbody) > 0

                # Check if try block has resource allocation
                has_resource_allocation = self._has_resource_allocation(node.body)

                if has_resource_allocation and not has_finally:
                    warnings.append(
                        f"Try block at line {node.lineno} allocates resources but has no finally block for cleanup"
                    )

    def _is_in_except_handler(self, raise_node: ast.Raise, tree: ast.AST) -> bool:
        """Check if a raise statement is inside an except handler."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if raise_node in ast.walk(node):
                    return True
        return False

    def _has_resource_allocation(self, body: list[ast.stmt]) -> bool:
        """Check if code block allocates resources (files, connections, etc)."""
        resource_keywords = ["open", "connect", "acquire", "allocate", "session"]

        for node in ast.walk(ast.Module(body=body, type_ignores=[])):
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id in resource_keywords
                ):
                    return True
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in resource_keywords
                ):
                    return True

        return False
