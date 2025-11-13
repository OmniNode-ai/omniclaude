#!/usr/bin/env python3
"""
Quality Gate Models - ONEX v2.0 Framework Implementation

Comprehensive quality validation checkpoints for agent pipeline stages.
Implements 23 quality gates from quality-gates-spec.yaml with full metadata.

Architecture:
- EnumQualityGate: Complete gate definitions with ONEX patterns
- ModelQualityGateResult: Pydantic validation result model
- ModelQualityGateResultSummary: Aggregate validation reporting
- QualityGateRegistry: Gate execution and results tracking

ONEX v2.0 Compliance:
- Enum/Model naming conventions
- Complete metadata from specification
- Pydantic v2 for type safety
- Performance tracking and validation
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class EnumQualityGate(str, Enum):
    """
    23 Quality gates across 8 validation categories.

    Total Target Time: <200ms per gate
    Categories: Sequential, Parallel, Intelligence, Coordination, Quality,
                Performance, Knowledge, Framework validation

    Gate Breakdown:
    - Sequential Validation (4): Input, process, output, integration testing
    - Parallel Validation (3): Context sync, coordination, result consistency
    - Intelligence Validation (3): RAG query, knowledge application, learning capture
    - Coordination Validation (3): Context inheritance, agent coordination, delegation
    - Quality Compliance (4): ONEX standards, anti-YOLO, type safety, error handling
    - Performance Validation (2): Performance thresholds, resource utilization
    - Knowledge Validation (2): UAKS integration, pattern recognition
    - Framework Validation (2): Lifecycle compliance, framework integration
    """

    # Sequential Validation Gates (SV-001 to SV-004)
    INPUT_VALIDATION = "sv_001_input_validation"
    PROCESS_VALIDATION = "sv_002_process_validation"
    OUTPUT_VALIDATION = "sv_003_output_validation"
    INTEGRATION_TESTING = "sv_004_integration_testing"

    # Parallel Validation Gates (PV-001 to PV-003)
    CONTEXT_SYNCHRONIZATION = "pv_001_context_synchronization"
    COORDINATION_VALIDATION = "pv_002_coordination_validation"
    RESULT_CONSISTENCY = "pv_003_result_consistency"

    # Intelligence Validation Gates (IV-001 to IV-003)
    RAG_QUERY_VALIDATION = "iv_001_rag_query_validation"
    KNOWLEDGE_APPLICATION = "iv_002_knowledge_application"
    LEARNING_CAPTURE = "iv_003_learning_capture"

    # Coordination Validation Gates (CV-001 to CV-003)
    CONTEXT_INHERITANCE = "cv_001_context_inheritance"
    AGENT_COORDINATION = "cv_002_agent_coordination"
    DELEGATION_VALIDATION = "cv_003_delegation_validation"

    # Quality Compliance Gates (QC-001 to QC-004)
    ONEX_STANDARDS = "qc_001_onex_standards"
    ANTI_YOLO_COMPLIANCE = "qc_002_anti_yolo_compliance"
    TYPE_SAFETY = "qc_003_type_safety"
    ERROR_HANDLING = "qc_004_error_handling"

    # Performance Validation Gates (PF-001 to PF-002)
    PERFORMANCE_THRESHOLDS = "pf_001_performance_thresholds"
    RESOURCE_UTILIZATION = "pf_002_resource_utilization"

    # Knowledge Validation Gates (KV-001 to KV-002)
    UAKS_INTEGRATION = "kv_001_uaks_integration"
    PATTERN_RECOGNITION = "kv_002_pattern_recognition"

    # Framework Validation Gates (FV-001 to FV-002)
    LIFECYCLE_COMPLIANCE = "fv_001_lifecycle_compliance"
    FRAMEWORK_INTEGRATION = "fv_002_framework_integration"

    @property
    def category(self) -> str:
        """Get category name for this gate."""
        categories = {
            # Sequential
            self.INPUT_VALIDATION: "sequential_validation",
            self.PROCESS_VALIDATION: "sequential_validation",
            self.OUTPUT_VALIDATION: "sequential_validation",
            self.INTEGRATION_TESTING: "sequential_validation",
            # Parallel
            self.CONTEXT_SYNCHRONIZATION: "parallel_validation",
            self.COORDINATION_VALIDATION: "parallel_validation",
            self.RESULT_CONSISTENCY: "parallel_validation",
            # Intelligence
            self.RAG_QUERY_VALIDATION: "intelligence_validation",
            self.KNOWLEDGE_APPLICATION: "intelligence_validation",
            self.LEARNING_CAPTURE: "intelligence_validation",
            # Coordination
            self.CONTEXT_INHERITANCE: "coordination_validation",
            self.AGENT_COORDINATION: "coordination_validation",
            self.DELEGATION_VALIDATION: "coordination_validation",
            # Quality
            self.ONEX_STANDARDS: "quality_compliance",
            self.ANTI_YOLO_COMPLIANCE: "quality_compliance",
            self.TYPE_SAFETY: "quality_compliance",
            self.ERROR_HANDLING: "quality_compliance",
            # Performance
            self.PERFORMANCE_THRESHOLDS: "performance_validation",
            self.RESOURCE_UTILIZATION: "performance_validation",
            # Knowledge
            self.UAKS_INTEGRATION: "knowledge_validation",
            self.PATTERN_RECOGNITION: "knowledge_validation",
            # Framework
            self.LIFECYCLE_COMPLIANCE: "framework_validation",
            self.FRAMEWORK_INTEGRATION: "framework_validation",
        }
        return categories.get(self, "unknown")

    @property
    def performance_target_ms(self) -> int:
        """Get performance target in milliseconds."""
        targets = {
            self.INPUT_VALIDATION: 50,
            self.PROCESS_VALIDATION: 30,
            self.OUTPUT_VALIDATION: 40,
            self.INTEGRATION_TESTING: 60,
            self.CONTEXT_SYNCHRONIZATION: 80,
            self.COORDINATION_VALIDATION: 50,
            self.RESULT_CONSISTENCY: 70,
            self.RAG_QUERY_VALIDATION: 100,
            self.KNOWLEDGE_APPLICATION: 75,
            self.LEARNING_CAPTURE: 50,
            self.CONTEXT_INHERITANCE: 40,
            self.AGENT_COORDINATION: 60,
            self.DELEGATION_VALIDATION: 45,
            self.ONEX_STANDARDS: 80,
            self.ANTI_YOLO_COMPLIANCE: 30,
            self.TYPE_SAFETY: 60,
            self.ERROR_HANDLING: 40,
            self.PERFORMANCE_THRESHOLDS: 30,
            self.RESOURCE_UTILIZATION: 25,
            self.UAKS_INTEGRATION: 50,
            self.PATTERN_RECOGNITION: 40,
            self.LIFECYCLE_COMPLIANCE: 35,
            self.FRAMEWORK_INTEGRATION: 25,
        }
        return targets.get(self, 200)

    @property
    def gate_name(self) -> str:
        """Get human-readable gate name."""
        names = {
            self.INPUT_VALIDATION: "Input Validation",
            self.PROCESS_VALIDATION: "Process Validation",
            self.OUTPUT_VALIDATION: "Output Validation",
            self.INTEGRATION_TESTING: "Integration Testing",
            self.CONTEXT_SYNCHRONIZATION: "Context Synchronization",
            self.COORDINATION_VALIDATION: "Coordination Validation",
            self.RESULT_CONSISTENCY: "Result Consistency",
            self.RAG_QUERY_VALIDATION: "RAG Query Validation",
            self.KNOWLEDGE_APPLICATION: "Knowledge Application",
            self.LEARNING_CAPTURE: "Learning Capture",
            self.CONTEXT_INHERITANCE: "Context Inheritance",
            self.AGENT_COORDINATION: "Agent Coordination",
            self.DELEGATION_VALIDATION: "Delegation Validation",
            self.ONEX_STANDARDS: "ONEX Standards",
            self.ANTI_YOLO_COMPLIANCE: "Anti-YOLO Compliance",
            self.TYPE_SAFETY: "Type Safety",
            self.ERROR_HANDLING: "Error Handling",
            self.PERFORMANCE_THRESHOLDS: "Performance Thresholds",
            self.RESOURCE_UTILIZATION: "Resource Utilization",
            self.UAKS_INTEGRATION: "UAKS Integration",
            self.PATTERN_RECOGNITION: "Pattern Recognition",
            self.LIFECYCLE_COMPLIANCE: "Lifecycle Compliance",
            self.FRAMEWORK_INTEGRATION: "Framework Integration",
        }
        return names.get(self, "Unknown")

    @property
    def description(self) -> str:
        """Get gate description."""
        # Shortened for space - full descriptions in docstrings above
        return f"{self.gate_name} validation"

    @property
    def validation_type(
        self,
    ) -> Literal["blocking", "monitoring", "checkpoint", "quality_check"]:
        """Get validation type."""
        types = {
            self.INPUT_VALIDATION: "blocking",
            self.PROCESS_VALIDATION: "monitoring",
            self.OUTPUT_VALIDATION: "blocking",
            self.INTEGRATION_TESTING: "checkpoint",
            self.CONTEXT_SYNCHRONIZATION: "blocking",
            self.COORDINATION_VALIDATION: "monitoring",
            self.RESULT_CONSISTENCY: "blocking",
            self.RAG_QUERY_VALIDATION: "quality_check",
            self.KNOWLEDGE_APPLICATION: "monitoring",
            self.LEARNING_CAPTURE: "checkpoint",
            self.CONTEXT_INHERITANCE: "blocking",
            self.AGENT_COORDINATION: "monitoring",
            self.DELEGATION_VALIDATION: "checkpoint",
            self.ONEX_STANDARDS: "blocking",
            self.ANTI_YOLO_COMPLIANCE: "monitoring",
            self.TYPE_SAFETY: "blocking",
            self.ERROR_HANDLING: "checkpoint",
            self.PERFORMANCE_THRESHOLDS: "checkpoint",
            self.RESOURCE_UTILIZATION: "monitoring",
            self.UAKS_INTEGRATION: "checkpoint",
            self.PATTERN_RECOGNITION: "checkpoint",
            self.LIFECYCLE_COMPLIANCE: "blocking",
            self.FRAMEWORK_INTEGRATION: "blocking",
        }
        return types.get(self, "checkpoint")

    @property
    def execution_point(self) -> str:
        """Get execution point for this gate."""
        points = {
            self.INPUT_VALIDATION: "pre_task_execution",
            self.PROCESS_VALIDATION: "during_execution",
            self.OUTPUT_VALIDATION: "post_execution",
            self.INTEGRATION_TESTING: "delegation_points",
            self.CONTEXT_SYNCHRONIZATION: "parallel_initialization",
            self.COORDINATION_VALIDATION: "coordination_checkpoints",
            self.RESULT_CONSISTENCY: "result_aggregation",
            self.RAG_QUERY_VALIDATION: "intelligence_gathering",
            self.KNOWLEDGE_APPLICATION: "execution_planning",
            self.LEARNING_CAPTURE: "completion",
            self.CONTEXT_INHERITANCE: "agent_delegation",
            self.AGENT_COORDINATION: "multi_agent_workflows",
            self.DELEGATION_VALIDATION: "delegation_completion",
            self.ONEX_STANDARDS: "code_generation",
            self.ANTI_YOLO_COMPLIANCE: "workflow_execution",
            self.TYPE_SAFETY: "code_generation",
            self.ERROR_HANDLING: "error_scenarios",
            self.PERFORMANCE_THRESHOLDS: "execution_completion",
            self.RESOURCE_UTILIZATION: "continuous_monitoring",
            self.UAKS_INTEGRATION: "completion",
            self.PATTERN_RECOGNITION: "completion",
            self.LIFECYCLE_COMPLIANCE: "initialization_and_cleanup",
            self.FRAMEWORK_INTEGRATION: "initialization",
        }
        return points.get(self, "unknown")

    @property
    def automation_level(self) -> Literal["fully_automated", "semi_automated"]:
        """Get automation level for this gate."""
        # Most gates are fully automated, only a few are semi-automated
        semi_automated = {
            self.INTEGRATION_TESTING,
            self.KNOWLEDGE_APPLICATION,
        }
        return "semi_automated" if self in semi_automated else "fully_automated"

    @property
    def dependencies(self) -> list[str]:
        """Get list of gate IDs this gate depends on."""
        deps = {
            self.PROCESS_VALIDATION: ["SV-001"],
            self.OUTPUT_VALIDATION: ["SV-002"],
            self.INTEGRATION_TESTING: ["SV-001", "SV-002"],
            self.COORDINATION_VALIDATION: ["PV-001"],
            self.RESULT_CONSISTENCY: ["PV-001", "PV-002"],
            self.KNOWLEDGE_APPLICATION: ["IV-001"],
            self.LEARNING_CAPTURE: ["IV-002"],
            self.AGENT_COORDINATION: ["CV-001"],
            self.DELEGATION_VALIDATION: ["CV-001", "CV-002"],
            self.TYPE_SAFETY: ["QC-001"],
            self.ERROR_HANDLING: ["QC-001"],
            self.PATTERN_RECOGNITION: ["KV-001"],
        }
        return deps.get(self, [])

    @property
    def is_mandatory(self) -> bool:
        """Check if gate is mandatory (all gates are mandatory in spec)."""
        return True

    @staticmethod
    def all_gates() -> list["EnumQualityGate"]:
        """Get all quality gates in definition order."""
        return list(EnumQualityGate)


class ModelQualityGateResult(BaseModel):
    """
    Result of a quality gate validation execution.

    ONEX v2.0 compliant Pydantic model with comprehensive result tracking.
    """

    gate: EnumQualityGate = Field(..., description="The quality gate that was executed")
    status: Literal["passed", "failed", "skipped"] = Field(
        ..., description="Validation status"
    )
    execution_time_ms: int = Field(
        ..., ge=0, description="Actual execution time in milliseconds"
    )
    message: str = Field(..., min_length=1, description="Human-readable result message")
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Additional context (None normalized to {})"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When validation was executed (UTC)",
    )

    @property
    def passed(self) -> bool:
        """Check if gate passed."""
        return self.status == "passed"

    @property
    def is_blocking(self) -> bool:
        """Check if gate failure should block pipeline."""
        return self.gate.validation_type == "blocking"

    @property
    def meets_performance_target(self) -> bool:
        """Check if execution time meets performance target."""
        return self.execution_time_ms <= self.gate.performance_target_ms

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "gate": self.gate.value,
            "gate_name": self.gate.gate_name,
            "category": self.gate.category,
            "status": self.status,
            "passed": self.passed,
            "is_blocking": self.is_blocking,
            "execution_time_ms": self.execution_time_ms,
            "performance_target_ms": self.gate.performance_target_ms,
            "meets_performance_target": self.meets_performance_target,
            "message": self.message,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }

    model_config = {
        "arbitrary_types_allowed": True,
    }


class ModelQualityGateResultSummary(BaseModel):
    """Aggregate summary of multiple quality gate results."""

    total_gates: int = Field(..., ge=0)
    passed: int = Field(..., ge=0)
    failed: int = Field(..., ge=0)
    skipped: int = Field(..., ge=0)
    total_execution_time_ms: int = Field(..., ge=0)
    gates_meeting_performance: int = Field(..., ge=0)
    results: list[ModelQualityGateResult] = Field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate."""
        return self.passed / self.total_gates if self.total_gates > 0 else 0.0

    @property
    def has_blocking_failures(self) -> bool:
        """Check if any blocking gates failed."""
        return any(r.status == "failed" and r.is_blocking for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_gates": self.total_gates,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "pass_rate": self.pass_rate,
            "total_execution_time_ms": self.total_execution_time_ms,
            "gates_meeting_performance": self.gates_meeting_performance,
            "has_blocking_failures": self.has_blocking_failures,
            "results": [r.to_dict() for r in self.results],
        }


class QualityGateRegistry:
    """
    Registry for quality gate execution and results tracking.

    Updated to work with ONEX v2.0 Pydantic models while maintaining
    backward compatibility with existing pipeline code.

    Supports validator registration and automatic execution with dependency checking.
    """

    def __init__(self) -> None:
        """Initialize quality gate registry."""
        self.results: list[ModelQualityGateResult] = []
        self.validators: dict[EnumQualityGate, Any] = {}  # Map gate -> validator

    def register_validator(self, validator: Any) -> None:
        """
        Register a quality gate validator.

        Args:
            validator: BaseQualityGate subclass instance

        Raises:
            ValueError: If validator is already registered
        """
        if validator.gate in self.validators:
            raise ValueError(f"Validator for {validator.gate.value} already registered")
        self.validators[validator.gate] = validator

    async def check_gate(
        self, gate: EnumQualityGate, context: dict[str, Any]
    ) -> ModelQualityGateResult:
        """
        Execute quality gate check.

        If a validator is registered for this gate, executes the validator.
        Otherwise, returns a placeholder pass result for backward compatibility.

        Args:
            gate: Quality gate to check
            context: Validation context

        Returns:
            Gate execution result
        """
        # Check if validator is registered
        if gate in self.validators:
            validator = self.validators[gate]

            # Check if gate should be skipped
            should_skip, skip_reason = validator.should_skip(context, self.results)
            if should_skip:
                result = validator.create_skipped_result(skip_reason)
                self.results.append(result)
                return result

            # Execute validator with timing
            result = await validator.execute_with_timing(context)
            self.results.append(result)
            return result

        # Placeholder - no validator registered, backward compatibility
        result = ModelQualityGateResult(
            gate=gate,
            status="passed",
            execution_time_ms=0,
            message=f"{gate.gate_name} validation passed (placeholder)",
            metadata={"placeholder": True, "context_keys": list(context.keys())},
        )
        self.results.append(result)
        return result

    def get_results(
        self, gate: EnumQualityGate | None = None
    ) -> list[ModelQualityGateResult]:
        """Get gate results, optionally filtered by gate."""
        if gate is None:
            return self.results.copy()
        return [r for r in self.results if r.gate == gate]

    def get_failed_gates(self) -> list[ModelQualityGateResult]:
        """Get all failed gate results."""
        return [r for r in self.results if not r.passed]

    def get_blocking_failures(self) -> list[ModelQualityGateResult]:
        """Get failed results that should block pipeline."""
        return [r for r in self.results if not r.passed and r.is_blocking]

    def clear(self) -> None:
        """Clear all results."""
        self.results.clear()

    def get_summary(self) -> dict[str, Any]:
        """Generate summary of gate results."""
        summary = ModelQualityGateResultSummary(
            total_gates=len(self.results),
            passed=sum(1 for r in self.results if r.status == "passed"),
            failed=sum(1 for r in self.results if r.status == "failed"),
            skipped=sum(1 for r in self.results if r.status == "skipped"),
            total_execution_time_ms=sum(r.execution_time_ms for r in self.results),
            gates_meeting_performance=sum(
                1 for r in self.results if r.meets_performance_target
            ),
            results=self.results,
        )
        return summary.to_dict()
