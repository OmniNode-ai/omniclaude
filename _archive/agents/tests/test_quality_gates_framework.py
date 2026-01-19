#!/usr/bin/env python3
"""
Tests for Quality Gates Framework (Poly-1 Deliverable).

Validates:
- EnumQualityGate properties and metadata (23 gates)
- ModelQualityGateResult validation and computed properties
- ModelQualityGateResultSummary aggregation
- QualityGateRegistry execution and tracking
- BaseQualityGate validator interface
- Dependency checking logic

ONEX v2.0 Compliance:
- Test naming follows test_<component>_<scenario> pattern
- Comprehensive coverage of all 23 gates
- Type safety validation
"""

from datetime import UTC, datetime

import pytest

from agents.lib.models.model_quality_gate import (
    EnumQualityGate,
    ModelQualityGateResult,
    ModelQualityGateResultSummary,
    QualityGateRegistry,
)
from agents.lib.validators.base_quality_gate import BaseQualityGate


class TestEnumQualityGate:
    """Test EnumQualityGate enum and properties."""

    def test_all_gates_defined(self):
        """Verify all 23 gates are defined."""
        gates = EnumQualityGate.all_gates()
        assert len(gates) == 23, f"Expected 23 gates, got {len(gates)}"

    def test_gate_categories(self):
        """Verify gate category assignments."""
        # Sequential (4 gates)
        assert EnumQualityGate.INPUT_VALIDATION.category == "sequential_validation"
        assert EnumQualityGate.PROCESS_VALIDATION.category == "sequential_validation"
        assert EnumQualityGate.OUTPUT_VALIDATION.category == "sequential_validation"
        assert EnumQualityGate.INTEGRATION_TESTING.category == "sequential_validation"

        # Parallel (3 gates)
        assert EnumQualityGate.CONTEXT_SYNCHRONIZATION.category == "parallel_validation"
        assert EnumQualityGate.COORDINATION_VALIDATION.category == "parallel_validation"
        assert EnumQualityGate.RESULT_CONSISTENCY.category == "parallel_validation"

        # Intelligence (3 gates)
        assert (
            EnumQualityGate.RAG_QUERY_VALIDATION.category == "intelligence_validation"
        )
        assert (
            EnumQualityGate.KNOWLEDGE_APPLICATION.category == "intelligence_validation"
        )
        assert EnumQualityGate.LEARNING_CAPTURE.category == "intelligence_validation"

        # Coordination (3 gates)
        assert EnumQualityGate.CONTEXT_INHERITANCE.category == "coordination_validation"
        assert EnumQualityGate.AGENT_COORDINATION.category == "coordination_validation"
        assert (
            EnumQualityGate.DELEGATION_VALIDATION.category == "coordination_validation"
        )

        # Quality Compliance (4 gates)
        assert EnumQualityGate.ONEX_STANDARDS.category == "quality_compliance"
        assert EnumQualityGate.ANTI_YOLO_COMPLIANCE.category == "quality_compliance"
        assert EnumQualityGate.TYPE_SAFETY.category == "quality_compliance"
        assert EnumQualityGate.ERROR_HANDLING.category == "quality_compliance"

        # Performance (2 gates)
        assert (
            EnumQualityGate.PERFORMANCE_THRESHOLDS.category == "performance_validation"
        )
        assert EnumQualityGate.RESOURCE_UTILIZATION.category == "performance_validation"

        # Knowledge (2 gates)
        assert EnumQualityGate.UAKS_INTEGRATION.category == "knowledge_validation"
        assert EnumQualityGate.PATTERN_RECOGNITION.category == "knowledge_validation"

        # Framework (2 gates)
        assert EnumQualityGate.LIFECYCLE_COMPLIANCE.category == "framework_validation"
        assert EnumQualityGate.FRAMEWORK_INTEGRATION.category == "framework_validation"

    def test_performance_targets(self):
        """Verify performance targets are set correctly."""
        # Sample gates with known targets
        assert EnumQualityGate.INPUT_VALIDATION.performance_target_ms == 50
        assert EnumQualityGate.PROCESS_VALIDATION.performance_target_ms == 30
        assert EnumQualityGate.RAG_QUERY_VALIDATION.performance_target_ms == 100
        assert EnumQualityGate.CONTEXT_SYNCHRONIZATION.performance_target_ms == 80
        assert EnumQualityGate.FRAMEWORK_INTEGRATION.performance_target_ms == 25

        # All gates should have positive targets
        for gate in EnumQualityGate.all_gates():
            assert gate.performance_target_ms > 0, f"{gate.value} has invalid target"
            assert gate.performance_target_ms <= 200, f"{gate.value} target > 200ms"

    def test_validation_types(self):
        """Verify validation type assignments."""
        # Blocking gates
        blocking = [
            EnumQualityGate.INPUT_VALIDATION,
            EnumQualityGate.OUTPUT_VALIDATION,
            EnumQualityGate.CONTEXT_SYNCHRONIZATION,
            EnumQualityGate.RESULT_CONSISTENCY,
            EnumQualityGate.CONTEXT_INHERITANCE,
            EnumQualityGate.ONEX_STANDARDS,
            EnumQualityGate.TYPE_SAFETY,
            EnumQualityGate.LIFECYCLE_COMPLIANCE,
            EnumQualityGate.FRAMEWORK_INTEGRATION,
        ]
        for gate in blocking:
            assert (
                gate.validation_type == "blocking"
            ), f"{gate.value} should be blocking"

        # Monitoring gates
        assert EnumQualityGate.PROCESS_VALIDATION.validation_type == "monitoring"
        assert EnumQualityGate.COORDINATION_VALIDATION.validation_type == "monitoring"
        assert EnumQualityGate.RESOURCE_UTILIZATION.validation_type == "monitoring"

        # Checkpoint gates
        assert EnumQualityGate.INTEGRATION_TESTING.validation_type == "checkpoint"
        assert EnumQualityGate.PERFORMANCE_THRESHOLDS.validation_type == "checkpoint"

    def test_gate_names(self):
        """Verify human-readable gate names."""
        assert EnumQualityGate.INPUT_VALIDATION.gate_name == "Input Validation"
        assert EnumQualityGate.RAG_QUERY_VALIDATION.gate_name == "RAG Query Validation"
        assert EnumQualityGate.ONEX_STANDARDS.gate_name == "ONEX Standards"

    def test_category_counts(self):
        """Verify correct number of gates per category."""
        categories = {}
        for gate in EnumQualityGate.all_gates():
            cat = gate.category
            categories[cat] = categories.get(cat, 0) + 1

        assert categories["sequential_validation"] == 4
        assert categories["parallel_validation"] == 3
        assert categories["intelligence_validation"] == 3
        assert categories["coordination_validation"] == 3
        assert categories["quality_compliance"] == 4
        assert categories["performance_validation"] == 2
        assert categories["knowledge_validation"] == 2
        assert categories["framework_validation"] == 2


class TestModelQualityGateResult:
    """Test ModelQualityGateResult Pydantic model."""

    def test_create_passed_result(self):
        """Test creating a passed gate result."""
        result = ModelQualityGateResult(
            gate=EnumQualityGate.INPUT_VALIDATION,
            status="passed",
            execution_time_ms=45,
            message="All inputs validated successfully",
        )

        assert result.gate == EnumQualityGate.INPUT_VALIDATION
        assert result.status == "passed"
        assert result.passed is True
        assert result.execution_time_ms == 45
        assert result.message == "All inputs validated successfully"

    def test_create_failed_result(self):
        """Test creating a failed gate result."""
        result = ModelQualityGateResult(
            gate=EnumQualityGate.TYPE_SAFETY,
            status="failed",
            execution_time_ms=65,
            message="Type errors detected",
            metadata={"errors": ["Missing type hint on line 42"]},
        )

        assert result.status == "failed"
        assert result.passed is False
        assert result.metadata["errors"] == ["Missing type hint on line 42"]

    def test_create_skipped_result(self):
        """Test creating a skipped gate result."""
        result = ModelQualityGateResult(
            gate=EnumQualityGate.INTEGRATION_TESTING,
            status="skipped",
            execution_time_ms=0,
            message="Dependencies not met",
        )

        assert result.status == "skipped"
        assert result.passed is False

    def test_performance_target_check(self):
        """Test performance target validation."""
        # Meets target (50ms target, 45ms actual)
        fast_result = ModelQualityGateResult(
            gate=EnumQualityGate.INPUT_VALIDATION,
            status="passed",
            execution_time_ms=45,
            message="Fast validation",
        )
        assert fast_result.meets_performance_target is True

        # Exceeds target (50ms target, 60ms actual)
        slow_result = ModelQualityGateResult(
            gate=EnumQualityGate.INPUT_VALIDATION,
            status="passed",
            execution_time_ms=60,
            message="Slow validation",
        )
        assert slow_result.meets_performance_target is False

    def test_blocking_check(self):
        """Test is_blocking property."""
        # Blocking gate
        blocking_result = ModelQualityGateResult(
            gate=EnumQualityGate.ONEX_STANDARDS,
            status="failed",
            execution_time_ms=80,
            message="ONEX violations found",
        )
        assert blocking_result.is_blocking is True

        # Non-blocking gate
        monitoring_result = ModelQualityGateResult(
            gate=EnumQualityGate.PROCESS_VALIDATION,
            status="passed",
            execution_time_ms=25,
            message="Process valid",
        )
        assert monitoring_result.is_blocking is False

    def test_to_dict_serialization(self):
        """Test dictionary serialization."""
        result = ModelQualityGateResult(
            gate=EnumQualityGate.INPUT_VALIDATION,
            status="passed",
            execution_time_ms=45,
            message="Success",
            metadata={"count": 5},
        )

        data = result.to_dict()

        assert data["gate"] == "sv_001_input_validation"
        assert data["gate_name"] == "Input Validation"
        assert data["category"] == "sequential_validation"
        assert data["status"] == "passed"
        assert data["passed"] is True
        assert data["execution_time_ms"] == 45
        assert data["performance_target_ms"] == 50
        assert data["meets_performance_target"] is True
        assert data["metadata"]["count"] == 5

    def test_timestamp_defaults_to_now(self):
        """Test timestamp defaults to current UTC time."""
        before = datetime.now(UTC)
        result = ModelQualityGateResult(
            gate=EnumQualityGate.INPUT_VALIDATION,
            status="passed",
            execution_time_ms=45,
            message="Success",
        )
        after = datetime.now(UTC)

        assert before <= result.timestamp <= after


class TestModelQualityGateResultSummary:
    """Test ModelQualityGateResultSummary aggregation model."""

    def test_create_summary(self):
        """Test creating a result summary."""
        results = [
            ModelQualityGateResult(
                gate=EnumQualityGate.INPUT_VALIDATION,
                status="passed",
                execution_time_ms=45,
                message="Input valid",
            ),
            ModelQualityGateResult(
                gate=EnumQualityGate.OUTPUT_VALIDATION,
                status="passed",
                execution_time_ms=38,
                message="Output valid",
            ),
            ModelQualityGateResult(
                gate=EnumQualityGate.TYPE_SAFETY,
                status="failed",
                execution_time_ms=70,
                message="Type errors",
            ),
        ]

        summary = ModelQualityGateResultSummary(
            total_gates=3,
            passed=2,
            failed=1,
            skipped=0,
            total_execution_time_ms=153,
            gates_meeting_performance=2,
            results=results,
        )

        assert summary.total_gates == 3
        assert summary.passed == 2
        assert summary.failed == 1
        assert summary.pass_rate == pytest.approx(0.667, abs=0.01)

    def test_blocking_failures_check(self):
        """Test has_blocking_failures property."""
        # With blocking failure
        with_blocking = ModelQualityGateResultSummary(
            total_gates=2,
            passed=1,
            failed=1,
            skipped=0,
            total_execution_time_ms=100,
            gates_meeting_performance=1,
            results=[
                ModelQualityGateResult(
                    gate=EnumQualityGate.INPUT_VALIDATION,
                    status="passed",
                    execution_time_ms=45,
                    message="Success",
                ),
                ModelQualityGateResult(
                    gate=EnumQualityGate.ONEX_STANDARDS,
                    status="failed",
                    execution_time_ms=80,
                    message="ONEX violation",
                ),
            ],
        )
        assert with_blocking.has_blocking_failures is True

        # Without blocking failure
        without_blocking = ModelQualityGateResultSummary(
            total_gates=1,
            passed=1,
            failed=0,
            skipped=0,
            total_execution_time_ms=45,
            gates_meeting_performance=1,
            results=[
                ModelQualityGateResult(
                    gate=EnumQualityGate.INPUT_VALIDATION,
                    status="passed",
                    execution_time_ms=45,
                    message="Success",
                ),
            ],
        )
        assert without_blocking.has_blocking_failures is False


class TestQualityGateRegistry:
    """Test QualityGateRegistry execution and tracking."""

    def test_registry_initialization(self):
        """Test registry initializes empty."""
        registry = QualityGateRegistry()
        assert len(registry.results) == 0

    @pytest.mark.asyncio
    async def test_check_gate(self):
        """Test executing a quality gate check."""
        registry = QualityGateRegistry()
        result = await registry.check_gate(
            EnumQualityGate.INPUT_VALIDATION, {"test": "context"}
        )

        assert result.gate == EnumQualityGate.INPUT_VALIDATION
        assert result.status == "passed"
        assert len(registry.results) == 1

    @pytest.mark.asyncio
    async def test_get_results_all(self):
        """Test retrieving all results."""
        registry = QualityGateRegistry()
        await registry.check_gate(EnumQualityGate.INPUT_VALIDATION, {})
        await registry.check_gate(EnumQualityGate.OUTPUT_VALIDATION, {})

        all_results = registry.get_results()
        assert len(all_results) == 2

    @pytest.mark.asyncio
    async def test_get_results_filtered(self):
        """Test retrieving filtered results."""
        registry = QualityGateRegistry()
        await registry.check_gate(EnumQualityGate.INPUT_VALIDATION, {})
        await registry.check_gate(EnumQualityGate.OUTPUT_VALIDATION, {})

        filtered = registry.get_results(EnumQualityGate.INPUT_VALIDATION)
        assert len(filtered) == 1
        assert filtered[0].gate == EnumQualityGate.INPUT_VALIDATION

    def test_get_failed_gates(self):
        """Test retrieving failed gates."""
        registry = QualityGateRegistry()

        registry.results = [
            ModelQualityGateResult(
                gate=EnumQualityGate.INPUT_VALIDATION,
                status="passed",
                execution_time_ms=45,
                message="Success",
            ),
            ModelQualityGateResult(
                gate=EnumQualityGate.TYPE_SAFETY,
                status="failed",
                execution_time_ms=70,
                message="Type errors",
            ),
        ]

        failed = registry.get_failed_gates()
        assert len(failed) == 1
        assert failed[0].gate == EnumQualityGate.TYPE_SAFETY

    def test_get_blocking_failures(self):
        """Test retrieving blocking failures."""
        registry = QualityGateRegistry()

        registry.results = [
            ModelQualityGateResult(
                gate=EnumQualityGate.PROCESS_VALIDATION,  # monitoring, not blocking
                status="failed",
                execution_time_ms=35,
                message="Process issues",
            ),
            ModelQualityGateResult(
                gate=EnumQualityGate.ONEX_STANDARDS,  # blocking
                status="failed",
                execution_time_ms=85,
                message="ONEX violations",
            ),
        ]

        blocking = registry.get_blocking_failures()
        assert len(blocking) == 1
        assert blocking[0].gate == EnumQualityGate.ONEX_STANDARDS

    def test_clear(self):
        """Test clearing results."""
        registry = QualityGateRegistry()
        registry.results = [
            ModelQualityGateResult(
                gate=EnumQualityGate.INPUT_VALIDATION,
                status="passed",
                execution_time_ms=45,
                message="Success",
            )
        ]

        registry.clear()
        assert len(registry.results) == 0

    def test_get_summary(self):
        """Test generating results summary."""
        registry = QualityGateRegistry()

        registry.results = [
            ModelQualityGateResult(
                gate=EnumQualityGate.INPUT_VALIDATION,
                status="passed",
                execution_time_ms=45,
                message="Success",
            ),
            ModelQualityGateResult(
                gate=EnumQualityGate.OUTPUT_VALIDATION,
                status="passed",
                execution_time_ms=38,
                message="Success",
            ),
            ModelQualityGateResult(
                gate=EnumQualityGate.TYPE_SAFETY,
                status="failed",
                execution_time_ms=70,
                message="Type errors",
            ),
        ]

        summary = registry.get_summary()

        assert summary["total_gates"] == 3
        assert summary["passed"] == 2
        assert summary["failed"] == 1
        assert summary["skipped"] == 0
        assert summary["pass_rate"] == pytest.approx(0.667, abs=0.01)
        assert summary["total_execution_time_ms"] == 153


class TestBaseQualityGate:
    """Test BaseQualityGate validator interface."""

    class MockValidator(BaseQualityGate):
        """Mock validator for testing."""

        async def validate(self, context: dict) -> ModelQualityGateResult:
            return ModelQualityGateResult(
                gate=self.gate,
                status="passed",
                execution_time_ms=45,
                message="Mock validation passed",
            )

    def test_validator_initialization(self):
        """Test initializing a validator."""
        validator = self.MockValidator(EnumQualityGate.INPUT_VALIDATION)
        assert validator.gate == EnumQualityGate.INPUT_VALIDATION

    @pytest.mark.asyncio
    async def test_execute_with_timing(self):
        """Test execution with automatic timing."""
        validator = self.MockValidator(EnumQualityGate.INPUT_VALIDATION)
        result = await validator.execute_with_timing({})

        assert result.gate == EnumQualityGate.INPUT_VALIDATION
        assert result.status == "passed"
        assert result.execution_time_ms >= 0
        assert isinstance(result.timestamp, datetime)

    def test_check_dependencies_no_deps(self):
        """Test dependency check with no dependencies."""
        validator = self.MockValidator(EnumQualityGate.INPUT_VALIDATION)
        met, missing = validator.check_dependencies([])

        assert met is True
        assert len(missing) == 0

    def test_get_gate_id_conversion(self):
        """Test gate ID extraction."""
        validator = self.MockValidator(EnumQualityGate.INPUT_VALIDATION)
        gate_id = validator._get_gate_id(EnumQualityGate.INPUT_VALIDATION)

        assert gate_id == "SV-001"

    def test_create_skipped_result(self):
        """Test creating skipped result."""
        validator = self.MockValidator(EnumQualityGate.INPUT_VALIDATION)
        result = validator.create_skipped_result("Dependencies not met")

        assert result.status == "skipped"
        assert result.message == "Gate skipped: Dependencies not met"
        assert result.metadata["skip_reason"] == "Dependencies not met"

    def test_should_skip_disabled_gate(self):
        """Test skipping disabled gate."""
        validator = self.MockValidator(EnumQualityGate.INPUT_VALIDATION)

        context = {"disabled_gates": [EnumQualityGate.INPUT_VALIDATION]}
        should_skip, reason = validator.should_skip(context, [])

        assert should_skip is True
        assert "disabled" in reason.lower()

    def test_get_info(self):
        """Test getting gate metadata."""
        validator = self.MockValidator(EnumQualityGate.INPUT_VALIDATION)
        info = validator.get_info()

        assert info["gate"] == "sv_001_input_validation"
        assert info["name"] == "Input Validation"
        assert info["category"] == "sequential_validation"
        assert info["performance_target_ms"] == 50
        assert info["is_mandatory"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
