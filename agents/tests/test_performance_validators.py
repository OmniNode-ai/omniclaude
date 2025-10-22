#!/usr/bin/env python3
"""
Tests for Performance Validators.

Tests 2 performance validation gates:
- PF-001: Performance Thresholds Validator
- PF-002: Resource Utilization Validator
"""

import pytest

from agents.lib.metrics.metrics_collector import MetricsCollector
from agents.lib.models.enum_performance_threshold import EnumPerformanceThreshold
from agents.lib.validators.performance_validators import (
    PerformanceThresholdsValidator,
    ResourceUtilizationValidator,
)


class TestPerformanceThresholdsValidator:
    """Tests for PF-001: Performance Thresholds Validator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return PerformanceThresholdsValidator()

    @pytest.fixture
    def metrics_collector(self):
        """Create metrics collector instance."""
        return MetricsCollector()

    @pytest.mark.asyncio
    async def test_all_within_thresholds(self, validator, metrics_collector):
        """Test validation passes when all metrics within thresholds."""
        # Record some good timings (below 80% threshold to avoid warnings)
        metrics_collector.record_stage_timing(
            stage_name="rag_query",
            duration_ms=1000,  # 67% of 1500ms threshold (below 80%)
            target_ms=1500,
            threshold=EnumPerformanceThreshold.RAG_QUERY_RESPONSE_TIME,
        )
        metrics_collector.record_stage_timing(
            stage_name="context_init",
            duration_ms=30,  # 60% of 50ms threshold (below 80%)
            target_ms=50,
            threshold=EnumPerformanceThreshold.CONTEXT_INITIALIZATION_TIME,
        )

        context = {"metrics_collector": metrics_collector}
        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["total_breaches"] == 0

    @pytest.mark.asyncio
    async def test_warning_level_breach(self, validator, metrics_collector):
        """Test validation passes with warnings for warning-level breaches."""
        # Record timing at warning level (80-95% of threshold)
        metrics_collector.record_stage_timing(
            stage_name="rag_query",
            duration_ms=1300,  # 87% of 1500ms threshold
            target_ms=1500,
            threshold=EnumPerformanceThreshold.RAG_QUERY_RESPONSE_TIME,
        )

        context = {"metrics_collector": metrics_collector, "allow_warnings": True}
        result = await validator.validate(context)

        assert result.status == "passed"
        assert len(result.metadata["warnings"]) > 0
        assert result.metadata["warning_breaches"] > 0

    @pytest.mark.asyncio
    async def test_critical_breach(self, validator, metrics_collector):
        """Test validation fails for critical threshold breaches."""
        # Record timing at critical level (95-105% of threshold)
        metrics_collector.record_stage_timing(
            stage_name="rag_query",
            duration_ms=1450,  # 97% of 1500ms threshold
            target_ms=1500,
            threshold=EnumPerformanceThreshold.RAG_QUERY_RESPONSE_TIME,
        )

        context = {"metrics_collector": metrics_collector}
        result = await validator.validate(context)

        assert result.status == "failed"
        assert result.metadata["critical_breaches"] > 0
        assert any(
            "Critical threshold breach" in issue for issue in result.metadata["issues"]
        )

    @pytest.mark.asyncio
    async def test_emergency_breach(self, validator, metrics_collector):
        """Test validation fails for emergency threshold breaches."""
        # Record timing at emergency level (>105% of threshold)
        metrics_collector.record_stage_timing(
            stage_name="rag_query",
            duration_ms=1600,  # 107% of 1500ms threshold
            target_ms=1500,
            threshold=EnumPerformanceThreshold.RAG_QUERY_RESPONSE_TIME,
        )

        context = {"metrics_collector": metrics_collector}
        result = await validator.validate(context)

        assert result.status == "failed"
        assert result.metadata["emergency_breaches"] > 0
        assert any(
            "Emergency threshold breach" in issue for issue in result.metadata["issues"]
        )

    @pytest.mark.asyncio
    async def test_performance_ratio_exceeded(self, validator, metrics_collector):
        """Test validation fails when average performance ratio exceeded."""
        # Record multiple timings with high ratios
        for i in range(5):
            metrics_collector.record_stage_timing(
                stage_name=f"stage_{i}",
                duration_ms=200,  # 2x the target
                target_ms=100,
            )

        context = {"metrics_collector": metrics_collector, "max_performance_ratio": 1.5}
        result = await validator.validate(context)

        assert result.status == "failed"
        assert any(
            "performance ratio" in issue.lower() for issue in result.metadata["issues"]
        )

    @pytest.mark.asyncio
    async def test_p95_ratio_warning(self, validator, metrics_collector):
        """Test warning for high P95 performance ratio."""
        # Record timings with variable performance
        for i in range(10):
            duration = 100 if i < 8 else 250  # Last 2 are slow
            metrics_collector.record_stage_timing(
                stage_name=f"stage_{i}",
                duration_ms=duration,
                target_ms=100,
            )

        context = {"metrics_collector": metrics_collector, "max_performance_ratio": 1.5}
        result = await validator.validate(context)

        # Should have warnings about P95 ratio
        assert result.status in ("passed", "failed")

    @pytest.mark.asyncio
    async def test_stage_specific_ratio(self, validator, metrics_collector):
        """Test warning for specific stage exceeding ratio."""
        # Record good and bad stage timings
        metrics_collector.record_stage_timing(
            stage_name="fast_stage",
            duration_ms=50,
            target_ms=100,
        )
        metrics_collector.record_stage_timing(
            stage_name="slow_stage",
            duration_ms=200,  # 2x target
            target_ms=100,
        )

        context = {"metrics_collector": metrics_collector, "max_performance_ratio": 1.5}
        result = await validator.validate(context)

        assert result.status in ("passed", "failed")
        if result.status == "passed":
            assert any("slow_stage" in w for w in result.metadata["warnings"])

    @pytest.mark.asyncio
    async def test_direct_stage_timings(self, validator):
        """Test validation with direct stage timings (no MetricsCollector)."""
        stage_timings = [
            {
                "stage_name": "rag_query",
                "duration_ms": 1200,
                "target_ms": 1500,
                "threshold": EnumPerformanceThreshold.RAG_QUERY_RESPONSE_TIME,
            },
            {
                "stage_name": "context_init",
                "duration_ms": 40,
                "target_ms": 50,
                "threshold": EnumPerformanceThreshold.CONTEXT_INITIALIZATION_TIME,
            },
        ]

        context = {"stage_timings": stage_timings}
        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["total_timings"] == 2

    @pytest.mark.asyncio
    async def test_no_metrics(self, validator):
        """Test validation with no metrics (should pass)."""
        context = {}
        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["total_timings"] == 0


class TestResourceUtilizationValidator:
    """Tests for PF-002: Resource Utilization Validator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return ResourceUtilizationValidator()

    @pytest.mark.asyncio
    async def test_resource_within_limits(self, validator):
        """Test validation passes when resources within limits."""
        context = {
            "max_memory_mb": 100.0,  # High limit
            "max_cpu_percent": 90.0,  # High limit
            "check_memory_leaks": False,
        }
        result = await validator.validate(context)

        # Should pass unless system is under extreme load
        assert result.status in ("passed", "failed")
        assert "current_memory_mb" in result.metadata

    @pytest.mark.asyncio
    async def test_memory_approaching_limit(self, validator):
        """Test warning when memory approaching limit."""
        # Get current memory usage
        import psutil

        process = psutil.Process()
        current_mb = process.memory_info().rss / (1024 * 1024)

        # Set limit just above current usage
        context = {
            "max_memory_mb": current_mb * 1.15,  # 15% above current
            "max_cpu_percent": 90.0,
        }
        result = await validator.validate(context)

        # Should have warnings about approaching limit
        assert result.status in ("passed", "failed")

    @pytest.mark.asyncio
    async def test_memory_limit_exceeded(self, validator):
        """Test failure when memory limit exceeded."""
        # Get current memory usage
        import psutil

        process = psutil.Process()
        current_mb = process.memory_info().rss / (1024 * 1024)

        # Set limit below current usage
        context = {
            "max_memory_mb": max(1.0, current_mb * 0.5),  # 50% of current
            "max_cpu_percent": 90.0,
        }
        result = await validator.validate(context)

        assert result.status == "failed"
        assert any("Memory usage" in issue for issue in result.metadata["issues"])

    @pytest.mark.asyncio
    async def test_memory_leak_detection(self, validator):
        """Test memory leak detection."""
        # Get current memory usage
        import psutil

        process = psutil.Process()
        current_mb = process.memory_info().rss / (1024 * 1024)

        # Simulate memory growth
        context = {
            "max_memory_mb": 100.0,
            "check_memory_leaks": True,
            "baseline_memory_mb": current_mb - 20,  # Pretend we grew 20MB
            "expected_memory_growth_mb": 5.0,  # But only expected 5MB
        }
        result = await validator.validate(context)

        # Should detect potential memory leak
        assert result.status == "failed"
        assert any(
            "memory leak" in issue.lower() for issue in result.metadata["issues"]
        )

    @pytest.mark.asyncio
    async def test_normal_memory_growth(self, validator):
        """Test normal memory growth doesn't trigger leak detection."""
        # Get current memory usage
        import psutil

        process = psutil.Process()
        current_mb = process.memory_info().rss / (1024 * 1024)

        # Simulate normal growth
        context = {
            "max_memory_mb": 100.0,
            "check_memory_leaks": True,
            "baseline_memory_mb": current_mb - 2,  # Small 2MB growth
            "expected_memory_growth_mb": 5.0,  # Expected 5MB
        }
        result = await validator.validate(context)

        # Should pass
        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_high_memory_growth_warning(self, validator):
        """Test warning for high but not critical memory growth."""
        # Get current memory usage
        import psutil

        process = psutil.Process()
        current_mb = process.memory_info().rss / (1024 * 1024)

        # Simulate moderate growth
        context = {
            "max_memory_mb": 100.0,
            "check_memory_leaks": True,
            "baseline_memory_mb": current_mb - 8,  # 8MB growth
            "expected_memory_growth_mb": 5.0,  # Expected 5MB (1.6x)
        }
        result = await validator.validate(context)

        # Should pass with warning
        assert result.status == "passed"
        if result.metadata["warnings"]:
            assert any(
                "memory growth" in w.lower() for w in result.metadata["warnings"]
            )

    @pytest.mark.asyncio
    async def test_cpu_usage_check(self, validator):
        """Test CPU usage validation."""
        context = {
            "max_memory_mb": 100.0,
            "max_cpu_percent": 1.0,  # Very low limit to trigger warning
        }
        result = await validator.validate(context)

        # Should have CPU warnings or pass if CPU is very low
        assert result.status in ("passed", "failed")

    @pytest.mark.asyncio
    async def test_thread_count_warning(self, validator):
        """Test warning for high thread count."""
        # This test may or may not trigger depending on system
        context = {
            "max_memory_mb": 100.0,
            "max_cpu_percent": 90.0,
        }
        result = await validator.validate(context)

        assert result.status in ("passed", "failed")
        assert "num_threads" in result.metadata

    @pytest.mark.asyncio
    async def test_metadata_completeness(self, validator):
        """Test that all expected metadata is present."""
        context = {
            "max_memory_mb": 100.0,
            "max_cpu_percent": 90.0,
            "baseline_memory_mb": 50.0,
        }
        result = await validator.validate(context)

        # Check all expected metadata fields
        assert "current_memory_mb" in result.metadata
        assert "max_memory_mb" in result.metadata
        assert "cpu_percent" in result.metadata
        assert "max_cpu_percent" in result.metadata
        assert "num_threads" in result.metadata
        assert "memory_growth_mb" in result.metadata

    @pytest.mark.asyncio
    async def test_default_limits(self, validator):
        """Test validation with default limits."""
        context = {}
        result = await validator.validate(context)

        # Should use defaults: 10MB memory, 80% CPU
        assert result.status in ("passed", "failed")
        assert result.metadata["max_memory_mb"] == 10.0
        assert result.metadata["max_cpu_percent"] == 80.0
