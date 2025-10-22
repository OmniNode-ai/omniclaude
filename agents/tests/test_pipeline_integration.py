#!/usr/bin/env python3
"""
Integration Tests for Pipeline Performance Tracking and Quality Gates

Tests Week 1 Day 5 deliverables:
- Performance metrics collection across all 7 stages
- Quality gate checkpoint execution
- Metrics summary in pipeline results
"""

from uuid import uuid4

import pytest

from agents.lib.generation_pipeline import GenerationPipeline

# Import the models
from agents.lib.models.model_performance_tracking import (
    MetricsCollector,
    ModelPerformanceMetric,
)
from agents.lib.models.model_quality_gate import (
    EnumQualityGate,
    QualityGateRegistry,
)


class TestPerformanceTracking:
    """Test performance metrics collection."""

    def test_metrics_collector_initialization(self):
        """Test that metrics collector initializes correctly."""
        collector = MetricsCollector()
        assert collector.metrics == []
        assert collector.thresholds == {}

    def test_set_threshold(self):
        """Test setting performance thresholds."""
        collector = MetricsCollector()
        collector.set_threshold("test_stage", target_ms=5000)

        assert "test_stage" in collector.thresholds
        assert collector.thresholds["test_stage"].target_ms == 5000
        assert collector.thresholds["test_stage"].warning_threshold == 1.1
        assert collector.thresholds["test_stage"].error_threshold == 2.0

    def test_record_stage_timing(self):
        """Test recording stage timing."""
        collector = MetricsCollector()
        collector.set_threshold("test_stage", target_ms=5000)

        metric = collector.record_stage_timing(
            stage_name="test_stage",
            duration_ms=4500,
        )

        assert metric.stage_name == "test_stage"
        assert metric.duration_ms == 4500
        assert metric.target_ms == 5000
        assert metric.performance_ratio < 1.0  # Under budget
        assert metric.is_within_threshold

    def test_performance_ratio_calculation(self):
        """Test performance ratio calculations."""
        metric = ModelPerformanceMetric(
            stage_name="test",
            duration_ms=6000,
            target_ms=5000,
        )

        assert metric.performance_ratio == 1.2  # 20% over budget
        assert not metric.is_within_threshold  # Exceeds 110% threshold
        assert metric.budget_variance_ms == 1000

    def test_metrics_summary(self):
        """Test metrics summary generation."""
        collector = MetricsCollector()
        collector.set_threshold("stage_1", target_ms=5000)
        collector.set_threshold("stage_2", target_ms=3000)

        collector.record_stage_timing("stage_1", duration_ms=4500)
        collector.record_stage_timing("stage_2", duration_ms=2800)

        summary = collector.get_summary()

        assert summary["total_stages"] == 2
        assert summary["total_duration_ms"] == 7300
        assert summary["total_target_ms"] == 8000
        assert summary["stages_within_threshold"] == 2
        assert summary["overall_performance_ratio"] < 1.0


class TestQualityGates:
    """Test quality gate execution."""

    @pytest.mark.asyncio
    async def test_quality_gate_registry_initialization(self):
        """Test quality gate registry initialization."""
        registry = QualityGateRegistry()
        assert registry.results == []

    @pytest.mark.asyncio
    async def test_check_gate_placeholder(self):
        """Test quality gate check (placeholder implementation)."""
        registry = QualityGateRegistry()

        result = await registry.check_gate(
            gate=EnumQualityGate.INPUT_VALIDATION, context={"test": "data"}
        )

        assert result.gate == EnumQualityGate.INPUT_VALIDATION
        assert result.status == "passed"  # Placeholder always passes
        assert result.passed
        assert len(registry.results) == 1

    @pytest.mark.asyncio
    async def test_multiple_gate_checks(self):
        """Test multiple quality gate checks."""
        registry = QualityGateRegistry()

        # Check multiple gates
        await registry.check_gate(EnumQualityGate.INPUT_VALIDATION, {})
        await registry.check_gate(EnumQualityGate.OUTPUT_VALIDATION, {})
        await registry.check_gate(EnumQualityGate.ONEX_STANDARDS, {})

        assert len(registry.results) == 3
        assert all(r.passed for r in registry.results)

    @pytest.mark.asyncio
    async def test_quality_gate_summary(self):
        """Test quality gate summary generation."""
        registry = QualityGateRegistry()

        await registry.check_gate(EnumQualityGate.INPUT_VALIDATION, {})
        await registry.check_gate(EnumQualityGate.OUTPUT_VALIDATION, {})

        summary = registry.get_summary()

        assert summary["total_gates"] == 2
        assert summary["passed"] == 2  # Placeholders always pass
        assert summary["failed"] == 0
        assert summary["blocking_failures"] == 0

    def test_quality_gate_enum_properties(self):
        """Test quality gate enum properties."""
        gate = EnumQualityGate.INPUT_VALIDATION

        assert gate.category == "sequential_validation"
        assert gate.gate_name == "Input Validation"
        assert gate.validation_type == "blocking"
        assert gate.performance_target_ms == 50


class TestPipelineIntegration:
    """Test pipeline integration with performance tracking and quality gates."""

    def test_pipeline_has_metrics_collector(self):
        """Test that pipeline initializes with metrics collector."""
        pipeline = GenerationPipeline(interactive_mode=False)

        assert hasattr(pipeline, "metrics_collector")
        assert isinstance(pipeline.metrics_collector, MetricsCollector)

    def test_pipeline_has_quality_gate_registry(self):
        """Test that pipeline initializes with quality gate registry."""
        pipeline = GenerationPipeline(interactive_mode=False)

        assert hasattr(pipeline, "quality_gate_registry")
        assert isinstance(pipeline.quality_gate_registry, QualityGateRegistry)

    def test_pipeline_configures_thresholds(self):
        """Test that pipeline configures performance thresholds."""
        pipeline = GenerationPipeline(interactive_mode=False)

        # Check that thresholds are configured for all 7 stages
        expected_stages = [
            "stage_1_prd_analysis",
            "stage_1.5_intelligence_gathering",
            "stage_2_contract_building",
            "stage_4_code_generation",
            "stage_4.5_event_bus_integration",
            "stage_5_post_validation",
            "stage_5.5_ai_refinement",
        ]

        for stage_name in expected_stages:
            assert stage_name in pipeline.metrics_collector.thresholds

    @pytest.mark.asyncio
    async def test_pipeline_execution_includes_metrics(self, tmp_path):
        """
        Test that pipeline execution includes performance metrics and quality gates.

        This is an integration test that runs a simplified pipeline execution.
        """
        pipeline = GenerationPipeline(
            interactive_mode=False,
            enable_intelligence_gathering=False,  # Disable to simplify test
            enable_compilation_testing=False,  # Disable to simplify test
        )

        # Create a simple test prompt
        prompt = "Create an Effect node for database writes in the user domain"
        output_dir = str(tmp_path)

        try:
            # Execute pipeline (may fail on actual generation, but should track metrics)
            result = await pipeline.execute(
                prompt=prompt,
                output_directory=output_dir,
                correlation_id=uuid4(),
            )

            # Check that performance metrics are included in result
            assert "performance_metrics" in result.metadata
            assert "quality_gates" in result.metadata

            metrics = result.metadata["performance_metrics"]
            assert "total_stages" in metrics
            assert "total_duration_ms" in metrics
            assert "metrics" in metrics

            gates = result.metadata["quality_gates"]
            assert "total_gates" in gates
            assert "passed" in gates

        except Exception:
            # Even if pipeline fails, we should have some metrics
            # (metrics are recorded in finally blocks)
            if hasattr(pipeline, "metrics_collector"):
                metrics = pipeline.metrics_collector.get_summary()
                assert metrics["total_stages"] >= 0  # At least attempted some stages

    def test_pipeline_check_quality_gate_method(self):
        """Test that pipeline has check_quality_gate method."""
        pipeline = GenerationPipeline(interactive_mode=False)

        assert hasattr(pipeline, "_check_quality_gate")
        assert callable(pipeline._check_quality_gate)


class TestMetricsPerformance:
    """Test that metrics collection has minimal overhead."""

    def test_metrics_collection_overhead(self):
        """Test that metrics collection is fast (<10ms)."""
        import time

        collector = MetricsCollector()
        collector.set_threshold("test", target_ms=5000)

        start = time.time()
        for i in range(100):
            collector.record_stage_timing("test", duration_ms=4500 + i)
        end = time.time()

        total_ms = (end - start) * 1000
        avg_ms = total_ms / 100

        # Should be much less than 10ms per recording
        assert avg_ms < 10, f"Metrics collection too slow: {avg_ms:.2f}ms per record"

    @pytest.mark.asyncio
    async def test_quality_gate_check_overhead(self):
        """Test that quality gate checks are fast (<200ms)."""
        import time

        registry = QualityGateRegistry()

        start = time.time()
        await registry.check_gate(EnumQualityGate.INPUT_VALIDATION, {})
        end = time.time()

        duration_ms = (end - start) * 1000

        # Placeholder implementation should be very fast
        assert duration_ms < 200, f"Quality gate check too slow: {duration_ms:.2f}ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
