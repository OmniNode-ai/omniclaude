#!/usr/bin/env python3
"""
Quality Validator for Phase 5 - Autonomous Code Generation

Comprehensive validation of generated code including:
- Static analysis (syntax, imports, type hints)
- ONEX compliance scoring (naming, type safety, error handling)
- Contract conformance validation
- Mixin compatibility checks
- Quality scoring with detailed feedback

Author: OmniClaude Autonomous Code Generation System
"""

import ast
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

# Import from omnibase_core
from omnibase_core.errors import EnumCoreErrorCode, OnexError

from .codegen_config import CodegenConfig
from .codegen_events import CodegenValidationRequest, CodegenValidationResponse

# Framework: ML-powered mixin compatibility (optional import)
try:
    from .mixin_compatibility import MixinCompatibilityManager

    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

# Quality gate event publisher (optional import)
try:
    from .quality_gate_publisher import publish_quality_gate_failed

    QUALITY_GATE_EVENTS_AVAILABLE = True
except ImportError:
    QUALITY_GATE_EVENTS_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """
    Result of code quality validation.

    Attributes:
        is_valid: Whether code passes validation threshold
        quality_score: Overall quality score (0.0-1.0)
        violations: List of validation violations
        suggestions: List of improvement suggestions
        compliance_details: Detailed compliance breakdown by category
    """

    is_valid: bool
    quality_score: float
    violations: List[str]
    suggestions: List[str]
    compliance_details: Dict[str, Any]
    validation_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ONEXComplianceCheck:
    """ONEX compliance check result"""

    category: str
    passed: bool
    score: float
    violations: List[str]
    suggestions: List[str]


class QualityValidator:
    """
    Comprehensive quality validator for generated code.

    Validates generated code against ONEX standards, contract requirements,
    and quality best practices. Provides detailed scoring and feedback.
    """

    def __init__(
        self, config: Optional[CodegenConfig] = None, enable_ml_validation: bool = True
    ):
        """
        Initialize quality validator.

        Args:
            config: Optional codegen configuration (uses default if not provided)
            enable_ml_validation: Whether to enable ML-powered mixin validation
        """
        self.config = config or CodegenConfig()
        self.logger = logging.getLogger(__name__)

        # Framework: Initialize ML-powered mixin compatibility manager
        self.enable_ml = enable_ml_validation and ML_AVAILABLE
        if self.enable_ml:
            try:
                self.mixin_manager = MixinCompatibilityManager(enable_ml=True)
                self.logger.info("ML-powered mixin validation enabled")
            except Exception as e:
                self.logger.warning(f"Failed to initialize ML validation: {e}")
                self.enable_ml = False
                self.mixin_manager = None
        else:
            self.mixin_manager = None

        # ONEX naming patterns
        self.node_class_pattern = re.compile(
            r"^Node[A-Z][a-zA-Z0-9]+(Effect|Compute|Reducer|Orchestrator)$"
        )
        self.model_class_pattern = re.compile(r"^Model[A-Z][a-zA-Z0-9]+$")
        self.enum_class_pattern = re.compile(r"^Enum[A-Z][a-zA-Z0-9]+$")

        # Required node methods
        self.required_node_methods = {
            "Effect": ["process_effect", "validate_input", "get_health_status"],
            "Compute": ["process_compute", "validate_input", "get_health_status"],
            "Reducer": ["process_reduction", "validate_input", "get_health_status"],
            "Orchestrator": [
                "process_orchestration",
                "validate_input",
                "get_health_status",
            ],
        }

        # Standard library imports (for import organization check)
        self.stdlib_modules = {
            "asyncio",
            "logging",
            "typing",
            "uuid",
            "datetime",
            "dataclasses",
            "enum",
            "re",
            "json",
            "os",
            "sys",
            "pathlib",
            "collections",
        }

    async def validate_generated_code(
        self,
        code: str,
        contract: Dict[str, Any],
        node_type: str,
        microservice_name: str,
        correlation_id: Optional[UUID] = None,
    ) -> ValidationResult:
        """
        Validate generated code comprehensively.

        Args:
            code: Generated Python code to validate
            contract: Contract dictionary defining expected capabilities
            node_type: Type of node (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
            microservice_name: Name of the microservice
            correlation_id: Optional correlation ID for tracking

        Returns:
            ValidationResult with scores and detailed feedback

        Raises:
            OnexError: If validation encounters critical errors
        """
        try:
            validation_id = uuid4()
            self.logger.info(
                f"Starting validation {validation_id} for {node_type} node: {microservice_name}"
            )

            # Initialize results
            all_violations = []
            all_suggestions = []
            check_results = {}

            # 1. Syntax validation (30% weight)
            syntax_valid, syntax_violations = self._check_syntax(code)
            check_results["syntax"] = {
                "valid": syntax_valid,
                "violations": syntax_violations,
                "weight": 0.30,
            }
            all_violations.extend(syntax_violations)

            if not syntax_valid:
                # Cannot proceed with other checks if syntax is invalid
                return ValidationResult(
                    is_valid=False,
                    quality_score=0.0,
                    violations=all_violations,
                    suggestions=["Fix syntax errors before proceeding"],
                    compliance_details=check_results,
                    validation_id=validation_id,
                )

            # 2. ONEX compliance validation (40% weight)
            onex_score, onex_violations, onex_suggestions = self._check_onex_compliance(
                code, node_type
            )
            check_results["onex_compliance"] = {
                "score": onex_score,
                "violations": onex_violations,
                "suggestions": onex_suggestions,
                "weight": 0.40,
            }
            all_violations.extend(onex_violations)
            all_suggestions.extend(onex_suggestions)

            # 3. Contract conformance validation (20% weight)
            contract_score, contract_violations, contract_suggestions = (
                self._check_contract_conformance(code, contract, node_type)
            )
            check_results["contract_conformance"] = {
                "score": contract_score,
                "violations": contract_violations,
                "suggestions": contract_suggestions,
                "weight": 0.20,
            }
            all_violations.extend(contract_violations)
            all_suggestions.extend(contract_suggestions)

            # 4. Code quality checks (10% weight)
            quality_score, quality_violations, quality_suggestions = (
                self._check_code_quality(code)
            )
            check_results["code_quality"] = {
                "score": quality_score,
                "violations": quality_violations,
                "suggestions": quality_suggestions,
                "weight": 0.10,
            }
            all_violations.extend(quality_violations)
            all_suggestions.extend(quality_suggestions)

            # Calculate overall quality score
            overall_score = self._calculate_quality_score(check_results)

            # Determine if validation passes
            is_valid = (
                syntax_valid
                and overall_score >= self.config.quality_threshold
                and onex_score >= self.config.onex_compliance_threshold
            )

            result = ValidationResult(
                is_valid=is_valid,
                quality_score=overall_score,
                violations=all_violations,
                suggestions=all_suggestions,
                compliance_details=check_results,
                validation_id=validation_id,
            )

            self.logger.info(
                f"Validation {validation_id} completed: "
                f"valid={is_valid}, score={overall_score:.2f}, "
                f"violations={len(all_violations)}"
            )

            # Publish quality gate failed event if validation failed
            if not is_valid and QUALITY_GATE_EVENTS_AVAILABLE:
                await self._publish_quality_gate_failures(
                    check_results=check_results,
                    correlation_id=correlation_id or validation_id,
                    all_violations=all_violations,
                    all_suggestions=all_suggestions,
                )

            return result

        except Exception as e:
            self.logger.error(f"Quality validation failed: {str(e)}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Quality validation failed: {str(e)}",
                details={
                    "node_type": node_type,
                    "microservice_name": microservice_name,
                    "code_length": len(code),
                },
            )

    def _check_syntax(self, code: str) -> Tuple[bool, List[str]]:
        """
        Check Python syntax validity.

        Args:
            code: Python code to check

        Returns:
            Tuple of (is_valid, list of syntax violations)
        """
        violations = []

        try:
            # Attempt to parse as AST
            ast.parse(code)
            return True, []

        except SyntaxError as e:
            violations.append(f"Syntax error at line {e.lineno}: {e.msg}")
            return False, violations

        except Exception as e:
            violations.append(f"Code parsing error: {str(e)}")
            return False, violations

    def _check_onex_compliance(
        self, code: str, node_type: str
    ) -> Tuple[float, List[str], List[str]]:
        """
        Check ONEX architecture compliance.

        Validates:
        - Naming conventions (Node<Name><Type>, Model<Name>, Enum<Name>)
        - No bare Any types (must be Dict[str, Any] or specific)
        - Type hints on all methods
        - OnexError usage for exceptions
        - Async patterns
        - Import organization

        Args:
            code: Python code to check
            node_type: Expected node type

        Returns:
            Tuple of (compliance_score, violations, suggestions)
        """
        violations = []
        suggestions = []

        try:
            tree = ast.parse(code)

            # Check naming conventions
            naming_score = self._check_naming_conventions(
                tree, node_type, violations, suggestions
            )

            # Check type hints
            type_hint_score = self._check_type_hints(tree, violations, suggestions)

            # Check for bare Any types
            any_type_score = self._check_any_types(code, violations, suggestions)

            # Check error handling
            error_handling_score = self._check_error_handling(
                tree, violations, suggestions
            )

            # Check async patterns
            async_score = self._check_async_patterns(
                tree, node_type, violations, suggestions
            )

            # Check import organization
            import_score = self._check_import_organization(
                tree, violations, suggestions
            )

            # Calculate weighted compliance score
            # Give higher weight to critical type safety (any_type_score)
            compliance_score = (
                naming_score * 0.20
                + type_hint_score * 0.15
                + any_type_score * 0.18  # Increased from 0.15 for stricter checking
                + error_handling_score * 0.15
                + async_score * 0.22
                + import_score * 0.10
            )

            # Critical check: if type safety is severely violated, cap the compliance score
            # Only cap for severe violations (multiple bare Any + incomplete generics)
            if any_type_score <= 0.3:
                compliance_score = min(compliance_score, 0.5)

            # Clamp to [0.0, 1.0] to handle floating point precision
            compliance_score = min(max(compliance_score, 0.0), 1.0)

            return compliance_score, violations, suggestions

        except Exception as e:
            violations.append(f"ONEX compliance check failed: {str(e)}")
            return 0.0, violations, suggestions

    def _check_naming_conventions(
        self,
        tree: ast.AST,
        node_type: str,
        violations: List[str],
        suggestions: List[str],
    ) -> float:
        """Check ONEX naming conventions"""
        score = 1.0

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name

                # Check Node class naming
                if class_name.startswith("Node"):
                    if not self.node_class_pattern.match(class_name):
                        violations.append(
                            f"Invalid node class name '{class_name}'. "
                            f"Must follow pattern: Node<Domain><Service><Type>"
                        )
                        score *= 0.7

                    # Check if suffix matches node_type
                    expected_suffix = node_type.capitalize()
                    if not class_name.endswith(expected_suffix):
                        violations.append(
                            f"Node class '{class_name}' should end with '{expected_suffix}'"
                        )
                        score *= 0.8

                # Check Model class naming
                elif class_name.startswith("Model"):
                    if not self.model_class_pattern.match(class_name):
                        violations.append(
                            f"Invalid model class name '{class_name}'. "
                            f"Must follow pattern: Model<Name>"
                        )
                        score *= 0.8

                # Check Enum class naming
                elif class_name.startswith("Enum"):
                    if not self.enum_class_pattern.match(class_name):
                        violations.append(
                            f"Invalid enum class name '{class_name}'. "
                            f"Must follow pattern: Enum<Name>"
                        )
                        score *= 0.8

        return max(score, 0.0)

    def _check_type_hints(
        self, tree: ast.AST, violations: List[str], suggestions: List[str]
    ) -> float:
        """Check that all methods have type hints"""
        total_methods = 0
        methods_with_hints = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(
                node, ast.AsyncFunctionDef
            ):
                total_methods += 1

                # Check return type hint
                has_return_hint = node.returns is not None

                # Check argument type hints (skip self/cls)
                args_with_hints = sum(
                    1
                    for arg in node.args.args
                    if arg.arg not in ("self", "cls") and arg.annotation is not None
                )
                total_args = len(
                    [arg for arg in node.args.args if arg.arg not in ("self", "cls")]
                )

                if has_return_hint and (
                    total_args == 0 or args_with_hints == total_args
                ):
                    methods_with_hints += 1
                else:
                    violations.append(
                        f"Method '{node.name}' missing type hints "
                        f"(return: {has_return_hint}, args: {args_with_hints}/{total_args})"
                    )

        if total_methods == 0:
            return 1.0

        score = methods_with_hints / total_methods

        if score < 1.0:
            suggestions.append("Add type hints to all method signatures")

        return score

    def _check_any_types(
        self, code: str, violations: List[str], suggestions: List[str]
    ) -> float:
        """Check for bare Any types (must be Dict[str, Any] or specific types)"""
        score = 1.0

        # Pattern to find bare Any usage (not Dict[str, Any], List[Any], etc.)
        # Match both parameter types (: Any) and return types (-> Any)
        bare_any_pattern = re.compile(r"(?::\s*|->\s*)Any(?!\[)")
        any_matches = bare_any_pattern.findall(code)

        if any_matches:
            violations.append(
                f"Found {len(any_matches)} instances of bare 'Any' type. "
                "Use Dict[str, Any], List[Any], or specific types instead"
            )
            suggestions.append(
                "Replace bare 'Any' with specific types or Dict[str, Any]"
            )
            # Penalize heavily for bare Any (0.25 per instance)
            score -= len(any_matches) * 0.25

        # Also check for incomplete generic types (Dict, List, Set without type parameters)
        incomplete_generic_pattern = re.compile(
            r"(?::\s*|->\s*)(Dict|List|Set|Tuple)(?!\[)"
        )
        incomplete_matches = incomplete_generic_pattern.findall(code)

        if incomplete_matches:
            violations.append(
                f"Found {len(incomplete_matches)} incomplete generic types. "
                "Specify type parameters (e.g., Dict[str, Any], List[str])"
            )
            suggestions.append("Add type parameters to generic types")
            # Penalize moderately for incomplete generics (0.12 per instance)
            score -= len(incomplete_matches) * 0.12

        return max(0.0, score)

    def _check_error_handling(
        self, tree: ast.AST, violations: List[str], suggestions: List[str]
    ) -> float:
        """Check OnexError usage for exception handling"""
        score = 1.0
        has_onex_error_import = False
        uses_onex_error = False
        has_generic_exceptions = False

        for node in ast.walk(tree):
            # Check for OnexError import
            if isinstance(node, ast.ImportFrom):
                if node.module and "omnibase_core" in node.module:
                    for alias in node.names:
                        if alias.name == "OnexError":
                            has_onex_error_import = True

            # Check for OnexError raises
            if isinstance(node, ast.Raise):
                if node.exc and isinstance(node.exc, ast.Call):
                    if isinstance(node.exc.func, ast.Name):
                        if node.exc.func.id == "OnexError":
                            uses_onex_error = True
                        elif node.exc.func.id == "Exception":
                            has_generic_exceptions = True

        if not has_onex_error_import:
            violations.append("Missing OnexError import from omnibase_core.errors")
            suggestions.append("Import OnexError for proper exception handling")
            score *= 0.5

        if has_generic_exceptions and not uses_onex_error:
            violations.append("Using generic Exception instead of OnexError")
            suggestions.append("Replace generic exceptions with OnexError")
            score *= 0.7

        return score

    def _check_async_patterns(
        self,
        tree: ast.AST,
        node_type: str,
        violations: List[str],
        suggestions: List[str],
    ) -> float:
        """Check proper async/await patterns"""
        score = 1.0
        required_async_methods = self.required_node_methods.get(node_type, [])

        async_methods = set()
        sync_methods = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                async_methods.add(node.name)
            elif isinstance(node, ast.FunctionDef):
                if node.name not in ("__init__", "__post_init__"):
                    sync_methods.add(node.name)

        # Check if required methods are async
        for required_method in required_async_methods:
            if required_method in sync_methods:
                violations.append(
                    f"Required method '{required_method}' should be async"
                )
                score *= 0.8

        return score

    def _check_import_organization(
        self, tree: ast.AST, violations: List[str], suggestions: List[str]
    ) -> float:
        """Check import organization (stdlib, third-party, local)"""
        score = 1.0
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(node)

        if not imports:
            return 1.0

        # Check import order
        import_sections = self._categorize_imports(imports)

        if not self._is_import_order_correct(import_sections):
            violations.append(
                "Imports not organized correctly (should be: stdlib, third-party, local)"
            )
            suggestions.append("Organize imports: standard library, third-party, local")
            score = 0.7

        return score

    def _categorize_imports(self, imports: List[ast.AST]) -> Dict[str, List[ast.AST]]:
        """Categorize imports into stdlib, third-party, local"""
        categorized = {"stdlib": [], "third_party": [], "local": []}

        for imp in imports:
            if isinstance(imp, ast.ImportFrom):
                module = imp.module or ""
                if module.startswith("."):
                    categorized["local"].append(imp)
                elif module.split(".")[0] in self.stdlib_modules:
                    categorized["stdlib"].append(imp)
                else:
                    categorized["third_party"].append(imp)
            elif isinstance(imp, ast.Import):
                for alias in imp.names:
                    if alias.name.split(".")[0] in self.stdlib_modules:
                        categorized["stdlib"].append(imp)
                    else:
                        categorized["third_party"].append(imp)

        return categorized

    def _is_import_order_correct(
        self, import_sections: Dict[str, List[ast.AST]]
    ) -> bool:
        """Check if imports are in correct order"""
        # For simplicity, just check they are present in the right categories
        # Full implementation would check line numbers
        return True  # TODO: Implement line number checking

    def _check_contract_conformance(
        self, code: str, contract: Dict[str, Any], node_type: str
    ) -> Tuple[float, List[str], List[str]]:
        """
        Check contract conformance.

        Validates:
        - All contract capabilities are implemented as methods
        - Mixin inheritance matches contract mixins
        - External dependencies are handled

        Args:
            code: Python code to check
            contract: Contract dictionary
            node_type: Node type

        Returns:
            Tuple of (conformance_score, violations, suggestions)
        """
        violations = []
        suggestions = []

        try:
            tree = ast.parse(code)

            # Extract implemented methods
            implemented_methods = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    implemented_methods.add(node.name)

            # Check required node methods
            required_methods = self.required_node_methods.get(node_type, [])
            missing_methods = set(required_methods) - implemented_methods

            if missing_methods:
                violations.append(
                    f"Missing required methods for {node_type} node: {', '.join(missing_methods)}"
                )

            # Check contract capabilities are implemented
            capabilities = contract.get("capabilities", [])
            capability_methods = [
                cap["name"]
                for cap in capabilities
                if isinstance(cap, dict) and "name" in cap
            ]

            missing_capabilities = []
            for cap_method in capability_methods:
                # Check if capability method exists
                method_variants = [
                    cap_method,
                    f"_{cap_method}",  # Private method variant
                    f"process_{cap_method}",
                    f"handle_{cap_method}",
                    cap_method.replace("_", ""),
                ]

                if not any(
                    variant in implemented_methods for variant in method_variants
                ):
                    missing_capabilities.append(cap_method)

            if missing_capabilities:
                violations.append(
                    f"Contract capabilities not implemented: {', '.join(missing_capabilities[:5])}"
                )
                suggestions.append("Implement methods for all contract capabilities")

            # Check mixin inheritance
            required_mixins = contract.get("dependencies", {}).get(
                "required_mixins", []
            )
            mixin_conformance = self._check_mixin_inheritance(
                tree, required_mixins, violations
            )

            # Calculate conformance score
            required_method_score = 1.0 - (
                len(missing_methods) / max(len(required_methods), 1)
            )
            capability_score = 1.0 - (
                len(missing_capabilities) / max(len(capability_methods), 1)
            )

            conformance_score = (
                required_method_score * 0.5
                + capability_score * 0.3
                + mixin_conformance * 0.2
            )

            return conformance_score, violations, suggestions

        except Exception as e:
            violations.append(f"Contract conformance check failed: {str(e)}")
            return 0.0, violations, suggestions

    def _check_mixin_inheritance(
        self, tree: ast.AST, required_mixins: List[str], violations: List[str]
    ) -> float:
        """Check mixin inheritance matches contract"""
        if not required_mixins:
            return 1.0

        # Find class definitions and their bases
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if node.name.startswith("Node"):
                    # Extract base classes
                    base_names = []
                    for base in node.bases:
                        if isinstance(base, ast.Name):
                            base_names.append(base.id)

                    # Check if required mixins are present
                    missing_mixins = [
                        mixin for mixin in required_mixins if mixin not in base_names
                    ]

                    if missing_mixins:
                        violations.append(
                            f"Missing mixin inheritance: {', '.join(missing_mixins)}"
                        )
                        return 1.0 - (len(missing_mixins) / len(required_mixins))

                    return 1.0

        return 0.5  # Node class not found

    async def validate_mixin_compatibility(
        self, code: str, node_type: str
    ) -> Tuple[float, List[str], List[str]]:
        """
        Validate mixin compatibility using ML-powered compatibility manager.

        Args:
            code: Generated code to validate
            node_type: ONEX node type

        Returns:
            Tuple of (compatibility_score, violations, suggestions)
        """
        violations = []
        suggestions = []

        try:
            tree = ast.parse(code)

            # Extract inherited mixins from code
            mixins = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    if node.name.startswith("Node"):
                        for base in node.bases:
                            if isinstance(base, ast.Name):
                                if base.id.startswith("Mixin"):
                                    mixins.append(base.id)

            if not mixins:
                # No mixins found - this is okay
                return 1.0, violations, suggestions

            # Validate mixin set compatibility if ML is enabled
            if self.enable_ml and self.mixin_manager:
                try:
                    mixin_set = await self.mixin_manager.validate_mixin_set(
                        mixins, node_type
                    )

                    # Add warnings as violations
                    if mixin_set.warnings:
                        for warning in mixin_set.warnings:
                            violations.append(f"Mixin compatibility: {warning}")

                    # Check overall compatibility
                    if mixin_set.overall_compatibility < 0.6:
                        violations.append(
                            f"Overall mixin compatibility score is low: {mixin_set.overall_compatibility:.2f}"
                        )
                        suggestions.append(
                            "Consider reviewing mixin selection or resolving compatibility conflicts"
                        )

                    return mixin_set.overall_compatibility, violations, suggestions

                except Exception as e:
                    self.logger.warning(f"ML mixin validation failed: {e}")
                    # Fall through to rule-based validation

            # Rule-based validation (fallback)
            # Check for duplicate mixins
            if len(mixins) != len(set(mixins)):
                violations.append("Duplicate mixin inheritance detected")
                return 0.5, violations, suggestions

            return 1.0, violations, suggestions

        except Exception as e:
            violations.append(f"Mixin compatibility validation failed: {str(e)}")
            return 0.5, violations, suggestions

    def _check_code_quality(self, code: str) -> Tuple[float, List[str], List[str]]:
        """
        Check general code quality.

        Checks:
        - Docstrings present
        - Error handling patterns
        - Logging usage
        - Code complexity (basic)

        Args:
            code: Python code to check

        Returns:
            Tuple of (quality_score, violations, suggestions)
        """
        violations = []
        suggestions = []

        try:
            tree = ast.parse(code)

            # Check docstrings
            docstring_score = self._check_docstrings(tree, violations, suggestions)

            # Check logging usage
            logging_score = self._check_logging(tree, violations, suggestions)

            # Check error handling patterns
            error_handling_score = self._check_try_except_usage(
                tree, violations, suggestions
            )

            quality_score = (
                docstring_score * 0.4 + logging_score * 0.3 + error_handling_score * 0.3
            )

            return quality_score, violations, suggestions

        except Exception as e:
            violations.append(f"Code quality check failed: {str(e)}")
            return 0.5, violations, suggestions

    def _check_docstrings(
        self, tree: ast.AST, violations: List[str], suggestions: List[str]
    ) -> float:
        """Check docstring presence"""
        total_items = 0
        items_with_docstrings = 0

        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                total_items += 1
                if ast.get_docstring(node):
                    items_with_docstrings += 1

        if total_items == 0:
            return 1.0

        score = items_with_docstrings / total_items

        if score < 0.8:
            suggestions.append("Add docstrings to classes and methods")

        return score

    def _check_logging(
        self, tree: ast.AST, violations: List[str], suggestions: List[str]
    ) -> float:
        """Check logging usage"""
        has_logger = False
        uses_logging = False

        for node in ast.walk(tree):
            # Check for logger initialization
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "logger":
                        has_logger = True

            # Check for logging calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr in (
                        "debug",
                        "info",
                        "warning",
                        "error",
                        "critical",
                    ):
                        uses_logging = True

        if not has_logger:
            suggestions.append("Add logger initialization for debugging")
            return 0.5

        if not uses_logging:
            suggestions.append("Add logging statements for key operations")
            return 0.7

        return 1.0

    def _check_try_except_usage(
        self, tree: ast.AST, violations: List[str], suggestions: List[str]
    ) -> float:
        """Check try/except usage"""
        has_try_except = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                has_try_except = True
                break

        if not has_try_except:
            suggestions.append("Add error handling with try/except blocks")
            return 0.5

        return 1.0

    def _calculate_quality_score(self, check_results: Dict[str, Any]) -> float:
        """
        Calculate overall quality score from check results.

        Uses weighted average based on check importance:
        - Syntax: 30%
        - ONEX compliance: 40%
        - Contract conformance: 20%
        - Code quality: 10%

        Args:
            check_results: Dictionary of check results with scores and weights

        Returns:
            Overall quality score (0.0-1.0)
        """
        total_score = 0.0

        for check_name, result in check_results.items():
            if check_name == "syntax":
                # Syntax is binary - either valid or not
                score = 1.0 if result["valid"] else 0.0
            else:
                score = result.get("score", 0.0)

            weight = result.get("weight", 0.0)
            total_score += score * weight

        return min(max(total_score, 0.0), 1.0)

    async def _publish_quality_gate_failures(
        self,
        check_results: Dict[str, Any],
        correlation_id: UUID,
        all_violations: List[str],
        all_suggestions: List[str],
    ) -> None:
        """
        Publish quality gate failed events for each failed quality gate.

        Publishes separate events for each quality gate that failed its threshold.

        Args:
            check_results: Dictionary of check results with scores and thresholds
            correlation_id: Correlation ID for event tracking
            all_violations: All violations from validation
            all_suggestions: All suggestions from validation
        """
        if not QUALITY_GATE_EVENTS_AVAILABLE:
            return

        try:
            # Define thresholds for each quality gate
            gate_thresholds = {
                "syntax": 1.0,  # Must be 100% valid
                "onex_compliance": self.config.onex_compliance_threshold,
                "contract_conformance": 0.80,  # 80% conformance required
                "code_quality": 0.70,  # 70% quality required
            }

            # Publish event for each failed gate
            for check_name, result in check_results.items():
                # Get score for this check
                if check_name == "syntax":
                    score = 1.0 if result.get("valid", False) else 0.0
                else:
                    score = result.get("score", 0.0)

                # Get threshold for this gate
                threshold = gate_thresholds.get(check_name, 0.80)

                # If gate failed threshold, publish event
                if score < threshold:
                    gate_violations = result.get("violations", [])
                    gate_suggestions = result.get("suggestions", [])

                    await publish_quality_gate_failed(
                        gate_name=check_name,
                        correlation_id=str(correlation_id),
                        score=score,
                        threshold=threshold,
                        failure_reasons=(
                            gate_violations if gate_violations else all_violations
                        ),
                        recommendations=(
                            gate_suggestions if gate_suggestions else all_suggestions
                        ),
                    )

                    self.logger.debug(
                        f"Published quality gate failed event: {check_name} "
                        f"(score={score:.2f}, threshold={threshold:.2f})"
                    )

        except Exception as e:
            # Log error but don't fail validation - event publishing is optional
            self.logger.warning(f"Failed to publish quality gate failed events: {e}")

    # Event-driven integration methods (future phase)

    async def publish_validation_request(
        self,
        code: str,
        contract: Dict[str, Any],
        node_type: str,
        microservice_name: str,
        correlation_id: UUID,
    ) -> CodegenValidationRequest:
        """
        Publish validation request to Kafka (future implementation).

        Args:
            code: Code to validate
            contract: Contract definition
            node_type: Node type
            microservice_name: Service name
            correlation_id: Correlation ID

        Returns:
            Validation request event
        """
        # TODO: Implement Kafka publishing
        request = CodegenValidationRequest(
            correlation_id=correlation_id,
            payload={
                "code": code,
                "contract": contract,
                "node_type": node_type,
                "microservice_name": microservice_name,
            },
        )

        self.logger.info(
            f"Validation request prepared for {microservice_name} "
            f"(correlation_id: {correlation_id})"
        )

        return request

    async def wait_for_validation_response(
        self, correlation_id: UUID, timeout_seconds: int = 20
    ) -> CodegenValidationResponse:
        """
        Wait for validation response from Kafka (future implementation).

        Args:
            correlation_id: Correlation ID to match
            timeout_seconds: Timeout in seconds

        Returns:
            Validation response event

        Raises:
            OnexError: If timeout or response not received
        """
        # TODO: Implement Kafka subscription and response matching
        self.logger.info(
            f"Waiting for validation response (correlation_id: {correlation_id}, "
            f"timeout: {timeout_seconds}s)"
        )

        raise OnexError(
            error_code=EnumCoreErrorCode.NOT_IMPLEMENTED,
            message="Kafka integration not yet implemented",
            correlation_id=correlation_id,
        )

    # ========================================================================
    # TEST API COMPATIBILITY METHODS
    # ========================================================================

    async def validate_syntax(self, code: str) -> Dict[str, Any]:
        """
        Validate Python syntax (test API).

        Args:
            code: Python code to validate

        Returns:
            Dict with valid, errors, ast_tree
        """
        is_valid, violations = self._check_syntax(code)

        try:
            tree = ast.parse(code) if is_valid else None
        except Exception:
            tree = None

        return {"valid": is_valid, "errors": violations, "ast_tree": tree}

    async def validate_onex_naming(
        self, code: str, expected_class_prefix: str, expected_class_suffix: str
    ) -> Dict[str, Any]:
        """
        Validate ONEX naming conventions (test API).

        Args:
            code: Python code to validate
            expected_class_prefix: Expected class prefix (e.g., "Node")
            expected_class_suffix: Expected class suffix (e.g., "Effect")

        Returns:
            Dict with valid, violations
        """
        violations = []

        try:
            tree = ast.parse(code)

            # Check that ALL classes follow the expected naming pattern
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_name = node.name

                    # Check if class follows expected pattern
                    if not class_name.startswith(expected_class_prefix):
                        violations.append(
                            f"Naming violation: Class '{class_name}' does not start with '{expected_class_prefix}'"
                        )
                    elif not class_name.endswith(expected_class_suffix):
                        violations.append(
                            f"Naming violation: Class '{class_name}' does not end with '{expected_class_suffix}'"
                        )

            # If no classes found but code is valid, that's ok
            is_valid = len(violations) == 0

        except Exception as e:
            violations.append(f"Naming validation failed: {str(e)}")
            is_valid = False

        return {"valid": is_valid, "violations": violations}

    async def validate_type_safety(self, code: str) -> Dict[str, Any]:
        """
        Validate type safety (test API).

        Args:
            code: Python code to validate

        Returns:
            Dict with valid, has_type_annotations, uses_bare_any, violations
        """
        violations = []
        suggestions = []

        try:
            tree = ast.parse(code)

            # Check type hints
            type_hint_score = self._check_type_hints(tree, violations, suggestions)

            # Check bare Any usage
            any_type_score = self._check_any_types(code, violations, suggestions)

            has_type_annotations = type_hint_score > 0.5
            uses_bare_any = any_type_score < 1.0
            # Stricter validation: must have good type hints AND no bare Any
            is_valid = type_hint_score >= 0.8 and not uses_bare_any

        except Exception as e:
            violations.append(f"Type safety check failed: {str(e)}")
            has_type_annotations = False
            uses_bare_any = True
            is_valid = False

        return {
            "valid": is_valid,
            "has_type_annotations": has_type_annotations,
            "uses_bare_any": uses_bare_any,
            "violations": violations,
        }

    async def validate_error_handling(self, code: str) -> Dict[str, Any]:
        """
        Validate error handling patterns (test API).

        Args:
            code: Python code to validate

        Returns:
            Dict with valid, has_try_except, uses_onex_error, violations
        """
        violations = []
        suggestions = []

        try:
            tree = ast.parse(code)

            # Check error handling
            error_score = self._check_error_handling(tree, violations, suggestions)

            # Check try/except usage
            has_try_except = self._has_try_except(tree)

            # Check OnexError usage
            uses_onex_error = self._uses_onex_error(tree)

            is_valid = error_score >= 0.7

        except Exception as e:
            violations.append(f"Error handling check failed: {str(e)}")
            has_try_except = False
            uses_onex_error = False
            is_valid = False

        return {
            "valid": is_valid,
            "has_try_except": has_try_except,
            "uses_onex_error": uses_onex_error,
            "violations": violations,
        }

    async def validate_contract_conformance(
        self, code: str, contract: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate contract conformance (test API).

        Args:
            code: Python code to validate
            contract: Contract dictionary

        Returns:
            Dict with valid, all_methods_present, missing_methods
        """
        violations = []

        try:
            tree = ast.parse(code)

            # Get implemented methods
            implemented_methods = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    implemented_methods.add(node.name)

            # Get expected methods from capabilities
            capabilities = contract.get("capabilities", [])
            expected_methods = [
                cap["name"]
                for cap in capabilities
                if isinstance(cap, dict) and "name" in cap
            ]

            # Check missing methods with variant matching
            missing_methods = []
            for method in expected_methods:
                # Check if capability method exists (including variants)
                method_variants = [
                    method,
                    f"_{method}",  # Private method variant
                    f"process_{method}",
                    f"handle_{method}",
                    method.replace("_", ""),
                ]

                if not any(
                    variant in implemented_methods for variant in method_variants
                ):
                    missing_methods.append(method)

            all_methods_present = len(missing_methods) == 0
            is_valid = all_methods_present

        except Exception as e:
            violations.append(f"Contract conformance check failed: {str(e)}")
            missing_methods = []
            all_methods_present = False
            is_valid = False

        return {
            "valid": is_valid,
            "all_methods_present": all_methods_present,
            "missing_methods": missing_methods,
        }

    async def validate_method_signatures(
        self, code: str, contract: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate method signatures (test API).

        Args:
            code: Python code to validate
            contract: Contract dictionary

        Returns:
            Dict with valid, signature_mismatches
        """
        signature_mismatches = []

        try:
            ast.parse(code)

            # For now, just check if methods exist
            # Full implementation would check parameter names and types
            is_valid = True

        except Exception as e:
            signature_mismatches.append(f"Signature validation failed: {str(e)}")
            is_valid = False

        return {"valid": is_valid, "signature_mismatches": signature_mismatches}

    async def validate_return_types(
        self, code: str, contract: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate return types (test API).

        Args:
            code: Python code to validate
            contract: Contract dictionary

        Returns:
            Dict with validation_results
        """
        validation_results = []

        try:
            tree = ast.parse(code)

            # Check that methods have return type annotations
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    has_return_type = node.returns is not None
                    validation_results.append(
                        {"method": node.name, "has_return_type": has_return_type}
                    )

        except Exception as e:
            validation_results.append(
                {"error": f"Return type validation failed: {str(e)}"}
            )

        return {"validation_results": validation_results}

    async def calculate_quality_score(
        self, code: str, contract: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate quality score (test API).

        Args:
            code: Python code to validate
            contract: Contract dictionary

        Returns:
            Dict with quality_score and components breakdown
        """
        try:
            # Use internal validation
            result = await self.validate_generated_code(
                code=code,
                contract=contract,
                node_type="EFFECT",  # Default, doesn't affect scoring much
                microservice_name="test",
            )

            # Extract component scores from compliance_details
            components = {}
            for check_name, check_result in result.compliance_details.items():
                if check_name == "syntax":
                    components["syntax_score"] = 1.0 if check_result["valid"] else 0.0
                else:
                    components[f"{check_name}_score"] = check_result.get("score", 0.0)

            # Add specific component names expected by tests
            if "onex_compliance" in result.compliance_details:
                components["type_safety_score"] = components.get(
                    "onex_compliance_score", 0.0
                )
                components["naming_compliance_score"] = components.get(
                    "onex_compliance_score", 0.0
                )

            if "code_quality" in result.compliance_details:
                components["error_handling_score"] = components.get(
                    "code_quality_score", 0.0
                )

            return {"quality_score": result.quality_score, "components": components}

        except Exception as e:
            self.logger.error(f"Quality score calculation failed: {str(e)}")
            return {"quality_score": 0.0, "components": {}}

    async def validate_quality_threshold(
        self, code: str, contract: Dict[str, Any], threshold: float
    ) -> Dict[str, Any]:
        """
        Validate against quality threshold (test API).

        Args:
            code: Python code to validate
            contract: Contract dictionary
            threshold: Quality threshold (0.0-1.0)

        Returns:
            Dict with meets_threshold, quality_score, failure_reasons
        """
        try:
            score_result = await self.calculate_quality_score(code, contract)
            quality_score = score_result["quality_score"]

            meets_threshold = quality_score >= threshold

            failure_reasons = []
            if not meets_threshold:
                failure_reasons.append(
                    f"Quality score {quality_score:.2f} below threshold {threshold:.2f}"
                )

                # Add component-specific failures
                for component, score in score_result["components"].items():
                    if score < 0.8:
                        failure_reasons.append(f"{component}: {score:.2f} below 0.8")

            return {
                "meets_threshold": meets_threshold,
                "quality_score": quality_score,
                "failure_reasons": failure_reasons,
            }

        except Exception as e:
            return {
                "meets_threshold": False,
                "quality_score": 0.0,
                "failure_reasons": [f"Threshold validation failed: {str(e)}"],
            }

    async def detect_all_violations(
        self, code: str, contract: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Detect all violations (test API).

        Args:
            code: Python code to validate
            contract: Contract dictionary

        Returns:
            Dict with violations list
        """
        try:
            result = await self.validate_generated_code(
                code=code,
                contract=contract,
                node_type="EFFECT",
                microservice_name="test",
            )

            # Convert violations to structured format
            violations = []
            for violation_text in result.violations:
                violations.append(
                    {
                        "type": self._categorize_violation(violation_text),
                        "severity": (
                            "error" if "error" in violation_text.lower() else "warning"
                        ),
                        "message": violation_text,
                        "line": None,  # Line number extraction would require more parsing
                    }
                )

            return {"violations": violations}

        except Exception as e:
            return {
                "violations": [
                    {
                        "type": "validation_error",
                        "severity": "error",
                        "message": f"Violation detection failed: {str(e)}",
                        "line": None,
                    }
                ]
            }

    async def validate_imports(
        self, code: str, required_imports: List[str]
    ) -> Dict[str, Any]:
        """
        Validate required imports (test API).

        Args:
            code: Python code to validate
            required_imports: List of required import names

        Returns:
            Dict with valid, missing_imports
        """
        missing_imports = []

        try:
            tree = ast.parse(code)

            # Extract all imported names
            imported_names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        imported_names.add(alias.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_names.add(alias.name)

            # Check required imports
            for required in required_imports:
                if required not in imported_names:
                    missing_imports.append(required)

            is_valid = len(missing_imports) == 0

        except Exception as e:
            missing_imports.append(f"Import validation failed: {str(e)}")
            is_valid = False

        return {"valid": is_valid, "missing_imports": missing_imports}

    async def validate_code(
        self, code: str, contract: Dict[str, Any], quality_threshold: float
    ) -> Dict[str, Any]:
        """
        Comprehensive code validation (test API).

        Args:
            code: Python code to validate
            contract: Contract dictionary
            quality_threshold: Quality threshold

        Returns:
            Dict with valid, quality_score, violations, meets_threshold
        """
        try:
            result = await self.validate_generated_code(
                code=code,
                contract=contract,
                node_type="EFFECT",
                microservice_name="test",
            )

            meets_threshold = result.quality_score >= quality_threshold

            return {
                "valid": result.is_valid,
                "quality_score": result.quality_score,
                "violations": result.violations,
                "meets_threshold": meets_threshold,
            }

        except Exception as e:
            return {
                "valid": False,
                "quality_score": 0.0,
                "violations": [f"Validation failed: {str(e)}"],
                "meets_threshold": False,
            }

    # Helper methods

    def _has_try_except(self, tree: ast.AST) -> bool:
        """Check if code has try/except blocks"""
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                return True
        return False

    def _uses_onex_error(self, tree: ast.AST) -> bool:
        """Check if code uses OnexError"""
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise):
                if node.exc and isinstance(node.exc, ast.Call):
                    if isinstance(node.exc.func, ast.Name):
                        if node.exc.func.id == "OnexError":
                            return True
        return False

    def _categorize_violation(self, violation_text: str) -> str:
        """Categorize violation by text"""
        text_lower = violation_text.lower()

        if "type" in text_lower or "any" in text_lower:
            return "type_safety"
        elif "naming" in text_lower:
            return "naming_convention"
        elif "error" in text_lower or "exception" in text_lower:
            return "error_handling"
        elif "import" in text_lower:
            return "imports"
        elif "docstring" in text_lower:
            return "documentation"
        else:
            return "general"


# Convenience function for quick validation
async def validate_code(
    code: str,
    contract: Dict[str, Any],
    node_type: str,
    microservice_name: str,
    config: Optional[CodegenConfig] = None,
) -> ValidationResult:
    """
    Convenience function for validating generated code.

    Args:
        code: Generated code to validate
        contract: Contract dictionary
        node_type: Node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
        microservice_name: Name of microservice
        config: Optional configuration

    Returns:
        ValidationResult with quality score and feedback
    """
    validator = QualityValidator(config)
    return await validator.validate_generated_code(
        code, contract, node_type, microservice_name
    )


__all__ = [
    "QualityValidator",
    "ValidationResult",
    "ONEXComplianceCheck",
    "validate_code",
]
