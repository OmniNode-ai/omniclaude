"""
Performance Metrics Collector for Agent Routing and Execution

Provides comprehensive metrics collection for:
- Routing decision latency and accuracy
- Confidence score distribution
- Cache hit rates
- Agent loading and transformation performance
- All 33 performance thresholds monitoring
- Trend analysis and optimization recommendations

Target: <10ms collection overhead per operation
"""

import asyncio
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Deque, Dict, List, Optional


class MetricType(str, Enum):
    """Types of metrics collected."""

    ROUTING_LATENCY = "routing_latency"
    CONFIDENCE_SCORE = "confidence_score"
    CACHE_HIT_RATE = "cache_hit_rate"
    AGENT_LOADING = "agent_loading"
    AGENT_TRANSFORMATION = "agent_transformation"
    THRESHOLD_VIOLATION = "threshold_violation"
    # Performance threshold categories
    INTELLIGENCE = "intelligence"
    PARALLEL_EXECUTION = "parallel_execution"
    COORDINATION = "coordination"
    CONTEXT_MANAGEMENT = "context_management"
    TEMPLATE_SYSTEM = "template_system"
    LIFECYCLE = "lifecycle"
    DASHBOARD = "dashboard"


class ThresholdStatus(str, Enum):
    """Threshold compliance status."""

    NORMAL = "normal"  # Within threshold
    WARNING = "warning"  # 80-95% of threshold
    CRITICAL = "critical"  # 95-105% of threshold
    EMERGENCY = "emergency"  # >105% of threshold


@dataclass
class MetricDataPoint:
    """Single metric data point."""

    timestamp: float
    value: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    metric_type: MetricType = MetricType.ROUTING_LATENCY


@dataclass
class ThresholdViolation:
    """Record of threshold violation."""

    threshold_id: str
    threshold_name: str
    measured_value: float
    threshold_value: float
    violation_percent: float
    status: ThresholdStatus
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceBaseline:
    """Performance baseline for comparison."""

    metric_type: MetricType
    baseline_mean: float
    baseline_median: float
    baseline_p95: float
    baseline_p99: float
    sample_count: int
    established_at: float
    window_minutes: int = 10


@dataclass
class TrendAnalysis:
    """Performance trend analysis result."""

    metric_type: MetricType
    current_mean: float
    baseline_mean: float
    degradation_percent: float
    trend_direction: str  # "improving", "stable", "degrading"
    confidence: float
    recommendations: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class RouterMetricsCollector:
    """
    High-performance metrics collector for routing operations.

    Features:
    - <10ms collection overhead
    - In-memory sliding windows for trend analysis
    - All 33 performance thresholds monitoring
    - Real-time threshold violation detection
    - Performance baseline establishment
    - Optimization recommendations
    - Database-ready for persistence

    Performance Targets:
    - Collection overhead: <10ms
    - Metrics query latency: <50ms
    - Trend analysis: <500ms
    - Memory footprint: <50MB
    """

    def __init__(
        self,
        window_size: int = 1000,  # Number of samples to keep
        window_minutes: int = 10,  # Time window for baseline
        metrics_dir: str = "traces/metrics",
    ):
        self.window_size = window_size
        self.window_minutes = window_minutes
        self.metrics_dir = Path(metrics_dir)
        self.metrics_dir.mkdir(parents=True, exist_ok=True)

        # Sliding windows for different metric types
        self._metrics: Dict[MetricType, Deque[MetricDataPoint]] = defaultdict(
            lambda: deque(maxlen=window_size)
        )

        # Threshold violations history
        self._violations: Deque[ThresholdViolation] = deque(maxlen=1000)

        # Performance baselines
        self._baselines: Dict[MetricType, PerformanceBaseline] = {}

        # Cache statistics
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_queries = 0

        # Routing statistics
        self._routing_decisions = 0
        self._successful_routings = 0
        self._fallback_routings = 0

        # Agent transformation statistics
        self._transformations = 0
        self._transformation_failures = 0

        # Performance thresholds configuration (loaded from YAML)
        self._thresholds: Dict[str, Dict[str, Any]] = {}

        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

        # Last metrics flush timestamp
        self._last_flush = time.time()

        # Initialize thresholds
        self._load_thresholds()

    def _load_thresholds(self):
        """Load performance thresholds from configuration."""
        # These are the 33 thresholds from performance-thresholds.yaml
        # Simplified inline version for demonstration
        self._thresholds = {
            # Intelligence thresholds (INT-001 to INT-006)
            "INT-001": {
                "name": "RAG Query Response Time",
                "threshold_ms": 1500,
                "alert_threshold_ms": 1200,
                "category": "intelligence",
            },
            "INT-002": {
                "name": "Intelligence Gathering Overhead",
                "threshold_ms": 100,
                "alert_threshold_ms": 80,
                "category": "intelligence",
            },
            "INT-003": {
                "name": "Pattern Recognition Performance",
                "threshold_ms": 500,
                "alert_threshold_ms": 400,
                "category": "intelligence",
            },
            "INT-004": {
                "name": "Knowledge Capture Latency",
                "threshold_ms": 300,
                "alert_threshold_ms": 250,
                "category": "intelligence",
            },
            "INT-005": {
                "name": "Cross-Domain Synthesis",
                "threshold_ms": 800,
                "alert_threshold_ms": 650,
                "category": "intelligence",
            },
            "INT-006": {
                "name": "Intelligence Application Time",
                "threshold_ms": 200,
                "alert_threshold_ms": 150,
                "category": "intelligence",
            },
            # Parallel execution thresholds (PAR-001 to PAR-005)
            "PAR-001": {
                "name": "Parallel Coordination Setup",
                "threshold_ms": 500,
                "alert_threshold_ms": 400,
                "category": "parallel_execution",
            },
            "PAR-002": {
                "name": "Context Distribution Time",
                "threshold_ms": 200,
                "alert_threshold_ms": 150,
                "category": "parallel_execution",
            },
            "PAR-003": {
                "name": "Synchronization Point Latency",
                "threshold_ms": 1000,
                "alert_threshold_ms": 800,
                "category": "parallel_execution",
            },
            "PAR-004": {
                "name": "Result Aggregation Performance",
                "threshold_ms": 300,
                "alert_threshold_ms": 225,
                "category": "parallel_execution",
            },
            "PAR-005": {
                "name": "Parallel Efficiency Ratio",
                "threshold_ratio": 0.6,
                "alert_threshold_ratio": 0.7,
                "category": "parallel_execution",
            },
            # Coordination thresholds (COORD-001 to COORD-004)
            "COORD-001": {
                "name": "Agent Delegation Handoff",
                "threshold_ms": 150,
                "alert_threshold_ms": 120,
                "category": "coordination",
            },
            "COORD-002": {
                "name": "Context Inheritance Latency",
                "threshold_ms": 50,
                "alert_threshold_ms": 35,
                "category": "coordination",
            },
            "COORD-003": {
                "name": "Multi-Agent Communication",
                "threshold_ms": 100,
                "alert_threshold_ms": 75,
                "category": "coordination",
            },
            "COORD-004": {
                "name": "Coordination Overhead",
                "threshold_ms": 300,
                "alert_threshold_ms": 225,
                "category": "coordination",
            },
            # Context management thresholds (CTX-001 to CTX-006)
            "CTX-001": {
                "name": "Context Initialization Time",
                "threshold_ms": 50,
                "alert_threshold_ms": 35,
                "category": "context_management",
            },
            "CTX-002": {
                "name": "Context Preservation Latency",
                "threshold_ms": 25,
                "alert_threshold_ms": 15,
                "category": "context_management",
            },
            "CTX-003": {
                "name": "Context Refresh Performance",
                "threshold_ms": 75,
                "alert_threshold_ms": 55,
                "category": "context_management",
            },
            "CTX-004": {
                "name": "Context Memory Footprint",
                "threshold_mb": 10,
                "alert_threshold_mb": 8,
                "category": "context_management",
            },
            "CTX-005": {
                "name": "Context Lifecycle Management",
                "threshold_ms": 200,
                "alert_threshold_ms": 150,
                "category": "context_management",
            },
            "CTX-006": {
                "name": "Context Cleanup Performance",
                "threshold_ms": 100,
                "alert_threshold_ms": 75,
                "category": "context_management",
            },
            # Template system thresholds (TPL-001 to TPL-004)
            "TPL-001": {
                "name": "Template Instantiation Time",
                "threshold_ms": 100,
                "alert_threshold_ms": 75,
                "category": "template_system",
            },
            "TPL-002": {
                "name": "Template Parameter Resolution",
                "threshold_ms": 50,
                "alert_threshold_ms": 35,
                "category": "template_system",
            },
            "TPL-003": {
                "name": "Configuration Overlay Performance",
                "threshold_ms": 30,
                "alert_threshold_ms": 20,
                "category": "template_system",
            },
            "TPL-004": {
                "name": "Template Cache Hit Ratio",
                "threshold_ratio": 0.85,
                "alert_threshold_ratio": 0.9,
                "category": "template_system",
            },
            # Lifecycle thresholds (LCL-001 to LCL-004)
            "LCL-001": {
                "name": "Agent Initialization Performance",
                "threshold_ms": 300,
                "alert_threshold_ms": 225,
                "category": "lifecycle",
            },
            "LCL-002": {
                "name": "Framework Integration Time",
                "threshold_ms": 100,
                "alert_threshold_ms": 75,
                "category": "lifecycle",
            },
            "LCL-003": {
                "name": "Quality Gate Execution",
                "threshold_ms": 200,
                "alert_threshold_ms": 150,
                "category": "lifecycle",
            },
            "LCL-004": {
                "name": "Agent Cleanup Performance",
                "threshold_ms": 150,
                "alert_threshold_ms": 110,
                "category": "lifecycle",
            },
            # Dashboard thresholds (DASH-001 to DASH-004)
            "DASH-001": {
                "name": "Performance Data Collection",
                "threshold_ms": 50,
                "alert_threshold_ms": 35,
                "category": "dashboard",
            },
            "DASH-002": {
                "name": "Dashboard Update Latency",
                "threshold_ms": 100,
                "alert_threshold_ms": 75,
                "category": "dashboard",
            },
            "DASH-003": {
                "name": "Trend Analysis Performance",
                "threshold_ms": 500,
                "alert_threshold_ms": 400,
                "category": "dashboard",
            },
            "DASH-004": {
                "name": "Optimization Recommendation Time",
                "threshold_ms": 300,
                "alert_threshold_ms": 225,
                "category": "dashboard",
            },
        }

    async def record_routing_decision(
        self,
        latency_ms: float,
        confidence_score: float,
        agent_selected: str,
        alternatives: Optional[List[Dict[str, Any]]] = None,
        cache_hit: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Record a routing decision with comprehensive metrics.

        Target: <10ms overhead

        Args:
            latency_ms: Time taken for routing decision
            confidence_score: Confidence in the routing decision (0-1)
            agent_selected: Name of selected agent
            alternatives: List of alternative agents considered
            cache_hit: Whether this was served from cache
            metadata: Additional context
        """
        start_time = time.time()

        async with self._lock:
            # Record routing latency
            self._metrics[MetricType.ROUTING_LATENCY].append(
                MetricDataPoint(
                    timestamp=time.time(),
                    value=latency_ms,
                    metadata={
                        "agent_selected": agent_selected,
                        "cache_hit": cache_hit,
                        **(metadata or {}),
                    },
                    metric_type=MetricType.ROUTING_LATENCY,
                )
            )

            # Record confidence score
            self._metrics[MetricType.CONFIDENCE_SCORE].append(
                MetricDataPoint(
                    timestamp=time.time(),
                    value=confidence_score,
                    metadata={
                        "agent_selected": agent_selected,
                        "alternatives_count": len(alternatives) if alternatives else 0,
                        **(metadata or {}),
                    },
                    metric_type=MetricType.CONFIDENCE_SCORE,
                )
            )

            # Update routing statistics
            self._routing_decisions += 1
            if confidence_score >= 0.7:
                self._successful_routings += 1
            else:
                self._fallback_routings += 1

            # Update cache statistics
            self._cache_queries += 1
            if cache_hit:
                self._cache_hits += 1
            else:
                self._cache_misses += 1

            # Check threshold violations
            await self._check_threshold_violation(
                "ROUTING_LATENCY", latency_ms, metadata
            )

        # Track collection overhead
        overhead_ms = (time.time() - start_time) * 1000
        if overhead_ms > 10:
            # Log warning if overhead exceeds target
            print(f"⚠️ Metrics collection overhead: {overhead_ms:.2f}ms (target: <10ms)")

    async def record_agent_loading(
        self,
        agent_name: str,
        loading_time_ms: float,
        success: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Record agent loading performance.

        Args:
            agent_name: Name of agent loaded
            loading_time_ms: Time taken to load agent
            success: Whether loading succeeded
            metadata: Additional context
        """
        async with self._lock:
            self._metrics[MetricType.AGENT_LOADING].append(
                MetricDataPoint(
                    timestamp=time.time(),
                    value=loading_time_ms,
                    metadata={
                        "agent_name": agent_name,
                        "success": success,
                        **(metadata or {}),
                    },
                    metric_type=MetricType.AGENT_LOADING,
                )
            )

            # Check threshold violation (using LCL-001: Agent Initialization)
            await self._check_threshold_violation("LCL-001", loading_time_ms, metadata)

    async def record_agent_transformation(
        self,
        from_agent: str,
        to_agent: str,
        transformation_time_ms: float,
        success: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Record agent transformation performance.

        Args:
            from_agent: Source agent identity
            to_agent: Target agent identity
            transformation_time_ms: Time taken for transformation
            success: Whether transformation succeeded
            metadata: Additional context
        """
        async with self._lock:
            self._metrics[MetricType.AGENT_TRANSFORMATION].append(
                MetricDataPoint(
                    timestamp=time.time(),
                    value=transformation_time_ms,
                    metadata={
                        "from_agent": from_agent,
                        "to_agent": to_agent,
                        "success": success,
                        **(metadata or {}),
                    },
                    metric_type=MetricType.AGENT_TRANSFORMATION,
                )
            )

            # Update transformation statistics
            self._transformations += 1
            if not success:
                self._transformation_failures += 1

            # Target for transformation: <50ms (not in thresholds, but documented)
            if transformation_time_ms > 50:
                await self._record_violation(
                    threshold_id="TRANSFORM-001",
                    threshold_name="Agent Transformation Time",
                    measured_value=transformation_time_ms,
                    threshold_value=50,
                    metadata=metadata,
                )

    async def record_threshold_metric(
        self,
        threshold_id: str,
        measured_value: float,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Record a measurement against a specific performance threshold.

        Args:
            threshold_id: Threshold identifier (e.g., "INT-001", "PAR-002")
            measured_value: Measured value
            metadata: Additional context
        """
        if threshold_id not in self._thresholds:
            return

        threshold_config = self._thresholds[threshold_id]
        category = threshold_config.get("category", "unknown")

        async with self._lock:
            # Map category to MetricType
            metric_type = MetricType.INTELLIGENCE  # default
            if category == "parallel_execution":
                metric_type = MetricType.PARALLEL_EXECUTION
            elif category == "coordination":
                metric_type = MetricType.COORDINATION
            elif category == "context_management":
                metric_type = MetricType.CONTEXT_MANAGEMENT
            elif category == "template_system":
                metric_type = MetricType.TEMPLATE_SYSTEM
            elif category == "lifecycle":
                metric_type = MetricType.LIFECYCLE
            elif category == "dashboard":
                metric_type = MetricType.DASHBOARD

            self._metrics[metric_type].append(
                MetricDataPoint(
                    timestamp=time.time(),
                    value=measured_value,
                    metadata={
                        "threshold_id": threshold_id,
                        "threshold_name": threshold_config["name"],
                        **(metadata or {}),
                    },
                    metric_type=metric_type,
                )
            )

            # Check threshold violation
            await self._check_threshold_violation(
                threshold_id, measured_value, metadata
            )

    async def _check_threshold_violation(
        self,
        threshold_id: str,
        measured_value: float,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Check if measurement violates threshold and record if so."""
        # Handle special case for routing latency
        if threshold_id == "ROUTING_LATENCY":
            # Routing should be <100ms per specs
            threshold_value = 100
        elif threshold_id not in self._thresholds:
            return
        else:
            threshold_config = self._thresholds[threshold_id]
            # Get threshold value (could be ms, mb, or ratio)
            threshold_value = (
                threshold_config.get("threshold_ms")
                or threshold_config.get("threshold_mb")
                or threshold_config.get("threshold_ratio", 0)
            )
            (
                threshold_config.get("alert_threshold_ms")
                or threshold_config.get("alert_threshold_mb")
                or threshold_config.get("alert_threshold_ratio", 0)
            )

        # Calculate violation percentage
        if threshold_value > 0:
            violation_percent = (measured_value / threshold_value) * 100

            # Determine status based on alert escalation levels
            if violation_percent >= 105:
                status = ThresholdStatus.EMERGENCY
            elif violation_percent >= 95:
                status = ThresholdStatus.CRITICAL
            elif violation_percent >= 80:
                status = ThresholdStatus.WARNING
            else:
                status = ThresholdStatus.NORMAL

            # Record if not normal
            if status != ThresholdStatus.NORMAL:
                await self._record_violation(
                    threshold_id=threshold_id,
                    threshold_name=self._thresholds.get(threshold_id, {}).get(
                        "name", threshold_id
                    ),
                    measured_value=measured_value,
                    threshold_value=threshold_value,
                    metadata=metadata,
                    violation_percent=violation_percent,
                    status=status,
                )

    async def _record_violation(
        self,
        threshold_id: str,
        threshold_name: str,
        measured_value: float,
        threshold_value: float,
        metadata: Optional[Dict[str, Any]] = None,
        violation_percent: Optional[float] = None,
        status: Optional[ThresholdStatus] = None,
    ):
        """Record a threshold violation."""
        if violation_percent is None:
            violation_percent = (measured_value / threshold_value) * 100

        if status is None:
            if violation_percent >= 105:
                status = ThresholdStatus.EMERGENCY
            elif violation_percent >= 95:
                status = ThresholdStatus.CRITICAL
            elif violation_percent >= 80:
                status = ThresholdStatus.WARNING
            else:
                status = ThresholdStatus.NORMAL

        violation = ThresholdViolation(
            threshold_id=threshold_id,
            threshold_name=threshold_name,
            measured_value=measured_value,
            threshold_value=threshold_value,
            violation_percent=violation_percent,
            status=status,
            timestamp=time.time(),
            metadata=metadata or {},
        )

        self._violations.append(violation)

        # Log critical violations
        if status in [ThresholdStatus.CRITICAL, ThresholdStatus.EMERGENCY]:
            print(
                f"🚨 {status.value.upper()}: {threshold_name} = {measured_value:.2f} (threshold: {threshold_value})"
            )

    async def establish_baseline(
        self, metric_type: MetricType, force_refresh: bool = False
    ) -> Optional[PerformanceBaseline]:
        """
        Establish performance baseline for a metric type.

        Args:
            metric_type: Type of metric to baseline
            force_refresh: Force recalculation even if baseline exists

        Returns:
            PerformanceBaseline or None if insufficient data
        """
        async with self._lock:
            # Check if baseline already exists
            if not force_refresh and metric_type in self._baselines:
                return self._baselines[metric_type]

            # Get metrics within window
            metrics = list(self._metrics[metric_type])
            if len(metrics) < 100:
                # Need at least 100 samples for reliable baseline
                return None

            # Filter to time window
            cutoff_time = time.time() - (self.window_minutes * 60)
            windowed_metrics = [m for m in metrics if m.timestamp >= cutoff_time]

            if len(windowed_metrics) < 100:
                return None

            # Calculate statistics
            values = [m.value for m in windowed_metrics]
            values.sort()

            baseline = PerformanceBaseline(
                metric_type=metric_type,
                baseline_mean=mean(values),
                baseline_median=median(values),
                baseline_p95=values[int(len(values) * 0.95)],
                baseline_p99=values[int(len(values) * 0.99)],
                sample_count=len(values),
                established_at=time.time(),
                window_minutes=self.window_minutes,
            )

            self._baselines[metric_type] = baseline
            return baseline

    async def analyze_trends(
        self, metric_type: MetricType, window_minutes: int = 5
    ) -> Optional[TrendAnalysis]:
        """
        Analyze performance trends for a metric type.

        Args:
            metric_type: Type of metric to analyze
            window_minutes: Time window for trend analysis

        Returns:
            TrendAnalysis or None if insufficient data
        """
        async with self._lock:
            # Get baseline
            baseline = await self.establish_baseline(metric_type)
            if not baseline:
                return None

            # Get recent metrics
            cutoff_time = time.time() - (window_minutes * 60)
            metrics = list(self._metrics[metric_type])
            recent_metrics = [m for m in metrics if m.timestamp >= cutoff_time]

            if len(recent_metrics) < 10:
                return None

            # Calculate current statistics
            recent_values = [m.value for m in recent_metrics]
            current_mean = mean(recent_values)

            # Calculate degradation
            degradation_percent = (
                (current_mean - baseline.baseline_mean) / baseline.baseline_mean
            ) * 100

            # Determine trend direction
            if degradation_percent < -5:
                trend_direction = "improving"
            elif degradation_percent > 15:
                trend_direction = "degrading"
            else:
                trend_direction = "stable"

            # Calculate confidence (based on sample size and variance)
            confidence = min(len(recent_metrics) / 100, 1.0)
            if len(recent_values) > 1:
                try:
                    std = stdev(recent_values)
                    cv = std / current_mean if current_mean > 0 else 0
                    confidence *= max(0, 1 - cv)
                except Exception as e:
                    # Log statistics calculation failure - confidence will remain at base level
                    print(
                        f"⚠️  [MetricsCollector] Failed to calculate confidence statistics: {e} "
                        f"(metric: {metric_type}, sample_size: {len(recent_values)})"
                    )
                    # Don't re-raise - use base confidence level instead

            # Generate recommendations
            recommendations = []
            if trend_direction == "degrading":
                recommendations.append("Performance degradation detected")
                if degradation_percent > 20:
                    recommendations.append("Consider immediate optimization")
                    recommendations.append(
                        "Review recent changes for performance impact"
                    )
                elif degradation_percent > 15:
                    recommendations.append("Monitor closely for further degradation")
                    recommendations.append("Schedule optimization review")
            elif trend_direction == "improving":
                recommendations.append(
                    "Performance improving - recent optimizations effective"
                )

            return TrendAnalysis(
                metric_type=metric_type,
                current_mean=current_mean,
                baseline_mean=baseline.baseline_mean,
                degradation_percent=degradation_percent,
                trend_direction=trend_direction,
                confidence=confidence,
                recommendations=recommendations,
                timestamp=time.time(),
            )

    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        hit_rate = (
            (self._cache_hits / self._cache_queries * 100)
            if self._cache_queries > 0
            else 0
        )

        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "total_queries": self._cache_queries,
            "hit_rate_percent": hit_rate,
            "target_hit_rate_percent": 60,
            "meets_target": hit_rate >= 60,
        }

    def get_routing_statistics(self) -> Dict[str, Any]:
        """Get routing decision statistics."""
        success_rate = (
            (self._successful_routings / self._routing_decisions * 100)
            if self._routing_decisions > 0
            else 0
        )

        return {
            "total_decisions": self._routing_decisions,
            "successful_routings": self._successful_routings,
            "fallback_routings": self._fallback_routings,
            "success_rate_percent": success_rate,
        }

    def get_transformation_statistics(self) -> Dict[str, Any]:
        """Get agent transformation statistics."""
        success_rate = (
            (
                (self._transformations - self._transformation_failures)
                / self._transformations
                * 100
            )
            if self._transformations > 0
            else 0
        )

        return {
            "total_transformations": self._transformations,
            "successful_transformations": self._transformations
            - self._transformation_failures,
            "failed_transformations": self._transformation_failures,
            "success_rate_percent": success_rate,
        }

    async def get_recent_violations(
        self, count: int = 10, min_status: ThresholdStatus = ThresholdStatus.WARNING
    ) -> List[ThresholdViolation]:
        """
        Get recent threshold violations.

        Args:
            count: Maximum number of violations to return
            min_status: Minimum severity level to include

        Returns:
            List of recent violations
        """
        async with self._lock:
            # Filter by status
            status_priority = {
                ThresholdStatus.EMERGENCY: 4,
                ThresholdStatus.CRITICAL: 3,
                ThresholdStatus.WARNING: 2,
                ThresholdStatus.NORMAL: 1,
            }
            min_priority = status_priority[min_status]

            filtered = [
                v for v in self._violations if status_priority[v.status] >= min_priority
            ]

            # Sort by timestamp descending
            filtered.sort(key=lambda v: v.timestamp, reverse=True)

            return filtered[:count]

    async def generate_optimization_report(self) -> Dict[str, Any]:
        """
        Generate comprehensive optimization report.

        Returns:
            Report with performance metrics, trends, and recommendations
        """
        start_time = time.time()

        report = {
            "generated_at": datetime.now().isoformat(),
            "cache_statistics": self.get_cache_statistics(),
            "routing_statistics": self.get_routing_statistics(),
            "transformation_statistics": self.get_transformation_statistics(),
            "performance_trends": {},
            "recent_violations": [],
            "optimization_recommendations": [],
            "generation_time_ms": 0,
        }

        # Analyze trends for each metric type
        for metric_type in [
            MetricType.ROUTING_LATENCY,
            MetricType.CONFIDENCE_SCORE,
            MetricType.AGENT_LOADING,
            MetricType.AGENT_TRANSFORMATION,
        ]:
            trend = await self.analyze_trends(metric_type)
            if trend:
                report["performance_trends"][metric_type.value] = {
                    "current_mean": trend.current_mean,
                    "baseline_mean": trend.baseline_mean,
                    "degradation_percent": trend.degradation_percent,
                    "trend_direction": trend.trend_direction,
                    "confidence": trend.confidence,
                    "recommendations": trend.recommendations,
                }

                # Add to overall recommendations if degrading
                if trend.trend_direction == "degrading":
                    report["optimization_recommendations"].extend(trend.recommendations)

        # Get recent violations
        violations = await self.get_recent_violations(count=10)
        report["recent_violations"] = [
            {
                "threshold_id": v.threshold_id,
                "threshold_name": v.threshold_name,
                "measured_value": v.measured_value,
                "threshold_value": v.threshold_value,
                "violation_percent": v.violation_percent,
                "status": v.status.value,
                "timestamp": datetime.fromtimestamp(v.timestamp).isoformat(),
            }
            for v in violations
        ]

        # Add cache-specific recommendations
        cache_stats = report["cache_statistics"]
        if cache_stats["hit_rate_percent"] < 60:
            report["optimization_recommendations"].append(
                f"Cache hit rate ({cache_stats['hit_rate_percent']:.1f}%) below target (60%) - review caching strategy"
            )

        # Calculate report generation time
        report["generation_time_ms"] = (time.time() - start_time) * 1000

        return report

    async def flush_to_file(self):
        """Flush current metrics to file for persistence."""
        async with self._lock:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            metrics_file = self.metrics_dir / f"metrics_{timestamp}.json"

            data = {
                "timestamp": datetime.now().isoformat(),
                "cache_statistics": self.get_cache_statistics(),
                "routing_statistics": self.get_routing_statistics(),
                "transformation_statistics": self.get_transformation_statistics(),
                "metrics_summary": {
                    metric_type.value: {
                        "count": len(self._metrics[metric_type]),
                        "latest_values": [
                            {"timestamp": m.timestamp, "value": m.value}
                            for m in list(self._metrics[metric_type])[-10:]
                        ],
                    }
                    for metric_type in self._metrics.keys()
                },
                "recent_violations": [
                    {
                        "threshold_id": v.threshold_id,
                        "threshold_name": v.threshold_name,
                        "measured_value": v.measured_value,
                        "threshold_value": v.threshold_value,
                        "status": v.status.value,
                        "timestamp": v.timestamp,
                    }
                    for v in list(self._violations)[-20:]
                ],
            }

            with open(metrics_file, "w") as f:
                json.dump(data, f, indent=2)

            self._last_flush = time.time()


# Global metrics collector instance
_metrics_collector: Optional[RouterMetricsCollector] = None


def get_metrics_collector() -> RouterMetricsCollector:
    """Get or create global metrics collector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = RouterMetricsCollector()
    return _metrics_collector
