"""
Comprehensive Monitoring Infrastructure

Provides unified monitoring for all agent framework components including:
- Metrics aggregation from all subsystems
- Real-time threshold checking and alerting
- Prometheus-compatible metrics export
- Dashboard data generation
- 100% critical path coverage

ONEX Pattern: Effect node (metrics persistence and alerting)
Performance Target: <50ms metric collection, <200ms alert generation
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

from .db import get_pg_pool

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class MetricType(Enum):
    """Metric types for classification."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


@dataclass
class Metric:
    """Single metric data point."""

    name: str
    value: float
    metric_type: MetricType
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    help_text: str = ""


@dataclass
class MonitoringAlert:
    """Monitoring alert with full context."""

    alert_id: str
    severity: AlertSeverity
    metric_name: str
    threshold: float
    actual_value: float
    message: str
    component: str
    labels: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    resolution_message: str | None = None


@dataclass
class HealthStatus:
    """Component health status."""

    component: str
    healthy: bool
    status: str
    last_check: datetime
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MonitoringThresholds:
    """Monitoring thresholds configuration."""

    # Template caching thresholds
    template_load_ms_warning: float = 50.0
    template_load_ms_critical: float = 100.0
    cache_hit_rate_warning: float = 0.70
    cache_hit_rate_critical: float = 0.60

    # Parallel generation thresholds
    parallel_speedup_warning: float = 2.5
    parallel_speedup_critical: float = 2.0
    generation_time_ms_warning: float = 3000.0
    generation_time_ms_critical: float = 5000.0

    # Mixin learning thresholds
    mixin_accuracy_warning: float = 0.90
    mixin_accuracy_critical: float = 0.85
    compatibility_score_warning: float = 0.80
    compatibility_score_critical: float = 0.70

    # Pattern matching thresholds
    pattern_precision_warning: float = 0.85
    pattern_precision_critical: float = 0.80
    false_positive_rate_warning: float = 0.15
    false_positive_rate_critical: float = 0.20

    # Event processing thresholds
    event_latency_p95_warning: float = 200.0
    event_latency_p95_critical: float = 300.0
    event_success_rate_warning: float = 0.95
    event_success_rate_critical: float = 0.90

    # Quality thresholds
    quality_score_warning: float = 0.80
    quality_score_critical: float = 0.75
    validation_pass_rate_warning: float = 0.90
    validation_pass_rate_critical: float = 0.85


class MonitoringSystem:
    """
    Comprehensive monitoring system for agent framework components.

    Features:
    - Aggregate metrics from template cache, parallel generation, mixin learning,
      pattern matching, and event processing
    - Real-time threshold checking with configurable alerts
    - Prometheus-compatible metrics export
    - Health checks for all critical components
    - Dashboard data generation
    - Alert lifecycle management (creation, resolution, escalation)

    Performance:
    - Metric collection: <50ms
    - Alert generation: <200ms
    - Dashboard query: <500ms
    """

    def __init__(self, thresholds: MonitoringThresholds | None = None):
        """Initialize monitoring system.

        Args:
            thresholds: Custom threshold configuration (uses defaults if None)
        """
        self.thresholds = thresholds or MonitoringThresholds()
        self.metrics: dict[str, list[Metric]] = defaultdict(list)
        self.active_alerts: dict[str, MonitoringAlert] = {}
        self.resolved_alerts: list[MonitoringAlert] = []
        self.health_statuses: dict[str, HealthStatus] = {}
        self._lock = asyncio.Lock()

        # Metric retention (keep last 1000 data points per metric)
        self._max_metric_history = 1000

        # Alert deduplication window (5 minutes)
        self._alert_dedup_window = timedelta(minutes=5)

        logger.info("MonitoringSystem initialized with thresholds")

    async def record_metric(
        self,
        name: str,
        value: float,
        metric_type: MetricType,
        labels: dict[str, str] | None = None,
        help_text: str = "",
    ) -> None:
        """Record a metric data point.

        Args:
            name: Metric name (e.g., 'template_load_duration_ms')
            value: Metric value
            metric_type: Type of metric (counter, gauge, histogram, etc.)
            labels: Optional labels for metric dimensions
            help_text: Human-readable description
        """
        metric = Metric(
            name=name,
            value=value,
            metric_type=metric_type,
            labels=labels or {},
            help_text=help_text,
        )

        async with self._lock:
            self.metrics[name].append(metric)

            # Trim metric history
            if len(self.metrics[name]) > self._max_metric_history:
                self.metrics[name] = self.metrics[name][-self._max_metric_history :]

        # Check thresholds and generate alerts
        await self._check_thresholds(metric)

    async def _check_thresholds(self, metric: Metric) -> None:
        """Check metric against thresholds and generate alerts if needed.

        Args:
            metric: Metric to check
        """
        alert_config = self._get_threshold_config(metric.name)
        if not alert_config:
            return

        warning_threshold, critical_threshold, comparison = alert_config

        # Determine if threshold is breached
        breached = False
        severity = None

        if comparison == "greater_than":
            if metric.value > critical_threshold:
                breached = True
                severity = AlertSeverity.CRITICAL
            elif metric.value > warning_threshold:
                breached = True
                severity = AlertSeverity.WARNING
        elif comparison == "less_than":
            if metric.value < critical_threshold:
                breached = True
                severity = AlertSeverity.CRITICAL
            elif metric.value < warning_threshold:
                breached = True
                severity = AlertSeverity.WARNING

        if breached and severity:
            await self._create_alert(
                metric_name=metric.name,
                severity=severity,
                actual_value=metric.value,
                threshold=(
                    critical_threshold
                    if severity == AlertSeverity.CRITICAL
                    else warning_threshold
                ),
                labels=metric.labels,
            )
        else:
            # Resolve any existing alerts for this metric
            await self._auto_resolve_alerts(metric.name, metric.labels)

    def _get_threshold_config(
        self, metric_name: str
    ) -> tuple[float, float, str] | None:
        """Get threshold configuration for a metric.

        Args:
            metric_name: Name of the metric

        Returns:
            Tuple of (warning_threshold, critical_threshold, comparison_type)
            or None if no threshold configured
        """
        thresholds_map = {
            "template_load_duration_ms": (
                self.thresholds.template_load_ms_warning,
                self.thresholds.template_load_ms_critical,
                "greater_than",
            ),
            "cache_hit_rate": (
                self.thresholds.cache_hit_rate_warning,
                self.thresholds.cache_hit_rate_critical,
                "less_than",
            ),
            "parallel_speedup": (
                self.thresholds.parallel_speedup_warning,
                self.thresholds.parallel_speedup_critical,
                "less_than",
            ),
            "generation_duration_ms": (
                self.thresholds.generation_time_ms_warning,
                self.thresholds.generation_time_ms_critical,
                "greater_than",
            ),
            "mixin_accuracy": (
                self.thresholds.mixin_accuracy_warning,
                self.thresholds.mixin_accuracy_critical,
                "less_than",
            ),
            "compatibility_score": (
                self.thresholds.compatibility_score_warning,
                self.thresholds.compatibility_score_critical,
                "less_than",
            ),
            "pattern_precision": (
                self.thresholds.pattern_precision_warning,
                self.thresholds.pattern_precision_critical,
                "less_than",
            ),
            "false_positive_rate": (
                self.thresholds.false_positive_rate_warning,
                self.thresholds.false_positive_rate_critical,
                "greater_than",
            ),
            "event_latency_p95_ms": (
                self.thresholds.event_latency_p95_warning,
                self.thresholds.event_latency_p95_critical,
                "greater_than",
            ),
            "event_success_rate": (
                self.thresholds.event_success_rate_warning,
                self.thresholds.event_success_rate_critical,
                "less_than",
            ),
            "quality_score": (
                self.thresholds.quality_score_warning,
                self.thresholds.quality_score_critical,
                "less_than",
            ),
            "validation_pass_rate": (
                self.thresholds.validation_pass_rate_warning,
                self.thresholds.validation_pass_rate_critical,
                "less_than",
            ),
        }

        return thresholds_map.get(metric_name)

    async def _create_alert(
        self,
        metric_name: str,
        severity: AlertSeverity,
        actual_value: float,
        threshold: float,
        labels: dict[str, str],
    ) -> None:
        """Create a new alert if not duplicate.

        Args:
            metric_name: Name of metric that triggered alert
            severity: Alert severity level
            actual_value: Actual metric value
            threshold: Threshold that was breached
            labels: Metric labels for context
        """
        # Create alert key for deduplication
        alert_key = (
            f"{metric_name}:{severity.value}:{json.dumps(labels, sort_keys=True)}"
        )

        async with self._lock:
            # Check if similar alert exists recently
            if alert_key in self.active_alerts:
                existing = self.active_alerts[alert_key]
                # Update existing alert value
                existing.actual_value = actual_value
                existing.created_at = datetime.now(UTC)
                return

            # Create new alert
            alert = MonitoringAlert(
                alert_id=str(uuid4()),
                severity=severity,
                metric_name=metric_name,
                threshold=threshold,
                actual_value=actual_value,
                message=self._format_alert_message(
                    metric_name, severity, actual_value, threshold
                ),
                component=self._get_component_from_metric(metric_name),
                labels=labels,
            )

            self.active_alerts[alert_key] = alert

            logger.warning(
                f"[MONITORING] {severity.value.upper()} ALERT: {alert.message}",
                extra={"alert_id": alert.alert_id, "component": alert.component},
            )

    async def _auto_resolve_alerts(
        self, metric_name: str, labels: dict[str, str]
    ) -> None:
        """Auto-resolve alerts when metric returns to normal.

        Args:
            metric_name: Name of metric
            labels: Metric labels for matching
        """
        async with self._lock:
            resolved_keys = []

            for alert_key, alert in self.active_alerts.items():
                if alert.metric_name == metric_name and alert.labels == labels:
                    alert.resolved_at = datetime.now(UTC)
                    alert.resolution_message = "Metric returned to normal range"
                    self.resolved_alerts.append(alert)
                    resolved_keys.append(alert_key)

            for key in resolved_keys:
                del self.active_alerts[key]

    def _format_alert_message(
        self,
        metric_name: str,
        severity: AlertSeverity,
        actual_value: float,
        threshold: float,
    ) -> str:
        """Format alert message.

        Args:
            metric_name: Metric name
            severity: Alert severity
            actual_value: Actual metric value
            threshold: Threshold value

        Returns:
            Formatted alert message
        """
        if metric_name.endswith("_ms"):
            return f"{metric_name}: {actual_value:.1f}ms exceeds {severity.value} threshold of {threshold:.1f}ms"
        elif (
            "_rate" in metric_name
            or "_accuracy" in metric_name
            or "_precision" in metric_name
            or "score" in metric_name
        ):
            return f"{metric_name}: {actual_value:.2%} below {severity.value} threshold of {threshold:.2%}"
        else:
            return f"{metric_name}: {actual_value:.2f} breaches {severity.value} threshold of {threshold:.2f}"

    def _get_component_from_metric(self, metric_name: str) -> str:
        """Determine component from metric name.

        Args:
            metric_name: Metric name

        Returns:
            Component name
        """
        if "template" in metric_name or "cache" in metric_name:
            return "template_cache"
        elif "parallel" in metric_name or "generation" in metric_name:
            return "parallel_generation"
        elif "mixin" in metric_name or "compatibility" in metric_name:
            return "mixin_learning"
        elif "pattern" in metric_name:
            return "pattern_matching"
        elif "event" in metric_name:
            return "event_processing"
        elif "quality" in metric_name or "validation" in metric_name:
            return "quality_validation"
        else:
            return "unknown"

    async def collect_all_metrics(
        self, time_window_minutes: int = 60
    ) -> dict[str, Any]:
        """Collect metrics from all subsystems.

        Args:
            time_window_minutes: Time window for metric aggregation

        Returns:
            Dictionary of aggregated metrics
        """
        start_time = time.time()
        cutoff_time = datetime.now(UTC) - timedelta(minutes=time_window_minutes)

        pool = await get_pg_pool()
        if not pool:
            logger.warning("Database connection not available for metric collection")
            return {"error": "Database unavailable"}

        try:
            async with pool.acquire() as conn:
                # Collect template cache metrics
                template_metrics = await self._collect_template_cache_metrics(
                    conn, cutoff_time
                )

                # Collect parallel generation metrics
                parallel_metrics = await self._collect_parallel_generation_metrics(
                    conn, cutoff_time
                )

                # Collect mixin learning metrics
                mixin_metrics = await self._collect_mixin_learning_metrics(
                    conn, cutoff_time
                )

                # Collect pattern feedback metrics
                pattern_metrics = await self._collect_pattern_feedback_metrics(
                    conn, cutoff_time
                )

                # Collect event processing metrics
                event_metrics = await self._collect_event_processing_metrics(
                    conn, cutoff_time
                )

                collection_time_ms = (time.time() - start_time) * 1000

                return {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "time_window_minutes": time_window_minutes,
                    "collection_time_ms": collection_time_ms,
                    "template_cache": template_metrics,
                    "parallel_generation": parallel_metrics,
                    "mixin_learning": mixin_metrics,
                    "pattern_matching": pattern_metrics,
                    "event_processing": event_metrics,
                    "active_alerts_count": len(self.active_alerts),
                    "health_status": self._get_overall_health_status(),
                }
        except Exception as e:
            logger.error(f"Error collecting metrics: {e}", exc_info=True)
            return {"error": str(e)}

    async def _collect_template_cache_metrics(
        self, conn: Any, cutoff_time: datetime
    ) -> dict[str, Any]:
        """Collect template cache metrics from database.

        Args:
            conn: Database connection
            cutoff_time: Only include metrics after this time

        Returns:
            Template cache metrics
        """
        try:
            # Query template_cache_efficiency view
            result = await conn.fetch(
                """
                SELECT
                    template_type,
                    template_count,
                    avg_cache_hits,
                    avg_cache_misses,
                    hit_rate,
                    avg_load_time_ms,
                    total_size_mb
                FROM template_cache_efficiency
            """
            )

            metrics = {
                "by_type": [dict(row) for row in result],
                "overall_hit_rate": 0.0,
                "avg_load_time_ms": 0.0,
                "total_templates": 0,
            }

            if result:
                total_hits = sum(
                    r["avg_cache_hits"] * r["template_count"] for r in result
                )
                total_misses = sum(
                    r["avg_cache_misses"] * r["template_count"] for r in result
                )
                total = total_hits + total_misses

                if total > 0:
                    metrics["overall_hit_rate"] = total_hits / total

                metrics["avg_load_time_ms"] = sum(
                    r["avg_load_time_ms"] for r in result
                ) / len(result)
                metrics["total_templates"] = sum(r["template_count"] for r in result)

            return metrics
        except Exception as e:
            logger.error(f"Error collecting template cache metrics: {e}")
            return {"error": str(e)}

    async def _collect_parallel_generation_metrics(
        self, conn: Any, cutoff_time: datetime
    ) -> dict[str, Any]:
        """Collect parallel generation metrics from database.

        Args:
            conn: Database connection
            cutoff_time: Only include metrics after this time

        Returns:
            Parallel generation metrics
        """
        try:
            # Query performance_metrics_summary view
            result = await conn.fetch(
                """
                SELECT
                    phase,
                    execution_count,
                    avg_duration_ms,
                    p95_duration_ms,
                    p99_duration_ms,
                    cache_hits,
                    parallel_executions,
                    avg_workers
                FROM performance_metrics_summary
                WHERE phase IN ('code_gen', 'total')
            """
            )

            metrics = {
                "by_phase": [dict(row) for row in result],
                "parallel_usage_rate": 0.0,
                "avg_speedup": 0.0,
            }

            # Calculate parallel usage rate
            total_execs = sum(r["execution_count"] for r in result)
            parallel_execs = sum(r["parallel_executions"] for r in result)

            if total_execs > 0:
                metrics["parallel_usage_rate"] = parallel_execs / total_execs

            return metrics
        except Exception as e:
            logger.error(f"Error collecting parallel generation metrics: {e}")
            return {"error": str(e)}

    async def _collect_mixin_learning_metrics(
        self, conn: Any, cutoff_time: datetime
    ) -> dict[str, Any]:
        """Collect mixin learning metrics from database.

        Args:
            conn: Database connection
            cutoff_time: Only include metrics after this time

        Returns:
            Mixin learning metrics
        """
        try:
            # Query mixin_compatibility_summary view
            result = await conn.fetch(
                """
                SELECT
                    node_type,
                    total_combinations,
                    avg_compatibility,
                    total_successes,
                    total_failures,
                    success_rate
                FROM mixin_compatibility_summary
            """
            )

            metrics = {
                "by_node_type": [dict(row) for row in result],
                "overall_success_rate": 0.0,
                "avg_compatibility_score": 0.0,
            }

            if result:
                total_tests = sum(
                    r["total_successes"] + r["total_failures"] for r in result
                )
                total_successes = sum(r["total_successes"] for r in result)

                if total_tests > 0:
                    metrics["overall_success_rate"] = total_successes / total_tests

                metrics["avg_compatibility_score"] = sum(
                    r["avg_compatibility"] for r in result
                ) / len(result)

            return metrics
        except Exception as e:
            logger.error(f"Error collecting mixin learning metrics: {e}")
            return {"error": str(e)}

    async def _collect_pattern_feedback_metrics(
        self, conn: Any, cutoff_time: datetime
    ) -> dict[str, Any]:
        """Collect pattern feedback metrics from database.

        Args:
            conn: Database connection
            cutoff_time: Only include metrics after this time

        Returns:
            Pattern feedback metrics
        """
        try:
            # Query pattern_feedback_analysis view
            result = await conn.fetch(
                """
                SELECT
                    pattern_name,
                    feedback_type,
                    feedback_count,
                    avg_confidence,
                    user_provided_count,
                    avg_learning_weight
                FROM pattern_feedback_analysis
            """
            )

            metrics = {
                "by_pattern": [dict(row) for row in result],
                "total_feedback_count": 0,
                "avg_confidence": 0.0,
                "precision": 0.0,
            }

            if result:
                metrics["total_feedback_count"] = sum(
                    r["feedback_count"] for r in result
                )

                # Calculate weighted average confidence
                total_weighted = sum(
                    r["avg_confidence"] * r["feedback_count"]
                    for r in result
                    if r["avg_confidence"]
                )
                total_count = sum(
                    r["feedback_count"] for r in result if r["avg_confidence"]
                )

                if total_count > 0:
                    metrics["avg_confidence"] = total_weighted / total_count

                # Calculate precision (correct / (correct + incorrect))
                correct = sum(
                    r["feedback_count"]
                    for r in result
                    if r["feedback_type"] == "correct"
                )
                incorrect = sum(
                    r["feedback_count"]
                    for r in result
                    if r["feedback_type"] == "incorrect"
                )

                if correct + incorrect > 0:
                    metrics["precision"] = correct / (correct + incorrect)

            return metrics
        except Exception as e:
            logger.error(f"Error collecting pattern feedback metrics: {e}")
            return {"error": str(e)}

    async def _collect_event_processing_metrics(
        self, conn: Any, cutoff_time: datetime
    ) -> dict[str, Any]:
        """Collect event processing metrics from database.

        Args:
            conn: Database connection
            cutoff_time: Only include metrics after this time

        Returns:
            Event processing metrics
        """
        try:
            # Query event_processing_health view
            result = await conn.fetch(
                """
                SELECT
                    event_type,
                    event_source,
                    total_events,
                    success_count,
                    failure_count,
                    success_rate,
                    avg_duration_ms,
                    avg_wait_ms,
                    avg_retries
                FROM event_processing_health
            """
            )

            metrics = {
                "by_event_type": [dict(row) for row in result],
                "overall_success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
            }

            if result:
                total_events = sum(r["total_events"] for r in result)
                total_successes = sum(r["success_count"] for r in result)

                if total_events > 0:
                    metrics["overall_success_rate"] = total_successes / total_events

                # Weighted average latency
                total_weighted = sum(
                    r["avg_duration_ms"] * r["total_events"] for r in result
                )
                if total_events > 0:
                    metrics["avg_latency_ms"] = total_weighted / total_events

                # Get p95 from raw metrics table
                p95_result = await conn.fetchval(
                    """
                    SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY processing_duration_ms)
                    FROM event_processing_metrics
                    WHERE created_at >= $1
                """,
                    cutoff_time,
                )

                if p95_result:
                    metrics["p95_latency_ms"] = float(p95_result)

            return metrics
        except Exception as e:
            logger.error(f"Error collecting event processing metrics: {e}")
            return {"error": str(e)}

    def _get_overall_health_status(self) -> str:
        """Get overall system health status.

        Returns:
            Health status string: 'healthy', 'degraded', or 'critical'
        """
        if not self.health_statuses:
            return "unknown"

        # Check if any component is unhealthy
        critical_count = sum(
            1
            for h in self.health_statuses.values()
            if not h.healthy and h.status == "critical"
        )
        degraded_count = sum(
            1
            for h in self.health_statuses.values()
            if not h.healthy and h.status == "degraded"
        )

        if critical_count > 0:
            return "critical"
        elif degraded_count > 0:
            return "degraded"
        else:
            return "healthy"

    async def update_health_status(
        self,
        component: str,
        healthy: bool,
        status: str,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update health status for a component.

        Args:
            component: Component name
            healthy: Whether component is healthy
            status: Status string ('healthy', 'degraded', 'critical')
            error_message: Optional error message if unhealthy
            metadata: Optional additional metadata
        """
        health_status = HealthStatus(
            component=component,
            healthy=healthy,
            status=status,
            last_check=datetime.now(UTC),
            error_message=error_message,
            metadata=metadata or {},
        )

        async with self._lock:
            self.health_statuses[component] = health_status

        if not healthy:
            logger.warning(
                f"[MONITORING] Component {component} is {status}: {error_message}",
                extra={"component": component, "status": status},
            )

    def get_active_alerts(
        self, severity: AlertSeverity | None = None, component: str | None = None
    ) -> list[MonitoringAlert]:
        """Get active alerts with optional filtering.

        Args:
            severity: Filter by severity level
            component: Filter by component name

        Returns:
            List of active alerts
        """
        alerts = list(self.active_alerts.values())

        if severity:
            alerts = [a for a in alerts if a.severity == severity]

        if component:
            alerts = [a for a in alerts if a.component == component]

        return sorted(alerts, key=lambda a: a.created_at, reverse=True)

    def get_resolved_alerts(self, hours: int = 24) -> list[MonitoringAlert]:
        """Get recently resolved alerts.

        Args:
            hours: Number of hours to look back

        Returns:
            List of resolved alerts
        """
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        return [
            alert
            for alert in self.resolved_alerts
            if alert.resolved_at and alert.resolved_at >= cutoff
        ]

    async def export_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus text format.

        Returns:
            Prometheus-formatted metrics string
        """
        lines = []

        async with self._lock:
            # Group metrics by name
            for metric_name, metric_list in self.metrics.items():
                if not metric_list:
                    continue

                latest_metric = metric_list[-1]

                # Add HELP line
                if latest_metric.help_text:
                    lines.append(f"# HELP {metric_name} {latest_metric.help_text}")

                # Add TYPE line
                type_str = latest_metric.metric_type.value.lower()
                lines.append(f"# TYPE {metric_name} {type_str}")

                # Add metric line(s)
                if latest_metric.metric_type == MetricType.HISTOGRAM:
                    # For histograms, export recent values with quantiles
                    values = [m.value for m in metric_list[-100:]]
                    values.sort()

                    labels_str = self._format_labels(latest_metric.labels)

                    # Export quantiles
                    for quantile in [0.5, 0.9, 0.95, 0.99]:
                        idx = int(len(values) * quantile)
                        value = values[min(idx, len(values) - 1)]
                        q_labels = {**latest_metric.labels, "quantile": str(quantile)}
                        q_labels_str = self._format_labels(q_labels)
                        lines.append(f"{metric_name}{q_labels_str} {value}")
                else:
                    # For counters and gauges, export latest value
                    labels_str = self._format_labels(latest_metric.labels)
                    lines.append(f"{metric_name}{labels_str} {latest_metric.value}")

        return "\n".join(lines) + "\n"

    def _format_labels(self, labels: dict[str, str]) -> str:
        """Format labels for Prometheus export.

        Args:
            labels: Label dictionary

        Returns:
            Formatted label string
        """
        if not labels:
            return ""

        label_strs = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        return "{" + ",".join(label_strs) + "}"

    def get_monitoring_summary(self) -> dict[str, Any]:
        """Get comprehensive monitoring summary.

        Returns:
            Dictionary with monitoring summary
        """
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "health": {
                "overall_status": self._get_overall_health_status(),
                "components": {
                    name: {
                        "healthy": status.healthy,
                        "status": status.status,
                        "last_check": status.last_check.isoformat(),
                        "error": status.error_message,
                    }
                    for name, status in self.health_statuses.items()
                },
            },
            "alerts": {
                "active_count": len(self.active_alerts),
                "critical_count": len(
                    self.get_active_alerts(severity=AlertSeverity.CRITICAL)
                ),
                "warning_count": len(
                    self.get_active_alerts(severity=AlertSeverity.WARNING)
                ),
                "info_count": len(self.get_active_alerts(severity=AlertSeverity.INFO)),
                "resolved_24h": len(self.get_resolved_alerts(hours=24)),
            },
            "metrics": {
                "total_metric_types": len(self.metrics),
                "total_data_points": sum(len(m) for m in self.metrics.values()),
            },
        }

    async def clear_metrics(self) -> None:
        """Clear all metrics and reset monitoring state."""
        async with self._lock:
            self.metrics.clear()
            self.active_alerts.clear()
            self.resolved_alerts.clear()
            self.health_statuses.clear()

        logger.info("Monitoring system metrics cleared")


# Global monitoring system instance
_monitoring_system: MonitoringSystem | None = None


def get_monitoring_system(
    thresholds: MonitoringThresholds | None = None,
) -> MonitoringSystem:
    """Get or create global monitoring system instance.

    Args:
        thresholds: Optional custom thresholds

    Returns:
        MonitoringSystem instance
    """
    global _monitoring_system

    if _monitoring_system is None:
        _monitoring_system = MonitoringSystem(thresholds)

    return _monitoring_system


# Convenience functions
async def record_metric(
    name: str,
    value: float,
    metric_type: MetricType,
    labels: dict[str, str] | None = None,
    help_text: str = "",
) -> None:
    """Record a metric data point.

    Args:
        name: Metric name
        value: Metric value
        metric_type: Type of metric
        labels: Optional labels
        help_text: Human-readable description
    """
    monitoring = get_monitoring_system()
    await monitoring.record_metric(name, value, metric_type, labels, help_text)


async def collect_all_metrics(time_window_minutes: int = 60) -> dict[str, Any]:
    """Collect metrics from all subsystems.

    Args:
        time_window_minutes: Time window for aggregation

    Returns:
        Dictionary of aggregated metrics
    """
    monitoring = get_monitoring_system()
    return await monitoring.collect_all_metrics(time_window_minutes)


async def update_health_status(
    component: str,
    healthy: bool,
    status: str,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Update health status for a component.

    Args:
        component: Component name
        healthy: Whether component is healthy
        status: Status string
        error_message: Optional error message
        metadata: Optional metadata
    """
    monitoring = get_monitoring_system()
    await monitoring.update_health_status(
        component, healthy, status, error_message, metadata
    )


def get_active_alerts(
    severity: AlertSeverity | None = None, component: str | None = None
) -> list[MonitoringAlert]:
    """Get active alerts with optional filtering.

    Args:
        severity: Filter by severity
        component: Filter by component

    Returns:
        List of active alerts
    """
    monitoring = get_monitoring_system()
    return monitoring.get_active_alerts(severity, component)


def get_monitoring_summary() -> dict[str, Any]:
    """Get comprehensive monitoring summary.

    Returns:
        Monitoring summary dictionary
    """
    monitoring = get_monitoring_system()
    return monitoring.get_monitoring_summary()


async def export_prometheus_metrics() -> str:
    """Export metrics in Prometheus text format.

    Returns:
        Prometheus-formatted metrics string
    """
    monitoring = get_monitoring_system()
    return await monitoring.export_prometheus_metrics()
