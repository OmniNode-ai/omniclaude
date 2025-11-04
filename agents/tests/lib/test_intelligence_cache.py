"""
Comprehensive test suite for intelligence_cache.py

Tests cover:
- Cache initialization (enabled/disabled states)
- Connection handling (success, ImportError, connection failures)
- Cache key generation
- Get operations (cache hit, miss, errors)
- Set operations (with default and custom TTL, errors)
- Cache invalidation (pattern-based and full clear)
- Statistics retrieval
- Error handling and graceful degradation
- Async operations

Coverage target: 80%+ (from 42%)
Missing lines covered: 77-78, 109, 123, 126-130, 141-142, 147-151, 160-173, 186-200, 204-213, 217-226, 233-250
"""

import json
import os
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.lib.intelligence_cache import IntelligenceCache


# Test fixtures
@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client with async methods."""
    client = AsyncMock()
    client.ping = AsyncMock()
    client.get = AsyncMock()
    client.setex = AsyncMock()
    client.delete = AsyncMock()
    client.keys = AsyncMock()
    client.close = AsyncMock()
    client.info = AsyncMock()
    return client


@pytest.fixture
def sample_params() -> Dict[str, Any]:
    """Sample query parameters for testing."""
    return {
        "collection": "code_patterns",
        "limit": 50,
        "include_patterns": True,
    }


@pytest.fixture
def sample_result() -> Dict[str, Any]:
    """Sample query result for caching."""
    return {
        "patterns": [
            {
                "name": "Node State Management",
                "confidence": 0.95,
                "file_path": "node_state_manager.py",
            }
        ],
        "total_count": 1,
        "query_time_ms": 450,
    }


class TestIntelligenceCacheInitialization:
    """Test cache initialization and configuration."""

    def test_cache_enabled_by_default(self):
        """Test cache is enabled by default."""
        cache = IntelligenceCache()
        assert cache.enabled is True

    def test_cache_disabled_via_parameter(self):
        """Test cache can be disabled via constructor parameter."""
        cache = IntelligenceCache(enabled=False)
        assert cache.enabled is False

    @patch.dict(os.environ, {"ENABLE_INTELLIGENCE_CACHE": "false"})
    def test_cache_disabled_via_env_var(self):
        """Test cache disabled via environment variable (covers lines 77-78)."""
        cache = IntelligenceCache()
        assert cache.enabled is False

    def test_default_redis_url(self):
        """Test default Redis URL is set correctly."""
        cache = IntelligenceCache()
        assert "archon-valkey:6379" in cache.redis_url
        assert "archon_cache_2025" in cache.redis_url

    def test_custom_redis_url(self):
        """Test custom Redis URL can be provided."""
        custom_url = "redis://:custom_password@localhost:6379/0"
        cache = IntelligenceCache(redis_url=custom_url)
        assert cache.redis_url == custom_url

    @patch.dict(os.environ, {"VALKEY_URL": "redis://env_url:6379/0"})
    def test_redis_url_from_env(self):
        """Test Redis URL from environment variable."""
        cache = IntelligenceCache()
        assert cache.redis_url == "redis://env_url:6379/0"

    def test_default_ttls(self):
        """Test default TTL values are set correctly."""
        cache = IntelligenceCache()
        assert cache._default_ttls["pattern_discovery"] == 300
        assert cache._default_ttls["infrastructure_query"] == 3600
        assert cache._default_ttls["schema_query"] == 1800
        assert cache._default_ttls["model_query"] == 3600

    @patch.dict(os.environ, {"CACHE_TTL_PATTERNS": "600"})
    def test_custom_ttl_from_env(self):
        """Test custom TTL from environment variable."""
        cache = IntelligenceCache()
        assert cache._default_ttls["pattern_discovery"] == 600


class TestIntelligenceCacheConnection:
    """Test cache connection handling."""

    @pytest.mark.asyncio
    async def test_connect_when_disabled(self):
        """Test connect() returns early when cache is disabled (covers line 109)."""
        cache = IntelligenceCache(enabled=False)
        await cache.connect()
        # _client is only set if cache is enabled, so we just verify connect doesn't raise

    @pytest.mark.asyncio
    async def test_connect_success(self, mock_redis_client):
        """Test successful connection to Redis (covers line 123)."""
        cache = IntelligenceCache()

        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.from_url = AsyncMock(return_value=mock_redis_client)
            await cache.connect()

            assert cache._client is mock_redis_client
            mock_redis_client.ping.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_import_error(self):
        """Test handling of missing redis module (covers lines 126-130)."""
        cache = IntelligenceCache()

        # Patch the import itself
        with patch.dict("sys.modules", {"redis.asyncio": None}):
            with patch("builtins.__import__", side_effect=ImportError("redis not found")):
                await cache.connect()

                assert cache.enabled is False

    @pytest.mark.asyncio
    async def test_connect_connection_error(self, mock_redis_client):
        """Test handling of connection failure."""
        cache = IntelligenceCache()
        mock_redis_client.ping.side_effect = Exception("Connection refused")

        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.from_url = AsyncMock(return_value=mock_redis_client)
            await cache.connect()

            assert cache.enabled is False

    @pytest.mark.asyncio
    async def test_close_success(self, mock_redis_client):
        """Test successful connection close."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        await cache.close()
        mock_redis_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_with_error(self, mock_redis_client):
        """Test close() handles errors gracefully (covers lines 141-142)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client
        mock_redis_client.close.side_effect = Exception("Close error")

        # Should not raise exception
        await cache.close()

    @pytest.mark.asyncio
    async def test_close_when_no_client(self):
        """Test close() when client is None."""
        cache = IntelligenceCache()
        cache._client = None

        # Should not raise exception
        await cache.close()


class TestIntelligenceCacheKeyGeneration:
    """Test cache key generation."""

    def test_generate_cache_key_deterministic(self):
        """Test cache key generation is deterministic (covers lines 147-151)."""
        cache = IntelligenceCache()
        params = {"collection": "code_patterns", "limit": 50}

        key1 = cache._generate_cache_key("pattern_discovery", params)
        key2 = cache._generate_cache_key("pattern_discovery", params)

        assert key1 == key2

    def test_generate_cache_key_different_params(self):
        """Test different parameters produce different keys."""
        cache = IntelligenceCache()
        params1 = {"collection": "code_patterns", "limit": 50}
        params2 = {"collection": "execution_patterns", "limit": 100}

        key1 = cache._generate_cache_key("pattern_discovery", params1)
        key2 = cache._generate_cache_key("pattern_discovery", params2)

        assert key1 != key2

    def test_generate_cache_key_format(self):
        """Test cache key format matches expected pattern."""
        cache = IntelligenceCache()
        params = {"collection": "code_patterns"}

        key = cache._generate_cache_key("pattern_discovery", params)

        assert key.startswith("intelligence:pattern_discovery:")
        # Hash should be 12 characters
        hash_part = key.split(":")[-1]
        assert len(hash_part) == 12

    def test_generate_cache_key_param_order_independent(self):
        """Test cache key is same regardless of parameter order."""
        cache = IntelligenceCache()
        params1 = {"a": 1, "b": 2, "c": 3}
        params2 = {"c": 3, "b": 2, "a": 1}

        key1 = cache._generate_cache_key("test", params1)
        key2 = cache._generate_cache_key("test", params2)

        assert key1 == key2


class TestIntelligenceCacheGet:
    """Test cache get operations."""

    @pytest.mark.asyncio
    async def test_get_when_disabled(self, sample_params):
        """Test get() returns None when cache is disabled."""
        cache = IntelligenceCache(enabled=False)
        result = await cache.get("pattern_discovery", sample_params)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_when_no_client(self, sample_params):
        """Test get() returns None when client is not connected."""
        cache = IntelligenceCache()
        cache._client = None
        result = await cache.get("pattern_discovery", sample_params)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_cache_hit(self, mock_redis_client, sample_params, sample_result):
        """Test cache hit returns cached data (covers lines 164-166)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock cache hit
        mock_redis_client.get.return_value = json.dumps(sample_result)

        result = await cache.get("pattern_discovery", sample_params)

        assert result == sample_result
        mock_redis_client.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_cache_miss(self, mock_redis_client, sample_params):
        """Test cache miss returns None (covers lines 168-169)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock cache miss
        mock_redis_client.get.return_value = None

        result = await cache.get("pattern_discovery", sample_params)

        assert result is None
        mock_redis_client.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_with_error(self, mock_redis_client, sample_params):
        """Test get() handles errors gracefully (covers lines 170-173)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock error
        mock_redis_client.get.side_effect = Exception("Redis error")

        result = await cache.get("pattern_discovery", sample_params)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_with_invalid_json(self, mock_redis_client, sample_params):
        """Test get() handles invalid JSON gracefully."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock invalid JSON
        mock_redis_client.get.return_value = "invalid json{{"

        result = await cache.get("pattern_discovery", sample_params)

        assert result is None


class TestIntelligenceCacheSet:
    """Test cache set operations."""

    @pytest.mark.asyncio
    async def test_set_when_disabled(self, sample_params, sample_result):
        """Test set() does nothing when cache is disabled."""
        cache = IntelligenceCache(enabled=False)
        # Should not raise exception
        await cache.set("pattern_discovery", sample_params, sample_result)

    @pytest.mark.asyncio
    async def test_set_when_no_client(self, sample_params, sample_result):
        """Test set() does nothing when client is not connected."""
        cache = IntelligenceCache()
        cache._client = None
        # Should not raise exception
        await cache.set("pattern_discovery", sample_params, sample_result)

    @pytest.mark.asyncio
    async def test_set_with_default_ttl(self, mock_redis_client, sample_params, sample_result):
        """Test set() uses default TTL (covers lines 189-194)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        await cache.set("pattern_discovery", sample_params, sample_result)

        # Verify setex was called with default TTL (300 seconds)
        mock_redis_client.setex.assert_awaited_once()
        call_args = mock_redis_client.setex.call_args
        assert call_args[0][1] == 300  # Default TTL for pattern_discovery

    @pytest.mark.asyncio
    async def test_set_with_custom_ttl(self, mock_redis_client, sample_params, sample_result):
        """Test set() uses custom TTL when provided (covers lines 186-197)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        custom_ttl = 600
        await cache.set("pattern_discovery", sample_params, sample_result, ttl_seconds=custom_ttl)

        # Verify setex was called with custom TTL
        call_args = mock_redis_client.setex.call_args
        assert call_args[0][1] == custom_ttl

    @pytest.mark.asyncio
    async def test_set_with_error(self, mock_redis_client, sample_params, sample_result):
        """Test set() handles errors gracefully (covers lines 198-200)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock error
        mock_redis_client.setex.side_effect = Exception("Redis error")

        # Should not raise exception
        await cache.set("pattern_discovery", sample_params, sample_result)

    @pytest.mark.asyncio
    async def test_set_serializes_result(self, mock_redis_client, sample_params, sample_result):
        """Test set() correctly serializes result to JSON."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        await cache.set("pattern_discovery", sample_params, sample_result)

        # Verify JSON serialization
        call_args = mock_redis_client.setex.call_args
        stored_json = call_args[0][2]
        assert json.loads(stored_json) == sample_result


class TestIntelligenceCacheInvalidation:
    """Test cache invalidation operations."""

    @pytest.mark.asyncio
    async def test_invalidate_pattern_when_disabled(self):
        """Test invalidate_pattern() does nothing when disabled."""
        cache = IntelligenceCache(enabled=False)
        # Should not raise exception
        await cache.invalidate_pattern("pattern_discovery")

    @pytest.mark.asyncio
    async def test_invalidate_pattern_when_no_client(self):
        """Test invalidate_pattern() does nothing when no client."""
        cache = IntelligenceCache()
        cache._client = None
        # Should not raise exception
        await cache.invalidate_pattern("pattern_discovery")

    @pytest.mark.asyncio
    async def test_invalidate_pattern_success(self, mock_redis_client):
        """Test successful pattern invalidation (covers lines 207-211)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock finding keys
        mock_keys = ["intelligence:pattern_discovery:abc123", "intelligence:pattern_discovery:def456"]
        mock_redis_client.keys.return_value = mock_keys

        await cache.invalidate_pattern("pattern_discovery")

        # Verify keys were searched and deleted
        mock_redis_client.keys.assert_awaited_once_with("intelligence:*pattern_discovery*")
        mock_redis_client.delete.assert_awaited_once_with(*mock_keys)

    @pytest.mark.asyncio
    async def test_invalidate_pattern_no_keys(self, mock_redis_client):
        """Test invalidate_pattern() when no keys match."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock no keys found
        mock_redis_client.keys.return_value = []

        await cache.invalidate_pattern("nonexistent")

        # Delete should not be called
        mock_redis_client.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalidate_pattern_with_error(self, mock_redis_client):
        """Test invalidate_pattern() handles errors gracefully (covers lines 212-213)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock error
        mock_redis_client.keys.side_effect = Exception("Redis error")

        # Should not raise exception
        await cache.invalidate_pattern("pattern_discovery")

    @pytest.mark.asyncio
    async def test_invalidate_all_when_disabled(self):
        """Test invalidate_all() does nothing when disabled."""
        cache = IntelligenceCache(enabled=False)
        # Should not raise exception
        await cache.invalidate_all()

    @pytest.mark.asyncio
    async def test_invalidate_all_when_no_client(self):
        """Test invalidate_all() does nothing when no client."""
        cache = IntelligenceCache()
        cache._client = None
        # Should not raise exception
        await cache.invalidate_all()

    @pytest.mark.asyncio
    async def test_invalidate_all_success(self, mock_redis_client):
        """Test successful cache clear (covers lines 221-224)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock finding keys
        mock_keys = [
            "intelligence:pattern_discovery:abc123",
            "intelligence:schema_query:def456",
            "intelligence:model_query:ghi789",
        ]
        mock_redis_client.keys.return_value = mock_keys

        await cache.invalidate_all()

        # Verify all intelligence keys were deleted
        mock_redis_client.keys.assert_awaited_once_with("intelligence:*")
        mock_redis_client.delete.assert_awaited_once_with(*mock_keys)

    @pytest.mark.asyncio
    async def test_invalidate_all_no_keys(self, mock_redis_client):
        """Test invalidate_all() when cache is empty."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock no keys found
        mock_redis_client.keys.return_value = []

        await cache.invalidate_all()

        # Delete should not be called
        mock_redis_client.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalidate_all_with_error(self, mock_redis_client):
        """Test invalidate_all() handles errors gracefully (covers lines 225-226)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock error
        mock_redis_client.keys.side_effect = Exception("Redis error")

        # Should not raise exception
        await cache.invalidate_all()


class TestIntelligenceCacheStats:
    """Test cache statistics retrieval."""

    @pytest.mark.asyncio
    async def test_get_stats_when_disabled(self):
        """Test get_stats() when cache is disabled."""
        cache = IntelligenceCache(enabled=False)
        stats = await cache.get_stats()

        assert stats == {"enabled": False}

    @pytest.mark.asyncio
    async def test_get_stats_when_no_client(self):
        """Test get_stats() when client is not connected."""
        cache = IntelligenceCache()
        cache._client = None
        stats = await cache.get_stats()

        assert stats == {"enabled": False}

    @pytest.mark.asyncio
    async def test_get_stats_success(self, mock_redis_client):
        """Test successful stats retrieval (covers lines 234-247)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock Redis stats
        mock_redis_client.info.return_value = {
            "keyspace_hits": 150,
            "keyspace_misses": 50,
        }

        stats = await cache.get_stats()

        assert stats["enabled"] is True
        assert stats["keyspace_hits"] == 150
        assert stats["keyspace_misses"] == 50
        assert stats["hit_rate"] == 0.75  # 150 / 200
        assert stats["hit_rate_percent"] == 75.0

    @pytest.mark.asyncio
    async def test_get_stats_zero_requests(self, mock_redis_client):
        """Test get_stats() when no requests have been made (covers line 239)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock Redis stats with zero hits/misses
        mock_redis_client.info.return_value = {
            "keyspace_hits": 0,
            "keyspace_misses": 0,
        }

        stats = await cache.get_stats()

        assert stats["hit_rate"] == 0.0
        assert stats["hit_rate_percent"] == 0.0

    @pytest.mark.asyncio
    async def test_get_stats_with_error(self, mock_redis_client):
        """Test get_stats() handles errors gracefully (covers lines 248-250)."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock error
        mock_redis_client.info.side_effect = Exception("Redis error")

        stats = await cache.get_stats()

        assert stats["enabled"] is True
        assert stats["error"] == "Stats unavailable"

    @pytest.mark.asyncio
    async def test_get_stats_missing_keys(self, mock_redis_client):
        """Test get_stats() handles missing info keys."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Mock incomplete stats
        mock_redis_client.info.return_value = {}

        stats = await cache.get_stats()

        # Should default to 0 for missing keys
        assert stats["keyspace_hits"] == 0
        assert stats["keyspace_misses"] == 0
        assert stats["hit_rate"] == 0.0


class TestIntelligenceCacheIntegration:
    """Integration tests for cache workflows."""

    @pytest.mark.asyncio
    async def test_full_cache_workflow(self, mock_redis_client, sample_params, sample_result):
        """Test complete cache workflow: connect -> get (miss) -> set -> get (hit) -> close."""
        cache = IntelligenceCache()

        # Connect
        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.from_url = AsyncMock(return_value=mock_redis_client)
            await cache.connect()

        # First get - cache miss
        mock_redis_client.get.return_value = None
        result1 = await cache.get("pattern_discovery", sample_params)
        assert result1 is None

        # Set cache
        await cache.set("pattern_discovery", sample_params, sample_result)

        # Second get - cache hit
        mock_redis_client.get.return_value = json.dumps(sample_result)
        result2 = await cache.get("pattern_discovery", sample_params)
        assert result2 == sample_result

        # Close
        await cache.close()

    @pytest.mark.asyncio
    async def test_cache_disabled_workflow(self, sample_params, sample_result):
        """Test workflow when cache is disabled."""
        cache = IntelligenceCache(enabled=False)

        await cache.connect()
        result = await cache.get("pattern_discovery", sample_params)
        assert result is None

        await cache.set("pattern_discovery", sample_params, sample_result)

        stats = await cache.get_stats()
        assert stats == {"enabled": False}

        # No need to close when disabled - _client never initialized

    @pytest.mark.asyncio
    async def test_cache_resilience_on_failures(self, mock_redis_client, sample_params, sample_result):
        """Test cache continues to work after individual operation failures."""
        cache = IntelligenceCache()

        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.from_url = AsyncMock(return_value=mock_redis_client)
            await cache.connect()

        # Simulate get failure
        mock_redis_client.get.side_effect = Exception("Get error")
        result = await cache.get("pattern_discovery", sample_params)
        assert result is None

        # Set should still work after get failure
        mock_redis_client.setex.side_effect = None
        mock_redis_client.get.side_effect = None
        await cache.set("pattern_discovery", sample_params, sample_result)

        # Get should work again
        mock_redis_client.get.return_value = json.dumps(sample_result)
        result = await cache.get("pattern_discovery", sample_params)
        assert result == sample_result


class TestIntelligenceCacheEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_empty_params(self, mock_redis_client):
        """Test cache with empty parameters."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        empty_params = {}
        result = {"data": "test"}

        await cache.set("test", empty_params, result)
        mock_redis_client.get.return_value = json.dumps(result)

        cached = await cache.get("test", empty_params)
        assert cached == result

    @pytest.mark.asyncio
    async def test_large_result(self, mock_redis_client):
        """Test caching large results."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        # Create large result
        large_result = {
            "patterns": [{"name": f"pattern_{i}", "data": "x" * 1000} for i in range(100)]
        }

        params = {"test": "large"}
        await cache.set("pattern_discovery", params, large_result)

        mock_redis_client.get.return_value = json.dumps(large_result)
        cached = await cache.get("pattern_discovery", params)

        assert cached == large_result

    @pytest.mark.asyncio
    async def test_special_characters_in_params(self, mock_redis_client):
        """Test cache key generation with special characters."""
        cache = IntelligenceCache()
        cache._client = mock_redis_client

        params = {
            "query": "test with spaces",
            "special": "chars!@#$%^&*()",
            "unicode": "测试",
        }

        result = {"data": "test"}
        await cache.set("test", params, result)

        # Should handle special characters without errors
        mock_redis_client.get.return_value = json.dumps(result)
        cached = await cache.get("test", params)
        assert cached == result

    def test_all_operation_types_have_ttls(self):
        """Test all expected operation types have default TTLs."""
        cache = IntelligenceCache()

        expected_operations = [
            "pattern_discovery",
            "infrastructure_query",
            "schema_query",
            "model_query",
            "debug_intelligence_query",
            "filesystem_query",
        ]

        for operation in expected_operations:
            assert operation in cache._default_ttls
            assert cache._default_ttls[operation] > 0


class TestIntelligenceCacheModuleExports:
    """Test module exports and public API."""

    def test_module_exports(self):
        """Test __all__ exports correct classes."""
        from agents.lib import intelligence_cache

        assert "IntelligenceCache" in intelligence_cache.__all__
        assert len(intelligence_cache.__all__) == 1

    def test_class_instantiation(self):
        """Test IntelligenceCache can be instantiated."""
        cache = IntelligenceCache()
        assert isinstance(cache, IntelligenceCache)
