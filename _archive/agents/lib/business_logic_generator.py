#!/usr/bin/env python3
"""
Business Logic Generator for Phase 5

Generates node implementation stubs from contracts with comprehensive
docstrings, type hints, error handling, and ONEX compliance.
"""

import ast
import logging
import re
from pathlib import Path
from typing import Any

# Import from omnibase_core
from omnibase_core.errors import EnumCoreErrorCode, OnexError

from .simple_prd_analyzer import PRDAnalysisResult
from .version_config import get_config

logger = logging.getLogger(__name__)


class CodegenConfig:
    """Configuration for business logic generation"""

    def __init__(self):
        self.config = get_config()
        self.generate_pattern_hooks = True
        self.include_correlation_tracking = True
        self.strict_type_hints = True
        self.comprehensive_docstrings = True
        self.onex_compliance_mode = True


class BusinessLogicGenerator:
    """
    Generate node implementation stubs from contracts.

    Supports all 4 ONEX node types (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
    with comprehensive method stubs, validation, health checks, and error handling.
    """

    def __init__(self, config: CodegenConfig | None = None):
        self.config = config or CodegenConfig()
        self.logger = logging.getLogger(__name__)

        # Node type to base class mapping
        self.node_base_classes = {
            "EFFECT": "NodeEffect",
            "COMPUTE": "NodeCompute",
            "REDUCER": "NodeReducer",
            "ORCHESTRATOR": "NodeOrchestrator",
        }

        # Node type to primary method mapping
        self.node_primary_methods = {
            "EFFECT": "execute_effect",
            "COMPUTE": "execute_compute",
            "REDUCER": "execute_reduction",
            "ORCHESTRATOR": "execute_orchestration",
        }

        # Mixin method templates
        self.mixin_methods = {
            "MixinEventBus": ["publish_event", "subscribe_to_topic", "handle_event"],
            "MixinCaching": [
                "cache_get",
                "cache_set",
                "cache_invalidate",
                "cache_clear",
            ],
            "MixinHealthCheck": ["get_health_status", "register_health_check"],
            "MixinRetry": ["retry_operation", "configure_retry_policy"],
            "MixinCircuitBreaker": [
                "circuit_check",
                "circuit_open",
                "circuit_close",
                "circuit_reset",
            ],
            "MixinLogging": ["log_debug", "log_info", "log_warning", "log_error"],
            "MixinMetrics": ["record_metric", "increment_counter", "record_histogram"],
            "MixinSecurity": ["authenticate", "authorize", "validate_token"],
            "MixinValidation": ["validate_input", "validate_output", "validate_schema"],
        }

    async def generate_node_implementation(
        self,
        contract: dict[str, Any],
        analysis_result: PRDAnalysisResult,
        node_type: str,
        microservice_name: str,
        domain: str,
    ) -> str:
        """
        Generate complete node implementation from contract.

        Args:
            contract: Contract dictionary from contract generator
            analysis_result: PRD analysis result
            node_type: Type of node (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
            microservice_name: Name of the microservice
            domain: Domain of the microservice

        Returns:
            Complete Python implementation as string

        Raises:
            OnexError: If generation fails or invalid node type
        """
        try:
            self.logger.info(
                f"Generating business logic for {node_type} node: {microservice_name}"
            )

            # Validate node type
            if node_type not in self.node_base_classes:
                raise OnexError(
                    code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message=f"Invalid node type: {node_type}",
                    details={"valid_types": list(self.node_base_classes.keys())},
                )

            # Generate class definition
            class_def = self._generate_class_definition(
                contract, analysis_result, node_type, microservice_name, domain
            )

            # Generate __init__ method
            init_method = self._generate_init_method(
                contract, analysis_result, node_type, microservice_name
            )

            # Generate primary processing method
            primary_method = self._generate_primary_method(
                contract, analysis_result, node_type, microservice_name
            )

            # Generate validation method
            validation_method = self._generate_validation_method(
                contract, node_type, microservice_name
            )

            # Generate health check
            health_check = self._generate_health_check(microservice_name, node_type)

            # Generate mixin methods
            mixin_methods = self._generate_mixin_methods(contract, microservice_name)

            # Generate capability methods
            capability_methods = self._generate_capability_methods(
                contract, analysis_result, node_type, microservice_name
            )

            # Combine all parts
            implementation = self._combine_implementation_parts(
                class_def,
                init_method,
                primary_method,
                validation_method,
                health_check,
                mixin_methods,
                capability_methods,
                contract,
                analysis_result,
                node_type,
                microservice_name,
                domain,
            )

            self.logger.info(
                f"Business logic generation completed for {microservice_name}"
            )
            return implementation

        except Exception as e:
            self.logger.error(f"Business logic generation failed: {str(e)}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Business logic generation failed: {str(e)}",
                details={
                    "node_type": node_type,
                    "microservice_name": microservice_name,
                    "domain": domain,
                },
            )

    def _generate_class_definition(
        self,
        contract: dict[str, Any],
        analysis_result: PRDAnalysisResult,
        node_type: str,
        microservice_name: str,
        domain: str,
    ) -> str:
        """Generate class definition with imports and inheritance"""

        pascal_name = self._to_pascal_case(microservice_name)
        base_class = self.node_base_classes[node_type]

        # Generate imports
        imports = self._generate_imports(contract, node_type)

        # Generate inheritance chain
        mixins = self._extract_mixins_from_contract(contract)
        inheritance = [base_class]
        if mixins:
            inheritance.extend(mixins)
        inheritance_str = ", ".join(inheritance)

        # Extract description
        description = contract.get(
            "description", analysis_result.parsed_prd.description
        )

        class_def = f'''#!/usr/bin/env python3
"""
{pascal_name} {node_type} Node Implementation

Generated from PRD: {analysis_result.parsed_prd.title}

{description}

Node Type: {node_type}
Domain: {domain}
Version: {contract.get("version", "1.0.0")}
"""

{imports}

logger = logging.getLogger(__name__)


class Node{pascal_name}{node_type.capitalize()}({inheritance_str}):
    """
    {pascal_name} {node_type} Node

    {description}

    ONEX Compliance:
        - Node Type: {node_type}
        - Naming: Node{pascal_name}{node_type.capitalize()}
        - Strong typing with specific type annotations
        - Comprehensive error handling with OnexError
        - Correlation ID tracking for all operations

    Capabilities:
{self._format_capabilities_docstring(contract)}

    External Dependencies:
{self._format_dependencies_docstring(contract)}

    Quality Baseline: {analysis_result.quality_baseline:.1%}
    Confidence Score: {analysis_result.confidence_score:.1%}
    """
'''

        return class_def

    def _generate_imports(self, contract: dict[str, Any], node_type: str) -> str:
        """Generate import statements"""

        imports = [
            "import asyncio",
            "import logging",
            "from typing import Dict, Optional, List, Any",
            "from uuid import UUID, uuid4",
            "from datetime import datetime, timezone",
            "",
            "# Core imports",
            f"from omnibase_core.nodes.node_{node_type.lower()} import {self.node_base_classes[node_type]}",
            "from omnibase_core.errors.error_codes import EnumCoreErrorCode",
            "from omnibase_core.errors import OnexError",
            "",
        ]

        # Add mixin imports
        mixins = self._extract_mixins_from_contract(contract)
        if mixins:
            imports.append("# Mixin imports")
            for mixin in mixins:
                imports.append(
                    f"from omnibase_core.mixins.{mixin.lower()} import {mixin}"
                )
            imports.append("")

        # Add local imports (these will be generated separately)
        imports.extend(
            [
                "# Local imports (to be generated)",
                "# from .models.model_<name>_input import Model<Name>Input",
                "# from .models.model_<name>_output import Model<Name>Output",
                "# from .models.model_<name>_config import Model<Name>Config",
                "# from .enums.enum_<name>_operation_type import Enum<Name>OperationType",
                "",
            ]
        )

        return "\n".join(imports)

    def _generate_init_method(
        self,
        contract: dict[str, Any],
        analysis_result: PRDAnalysisResult,
        node_type: str,
        microservice_name: str,
    ) -> str:
        """Generate __init__ method with mixin initialization"""

        pascal_name = self._to_pascal_case(microservice_name)
        mixins = self._extract_mixins_from_contract(contract)

        init_method = f'''
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize {pascal_name} {node_type} service.

        Args:
            config: Optional configuration dictionary

        Raises:
            OnexError: If initialization fails
        """
        try:
            super().__init__()
            self.config = config or {{}}
            self.logger = logging.getLogger(__name__)

            # Initialize correlation tracking
            self._active_operations: Dict[UUID, Dict[str, Any]] = {{}}

            # Initialize metrics
            self._operation_count = 0
            self._error_count = 0
            self._start_time = datetime.now(timezone.utc)
'''

        # Add mixin initialization
        if mixins:
            init_method += "\n            # Initialize mixins\n"
            for mixin in mixins:
                init_method += f"            self._init_{mixin.lower()}()\n"

        init_method += """
            self.logger.info(f"Initialized {node_type} service: {microservice_name}")

        except Exception as e:
            self.logger.error(f"Initialization failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.INITIALIZATION_ERROR,
                message=f"Failed to initialize {microservice_name}: {{str(e)}}",
                details={{"config": self.config}}
            )
"""

        return init_method

    def _generate_primary_method(
        self,
        contract: dict[str, Any],
        analysis_result: PRDAnalysisResult,
        node_type: str,
        microservice_name: str,
    ) -> str:
        """Generate primary processing method for node type"""

        pascal_name = self._to_pascal_case(microservice_name)
        method_name = self.node_primary_methods[node_type]

        # Infer logic hints from contract
        logic_hints = self._infer_method_logic_hints(
            contract, analysis_result, node_type
        )

        method = f'''
    async def {method_name}(
        self,
        input_data: Dict[str, Any],
        correlation_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        Execute {node_type.lower()} operation for {microservice_name}.

        This method performs the core {node_type.lower()} logic with comprehensive
        error handling, validation, and correlation tracking.

        Args:
            input_data: Input data for the operation
            correlation_id: Optional correlation ID for request tracing

        Returns:
            Dict[str, Any]: Operation result with metadata

        Raises:
            OnexError: If operation fails

        Example:
            >>> service = Node{pascal_name}{node_type.capitalize()}Service()
            >>> result = await service.{method_name}(
            ...     {{"operation": "process", "data": {{}}}},
            ...     correlation_id=uuid4()
            ... )
        """
        # Generate correlation ID if not provided
        if correlation_id is None:
            correlation_id = uuid4()

        # Track operation start
        operation_context = {{
            "correlation_id": correlation_id,
            "operation": "{method_name}",
            "start_time": datetime.now(timezone.utc),
            "input_data": input_data
        }}
        self._active_operations[correlation_id] = operation_context

        try:
            self.logger.info(
                f"Starting {{operation_context['operation']}} with correlation_id={{correlation_id}}"
            )

            # Validate input
            await self._validate_input(input_data, correlation_id)

            # Execute operation
            result = await self._execute_operation(input_data, correlation_id)

            # Update metrics
            self._operation_count += 1

            # Track operation completion
            operation_context["end_time"] = datetime.now(timezone.utc)
            operation_context["status"] = "success"

            self.logger.info(
                f"Completed {{operation_context['operation']}} with correlation_id={{correlation_id}}"
            )

            return {{
                "success": True,
                "correlation_id": str(correlation_id),
                "result": result,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": {{
                    "operation_count": self._operation_count,
                    "node_type": "{node_type}"
                }}
            }}

        except OnexError:
            # Re-raise ONEX errors with correlation context
            self._error_count += 1
            operation_context["status"] = "failed"
            raise

        except Exception as e:
            # Wrap unexpected errors
            self._error_count += 1
            operation_context["status"] = "failed"
            self.logger.error(
                f"Operation failed with correlation_id={{correlation_id}}: {{str(e)}}"
            )
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"{method_name} failed: {{str(e)}}",
                details={{
                    "correlation_id": str(correlation_id),
                    "input_data": input_data,
                    "error_type": type(e).__name__
                }}
            ) from e

        finally:
            # Cleanup operation tracking
            if correlation_id in self._active_operations:
                del self._active_operations[correlation_id]

    async def _execute_operation(
        self,
        input_data: Dict[str, Any],
        correlation_id: UUID
    ) -> Dict[str, Any]:
        """
        Execute the core {node_type.lower()} operation.

        Args:
            input_data: Validated input data
            correlation_id: Correlation ID for tracing

        Returns:
            Dict[str, Any]: Operation result

        Raises:
            OnexError: If operation fails
        """
        self.logger.debug(f"Executing operation with correlation_id={{correlation_id}}")

        # TODO: Implement {node_type.lower()} logic
{logic_hints}

        # Placeholder result
        result = {{
            "status": "completed",
            "correlation_id": str(correlation_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {{}}
        }}

        return result
'''

        return method

    def _generate_validation_method(
        self, contract: dict[str, Any], node_type: str, microservice_name: str
    ) -> str:
        """Generate input validation method"""

        capabilities = contract.get("capabilities", [])

        validation_checks = []
        for capability in capabilities:
            if isinstance(capability, dict):
                cap_name = capability.get("name", "")
                if capability.get("required", False):
                    validation_checks.append(f"            # Validate {cap_name}")

        validation_code = (
            "\n".join(validation_checks)
            if validation_checks
            else "            # Add validation logic here"
        )

        method = f'''
    async def _validate_input(
        self,
        input_data: Dict[str, Any],
        correlation_id: UUID
    ) -> None:
        """
        Validate input data before processing.

        Args:
            input_data: Input data to validate
            correlation_id: Correlation ID for tracing

        Raises:
            OnexError: If validation fails
        """
        self.logger.debug(f"Validating input with correlation_id={{correlation_id}}")

        # Check required fields
        if not input_data:
            raise OnexError(
                code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="Input data cannot be empty",
                details={{"correlation_id": str(correlation_id)}}
            )

{validation_code}

        self.logger.debug(f"Input validation passed for correlation_id={{correlation_id}}")
'''

        return method

    def _generate_health_check(self, microservice_name: str, node_type: str) -> str:
        """Generate health check method"""

        method = f'''
    async def get_health_status(self) -> Dict[str, Any]:
        """
        Get health status of the service.

        Returns:
            Dict[str, Any]: Health status with metrics
        """
        uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds()

        return {{
            "service": "{microservice_name}",
            "node_type": "{node_type}",
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "1.0.0",
            "metrics": {{
                "uptime_seconds": uptime,
                "operation_count": self._operation_count,
                "error_count": self._error_count,
                "active_operations": len(self._active_operations),
                "error_rate": self._error_count / max(self._operation_count, 1)
            }}
        }}
'''

        return method

    def _generate_mixin_methods(
        self, contract: dict[str, Any], microservice_name: str
    ) -> list[str]:
        """Generate mixin-specific method stubs"""

        mixins = self._extract_mixins_from_contract(contract)
        methods = []

        for mixin in mixins:
            if mixin in self.mixin_methods:
                for method_name in self.mixin_methods[mixin]:
                    stub = self._generate_mixin_method_stub(
                        mixin, method_name, microservice_name
                    )
                    methods.append(stub)

        return methods

    def _generate_mixin_method_stub(
        self, mixin: str, method_name: str, microservice_name: str
    ) -> str:
        """Generate stub for a specific mixin method"""

        stub = f'''
    async def {method_name}(self, **kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """
        {mixin} - {method_name}

        TODO: Implement {method_name} for {mixin}

        Args:
            **kwargs: Keyword arguments for the operation

        Returns:
            Dict[str, Any]: Method result

        Raises:
            OnexError: If operation fails
        """
        self.logger.warning(f"{{'{method_name}'}} not implemented for {{'{mixin}'}}")
        raise OnexError(
            code=EnumCoreErrorCode.NOT_IMPLEMENTED,
            message=f"Method {{'{method_name}'}} not implemented",
            details={{"mixin": "{mixin}", "service": "{microservice_name}"}}
        )
'''

        return stub

    def _generate_capability_methods(
        self,
        contract: dict[str, Any],
        analysis_result: PRDAnalysisResult,
        node_type: str,
        microservice_name: str,
    ) -> list[str]:
        """Generate methods for each capability in contract"""

        capabilities = contract.get("capabilities", [])
        methods = []

        for capability in capabilities:
            if not isinstance(capability, dict):
                continue

            cap_name = capability.get("name", "")
            cap_type = capability.get("type", "")
            cap_desc = capability.get("description", "")

            # Skip system capabilities (generated elsewhere)
            if cap_type == "system":
                continue

            # Detect CRUD pattern
            pattern_type = self._detect_pattern_type(cap_name, cap_type)

            method = self._generate_capability_method(
                cap_name, cap_desc, cap_type, pattern_type, microservice_name, node_type
            )
            methods.append(method)

        return methods

    def _generate_capability_method(
        self,
        capability_name: str,
        capability_desc: str,
        capability_type: str,
        pattern_type: str | None,
        microservice_name: str,
        node_type: str,
    ) -> str:
        """Generate a single capability method"""

        method_name = self._sanitize_method_name(capability_name)

        # Add pattern hook comment if applicable
        pattern_hook = ""
        if pattern_type and self.config.generate_pattern_hooks:
            pattern_hook = f"\n        # PATTERN_HOOK: {pattern_type} - This method is eligible for pattern-based generation\n"

        method = f'''
    async def {method_name}(
        self,
        data: Dict[str, Any],
        correlation_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        {capability_desc}

        Capability: {capability_name}
        Type: {capability_type}
        {f"Pattern: {pattern_type}" if pattern_type else ""}

        Args:
            data: Input data for the operation
            correlation_id: Optional correlation ID for tracing

        Returns:
            Dict[str, Any]: Operation result

        Raises:
            OnexError: If operation fails
        """
        if correlation_id is None:
            correlation_id = uuid4()
        {pattern_hook}
        self.logger.info(f"Executing {{'{method_name}'}} with correlation_id={{correlation_id}}")

        try:
            # TODO: Implement {capability_name} logic
            # Capability type: {capability_type}

            result = {{
                "capability": "{capability_name}",
                "status": "success",
                "correlation_id": str(correlation_id),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }}

            return result

        except Exception as e:
            self.logger.error(f"{{'{method_name}'}} failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"{capability_name} failed: {{str(e)}}",
                details={{
                    "correlation_id": str(correlation_id),
                    "capability": "{capability_name}",
                    "data": data
                }}
            ) from e
'''

        return method

    def _detect_pattern_type(
        self, capability_name: str, capability_type: str
    ) -> str | None:
        """
        Detect if capability follows a known pattern (CRUD, etc.)

        Framework: Enhanced with feedback learning integration.
        Pattern detection results can be recorded for continuous improvement.
        """

        name_lower = capability_name.lower()
        type_lower = capability_type.lower()

        # CRUD pattern detection
        if (
            any(keyword in name_lower for keyword in ["create", "insert", "add"])
            or type_lower == "create"
        ):
            return "CRUD_CREATE"
        elif (
            any(
                keyword in name_lower
                for keyword in ["read", "get", "fetch", "retrieve", "list"]
            )
            or type_lower == "read"
        ):
            return "CRUD_READ"
        elif (
            any(
                keyword in name_lower
                for keyword in ["update", "modify", "edit", "change"]
            )
            or type_lower == "update"
        ):
            return "CRUD_UPDATE"
        elif (
            any(keyword in name_lower for keyword in ["delete", "remove", "destroy"])
            or type_lower == "delete"
        ):
            return "CRUD_DELETE"

        # Other patterns
        elif any(
            keyword in name_lower for keyword in ["aggregate", "summarize", "reduce"]
        ):
            return "AGGREGATION"
        elif any(keyword in name_lower for keyword in ["transform", "convert", "map"]):
            return "TRANSFORMATION"
        elif any(keyword in name_lower for keyword in ["validate", "check", "verify"]):
            return "VALIDATION"

        return None

    def record_pattern_detection(
        self,
        session_id: str,
        capability_name: str,
        detected_pattern: str,
        confidence: float,
        actual_pattern: str | None = None,
        feedback_type: str = "automated",
    ) -> None:
        """
        Record pattern detection for feedback learning.

        This method allows recording pattern matches for later analysis
        and continuous improvement of pattern matching precision.

        Args:
            session_id: Generation session ID
            capability_name: Name of capability being analyzed
            detected_pattern: Pattern that was detected
            confidence: Confidence score of detection
            actual_pattern: Actual pattern (if known, for validation)
            feedback_type: Type of feedback (automated, manual, validation)

        Note: This is a placeholder for framework feedback integration.
        Implementation requires PatternFeedbackCollector integration.
        """
        # TODO: Integrate with PatternFeedbackCollector
        # For now, just log the detection
        self.logger.debug(
            f"Pattern detection: {capability_name} -> {detected_pattern} "
            f"(confidence={confidence:.2f}, feedback={feedback_type})"
        )

    def _infer_method_logic_hints(
        self,
        contract: dict[str, Any],
        analysis_result: PRDAnalysisResult,
        node_type: str,
    ) -> str:
        """Generate TODO comments with implementation guidance"""

        hints = []

        # Add hints based on node type
        if node_type == "EFFECT":
            hints.append("        # EFFECT Node: Implement external I/O operations")
            hints.append("        # - Database writes/reads")
            hints.append("        # - API calls")
            hints.append("        # - File system operations")
        elif node_type == "COMPUTE":
            hints.append("        # COMPUTE Node: Implement pure transformation logic")
            hints.append("        # - Data transformations")
            hints.append("        # - Calculations")
            hints.append("        # - Algorithm implementations")
        elif node_type == "REDUCER":
            hints.append(
                "        # REDUCER Node: Implement aggregation/reduction logic"
            )
            hints.append("        # - Data aggregation")
            hints.append("        # - State persistence")
            hints.append("        # - Summary computations")
        elif node_type == "ORCHESTRATOR":
            hints.append("        # ORCHESTRATOR Node: Implement workflow coordination")
            hints.append("        # - Task delegation")
            hints.append("        # - Workflow state management")
            hints.append("        # - Error compensation")

        # Add hints from requirements
        hints.append("        #")
        hints.append("        # Based on requirements:")
        for req in analysis_result.parsed_prd.functional_requirements[:3]:
            hints.append(f"        # - {req}")

        # Add hints from external systems
        if analysis_result.external_systems:
            hints.append("        #")
            hints.append("        # External systems to integrate:")
            for system in analysis_result.external_systems:
                hints.append(f"        # - {system}")

        return "\n".join(hints)

    def _combine_implementation_parts(
        self,
        class_def: str,
        init_method: str,
        primary_method: str,
        validation_method: str,
        health_check: str,
        mixin_methods: list[str],
        capability_methods: list[str],
        contract: dict[str, Any],
        analysis_result: PRDAnalysisResult,
        node_type: str,
        microservice_name: str,
        domain: str,
    ) -> str:
        """Combine all implementation parts into complete file"""

        parts = [
            class_def,
            init_method,
            primary_method,
            validation_method,
            health_check,
        ]

        # Add mixin methods
        if mixin_methods:
            parts.append("\n    # Mixin Methods")
            parts.extend(mixin_methods)

        # Add capability methods
        if capability_methods:
            parts.append("\n    # Capability Methods")
            parts.extend(capability_methods)

        # Add main guard
        parts.append(self._generate_main_guard(microservice_name, node_type))

        return "\n".join(parts)

    def _generate_main_guard(self, microservice_name: str, node_type: str) -> str:
        """Generate if __name__ == '__main__' block"""

        pascal_name = self._to_pascal_case(microservice_name)

        guard = f'''

# Main execution example
if __name__ == "__main__":
    """Example usage of {pascal_name} {node_type} service"""

    async def main():
        # Initialize service
        config = {{"debug": True}}
        service = Node{pascal_name}{node_type.capitalize()}(config)

        # Check health
        health = await service.get_health_status()
        print(f"Service health: {{health}}")

        # Example operation
        input_data = {{
            "operation": "example",
            "data": {{"test": "value"}}
        }}

        correlation_id = uuid4()
        result = await service.{self.node_primary_methods[node_type]}(
            input_data,
            correlation_id=correlation_id
        )

        print(f"Operation result: {{result}}")

    # Run example
    asyncio.run(main())
'''

        return guard

    def _format_capabilities_docstring(self, contract: dict[str, Any]) -> str:
        """Format capabilities for docstring"""

        capabilities = contract.get("capabilities", [])
        if not capabilities:
            return "        - No capabilities defined"

        lines = []
        for cap in capabilities[:5]:  # Show first 5
            if isinstance(cap, dict):
                name = cap.get("name", "unknown")
                desc = cap.get("description", "")
                lines.append(f"        - {name}: {desc}")

        if len(capabilities) > 5:
            lines.append(f"        - ... and {len(capabilities) - 5} more")

        return "\n".join(lines)

    def _format_dependencies_docstring(self, contract: dict[str, Any]) -> str:
        """Format dependencies for docstring"""

        external_systems = contract.get("dependencies", {}).get("external_systems", [])
        if not external_systems:
            return "        - None"

        lines = [f"        - {system}" for system in external_systems]
        return "\n".join(lines)

    def _extract_mixins_from_contract(self, contract: dict[str, Any]) -> list[str]:
        """
        Extract mixin names from contract.

        Supports two formats:
        1. dependencies.required_mixins: [list of mixin names]
        2. subcontracts: [{"mixin": "MixinName", ...}, ...]

        Args:
            contract: Contract dictionary

        Returns:
            List of mixin names
        """
        mixins = []

        # Check dependencies.required_mixins format
        if "dependencies" in contract:
            deps_mixins = contract["dependencies"].get("required_mixins", [])
            if deps_mixins:
                mixins.extend(deps_mixins)

        # Check subcontracts format
        if "subcontracts" in contract:
            for subcontract in contract["subcontracts"]:
                if isinstance(subcontract, dict) and "mixin" in subcontract:
                    mixins.append(subcontract["mixin"])

        return mixins

    def _to_pascal_case(self, text: str) -> str:
        """Convert text to PascalCase"""
        return "".join(
            word.capitalize()
            for word in text.replace("_", " ").replace("-", " ").split()
        )

    def _sanitize_method_name(self, text: str) -> str:
        """Convert text to valid Python method name"""
        # Remove special characters and convert to snake_case
        name = re.sub(r"[^\w\s-]", "", text.lower())
        name = re.sub(r"[-\s]+", "_", name)
        # Ensure it doesn't start with a number
        if name and name[0].isdigit():
            name = f"_{name}"
        return name

    # ========================================================================
    # TEST API COMPATIBILITY METHODS
    # ========================================================================

    async def generate_node_stub(
        self,
        node_type: str,
        microservice_name: str,
        domain: str,
        contract: dict[str, Any],
        analysis_result: PRDAnalysisResult,
        pattern_hint: str | None = None,
        include_error_handling: bool = True,
        validation_feedback: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Generate node stub (wrapper for test compatibility).

        This method provides the API expected by tests while calling the
        internal generate_node_implementation method.

        Args:
            node_type: Type of node (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
            microservice_name: Name of the microservice
            domain: Domain of the microservice
            contract: Contract dictionary
            analysis_result: PRD analysis result
            pattern_hint: Optional pattern hint for generation
            include_error_handling: Whether to include error handling
            validation_feedback: Optional validation feedback for regeneration

        Returns:
            Dict with code, class_name, methods, and node_type
        """
        # Generate implementation
        code = await self.generate_node_implementation(
            contract=contract,
            analysis_result=analysis_result,
            node_type=node_type,
            microservice_name=microservice_name,
            domain=domain,
        )

        # Parse code to extract class name and methods
        class_name = self._extract_class_name(code, node_type, microservice_name)
        methods = self._extract_method_names(code)

        return {
            "code": code,
            "class_name": class_name,
            "methods": methods,
            "node_type": node_type,
            "microservice_name": microservice_name,
            "domain": domain,
        }

    async def generate_node_file(
        self,
        node_type: str,
        microservice_name: str,
        domain: str,
        contract: dict[str, Any],
        analysis_result: PRDAnalysisResult,
        output_directory: str,
    ) -> dict[str, Any]:
        """
        Generate node file and write to disk.

        Args:
            node_type: Type of node
            microservice_name: Name of the microservice
            domain: Domain
            contract: Contract dictionary
            analysis_result: PRD analysis result
            output_directory: Directory to write file

        Returns:
            Dict with file_path, code, class_name
        """
        # Generate stub first
        result = await self.generate_node_stub(
            node_type=node_type,
            microservice_name=microservice_name,
            domain=domain,
            contract=contract,
            analysis_result=analysis_result,
        )

        # Generate file name
        self._to_pascal_case(microservice_name)
        file_name = f"node_{microservice_name}_{node_type.lower()}.py"
        file_path = Path(output_directory) / file_name

        # Write to file
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(result["code"])

        return {**result, "file_path": str(file_path), "file_name": file_name}

    def _extract_class_name(
        self, code: str, node_type: str, microservice_name: str
    ) -> str:
        """Extract class name from generated code"""
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    if node.name.startswith("Node"):
                        return node.name
        except Exception:
            pass

        # Fallback to generated name
        pascal_name = self._to_pascal_case(microservice_name)
        return f"Node{pascal_name}{node_type.capitalize()}"

    def _extract_method_names(self, code: str) -> list[str]:
        """Extract method names from generated code"""
        methods = []
        try:
            tree = ast.parse(code)
            # Find the main class definition
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name.startswith("Node"):
                    # Extract methods from this class only
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            methods.append(item.name)
                    break
        except Exception:
            pass
        return methods
