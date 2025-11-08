"""
Comprehensive Tests for Health Checker Module

Tests for complete coverage of agents/lib/health_checker.py including:
- All component health checks (database, template cache, parallel generation, etc.)
- Degraded and critical status paths
- Timeout scenarios
- Database unavailable scenarios
- Background health check tasks
- Convenience functions
- Edge cases and error handling

Target: Increase coverage from 55% to 80%+

ONEX Pattern: Test validation for Effect nodes
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.lib.health_checker import (
    HealthCheckConfig,
    HealthChecker,
    HealthCheckResult,
    HealthCheckStatus,
    check_component_health,
    check_system_health,
    get_health_checker,
    get_overall_health_status,
)


class TestHealthCheckerDatabaseHealth:
    """Tests for database health check with all status paths."""

    @pytest.fixture
    def health_checker(self):
        """Create health checker with custom config."""
        config = HealthCheckConfig(
            check_timeout_ms=1000,
            database_max_latency_ms=50.0,  # Low threshold for testing degraded
        )
        return HealthChecker(config)

    @pytest.mark.asyncio
    async def test_database_health_check_degraded_slow_response(self, health_checker):
        """Test degraded status when database responds slowly."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()

            # Simulate slow query response
            async def slow_fetchval(*args):
                await asyncio.sleep(0.06)  # 60ms - above 50ms threshold
                return 1

            mock_conn.fetchval = slow_fetchval

            # Create async context manager mock
            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool_instance.get_size = MagicMock(return_value=5)
            mock_pool_instance.get_idle_size = MagicMock(return_value=3)

            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_database_health()

            assert result.component == "database"
            assert result.status == HealthCheckStatus.DEGRADED
            assert result.healthy is True  # Still functional but slow
            assert "responding slowly" in result.message
            assert "query_latency_ms" in result.metadata
            assert (
                result.metadata["query_latency_ms"]
                > health_checker.config.database_max_latency_ms
            )

    @pytest.mark.asyncio
    async def test_database_health_check_timeout(self, health_checker):
        """Test database health check timeout handling."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            # Simulate timeout
            mock_conn.fetchval = AsyncMock(side_effect=asyncio.TimeoutError())

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_database_health()

            assert result.component == "database"
            assert result.status == HealthCheckStatus.CRITICAL
            assert result.healthy is False
            assert "timed out" in result.message
            assert result.error == "Timeout"

    @pytest.mark.asyncio
    async def test_database_health_check_pool_unavailable(self, health_checker):
        """Test when database pool is not available."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_pool.return_value = None

            result = await health_checker.check_database_health()

            assert result.component == "database"
            assert result.status == HealthCheckStatus.CRITICAL
            assert result.healthy is False
            assert "pool not available" in result.message
            assert result.error == "Pool initialization failed"

    @pytest.mark.asyncio
    async def test_database_health_check_exception(self, health_checker):
        """Test database health check exception handling."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_pool.side_effect = Exception("Connection refused")

            result = await health_checker.check_database_health()

            assert result.component == "database"
            assert result.status == HealthCheckStatus.CRITICAL
            assert result.healthy is False
            assert "Connection refused" in result.error


class TestHealthCheckerTemplateCacheHealth:
    """Tests for template cache health check."""

    @pytest.fixture
    def health_checker(self):
        """Create health checker with custom config."""
        config = HealthCheckConfig(cache_min_hit_rate=0.70)
        return HealthChecker(config)

    @pytest.mark.asyncio
    async def test_template_cache_database_unavailable(self, health_checker):
        """Test template cache health when database is unavailable."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_pool.return_value = None

            result = await health_checker.check_template_cache_health()

            assert result.component == "template_cache"
            assert result.status == HealthCheckStatus.UNKNOWN
            assert result.healthy is False
            assert "Database unavailable" in result.message

    @pytest.mark.asyncio
    async def test_template_cache_low_hit_rate_degraded(self, health_checker):
        """Test degraded status when cache hit rate is low."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            # Low hit rate: 600 hits / 1000 total = 60% (below 70% threshold)
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_hits": 600,
                    "total_misses": 400,
                    "avg_load_time": 45.0,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_template_cache_health()

            assert result.component == "template_cache"
            assert result.status == HealthCheckStatus.DEGRADED
            assert result.healthy is True
            assert "hit rate low" in result.message
            assert result.metadata["hit_rate"] == 0.6


class TestHealthCheckerParallelGenerationHealth:
    """Tests for parallel generation health check."""

    @pytest.fixture
    def health_checker(self):
        """Create health checker with custom config."""
        config = HealthCheckConfig(generation_max_failure_rate=0.20)
        return HealthChecker(config)

    @pytest.mark.asyncio
    async def test_parallel_generation_database_unavailable(self, health_checker):
        """Test parallel generation health when database is unavailable."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_pool.return_value = None

            result = await health_checker.check_parallel_generation_health()

            assert result.component == "parallel_generation"
            assert result.status == HealthCheckStatus.UNKNOWN
            assert result.healthy is False
            assert "Database unavailable" in result.message

    @pytest.mark.asyncio
    async def test_parallel_generation_no_recent_activity(self, health_checker):
        """Test status when there's no recent generation activity."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            # No generations in the past hour
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_generations": 0,
                    "avg_duration_ms": None,
                    "success_count": None,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_parallel_generation_health()

            assert result.component == "parallel_generation"
            assert result.status == HealthCheckStatus.UNKNOWN
            assert result.healthy is True
            assert "No recent generation activity" in result.message
            assert result.metadata["failure_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_parallel_generation_high_failure_rate_degraded(self, health_checker):
        """Test degraded status with high failure rate."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            # 30% failure rate (30 failures out of 100 total, above 20% threshold)
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_generations": 100,
                    "avg_duration_ms": 2500.0,
                    "success_count": 70,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_parallel_generation_health()

            assert result.component == "parallel_generation"
            assert result.status == HealthCheckStatus.DEGRADED
            assert result.healthy is True
            assert "failure rate high" in result.message
            assert result.metadata["failure_rate"] == 0.3

    @pytest.mark.asyncio
    async def test_parallel_generation_healthy(self, health_checker):
        """Test healthy status with low failure rate."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            # 5% failure rate (below 20% threshold)
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_generations": 100,
                    "avg_duration_ms": 2200.0,
                    "success_count": 95,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_parallel_generation_health()

            assert result.component == "parallel_generation"
            assert result.status == HealthCheckStatus.HEALTHY
            assert result.healthy is True
            assert "healthy" in result.message
            assert result.metadata["failure_rate"] == 0.05


class TestHealthCheckerMixinLearningHealth:
    """Tests for mixin learning health check."""

    @pytest.fixture
    def health_checker(self):
        """Create health checker with custom config."""
        config = HealthCheckConfig(mixin_min_success_rate=0.80)
        return HealthChecker(config)

    @pytest.mark.asyncio
    async def test_mixin_learning_database_unavailable(self, health_checker):
        """Test mixin learning health when database is unavailable."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_pool.return_value = None

            result = await health_checker.check_mixin_learning_health()

            assert result.component == "mixin_learning"
            assert result.status == HealthCheckStatus.UNKNOWN
            assert result.healthy is False
            assert "Database unavailable" in result.message

    @pytest.mark.asyncio
    async def test_mixin_learning_no_data(self, health_checker):
        """Test status when there's no mixin compatibility data."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_combinations": 0,
                    "avg_score": None,
                    "total_successes": 0,
                    "total_failures": 0,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_mixin_learning_health()

            assert result.component == "mixin_learning"
            assert result.status == HealthCheckStatus.UNKNOWN
            assert result.healthy is True
            assert "No mixin compatibility data" in result.message

    @pytest.mark.asyncio
    async def test_mixin_learning_low_success_rate_degraded(self, health_checker):
        """Test degraded status with low success rate."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            # 70% success rate (below 80% threshold)
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_combinations": 50,
                    "avg_score": 0.75,
                    "total_successes": 350,
                    "total_failures": 150,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_mixin_learning_health()

            assert result.component == "mixin_learning"
            assert result.status == HealthCheckStatus.DEGRADED
            assert result.healthy is True
            assert "success rate low" in result.message
            assert result.metadata["success_rate"] == 0.7

    @pytest.mark.asyncio
    async def test_mixin_learning_healthy(self, health_checker):
        """Test healthy status with good success rate."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            # 90% success rate (above 80% threshold)
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_combinations": 50,
                    "avg_score": 0.92,
                    "total_successes": 450,
                    "total_failures": 50,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_mixin_learning_health()

            assert result.component == "mixin_learning"
            assert result.status == HealthCheckStatus.HEALTHY
            assert result.healthy is True
            assert "healthy" in result.message
            assert result.metadata["success_rate"] == 0.9


class TestHealthCheckerPatternMatchingHealth:
    """Tests for pattern matching health check."""

    @pytest.fixture
    def health_checker(self):
        """Create health checker with custom config."""
        config = HealthCheckConfig(pattern_min_precision=0.75)
        return HealthChecker(config)

    @pytest.mark.asyncio
    async def test_pattern_matching_database_unavailable(self, health_checker):
        """Test pattern matching health when database is unavailable."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_pool.return_value = None

            result = await health_checker.check_pattern_matching_health()

            assert result.component == "pattern_matching"
            assert result.status == HealthCheckStatus.UNKNOWN
            assert result.healthy is False
            assert "Database unavailable" in result.message

    @pytest.mark.asyncio
    async def test_pattern_matching_no_recent_feedback(self, health_checker):
        """Test status when there's no recent pattern feedback."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_feedback": 0,
                    "correct_count": 0,
                    "incorrect_count": 0,
                    "avg_confidence": None,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_pattern_matching_health()

            assert result.component == "pattern_matching"
            assert result.status == HealthCheckStatus.UNKNOWN
            assert result.healthy is True
            assert "No recent pattern feedback" in result.message

    @pytest.mark.asyncio
    async def test_pattern_matching_low_precision_degraded(self, health_checker):
        """Test degraded status with low precision."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            # 70% precision (below 75% threshold)
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_feedback": 100,
                    "correct_count": 70,
                    "incorrect_count": 30,
                    "avg_confidence": 0.82,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_pattern_matching_health()

            assert result.component == "pattern_matching"
            assert result.status == HealthCheckStatus.DEGRADED
            assert result.healthy is True
            assert "precision low" in result.message
            assert result.metadata["precision"] == 0.7

    @pytest.mark.asyncio
    async def test_pattern_matching_healthy(self, health_checker):
        """Test healthy status with good precision."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            # 90% precision (above 75% threshold)
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_feedback": 100,
                    "correct_count": 90,
                    "incorrect_count": 10,
                    "avg_confidence": 0.88,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_pattern_matching_health()

            assert result.component == "pattern_matching"
            assert result.status == HealthCheckStatus.HEALTHY
            assert result.healthy is True
            assert "healthy" in result.message
            assert result.metadata["precision"] == 0.9


class TestHealthCheckerEventProcessingHealth:
    """Tests for event processing health check."""

    @pytest.fixture
    def health_checker(self):
        """Create health checker with custom config."""
        config = HealthCheckConfig(event_max_p95_latency_ms=300.0)
        return HealthChecker(config)

    @pytest.mark.asyncio
    async def test_event_processing_database_unavailable(self, health_checker):
        """Test event processing health when database is unavailable."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_pool.return_value = None

            result = await health_checker.check_event_processing_health()

            assert result.component == "event_processing"
            assert result.status == HealthCheckStatus.UNKNOWN
            assert result.healthy is False
            assert "Database unavailable" in result.message

    @pytest.mark.asyncio
    async def test_event_processing_no_recent_activity(self, health_checker):
        """Test status when there's no recent event processing activity."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_events": 0,
                    "success_count": 0,
                    "p95_latency": None,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_event_processing_health()

            assert result.component == "event_processing"
            assert result.status == HealthCheckStatus.UNKNOWN
            assert result.healthy is True
            assert "No recent event processing activity" in result.message

    @pytest.mark.asyncio
    async def test_event_processing_high_latency_degraded(self, health_checker):
        """Test degraded status with high p95 latency."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            # P95 latency of 450ms (above 300ms threshold)
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_events": 1000,
                    "success_count": 980,
                    "p95_latency": 450.0,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_event_processing_health()

            assert result.component == "event_processing"
            assert result.status == HealthCheckStatus.DEGRADED
            assert result.healthy is True
            assert "p95 latency high" in result.message
            assert result.metadata["p95_latency_ms"] == 450.0

    @pytest.mark.asyncio
    async def test_event_processing_healthy(self, health_checker):
        """Test healthy status with good latency."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            # P95 latency of 150ms (below 300ms threshold)
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_events": 1000,
                    "success_count": 995,
                    "p95_latency": 150.0,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_event_processing_health()

            assert result.component == "event_processing"
            assert result.status == HealthCheckStatus.HEALTHY
            assert result.healthy is True
            assert "healthy" in result.message
            assert result.metadata["p95_latency_ms"] == 150.0


class TestHealthCheckerSystemHealth:
    """Tests for system-wide health check."""

    @pytest.fixture
    def health_checker(self):
        """Create health checker."""
        return HealthChecker()

    @pytest.mark.asyncio
    async def test_system_health_check_with_exception_in_check(self, health_checker):
        """Test system health check when individual check raises exception."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            # First call succeeds, rest fail with different exceptions
            call_count = 0

            def pool_side_effect():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # Database check succeeds
                    mock_conn = AsyncMock()
                    mock_conn.fetchval = AsyncMock(return_value=1)
                    mock_pool_instance = AsyncMock()
                    mock_pool_instance.acquire.return_value.__aenter__.return_value = (
                        mock_conn
                    )
                    mock_pool_instance.get_size.return_value = 5
                    mock_pool_instance.get_idle_size.return_value = 3
                    return mock_pool_instance
                else:
                    # Other checks raise exception
                    raise Exception(f"Check {call_count} failed")

            mock_pool.side_effect = pool_side_effect

            results = await health_checker.check_system_health()

            assert isinstance(results, dict)
            # Database should succeed
            assert "database" in results
            # Other components should have exception results
            critical_results = [
                r for r in results.values() if r.status == HealthCheckStatus.CRITICAL
            ]
            assert len(critical_results) > 0

    @pytest.mark.asyncio
    async def test_system_health_check_timeout(self, health_checker):
        """Test system health check timeout handling."""
        # Set very short timeout
        health_checker.config.system_check_timeout_ms = 10  # 10ms

        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            # Make checks slow to trigger timeout
            async def slow_pool():
                await asyncio.sleep(1)  # 1 second - way over timeout
                return None

            mock_pool.side_effect = slow_pool

            results = await health_checker.check_system_health()

            assert "system" in results
            result = results["system"]
            assert result.status == HealthCheckStatus.CRITICAL
            assert result.healthy is False
            assert "timed out" in result.message

    @pytest.mark.asyncio
    async def test_system_health_check_unexpected_exception(self, health_checker):
        """Test system health check with unexpected exception."""
        with patch.object(
            health_checker,
            "check_database_health",
            side_effect=ValueError("Unexpected error"),
        ):
            results = await health_checker.check_system_health()

            # Should handle exception gracefully
            assert isinstance(results, dict)
            # System should be in critical state
            if "system" in results:
                assert results["system"].status == HealthCheckStatus.CRITICAL


class TestHealthCheckerBackgroundChecks:
    """Tests for background health check tasks."""

    @pytest.fixture
    def health_checker(self):
        """Create health checker."""
        return HealthChecker()

    @pytest.mark.asyncio
    async def test_start_background_checks(self, health_checker):
        """Test starting background health checks."""
        with patch.object(health_checker, "check_system_health") as mock_check:
            mock_check.return_value = {}

            await health_checker.start_background_checks(interval_seconds=1)

            assert health_checker._running is True
            assert health_checker.background_task is not None

            # Give it time to run at least once
            await asyncio.sleep(0.1)

            # Clean up
            await health_checker.stop_background_checks()

    @pytest.mark.asyncio
    async def test_start_background_checks_already_running(self, health_checker):
        """Test starting background checks when already running."""
        health_checker._running = True

        # Should not create new task
        await health_checker.start_background_checks()

        assert health_checker.background_task is None

        # Clean up
        health_checker._running = False

    @pytest.mark.asyncio
    async def test_stop_background_checks(self, health_checker):
        """Test stopping background health checks."""
        with patch.object(health_checker, "check_system_health") as mock_check:
            mock_check.return_value = {}

            await health_checker.start_background_checks(interval_seconds=1)
            assert health_checker._running is True

            await health_checker.stop_background_checks()

            assert health_checker._running is False

    @pytest.mark.asyncio
    async def test_background_check_handles_exceptions(self, health_checker):
        """Test that background checks handle exceptions gracefully."""
        with patch.object(
            health_checker, "check_system_health", side_effect=Exception("Test error")
        ):
            await health_checker.start_background_checks(interval_seconds=0.1)

            # Give it time to run and handle exception
            await asyncio.sleep(0.2)

            # Should still be running despite exception
            assert health_checker._running is True

            # Clean up
            await health_checker.stop_background_checks()


class TestHealthCheckerConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @pytest.mark.asyncio
    async def test_get_health_checker(self):
        """Test get_health_checker creates and returns singleton."""
        # Reset global instance
        import agents.lib.health_checker as hc_module

        hc_module._health_checker = None

        checker1 = get_health_checker()
        assert checker1 is not None

        checker2 = get_health_checker()
        assert checker1 is checker2  # Same instance

        # Clean up
        hc_module._health_checker = None

    @pytest.mark.asyncio
    async def test_get_health_checker_with_config(self):
        """Test get_health_checker with custom config."""
        import agents.lib.health_checker as hc_module

        hc_module._health_checker = None

        config = HealthCheckConfig(database_max_latency_ms=50.0)
        checker = get_health_checker(config)

        assert checker.config.database_max_latency_ms == 50.0

        # Clean up
        hc_module._health_checker = None

    @pytest.mark.asyncio
    async def test_check_system_health_convenience_function(self):
        """Test check_system_health convenience function."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            mock_conn.fetchval = AsyncMock(return_value=1)
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_hits": 800,
                    "total_misses": 200,
                    "avg_load_time": 45.0,
                    "total_generations": 0,
                    "avg_duration_ms": None,
                    "success_count": None,
                    "total_combinations": 0,
                    "avg_score": None,
                    "total_successes": 0,
                    "total_failures": 0,
                    "total_feedback": 0,
                    "correct_count": 0,
                    "incorrect_count": 0,
                    "avg_confidence": None,
                    "total_events": 0,
                    "p95_latency": None,
                }
            )

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire.return_value.__aenter__.return_value = mock_conn
            mock_pool_instance.get_size.return_value = 5
            mock_pool_instance.get_idle_size.return_value = 3
            mock_pool.return_value = mock_pool_instance

            results = await check_system_health()

            assert isinstance(results, dict)
            assert len(results) > 0

    @pytest.mark.asyncio
    async def test_check_component_health_valid_component(self):
        """Test check_component_health for valid component."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_pool.return_value = None

            result = await check_component_health("database")

            assert result is not None
            assert result.component == "database"

    @pytest.mark.asyncio
    async def test_check_component_health_invalid_component(self):
        """Test check_component_health for invalid component."""
        result = await check_component_health("invalid_component")

        assert result is None

    @pytest.mark.asyncio
    async def test_check_component_health_all_components(self):
        """Test check_component_health for all valid components."""
        components = [
            "database",
            "template_cache",
            "parallel_generation",
            "mixin_learning",
            "pattern_matching",
            "event_processing",
        ]

        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_pool.return_value = None

            for component in components:
                result = await check_component_health(component)
                assert result is not None
                assert result.component == component

    def test_get_overall_health_status_convenience_function(self):
        """Test get_overall_health_status convenience function."""
        # Reset global instance to ensure clean state
        import agents.lib.health_checker as hc_module

        hc_module._health_checker = None

        # Should return UNKNOWN initially (no checks run yet)
        status = get_overall_health_status()
        assert status == HealthCheckStatus.UNKNOWN

        # Clean up
        hc_module._health_checker = None


class TestHealthCheckerEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def health_checker(self):
        """Create health checker."""
        return HealthChecker()

    @pytest.mark.asyncio
    async def test_cache_hit_rate_with_zero_accesses(self, health_checker):
        """Test cache hit rate calculation with zero accesses."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_hits": 0,
                    "total_misses": 0,
                    "avg_load_time": 0,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_template_cache_health()

            # Should handle division by zero gracefully
            assert result.metadata["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_pattern_precision_with_zero_feedback(self, health_checker):
        """Test pattern precision calculation with zero correct and incorrect."""
        with patch("agents.lib.health_checker.get_pg_pool") as mock_pool:
            mock_conn = AsyncMock()
            # Total feedback > 0, but no correct or incorrect counts
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "total_feedback": 10,
                    "correct_count": 0,
                    "incorrect_count": 0,
                    "avg_confidence": 0.5,
                }
            )

            mock_acquire = MagicMock()
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=None)

            mock_pool_instance = AsyncMock()
            mock_pool_instance.acquire = MagicMock(return_value=mock_acquire)
            mock_pool.return_value = mock_pool_instance

            result = await health_checker.check_pattern_matching_health()

            # Should handle division by zero gracefully
            assert result.metadata["precision"] == 0.0

    @pytest.mark.asyncio
    async def test_overall_health_with_mixed_statuses(self, health_checker):
        """Test overall health calculation with various status combinations."""
        # Add checks in different states
        health_checker.last_checks["comp1"] = HealthCheckResult(
            component="comp1",
            status=HealthCheckStatus.HEALTHY,
            healthy=True,
            message="OK",
            check_duration_ms=10.0,
        )
        health_checker.last_checks["comp2"] = HealthCheckResult(
            component="comp2",
            status=HealthCheckStatus.UNKNOWN,
            healthy=False,
            message="Unknown",
            check_duration_ms=10.0,
        )

        # With healthy + unknown, should be unknown
        assert health_checker.get_overall_health_status() == HealthCheckStatus.UNKNOWN


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
