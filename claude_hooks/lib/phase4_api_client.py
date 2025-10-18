"""
Phase 4 Pattern Traceability API Client

Resilient HTTP client for interacting with Intelligence Service Phase 4 APIs:
- Pattern lineage tracking (POST /lineage/track, GET /lineage/{id})
- Usage analytics (POST /analytics/compute, GET /analytics/{id})
- Feedback loop (POST /feedback/analyze, POST /feedback/apply)
- Search and validation endpoints
- Health monitoring

Key Features:
- 2-second timeout with exponential backoff retry (3 attempts)
- Graceful degradation (returns {"success": False, "error": ...} on failure)
- All 7 Phase 4 endpoints implemented
- Async-first design with httpx.AsyncClient

Designed for Claude Code hooks and PatternTracker integration.
"""

import httpx
import asyncio
import logging
import sys
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime

logger = logging.getLogger(__name__)


class Phase4APIClient:
    """
    Resilient async client for Phase 4 Pattern Traceability APIs.

    Features:
    - Configurable timeout (default: 2.0s for production use)
    - Exponential backoff retry (3 attempts: 1s, 2s, 4s)
    - Graceful error handling (never raises to caller)
    - Context manager support for proper cleanup

    Example:
        ```python
        async with Phase4APIClient(timeout=2.0) as client:
            # Track pattern creation
            result = await client.track_lineage(
                event_type="pattern_created",
                pattern_id="abc123def456",
                pattern_name="UserAuthHandler",
                pattern_type="code",
                pattern_version="1.0.0",
                pattern_data={"code": "...", "language": "python"},
                triggered_by="pre-commit-hook"
            )

            if result["success"]:
                print(f"Tracked lineage: {result['data']['lineage_id']}")
            else:
                print(f"Failed gracefully: {result['error']}")
        ```
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8053",
        timeout: float = 2.0,
        max_retries: int = 3,
        api_key: Optional[str] = None,
    ):
        """
        Initialize Phase 4 API client.

        Args:
            base_url: Intelligence Service base URL (default: http://localhost:8053)
            timeout: Request timeout in seconds (default: 2.0 for production)
            max_retries: Maximum retry attempts (default: 3)
            api_key: Optional API key for authentication
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.api_key = api_key

        # HTTP client (initialized in __aenter__)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Async context manager entry - initializes HTTP client"""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, headers=headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - closes HTTP client"""
        await self.close()

    async def close(self):
        """Explicitly close the HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ========================================================================
    # Core Retry Logic with Exponential Backoff
    # ========================================================================

    async def _retry_request(self, request_func: Callable, operation_name: str) -> Dict[str, Any]:
        """
        Execute request with retry logic and exponential backoff.

        Retry strategy:
        - Attempt 1: Immediate (0s wait)
        - Attempt 2: 1s wait (2^0)
        - Attempt 3: 2s wait (2^1)
        - Attempt 4: 4s wait (2^2) - only if max_retries=4+

        Args:
            request_func: Async function that executes the HTTP request
            operation_name: Name of operation for logging

        Returns:
            Response dict on success, error dict on failure
        """
        last_error = None

        for attempt in range(self.max_retries):
            try:
                # Execute the request
                response = await request_func()
                response.raise_for_status()
                return response.json()

            except httpx.TimeoutException as e:
                last_error = f"Timeout after {self.timeout}s"
                if attempt < self.max_retries - 1:
                    wait_time = 2**attempt  # Exponential: 1s, 2s, 4s
                    logger.warning(
                        f"{operation_name} timeout (attempt {attempt + 1}/{self.max_retries}), "
                        f"retrying in {wait_time}s..."
                    )
                    print(
                        f"❌ [Phase4API] {operation_name} timeout after {self.timeout}s "
                        f"(attempt {attempt + 1}/{self.max_retries}), retrying in {wait_time}s...",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"{operation_name} failed after {self.max_retries} timeout attempts")
                    print(
                        f"❌ [Phase4API] {operation_name} failed after {self.max_retries} timeout attempts",
                        file=sys.stderr,
                    )

            except httpx.HTTPStatusError as e:
                # Don't retry on 4xx client errors (except 429 rate limit)
                if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                    print(
                        f"❌ [Phase4API] {operation_name} HTTP error {e.response.status_code}: {e.response.text[:100]}",
                        file=sys.stderr,
                    )
                    return {
                        "success": False,
                        "error": f"HTTP {e.response.status_code}: {e.response.text}",
                        "status_code": e.response.status_code,
                    }

                # Retry on 5xx server errors and 429 rate limits
                last_error = f"HTTP {e.response.status_code}"
                if attempt < self.max_retries - 1:
                    wait_time = 2**attempt
                    logger.warning(
                        f"{operation_name} returned {e.response.status_code} "
                        f"(attempt {attempt + 1}/{self.max_retries}), retrying in {wait_time}s..."
                    )
                    print(
                        f"❌ [Phase4API] {operation_name} HTTP {e.response.status_code} "
                        f"(attempt {attempt + 1}/{self.max_retries}), retrying in {wait_time}s...",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"{operation_name} failed after {self.max_retries} attempts: {last_error}")
                    print(
                        f"❌ [Phase4API] {operation_name} failed after {self.max_retries} attempts: {last_error}",
                        file=sys.stderr,
                    )

            except httpx.ConnectError as e:
                # Connection failures (service unavailable, refused, etc.)
                last_error = f"Connection failed to {self.base_url}: {str(e)}"
                if attempt < self.max_retries - 1:
                    wait_time = 2**attempt
                    logger.warning(
                        f"{operation_name} connection failed (attempt {attempt + 1}/{self.max_retries}), "
                        f"retrying in {wait_time}s..."
                    )
                    print(
                        f"❌ [Phase4API] {operation_name} connection failed to {self.base_url} "
                        f"(attempt {attempt + 1}/{self.max_retries}), retrying in {wait_time}s...",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"{operation_name} failed after {self.max_retries} connection attempts")
                    print(
                        f"❌ [Phase4API] {operation_name} connection failed after {self.max_retries} attempts: {last_error}",
                        file=sys.stderr,
                    )

            except httpx.RequestError as e:
                # Other network errors (DNS, invalid URL, etc.)
                last_error = f"Network error: {str(e)}"
                if attempt < self.max_retries - 1:
                    wait_time = 2**attempt
                    logger.warning(
                        f"{operation_name} network error (attempt {attempt + 1}/{self.max_retries}), "
                        f"retrying in {wait_time}s..."
                    )
                    print(
                        f"❌ [Phase4API] {operation_name} network error: {str(e)[:100]} "
                        f"(attempt {attempt + 1}/{self.max_retries}), retrying in {wait_time}s...",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"{operation_name} failed after {self.max_retries} attempts: {last_error}")
                    print(
                        f"❌ [Phase4API] {operation_name} failed after {self.max_retries} attempts: {last_error}",
                        file=sys.stderr,
                    )

            except Exception as e:
                # Unexpected errors
                last_error = f"Unexpected error: {type(e).__name__}: {str(e)}"
                logger.error(f"{operation_name} unexpected error: {e}", exc_info=True)
                print(
                    f"❌ [Phase4API] {operation_name} unexpected error: {type(e).__name__}: {str(e)[:100]}",
                    file=sys.stderr,
                )
                break  # Don't retry on unexpected errors

        # All retries exhausted or unexpected error
        return {"success": False, "error": last_error or "Unknown error", "retries_exhausted": True}

    # ========================================================================
    # Endpoint 1: Track Lineage (POST /lineage/track)
    # ========================================================================

    async def track_lineage(
        self,
        event_type: str,
        pattern_id: str,
        pattern_name: str,
        pattern_type: str,
        pattern_version: str,
        pattern_data: Dict[str, Any],
        triggered_by: str,
        metadata: Optional[Dict[str, Any]] = None,
        parent_pattern_ids: Optional[List[str]] = None,
        edge_type: Optional[str] = None,
        transformation_type: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Track a pattern lineage event (creation, modification, etc.).

        POST /api/pattern-traceability/lineage/track

        Event Types:
            - pattern_created: New pattern creation
            - pattern_modified: Pattern update/enhancement
            - pattern_merged: Multiple patterns merged
            - pattern_applied: Pattern used in execution
            - pattern_deprecated: Pattern marked deprecated
            - pattern_forked: Pattern branched for variation

        Edge Types (for derived patterns):
            - derived_from: Direct derivation
            - modified_from: Modified version
            - merged_from: Merged from multiple sources
            - replaced_by: Superseded by new version
            - inspired_by: Loosely based on
            - deprecated_by: Deprecated in favor of

        Args:
            event_type: Event type (pattern_created, pattern_modified, etc.)
            pattern_id: 16-char deterministic pattern ID
            pattern_name: Human-readable pattern name
            pattern_type: Pattern type (code, config, template, workflow)
            pattern_version: Semantic version (e.g., "1.0.0")
            pattern_data: Pattern content snapshot (dict with code, language, etc.)
            triggered_by: Source of event (hook, user, system, ai_assistant)
            metadata: Additional metadata (optional)
            parent_pattern_ids: List of parent pattern IDs (for derived patterns)
            edge_type: Relationship type (derived_from, modified_from, etc.)
            transformation_type: Transformation applied (enhancement, refactoring, etc.)
            reason: Reason for the event (optional)

        Returns:
            {
                "success": True,
                "data": {
                    "lineage_id": "uuid",
                    "pattern_id": "abc123def456",
                    "event_id": "uuid"
                },
                "metadata": {
                    "processing_time_ms": 45.23,
                    "correlation_id": "uuid"
                }
            }
            OR on error:
            {
                "success": False,
                "error": "Error description"
            }
        """
        if not self._client:
            return {"success": False, "error": "Client not initialized - use 'async with' context manager"}

        payload = {
            "event_type": event_type,
            "pattern_id": pattern_id,
            "pattern_name": pattern_name,
            "pattern_type": pattern_type,
            "pattern_version": pattern_version,
            "pattern_data": pattern_data,
            "triggered_by": triggered_by,
            "parent_pattern_ids": parent_pattern_ids or [],
            "edge_type": edge_type,
            "transformation_type": transformation_type,
            "reason": reason,
        }

        # Add metadata if provided
        if metadata:
            payload["metadata"] = metadata

        async def request():
            return await self._client.post("/api/pattern-traceability/lineage/track", json=payload)

        return await self._retry_request(request, "track_lineage")

    # ========================================================================
    # Endpoint 2: Query Lineage (GET /lineage/{pattern_id})
    # ========================================================================

    async def query_lineage(
        self, pattern_id: str, include_ancestors: bool = True, include_descendants: bool = True
    ) -> Dict[str, Any]:
        """
        Query pattern lineage (ancestry or descendants).

        GET /api/pattern-traceability/lineage/{pattern_id}
        Query params: include_ancestors, include_descendants

        Args:
            pattern_id: Pattern ID to query
            include_ancestors: Include ancestor patterns (default: True)
            include_descendants: Include descendant patterns (default: True)

        Returns:
            {
                "success": True,
                "data": {
                    "pattern_id": "abc123def456",
                    "pattern_node_id": "uuid",
                    "ancestry_depth": 2,
                    "total_ancestors": 2,
                    "total_descendants": 1,
                    "lineage_graph": {
                        "ancestors": [...],
                        "descendants": [...]
                    }
                },
                "metadata": {
                    "processing_time_ms": 156.34,
                    "query_type": "ancestry"
                }
            }
            OR on error:
            {
                "success": False,
                "error": "Error description"
            }
        """
        if not self._client:
            return {"success": False, "error": "Client not initialized - use 'async with' context manager"}

        params = {
            "include_ancestors": str(include_ancestors).lower(),
            "include_descendants": str(include_descendants).lower(),
        }

        async def request():
            return await self._client.get(f"/api/pattern-traceability/lineage/{pattern_id}", params=params)

        return await self._retry_request(request, "query_lineage")

    # ========================================================================
    # Endpoint 3: Compute Analytics (POST /analytics/compute)
    # ========================================================================

    async def compute_analytics(
        self,
        pattern_id: str,
        time_window_type: str = "weekly",
        metrics: Optional[List[str]] = None,
        include_performance: bool = True,
        include_trends: bool = True,
        include_distribution: bool = False,
    ) -> Dict[str, Any]:
        """
        Compute comprehensive usage analytics for a pattern.

        POST /api/pattern-traceability/analytics/compute

        Time Windows:
            - hourly: Last 1 hour
            - daily: Last 24 hours
            - weekly: Last 7 days (default)
            - monthly: Last 30 days
            - quarterly: Last 90 days
            - yearly: Last 365 days

        Args:
            pattern_id: Pattern ID to analyze
            time_window_type: Time window (hourly, daily, weekly, monthly, quarterly, yearly)
            metrics: Optional list of specific metrics to compute
            include_performance: Include performance metrics (avg, p95, p99 execution time)
            include_trends: Include trend analysis (growing, stable, declining, etc.)
            include_distribution: Include context distribution

        Returns:
            {
                "success": True,
                "pattern_id": "abc123def456",
                "time_window": {...},
                "usage_metrics": {
                    "total_executions": 1523,
                    "executions_per_day": 217.57,
                    "unique_contexts": 12,
                    "unique_users": 5
                },
                "success_metrics": {
                    "success_rate": 0.9672,
                    "error_rate": 0.0328,
                    "avg_quality_score": 0.8945
                },
                "performance_metrics": {...},
                "trend_analysis": {...},
                "analytics_quality_score": 0.92,
                "processing_time_ms": 245.67
            }
            OR on error:
            {
                "success": False,
                "error": "Error description"
            }
        """
        if not self._client:
            return {"success": False, "error": "Client not initialized - use 'async with' context manager"}

        payload = {
            "pattern_id": pattern_id,
            "time_window_type": time_window_type,
            "include_performance": include_performance,
            "include_trends": include_trends,
            "include_distribution": include_distribution,
        }

        if metrics:
            payload["metrics"] = metrics

        async def request():
            return await self._client.post("/api/pattern-traceability/analytics/compute", json=payload)

        return await self._retry_request(request, "compute_analytics")

    # ========================================================================
    # Endpoint 4: Get Analytics (GET /analytics/{pattern_id})
    # ========================================================================

    async def get_analytics(
        self, pattern_id: str, time_window: str = "weekly", include_trends: bool = True
    ) -> Dict[str, Any]:
        """
        Get pattern analytics with default settings (simplified endpoint).

        GET /api/pattern-traceability/analytics/{pattern_id}
        Query params: time_window, include_trends

        This is a convenience endpoint that calls compute_analytics internally
        with sensible defaults.

        Args:
            pattern_id: Pattern ID to analyze
            time_window: Time window type (default: weekly)
            include_trends: Include trend analysis (default: True)

        Returns:
            Same structure as compute_analytics()
        """
        if not self._client:
            return {"success": False, "error": "Client not initialized - use 'async with' context manager"}

        params = {"time_window": time_window, "include_trends": str(include_trends).lower()}

        async def request():
            return await self._client.get(f"/api/pattern-traceability/analytics/{pattern_id}", params=params)

        return await self._retry_request(request, "get_analytics")

    # ========================================================================
    # Endpoint 5: Analyze Feedback (POST /feedback/analyze)
    # ========================================================================

    async def analyze_feedback(
        self,
        pattern_id: str,
        feedback_type: str = "performance",
        time_window_days: int = 7,
        auto_apply_threshold: float = 0.95,
        min_sample_size: int = 30,
        significance_level: float = 0.05,
        enable_ab_testing: bool = True,
    ) -> Dict[str, Any]:
        """
        Orchestrate feedback loop workflow for pattern improvement.

        POST /api/pattern-traceability/feedback/analyze

        Workflow: collect feedback → analyze → generate improvements → validate → apply

        Feedback Types:
            - performance: Performance optimization
            - quality: Code quality improvements
            - usage: Usage pattern analysis
            - all: Comprehensive analysis

        Statistical Validation:
            - Minimum sample size: 30 executions (default)
            - Significance level: p-value < 0.05 (default)
            - Auto-apply threshold: confidence ≥ 0.95 (default)
            - A/B testing: Enabled by default

        Args:
            pattern_id: Pattern ID to improve
            feedback_type: Type of feedback (performance, quality, usage, all)
            time_window_days: Analysis time window in days (1-90)
            auto_apply_threshold: Auto-apply confidence threshold (0.0-1.0)
            min_sample_size: Minimum sample size for validation
            significance_level: P-value threshold for statistical significance
            enable_ab_testing: Enable A/B testing for validation

        Returns:
            {
                "success": True,
                "data": {
                    "pattern_id": "abc123def456",
                    "feedback_collected": 100,
                    "executions_analyzed": 100,
                    "improvements_identified": 3,
                    "improvements_validated": 2,
                    "improvements_applied": 1,
                    "improvements_rejected": 1,
                    "performance_delta": 0.60,
                    "p_value": 0.003,
                    "statistically_significant": True,
                    "confidence_score": 0.997,
                    "workflow_stages": {...},
                    "improvement_opportunities": [...],
                    "validation_results": [...],
                    "baseline_metrics": {...},
                    "improved_metrics": {...}
                },
                "metadata": {
                    "correlation_id": "uuid",
                    "duration_ms": 8234.56
                }
            }
            OR on error/insufficient data:
            {
                "success": False,
                "error": "Error description"
            }
        """
        if not self._client:
            return {"success": False, "error": "Client not initialized - use 'async with' context manager"}

        payload = {
            "pattern_id": pattern_id,
            "feedback_type": feedback_type,
            "time_window_days": time_window_days,
            "auto_apply_threshold": auto_apply_threshold,
            "min_sample_size": min_sample_size,
            "significance_level": significance_level,
            "enable_ab_testing": enable_ab_testing,
        }

        async def request():
            return await self._client.post("/api/pattern-traceability/feedback/analyze", json=payload)

        return await self._retry_request(request, "analyze_feedback")

    # ========================================================================
    # Endpoint 6: Search Patterns (POST /search)
    # ========================================================================

    async def search_patterns(
        self,
        query: str,
        pattern_types: Optional[List[str]] = None,
        min_quality_score: Optional[float] = None,
        time_window_days: Optional[int] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Search for patterns by name, type, or content.

        POST /api/pattern-traceability/search

        Args:
            query: Search query string
            pattern_types: Filter by pattern types (code, config, template, workflow)
            min_quality_score: Minimum quality score filter (0.0-1.0)
            time_window_days: Only include patterns from last N days
            limit: Maximum results to return (default: 10)

        Returns:
            {
                "success": True,
                "results": [
                    {
                        "pattern_id": "abc123def456",
                        "pattern_name": "UserAuthHandler",
                        "pattern_type": "code",
                        "quality_score": 0.92,
                        "usage_count": 150,
                        "last_used": "2025-10-03T10:00:00Z"
                    },
                    ...
                ],
                "total_found": 25,
                "limit": 10,
                "processing_time_ms": 123.45
            }
            OR on error:
            {
                "success": False,
                "error": "Error description"
            }
        """
        if not self._client:
            return {"success": False, "error": "Client not initialized - use 'async with' context manager"}

        payload = {"query": query, "limit": limit}

        if pattern_types:
            payload["pattern_types"] = pattern_types
        if min_quality_score is not None:
            payload["min_quality_score"] = min_quality_score
        if time_window_days is not None:
            payload["time_window_days"] = time_window_days

        async def request():
            return await self._client.post("/api/pattern-traceability/search", json=payload)

        return await self._retry_request(request, "search_patterns")

    # ========================================================================
    # Endpoint 7: Validate Integrity (POST /validate)
    # ========================================================================

    async def validate_integrity(
        self,
        pattern_id: Optional[str] = None,
        check_lineage: bool = True,
        check_analytics: bool = True,
        check_orphans: bool = True,
    ) -> Dict[str, Any]:
        """
        Validate pattern data integrity.

        POST /api/pattern-traceability/validate

        Checks:
            - Lineage graph consistency (no circular dependencies, valid edges)
            - Analytics data completeness and accuracy
            - Orphaned patterns (patterns with missing parents)
            - Data corruption or inconsistencies

        Args:
            pattern_id: Optional specific pattern to validate (or all if None)
            check_lineage: Validate lineage graph integrity
            check_analytics: Validate analytics data consistency
            check_orphans: Check for orphaned patterns

        Returns:
            {
                "success": True,
                "validation_results": {
                    "lineage_valid": True,
                    "analytics_valid": True,
                    "orphans_found": 0,
                    "issues_found": 0,
                    "warnings": [],
                    "errors": []
                },
                "patterns_checked": 150,
                "processing_time_ms": 567.89
            }
            OR on error:
            {
                "success": False,
                "error": "Error description"
            }
        """
        if not self._client:
            return {"success": False, "error": "Client not initialized - use 'async with' context manager"}

        payload = {"check_lineage": check_lineage, "check_analytics": check_analytics, "check_orphans": check_orphans}

        if pattern_id:
            payload["pattern_id"] = pattern_id

        async def request():
            return await self._client.post("/api/pattern-traceability/validate", json=payload)

        return await self._retry_request(request, "validate_integrity")

    # ========================================================================
    # Health Check
    # ========================================================================

    async def health_check(self) -> Dict[str, Any]:
        """
        Check Phase 4 API health status.

        GET /api/pattern-traceability/health

        Returns:
            {
                "status": "healthy" | "degraded" | "unhealthy",
                "components": {
                    "lineage_tracker": "operational" | "database_unavailable" | "error: ...",
                    "usage_analytics": "operational",
                    "feedback_orchestrator": "operational"
                },
                "timestamp": "2025-10-03T11:09:02.645024",
                "response_time_ms": 10.04
            }
            OR on error:
            {
                "success": False,
                "error": "Error description"
            }
        """
        if not self._client:
            return {"success": False, "error": "Client not initialized - use 'async with' context manager"}

        async def request():
            return await self._client.get("/api/pattern-traceability/health")

        return await self._retry_request(request, "health_check")

    # ========================================================================
    # Convenience Methods for Common Operations
    # ========================================================================

    async def track_pattern_creation(
        self,
        pattern_id: str,
        pattern_name: str,
        code: str,
        language: str = "python",
        context: Optional[Dict[str, Any]] = None,
        triggered_by: str = "hook",
    ) -> Dict[str, Any]:
        """
        Convenience method: Track pattern creation with code.

        Wraps track_lineage() with sensible defaults for pattern creation.

        Args:
            pattern_id: Unique 16-char pattern ID
            pattern_name: Human-readable pattern name
            code: Source code
            language: Programming language (default: python)
            context: Additional context (optional)
            triggered_by: Event source (default: hook)

        Returns:
            Same as track_lineage()
        """
        pattern_data = {"code": code, "language": language, "created_at": datetime.utcnow().isoformat()}

        if context:
            pattern_data["context"] = context

        return await self.track_lineage(
            event_type="pattern_created",
            pattern_id=pattern_id,
            pattern_name=pattern_name,
            pattern_type="code",
            pattern_version="1.0.0",
            pattern_data=pattern_data,
            triggered_by=triggered_by,
        )

    async def track_pattern_modification(
        self,
        pattern_id: str,
        pattern_name: str,
        parent_pattern_id: str,
        code: str,
        language: str = "python",
        reason: Optional[str] = None,
        version: str = "2.0.0",
        triggered_by: str = "hook",
    ) -> Dict[str, Any]:
        """
        Convenience method: Track pattern modification.

        Wraps track_lineage() for pattern modification events.

        Args:
            pattern_id: New pattern version ID
            pattern_name: Pattern name
            parent_pattern_id: Parent pattern ID (previous version)
            code: Modified source code
            language: Programming language
            reason: Reason for modification
            version: New semantic version
            triggered_by: Event source

        Returns:
            Same as track_lineage()
        """
        pattern_data = {"code": code, "language": language, "modified_at": datetime.utcnow().isoformat()}

        return await self.track_lineage(
            event_type="pattern_modified",
            pattern_id=pattern_id,
            pattern_name=pattern_name,
            pattern_type="code",
            pattern_version=version,
            pattern_data=pattern_data,
            parent_pattern_ids=[parent_pattern_id],
            edge_type="modified_from",
            transformation_type="enhancement",
            reason=reason,
            triggered_by=triggered_by,
        )

    async def get_pattern_health(
        self, pattern_id: str, include_analytics: bool = True, include_lineage: bool = True
    ) -> Dict[str, Any]:
        """
        Convenience method: Get comprehensive pattern health status.

        Combines analytics and lineage data for a complete pattern overview.

        Args:
            pattern_id: Pattern ID to analyze
            include_analytics: Include usage analytics (default: True)
            include_lineage: Include lineage graph (default: True)

        Returns:
            {
                "success": True,
                "pattern_id": "abc123def456",
                "analytics": {...} if include_analytics else None,
                "lineage": {...} if include_lineage else None,
                "health_score": 0.85,
                "status": "healthy" | "degraded" | "unhealthy"
            }
        """
        result = {
            "success": True,
            "pattern_id": pattern_id,
            "analytics": None,
            "lineage": None,
            "health_score": 0.0,
            "status": "unknown",
        }

        # Get analytics if requested
        if include_analytics:
            analytics = await self.get_analytics(pattern_id)
            if analytics.get("success"):
                result["analytics"] = analytics
            else:
                result["success"] = False
                result["errors"] = [f"Analytics failed: {analytics.get('error')}"]

        # Get lineage if requested
        if include_lineage:
            lineage = await self.query_lineage(pattern_id)
            if lineage.get("success"):
                result["lineage"] = lineage
            else:
                if "errors" not in result:
                    result["errors"] = []
                result["errors"].append(f"Lineage failed: {lineage.get('error')}")

        # Calculate health score
        if result["analytics"]:
            quality = result["analytics"].get("success_metrics", {}).get("avg_quality_score", 0)
            success_rate = result["analytics"].get("success_metrics", {}).get("success_rate", 0)
            result["health_score"] = (quality + success_rate) / 2

            if result["health_score"] >= 0.8:
                result["status"] = "healthy"
            elif result["health_score"] >= 0.5:
                result["status"] = "degraded"
            else:
                result["status"] = "unhealthy"

        return result
