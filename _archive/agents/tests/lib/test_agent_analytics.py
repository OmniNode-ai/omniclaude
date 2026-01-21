#!/usr/bin/env python3
"""
Comprehensive Tests for Agent Analytics

Tests for agent_analytics.py covering:
- Performance tracking with database success/failure
- Performance summary with caching
- Agent recommendations with confidence scoring
- Performance trends over time
- Cache management (validation and invalidation)
- Error handling and graceful degradation
- Edge cases (no pool, empty data, null values)

Coverage Target: 80%+
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agents.lib.agent_analytics import (
    AgentAnalytics,
    agent_analytics,
    get_agent_recommendations,
    track_agent_performance,
)

# ============================================================================
# TEST FIXTURES
# ============================================================================


class MockRow(dict):
    """Mock database row that behaves like both dict and object with attributes"""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(f"MockRow has no attribute '{item}'")


@pytest.fixture
def mock_pg_pool():
    """Mock PostgreSQL connection pool"""
    pool = AsyncMock()
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock()

    # Create async context manager mock
    acquire_mock = AsyncMock()
    acquire_mock.__aenter__ = AsyncMock(return_value=conn)
    acquire_mock.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = Mock(return_value=acquire_mock)

    return pool


@pytest.fixture
def analytics_instance():
    """Fresh AgentAnalytics instance for each test"""
    return AgentAnalytics()


@pytest.fixture
def sample_performance_data():
    """Sample performance data for testing"""
    return {
        "total_tasks": 100,
        "successful_tasks": 85,
        "avg_duration_ms": 1500.5,
        "min_duration_ms": 500.0,
        "max_duration_ms": 3000.0,
        "duration_stddev": 450.2,
    }


@pytest.fixture
def sample_agent_metrics():
    """Sample agent metrics"""
    return [
        {
            "agent_id": "agent-1",
            "total_tasks": 50,
            "successful_tasks": 45,
            "avg_duration_ms": 1200.0,
            "success_rate_percent": 90.0,
        },
        {
            "agent_id": "agent-2",
            "total_tasks": 50,
            "successful_tasks": 40,
            "avg_duration_ms": 1800.0,
            "success_rate_percent": 80.0,
        },
    ]


@pytest.fixture
def sample_task_metrics():
    """Sample task metrics"""
    return [
        {
            "task_type": "code_generation",
            "total_tasks": 60,
            "successful_tasks": 55,
            "avg_duration_ms": 1400.0,
            "success_rate_percent": 91.67,
        },
        {
            "task_type": "code_review",
            "total_tasks": 40,
            "successful_tasks": 30,
            "avg_duration_ms": 1600.0,
            "success_rate_percent": 75.0,
        },
    ]


@pytest.fixture
def sample_top_agents():
    """Sample top agents by task"""
    return [
        {
            "task_type": "code_generation",
            "agent_id": "agent-1",
            "total_tasks": 30,
            "successful_tasks": 28,
            "avg_duration_ms": 1100.0,
            "success_rate_percent": 93.33,
        },
        {
            "task_type": "code_review",
            "agent_id": "agent-2",
            "total_tasks": 20,
            "successful_tasks": 18,
            "avg_duration_ms": 1500.0,
            "success_rate_percent": 90.0,
        },
    ]


@pytest.fixture
def sample_trends_data():
    """Sample performance trends data"""
    now = datetime.now()
    return [
        {
            "time_bucket": now - timedelta(hours=2),
            "total_tasks": 10,
            "successful_tasks": 9,
            "avg_duration_ms": 1200.0,
            "success_rate_percent": 90.0,
        },
        {
            "time_bucket": now - timedelta(hours=1),
            "total_tasks": 15,
            "successful_tasks": 14,
            "avg_duration_ms": 1100.0,
            "success_rate_percent": 93.33,
        },
    ]


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


class TestAgentAnalyticsInit:
    """Tests for AgentAnalytics initialization"""

    def test_init_default_values(self):
        """Test initialization with default values"""
        analytics = AgentAnalytics()

        assert analytics._performance_cache == {}
        assert analytics._cache_ttl == 300  # 5 minutes
        assert analytics._last_cache_update is None

    def test_global_instance_exists(self):
        """Test that global instance is created"""
        assert agent_analytics is not None
        assert isinstance(agent_analytics, AgentAnalytics)


# ============================================================================
# TRACK PERFORMANCE TESTS
# ============================================================================


class TestTrackPerformance:
    """Tests for track_agent_performance method"""

    @pytest.mark.asyncio
    async def test_track_performance_success(self, analytics_instance, mock_pg_pool):
        """Test successful performance tracking"""
        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            performance_id = await analytics_instance.track_agent_performance(
                agent_id="test-agent",
                task_type="code_generation",
                success=True,
                duration_ms=1500,
                run_id="test-run-123",
                metadata={"key": "value"},
                correlation_id="corr-123",
            )

            # Verify performance ID is a valid UUID
            assert len(performance_id) == 36  # UUID format
            assert performance_id != "no-tracking-id"

            # Verify database insert was called
            conn = await mock_pg_pool.acquire().__aenter__()
            conn.execute.assert_called_once()

            # Verify cache was invalidated
            assert analytics_instance._last_cache_update is None
            assert analytics_instance._performance_cache == {}

    @pytest.mark.asyncio
    async def test_track_performance_no_pool(self, analytics_instance):
        """Test tracking when database pool is not available"""
        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=None):
            performance_id = await analytics_instance.track_agent_performance(
                agent_id="test-agent",
                task_type="code_generation",
                success=True,
                duration_ms=1500,
                run_id="test-run-123",
            )

            assert performance_id == "no-tracking-id"

    @pytest.mark.asyncio
    async def test_track_performance_database_error(
        self, analytics_instance, mock_pg_pool
    ):
        """Test graceful handling of database errors"""
        # Make execute raise an error
        conn = await mock_pg_pool.acquire().__aenter__()
        conn.execute.side_effect = Exception("Database connection failed")

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            with patch("builtins.print") as mock_print:
                performance_id = await analytics_instance.track_agent_performance(
                    agent_id="test-agent",
                    task_type="code_generation",
                    success=False,
                    duration_ms=2000,
                    run_id="test-run-456",
                )

                assert performance_id == "no-tracking-id"
                mock_print.assert_called_once()
                assert "Failed to track agent performance" in str(mock_print.call_args)

    @pytest.mark.asyncio
    async def test_track_performance_with_metadata(
        self, analytics_instance, mock_pg_pool
    ):
        """Test tracking with complex metadata"""
        metadata = {
            "complexity": "high",
            "language": "python",
            "lines_of_code": 150,
            "nested": {"key": "value"},
        }

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            performance_id = await analytics_instance.track_agent_performance(
                agent_id="test-agent",
                task_type="code_generation",
                success=True,
                duration_ms=1500,
                run_id="test-run-789",
                metadata=metadata,
                correlation_id="corr-789",
            )

            assert performance_id != "no-tracking-id"

            # Verify metadata was JSON-encoded
            conn = await mock_pg_pool.acquire().__aenter__()
            call_args = conn.execute.call_args[0]
            # The metadata should be the 8th parameter (index 7)
            json_metadata = call_args[8]
            assert isinstance(json_metadata, str)
            parsed = json.loads(json_metadata)
            assert parsed["complexity"] == "high"

    @pytest.mark.asyncio
    async def test_track_performance_no_metadata(
        self, analytics_instance, mock_pg_pool
    ):
        """Test tracking without metadata (defaults to empty dict)"""
        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            performance_id = await analytics_instance.track_agent_performance(
                agent_id="test-agent",
                task_type="code_generation",
                success=True,
                duration_ms=1500,
                run_id="test-run-999",
            )

            assert performance_id != "no-tracking-id"

            # Verify empty metadata was passed
            conn = await mock_pg_pool.acquire().__aenter__()
            call_args = conn.execute.call_args[0]
            json_metadata = call_args[8]
            parsed = json.loads(json_metadata)
            assert parsed == {}


# ============================================================================
# PERFORMANCE SUMMARY TESTS
# ============================================================================


class TestPerformanceSummary:
    """Tests for get_agent_performance_summary method"""

    @pytest.mark.asyncio
    async def test_get_summary_success(
        self,
        analytics_instance,
        mock_pg_pool,
        sample_performance_data,
        sample_agent_metrics,
        sample_task_metrics,
        sample_top_agents,
    ):
        """Test successful retrieval of performance summary"""
        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetchrow.return_value = sample_performance_data
        conn.fetch.side_effect = [
            [MockRow(m) for m in sample_agent_metrics],
            [MockRow(m) for m in sample_task_metrics],
            [MockRow(m) for m in sample_top_agents],
        ]

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            summary = await analytics_instance.get_agent_performance_summary(days=30)

            assert summary["period_days"] == 30
            assert "since_date" in summary
            assert summary["overall_metrics"]["total_tasks"] == 100
            assert len(summary["agent_metrics"]) == 2
            assert len(summary["task_metrics"]) == 2
            assert len(summary["top_agents_by_task"]) == 2

    @pytest.mark.asyncio
    async def test_get_summary_with_filters(
        self, analytics_instance, mock_pg_pool, sample_performance_data
    ):
        """Test summary with agent_id and task_type filters"""
        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetchrow.return_value = sample_performance_data
        conn.fetch.return_value = []

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            summary = await analytics_instance.get_agent_performance_summary(
                agent_id="specific-agent", task_type="code_generation", days=7
            )

            assert summary["period_days"] == 7
            assert "overall_metrics" in summary

            # Verify filters were applied in queries
            assert conn.fetch.call_count == 3  # agent_metrics, task_metrics, top_agents

    @pytest.mark.asyncio
    async def test_get_summary_uses_cache(self, analytics_instance, mock_pg_pool):
        """Test that summary uses cache when valid"""
        # Populate cache
        cache_key = "all_all_30"
        cached_data = {"period_days": 30, "cached": True}
        analytics_instance._performance_cache[cache_key] = cached_data
        analytics_instance._last_cache_update = datetime.now()

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            summary = await analytics_instance.get_agent_performance_summary(days=30)

            # Should return cached data without database call
            assert summary == cached_data
            assert summary["cached"] is True

            # Verify no database calls were made
            conn = await mock_pg_pool.acquire().__aenter__()
            conn.fetchrow.assert_not_called()
            conn.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_summary_cache_expired(
        self, analytics_instance, mock_pg_pool, sample_performance_data
    ):
        """Test that expired cache is not used"""
        # Set cache with old timestamp
        cache_key = "all_all_30"
        analytics_instance._performance_cache[cache_key] = {"old": "data"}
        analytics_instance._last_cache_update = datetime.now() - timedelta(seconds=400)

        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetchrow.return_value = sample_performance_data
        conn.fetch.return_value = []

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            summary = await analytics_instance.get_agent_performance_summary(days=30)

            # Should fetch new data, not use cache
            assert "old" not in summary
            assert summary["overall_metrics"]["total_tasks"] == 100

            # Verify database was called
            conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_summary_no_pool(self, analytics_instance):
        """Test summary when database pool is not available"""
        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=None):
            summary = await analytics_instance.get_agent_performance_summary()

            assert summary == {}

    @pytest.mark.asyncio
    async def test_get_summary_database_error(self, analytics_instance, mock_pg_pool):
        """Test graceful handling of database errors in summary"""
        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetchrow.side_effect = Exception("Database query failed")

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            with patch("builtins.print") as mock_print:
                summary = await analytics_instance.get_agent_performance_summary()

                assert summary["overall_metrics"] == {}
                assert summary["agent_metrics"] == []
                assert summary["task_metrics"] == []
                mock_print.assert_called_once()
                assert "Failed to get agent performance summary" in str(
                    mock_print.call_args
                )

    @pytest.mark.asyncio
    async def test_get_summary_caches_result(
        self, analytics_instance, mock_pg_pool, sample_performance_data
    ):
        """Test that summary result is cached"""
        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetchrow.return_value = sample_performance_data
        conn.fetch.return_value = []

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            summary = await analytics_instance.get_agent_performance_summary(days=30)

            # Verify cache was updated
            cache_key = "all_all_30"
            assert cache_key in analytics_instance._performance_cache
            assert analytics_instance._performance_cache[cache_key] == summary
            assert analytics_instance._last_cache_update is not None


# ============================================================================
# AGENT RECOMMENDATIONS TESTS
# ============================================================================


class TestAgentRecommendations:
    """Tests for get_agent_recommendations method"""

    @pytest.mark.asyncio
    async def test_get_recommendations_success(self, analytics_instance, mock_pg_pool):
        """Test successful retrieval of agent recommendations"""
        sample_data = [
            {
                "agent_id": "agent-1",
                "total_tasks": 10,
                "successful_tasks": 9,
                "avg_duration_ms": 800.0,
                "success_rate_percent": 90.0,
                "duration_stddev": 100.0,
            },
            {
                "agent_id": "agent-2",
                "total_tasks": 8,
                "successful_tasks": 6,
                "avg_duration_ms": 1200.0,
                "success_rate_percent": 75.0,
                "duration_stddev": 200.0,
            },
        ]

        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetch.return_value = [MockRow(data) for data in sample_data]

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            recommendations = await analytics_instance.get_agent_recommendations(
                task_type="code_generation", limit=2, days=30
            )

            assert len(recommendations) == 2
            assert recommendations[0]["agent_id"] == "agent-1"
            assert recommendations[0]["success_rate_percent"] == 90.0
            assert "confidence_score" in recommendations[0]
            assert "recommendation_reason" in recommendations[0]

    @pytest.mark.asyncio
    async def test_get_recommendations_confidence_calculation(
        self, analytics_instance, mock_pg_pool
    ):
        """Test confidence score calculation"""
        sample_data = [
            {
                "agent_id": "high-success",
                "total_tasks": 10,
                "successful_tasks": 10,
                "avg_duration_ms": 1000.0,
                "success_rate_percent": 100.0,
                "duration_stddev": 50.0,  # Low variance = high consistency
            }
        ]

        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetch.return_value = [MockRow(data) for data in sample_data]

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            recommendations = await analytics_instance.get_agent_recommendations(
                task_type="code_generation"
            )

            # High success rate + low variance should give high confidence
            assert recommendations[0]["confidence_score"] > 0.9

    @pytest.mark.asyncio
    async def test_get_recommendations_with_context(
        self, analytics_instance, mock_pg_pool
    ):
        """Test recommendations with additional context"""
        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetch.return_value = []

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            recommendations = await analytics_instance.get_agent_recommendations(
                task_type="code_generation",
                context={"complexity": "high", "language": "python"},
                limit=5,
            )

            # Context is accepted but currently not used in filtering
            assert isinstance(recommendations, list)

    @pytest.mark.asyncio
    async def test_get_recommendations_no_pool(self, analytics_instance):
        """Test recommendations when database pool is not available"""
        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=None):
            recommendations = await analytics_instance.get_agent_recommendations(
                task_type="code_generation"
            )

            assert recommendations == []

    @pytest.mark.asyncio
    async def test_get_recommendations_database_error(
        self, analytics_instance, mock_pg_pool
    ):
        """Test graceful handling of database errors in recommendations"""
        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetch.side_effect = Exception("Database error")

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            with patch("builtins.print") as mock_print:
                recommendations = await analytics_instance.get_agent_recommendations(
                    task_type="code_generation"
                )

                assert recommendations == []
                mock_print.assert_called_once()
                assert "Failed to get agent recommendations" in str(
                    mock_print.call_args
                )

    @pytest.mark.asyncio
    async def test_get_recommendations_null_values(
        self, analytics_instance, mock_pg_pool
    ):
        """Test handling of null values in recommendations"""
        sample_data = [
            {
                "agent_id": "agent-with-nulls",
                "total_tasks": 5,
                "successful_tasks": 3,
                "avg_duration_ms": 1000.0,
                "success_rate_percent": None,  # Null success rate
                "duration_stddev": None,  # Null stddev
            }
        ]

        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetch.return_value = [MockRow(data) for data in sample_data]

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            recommendations = await analytics_instance.get_agent_recommendations(
                task_type="code_generation"
            )

            assert len(recommendations) == 1
            assert recommendations[0]["success_rate_percent"] == 0
            # Should handle null values without crashing


# ============================================================================
# RECOMMENDATION REASON TESTS
# ============================================================================


class TestRecommendationReason:
    """Tests for _get_recommendation_reason method"""

    def test_high_success_fast_execution(self, analytics_instance):
        """Test reason for high success rate with fast execution"""
        reason = analytics_instance._get_recommendation_reason(
            success_rate=95.0, avg_duration=500.0
        )
        assert reason == "High success rate with fast execution"

    def test_high_success_reliable_execution(self, analytics_instance):
        """Test reason for high success rate with slower execution"""
        reason = analytics_instance._get_recommendation_reason(
            success_rate=92.0, avg_duration=2000.0
        )
        assert reason == "High success rate with reliable execution"

    def test_good_success_rate(self, analytics_instance):
        """Test reason for good success rate"""
        reason = analytics_instance._get_recommendation_reason(
            success_rate=80.0, avg_duration=1500.0
        )
        assert reason == "Good success rate with acceptable performance"

    def test_moderate_success_rate(self, analytics_instance):
        """Test reason for moderate success rate"""
        reason = analytics_instance._get_recommendation_reason(
            success_rate=60.0, avg_duration=1500.0
        )
        assert reason == "Moderate success rate, consider alternatives"


# ============================================================================
# PERFORMANCE TRENDS TESTS
# ============================================================================


class TestPerformanceTrends:
    """Tests for get_performance_trends method"""

    @pytest.mark.asyncio
    async def test_get_trends_success(
        self, analytics_instance, mock_pg_pool, sample_trends_data
    ):
        """Test successful retrieval of performance trends"""
        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetch.return_value = [MockRow(data) for data in sample_trends_data]

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            trends = await analytics_instance.get_performance_trends(
                days=7, interval_hours=24
            )

            assert trends["period_days"] == 7
            assert trends["interval_hours"] == 24
            assert "since_date" in trends
            assert len(trends["trends"]) == 2
            assert "success_trend" in trends
            assert "duration_trend" in trends

    @pytest.mark.asyncio
    async def test_get_trends_improving(self, analytics_instance, mock_pg_pool):
        """Test trends showing improvement"""
        # First half has lower success, second half has higher success
        trends_data = [
            {
                "time_bucket": datetime.now() - timedelta(hours=4),
                "total_tasks": 10,
                "successful_tasks": 7,
                "avg_duration_ms": 1500.0,
                "success_rate_percent": 70.0,
            },
            {
                "time_bucket": datetime.now() - timedelta(hours=2),
                "total_tasks": 10,
                "successful_tasks": 9,
                "avg_duration_ms": 1000.0,
                "success_rate_percent": 90.0,
            },
        ]

        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetch.return_value = [MockRow(data) for data in trends_data]

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            trends = await analytics_instance.get_performance_trends(days=1)

            assert trends["success_trend"] == "improving"
            assert trends["duration_trend"] == "improving"
            assert trends["trend_summary"]["success_rate_change"] > 0
            assert trends["trend_summary"]["duration_change"] < 0

    @pytest.mark.asyncio
    async def test_get_trends_declining(self, analytics_instance, mock_pg_pool):
        """Test trends showing decline"""
        trends_data = [
            {
                "time_bucket": datetime.now() - timedelta(hours=4),
                "total_tasks": 10,
                "successful_tasks": 9,
                "avg_duration_ms": 1000.0,
                "success_rate_percent": 90.0,
            },
            {
                "time_bucket": datetime.now() - timedelta(hours=2),
                "total_tasks": 10,
                "successful_tasks": 7,
                "avg_duration_ms": 1500.0,
                "success_rate_percent": 70.0,
            },
        ]

        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetch.return_value = [MockRow(data) for data in trends_data]

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            trends = await analytics_instance.get_performance_trends(days=1)

            assert trends["success_trend"] == "declining"
            assert trends["duration_trend"] == "declining"

    @pytest.mark.asyncio
    async def test_get_trends_stable(self, analytics_instance, mock_pg_pool):
        """Test trends showing stability"""
        trends_data = [
            {
                "time_bucket": datetime.now() - timedelta(hours=4),
                "total_tasks": 10,
                "successful_tasks": 8,
                "avg_duration_ms": 1200.0,
                "success_rate_percent": 80.0,
            },
            {
                "time_bucket": datetime.now() - timedelta(hours=2),
                "total_tasks": 10,
                "successful_tasks": 8,
                "avg_duration_ms": 1200.0,
                "success_rate_percent": 80.0,
            },
        ]

        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetch.return_value = [MockRow(data) for data in trends_data]

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            trends = await analytics_instance.get_performance_trends(days=1)

            assert trends["success_trend"] == "stable"
            assert trends["duration_trend"] == "stable"

    @pytest.mark.asyncio
    async def test_get_trends_no_data(self, analytics_instance, mock_pg_pool):
        """Test trends with no data"""
        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetch.return_value = []

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            trends = await analytics_instance.get_performance_trends(days=1)

            assert trends["trends"] == []
            assert trends["success_trend"] == "stable"
            assert trends["duration_trend"] == "stable"
            assert trends["trend_summary"]["success_rate_change"] == 0
            assert trends["trend_summary"]["duration_change"] == 0

    @pytest.mark.asyncio
    async def test_get_trends_with_filters(self, analytics_instance, mock_pg_pool):
        """Test trends with agent_id and task_type filters"""
        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetch.return_value = []

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            trends = await analytics_instance.get_performance_trends(
                agent_id="specific-agent", task_type="code_generation", days=14
            )

            assert trends["period_days"] == 14
            # Verify query was executed with filters
            conn.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_trends_no_pool(self, analytics_instance):
        """Test trends when database pool is not available"""
        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=None):
            trends = await analytics_instance.get_performance_trends()

            assert trends == {}

    @pytest.mark.asyncio
    async def test_get_trends_database_error(self, analytics_instance, mock_pg_pool):
        """Test graceful handling of database errors in trends"""
        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetch.side_effect = Exception("Database error")

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            with patch("builtins.print") as mock_print:
                trends = await analytics_instance.get_performance_trends()

                assert trends["trends"] == []
                assert trends["success_trend"] == "unknown"
                assert trends["duration_trend"] == "unknown"
                mock_print.assert_called_once()


# ============================================================================
# CACHE MANAGEMENT TESTS
# ============================================================================


class TestCacheManagement:
    """Tests for cache validation and invalidation"""

    def test_cache_valid_when_recent(self, analytics_instance):
        """Test that cache is valid when recently updated"""
        analytics_instance._last_cache_update = datetime.now()
        assert analytics_instance._is_cache_valid() is True

    def test_cache_invalid_when_expired(self, analytics_instance):
        """Test that cache is invalid when expired"""
        # Set update time to 10 minutes ago (cache TTL is 5 minutes)
        analytics_instance._last_cache_update = datetime.now() - timedelta(seconds=600)
        assert analytics_instance._is_cache_valid() is False

    def test_cache_invalid_when_never_updated(self, analytics_instance):
        """Test that cache is invalid when never updated"""
        analytics_instance._last_cache_update = None
        assert analytics_instance._is_cache_valid() is False

    def test_invalidate_cache_clears_data(self, analytics_instance):
        """Test that invalidate_cache clears all cached data"""
        # Populate cache
        analytics_instance._performance_cache = {"key1": "value1", "key2": "value2"}
        analytics_instance._last_cache_update = datetime.now()

        # Invalidate
        analytics_instance._invalidate_cache()

        assert analytics_instance._performance_cache == {}
        assert analytics_instance._last_cache_update is None

    @pytest.mark.asyncio
    async def test_track_performance_invalidates_cache(
        self, analytics_instance, mock_pg_pool
    ):
        """Test that tracking performance invalidates the cache"""
        # Populate cache
        analytics_instance._performance_cache = {"key": "value"}
        analytics_instance._last_cache_update = datetime.now()

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            await analytics_instance.track_agent_performance(
                agent_id="test",
                task_type="test",
                success=True,
                duration_ms=100,
                run_id="123",
            )

            # Cache should be invalidated
            assert analytics_instance._performance_cache == {}
            assert analytics_instance._last_cache_update is None


# ============================================================================
# MODULE-LEVEL FUNCTION TESTS
# ============================================================================


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions"""

    @pytest.mark.asyncio
    async def test_track_agent_performance_function(self, mock_pg_pool):
        """Test module-level track_agent_performance function"""
        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            performance_id = await track_agent_performance(
                agent_id="module-agent",
                task_type="module_test",
                success=True,
                duration_ms=1234,
                run_id="module-run-123",
                metadata={"test": "data"},
                correlation_id="module-corr-123",
            )

            assert performance_id != "no-tracking-id"
            # Verify it calls the instance method
            conn = await mock_pg_pool.acquire().__aenter__()
            conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_agent_recommendations_function(self, mock_pg_pool):
        """Test module-level get_agent_recommendations function"""
        sample_data = [
            {
                "agent_id": "recommended-agent",
                "total_tasks": 10,
                "successful_tasks": 9,
                "avg_duration_ms": 1000.0,
                "success_rate_percent": 90.0,
                "duration_stddev": 100.0,
            }
        ]

        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetch.return_value = [MockRow(data) for data in sample_data]

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            recommendations = await get_agent_recommendations(
                task_type="module_test", context={"key": "value"}, limit=5, days=14
            )

            assert len(recommendations) == 1
            assert recommendations[0]["agent_id"] == "recommended-agent"


# ============================================================================
# EDGE CASES AND ERROR HANDLING
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling"""

    @pytest.mark.asyncio
    async def test_empty_performance_data(self, analytics_instance, mock_pg_pool):
        """Test handling of empty performance data"""
        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetchrow.return_value = None
        conn.fetch.return_value = []

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            summary = await analytics_instance.get_agent_performance_summary()

            assert summary["overall_metrics"] == {}
            assert summary["agent_metrics"] == []

    @pytest.mark.asyncio
    async def test_very_large_duration(self, analytics_instance, mock_pg_pool):
        """Test handling of very large duration values"""
        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            performance_id = await analytics_instance.track_agent_performance(
                agent_id="slow-agent",
                task_type="slow_task",
                success=True,
                duration_ms=999999999,  # Very large duration
                run_id="slow-run",
            )

            assert performance_id != "no-tracking-id"

    @pytest.mark.asyncio
    async def test_zero_duration(self, analytics_instance, mock_pg_pool):
        """Test handling of zero duration"""
        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            performance_id = await analytics_instance.track_agent_performance(
                agent_id="instant-agent",
                task_type="instant_task",
                success=True,
                duration_ms=0,
                run_id="instant-run",
            )

            assert performance_id != "no-tracking-id"

    @pytest.mark.asyncio
    async def test_special_characters_in_ids(self, analytics_instance, mock_pg_pool):
        """Test handling of special characters in IDs"""
        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            performance_id = await analytics_instance.track_agent_performance(
                agent_id="agent-with-special!@#$%",
                task_type="task/with/slashes",
                success=True,
                duration_ms=1000,
                run_id="run:with:colons",
            )

            assert performance_id != "no-tracking-id"

    @pytest.mark.asyncio
    async def test_very_long_strings(self, analytics_instance, mock_pg_pool):
        """Test handling of very long strings"""
        long_agent_id = "a" * 1000
        long_task_type = "t" * 1000

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            performance_id = await analytics_instance.track_agent_performance(
                agent_id=long_agent_id,
                task_type=long_task_type,
                success=True,
                duration_ms=1000,
                run_id="long-run",
            )

            assert performance_id != "no-tracking-id"

    def test_cache_boundary_conditions(self, analytics_instance):
        """Test cache validation at exact TTL boundary"""
        # Set update time to exactly TTL seconds ago
        analytics_instance._last_cache_update = datetime.now() - timedelta(
            seconds=analytics_instance._cache_ttl
        )

        # Should be invalid at exact boundary
        assert analytics_instance._is_cache_valid() is False


# ============================================================================
# INTEGRATION-STYLE TESTS
# ============================================================================


class TestIntegration:
    """Integration-style tests covering multiple operations"""

    @pytest.mark.asyncio
    async def test_track_and_retrieve_workflow(self, analytics_instance, mock_pg_pool):
        """Test complete workflow of tracking and retrieving performance"""
        # Setup mock to track calls
        conn = await mock_pg_pool.acquire().__aenter__()
        conn.fetchrow.return_value = {
            "total_tasks": 1,
            "successful_tasks": 1,
            "avg_duration_ms": 1500.0,
            "min_duration_ms": 1500.0,
            "max_duration_ms": 1500.0,
            "duration_stddev": 0.0,
        }
        conn.fetch.return_value = []

        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            # Track performance
            perf_id = await analytics_instance.track_agent_performance(
                agent_id="workflow-agent",
                task_type="workflow_test",
                success=True,
                duration_ms=1500,
                run_id="workflow-run",
            )

            assert perf_id != "no-tracking-id"

            # Retrieve summary
            summary = await analytics_instance.get_agent_performance_summary(days=1)

            assert summary["overall_metrics"]["total_tasks"] == 1

    @pytest.mark.asyncio
    async def test_multiple_tracks_with_cache_invalidation(
        self, analytics_instance, mock_pg_pool
    ):
        """Test that multiple tracks properly invalidate cache"""
        with patch("agents.lib.agent_analytics.get_pg_pool", return_value=mock_pg_pool):
            # Track first performance
            await analytics_instance.track_agent_performance(
                agent_id="multi-agent",
                task_type="multi_test",
                success=True,
                duration_ms=1000,
                run_id="multi-1",
            )

            # Cache should be empty
            assert analytics_instance._performance_cache == {}

            # Track second performance
            await analytics_instance.track_agent_performance(
                agent_id="multi-agent",
                task_type="multi_test",
                success=False,
                duration_ms=2000,
                run_id="multi-2",
            )

            # Cache should still be empty
            assert analytics_instance._performance_cache == {}
