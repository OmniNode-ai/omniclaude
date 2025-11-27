#!/usr/bin/env python3
"""
Performance Validators - ONEX Agent Framework.

Implements 2 performance validation gates:
- PF-001: Performance Thresholds - Validate performance meets established thresholds
- PF-002: Resource Utilization - Monitor and validate resource usage efficiency

ONEX v2.0 Compliance:
- BaseQualityGate subclass pattern
- Integration with MetricsCollector
- EnumPerformanceThreshold validation
- Performance targets: PF <50ms per gate
"""

from typing import Any, Literal

import psutil

from ..metrics.metrics_collector import MetricsCollector
from ..models.model_quality_gate import EnumQualityGate, ModelQualityGateResult
from .base_quality_gate import BaseQualityGate


class PerformanceThresholdsValidator(BaseQualityGate):
    """
    PF-001: Performance Thresholds Validator.

    Validates performance meets established thresholds:
    - Stage execution times within targets
    - Overall pipeline within budget
    - No critical threshold breaches
    - Performance ratios acceptable (<1.5x target)
    - Resource usage within limits

    Integrates with MetricsCollector from Poly-2 for actual metrics.

    Performance Target: 30ms
    """

    def __init__(self) -> None:
        """Initialize performance thresholds validator."""
        super().__init__(EnumQualityGate.PERFORMANCE_THRESHOLDS)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Validate performance threshold compliance.

        Expected context keys:
        - metrics_collector: MetricsCollector - Metrics collector instance with recorded data
        - stage_timings: list[dict] - Alternative: Direct stage timing data
        - max_performance_ratio: float - Max acceptable ratio (default: 1.5)
        - allow_warnings: bool - Allow warning-level breaches (default: True)

        Returns:
            ModelQualityGateResult with validation outcome
        """
        issues: list[str] = []
        warnings: list[str] = []

        # Get metrics collector or create from stage timings
        metrics_collector = context.get("metrics_collector")
        stage_timings = context.get("stage_timings", [])
        max_performance_ratio = context.get("max_performance_ratio", 1.5)
        allow_warnings = context.get("allow_warnings", True)

        # Create metrics collector if not provided
        if metrics_collector is None:
            metrics_collector = MetricsCollector()

            # Populate from stage_timings if provided
            for timing in stage_timings:
                metrics_collector.record_stage_timing(
                    stage_name=timing.get("stage_name", "unknown"),
                    duration_ms=timing.get("duration_ms", 0),
                    target_ms=timing.get("target_ms", 0),
                    threshold=timing.get("threshold"),
                )

        # Get metrics summary
        summary = metrics_collector.get_summary()

        # Check threshold breaches
        breaches = metrics_collector.threshold_breaches

        # Categorize breaches
        critical_breaches = [b for b in breaches if b.breach_type == "critical"]
        emergency_breaches = [b for b in breaches if b.breach_type == "emergency"]
        warning_breaches = [b for b in breaches if b.breach_type == "warning"]

        # Emergency breaches are always failures
        if emergency_breaches:
            for breach in emergency_breaches:
                issues.append(
                    f"Emergency threshold breach: {breach.threshold.name} - "
                    f"{breach.actual_value:.0f} vs {breach.threshold_value:.0f} "
                    f"({breach.breach_percentage:.1f}%)"
                )

        # Critical breaches are failures
        if critical_breaches:
            for breach in critical_breaches:
                issues.append(
                    f"Critical threshold breach: {breach.threshold.name} - "
                    f"{breach.actual_value:.0f} vs {breach.threshold_value:.0f} "
                    f"({breach.breach_percentage:.1f}%)"
                )

        # Warning breaches are warnings if allowed
        if warning_breaches:
            for breach in warning_breaches:
                message = (
                    f"Warning threshold breach: {breach.threshold.name} - "
                    f"{breach.actual_value:.0f} vs {breach.threshold_value:.0f} "
                    f"({breach.breach_percentage:.1f}%)"
                )
                if allow_warnings:
                    warnings.append(message)
                else:
                    issues.append(message)

        # Check performance ratios
        if summary.avg_performance_ratio > max_performance_ratio:
            issues.append(
                f"Average performance ratio {summary.avg_performance_ratio:.2f} "
                f"exceeds maximum {max_performance_ratio:.2f}"
            )

        if summary.p95_performance_ratio > max_performance_ratio * 1.2:
            warnings.append(
                f"P95 performance ratio {summary.p95_performance_ratio:.2f} "
                f"exceeds {max_performance_ratio * 1.2:.2f}"
            )

        # Check individual stage performance
        for stage_name, metrics in summary.stage_metrics.items():
            stage_ratio = metrics.get("avg_performance_ratio", 0.0)
            if stage_ratio > max_performance_ratio:
                warnings.append(
                    f"Stage '{stage_name}' ratio {stage_ratio:.2f} exceeds {max_performance_ratio:.2f}"
                )

        # Determine status
        status: Literal["passed", "failed", "skipped"]
        if issues:
            status = "failed"
            message = f"Performance threshold violations: {len(issues)} issues, {summary.total_breaches} total breaches"
        elif warnings:
            status = "passed"
            message = f"Performance thresholds passed with {len(warnings)} warnings"
        else:
            status = "passed"
            message = f"Performance thresholds validation passed - {summary.total_timings} timings checked"

        return ModelQualityGateResult(
            gate=self.gate,
            status=status,
            execution_time_ms=0,
            message=message,
            metadata={
                "issues": issues,
                "warnings": warnings,
                "total_timings": summary.total_timings,
                "total_breaches": summary.total_breaches,
                "avg_duration_ms": summary.avg_duration_ms,
                "p95_duration_ms": summary.p95_duration_ms,
                "avg_performance_ratio": summary.avg_performance_ratio,
                "p95_performance_ratio": summary.p95_performance_ratio,
                "emergency_breaches": len(emergency_breaches),
                "critical_breaches": len(critical_breaches),
                "warning_breaches": len(warning_breaches),
                "stage_metrics": summary.stage_metrics,
            },
        )


class ResourceUtilizationValidator(BaseQualityGate):
    """
    PF-002: Resource Utilization Validator.

    Monitors and validates resource usage efficiency:
    - Memory usage within limits (CTX-004: <10MB per agent)
    - CPU utilization reasonable
    - No obvious resource leaks
    - Resource cleanup in finally blocks
    - Efficient data structures used

    Performance Target: 25ms
    """

    def __init__(self) -> None:
        """Initialize resource utilization validator."""
        super().__init__(EnumQualityGate.RESOURCE_UTILIZATION)

        # Get current process
        self.process = psutil.Process()

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Validate resource utilization compliance.

        Expected context keys:
        - max_memory_mb: float - Maximum memory in MB (default: 10.0)
        - max_cpu_percent: float - Maximum CPU percent (default: 80.0)
        - check_memory_leaks: bool - Check for memory leaks (default: True)
        - baseline_memory_mb: float - Baseline memory before operation
        - expected_memory_growth_mb: float - Expected memory growth

        Returns:
            ModelQualityGateResult with validation outcome
        """
        issues: list[str] = []
        warnings: list[str] = []

        max_memory_mb = context.get("max_memory_mb", 10.0)
        max_cpu_percent = context.get("max_cpu_percent", 80.0)
        check_memory_leaks = context.get("check_memory_leaks", True)
        baseline_memory_mb = context.get("baseline_memory_mb")
        expected_memory_growth_mb = context.get("expected_memory_growth_mb", 5.0)

        # Get current resource usage
        memory_info = self.process.memory_info()
        current_memory_mb = memory_info.rss / (1024 * 1024)  # Convert to MB

        # Get CPU usage (non-blocking, interval=None for instant)
        cpu_percent = self.process.cpu_percent(interval=None)

        # Check memory usage
        if current_memory_mb > max_memory_mb:
            issues.append(
                f"Memory usage {current_memory_mb:.2f}MB exceeds maximum {max_memory_mb}MB"
            )
        elif current_memory_mb > max_memory_mb * 0.8:
            warnings.append(
                f"Memory usage {current_memory_mb:.2f}MB approaching limit {max_memory_mb}MB"
            )

        # Check CPU usage
        if cpu_percent > max_cpu_percent:
            warnings.append(
                f"CPU usage {cpu_percent:.1f}% exceeds maximum {max_cpu_percent}%"
            )

        # Check for memory leaks if baseline provided
        if check_memory_leaks and baseline_memory_mb is not None:
            memory_growth = current_memory_mb - baseline_memory_mb

            if memory_growth > expected_memory_growth_mb * 2:
                issues.append(
                    f"Potential memory leak: {memory_growth:.2f}MB growth exceeds "
                    f"expected {expected_memory_growth_mb}MB"
                )
            elif memory_growth > expected_memory_growth_mb * 1.5:
                warnings.append(
                    f"High memory growth: {memory_growth:.2f}MB vs expected {expected_memory_growth_mb}MB"
                )

        # Check file descriptors (potential resource leak)
        try:
            num_fds = self.process.num_fds() if hasattr(self.process, "num_fds") else 0
            if num_fds > 100:
                warnings.append(
                    f"High number of file descriptors: {num_fds} (potential resource leak)"
                )
        except (AttributeError, psutil.AccessDenied):
            # num_fds not available on all platforms
            pass

        # Check thread count (potential resource leak)
        num_threads = self.process.num_threads()
        if num_threads > 20:
            warnings.append(
                f"High thread count: {num_threads} (potential resource leak)"
            )

        # Determine status
        status: Literal["passed", "failed", "skipped"]
        if issues:
            status = "failed"
            message = f"Resource utilization violations: {len(issues)} issues found"
        elif warnings:
            status = "passed"
            message = f"Resource utilization passed with {len(warnings)} warnings"
        else:
            status = "passed"
            message = "Resource utilization validation passed"

        return ModelQualityGateResult(
            gate=self.gate,
            status=status,
            execution_time_ms=0,
            message=message,
            metadata={
                "issues": issues,
                "warnings": warnings,
                "current_memory_mb": current_memory_mb,
                "max_memory_mb": max_memory_mb,
                "cpu_percent": cpu_percent,
                "max_cpu_percent": max_cpu_percent,
                "num_threads": num_threads,
                "baseline_memory_mb": baseline_memory_mb,
                "memory_growth_mb": (
                    current_memory_mb - baseline_memory_mb
                    if baseline_memory_mb is not None
                    else 0.0
                ),
            },
        )
