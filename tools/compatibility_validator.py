#!/usr/bin/env python3
"""
OmniBase Core Compatibility Validator

Validates that generated code templates and files are compatible with omnibase_core:
- Import paths exist and are importable
- ONEX naming conventions are followed
- Pydantic v2 patterns are used
- Base classes are properly inherited
- Container-based DI is used
- No forbidden patterns

Usage:
    poetry run python tools/compatibility_validator.py --file <file_path> [--json]
    poetry run python tools/compatibility_validator.py --template <template_path> --check-all
    poetry run python tools/compatibility_validator.py --directory <dir_path> --recursive
"""

import argparse
import ast
import importlib
import json
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class CheckStatus(Enum):
    """Status of a validation check"""

    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIP = "skip"


class CheckType(Enum):
    """Type of validation check"""

    IMPORT = "import"
    PATTERN = "pattern"
    PYDANTIC = "pydantic"
    BASE_CLASS = "base_class"
    DI_CONTAINER = "di_container"
    TYPE_HINT = "type_hint"
    NAMING = "naming"
    FORBIDDEN = "forbidden"


@dataclass
class ValidationCheck:
    """Result of a single validation check"""

    check_type: CheckType
    status: CheckStatus
    rule: str
    message: str
    line_number: Optional[int] = None
    details: Optional[str] = None
    suggestion: Optional[str] = None


@dataclass
class ValidationResult:
    """Complete validation result for a file"""

    file_path: str
    overall_status: CheckStatus
    checks: List[ValidationCheck] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def summary(self) -> Dict[str, int]:
        """Get summary statistics"""
        return {
            "total": len(self.checks),
            "passed": sum(1 for c in self.checks if c.status == CheckStatus.PASS),
            "failed": sum(1 for c in self.checks if c.status == CheckStatus.FAIL),
            "warnings": sum(1 for c in self.checks if c.status == CheckStatus.WARNING),
            "skipped": sum(1 for c in self.checks if c.status == CheckStatus.SKIP),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "file_path": self.file_path,
            "status": self.overall_status.value,
            "checks": [
                {
                    "type": c.check_type.value,
                    "status": c.status.value,
                    "rule": c.rule,
                    "message": c.message,
                    "line": c.line_number,
                    "details": c.details,
                    "suggestion": c.suggestion,
                }
                for c in self.checks
            ],
            "summary": self.summary,
            "errors": self.errors,
        }


class OmniBaseCompatibilityValidator:
    """Validator for omnibase_core compatibility"""

    # Known valid import paths from omnibase_core
    VALID_IMPORTS = {
        "omnibase_core.nodes.node_effect": ["NodeEffect"],
        "omnibase_core.nodes.node_compute": ["NodeCompute"],
        "omnibase_core.nodes.node_reducer": ["NodeReducer"],
        "omnibase_core.nodes.node_orchestrator": ["NodeOrchestrator"],
        "omnibase_core.nodes.model_effect_input": ["ModelEffectInput"],
        "omnibase_core.nodes.model_effect_output": ["ModelEffectOutput"],
        "omnibase_core.nodes.model_compute_input": ["ModelComputeInput"],
        "omnibase_core.nodes.model_compute_output": ["ModelComputeOutput"],
        "omnibase_core.nodes.model_reducer_input": ["ModelReducerInput"],
        "omnibase_core.nodes.model_reducer_output": ["ModelReducerOutput"],
        "omnibase_core.nodes.model_orchestrator_input": ["ModelOrchestratorInput"],
        "omnibase_core.nodes.model_orchestrator_output": ["ModelOrchestratorOutput"],
        "omnibase_core.errors.model_onex_error": ["ModelOnexError", "OnexError"],
        "omnibase_core.errors.error_codes": ["EnumCoreErrorCode"],
        "omnibase_core.models.container.model_onex_container": ["ModelONEXContainer"],
        "omnibase_core.primitives.model_semver": ["ModelSemVer"],
        "omnibase_core.errors": ["OnexError", "ModelOnexError", "EnumCoreErrorCode"],
    }

    # Incorrect import paths to detect (common mistakes)
    INCORRECT_IMPORTS = {
        "omnibase_core.core.node_effect": "Use omnibase_core.nodes.model_effect_input/model_effect_output instead",
        "omnibase_core.core.node_compute": "Use omnibase_core.nodes.model_compute_input/model_compute_output instead",
        "omnibase_core.core.model_onex_error": "Use omnibase_core.errors.model_onex_error instead",
    }

    # ONEX naming patterns
    NODE_CLASS_PATTERN = re.compile(
        r"^Node[A-Z][a-zA-Z]+(Effect|Compute|Reducer|Orchestrator)$"
    )
    MODEL_CLASS_PATTERN = re.compile(r"^Model[A-Z][a-zA-Z]+$")
    ENUM_CLASS_PATTERN = re.compile(r"^Enum[A-Z][a-zA-Z]+$")

    # Pydantic v1 patterns to detect (should be v2)
    PYDANTIC_V1_PATTERNS = {
        ".dict(": ".model_dump(",
        ".json(": ".model_dump_json(",
        ".parse_obj(": ".model_validate(",
        ".parse_raw(": ".model_validate_json(",
        ".schema(": ".model_json_schema(",
        "Config:": "model_config =",
    }

    # Forbidden patterns
    FORBIDDEN_PATTERNS = {
        "from typing import Any": "Avoid using Any types - use specific types instead",
        "import *": "Avoid wildcard imports - import specific items",
    }

    # Template placeholder patterns to substitute
    TEMPLATE_PLACEHOLDERS = {
        "{MICROSERVICE_NAME}": "example_service",
        "{MICROSERVICE_NAME_PASCAL}": "ExampleService",
        "{DOMAIN}": "example_domain",
        "{DOMAIN_PASCAL}": "ExampleDomain",
        "{NODE_TYPE}": "EFFECT",
        "{BUSINESS_DESCRIPTION}": "Example business description",
        "{MIXIN_IMPORTS}": "",
        "{MIXIN_INHERITANCE}": "",
        "{MIXIN_INITIALIZATION}": "",
        "{BUSINESS_LOGIC_STUB}": "# Business logic",
        "{OPERATIONS}": "[]",
        "{FEATURES}": "# Features",
    }

    def __init__(
        self,
        strict: bool = False,
        omnibase_path: Optional[Path] = None,
        template_mode: bool = False,
    ):
        """
        Initialize validator

        Args:
            strict: Enable strict validation (warnings become errors)
            omnibase_path: Path to omnibase_core for import validation
            template_mode: Enable template mode (substitute placeholders)
        """
        self.strict = strict
        self.template_mode = template_mode
        self.omnibase_path = omnibase_path or Path(
            "/Volumes/PRO-G40/Code/omnibase_core"
        )

    def validate_file(self, file_path: Path) -> ValidationResult:
        """
        Validate a Python file for omnibase_core compatibility

        Args:
            file_path: Path to file to validate

        Returns:
            ValidationResult with all checks
        """
        result = ValidationResult(
            file_path=str(file_path), overall_status=CheckStatus.PASS
        )

        try:
            # Read file content
            content = file_path.read_text()

            # Auto-detect template mode if not explicitly set
            is_template = self.template_mode or self._is_template_file(content)

            # Substitute template placeholders if needed
            if is_template:
                result.checks.append(
                    ValidationCheck(
                        check_type=CheckType.PATTERN,
                        status=CheckStatus.PASS,
                        rule="template_mode",
                        message="Template mode enabled - substituting placeholders",
                    )
                )
                content = self._substitute_placeholders(content)

            # Parse AST
            try:
                tree = ast.parse(content, filename=str(file_path))
            except SyntaxError as e:
                if is_template:
                    result.errors.append(
                        f"Syntax error even after placeholder substitution: {e}. "
                        "Template may have additional unrecognized placeholders."
                    )
                else:
                    result.errors.append(f"Syntax error: {e}")
                result.overall_status = CheckStatus.FAIL
                return result

            # Run validation checks
            self._check_imports(tree, content, result)
            self._check_class_naming(tree, result)
            self._check_base_classes(tree, result)
            self._check_container_di(tree, result)
            self._check_pydantic_v2(content, result)
            self._check_type_hints(tree, result)
            self._check_forbidden_patterns(content, result)

            # Determine overall status
            if any(c.status == CheckStatus.FAIL for c in result.checks):
                result.overall_status = CheckStatus.FAIL
            elif any(c.status == CheckStatus.WARNING for c in result.checks):
                result.overall_status = (
                    CheckStatus.FAIL if self.strict else CheckStatus.WARNING
                )

        except Exception as e:
            result.errors.append(f"Validation error: {e}")
            result.overall_status = CheckStatus.FAIL

        return result

    def _is_template_file(self, content: str) -> bool:
        """Check if file appears to be a template with placeholders"""
        # Look for common placeholder patterns
        template_patterns = [
            r"\{[A-Z_]+\}",  # {PLACEHOLDER}
            r"\{MICROSERVICE_NAME",
            r"\{DOMAIN",
            r"\{NODE_TYPE",
        ]
        for pattern in template_patterns:
            if re.search(pattern, content):
                return True
        return False

    def _substitute_placeholders(self, content: str) -> str:
        """Substitute template placeholders with dummy values"""
        for placeholder, value in self.TEMPLATE_PLACEHOLDERS.items():
            content = content.replace(placeholder, value)
        return content

    def _check_imports(
        self, tree: ast.AST, content: str, result: ValidationResult
    ) -> None:
        """Check import statements for validity"""
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if not module.startswith("omnibase_core"):
                    continue

                line_no = node.lineno

                # Check for incorrect import paths
                if module in self.INCORRECT_IMPORTS:
                    result.checks.append(
                        ValidationCheck(
                            check_type=CheckType.IMPORT,
                            status=CheckStatus.FAIL,
                            rule="incorrect_import_path",
                            message=f"Incorrect import path: {module}",
                            line_number=line_no,
                            details=self.INCORRECT_IMPORTS[module],
                            suggestion=self.INCORRECT_IMPORTS[module],
                        )
                    )
                    continue

                # Check if module exists
                if module in self.VALID_IMPORTS:
                    # Check imported names
                    for alias in node.names:
                        name = alias.name
                        if name != "*" and name not in self.VALID_IMPORTS[module]:
                            result.checks.append(
                                ValidationCheck(
                                    check_type=CheckType.IMPORT,
                                    status=CheckStatus.WARNING,
                                    rule="unknown_import_name",
                                    message=f"Unknown import: {name} from {module}",
                                    line_number=line_no,
                                    details=f"Valid imports from {module}: {', '.join(self.VALID_IMPORTS[module])}",
                                )
                            )
                        else:
                            result.checks.append(
                                ValidationCheck(
                                    check_type=CheckType.IMPORT,
                                    status=CheckStatus.PASS,
                                    rule="valid_import",
                                    message=f"Valid import: {name} from {module}",
                                    line_number=line_no,
                                )
                            )
                else:
                    # Try to actually import it
                    try:
                        # Add omnibase_core to path if provided
                        if self.omnibase_path.exists():
                            sys.path.insert(0, str(self.omnibase_path / "src"))

                        importlib.import_module(module)
                        result.checks.append(
                            ValidationCheck(
                                check_type=CheckType.IMPORT,
                                status=CheckStatus.PASS,
                                rule="importable_module",
                                message=f"Module is importable: {module}",
                                line_number=line_no,
                            )
                        )
                    except ImportError:
                        result.checks.append(
                            ValidationCheck(
                                check_type=CheckType.IMPORT,
                                status=CheckStatus.FAIL,
                                rule="import_not_found",
                                message=f"Import not found: {module}",
                                line_number=line_no,
                                details=f"Module {module} cannot be imported",
                                suggestion="Check omnibase_core documentation for correct import paths",
                            )
                        )

    def _check_class_naming(self, tree: ast.AST, result: ValidationResult) -> None:
        """Check ONEX naming conventions"""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                line_no = node.lineno

                # Check Node classes
                if class_name.startswith("Node") and not class_name.startswith(
                    "NodeTest"
                ):
                    if self.NODE_CLASS_PATTERN.match(class_name):
                        # Extract node type
                        if class_name.endswith("Effect"):
                            node_type = "Effect"
                        elif class_name.endswith("Compute"):
                            node_type = "Compute"
                        elif class_name.endswith("Reducer"):
                            node_type = "Reducer"
                        elif class_name.endswith("Orchestrator"):
                            node_type = "Orchestrator"
                        else:
                            node_type = None

                        if node_type:
                            result.checks.append(
                                ValidationCheck(
                                    check_type=CheckType.NAMING,
                                    status=CheckStatus.PASS,
                                    rule="onex_node_naming",
                                    message=f"Valid ONEX node naming: {class_name}",
                                    line_number=line_no,
                                    details=f"Node type: {node_type}",
                                )
                            )
                    else:
                        result.checks.append(
                            ValidationCheck(
                                check_type=CheckType.NAMING,
                                status=CheckStatus.FAIL,
                                rule="invalid_node_naming",
                                message=f"Invalid ONEX node naming: {class_name}",
                                line_number=line_no,
                                details="Node classes must follow pattern: Node<Name><Type> where Type is Effect, Compute, Reducer, or Orchestrator",
                                suggestion="Example: NodeUserServiceEffect, NodeDataProcessorCompute",
                            )
                        )

                # Check Model classes
                elif class_name.startswith("Model"):
                    if self.MODEL_CLASS_PATTERN.match(class_name):
                        result.checks.append(
                            ValidationCheck(
                                check_type=CheckType.NAMING,
                                status=CheckStatus.PASS,
                                rule="onex_model_naming",
                                message=f"Valid ONEX model naming: {class_name}",
                                line_number=line_no,
                            )
                        )

                # Check Enum classes
                elif class_name.startswith("Enum"):
                    if self.ENUM_CLASS_PATTERN.match(class_name):
                        result.checks.append(
                            ValidationCheck(
                                check_type=CheckType.NAMING,
                                status=CheckStatus.PASS,
                                rule="onex_enum_naming",
                                message=f"Valid ONEX enum naming: {class_name}",
                                line_number=line_no,
                            )
                        )

    def _check_base_classes(self, tree: ast.AST, result: ValidationResult) -> None:
        """Check that Node classes inherit from correct base classes"""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                line_no = node.lineno

                # Check Node classes
                if class_name.startswith("Node") and not class_name.startswith(
                    "NodeTest"
                ):
                    base_names = [self._get_base_name(base) for base in node.bases]

                    # Determine expected base class
                    expected_base = None
                    if class_name.endswith("Effect"):
                        expected_base = "NodeEffect"
                    elif class_name.endswith("Compute"):
                        expected_base = "NodeCompute"
                    elif class_name.endswith("Reducer"):
                        expected_base = "NodeReducer"
                    elif class_name.endswith("Orchestrator"):
                        expected_base = "NodeOrchestrator"

                    if expected_base:
                        if expected_base in base_names:
                            result.checks.append(
                                ValidationCheck(
                                    check_type=CheckType.BASE_CLASS,
                                    status=CheckStatus.PASS,
                                    rule="correct_base_class",
                                    message=f"{class_name} inherits from {expected_base}",
                                    line_number=line_no,
                                )
                            )
                        else:
                            result.checks.append(
                                ValidationCheck(
                                    check_type=CheckType.BASE_CLASS,
                                    status=CheckStatus.FAIL,
                                    rule="missing_base_class",
                                    message=f"{class_name} does not inherit from {expected_base}",
                                    line_number=line_no,
                                    details=f"Found base classes: {', '.join(base_names) if base_names else 'none'}",
                                    suggestion=f"Add {expected_base} as base class: class {class_name}({expected_base}):",
                                )
                            )

    def _get_base_name(self, base: ast.expr) -> str:
        """Extract base class name from AST node"""
        if isinstance(base, ast.Name):
            return base.id
        elif isinstance(base, ast.Attribute):
            return base.attr
        return ""

    def _check_container_di(self, tree: ast.AST, result: ValidationResult) -> None:
        """Check for container-based dependency injection"""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                line_no = node.lineno

                # Check Node classes
                if class_name.startswith("Node") and not class_name.startswith(
                    "NodeTest"
                ):
                    # Find __init__ method
                    init_method = None
                    for item in node.body:
                        if (
                            isinstance(item, ast.FunctionDef)
                            and item.name == "__init__"
                        ):
                            init_method = item
                            break

                    if init_method:
                        # Check for container parameter
                        has_container = False
                        for arg in init_method.args.args[1:]:  # Skip self
                            if arg.arg == "container":
                                # Check type annotation
                                if arg.annotation:
                                    annotation = self._get_annotation_name(
                                        arg.annotation
                                    )
                                    if annotation == "ModelONEXContainer":
                                        has_container = True
                                        result.checks.append(
                                            ValidationCheck(
                                                check_type=CheckType.DI_CONTAINER,
                                                status=CheckStatus.PASS,
                                                rule="container_di_present",
                                                message=f"{class_name}.__init__ uses container DI",
                                                line_number=init_method.lineno,
                                            )
                                        )
                                        break

                        if not has_container:
                            result.checks.append(
                                ValidationCheck(
                                    check_type=CheckType.DI_CONTAINER,
                                    status=CheckStatus.WARNING,
                                    rule="container_di_missing",
                                    message=f"{class_name}.__init__ missing container DI",
                                    line_number=(
                                        init_method.lineno if init_method else line_no
                                    ),
                                    suggestion="Add: def __init__(self, container: ModelONEXContainer):",
                                )
                            )

    def _get_annotation_name(self, annotation: ast.expr) -> str:
        """Extract type annotation name"""
        if isinstance(annotation, ast.Name):
            return annotation.id
        elif isinstance(annotation, ast.Attribute):
            return annotation.attr
        return ""

    def _check_pydantic_v2(self, content: str, result: ValidationResult) -> None:
        """Check for Pydantic v2 compliance"""
        lines = content.split("\n")

        for pattern, replacement in self.PYDANTIC_V1_PATTERNS.items():
            for line_no, line in enumerate(lines, 1):
                if pattern in line:
                    result.checks.append(
                        ValidationCheck(
                            check_type=CheckType.PYDANTIC,
                            status=CheckStatus.FAIL,
                            rule="pydantic_v1_pattern",
                            message=f"Pydantic v1 pattern found: {pattern}",
                            line_number=line_no,
                            details=f"Found in: {line.strip()}",
                            suggestion=f"Replace with: {replacement}",
                        )
                    )

    def _check_type_hints(self, tree: ast.AST, result: ValidationResult) -> None:
        """Check for proper type hints and avoid Any types"""
        for node in ast.walk(tree):
            # Check function definitions
            if isinstance(node, ast.FunctionDef):
                # Check for return type annotation
                if not node.returns and node.name not in [
                    "__init__",
                    "__str__",
                    "__repr__",
                ]:
                    result.checks.append(
                        ValidationCheck(
                            check_type=CheckType.TYPE_HINT,
                            status=CheckStatus.WARNING,
                            rule="missing_return_type",
                            message=f"Function {node.name} missing return type annotation",
                            line_number=node.lineno,
                            suggestion="Add return type annotation",
                        )
                    )

                # Check for Any type usage
                if node.returns:
                    annotation_str = ast.unparse(node.returns)
                    if "Any" in annotation_str:
                        result.checks.append(
                            ValidationCheck(
                                check_type=CheckType.TYPE_HINT,
                                status=CheckStatus.WARNING,
                                rule="any_type_usage",
                                message=f"Function {node.name} uses Any type",
                                line_number=node.lineno,
                                details="ONEX standards discourage Any types",
                                suggestion="Use specific types instead of Any",
                            )
                        )

    def _check_forbidden_patterns(self, content: str, result: ValidationResult) -> None:
        """Check for forbidden patterns"""
        lines = content.split("\n")

        for pattern, reason in self.FORBIDDEN_PATTERNS.items():
            for line_no, line in enumerate(lines, 1):
                if pattern in line and not line.strip().startswith("#"):
                    result.checks.append(
                        ValidationCheck(
                            check_type=CheckType.FORBIDDEN,
                            status=CheckStatus.WARNING,
                            rule="forbidden_pattern",
                            message=f"Forbidden pattern: {pattern}",
                            line_number=line_no,
                            details=reason,
                        )
                    )

    def validate_directory(
        self, directory: Path, recursive: bool = False, pattern: str = "*.py"
    ) -> List[ValidationResult]:
        """
        Validate all Python files in a directory

        Args:
            directory: Directory to validate
            recursive: Recursively validate subdirectories
            pattern: File pattern to match

        Returns:
            List of ValidationResult for each file
        """
        results = []

        if recursive:
            files = directory.rglob(pattern)
        else:
            files = directory.glob(pattern)

        for file_path in files:
            if file_path.is_file():
                results.append(self.validate_file(file_path))

        return results


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="OmniBase Core Compatibility Validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate a single file
  python tools/compatibility_validator.py --file agents/templates/effect_node_template.py

  # Validate with JSON output
  python tools/compatibility_validator.py --file mynode.py --json

  # Validate all templates
  python tools/compatibility_validator.py --directory agents/templates --json

  # Validate recursively with strict mode
  python tools/compatibility_validator.py --directory agents --recursive --strict

  # Check specific patterns only
  python tools/compatibility_validator.py --file myfile.py --check-imports --check-patterns
        """,
    )

    parser.add_argument("--file", type=Path, help="File to validate")
    parser.add_argument("--directory", type=Path, help="Directory to validate")
    parser.add_argument(
        "--recursive", action="store_true", help="Recursively validate subdirectories"
    )
    parser.add_argument(
        "--pattern", default="*.py", help="File pattern to match (default: *.py)"
    )
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parser.add_argument(
        "--strict", action="store_true", help="Strict mode (warnings become errors)"
    )
    parser.add_argument(
        "--template-mode",
        action="store_true",
        help="Template mode (substitute placeholders)",
    )
    parser.add_argument("--omnibase-path", type=Path, help="Path to omnibase_core")

    # Filter options
    parser.add_argument(
        "--check-imports", action="store_true", help="Only check imports"
    )
    parser.add_argument(
        "--check-patterns", action="store_true", help="Only check naming patterns"
    )
    parser.add_argument(
        "--check-pydantic", action="store_true", help="Only check Pydantic v2"
    )
    parser.add_argument(
        "--check-all", action="store_true", help="Run all checks (default)"
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.file and not args.directory:
        parser.error("Must specify either --file or --directory")

    if args.file and args.directory:
        parser.error("Cannot specify both --file and --directory")

    # Create validator
    validator = OmniBaseCompatibilityValidator(
        strict=args.strict,
        omnibase_path=args.omnibase_path,
        template_mode=args.template_mode,
    )

    # Run validation
    results = []
    if args.file:
        if not args.file.exists():
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        results = [validator.validate_file(args.file)]
    elif args.directory:
        if not args.directory.exists():
            print(f"Error: Directory not found: {args.directory}", file=sys.stderr)
            sys.exit(1)
        results = validator.validate_directory(
            args.directory, recursive=args.recursive, pattern=args.pattern
        )

    # Output results
    if args.json:
        output = {
            "total_files": len(results),
            "results": [r.to_dict() for r in results],
            "overall_summary": {
                "passed": sum(
                    1 for r in results if r.overall_status == CheckStatus.PASS
                ),
                "failed": sum(
                    1 for r in results if r.overall_status == CheckStatus.FAIL
                ),
                "warnings": sum(
                    1 for r in results if r.overall_status == CheckStatus.WARNING
                ),
            },
        }
        print(json.dumps(output, indent=2))
    else:
        # Human-readable output
        for result in results:
            print(f"\n{'=' * 80}")
            print(f"File: {result.file_path}")
            print(f"Status: {result.overall_status.value.upper()}")
            print(f"Summary: {result.summary}")
            print(f"{'=' * 80}")

            if result.errors:
                print("\nErrors:")
                for error in result.errors:
                    print(f"  ❌ {error}")

            # Group checks by status
            failed = [c for c in result.checks if c.status == CheckStatus.FAIL]
            warnings = [c for c in result.checks if c.status == CheckStatus.WARNING]
            passed = [c for c in result.checks if c.status == CheckStatus.PASS]

            if failed:
                print(f"\n❌ Failed Checks ({len(failed)}):")
                for check in failed:
                    print(f"\n  [{check.check_type.value}] {check.rule}")
                    print(f"  Line {check.line_number}: {check.message}")
                    if check.details:
                        print(f"  Details: {check.details}")
                    if check.suggestion:
                        print(f"  💡 Suggestion: {check.suggestion}")

            if warnings:
                print(f"\n⚠️  Warnings ({len(warnings)}):")
                for check in warnings:
                    print(f"\n  [{check.check_type.value}] {check.rule}")
                    print(f"  Line {check.line_number}: {check.message}")
                    if check.suggestion:
                        print(f"  💡 Suggestion: {check.suggestion}")

            if args.json or not failed:  # Show passed only in verbose mode
                print(f"\n✅ Passed Checks ({len(passed)})")

    # Exit code
    has_failures = any(r.overall_status == CheckStatus.FAIL for r in results)
    has_warnings = any(r.overall_status == CheckStatus.WARNING for r in results)

    if has_failures:
        sys.exit(1)
    elif has_warnings and args.strict:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
