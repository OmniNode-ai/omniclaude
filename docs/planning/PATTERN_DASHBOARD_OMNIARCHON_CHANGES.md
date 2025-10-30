# Pattern Dashboard - Omniarchon Changes

**Date**: 2025-10-28
**Target Repository**: `/Volumes/PRO-G40/Code/Omniarchon`
**Service**: archon-intelligence (port 8053)
**Correlation ID**: a06eb29a-8922-4fdf-bb27-96fc40fae415

## Overview

This document specifies all changes required in the **omniarchon** repository to implement the Pattern Learning Dashboard backend.

**Total Effort**: ~48 hours (7 working days)
**Files to Modify**: 8 existing files
**Files to Create**: 5 new files
**Database Changes**: 2 schema additions

---

## File Changes Summary

### Files to Modify (8)

1. `services/intelligence/src/api/pattern_analytics/routes.py` ⭐ **Primary**
2. `services/intelligence/src/api/pattern_analytics/service.py` ⭐ **Primary**
3. `services/intelligence/src/api/pattern_analytics/models.py` ⭐ **Primary**
4. `services/intelligence/src/services/pattern_learning/phase1_foundation/storage/node_pattern_storage_effect.py`
5. `services/intelligence/src/services/pattern_learning/phase4_traceability/node_pattern_lineage_tracker_effect.py`
6. `services/intelligence/src/handlers/pattern_analytics_handler.py`
7. `services/intelligence/app.py` (for WebSocket - optional)
8. `services/intelligence/alembic/versions/` (new migration file)

### Files to Create (5)

1. `services/intelligence/src/services/pattern_learning/phase4_traceability/pattern_trend_analyzer.py` ⭐ **New Service**
2. `services/intelligence/src/services/pattern_learning/phase2_matching/pattern_comparator.py` ⭐ **New Service**
3. `services/intelligence/tests/integration/test_api_pattern_dashboard.py` **New Tests**
4. `services/intelligence/tests/unit/pattern_learning/test_pattern_trend_analyzer.py` **New Tests**
5. `services/intelligence/tests/unit/pattern_learning/test_pattern_comparator.py` **New Tests**

---

## Detailed File Changes

## 1. Pattern Analytics Routes (routes.py)

**File**: `services/intelligence/src/api/pattern_analytics/routes.py`
**Status**: Modify existing file
**Effort**: 4 hours

### New Endpoints to Add

#### Endpoint 1: Dashboard Summary

```python
@router.get(
    "/dashboard-summary",
    response_model=DashboardSummaryResponse,
    summary="Get Pattern Dashboard Summary",
    description="Aggregated metrics for pattern dashboard overview"
)
@api_error_handler("get_dashboard_summary")
async def get_dashboard_summary():
    """
    Get comprehensive dashboard summary.

    Returns:
    - Total patterns count
    - Average success rate
    - Top 10 most used patterns
    - Quality distribution
    - Recent trends
    """
    result = await pattern_analytics_service.get_dashboard_summary()
    logger.info(f"Dashboard summary generated | total_patterns={result['total_patterns']}")
    return DashboardSummaryResponse(**result)
```

#### Endpoint 2: Pattern Quality Metrics

```python
@router.get(
    "/quality-metrics",
    response_model=QualityMetricsResponse,
    summary="Get Pattern Quality Metrics",
    description="Quality scores for patterns with trend data"
)
@api_error_handler("get_quality_metrics")
async def get_quality_metrics(
    pattern_id: Optional[UUID] = Query(None, description="Specific pattern ID"),
    pattern_type: Optional[str] = Query(None, description="Filter by pattern type"),
    min_quality: float = Query(0.0, ge=0.0, le=1.0, description="Minimum quality score")
):
    """
    Get quality metrics for patterns.

    Query Parameters:
    - pattern_id: Filter to specific pattern (optional)
    - pattern_type: Filter by type (architectural, quality, etc.)
    - min_quality: Minimum quality threshold

    Returns quality scores with confidence and trends.
    """
    result = await pattern_analytics_service.get_quality_metrics(
        pattern_id=pattern_id,
        pattern_type=pattern_type,
        min_quality=min_quality
    )
    return QualityMetricsResponse(**result)
```

#### Endpoint 3: Usage Statistics

```python
@router.get(
    "/usage-stats",
    response_model=UsageStatsResponse,
    summary="Get Pattern Usage Statistics",
    description="Usage counts and frequency analysis"
)
@api_error_handler("get_usage_stats")
async def get_usage_stats(
    pattern_id: Optional[UUID] = Query(None, description="Specific pattern ID"),
    time_range: str = Query("7d", description="Time range (1d, 7d, 30d, 90d)"),
    group_by: str = Query("day", description="Grouping (hour, day, week)")
):
    """
    Get usage statistics for patterns.

    Query Parameters:
    - pattern_id: Filter to specific pattern (optional)
    - time_range: Time window for analysis
    - group_by: Aggregation granularity

    Returns usage counts per time period.
    """
    result = await pattern_analytics_service.get_usage_stats(
        pattern_id=pattern_id,
        time_range=time_range,
        group_by=group_by
    )
    return UsageStatsResponse(**result)
```

#### Endpoint 4: Trend Analysis

```python
@router.get(
    "/trends",
    response_model=TrendAnalysisResponse,
    summary="Get Pattern Trends",
    description="Trend analysis for quality, usage, and performance"
)
@api_error_handler("get_pattern_trends")
async def get_pattern_trends(
    trend_type: str = Query("usage", description="Trend type (usage, quality, performance)"),
    pattern_id: Optional[UUID] = Query(None, description="Specific pattern ID"),
    time_range: str = Query("30d", description="Analysis time window")
):
    """
    Analyze trends for patterns.

    Query Parameters:
    - trend_type: Type of trend to analyze
    - pattern_id: Filter to specific pattern (optional)
    - time_range: Time window for trend analysis

    Returns:
    - Trend direction (increasing, decreasing, stable)
    - Trend velocity (rate of change)
    - Predictions (if applicable)
    """
    result = await pattern_analytics_service.get_pattern_trends(
        trend_type=trend_type,
        pattern_id=pattern_id,
        time_range=time_range
    )
    return TrendAnalysisResponse(**result)
```

#### Endpoint 5: Pattern Comparison

```python
@router.post(
    "/compare",
    response_model=PatternComparisonResponse,
    summary="Compare Multiple Patterns",
    description="Side-by-side comparison of pattern metrics"
)
@api_error_handler("compare_patterns")
async def compare_patterns(request: PatternComparisonRequest):
    """
    Compare multiple patterns.

    Body:
    - pattern_ids: List of pattern UUIDs to compare (2-10)
    - metrics: Metrics to compare (quality, usage, success_rate, etc.)

    Returns comparison matrix with statistical analysis.
    """
    result = await pattern_analytics_service.compare_patterns(
        pattern_ids=request.pattern_ids,
        metrics=request.metrics
    )
    return PatternComparisonResponse(**result)
```

#### Endpoint 6: Time Series Data

```python
@router.get(
    "/time-series",
    response_model=TimeSeriesResponse,
    summary="Get Time Series Data",
    description="Time series data for charts and visualizations"
)
@api_error_handler("get_time_series")
async def get_time_series(
    pattern_id: UUID = Query(..., description="Pattern ID"),
    metric: str = Query("usage", description="Metric to retrieve (usage, quality, success_rate)"),
    time_range: str = Query("30d", description="Time range"),
    granularity: str = Query("day", description="Data point granularity")
):
    """
    Get time series data for pattern metrics.

    Returns array of {timestamp, value} pairs for charting.
    """
    result = await pattern_analytics_service.get_time_series(
        pattern_id=pattern_id,
        metric=metric,
        time_range=time_range,
        granularity=granularity
    )
    return TimeSeriesResponse(**result)
```

#### Endpoint 7: Real-Time Stream (SSE)

```python
@router.get(
    "/stream",
    summary="Real-Time Pattern Metrics Stream",
    description="Server-Sent Events stream for real-time dashboard updates"
)
async def stream_pattern_metrics(
    request: Request,
    pattern_ids: Optional[str] = Query(None, description="Comma-separated pattern IDs to watch")
):
    """
    Stream real-time pattern metric updates.

    Uses Server-Sent Events (SSE) for push updates.
    Client receives updates when metrics change.

    Example:
        EventSource: /api/pattern-analytics/stream?pattern_ids=uuid1,uuid2
    """
    async def event_generator():
        try:
            pattern_id_list = pattern_ids.split(",") if pattern_ids else None

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                # Get latest metrics
                metrics = await pattern_analytics_service.get_realtime_metrics(
                    pattern_ids=pattern_id_list
                )

                # Send SSE event
                yield {
                    "event": "metrics_update",
                    "data": json.dumps(metrics)
                }

                # Wait before next update
                await asyncio.sleep(5)  # 5 second refresh

        except asyncio.CancelledError:
            logger.info("SSE client disconnected")

    return EventSourceResponse(event_generator())
```

---

## 2. Pattern Analytics Service (service.py)

**File**: `services/intelligence/src/api/pattern_analytics/service.py`
**Status**: Modify existing file
**Effort**: 8 hours

### New Methods to Add

```python
class PatternAnalyticsService:
    """Service for pattern analytics operations."""

    # ... existing methods ...

    async def get_dashboard_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive dashboard summary.

        Returns:
            Dictionary with:
            - total_patterns: Total pattern count
            - average_success_rate: Mean success rate across all patterns
            - top_patterns: Top 10 most used patterns
            - quality_distribution: Distribution of quality scores
            - recent_trends: Emerging/declining patterns
        """
        # Query total patterns
        total_patterns = await self._count_total_patterns()

        # Calculate average success rate
        avg_success_rate = await self._calculate_average_success_rate()

        # Get top 10 patterns by usage
        top_patterns = await self.get_top_performing_patterns(limit=10)

        # Get quality distribution
        quality_dist = await self._get_quality_distribution()

        # Get recent trends (last 7 days)
        trends = await self._get_recent_trends(days=7)

        return {
            "total_patterns": total_patterns,
            "average_success_rate": avg_success_rate,
            "top_patterns": top_patterns,
            "quality_distribution": quality_dist,
            "recent_trends": trends,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

    async def get_quality_metrics(
        self,
        pattern_id: Optional[UUID] = None,
        pattern_type: Optional[str] = None,
        min_quality: float = 0.0
    ) -> Dict[str, Any]:
        """
        Get quality metrics for patterns.

        Args:
            pattern_id: Filter to specific pattern
            pattern_type: Filter by pattern type
            min_quality: Minimum quality threshold

        Returns:
            Quality metrics with trends
        """
        # Build query
        query = """
            SELECT
                p.id,
                p.name,
                p.pattern_type,
                pqm.quality_score,
                pqm.confidence,
                pqm.measurement_timestamp,
                COUNT(*) OVER (PARTITION BY p.id) as measurement_count
            FROM patterns p
            JOIN pattern_quality_metrics pqm ON p.id = pqm.pattern_id
            WHERE pqm.quality_score >= $1
        """

        params = [min_quality]

        if pattern_id:
            query += " AND p.id = $2"
            params.append(pattern_id)

        if pattern_type:
            param_idx = len(params) + 1
            query += f" AND p.pattern_type = ${param_idx}"
            params.append(pattern_type)

        query += " ORDER BY pqm.measurement_timestamp DESC"

        results = await self.db.fetch(query, *params)

        # Group by pattern and calculate trends
        patterns = {}
        for row in results:
            pid = row['id']
            if pid not in patterns:
                patterns[pid] = {
                    "pattern_id": pid,
                    "pattern_name": row['name'],
                    "pattern_type": row['pattern_type'],
                    "measurements": []
                }

            patterns[pid]['measurements'].append({
                "quality_score": row['quality_score'],
                "confidence": row['confidence'],
                "timestamp": row['measurement_timestamp']
            })

        # Calculate trends for each pattern
        for pattern_data in patterns.values():
            pattern_data['trend'] = self._calculate_trend(
                pattern_data['measurements']
            )

        return {
            "patterns": list(patterns.values()),
            "total_count": len(patterns)
        }

    async def get_usage_stats(
        self,
        pattern_id: Optional[UUID] = None,
        time_range: str = "7d",
        group_by: str = "day"
    ) -> Dict[str, Any]:
        """
        Get usage statistics for patterns.

        Args:
            pattern_id: Filter to specific pattern
            time_range: Time window (1d, 7d, 30d, 90d)
            group_by: Aggregation granularity (hour, day, week)

        Returns:
            Usage counts per time period
        """
        # Parse time range
        days = self._parse_time_range(time_range)
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        # Determine grouping interval
        interval_mapping = {
            "hour": "1 hour",
            "day": "1 day",
            "week": "1 week"
        }
        interval = interval_mapping.get(group_by, "1 day")

        # Query usage stats
        query = """
            SELECT
                p.id,
                p.name,
                time_bucket($1::interval, pf.created_at) as time_bucket,
                COUNT(*) as usage_count
            FROM patterns p
            JOIN pattern_feedback pf ON p.id = pf.pattern_id
            WHERE pf.created_at >= $2
        """

        params = [interval, start_date]

        if pattern_id:
            query += " AND p.id = $3"
            params.append(pattern_id)

        query += " GROUP BY p.id, p.name, time_bucket ORDER BY time_bucket"

        results = await self.db.fetch(query, *params)

        # Group by pattern
        patterns = {}
        for row in results:
            pid = row['id']
            if pid not in patterns:
                patterns[pid] = {
                    "pattern_id": pid,
                    "pattern_name": row['name'],
                    "usage_data": []
                }

            patterns[pid]['usage_data'].append({
                "timestamp": row['time_bucket'],
                "count": row['usage_count']
            })

        return {
            "patterns": list(patterns.values()),
            "time_range": time_range,
            "granularity": group_by
        }

    async def get_pattern_trends(
        self,
        trend_type: str,
        pattern_id: Optional[UUID] = None,
        time_range: str = "30d"
    ) -> Dict[str, Any]:
        """
        Analyze trends for patterns.

        Args:
            trend_type: Type of trend (usage, quality, performance)
            pattern_id: Filter to specific pattern
            time_range: Analysis time window

        Returns:
            Trend analysis results
        """
        from .pattern_trend_analyzer import PatternTrendAnalyzer

        analyzer = PatternTrendAnalyzer(self.db)

        if trend_type == "usage":
            trends = await analyzer.analyze_usage_trends(
                pattern_id=pattern_id,
                time_range=time_range
            )
        elif trend_type == "quality":
            trends = await analyzer.analyze_quality_trends(
                pattern_id=pattern_id,
                time_range=time_range
            )
        elif trend_type == "performance":
            trends = await analyzer.analyze_performance_trends(
                pattern_id=pattern_id,
                time_range=time_range
            )
        else:
            raise ValueError(f"Unknown trend type: {trend_type}")

        return trends

    async def compare_patterns(
        self,
        pattern_ids: List[UUID],
        metrics: List[str]
    ) -> Dict[str, Any]:
        """
        Compare multiple patterns.

        Args:
            pattern_ids: List of pattern UUIDs to compare (2-10)
            metrics: Metrics to compare

        Returns:
            Comparison matrix with statistical analysis
        """
        from .pattern_comparator import PatternComparator

        if len(pattern_ids) < 2:
            raise ValueError("At least 2 patterns required for comparison")
        if len(pattern_ids) > 10:
            raise ValueError("Maximum 10 patterns for comparison")

        comparator = PatternComparator(self.db)

        comparison = await comparator.compare_patterns(
            pattern_ids=pattern_ids,
            metrics=metrics
        )

        return comparison

    async def get_time_series(
        self,
        pattern_id: UUID,
        metric: str,
        time_range: str,
        granularity: str
    ) -> Dict[str, Any]:
        """
        Get time series data for pattern metrics.

        Args:
            pattern_id: Pattern UUID
            metric: Metric to retrieve
            time_range: Time range
            granularity: Data point granularity

        Returns:
            Time series data array
        """
        days = self._parse_time_range(time_range)
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        # Query based on metric type
        if metric == "usage":
            query = """
                SELECT
                    time_bucket($1::interval, created_at) as timestamp,
                    COUNT(*) as value
                FROM pattern_feedback
                WHERE pattern_id = $2 AND created_at >= $3
                GROUP BY timestamp
                ORDER BY timestamp
            """
        elif metric == "quality":
            query = """
                SELECT
                    measurement_timestamp as timestamp,
                    quality_score as value
                FROM pattern_quality_metrics
                WHERE pattern_id = $1 AND measurement_timestamp >= $2
                ORDER BY timestamp
            """
        elif metric == "success_rate":
            query = """
                SELECT
                    time_bucket($1::interval, created_at) as timestamp,
                    AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) as value
                FROM pattern_feedback
                WHERE pattern_id = $2 AND created_at >= $3
                GROUP BY timestamp
                ORDER BY timestamp
            """

        # Execute query and return data
        results = await self.db.fetch(query, granularity, pattern_id, start_date)

        return {
            "pattern_id": pattern_id,
            "metric": metric,
            "time_range": time_range,
            "granularity": granularity,
            "data": [
                {"timestamp": row['timestamp'], "value": row['value']}
                for row in results
            ]
        }

    async def get_realtime_metrics(
        self,
        pattern_ids: Optional[List[UUID]] = None
    ) -> Dict[str, Any]:
        """
        Get real-time metrics for SSE streaming.

        Args:
            pattern_ids: Optional filter to specific patterns

        Returns:
            Current metrics snapshot
        """
        # Get latest metrics
        query = """
            SELECT
                p.id,
                p.name,
                COUNT(pf.id) as usage_count,
                AVG(CASE WHEN pf.success THEN 1.0 ELSE 0.0 END) as success_rate,
                MAX(pqm.quality_score) as latest_quality
            FROM patterns p
            LEFT JOIN pattern_feedback pf ON p.id = pf.pattern_id
                AND pf.created_at >= NOW() - INTERVAL '5 minutes'
            LEFT JOIN pattern_quality_metrics pqm ON p.id = pqm.pattern_id
            WHERE 1=1
        """

        params = []
        if pattern_ids:
            query += " AND p.id = ANY($1)"
            params.append(pattern_ids)

        query += " GROUP BY p.id, p.name"

        results = await self.db.fetch(query, *params)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "patterns": [
                {
                    "pattern_id": row['id'],
                    "pattern_name": row['name'],
                    "usage_count_last_5min": row['usage_count'],
                    "success_rate": row['success_rate'],
                    "latest_quality": row['latest_quality']
                }
                for row in results
            ]
        }

    # Helper methods

    def _parse_time_range(self, time_range: str) -> int:
        """Parse time range string to days."""
        mapping = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}
        return mapping.get(time_range, 7)

    def _calculate_trend(self, measurements: List[Dict]) -> Dict[str, Any]:
        """Calculate trend from measurements using linear regression."""
        if len(measurements) < 2:
            return {"direction": "insufficient_data"}

        # Simple linear regression
        n = len(measurements)
        x = list(range(n))
        y = [m['quality_score'] for m in measurements]

        x_mean = sum(x) / n
        y_mean = sum(y) / n

        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return {"direction": "stable", "velocity": 0.0}

        slope = numerator / denominator

        # Determine direction
        if abs(slope) < 0.01:
            direction = "stable"
        elif slope > 0:
            direction = "increasing"
        else:
            direction = "decreasing"

        return {
            "direction": direction,
            "velocity": abs(slope),
            "slope": slope
        }
```

---

## 3. Pattern Analytics Models (models.py)

**File**: `services/intelligence/src/api/pattern_analytics/models.py`
**Status**: Modify existing file
**Effort**: 3 hours

### New Response Models to Add

```python
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID


class QualityMetric(BaseModel):
    """Quality metric for a pattern."""
    quality_score: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    timestamp: datetime


class PatternQualityData(BaseModel):
    """Quality data for a single pattern."""
    pattern_id: UUID
    pattern_name: str
    pattern_type: str
    measurements: List[QualityMetric]
    trend: Dict[str, Any]  # direction, velocity, slope


class QualityMetricsResponse(BaseModel):
    """Response for quality metrics endpoint."""
    patterns: List[PatternQualityData]
    total_count: int


class UsageDataPoint(BaseModel):
    """Single usage data point."""
    timestamp: datetime
    count: int


class PatternUsageData(BaseModel):
    """Usage data for a single pattern."""
    pattern_id: UUID
    pattern_name: str
    usage_data: List[UsageDataPoint]


class UsageStatsResponse(BaseModel):
    """Response for usage stats endpoint."""
    patterns: List[PatternUsageData]
    time_range: str
    granularity: str


class TrendAnalysis(BaseModel):
    """Trend analysis result."""
    pattern_id: UUID
    pattern_name: str
    trend_type: str
    direction: str  # increasing, decreasing, stable, insufficient_data
    velocity: float  # rate of change
    confidence: float
    prediction: Optional[Dict[str, Any]] = None


class TrendAnalysisResponse(BaseModel):
    """Response for trend analysis endpoint."""
    trends: List[TrendAnalysis]
    time_range: str


class PatternComparisonMetric(BaseModel):
    """Single metric comparison."""
    metric_name: str
    values: Dict[UUID, float]  # pattern_id -> value
    statistics: Dict[str, float]  # mean, median, std_dev


class PatternComparisonRequest(BaseModel):
    """Request for pattern comparison."""
    pattern_ids: List[UUID] = Field(..., min_items=2, max_items=10)
    metrics: List[str] = Field(default=["quality", "usage", "success_rate"])


class PatternComparisonResponse(BaseModel):
    """Response for pattern comparison."""
    patterns: List[Dict[str, Any]]  # Pattern metadata
    comparisons: List[PatternComparisonMetric]
    rankings: Dict[str, List[UUID]]  # metric -> ranked pattern_ids


class TimeSeriesDataPoint(BaseModel):
    """Single time series data point."""
    timestamp: datetime
    value: float


class TimeSeriesResponse(BaseModel):
    """Response for time series endpoint."""
    pattern_id: UUID
    metric: str
    time_range: str
    granularity: str
    data: List[TimeSeriesDataPoint]


class QualityDistribution(BaseModel):
    """Quality score distribution."""
    range: str  # "0.0-0.2", "0.2-0.4", etc.
    count: int
    percentage: float


class RecentTrend(BaseModel):
    """Recent trend summary."""
    trend_type: str  # emerging, declining, stable
    patterns: List[Dict[str, Any]]
    count: int


class DashboardSummaryResponse(BaseModel):
    """Response for dashboard summary endpoint."""
    total_patterns: int
    average_success_rate: float
    top_patterns: List[Dict[str, Any]]
    quality_distribution: List[QualityDistribution]
    recent_trends: List[RecentTrend]
    generated_at: datetime
```

---

## 4. Pattern Trend Analyzer (NEW FILE)

**File**: `services/intelligence/src/services/pattern_learning/phase4_traceability/pattern_trend_analyzer.py`
**Status**: Create new file
**Effort**: 6 hours

```python
"""
Pattern Trend Analyzer

Statistical analysis of pattern trends over time.
Detects emerging/declining patterns and calculates trend metrics.

ONEX v2.0 Compliance:
- Compute node for trend calculation
- Type-safe trend models
- Performance tracking (<500ms target)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import numpy as np
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TrendDirection(str):
    """Trend direction enumeration."""
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    INSUFFICIENT_DATA = "insufficient_data"


class TrendMetrics(BaseModel):
    """Trend analysis metrics."""
    direction: str
    velocity: float  # Rate of change
    confidence: float  # Statistical confidence
    slope: float  # Linear regression slope
    r_squared: float  # Goodness of fit
    prediction: Optional[float] = None  # Next period prediction


class PatternTrendAnalyzer:
    """
    Analyze trends for pattern metrics.

    Provides:
    - Usage trend analysis
    - Quality trend analysis
    - Performance trend analysis
    - Emerging pattern detection
    - Declining pattern detection
    """

    def __init__(self, db_connection):
        """
        Initialize trend analyzer.

        Args:
            db_connection: Database connection for queries
        """
        self.db = db_connection

    async def analyze_usage_trends(
        self,
        pattern_id: Optional[UUID] = None,
        time_range: str = "30d"
    ) -> Dict[str, Any]:
        """
        Analyze usage trends for patterns.

        Args:
            pattern_id: Filter to specific pattern (optional)
            time_range: Time window for analysis

        Returns:
            Trend analysis results with direction, velocity, predictions
        """
        days = self._parse_time_range(time_range)
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        # Query usage data
        query = """
            SELECT
                p.id,
                p.name,
                time_bucket('1 day', pf.created_at) as day,
                COUNT(*) as usage_count
            FROM patterns p
            JOIN pattern_feedback pf ON p.id = pf.pattern_id
            WHERE pf.created_at >= $1
        """

        params = [start_date]

        if pattern_id:
            query += " AND p.id = $2"
            params.append(pattern_id)

        query += " GROUP BY p.id, p.name, day ORDER BY p.id, day"

        results = await self.db.fetch(query, *params)

        # Group by pattern and analyze trends
        patterns = {}
        for row in results:
            pid = row['id']
            if pid not in patterns:
                patterns[pid] = {
                    "pattern_id": pid,
                    "pattern_name": row['name'],
                    "data_points": []
                }

            patterns[pid]['data_points'].append({
                "timestamp": row['day'],
                "value": row['usage_count']
            })

        # Calculate trends for each pattern
        trends = []
        for pattern_data in patterns.values():
            metrics = self._calculate_trend_metrics(
                pattern_data['data_points']
            )

            trends.append({
                "pattern_id": pattern_data['pattern_id'],
                "pattern_name": pattern_data['pattern_name'],
                "trend_type": "usage",
                "direction": metrics.direction,
                "velocity": metrics.velocity,
                "confidence": metrics.confidence,
                "prediction": metrics.prediction
            })

        return {
            "trends": trends,
            "time_range": time_range
        }

    async def analyze_quality_trends(
        self,
        pattern_id: Optional[UUID] = None,
        time_range: str = "30d"
    ) -> Dict[str, Any]:
        """
        Analyze quality trends for patterns.

        Args:
            pattern_id: Filter to specific pattern (optional)
            time_range: Time window for analysis

        Returns:
            Quality trend analysis results
        """
        days = self._parse_time_range(time_range)
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        # Query quality metrics
        query = """
            SELECT
                p.id,
                p.name,
                pqm.measurement_timestamp,
                pqm.quality_score
            FROM patterns p
            JOIN pattern_quality_metrics pqm ON p.id = pqm.pattern_id
            WHERE pqm.measurement_timestamp >= $1
        """

        params = [start_date]

        if pattern_id:
            query += " AND p.id = $2"
            params.append(pattern_id)

        query += " ORDER BY p.id, pqm.measurement_timestamp"

        results = await self.db.fetch(query, *params)

        # Group and analyze
        patterns = {}
        for row in results:
            pid = row['id']
            if pid not in patterns:
                patterns[pid] = {
                    "pattern_id": pid,
                    "pattern_name": row['name'],
                    "data_points": []
                }

            patterns[pid]['data_points'].append({
                "timestamp": row['measurement_timestamp'],
                "value": row['quality_score']
            })

        trends = []
        for pattern_data in patterns.values():
            metrics = self._calculate_trend_metrics(
                pattern_data['data_points']
            )

            trends.append({
                "pattern_id": pattern_data['pattern_id'],
                "pattern_name": pattern_data['pattern_name'],
                "trend_type": "quality",
                "direction": metrics.direction,
                "velocity": metrics.velocity,
                "confidence": metrics.confidence,
                "prediction": metrics.prediction
            })

        return {
            "trends": trends,
            "time_range": time_range
        }

    async def detect_emerging_patterns(
        self,
        time_window: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Detect emerging patterns (significant usage increase).

        Args:
            time_window: Days to analyze

        Returns:
            List of emerging patterns with growth metrics
        """
        # Compare recent window to previous window
        recent_start = datetime.now(timezone.utc) - timedelta(days=time_window)
        previous_start = recent_start - timedelta(days=time_window)

        query = """
            WITH recent_usage AS (
                SELECT
                    pattern_id,
                    COUNT(*) as recent_count
                FROM pattern_feedback
                WHERE created_at >= $1
                GROUP BY pattern_id
            ),
            previous_usage AS (
                SELECT
                    pattern_id,
                    COUNT(*) as previous_count
                FROM pattern_feedback
                WHERE created_at >= $2 AND created_at < $1
                GROUP BY pattern_id
            )
            SELECT
                p.id,
                p.name,
                COALESCE(ru.recent_count, 0) as recent_count,
                COALESCE(pu.previous_count, 0) as previous_count,
                CASE
                    WHEN pu.previous_count > 0
                    THEN (ru.recent_count - pu.previous_count)::float / pu.previous_count
                    ELSE NULL
                END as growth_rate
            FROM patterns p
            LEFT JOIN recent_usage ru ON p.id = ru.pattern_id
            LEFT JOIN previous_usage pu ON p.id = pu.pattern_id
            WHERE ru.recent_count > 0
            ORDER BY growth_rate DESC NULLS LAST
            LIMIT 20
        """

        results = await self.db.fetch(query, recent_start, previous_start)

        emerging = []
        for row in results:
            if row['growth_rate'] and row['growth_rate'] > 0.5:  # 50% increase
                emerging.append({
                    "pattern_id": row['id'],
                    "pattern_name": row['name'],
                    "recent_usage": row['recent_count'],
                    "previous_usage": row['previous_count'],
                    "growth_rate": row['growth_rate']
                })

        return emerging

    async def identify_declining_patterns(
        self,
        threshold: float = -0.3
    ) -> List[Dict[str, Any]]:
        """
        Identify declining patterns (significant usage decrease).

        Args:
            threshold: Decline threshold (default: -30%)

        Returns:
            List of declining patterns
        """
        time_window = 7
        recent_start = datetime.now(timezone.utc) - timedelta(days=time_window)
        previous_start = recent_start - timedelta(days=time_window)

        query = """
            WITH recent_usage AS (
                SELECT
                    pattern_id,
                    COUNT(*) as recent_count
                FROM pattern_feedback
                WHERE created_at >= $1
                GROUP BY pattern_id
            ),
            previous_usage AS (
                SELECT
                    pattern_id,
                    COUNT(*) as previous_count
                FROM pattern_feedback
                WHERE created_at >= $2 AND created_at < $1
                GROUP BY pattern_id
            )
            SELECT
                p.id,
                p.name,
                COALESCE(ru.recent_count, 0) as recent_count,
                COALESCE(pu.previous_count, 0) as previous_count,
                CASE
                    WHEN pu.previous_count > 0
                    THEN (ru.recent_count - pu.previous_count)::float / pu.previous_count
                    ELSE NULL
                END as decline_rate
            FROM patterns p
            LEFT JOIN recent_usage ru ON p.id = ru.pattern_id
            LEFT JOIN previous_usage pu ON p.id = pu.pattern_id
            WHERE pu.previous_count > 0
            ORDER BY decline_rate ASC NULLS LAST
            LIMIT 20
        """

        results = await self.db.fetch(query, recent_start, previous_start)

        declining = []
        for row in results:
            if row['decline_rate'] and row['decline_rate'] < threshold:
                declining.append({
                    "pattern_id": row['id'],
                    "pattern_name": row['name'],
                    "recent_usage": row['recent_count'],
                    "previous_usage": row['previous_count'],
                    "decline_rate": row['decline_rate']
                })

        return declining

    def _calculate_trend_metrics(
        self,
        data_points: List[Dict[str, Any]]
    ) -> TrendMetrics:
        """
        Calculate trend metrics using linear regression.

        Args:
            data_points: List of {timestamp, value} dicts

        Returns:
            TrendMetrics with direction, velocity, confidence
        """
        if len(data_points) < 3:
            return TrendMetrics(
                direction=TrendDirection.INSUFFICIENT_DATA,
                velocity=0.0,
                confidence=0.0,
                slope=0.0,
                r_squared=0.0
            )

        # Extract values
        n = len(data_points)
        x = np.array(range(n), dtype=float)
        y = np.array([dp['value'] for dp in data_points], dtype=float)

        # Linear regression
        x_mean = np.mean(x)
        y_mean = np.mean(y)

        numerator = np.sum((x - x_mean) * (y - y_mean))
        denominator = np.sum((x - x_mean) ** 2)

        if denominator == 0:
            slope = 0.0
        else:
            slope = numerator / denominator

        intercept = y_mean - slope * x_mean

        # R-squared (goodness of fit)
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y_mean) ** 2)

        if ss_tot == 0:
            r_squared = 1.0
        else:
            r_squared = 1 - (ss_res / ss_tot)

        # Determine direction
        threshold = 0.01 * np.mean(y)  # 1% of mean value

        if abs(slope) < threshold:
            direction = TrendDirection.STABLE
        elif slope > 0:
            direction = TrendDirection.INCREASING
        else:
            direction = TrendDirection.DECREASING

        # Velocity (absolute rate of change)
        velocity = abs(slope)

        # Confidence (based on R-squared)
        confidence = max(0.0, min(1.0, r_squared))

        # Prediction (next time point)
        prediction = slope * n + intercept

        return TrendMetrics(
            direction=direction,
            velocity=velocity,
            confidence=confidence,
            slope=slope,
            r_squared=r_squared,
            prediction=prediction if prediction > 0 else None
        )

    def _parse_time_range(self, time_range: str) -> int:
        """Parse time range string to days."""
        mapping = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}
        return mapping.get(time_range, 30)
```

---

(Continued in next message due to length limits...)

## Database Schema Changes

### Migration File

**File**: `services/intelligence/alembic/versions/YYYYMMDD_pattern_dashboard_schema.py`
**Status**: Create new migration
**Effort**: 2 hours

```python
"""Pattern Dashboard Schema

Revision ID: pattern_dashboard_001
Revises: previous_revision
Create Date: 2025-10-28

Add schema for pattern dashboard metrics:
- pattern_quality_metrics table
- Indexes for trend queries
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'pattern_dashboard_001'
down_revision = 'previous_revision'  # Update with actual previous revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create pattern_quality_metrics table
    op.create_table(
        'pattern_quality_metrics',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('pattern_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('quality_score', sa.Float, nullable=False),
        sa.Column('confidence', sa.Float, nullable=False),
        sa.Column('measurement_timestamp', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('version', sa.String(50), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['pattern_id'], ['patterns.id'], ondelete='CASCADE')
    )

    # Create indexes for performance
    op.create_index(
        'idx_pattern_quality_metrics_pattern_id',
        'pattern_quality_metrics',
        ['pattern_id']
    )

    op.create_index(
        'idx_pattern_quality_metrics_timestamp',
        'pattern_quality_metrics',
        ['measurement_timestamp']
    )

    # Create index on pattern_feedback for trend queries
    op.create_index(
        'idx_pattern_feedback_created_at',
        'pattern_feedback',
        ['created_at']
    )

    # Create index for pattern_type filtering
    op.create_index(
        'idx_patterns_pattern_type',
        'patterns',
        ['pattern_type']
    )


def downgrade() -> None:
    op.drop_index('idx_patterns_pattern_type', table_name='patterns')
    op.drop_index('idx_pattern_feedback_created_at', table_name='pattern_feedback')
    op.drop_index('idx_pattern_quality_metrics_timestamp', table_name='pattern_quality_metrics')
    op.drop_index('idx_pattern_quality_metrics_pattern_id', table_name='pattern_quality_metrics')
    op.drop_table('pattern_quality_metrics')
```

---

## Testing Requirements

### Integration Tests

**File**: `services/intelligence/tests/integration/test_api_pattern_dashboard.py`
**Status**: Create new file
**Effort**: 4 hours

```python
"""
Integration tests for Pattern Dashboard APIs.

Tests all dashboard endpoints end-to-end with real database.
"""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4


@pytest.mark.asyncio
async def test_dashboard_summary(test_client, db_with_patterns):
    """Test dashboard summary endpoint."""
    response = await test_client.get("/api/pattern-analytics/dashboard-summary")

    assert response.status_code == 200
    data = response.json()

    assert "total_patterns" in data
    assert "average_success_rate" in data
    assert "top_patterns" in data
    assert "quality_distribution" in data
    assert "recent_trends" in data


@pytest.mark.asyncio
async def test_quality_metrics(test_client, db_with_patterns):
    """Test quality metrics endpoint."""
    response = await test_client.get(
        "/api/pattern-analytics/quality-metrics",
        params={"min_quality": 0.7}
    )

    assert response.status_code == 200
    data = response.json()

    assert "patterns" in data
    assert all(p["measurements"][0]["quality_score"] >= 0.7 for p in data["patterns"] if p["measurements"])


@pytest.mark.asyncio
async def test_usage_stats(test_client, db_with_patterns):
    """Test usage statistics endpoint."""
    response = await test_client.get(
        "/api/pattern-analytics/usage-stats",
        params={"time_range": "7d", "group_by": "day"}
    )

    assert response.status_code == 200
    data = response.json()

    assert data["time_range"] == "7d"
    assert data["granularity"] == "day"
    assert "patterns" in data


@pytest.mark.asyncio
async def test_trend_analysis(test_client, db_with_patterns):
    """Test trend analysis endpoint."""
    response = await test_client.get(
        "/api/pattern-analytics/trends",
        params={"trend_type": "usage", "time_range": "30d"}
    )

    assert response.status_code == 200
    data = response.json()

    assert "trends" in data
    assert data["time_range"] == "30d"


@pytest.mark.asyncio
async def test_pattern_comparison(test_client, db_with_patterns):
    """Test pattern comparison endpoint."""
    pattern_ids = [str(uuid4()), str(uuid4())]

    response = await test_client.post(
        "/api/pattern-analytics/compare",
        json={
            "pattern_ids": pattern_ids,
            "metrics": ["quality", "usage"]
        }
    )

    assert response.status_code == 200
    data = response.json()

    assert "patterns" in data
    assert "comparisons" in data
    assert "rankings" in data


@pytest.mark.asyncio
async def test_time_series(test_client, db_with_patterns):
    """Test time series endpoint."""
    pattern_id = str(uuid4())

    response = await test_client.get(
        "/api/pattern-analytics/time-series",
        params={
            "pattern_id": pattern_id,
            "metric": "usage",
            "time_range": "30d",
            "granularity": "day"
        }
    )

    assert response.status_code == 200
    data = response.json()

    assert data["pattern_id"] == pattern_id
    assert data["metric"] == "usage"
    assert "data" in data
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] Code review completed
- [ ] Unit tests passing (100% coverage target)
- [ ] Integration tests passing
- [ ] Performance benchmarks run and documented
- [ ] API documentation updated
- [ ] Database migration tested on staging
- [ ] Backward compatibility verified

### Deployment Steps

1. **Run Database Migration**:
   ```bash
   docker exec -it archon-intelligence alembic upgrade head
   ```

2. **Rebuild Container**:
   ```bash
   cd /Volumes/PRO-G40/Code/Omniarchon/deployment
   docker-compose up -d --build archon-intelligence
   ```

3. **Verify Health**:
   ```bash
   curl http://localhost:8053/health
   ```

4. **Test New Endpoints**:
   ```bash
   curl http://localhost:8053/api/pattern-analytics/dashboard-summary
   curl http://localhost:8053/api/pattern-analytics/quality-metrics
   curl http://localhost:8053/api/pattern-analytics/usage-stats
   ```

5. **Monitor Logs**:
   ```bash
   docker logs -f archon-intelligence
   ```

### Post-Deployment

- [ ] All endpoints responding successfully
- [ ] Dashboard data loading correctly
- [ ] No errors in logs
- [ ] Performance metrics within SLAs
- [ ] Real-time updates working (if implemented)

---

## Performance Targets

| Metric | Target | Critical |
|--------|--------|----------|
| Dashboard summary | <500ms | >2s |
| Quality metrics | <200ms | >1s |
| Usage stats | <300ms | >1s |
| Trend analysis | <500ms | >2s |
| Pattern comparison | <400ms | >1.5s |
| Time series | <200ms | >1s |
| Real-time update latency | <1s | >5s |

---

## Summary

**Files to Modify**: 8
**Files to Create**: 5
**Total Effort**: ~48 hours (7 working days)

**Critical Path**:
1. Database migration (2h)
2. Service layer methods (8h)
3. API routes (4h)
4. Testing (4h)

**Key Dependencies**:
- PostgreSQL with TimescaleDB (for time_bucket)
- Existing pattern_feedback table
- Existing patterns table

**Deployment Risk**: Low (backward compatible, new endpoints only)

**Next Steps**:
1. Review this plan with team
2. Create detailed tickets in issue tracker
3. Set up development environment
4. Begin Phase 1 implementation
