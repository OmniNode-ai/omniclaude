"""
Health Check Framework

Provides comprehensive health checks for all Phase 7 components with:
- Database connectivity checks
- Template cache health
- Parallel generation capacity
- Mixin learning system status
- Pattern matching system health
- Event processing health
- Dependency checks

ONEX Pattern: Effect node (health state verification and reporting)
Performance Target: <100ms per health check, <500ms for full system check
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Awaitable
from uuid import uuid4

from .db import get_pg_pool
from .monitoring import update_health_status, AlertSeverity

logger = logging.getLogger(__name__)


class HealthCheckStatus(Enum):
    """Health check status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    component: str
    status: HealthCheckStatus
    healthy: bool
    message: str
    check_duration_ms: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class HealthCheckConfig:
    """Configuration for health checks."""
    # Timeout for individual health checks (ms)
    check_timeout_ms: int = 5000

    # Timeout for full system health check (ms)
    system_check_timeout_ms: int = 10000

    # Health check intervals (seconds)
    database_check_interval: int = 30
    cache_check_interval: int = 60
    generation_check_interval: int = 120
    mixin_check_interval: int = 300
    pattern_check_interval: int = 300
    event_check_interval: int = 60

    # Health thresholds
    database_max_latency_ms: float = 100.0
    cache_min_hit_rate: float = 0.50
    generation_max_failure_rate: float = 0.20
    mixin_min_success_rate: float = 0.80
    pattern_min_precision: float = 0.75
    event_max_p95_latency_ms: float = 300.0


class HealthChecker:
    """
    Comprehensive health check framework for Phase 7 components.

    Features:
    - Individual component health checks
    - Full system health validation
    - Automatic health status updates to monitoring system
    - Configurable check intervals and thresholds
    - Async health check execution with timeouts
    - Dependency validation

    Performance:
    - Individual check: <100ms
    - Full system check: <500ms
    - Non-blocking async execution
    """

    def __init__(self, config: Optional[HealthCheckConfig] = None):
        """Initialize health checker.

        Args:
            config: Health check configuration (uses defaults if None)
        """
        self.config = config or HealthCheckConfig()
        self.last_checks: Dict[str, HealthCheckResult] = {}
        self.background_task: Optional[asyncio.Task] = None
        self._running = False

        logger.info("HealthChecker initialized")

    async def check_database_health(self) -> HealthCheckResult:
        """Check database connectivity and performance.

        Returns:
            HealthCheckResult for database
        """
        start_time = time.time()
        component = "database"

        try:
            pool = await get_pg_pool()
            if not pool:
                return HealthCheckResult(
                    component=component,
                    status=HealthCheckStatus.CRITICAL,
                    healthy=False,
                    message="Database pool not available",
                    check_duration_ms=0.0,
                    error="Pool initialization failed"
                )

            # Test connection with simple query
            query_start = time.time()
            async with pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                query_duration_ms = (time.time() - query_start) * 1000

                # Check if latency is acceptable
                if query_duration_ms > self.config.database_max_latency_ms:
                    status = HealthCheckStatus.DEGRADED
                    healthy = True  # Still functional but slow
                    message = f"Database responding slowly ({query_duration_ms:.1f}ms > {self.config.database_max_latency_ms}ms threshold)"
                else:
                    status = HealthCheckStatus.HEALTHY
                    healthy = True
                    message = f"Database healthy (latency: {query_duration_ms:.1f}ms)"

                check_duration_ms = (time.time() - start_time) * 1000

                result = HealthCheckResult(
                    component=component,
                    status=status,
                    healthy=healthy,
                    message=message,
                    check_duration_ms=check_duration_ms,
                    metadata={
                        "query_latency_ms": query_duration_ms,
                        "pool_size": pool.get_size(),
                        "pool_idle": pool.get_idle_size()
                    }
                )

                # Update monitoring system
                await update_health_status(
                    component=component,
                    healthy=healthy,
                    status=status.value,
                    error_message=None if healthy else message,
                    metadata=result.metadata
                )

                return result

        except asyncio.TimeoutError:
            check_duration_ms = (time.time() - start_time) * 1000
            result = HealthCheckResult(
                component=component,
                status=HealthCheckStatus.CRITICAL,
                healthy=False,
                message="Database health check timed out",
                check_duration_ms=check_duration_ms,
                error="Timeout"
            )
            await update_health_status(component, False, "critical", "Timeout")
            return result

        except Exception as e:
            check_duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Database health check failed: {e}", exc_info=True)

            result = HealthCheckResult(
                component=component,
                status=HealthCheckStatus.CRITICAL,
                healthy=False,
                message=f"Database health check failed: {str(e)}",
                check_duration_ms=check_duration_ms,
                error=str(e)
            )
            await update_health_status(component, False, "critical", str(e))
            return result

    async def check_template_cache_health(self) -> HealthCheckResult:
        """Check template cache health and performance.

        Returns:
            HealthCheckResult for template cache
        """
        start_time = time.time()
        component = "template_cache"

        try:
            pool = await get_pg_pool()
            if not pool:
                return HealthCheckResult(
                    component=component,
                    status=HealthCheckStatus.UNKNOWN,
                    healthy=False,
                    message="Database unavailable for cache check",
                    check_duration_ms=0.0,
                    error="Database unavailable"
                )

            async with pool.acquire() as conn:
                # Check cache hit rate
                result = await conn.fetchrow("""
                    SELECT
                        COALESCE(SUM(cache_hits), 0) as total_hits,
                        COALESCE(SUM(cache_misses), 0) as total_misses,
                        COALESCE(AVG(load_time_ms), 0) as avg_load_time
                    FROM template_cache_metadata
                """)

                total_hits = result['total_hits'] or 0
                total_misses = result['total_misses'] or 0
                avg_load_time = result['avg_load_time'] or 0

                total_accesses = total_hits + total_misses
                hit_rate = total_hits / total_accesses if total_accesses > 0 else 0.0

                # Determine health status
                if hit_rate < self.config.cache_min_hit_rate:
                    status = HealthCheckStatus.DEGRADED
                    healthy = True
                    message = f"Cache hit rate low ({hit_rate:.1%} < {self.config.cache_min_hit_rate:.1%})"
                else:
                    status = HealthCheckStatus.HEALTHY
                    healthy = True
                    message = f"Template cache healthy (hit rate: {hit_rate:.1%})"

                check_duration_ms = (time.time() - start_time) * 1000

                check_result = HealthCheckResult(
                    component=component,
                    status=status,
                    healthy=healthy,
                    message=message,
                    check_duration_ms=check_duration_ms,
                    metadata={
                        "hit_rate": hit_rate,
                        "total_hits": total_hits,
                        "total_misses": total_misses,
                        "avg_load_time_ms": avg_load_time
                    }
                )

                await update_health_status(
                    component=component,
                    healthy=healthy,
                    status=status.value,
                    metadata=check_result.metadata
                )

                return check_result

        except Exception as e:
            check_duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Template cache health check failed: {e}", exc_info=True)

            result = HealthCheckResult(
                component=component,
                status=HealthCheckStatus.CRITICAL,
                healthy=False,
                message=f"Cache health check failed: {str(e)}",
                check_duration_ms=check_duration_ms,
                error=str(e)
            )
            await update_health_status(component, False, "critical", str(e))
            return result

    async def check_parallel_generation_health(self) -> HealthCheckResult:
        """Check parallel generation system health.

        Returns:
            HealthCheckResult for parallel generation
        """
        start_time = time.time()
        component = "parallel_generation"

        try:
            pool = await get_pg_pool()
            if not pool:
                return HealthCheckResult(
                    component=component,
                    status=HealthCheckStatus.UNKNOWN,
                    healthy=False,
                    message="Database unavailable for generation check",
                    check_duration_ms=0.0,
                    error="Database unavailable"
                )

            async with pool.acquire() as conn:
                # Check recent generation metrics
                result = await conn.fetchrow("""
                    SELECT
                        COUNT(*) as total_generations,
                        AVG(duration_ms) as avg_duration_ms,
                        SUM(CASE WHEN metadata->>'success' = 'true' THEN 1 ELSE 0 END) as success_count
                    FROM generation_performance_metrics
                    WHERE created_at >= NOW() - INTERVAL '1 hour'
                        AND phase = 'total'
                """)

                total = result['total_generations'] or 0
                avg_duration = result['avg_duration_ms'] or 0
                successes = result['success_count'] or 0

                if total == 0:
                    status = HealthCheckStatus.UNKNOWN
                    healthy = True
                    message = "No recent generation activity"
                    failure_rate = 0.0
                else:
                    failure_rate = (total - successes) / total

                    if failure_rate > self.config.generation_max_failure_rate:
                        status = HealthCheckStatus.DEGRADED
                        healthy = True
                        message = f"Generation failure rate high ({failure_rate:.1%})"
                    else:
                        status = HealthCheckStatus.HEALTHY
                        healthy = True
                        message = f"Parallel generation healthy (failure rate: {failure_rate:.1%})"

                check_duration_ms = (time.time() - start_time) * 1000

                check_result = HealthCheckResult(
                    component=component,
                    status=status,
                    healthy=healthy,
                    message=message,
                    check_duration_ms=check_duration_ms,
                    metadata={
                        "total_generations": total,
                        "avg_duration_ms": avg_duration,
                        "failure_rate": failure_rate
                    }
                )

                await update_health_status(
                    component=component,
                    healthy=healthy,
                    status=status.value,
                    metadata=check_result.metadata
                )

                return check_result

        except Exception as e:
            check_duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Parallel generation health check failed: {e}", exc_info=True)

            result = HealthCheckResult(
                component=component,
                status=HealthCheckStatus.CRITICAL,
                healthy=False,
                message=f"Generation health check failed: {str(e)}",
                check_duration_ms=check_duration_ms,
                error=str(e)
            )
            await update_health_status(component, False, "critical", str(e))
            return result

    async def check_mixin_learning_health(self) -> HealthCheckResult:
        """Check mixin learning system health.

        Returns:
            HealthCheckResult for mixin learning
        """
        start_time = time.time()
        component = "mixin_learning"

        try:
            pool = await get_pg_pool()
            if not pool:
                return HealthCheckResult(
                    component=component,
                    status=HealthCheckStatus.UNKNOWN,
                    healthy=False,
                    message="Database unavailable for mixin check",
                    check_duration_ms=0.0,
                    error="Database unavailable"
                )

            async with pool.acquire() as conn:
                # Check mixin compatibility data
                result = await conn.fetchrow("""
                    SELECT
                        COUNT(*) as total_combinations,
                        AVG(compatibility_score) as avg_score,
                        SUM(success_count) as total_successes,
                        SUM(failure_count) as total_failures
                    FROM mixin_compatibility_matrix
                """)

                total_combinations = result['total_combinations'] or 0
                avg_score = result['avg_score'] or 0
                total_successes = result['total_successes'] or 0
                total_failures = result['total_failures'] or 0

                total_tests = total_successes + total_failures

                if total_tests == 0:
                    status = HealthCheckStatus.UNKNOWN
                    healthy = True
                    message = "No mixin compatibility data yet"
                    success_rate = 0.0
                else:
                    success_rate = total_successes / total_tests

                    if success_rate < self.config.mixin_min_success_rate:
                        status = HealthCheckStatus.DEGRADED
                        healthy = True
                        message = f"Mixin success rate low ({success_rate:.1%})"
                    else:
                        status = HealthCheckStatus.HEALTHY
                        healthy = True
                        message = f"Mixin learning healthy (success rate: {success_rate:.1%})"

                check_duration_ms = (time.time() - start_time) * 1000

                check_result = HealthCheckResult(
                    component=component,
                    status=status,
                    healthy=healthy,
                    message=message,
                    check_duration_ms=check_duration_ms,
                    metadata={
                        "total_combinations": total_combinations,
                        "avg_compatibility_score": float(avg_score),
                        "success_rate": success_rate
                    }
                )

                await update_health_status(
                    component=component,
                    healthy=healthy,
                    status=status.value,
                    metadata=check_result.metadata
                )

                return check_result

        except Exception as e:
            check_duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Mixin learning health check failed: {e}", exc_info=True)

            result = HealthCheckResult(
                component=component,
                status=HealthCheckStatus.CRITICAL,
                healthy=False,
                message=f"Mixin health check failed: {str(e)}",
                check_duration_ms=check_duration_ms,
                error=str(e)
            )
            await update_health_status(component, False, "critical", str(e))
            return result

    async def check_pattern_matching_health(self) -> HealthCheckResult:
        """Check pattern matching system health.

        Returns:
            HealthCheckResult for pattern matching
        """
        start_time = time.time()
        component = "pattern_matching"

        try:
            pool = await get_pg_pool()
            if not pool:
                return HealthCheckResult(
                    component=component,
                    status=HealthCheckStatus.UNKNOWN,
                    healthy=False,
                    message="Database unavailable for pattern check",
                    check_duration_ms=0.0,
                    error="Database unavailable"
                )

            async with pool.acquire() as conn:
                # Check pattern feedback data
                result = await conn.fetchrow("""
                    SELECT
                        COUNT(*) as total_feedback,
                        SUM(CASE WHEN feedback_type = 'correct' THEN 1 ELSE 0 END) as correct_count,
                        SUM(CASE WHEN feedback_type = 'incorrect' THEN 1 ELSE 0 END) as incorrect_count,
                        AVG(detected_confidence) as avg_confidence
                    FROM pattern_feedback_log
                    WHERE created_at >= NOW() - INTERVAL '7 days'
                """)

                total_feedback = result['total_feedback'] or 0
                correct = result['correct_count'] or 0
                incorrect = result['incorrect_count'] or 0
                avg_confidence = result['avg_confidence'] or 0

                if total_feedback == 0:
                    status = HealthCheckStatus.UNKNOWN
                    healthy = True
                    message = "No recent pattern feedback"
                    precision = 0.0
                else:
                    precision = correct / (correct + incorrect) if (correct + incorrect) > 0 else 0.0

                    if precision < self.config.pattern_min_precision:
                        status = HealthCheckStatus.DEGRADED
                        healthy = True
                        message = f"Pattern precision low ({precision:.1%})"
                    else:
                        status = HealthCheckStatus.HEALTHY
                        healthy = True
                        message = f"Pattern matching healthy (precision: {precision:.1%})"

                check_duration_ms = (time.time() - start_time) * 1000

                check_result = HealthCheckResult(
                    component=component,
                    status=status,
                    healthy=healthy,
                    message=message,
                    check_duration_ms=check_duration_ms,
                    metadata={
                        "total_feedback": total_feedback,
                        "precision": precision,
                        "avg_confidence": float(avg_confidence)
                    }
                )

                await update_health_status(
                    component=component,
                    healthy=healthy,
                    status=status.value,
                    metadata=check_result.metadata
                )

                return check_result

        except Exception as e:
            check_duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Pattern matching health check failed: {e}", exc_info=True)

            result = HealthCheckResult(
                component=component,
                status=HealthCheckStatus.CRITICAL,
                healthy=False,
                message=f"Pattern health check failed: {str(e)}",
                check_duration_ms=check_duration_ms,
                error=str(e)
            )
            await update_health_status(component, False, "critical", str(e))
            return result

    async def check_event_processing_health(self) -> HealthCheckResult:
        """Check event processing system health.

        Returns:
            HealthCheckResult for event processing
        """
        start_time = time.time()
        component = "event_processing"

        try:
            pool = await get_pg_pool()
            if not pool:
                return HealthCheckResult(
                    component=component,
                    status=HealthCheckStatus.UNKNOWN,
                    healthy=False,
                    message="Database unavailable for event check",
                    check_duration_ms=0.0,
                    error="Database unavailable"
                )

            async with pool.acquire() as conn:
                # Check event processing metrics
                result = await conn.fetchrow("""
                    SELECT
                        COUNT(*) as total_events,
                        SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
                        percentile_cont(0.95) WITHIN GROUP (ORDER BY processing_duration_ms) as p95_latency
                    FROM event_processing_metrics
                    WHERE created_at >= NOW() - INTERVAL '1 hour'
                """)

                total_events = result['total_events'] or 0
                success_count = result['success_count'] or 0
                p95_latency = result['p95_latency'] or 0

                if total_events == 0:
                    status = HealthCheckStatus.UNKNOWN
                    healthy = True
                    message = "No recent event processing activity"
                else:
                    success_rate = success_count / total_events

                    if p95_latency > self.config.event_max_p95_latency_ms:
                        status = HealthCheckStatus.DEGRADED
                        healthy = True
                        message = f"Event p95 latency high ({p95_latency:.1f}ms)"
                    else:
                        status = HealthCheckStatus.HEALTHY
                        healthy = True
                        message = f"Event processing healthy (p95: {p95_latency:.1f}ms)"

                check_duration_ms = (time.time() - start_time) * 1000

                check_result = HealthCheckResult(
                    component=component,
                    status=status,
                    healthy=healthy,
                    message=message,
                    check_duration_ms=check_duration_ms,
                    metadata={
                        "total_events": total_events,
                        "success_rate": success_rate if total_events > 0 else 0.0,
                        "p95_latency_ms": float(p95_latency)
                    }
                )

                await update_health_status(
                    component=component,
                    healthy=healthy,
                    status=status.value,
                    metadata=check_result.metadata
                )

                return check_result

        except Exception as e:
            check_duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Event processing health check failed: {e}", exc_info=True)

            result = HealthCheckResult(
                component=component,
                status=HealthCheckStatus.CRITICAL,
                healthy=False,
                message=f"Event health check failed: {str(e)}",
                check_duration_ms=check_duration_ms,
                error=str(e)
            )
            await update_health_status(component, False, "critical", str(e))
            return result

    async def check_system_health(self) -> Dict[str, HealthCheckResult]:
        """Run all health checks and return comprehensive system health.

        Returns:
            Dictionary mapping component names to health check results
        """
        start_time = time.time()

        try:
            # Run all health checks in parallel with timeout
            checks = await asyncio.wait_for(
                asyncio.gather(
                    self.check_database_health(),
                    self.check_template_cache_health(),
                    self.check_parallel_generation_health(),
                    self.check_mixin_learning_health(),
                    self.check_pattern_matching_health(),
                    self.check_event_processing_health(),
                    return_exceptions=True
                ),
                timeout=self.config.system_check_timeout_ms / 1000.0
            )

            # Build results dictionary
            results = {}
            component_names = [
                "database",
                "template_cache",
                "parallel_generation",
                "mixin_learning",
                "pattern_matching",
                "event_processing"
            ]

            for component, check in zip(component_names, checks):
                if isinstance(check, Exception):
                    logger.error(f"Health check failed for {component}: {check}")
                    results[component] = HealthCheckResult(
                        component=component,
                        status=HealthCheckStatus.CRITICAL,
                        healthy=False,
                        message=f"Health check exception: {str(check)}",
                        check_duration_ms=0.0,
                        error=str(check)
                    )
                else:
                    results[component] = check
                    self.last_checks[component] = check

            total_duration_ms = (time.time() - start_time) * 1000
            logger.info(f"System health check completed in {total_duration_ms:.1f}ms")

            return results

        except asyncio.TimeoutError:
            logger.error("System health check timed out")
            return {
                "system": HealthCheckResult(
                    component="system",
                    status=HealthCheckStatus.CRITICAL,
                    healthy=False,
                    message="System health check timed out",
                    check_duration_ms=self.config.system_check_timeout_ms,
                    error="Timeout"
                )
            }
        except Exception as e:
            logger.error(f"System health check failed: {e}", exc_info=True)
            return {
                "system": HealthCheckResult(
                    component="system",
                    status=HealthCheckStatus.CRITICAL,
                    healthy=False,
                    message=f"System health check failed: {str(e)}",
                    check_duration_ms=0.0,
                    error=str(e)
                )
            }

    def get_overall_health_status(self) -> HealthCheckStatus:
        """Get overall system health status based on last checks.

        Returns:
            Overall health status
        """
        if not self.last_checks:
            return HealthCheckStatus.UNKNOWN

        # If any component is critical, system is critical
        if any(c.status == HealthCheckStatus.CRITICAL for c in self.last_checks.values()):
            return HealthCheckStatus.CRITICAL

        # If any component is degraded, system is degraded
        if any(c.status == HealthCheckStatus.DEGRADED for c in self.last_checks.values()):
            return HealthCheckStatus.DEGRADED

        # If all components are healthy
        if all(c.status == HealthCheckStatus.HEALTHY for c in self.last_checks.values()):
            return HealthCheckStatus.HEALTHY

        # Otherwise unknown
        return HealthCheckStatus.UNKNOWN

    async def start_background_checks(self, interval_seconds: int = 60) -> None:
        """Start background health checks at specified interval.

        Args:
            interval_seconds: Interval between health checks
        """
        if self._running:
            logger.warning("Background health checks already running")
            return

        self._running = True

        async def background_loop():
            while self._running:
                try:
                    await self.check_system_health()
                    await asyncio.sleep(interval_seconds)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Background health check error: {e}", exc_info=True)
                    await asyncio.sleep(interval_seconds)

        self.background_task = asyncio.create_task(background_loop())
        logger.info(f"Started background health checks (interval: {interval_seconds}s)")

    async def stop_background_checks(self) -> None:
        """Stop background health checks."""
        self._running = False

        if self.background_task:
            self.background_task.cancel()
            try:
                await self.background_task
            except asyncio.CancelledError:
                pass

        logger.info("Stopped background health checks")


# Global health checker instance
_health_checker: Optional[HealthChecker] = None


def get_health_checker(config: Optional[HealthCheckConfig] = None) -> HealthChecker:
    """Get or create global health checker instance.

    Args:
        config: Optional health check configuration

    Returns:
        HealthChecker instance
    """
    global _health_checker

    if _health_checker is None:
        _health_checker = HealthChecker(config)

    return _health_checker


# Convenience functions
async def check_system_health() -> Dict[str, HealthCheckResult]:
    """Run all health checks and return system health.

    Returns:
        Dictionary of health check results
    """
    checker = get_health_checker()
    return await checker.check_system_health()


async def check_component_health(component: str) -> Optional[HealthCheckResult]:
    """Check health of a specific component.

    Args:
        component: Component name

    Returns:
        HealthCheckResult or None if component unknown
    """
    checker = get_health_checker()

    component_checks = {
        "database": checker.check_database_health,
        "template_cache": checker.check_template_cache_health,
        "parallel_generation": checker.check_parallel_generation_health,
        "mixin_learning": checker.check_mixin_learning_health,
        "pattern_matching": checker.check_pattern_matching_health,
        "event_processing": checker.check_event_processing_health
    }

    check_func = component_checks.get(component)
    if not check_func:
        return None

    return await check_func()


def get_overall_health_status() -> HealthCheckStatus:
    """Get overall system health status.

    Returns:
        Overall health status
    """
    checker = get_health_checker()
    return checker.get_overall_health_status()
