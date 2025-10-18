"""
Test Suite for Resilience Layer

Tests all resilience components:
- ResilientExecutor (fire-and-forget)
- CircuitBreaker (fault tolerance)
- PatternCache (offline caching)
- Phase4HealthChecker (health monitoring)
- Graceful degradation decorators

Run tests:
    cd /Users/jonah/.claude/hooks
    python -m pytest lib/test_resilience.py -v
"""

import pytest
import asyncio
import time
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from lib.resilience import (
    ResilientExecutor,
    CircuitBreaker,
    PatternCache,
    Phase4HealthChecker,
    graceful_tracking,
    ResilientAPIClient,
    CachedPatternEvent,
)


# ============================================================================
# ResilientExecutor Tests
# ============================================================================


@pytest.mark.asyncio
async def test_fire_and_forget_success():
    """Test fire-and-forget with successful task"""
    executor = ResilientExecutor()
    result_holder = []

    async def successful_task():
        await asyncio.sleep(0.01)
        result_holder.append("success")
        return "done"

    # Fire and forget
    task = executor.fire_and_forget(successful_task())

    # Should not block
    assert len(result_holder) == 0

    # Wait for completion
    await asyncio.sleep(0.05)
    assert result_holder == ["success"]

    # Check stats
    stats = executor.get_stats()
    assert stats["total_tasks"] == 1
    assert stats["success_count"] == 1
    assert stats["error_count"] == 0


@pytest.mark.asyncio
async def test_fire_and_forget_error_handling():
    """Test fire-and-forget handles errors gracefully"""
    executor = ResilientExecutor()

    async def failing_task():
        await asyncio.sleep(0.01)
        raise ValueError("Task failed")

    # Should not raise
    task = executor.fire_and_forget(failing_task())

    # Wait for completion
    await asyncio.sleep(0.05)

    # Check stats - error should be recorded
    stats = executor.get_stats()
    assert stats["total_tasks"] == 1
    assert stats["error_count"] == 1
    assert stats["success_count"] == 0


@pytest.mark.asyncio
async def test_executor_wait_for_completion():
    """Test waiting for all tasks to complete"""
    executor = ResilientExecutor()
    completed = []

    async def slow_task(task_id):
        await asyncio.sleep(0.02)
        completed.append(task_id)

    # Start multiple tasks
    for i in range(3):
        executor.fire_and_forget(slow_task(i))

    # Wait for completion
    success = await executor.wait_for_completion(timeout=1.0)

    assert success is True
    assert len(completed) == 3
    assert set(completed) == {0, 1, 2}


# ============================================================================
# CircuitBreaker Tests
# ============================================================================


@pytest.mark.asyncio
async def test_circuit_breaker_closed_state():
    """Test circuit breaker in closed state (normal operation)"""
    breaker = CircuitBreaker(failure_threshold=3, timeout=60)

    async def successful_call():
        return "success"

    result = await breaker.call(successful_call)
    assert result == "success"

    state = breaker.get_state()
    assert state["state"] == "closed"
    assert state["failure_count"] == 0


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures():
    """Test circuit breaker opens after threshold failures"""
    breaker = CircuitBreaker(failure_threshold=3, timeout=1)

    async def failing_call():
        raise ConnectionError("API unavailable")

    # Make failing calls
    for i in range(3):
        result = await breaker.call(failing_call)
        assert result is None

    # Circuit should be open now
    state = breaker.get_state()
    assert state["state"] == "open"
    assert state["failure_count"] == 3

    # Further calls should be blocked
    result = await breaker.call(failing_call)
    assert result is None


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_transition():
    """Test circuit breaker transitions to half-open after timeout"""
    breaker = CircuitBreaker(failure_threshold=2, timeout=0.1)

    async def failing_call():
        raise ConnectionError("API unavailable")

    # Open the circuit
    await breaker.call(failing_call)
    await breaker.call(failing_call)

    state = breaker.get_state()
    assert state["state"] == "open"

    # Wait for timeout
    await asyncio.sleep(0.15)

    # Next call should try (half-open)
    async def successful_call():
        return "recovered"

    result = await breaker.call(successful_call)
    assert result == "recovered"

    # Should be closed now
    state = breaker.get_state()
    assert state["state"] == "closed"


@pytest.mark.asyncio
async def test_circuit_breaker_reset():
    """Test manual circuit breaker reset"""
    breaker = CircuitBreaker(failure_threshold=2)

    async def failing_call():
        raise ValueError("Error")

    # Open the circuit
    await breaker.call(failing_call)
    await breaker.call(failing_call)

    assert breaker.get_state()["state"] == "open"

    # Manual reset
    breaker.reset()

    state = breaker.get_state()
    assert state["state"] == "closed"
    assert state["failure_count"] == 0


# ============================================================================
# PatternCache Tests
# ============================================================================


@pytest.mark.asyncio
async def test_cache_pattern_event(tmp_path):
    """Test caching pattern event"""
    cache = PatternCache(cache_dir=tmp_path / "test_cache")

    event = {"event_type": "pattern_created", "pattern_id": "test-001", "pattern_data": {"code": "function test() {}"}}

    event_id = await cache.cache_pattern_event(event)

    assert event_id != ""
    assert "test-001" in event_id

    # Check file was created
    cache_files = list(cache.cache_dir.glob("pending_*.json"))
    assert len(cache_files) == 1

    # Verify content
    with open(cache_files[0]) as f:
        cached_data = json.load(f)
        assert cached_data["pattern_id"] == "test-001"
        assert cached_data["event_type"] == "pattern_created"


@pytest.mark.asyncio
async def test_cache_sync_events(tmp_path):
    """Test syncing cached events"""
    cache = PatternCache(cache_dir=tmp_path / "test_cache")

    # Create cached events
    for i in range(3):
        await cache.cache_pattern_event(
            {"event_type": "pattern_created", "pattern_id": f"test-{i:03d}", "pattern_data": {}}
        )

    # Mock API client
    api_client = MagicMock()
    api_client.track_lineage = AsyncMock(return_value={"success": True})

    # Sync events
    stats = await cache.sync_cached_events(api_client)

    assert stats["total_found"] == 3
    assert stats["synced"] == 3
    assert stats["failed"] == 0

    # Cache files should be deleted
    cache_files = list(cache.cache_dir.glob("pending_*.json"))
    assert len(cache_files) == 0


@pytest.mark.asyncio
async def test_cache_sync_with_failures(tmp_path):
    """Test sync handles failures gracefully"""
    cache = PatternCache(cache_dir=tmp_path / "test_cache")

    # Create cached events
    await cache.cache_pattern_event({"event_type": "pattern_created", "pattern_id": "test-001", "pattern_data": {}})

    # Mock API client that fails
    api_client = MagicMock()
    api_client.track_lineage = AsyncMock(side_effect=ConnectionError("API unavailable"))

    # Sync should handle failure
    stats = await cache.sync_cached_events(api_client)

    assert stats["total_found"] == 1
    assert stats["failed"] == 1
    assert stats["synced"] == 0

    # Cache file should still exist
    cache_files = list(cache.cache_dir.glob("pending_*.json"))
    assert len(cache_files) == 1


@pytest.mark.asyncio
async def test_cache_cleanup_old_events(tmp_path):
    """Test cleanup of old cached events"""
    cache = PatternCache(cache_dir=tmp_path / "test_cache", max_age_days=1)

    # Create an old event (mock timestamp)
    event_id = await cache.cache_pattern_event(
        {"event_type": "pattern_created", "pattern_id": "old-001", "pattern_data": {}}
    )

    # Manually modify timestamp to make it old
    cache_files = list(cache.cache_dir.glob("pending_*.json"))
    assert len(cache_files) == 1

    with open(cache_files[0]) as f:
        event_data = json.load(f)

    # Set old timestamp (2 days ago)
    from datetime import datetime, timedelta

    old_time = datetime.utcnow() - timedelta(days=2)
    event_data["timestamp"] = old_time.isoformat()

    with open(cache_files[0], "w") as f:
        json.dump(event_data, f)

    # Run cleanup
    cleaned = await cache.cleanup_old_events()

    assert cleaned == 1

    # Cache should be empty
    cache_files = list(cache.cache_dir.glob("pending_*.json"))
    assert len(cache_files) == 0


# ============================================================================
# Phase4HealthChecker Tests
# ============================================================================


@pytest.mark.asyncio
async def test_health_checker_healthy_api():
    """Test health checker with healthy API"""
    with patch("httpx.AsyncClient") as mock_client:
        # Mock successful health check
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy"}

        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

        checker = Phase4HealthChecker(base_url="http://localhost:8053")
        is_healthy = await checker.check_health(force=True)

        assert is_healthy is True
        assert checker.consecutive_successes == 1
        assert checker.consecutive_failures == 0


@pytest.mark.asyncio
async def test_health_checker_unhealthy_api():
    """Test health checker with unhealthy API"""
    with patch("httpx.AsyncClient") as mock_client:
        # Mock failed health check
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=ConnectionError("Connection refused")
        )

        checker = Phase4HealthChecker(base_url="http://localhost:8053")
        is_healthy = await checker.check_health(force=True)

        assert is_healthy is False
        assert checker.consecutive_failures == 1
        assert checker.consecutive_successes == 0


@pytest.mark.asyncio
async def test_health_checker_caching():
    """Test health check result caching"""
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy"}

        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        checker = Phase4HealthChecker(base_url="http://localhost:8053", check_interval=60)

        # First check
        is_healthy = await checker.check_health(force=True)
        assert is_healthy is True
        assert mock_get.call_count == 1

        # Second check should use cache
        is_healthy = await checker.check_health()
        assert is_healthy is True
        assert mock_get.call_count == 1  # Not called again


# ============================================================================
# Graceful Degradation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_graceful_tracking_success():
    """Test graceful tracking with successful function"""

    @graceful_tracking(fallback_return={})
    async def track_pattern(pattern_id):
        return {"success": True, "pattern_id": pattern_id}

    result = await track_pattern("test-001")
    assert result == {"success": True, "pattern_id": "test-001"}


@pytest.mark.asyncio
async def test_graceful_tracking_handles_errors():
    """Test graceful tracking handles errors gracefully"""

    @graceful_tracking(fallback_return={"error": "fallback"})
    async def failing_function():
        raise ValueError("Something went wrong")

    result = await failing_function()
    assert result == {"error": "fallback"}


@pytest.mark.asyncio
async def test_graceful_tracking_custom_fallback():
    """Test graceful tracking with custom fallback"""

    @graceful_tracking(fallback_return=None)
    async def nullable_function():
        raise ConnectionError("API down")

    result = await nullable_function()
    assert result is None


# ============================================================================
# ResilientAPIClient Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_resilient_client_successful_tracking(tmp_path):
    """Test resilient client with successful API call"""
    with patch("httpx.AsyncClient") as mock_http:
        # Mock health check
        health_response = MagicMock()
        health_response.status_code = 200
        health_response.json.return_value = {"status": "healthy"}

        # Mock tracking API
        track_response = MagicMock()
        track_response.status_code = 200
        track_response.json.return_value = {"success": True, "data": {"node_id": "node-123"}}

        async def mock_request(url, **kwargs):
            if "health" in url:
                return health_response
            else:
                return track_response

        mock_client_instance = MagicMock()
        mock_client_instance.get = AsyncMock(side_effect=mock_request)
        mock_client_instance.post = AsyncMock(side_effect=mock_request)

        mock_http.return_value.__aenter__.return_value = mock_client_instance

        # Create client
        client = ResilientAPIClient(base_url="http://localhost:8053")
        client.cache.cache_dir = tmp_path / "cache"

        # Track pattern
        result = await client.track_pattern_resilient(
            event_type="pattern_created", pattern_id="test-001", pattern_data={"code": "test"}
        )

        assert result["success"] is True
        assert result["cached"] is False


@pytest.mark.asyncio
async def test_resilient_client_caches_when_api_down(tmp_path):
    """Test resilient client caches events when API is down"""
    with patch("httpx.AsyncClient") as mock_http:
        # Mock failed health check
        mock_http.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=ConnectionError("Connection refused")
        )

        # Create client
        client = ResilientAPIClient(base_url="http://localhost:8053")
        client.cache.cache_dir = tmp_path / "cache"

        # Track pattern (should cache)
        result = await client.track_pattern_resilient(
            event_type="pattern_created", pattern_id="test-001", pattern_data={"code": "test"}
        )

        assert result["success"] is False
        assert result["cached"] is True
        assert "event_id" in result

        # Verify cached file exists
        cache_files = list(client.cache.cache_dir.glob("pending_*.json"))
        assert len(cache_files) == 1


@pytest.mark.asyncio
async def test_resilient_client_stats():
    """Test resilient client statistics"""
    client = ResilientAPIClient(base_url="http://localhost:8053")

    stats = await client.get_stats()

    assert "executor" in stats
    assert "health" in stats
    assert "circuit_breaker" in stats
    assert "cache" in stats


# ============================================================================
# Integration Test: Complete Workflow
# ============================================================================


@pytest.mark.asyncio
async def test_complete_resilience_workflow(tmp_path):
    """Test complete resilience workflow from cache to sync"""
    with patch("httpx.AsyncClient") as mock_http:
        # Stage 1: API is down - events get cached
        mock_http.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=ConnectionError("Connection refused")
        )

        client = ResilientAPIClient(base_url="http://localhost:8053")
        client.cache.cache_dir = tmp_path / "cache"

        # Track multiple patterns while API is down
        for i in range(3):
            result = await client.track_pattern_resilient(
                event_type="pattern_created", pattern_id=f"test-{i:03d}", pattern_data={"code": f"test {i}"}
            )
            assert result["cached"] is True

        # Verify 3 cached files
        cache_files = list(client.cache.cache_dir.glob("pending_*.json"))
        assert len(cache_files) == 3

        # Stage 2: API comes back online
        health_response = MagicMock()
        health_response.status_code = 200
        health_response.json.return_value = {"status": "healthy"}

        track_response = MagicMock()
        track_response.status_code = 200
        track_response.json.return_value = {"success": True}

        async def mock_healthy_request(url, **kwargs):
            if "health" in url:
                return health_response
            else:
                return track_response

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=mock_healthy_request)
        mock_client.post = AsyncMock(side_effect=mock_healthy_request)
        mock_http.return_value.__aenter__.return_value = mock_client

        # Mock track_lineage for sync
        client.track_lineage = AsyncMock(return_value={"success": True})

        # Manually sync cached events
        sync_stats = await client.cache.sync_cached_events(client)

        assert sync_stats["synced"] == 3
        assert sync_stats["failed"] == 0

        # Cache should be empty now
        cache_files = list(client.cache.cache_dir.glob("pending_*.json"))
        assert len(cache_files) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
