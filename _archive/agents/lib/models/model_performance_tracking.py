#!/usr/bin/env python3
"""
Performance Tracking Models - Week 1 MVP Day 5 (Poly-1)

Provides real-time performance monitoring for agent pipeline stages.
Tracks timing, thresholds, and performance ratios with <10ms overhead.

Architecture:
- ModelPerformanceMetric: Individual stage timing measurement
- ModelPerformanceThreshold: Target vs actual comparison
- MetricsCollector: Centralized metrics aggregation
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ModelPerformanceMetric:
    """
    Individual performance measurement for a pipeline stage.

    Tracks timing, threshold compliance, and metadata for analysis.
    """

    stage_name: str
    """Pipeline stage identifier (e.g., 'stage_1_prd_analysis')"""

    duration_ms: int
    """Actual execution time in milliseconds"""

    target_ms: int
    """Performance target in milliseconds"""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When measurement was recorded"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional context (e.g., input size, complexity)"""

    @property
    def performance_ratio(self) -> float:
        """
        Calculate performance ratio (actual/target).

        Returns:
            <1.0: Under budget (good)
            =1.0: Exactly on target
            >1.0: Over budget (needs optimization)
        """
        if self.target_ms == 0:
            return 0.0
        return self.duration_ms / self.target_ms

    @property
    def is_within_threshold(self) -> bool:
        """Check if execution was within 110% of target."""
        return self.performance_ratio <= 1.1

    @property
    def budget_variance_ms(self) -> int:
        """Calculate variance from target (negative = under budget)."""
        return self.duration_ms - self.target_ms

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "stage_name": self.stage_name,
            "duration_ms": self.duration_ms,
            "target_ms": self.target_ms,
            "performance_ratio": self.performance_ratio,
            "is_within_threshold": self.is_within_threshold,
            "budget_variance_ms": self.budget_variance_ms,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class ModelPerformanceThreshold:
    """
    Performance threshold configuration for a stage.

    Defines target timing and warning/error thresholds.
    """

    stage_name: str
    """Stage identifier"""

    target_ms: int
    """Target execution time"""

    warning_threshold: float = 1.1
    """Trigger warning at 110% of target"""

    error_threshold: float = 2.0
    """Trigger error at 200% of target"""

    def check_compliance(self, actual_ms: int) -> str:
        """
        Check if actual timing meets thresholds.

        Returns:
            'success': Within target
            'warning': Exceeds warning threshold
            'error': Exceeds error threshold
        """
        ratio = actual_ms / self.target_ms if self.target_ms > 0 else 0.0

        if ratio >= self.error_threshold:
            return "error"
        elif ratio >= self.warning_threshold:
            return "warning"
        else:
            return "success"


class MetricsCollector:
    """
    Centralized performance metrics collection and aggregation.

    Usage:
        collector = MetricsCollector()
        collector.record_stage_timing("stage_1", duration_ms=4500, target_ms=5000)
        summary = collector.get_summary()
    """

    def __init__(self):
        """Initialize metrics collector."""
        self.metrics: list[ModelPerformanceMetric] = []
        self.thresholds: dict[str, ModelPerformanceThreshold] = {}

    def set_threshold(
        self,
        stage_name: str,
        target_ms: int,
        warning_threshold: float = 1.1,
        error_threshold: float = 2.0,
    ) -> None:
        """
        Configure performance threshold for a stage.

        Args:
            stage_name: Stage identifier
            target_ms: Target execution time
            warning_threshold: Warning multiplier (default 1.1 = 110%)
            error_threshold: Error multiplier (default 2.0 = 200%)
        """
        self.thresholds[stage_name] = ModelPerformanceThreshold(
            stage_name=stage_name,
            target_ms=target_ms,
            warning_threshold=warning_threshold,
            error_threshold=error_threshold,
        )

    def record_stage_timing(
        self,
        stage_name: str,
        duration_ms: int,
        target_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ModelPerformanceMetric:
        """
        Record timing for a pipeline stage.

        Args:
            stage_name: Stage identifier
            duration_ms: Actual execution time
            target_ms: Override target (uses threshold if not provided)
            metadata: Additional context

        Returns:
            Created performance metric
        """
        # Use threshold target if not provided
        if target_ms is None:
            if stage_name in self.thresholds:
                target_ms = self.thresholds[stage_name].target_ms
            else:
                target_ms = 0  # No target set

        metric = ModelPerformanceMetric(
            stage_name=stage_name,
            duration_ms=duration_ms,
            target_ms=target_ms,
            metadata=metadata or {},
        )

        self.metrics.append(metric)
        return metric

    def get_summary(self) -> dict[str, Any]:
        """
        Generate comprehensive metrics summary.

        Returns:
            Dictionary with:
            - total_stages: Number of stages measured
            - total_duration_ms: Total execution time
            - total_target_ms: Total target time
            - overall_performance_ratio: Aggregate ratio
            - stages_within_threshold: Count of compliant stages
            - metrics: List of individual metrics
        """
        if not self.metrics:
            return {
                "total_stages": 0,
                "total_duration_ms": 0,
                "total_target_ms": 0,
                "overall_performance_ratio": 0.0,
                "stages_within_threshold": 0,
                "metrics": [],
            }

        total_duration = sum(m.duration_ms for m in self.metrics)
        total_target = sum(m.target_ms for m in self.metrics)

        return {
            "total_stages": len(self.metrics),
            "total_duration_ms": total_duration,
            "total_target_ms": total_target,
            "overall_performance_ratio": (
                total_duration / total_target if total_target > 0 else 0.0
            ),
            "stages_within_threshold": sum(
                1 for m in self.metrics if m.is_within_threshold
            ),
            "metrics": [m.to_dict() for m in self.metrics],
        }

    def get_stage_metrics(self, stage_name: str) -> list[ModelPerformanceMetric]:
        """Get all metrics for a specific stage."""
        return [m for m in self.metrics if m.stage_name == stage_name]

    def clear(self) -> None:
        """Clear all collected metrics."""
        self.metrics.clear()
