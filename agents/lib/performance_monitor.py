"""
Real-time Performance Monitoring

Monitors workflow performance in real-time, tracks metrics, and alerts on
performance degradation. Provides insights for optimization.
"""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional


class PerformanceLevel(Enum):
    """Performance level indicators."""

    EXCELLENT = "excellent"  # < 50th percentile
    GOOD = "good"  # 50-75th percentile
    AVERAGE = "average"  # 75-90th percentile
    POOR = "poor"  # 90-95th percentile
    CRITICAL = "critical"  # > 95th percentile


@dataclass
class PerformanceThreshold:
    """Performance threshold configuration."""

    phase: str
    warning_duration_ms: float
    critical_duration_ms: float
    min_success_rate: float = 0.8
    max_error_rate: float = 0.2


@dataclass
class PerformanceMetrics:
    """Performance metrics for a specific phase."""

    phase: str
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float = float("inf")
    max_duration_ms: float = 0.0
    avg_duration_ms: float = 0.0
    p50_duration_ms: float = 0.0
    p90_duration_ms: float = 0.0
    p95_duration_ms: float = 0.0
    p99_duration_ms: float = 0.0
    recent_durations: deque = field(default_factory=lambda: deque(maxlen=100))
    error_types: Dict[str, int] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.now)


class PerformanceMonitor:
    """
    Real-time performance monitoring for workflow phases.

    Features:
    - Real-time metrics tracking
    - Performance threshold monitoring
    - Alert generation
    - Historical trend analysis
    - Performance level classification
    """

    def __init__(self):
        self.metrics: Dict[str, PerformanceMetrics] = {}
        self.thresholds: Dict[str, PerformanceThreshold] = {}
        self.alerts: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()

        # Default thresholds for common phases
        self._setup_default_thresholds()

    def _setup_default_thresholds(self):
        """Setup default performance thresholds."""
        default_thresholds = {
            "CONTEXT_GATHERING": PerformanceThreshold(
                phase="CONTEXT_GATHERING", warning_duration_ms=200.0, critical_duration_ms=500.0, min_success_rate=0.9
            ),
            "QUORUM_VALIDATION": PerformanceThreshold(
                phase="QUORUM_VALIDATION", warning_duration_ms=2000.0, critical_duration_ms=5000.0, min_success_rate=0.8
            ),
            "TASK_ARCHITECTURE": PerformanceThreshold(
                phase="TASK_ARCHITECTURE",
                warning_duration_ms=1000.0,
                critical_duration_ms=3000.0,
                min_success_rate=0.85,
            ),
            "PARALLEL_EXECUTION": PerformanceThreshold(
                phase="PARALLEL_EXECUTION",
                warning_duration_ms=5000.0,
                critical_duration_ms=15000.0,
                min_success_rate=0.75,
            ),
        }

        for phase, threshold in default_thresholds.items():
            self.thresholds[phase] = threshold

    async def track_phase_performance(
        self,
        phase: str,
        duration_ms: float,
        success: bool,
        error_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Track performance metrics for a phase execution.

        Args:
            phase: Phase name
            duration_ms: Execution duration in milliseconds
            success: Whether execution was successful
            error_type: Type of error if failed
            metadata: Additional metadata
        """
        async with self._lock:
            if phase not in self.metrics:
                self.metrics[phase] = PerformanceMetrics(phase=phase)

            metrics = self.metrics[phase]

            # Update counters
            metrics.total_executions += 1
            if success:
                metrics.successful_executions += 1
            else:
                metrics.failed_executions += 1
                if error_type:
                    metrics.error_types[error_type] = metrics.error_types.get(error_type, 0) + 1

            # Update duration statistics
            metrics.total_duration_ms += duration_ms
            metrics.min_duration_ms = min(metrics.min_duration_ms, duration_ms)
            metrics.max_duration_ms = max(metrics.max_duration_ms, duration_ms)
            metrics.avg_duration_ms = metrics.total_duration_ms / metrics.total_executions

            # Update recent durations for percentile calculations
            metrics.recent_durations.append(duration_ms)

            # Calculate percentiles
            if metrics.recent_durations:
                sorted_durations = sorted(metrics.recent_durations)
                n = len(sorted_durations)
                metrics.p50_duration_ms = sorted_durations[int(n * 0.5)]
                metrics.p90_duration_ms = sorted_durations[int(n * 0.9)]
                metrics.p95_duration_ms = sorted_durations[int(n * 0.95)]
                metrics.p99_duration_ms = sorted_durations[int(n * 0.99)]

            metrics.last_updated = datetime.now()

            # Check for performance issues
            await self._check_performance_thresholds(phase, metrics)

    async def _check_performance_thresholds(self, phase: str, metrics: PerformanceMetrics):
        """Check if performance meets thresholds and generate alerts."""
        if phase not in self.thresholds:
            return

        threshold = self.thresholds[phase]

        # Check duration thresholds
        if metrics.avg_duration_ms > threshold.critical_duration_ms:
            await self._generate_alert(
                phase=phase,
                level="CRITICAL",
                message=f"Phase {phase} average duration {metrics.avg_duration_ms:.0f}ms exceeds critical threshold {threshold.critical_duration_ms}ms",
                metrics=metrics,
            )
        elif metrics.avg_duration_ms > threshold.warning_duration_ms:
            await self._generate_alert(
                phase=phase,
                level="WARNING",
                message=f"Phase {phase} average duration {metrics.avg_duration_ms:.0f}ms exceeds warning threshold {threshold.warning_duration_ms}ms",
                metrics=metrics,
            )

        # Check success rate thresholds
        if metrics.total_executions > 0:
            success_rate = metrics.successful_executions / metrics.total_executions
            if success_rate < threshold.min_success_rate:
                await self._generate_alert(
                    phase=phase,
                    level="CRITICAL",
                    message=f"Phase {phase} success rate {success_rate:.1%} below minimum threshold {threshold.min_success_rate:.1%}",
                    metrics=metrics,
                )

    async def _generate_alert(self, phase: str, level: str, message: str, metrics: PerformanceMetrics):
        """Generate a performance alert."""
        alert = {
            "timestamp": datetime.now().isoformat(),
            "phase": phase,
            "level": level,
            "message": message,
            "metrics": {
                "total_executions": metrics.total_executions,
                "success_rate": metrics.successful_executions / max(metrics.total_executions, 1),
                "avg_duration_ms": metrics.avg_duration_ms,
                "p95_duration_ms": metrics.p95_duration_ms,
            },
        }

        self.alerts.append(alert)

        # Keep only recent alerts (last 1000)
        if len(self.alerts) > 1000:
            self.alerts = self.alerts[-1000:]

        print(f"[PerformanceMonitor] {level} ALERT: {message}", file=sys.stderr)

    async def check_performance_threshold(self, phase: str, duration_ms: float) -> bool:
        """
        Check if a phase duration meets performance thresholds.

        Args:
            phase: Phase name
            duration_ms: Duration in milliseconds

        Returns:
            True if performance is acceptable
        """
        if phase not in self.thresholds:
            return True

        threshold = self.thresholds[phase]
        return duration_ms <= threshold.warning_duration_ms

    def get_performance_level(self, phase: str, duration_ms: float) -> PerformanceLevel:
        """
        Get performance level for a duration.

        Args:
            phase: Phase name
            duration_ms: Duration in milliseconds

        Returns:
            Performance level
        """
        if phase not in self.metrics:
            return PerformanceLevel.EXCELLENT

        metrics = self.metrics[phase]
        if not metrics.recent_durations:
            return PerformanceLevel.EXCELLENT

        # Calculate percentile rank
        sorted_durations = sorted(metrics.recent_durations)
        n = len(sorted_durations)

        # Find percentile rank
        rank = sum(1 for d in sorted_durations if d <= duration_ms) / n

        if rank <= 0.5:
            return PerformanceLevel.EXCELLENT
        elif rank <= 0.75:
            return PerformanceLevel.GOOD
        elif rank <= 0.9:
            return PerformanceLevel.AVERAGE
        elif rank <= 0.95:
            return PerformanceLevel.POOR
        else:
            return PerformanceLevel.CRITICAL

    def get_phase_metrics(self, phase: str) -> Optional[PerformanceMetrics]:
        """Get performance metrics for a specific phase."""
        return self.metrics.get(phase)

    def get_all_metrics(self) -> Dict[str, PerformanceMetrics]:
        """Get all performance metrics."""
        return self.metrics.copy()

    def get_recent_alerts(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get recent alerts within specified hours."""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [alert for alert in self.alerts if datetime.fromisoformat(alert["timestamp"]) >= cutoff]

    def get_performance_summary(self) -> Dict[str, Any]:
        """Get overall performance summary."""
        summary = {
            "total_phases": len(self.metrics),
            "total_executions": sum(m.total_executions for m in self.metrics.values()),
            "overall_success_rate": 0.0,
            "phase_summaries": {},
            "recent_alerts": len(self.get_recent_alerts(1)),  # Last hour
            "performance_trends": {},
        }

        if self.metrics:
            total_successful = sum(m.successful_executions for m in self.metrics.values())
            total_executions = sum(m.total_executions for m in self.metrics.values())
            summary["overall_success_rate"] = total_successful / max(total_executions, 1)

        # Phase summaries
        for phase, metrics in self.metrics.items():
            success_rate = metrics.successful_executions / max(metrics.total_executions, 1)
            summary["phase_summaries"][phase] = {
                "executions": metrics.total_executions,
                "success_rate": success_rate,
                "avg_duration_ms": metrics.avg_duration_ms,
                "p95_duration_ms": metrics.p95_duration_ms,
                "performance_level": self.get_performance_level(phase, metrics.avg_duration_ms).value,
            }

        return summary

    def set_threshold(self, phase: str, threshold: PerformanceThreshold):
        """Set performance threshold for a phase."""
        self.thresholds[phase] = threshold

    def clear_metrics(self, phase: Optional[str] = None):
        """Clear performance metrics."""
        if phase:
            if phase in self.metrics:
                del self.metrics[phase]
        else:
            self.metrics.clear()
            self.alerts.clear()

    def export_metrics(self) -> Dict[str, Any]:
        """Export metrics for analysis."""
        return {
            "timestamp": datetime.now().isoformat(),
            "metrics": {
                phase: {
                    "total_executions": m.total_executions,
                    "successful_executions": m.successful_executions,
                    "failed_executions": m.failed_executions,
                    "avg_duration_ms": m.avg_duration_ms,
                    "min_duration_ms": m.min_duration_ms,
                    "max_duration_ms": m.max_duration_ms,
                    "p50_duration_ms": m.p50_duration_ms,
                    "p90_duration_ms": m.p90_duration_ms,
                    "p95_duration_ms": m.p95_duration_ms,
                    "p99_duration_ms": m.p99_duration_ms,
                    "error_types": m.error_types,
                    "last_updated": m.last_updated.isoformat(),
                }
                for phase, m in self.metrics.items()
            },
            "thresholds": {
                phase: {
                    "warning_duration_ms": t.warning_duration_ms,
                    "critical_duration_ms": t.critical_duration_ms,
                    "min_success_rate": t.min_success_rate,
                    "max_error_rate": t.max_error_rate,
                }
                for phase, t in self.thresholds.items()
            },
            "recent_alerts": self.get_recent_alerts(24),
        }


# Global performance monitor instance
performance_monitor = PerformanceMonitor()


# Convenience functions
async def track_phase_performance(
    phase: str,
    duration_ms: float,
    success: bool,
    error_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Track performance metrics for a phase execution."""
    await performance_monitor.track_phase_performance(phase, duration_ms, success, error_type, metadata)


async def check_performance_threshold(phase: str, duration_ms: float) -> bool:
    """Check if a phase duration meets performance thresholds."""
    return await performance_monitor.check_performance_threshold(phase, duration_ms)


def get_performance_level(phase: str, duration_ms: float) -> PerformanceLevel:
    """Get performance level for a duration."""
    return performance_monitor.get_performance_level(phase, duration_ms)


def get_performance_summary() -> Dict[str, Any]:
    """Get overall performance summary."""
    return performance_monitor.get_performance_summary()


def get_phase_metrics(phase: str) -> Optional[PerformanceMetrics]:
    """Get performance metrics for a specific phase."""
    return performance_monitor.get_phase_metrics(phase)


def get_recent_alerts(hours: int = 24) -> List[Dict[str, Any]]:
    """Get recent alerts within specified hours."""
    return performance_monitor.get_recent_alerts(hours)


def export_metrics() -> Dict[str, Any]:
    """Export metrics for analysis."""
    return performance_monitor.export_metrics()
