#!/usr/bin/env python3
"""
Framework Validation Quality Gates - FV-001 to FV-002

Validates agent lifecycle management and framework integration
for the ONEX Agent Framework.

ONEX v2.0 Compliance:
- Lifecycle method presence and execution
- Resource management validation
- Framework imports and patterns
- Template @include usage
- Performance targets: FV-001 (35ms), FV-002 (25ms)

Quality Gates:
- FV-001: Lifecycle Compliance - Validates agent lifecycle management
- FV-002: Framework Integration - Validates framework integration and patterns
"""

import inspect
from typing import Any

from ..models.model_quality_gate import EnumQualityGate, ModelQualityGateResult
from .base_quality_gate import BaseQualityGate


class LifecycleComplianceValidator(BaseQualityGate):
    """
    FV-001: Lifecycle Compliance Validator

    Validates agent lifecycle management compliance at initialization and cleanup.

    Validation Checks:
    - Lifecycle methods present (__init__, startup/initialize, shutdown/cleanup)
    - Initialization successful
    - Cleanup performed in finally blocks
    - Resources properly managed (connections, files, etc.)
    - No resource leaks detected

    Performance Target: 35ms
    Execution Point: initialization_and_cleanup
    Validation Type: blocking
    Dependencies: None

    Lifecycle Pattern:
    ```python
    class NodeXxxEffect:
        def __init__(self, container: ModelContainer):
            # Dependency injection pattern
            pass

        async def startup(self) -> None:
            # Initialize resources
            pass

        async def shutdown(self) -> None:
            # Clean up resources
            pass
    ```

    Example:
        validator = LifecycleComplianceValidator()
        result = await validator.validate({
            "agent_class": NodeDatabaseWriterEffect,
            "initialization_result": {"success": True},
            "cleanup_result": {"success": True, "resources_released": 3}
        })
    """

    # Required lifecycle methods
    REQUIRED_INIT_METHODS = ["__init__"]
    STARTUP_METHODS = ["startup", "initialize", "start"]
    CLEANUP_METHODS = ["shutdown", "cleanup", "close"]

    def __init__(self) -> None:
        """Initialize FV-001 validator."""
        super().__init__(EnumQualityGate.LIFECYCLE_COMPLIANCE)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Validate lifecycle management compliance.

        Args:
            context: Must contain:
                - agent_class: Class to validate (or)
                - agent_instance: Instance to validate
                - Optional: initialization_result: Init result
                - Optional: cleanup_result: Cleanup result

        Returns:
            ModelQualityGateResult with validation outcome
        """
        issues: list[str] = []
        warnings: list[str] = []
        metadata: dict[str, Any] = {}

        # Get agent class or instance
        agent_class = context.get("agent_class")
        agent_instance = context.get("agent_instance")

        if not agent_class and not agent_instance:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="No agent_class or agent_instance provided",
                metadata={"error": "missing_agent"},
            )

        # Get class from instance if needed
        if agent_instance and not agent_class:
            agent_class = type(agent_instance)

        metadata["agent_class"] = agent_class.__name__

        # Check required __init__ method
        if not hasattr(agent_class, "__init__"):
            issues.append("Missing __init__ method")
        else:
            metadata["has_init"] = True

            # Check __init__ signature for dependency injection
            init_sig = inspect.signature(agent_class.__init__)
            params = list(init_sig.parameters.keys())

            # Should have self + at least one dependency parameter
            if len(params) < 2:
                warnings.append(
                    "__init__ has no dependency parameters (expected container/dependencies)"
                )
            else:
                metadata["init_params"] = params[1:]  # Exclude 'self'

        # Check startup/initialization methods
        startup_methods = [
            method for method in self.STARTUP_METHODS if hasattr(agent_class, method)
        ]

        if not startup_methods:
            warnings.append(
                f"No startup method found (expected one of: {', '.join(self.STARTUP_METHODS)})"
            )
        else:
            metadata["startup_methods"] = startup_methods

            # Check if startup method is async
            startup_method = getattr(agent_class, startup_methods[0])
            if not inspect.iscoroutinefunction(startup_method):
                warnings.append(
                    f"{startup_methods[0]} method should be async for ONEX compliance"
                )

        # Check cleanup/shutdown methods
        cleanup_methods = [
            method for method in self.CLEANUP_METHODS if hasattr(agent_class, method)
        ]

        if not cleanup_methods:
            warnings.append(
                f"No cleanup method found (expected one of: {', '.join(self.CLEANUP_METHODS)})"
            )
        else:
            metadata["cleanup_methods"] = cleanup_methods

            # Check if cleanup method is async
            cleanup_method = getattr(agent_class, cleanup_methods[0])
            if not inspect.iscoroutinefunction(cleanup_method):
                warnings.append(
                    f"{cleanup_methods[0]} method should be async for ONEX compliance"
                )

        # Check initialization result if provided
        init_result = context.get("initialization_result")
        if init_result:
            metadata["initialization_attempted"] = True

            if not init_result.get("success", False):
                issues.append(
                    f"Initialization failed: {init_result.get('error', 'unknown')}"
                )
            else:
                metadata["initialization_success"] = True

                # Check for resource acquisition
                if "resources_acquired" in init_result:
                    metadata["resources_acquired"] = init_result["resources_acquired"]

        # Check cleanup result if provided
        cleanup_result = context.get("cleanup_result")
        if cleanup_result:
            metadata["cleanup_attempted"] = True

            if not cleanup_result.get("success", False):
                issues.append(
                    f"Cleanup failed: {cleanup_result.get('error', 'unknown')}"
                )
            else:
                metadata["cleanup_success"] = True

                # Check for resource release
                if "resources_released" in cleanup_result:
                    metadata["resources_released"] = cleanup_result[
                        "resources_released"
                    ]

                # Check for resource leaks
                if "resource_leaks" in cleanup_result:
                    leaks = cleanup_result["resource_leaks"]
                    if leaks > 0:
                        issues.append(f"Resource leaks detected: {leaks} unreleased")

        # Check if cleanup is in finally block (source code inspection)
        cleanup_in_finally = context.get("cleanup_in_finally", True)
        if not cleanup_in_finally:
            warnings.append("Cleanup should be performed in finally blocks")

        metadata["cleanup_in_finally"] = cleanup_in_finally

        # Determine validation status
        if issues:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Lifecycle compliance failed: {'; '.join(issues)}",
                metadata={
                    **metadata,
                    "issues": issues,
                    "warnings": warnings,
                },
            )

        # Build success message
        message_parts = ["Lifecycle compliance validated"]

        if startup_methods:
            message_parts.append(f"startup={startup_methods[0]}")

        if cleanup_methods:
            message_parts.append(f"cleanup={cleanup_methods[0]}")

        if warnings:
            message_parts.append(f"({len(warnings)} warnings)")

        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,
            message="; ".join(message_parts),
            metadata={
                **metadata,
                "warnings": warnings,
                "validation_complete": True,
            },
        )


class FrameworkIntegrationValidator(BaseQualityGate):
    """
    FV-002: Framework Integration Validator

    Validates proper framework integration and @include template usage at initialization.

    Validation Checks:
    - Framework imports present (omnibase_core, llama_index, etc.)
    - Templates use @include for reusability
    - Framework patterns followed (dependency injection, events, ONEX node types)
    - Integration points implemented (contract YAML, event publishing, health checks)
    - No framework violations

    Performance Target: 25ms
    Execution Point: initialization
    Validation Type: blocking
    Dependencies: None

    Framework Patterns:
    - Dependency injection via ModelContainer
    - Event-driven architecture via EventPublisher
    - ONEX node types (Effect/Compute/Reducer/Orchestrator)
    - Contract YAML definitions
    - Health check endpoints

    Example:
        validator = FrameworkIntegrationValidator()
        result = await validator.validate({
            "module": my_module,
            "imports": ["omnibase_core", "llama_index"],
            "patterns_used": ["dependency_injection", "event_publishing"],
            "integration_points": {
                "contract_yaml": True,
                "event_publisher": True,
                "health_check": True
            }
        })
    """

    # Required framework imports
    CORE_FRAMEWORK_IMPORTS = {
        "omnibase_core",
        "llama_index",
        "pydantic",
    }

    # Common framework patterns
    FRAMEWORK_PATTERNS = {
        "dependency_injection": ["ModelContainer", "Container"],
        "event_publishing": ["EventPublisher", "publish_event", "emit"],
        "onex_node_types": [
            "NodeEffect",
            "NodeCompute",
            "NodeReducer",
            "NodeOrchestrator",
        ],
        "contract_definitions": ["ModelContract", "contract.yaml"],
        "health_checks": ["health_check", "healthcheck", "/health"],
    }

    # ONEX node naming patterns
    ONEX_NODE_SUFFIXES = ["Effect", "Compute", "Reducer", "Orchestrator"]

    def __init__(self) -> None:
        """Initialize FV-002 validator."""
        super().__init__(EnumQualityGate.FRAMEWORK_INTEGRATION)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Validate framework integration compliance.

        Args:
            context: Must contain:
                - module: Python module to validate (or)
                - imports: List of imports
                - Optional: patterns_used: List of patterns
                - Optional: integration_points: Dict of integration checks
                - Optional: source_code: Source code for template checks

        Returns:
            ModelQualityGateResult with validation outcome
        """
        issues: list[str] = []
        warnings: list[str] = []
        metadata: dict[str, Any] = {}

        # Get imports from module or directly from context
        imports = context.get("imports", [])
        module = context.get("module")

        if module and not imports:
            # Extract imports from module
            imports = self._extract_imports_from_module(module)

        if not imports:
            warnings.append("No imports provided for validation")
        else:
            metadata["imports_count"] = len(imports)

            # Check for core framework imports
            missing_core = self.CORE_FRAMEWORK_IMPORTS - set(imports)
            if missing_core:
                warnings.append(
                    f"Missing recommended framework imports: {', '.join(missing_core)}"
                )

            metadata["framework_imports"] = [
                imp for imp in imports if imp in self.CORE_FRAMEWORK_IMPORTS
            ]

        # Check patterns used
        patterns_used = context.get("patterns_used", [])
        if patterns_used:
            metadata["patterns_used"] = patterns_used
        else:
            warnings.append("No framework patterns specified")

        # Validate ONEX node type compliance if class provided
        agent_class = context.get("agent_class")
        if agent_class:
            class_name = agent_class.__name__

            # Check if class name follows ONEX naming
            if class_name.startswith("Node"):
                # Check suffix
                has_valid_suffix = any(
                    class_name.endswith(suffix) for suffix in self.ONEX_NODE_SUFFIXES
                )

                if not has_valid_suffix:
                    issues.append(
                        f"ONEX node class '{class_name}' must end with one of: "
                        f"{', '.join(self.ONEX_NODE_SUFFIXES)}"
                    )
                else:
                    # Determine node type
                    node_type = next(
                        (
                            suffix
                            for suffix in self.ONEX_NODE_SUFFIXES
                            if class_name.endswith(suffix)
                        ),
                        None,
                    )
                    metadata["onex_node_type"] = node_type
            else:
                warnings.append(
                    f"Class '{class_name}' doesn't follow ONEX naming (should start with 'Node')"
                )

        # Check integration points
        integration_points = context.get("integration_points", {})
        if integration_points:
            metadata["integration_points"] = integration_points

            # Check required integration points
            required_integrations = ["contract_yaml", "event_publisher"]

            for integration in required_integrations:
                if integration not in integration_points:
                    warnings.append(f"Missing integration point: {integration}")
                elif not integration_points[integration]:
                    warnings.append(f"Integration point not implemented: {integration}")

        # Check for @include template usage in source code
        source_code = context.get("source_code")
        if source_code:
            include_count = source_code.count("@include")
            metadata["include_directives"] = include_count

            if include_count == 0:
                warnings.append(
                    "No @include directives found (templates should use @include for reusability)"
                )

            # Check for common template patterns
            template_patterns = [
                "@MANDATORY_FUNCTIONS.md",
                "@COMMON_TEMPLATES.md",
                "@COMMON_AGENT_PATTERNS.md",
            ]

            found_templates = [
                pattern for pattern in template_patterns if pattern in source_code
            ]

            metadata["templates_used"] = found_templates  # Always set, even if empty
        else:
            warnings.append("No source code provided for template validation")

        # Check dependency injection pattern
        if agent_class:
            init_method = getattr(agent_class, "__init__", None)
            if init_method:
                sig = inspect.signature(init_method)
                params = list(sig.parameters.keys())

                # Check for container-like parameter
                has_container = any("container" in param.lower() for param in params)

                if has_container:
                    metadata["dependency_injection"] = True
                else:
                    warnings.append(
                        "No container parameter in __init__ (dependency injection pattern)"
                    )

        # Check event publishing capability
        has_event_publisher = False
        if agent_class:
            # Check for event publisher attributes or methods
            for attr in dir(agent_class):
                if any(
                    keyword in attr.lower() for keyword in ["event", "publish", "emit"]
                ):
                    has_event_publisher = True
                    break

        if has_event_publisher:
            metadata["event_publishing"] = True
        else:
            warnings.append("No event publishing capability detected")

        # Determine validation status
        if issues:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Framework integration validation failed: {'; '.join(issues)}",
                metadata={
                    **metadata,
                    "issues": issues,
                    "warnings": warnings,
                },
            )

        # Build success message
        message_parts = ["Framework integration validated"]

        if metadata.get("onex_node_type"):
            message_parts.append(f"type={metadata['onex_node_type']}")

        if metadata.get("imports_count"):
            message_parts.append(f"{metadata['imports_count']} imports")

        if warnings:
            message_parts.append(f"({len(warnings)} warnings)")

        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,
            message="; ".join(message_parts),
            metadata={
                **metadata,
                "warnings": warnings,
                "validation_complete": True,
            },
        )

    def _extract_imports_from_module(self, module: Any) -> list[str]:
        """
        Extract import names from a module.

        Args:
            module: Python module object

        Returns:
            List of imported module names
        """
        imports: list[str] = []

        # Get module attributes
        for attr_name in dir(module):
            attr = getattr(module, attr_name, None)

            # Check if it's a module
            if inspect.ismodule(attr):
                # Get module name (base name without submodules)
                module_name = attr.__name__.split(".")[0]
                if module_name not in imports:
                    imports.append(module_name)

        return imports
