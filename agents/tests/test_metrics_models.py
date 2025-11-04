#!/usr/bin/env python3
"""
Unit Tests for Performance Tracking and Quality Gate Models

Tests Week 1 Day 5 model implementations without pipeline dependencies.

Setup:
    Run with pytest from project root:

        cd /path/to/omniclaude
        pytest agents/tests/test_metrics_models.py -v

    Or use PYTHONPATH:

        PYTHONPATH=/path/to/omniclaude pytest agents/tests/test_metrics_models.py -v
"""


import pytest

from agents.lib.models.model_performance_tracking import (
    MetricsCollector,
    ModelPerformanceMetric,
    ModelPerformanceThreshold,
)
from agents.lib.models.model_quality_gate import (  # noqa: E402
    EnumQualityGate,
    ModelQualityGateResult,
    QualityGateRegistry,
)


class TestPerformanceModels:
    """Test performance tracking models."""

    def test_performance_metric_creation(self):
        """Test creating a performance metric."""
        metric = ModelPerformanceMetric(
            stage_name="test_stage",
            duration_ms=4500,
            target_ms=5000,
        )

        assert metric.stage_name == "test_stage"
        assert metric.duration_ms == 4500
        assert metric.target_ms == 5000
        assert metric.performance_ratio == 0.9
        assert metric.is_within_threshold
        assert metric.budget_variance_ms == -500

    def test_performance_metric_over_budget(self):
        """Test performance metric when over budget."""
        metric = ModelPerformanceMetric(
            stage_name="slow_stage",
            duration_ms=6000,
            target_ms=5000,
        )

        assert metric.performance_ratio == 1.2
        assert not metric.is_within_threshold  # Over 110%
        assert metric.budget_variance_ms == 1000

    def test_performance_metric_to_dict(self):
        """Test converting metric to dictionary."""
        metric = ModelPerformanceMetric(
            stage_name="test",
            duration_ms=4500,
            target_ms=5000,
        )

        data = metric.to_dict()

        assert data["stage_name"] == "test"
        assert data["duration_ms"] == 4500
        assert data["target_ms"] == 5000
        assert data["performance_ratio"] == 0.9
        assert data["is_within_threshold"] is True
        assert "timestamp" in data

    def test_performance_threshold(self):
        """Test performance threshold checking."""
        threshold = ModelPerformanceThreshold(
            stage_name="test",
            target_ms=5000,
            warning_threshold=1.1,
            error_threshold=2.0,
        )

        assert threshold.check_compliance(4500) == "success"
        assert threshold.check_compliance(5600) == "warning"  # 112%
        assert threshold.check_compliance(10500) == "error"  # 210%

    def test_metrics_collector_basic(self):
        """Test basic metrics collector operations."""
        collector = MetricsCollector()

        assert len(collector.metrics) == 0
        assert len(collector.thresholds) == 0

        collector.set_threshold("stage_1", target_ms=5000)
        assert "stage_1" in collector.thresholds

        metric = collector.record_stage_timing("stage_1", duration_ms=4500)
        assert len(collector.metrics) == 1
        assert metric.stage_name == "stage_1"

    def test_metrics_collector_summary(self):
        """Test metrics collector summary generation."""
        collector = MetricsCollector()

        collector.set_threshold("stage_1", target_ms=5000)
        collector.set_threshold("stage_2", target_ms=3000)
        collector.set_threshold("stage_3", target_ms=2000)

        collector.record_stage_timing("stage_1", duration_ms=4500)
        collector.record_stage_timing("stage_2", duration_ms=2800)
        collector.record_stage_timing("stage_3", duration_ms=1900)

        summary = collector.get_summary()

        assert summary["total_stages"] == 3
        assert summary["total_duration_ms"] == 9200
        assert summary["total_target_ms"] == 10000
        assert summary["overall_performance_ratio"] == 0.92
        assert summary["stages_within_threshold"] == 3
        assert len(summary["metrics"]) == 3

    def test_metrics_collector_get_stage_metrics(self):
        """Test getting metrics for specific stage."""
        collector = MetricsCollector()
        collector.set_threshold("stage_1", target_ms=5000)

        collector.record_stage_timing("stage_1", duration_ms=4500)
        collector.record_stage_timing("stage_1", duration_ms=4800)
        collector.record_stage_timing("stage_2", duration_ms=3000)

        stage_1_metrics = collector.get_stage_metrics("stage_1")
        assert len(stage_1_metrics) == 2
        assert all(m.stage_name == "stage_1" for m in stage_1_metrics)


class TestQualityGateModels:
    """Test quality gate models."""

    def test_quality_gate_enum_values(self):
        """Test quality gate enum values."""
        assert EnumQualityGate.INPUT_VALIDATION == "sv_001_input_validation"
        assert EnumQualityGate.OUTPUT_VALIDATION == "sv_003_output_validation"
        assert EnumQualityGate.ONEX_STANDARDS == "qc_001_onex_standards"

    def test_quality_gate_enum_properties(self):
        """Test quality gate enum properties."""
        gate = EnumQualityGate.INPUT_VALIDATION

        assert gate.category == "sequential_validation"
        assert gate.gate_name == "Input Validation"
        assert gate.validation_type == "blocking"
        assert gate.performance_target_ms == 50

    def test_quality_gate_enum_all_gates(self):
        """Test getting all quality gates."""
        all_gates = EnumQualityGate.all_gates()

        assert len(all_gates) == 23  # From spec
        assert EnumQualityGate.INPUT_VALIDATION in all_gates
        assert EnumQualityGate.ONEX_STANDARDS in all_gates

    @pytest.mark.asyncio
    async def test_quality_gate_result(self):
        """Test quality gate result model."""
        result = ModelQualityGateResult(
            gate=EnumQualityGate.INPUT_VALIDATION,
            status="passed",
            execution_time_ms=45,
            message="Input validation passed",
        )

        assert result.gate == EnumQualityGate.INPUT_VALIDATION
        assert result.status == "passed"
        assert result.passed
        assert result.is_blocking
        assert result.meets_performance_target  # 45ms < 50ms target

    @pytest.mark.asyncio
    async def test_quality_gate_result_to_dict(self):
        """Test converting gate result to dictionary."""
        result = ModelQualityGateResult(
            gate=EnumQualityGate.OUTPUT_VALIDATION,
            status="passed",
            execution_time_ms=35,
            message="Output validation passed",
        )

        data = result.to_dict()

        assert data["gate"] == "sv_003_output_validation"
        assert data["gate_name"] == "Output Validation"
        assert data["category"] == "sequential_validation"
        assert data["status"] == "passed"
        assert data["passed"] is True
        assert data["is_blocking"] is True
        assert data["execution_time_ms"] == 35
        assert data["meets_performance_target"] is True

    @pytest.mark.asyncio
    async def test_quality_gate_registry(self):
        """Test quality gate registry."""
        registry = QualityGateRegistry()

        assert len(registry.results) == 0

        result = await registry.check_gate(
            EnumQualityGate.INPUT_VALIDATION, {"test": "context"}
        )

        assert result.passed
        assert len(registry.results) == 1

    @pytest.mark.asyncio
    async def test_quality_gate_registry_summary(self):
        """Test quality gate registry summary."""
        registry = QualityGateRegistry()

        await registry.check_gate(EnumQualityGate.INPUT_VALIDATION, {})
        await registry.check_gate(EnumQualityGate.OUTPUT_VALIDATION, {})
        await registry.check_gate(EnumQualityGate.ONEX_STANDARDS, {})

        summary = registry.get_summary()

        assert summary["total_gates"] == 3
        assert summary["passed"] == 3
        assert summary["failed"] == 0
        assert summary["skipped"] == 0
        assert summary["has_blocking_failures"] is False
        assert len(summary["results"]) == 3

    @pytest.mark.asyncio
    async def test_quality_gate_registry_get_results(self):
        """Test getting specific gate results."""
        registry = QualityGateRegistry()

        await registry.check_gate(EnumQualityGate.INPUT_VALIDATION, {})
        await registry.check_gate(EnumQualityGate.OUTPUT_VALIDATION, {})
        await registry.check_gate(EnumQualityGate.INPUT_VALIDATION, {})

        all_results = registry.get_results()
        assert len(all_results) == 3

        input_results = registry.get_results(EnumQualityGate.INPUT_VALIDATION)
        assert len(input_results) == 2
        assert all(r.gate == EnumQualityGate.INPUT_VALIDATION for r in input_results)


class TestPerformanceOverhead:
    """Test that models have minimal overhead."""

    def test_metric_creation_performance(self):
        """Test that creating metrics is fast."""
        import time

        start = time.time()
        for i in range(1000):
            metric = ModelPerformanceMetric(
                stage_name=f"stage_{i}",
                duration_ms=4500 + i,
                target_ms=5000,
            )
            _ = metric.performance_ratio
            _ = metric.is_within_threshold
        end = time.time()

        total_ms = (end - start) * 1000
        avg_ms = total_ms / 1000

        # Should be very fast
        assert avg_ms < 1, f"Metric creation too slow: {avg_ms:.3f}ms per metric"

    def test_metrics_collection_performance(self):
        """Test that metrics collection is fast."""
        import time

        collector = MetricsCollector()
        collector.set_threshold("test", target_ms=5000)

        start = time.time()
        for i in range(100):
            collector.record_stage_timing("test", duration_ms=4500 + i)
        end = time.time()

        total_ms = (end - start) * 1000
        avg_ms = total_ms / 100

        # Target: <10ms overhead per stage
        assert avg_ms < 10, f"Collection too slow: {avg_ms:.2f}ms per record"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
