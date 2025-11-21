#!/usr/bin/env python3
"""
Pure Aggregation Logic for Agent Performance Metrics.

This module contains pure functions for aggregating agent performance metrics
with threshold validation. No I/O operations - just data transformation.

Based on omninode_bridge MetricsAggregator patterns:
- Pure functions for aggregation (no I/O, no side effects)
- Streaming aggregation with percentile calculations
- Performance targets: >1000 events/second, <100ms aggregation latency

Performance Targets:
- >1000 events/second throughput
- <100ms aggregation latency for 1000 items
- Streaming aggregation with windowing
"""

import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..models.enum_performance_threshold import EnumPerformanceThreshold


class ThresholdBreach(BaseModel):
    """
    Threshold breach event.

    Records when actual performance exceeds defined thresholds.
    """

    threshold: EnumPerformanceThreshold = Field(
        ..., description="Threshold that was breached"
    )
    actual_value: float = Field(..., description="Actual measured value")
    threshold_value: float = Field(..., description="Threshold limit value")
    alert_threshold_value: float = Field(..., description="Alert threshold value")
    breach_percentage: float = Field(
        ..., description="Percentage over threshold (>100% is breach)"
    )
    breach_type: str = Field(
        ..., description="Breach severity: warning/critical/emergency"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Breach detection timestamp",
    )
    context: Dict[str, Any] = Field(
        default_factory=dict, description="Additional breach context"
    )

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


class StageTiming(BaseModel):
    """Stage timing record for aggregation."""

    stage_name: str = Field(..., description="Stage identifier")
    duration_ms: int = Field(..., description="Stage duration in milliseconds")
    target_ms: int = Field(..., description="Target threshold in milliseconds")
    threshold: Optional[EnumPerformanceThreshold] = Field(
        default=None, description="Performance threshold (if applicable)"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timing timestamp",
    )

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


class MetricsSummary(BaseModel):
    """
    Aggregated metrics summary.

    Provides percentile-based performance analysis like omninode_bridge aggregator.
    """

    total_timings: int = Field(..., description="Total timing records processed")
    total_breaches: int = Field(..., description="Total threshold breaches detected")

    # Duration statistics (milliseconds)
    avg_duration_ms: float = Field(..., description="Average duration")
    p50_duration_ms: float = Field(..., description="50th percentile (median)")
    p95_duration_ms: float = Field(..., description="95th percentile")
    p99_duration_ms: float = Field(..., description="99th percentile")
    min_duration_ms: float = Field(..., description="Minimum duration")
    max_duration_ms: float = Field(..., description="Maximum duration")

    # Performance ratio statistics
    avg_performance_ratio: float = Field(..., description="Average actual/target ratio")
    p50_performance_ratio: float = Field(..., description="Median actual/target ratio")
    p95_performance_ratio: float = Field(
        ..., description="95th percentile actual/target ratio"
    )
    p99_performance_ratio: float = Field(
        ..., description="99th percentile actual/target ratio"
    )

    # Breach statistics
    warning_breaches: int = Field(..., description="Warning level breaches (80-95%)")
    critical_breaches: int = Field(..., description="Critical level breaches (95-105%)")
    emergency_breaches: int = Field(..., description="Emergency breaches (>105%)")

    # Stage-specific metrics
    stage_metrics: Dict[str, Dict[str, float]] = Field(
        default_factory=dict, description="Per-stage aggregated metrics"
    )

    # Threshold-specific metrics
    threshold_metrics: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict, description="Per-threshold aggregated metrics"
    )

    # Window metadata
    window_start: datetime = Field(..., description="Metrics window start")
    window_end: datetime = Field(..., description="Metrics window end")
    aggregation_duration_ms: float = Field(
        default=0.0, description="Time taken to compute aggregation"
    )

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


class MetricsCollector:
    """
    Collect and aggregate performance metrics.

    Pure aggregation logic for streaming performance metrics following
    omninode_bridge patterns. All methods are pure functions (no I/O,
    no side effects) for easy testing and reasoning.

    Performance characteristics:
    - <100ms aggregation for 1000 items
    - Streaming percentile calculations
    - Threshold breach detection with severity levels
    """

    def __init__(self):
        """Initialize metrics collector."""
        self.stage_timings: List[StageTiming] = []
        self.threshold_breaches: List[ThresholdBreach] = []

    def record_stage_timing(
        self,
        stage_name: str,
        duration_ms: int,
        target_ms: int,
        threshold: Optional[EnumPerformanceThreshold] = None,
    ) -> bool:
        """
        Record stage timing and check against threshold.

        Args:
            stage_name: Stage identifier
            duration_ms: Actual stage duration in milliseconds
            target_ms: Target threshold in milliseconds
            threshold: Optional performance threshold enum

        Returns:
            True if within threshold, False if breached
        """
        timing = StageTiming(
            stage_name=stage_name,
            duration_ms=duration_ms,
            target_ms=target_ms,
            threshold=threshold,
        )
        self.stage_timings.append(timing)

        # Check threshold if provided
        if threshold is not None:
            return self.check_threshold(threshold, duration_ms)
        else:
            # Basic check against target_ms
            return duration_ms <= target_ms

    def check_threshold(
        self,
        threshold: EnumPerformanceThreshold,
        actual_value: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Check if actual value meets threshold.

        Implements multi-level breach detection:
        - Warning: 80-95% of threshold
        - Critical: 95-105% of threshold
        - Emergency: >105% of threshold

        Args:
            threshold: Performance threshold to check
            actual_value: Actual measured value (ms, MB, or ratio)
            context: Optional additional context

        Returns:
            True if within threshold, False if breached
        """
        # Get threshold values based on measurement type
        if threshold.threshold_ms > 0:
            threshold_value = threshold.threshold_ms
            alert_threshold_value = threshold.alert_threshold_ms
        elif threshold.threshold_mb > 0:
            threshold_value = threshold.threshold_mb
            alert_threshold_value = threshold.alert_threshold_mb
        elif threshold.threshold_ratio > 0:
            threshold_value = threshold.threshold_ratio
            alert_threshold_value = threshold.alert_threshold_ratio
        else:
            # No threshold defined
            return True

        # Calculate breach percentage
        breach_percentage = (actual_value / threshold_value) * 100

        # Determine breach type based on percentage
        if breach_percentage >= 105:
            breach_type = "emergency"
            breached = True
        elif breach_percentage >= 95:
            breach_type = "critical"
            breached = True
        elif breach_percentage >= 80:
            breach_type = "warning"
            breached = True
        else:
            breach_type = "none"
            breached = False

        # Record breach if detected
        if breached:
            breach = ThresholdBreach(
                threshold=threshold,
                actual_value=actual_value,
                threshold_value=threshold_value,
                alert_threshold_value=alert_threshold_value,
                breach_percentage=breach_percentage,
                breach_type=breach_type,
                context=context or {},
            )
            self.threshold_breaches.append(breach)

        return not breached

    def get_summary(self) -> MetricsSummary:
        """
        Get metrics summary with percentiles.

        Calculates comprehensive performance statistics using percentile
        analysis like omninode_bridge aggregator (p50, p95, p99).

        Returns:
            MetricsSummary with aggregated performance metrics
        """
        # Count breaches by severity (even if no stage timings)
        warning_breaches = sum(
            1 for b in self.threshold_breaches if b.breach_type == "warning"
        )
        critical_breaches = sum(
            1 for b in self.threshold_breaches if b.breach_type == "critical"
        )
        emergency_breaches = sum(
            1 for b in self.threshold_breaches if b.breach_type == "emergency"
        )

        # Compute per-threshold metrics (even if no stage timings)
        threshold_metrics = self._compute_threshold_metrics()

        if not self.stage_timings:
            # Return summary with breach data but no timing data
            window_start = datetime.now(timezone.utc)
            window_end = datetime.now(timezone.utc)
            if self.threshold_breaches:
                timestamps = [b.timestamp for b in self.threshold_breaches]
                window_start = min(timestamps)
                window_end = max(timestamps)

            return MetricsSummary(
                total_timings=0,
                total_breaches=len(self.threshold_breaches),
                avg_duration_ms=0.0,
                p50_duration_ms=0.0,
                p95_duration_ms=0.0,
                p99_duration_ms=0.0,
                min_duration_ms=0.0,
                max_duration_ms=0.0,
                avg_performance_ratio=0.0,
                p50_performance_ratio=0.0,
                p95_performance_ratio=0.0,
                p99_performance_ratio=0.0,
                warning_breaches=warning_breaches,
                critical_breaches=critical_breaches,
                emergency_breaches=emergency_breaches,
                threshold_metrics=threshold_metrics,
                window_start=window_start,
                window_end=window_end,
            )

        # Calculate duration statistics
        durations = [t.duration_ms for t in self.stage_timings]
        avg_duration = statistics.mean(durations)
        p50_duration = self._percentile(durations, 0.50)
        p95_duration = self._percentile(durations, 0.95)
        p99_duration = self._percentile(durations, 0.99)
        min_duration = min(durations)
        max_duration = max(durations)

        # Calculate performance ratio statistics
        ratios = [
            t.duration_ms / t.target_ms for t in self.stage_timings if t.target_ms > 0
        ]
        if ratios:
            avg_ratio = statistics.mean(ratios)
            p50_ratio = self._percentile(ratios, 0.50)
            p95_ratio = self._percentile(ratios, 0.95)
            p99_ratio = self._percentile(ratios, 0.99)
        else:
            avg_ratio = 0.0
            p50_ratio = 0.0
            p95_ratio = 0.0
            p99_ratio = 0.0

        # Compute per-stage metrics
        stage_metrics = self._compute_stage_metrics()

        # Get window bounds
        timestamps = [t.timestamp for t in self.stage_timings]
        window_start = min(timestamps)
        window_end = max(timestamps)

        return MetricsSummary(
            total_timings=len(self.stage_timings),
            total_breaches=len(self.threshold_breaches),
            avg_duration_ms=avg_duration,
            p50_duration_ms=p50_duration,
            p95_duration_ms=p95_duration,
            p99_duration_ms=p99_duration,
            min_duration_ms=min_duration,
            max_duration_ms=max_duration,
            avg_performance_ratio=avg_ratio,
            p50_performance_ratio=p50_ratio,
            p95_performance_ratio=p95_ratio,
            p99_performance_ratio=p99_ratio,
            warning_breaches=warning_breaches,
            critical_breaches=critical_breaches,
            emergency_breaches=emergency_breaches,
            stage_metrics=stage_metrics,
            threshold_metrics=threshold_metrics,
            window_start=window_start,
            window_end=window_end,
        )

    def _percentile(self, data: List[float], percentile: float) -> float:
        """
        Calculate percentile of data.

        Args:
            data: List of values
            percentile: Percentile (0.0-1.0)

        Returns:
            Percentile value
        """
        if not data:
            return 0.0

        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile)
        return sorted_data[min(index, len(sorted_data) - 1)]

    def _compute_stage_metrics(self) -> Dict[str, Dict[str, float]]:
        """
        Compute per-stage aggregated metrics.

        Returns:
            Dict mapping stage names to their aggregated metrics
        """
        from collections import defaultdict

        stage_data: Dict[str, List[StageTiming]] = defaultdict(list)

        for timing in self.stage_timings:
            stage_data[timing.stage_name].append(timing)

        stage_metrics = {}
        for stage_name, timings in stage_data.items():
            durations = [t.duration_ms for t in timings]
            ratios = [t.duration_ms / t.target_ms for t in timings if t.target_ms > 0]

            stage_metrics[stage_name] = {
                "total_executions": len(timings),
                "avg_duration_ms": statistics.mean(durations),
                "p50_duration_ms": self._percentile(durations, 0.50),
                "p95_duration_ms": self._percentile(durations, 0.95),
                "min_duration_ms": min(durations),
                "max_duration_ms": max(durations),
                "avg_performance_ratio": statistics.mean(ratios) if ratios else 0.0,
            }

        return stage_metrics

    def _compute_threshold_metrics(self) -> Dict[str, Dict[str, Any]]:
        """
        Compute per-threshold aggregated metrics.

        Returns:
            Dict mapping threshold names to their metrics
        """
        from collections import defaultdict

        threshold_data: Dict[str, List[ThresholdBreach]] = defaultdict(list)

        for breach in self.threshold_breaches:
            threshold_data[breach.threshold.value].append(breach)

        threshold_metrics = {}
        for threshold_name, breaches in threshold_data.items():
            breach_percentages = [b.breach_percentage for b in breaches]

            threshold_metrics[threshold_name] = {
                "total_breaches": len(breaches),
                "avg_breach_percentage": statistics.mean(breach_percentages),
                "max_breach_percentage": max(breach_percentages),
                "warning_count": sum(1 for b in breaches if b.breach_type == "warning"),
                "critical_count": sum(
                    1 for b in breaches if b.breach_type == "critical"
                ),
                "emergency_count": sum(
                    1 for b in breaches if b.breach_type == "emergency"
                ),
            }

        return threshold_metrics

    def reset(self) -> None:
        """Reset all collected metrics."""
        self.stage_timings.clear()
        self.threshold_breaches.clear()
