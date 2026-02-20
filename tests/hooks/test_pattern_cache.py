# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for the pattern projection cache (OMN-2425).

Verifies:
1. Cache is empty on init
2. is_warm() is False before first update
3. update() makes is_warm() True
4. get() returns correct patterns for domain
5. Staleness: cache is stale after threshold exceeded
6. get() returns empty list for unknown domain (not None)

Part of OMN-2425: consume pattern projection and cache for context injection.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from plugins.onex.hooks.lib.pattern_cache import PatternProjectionCache

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def cache() -> PatternProjectionCache:
    """Return a fresh PatternProjectionCache for each test."""
    return PatternProjectionCache()


# =============================================================================
# Initialization tests
# =============================================================================


class TestPatternCacheInit:
    """Tests for initial cache state."""

    def test_cache_is_empty_on_init(self, cache: PatternProjectionCache) -> None:
        """Cache holds no patterns when first created."""
        result = cache.get("general")
        assert result == []

    def test_is_warm_is_false_before_first_update(
        self, cache: PatternProjectionCache
    ) -> None:
        """is_warm() returns False when no update has been called."""
        assert cache.is_warm() is False

    def test_is_stale_is_true_when_cold(self, cache: PatternProjectionCache) -> None:
        """is_stale() returns True when the cache has never been updated."""
        assert cache.is_stale() is True


# =============================================================================
# Update and retrieval tests
# =============================================================================


class TestPatternCacheUpdate:
    """Tests for update and get operations."""

    def test_update_makes_is_warm_true(self, cache: PatternProjectionCache) -> None:
        """After update(), is_warm() returns True."""
        cache.update(
            "general", [{"id": "p1", "pattern_signature": "x", "confidence": 0.9}]
        )
        assert cache.is_warm() is True

    def test_get_returns_correct_patterns_for_domain(
        self, cache: PatternProjectionCache
    ) -> None:
        """get() returns the patterns stored for the given domain."""
        patterns = [
            {"id": "p1", "pattern_signature": "pattern one", "confidence": 0.85},
            {"id": "p2", "pattern_signature": "pattern two", "confidence": 0.75},
        ]
        cache.update("testing", patterns)
        result = cache.get("testing")
        assert len(result) == 2
        assert result[0]["id"] == "p1"
        assert result[1]["id"] == "p2"

    def test_get_returns_empty_list_for_unknown_domain(
        self, cache: PatternProjectionCache
    ) -> None:
        """get() returns [] (not None) for a domain that was never stored."""
        cache.update(
            "general", [{"id": "p1", "pattern_signature": "x", "confidence": 0.9}]
        )
        result = cache.get("nonexistent_domain")
        assert result == []
        assert result is not None

    def test_get_returns_copy_not_reference(
        self, cache: PatternProjectionCache
    ) -> None:
        """get() returns a copy; mutating the result does not affect the cache."""
        patterns = [{"id": "p1", "pattern_signature": "x", "confidence": 0.9}]
        cache.update("general", patterns)
        returned = cache.get("general")
        returned.clear()
        assert len(cache.get("general")) == 1

    def test_update_replaces_existing_patterns(
        self, cache: PatternProjectionCache
    ) -> None:
        """Calling update() again replaces the previously cached patterns."""
        cache.update(
            "general", [{"id": "old", "pattern_signature": "old", "confidence": 0.9}]
        )
        cache.update(
            "general",
            [
                {"id": "new1", "pattern_signature": "n1", "confidence": 0.8},
                {"id": "new2", "pattern_signature": "n2", "confidence": 0.7},
            ],
        )
        result = cache.get("general")
        assert len(result) == 2
        assert result[0]["id"] == "new1"

    def test_get_with_none_domain_returns_general(
        self, cache: PatternProjectionCache
    ) -> None:
        """get(None) falls back to the 'general' domain key."""
        cache.update(
            "general", [{"id": "g1", "pattern_signature": "g", "confidence": 0.9}]
        )
        result = cache.get(None)
        assert len(result) == 1
        assert result[0]["id"] == "g1"


# =============================================================================
# Staleness tests
# =============================================================================


class TestPatternCacheStaleness:
    """Tests for staleness detection."""

    def test_cache_is_not_stale_immediately_after_update(
        self, cache: PatternProjectionCache
    ) -> None:
        """is_stale() returns False right after update()."""
        cache.update(
            "general", [{"id": "p1", "pattern_signature": "x", "confidence": 0.9}]
        )
        assert cache.is_stale() is False

    def test_cache_is_stale_after_threshold_exceeded(
        self, cache: PatternProjectionCache
    ) -> None:
        """is_stale() returns True when the elapsed time exceeds the stale threshold.

        We mock time.monotonic() to simulate time passage without actually waiting.
        """
        cache.update(
            "general", [{"id": "p1", "pattern_signature": "x", "confidence": 0.9}]
        )
        # Simulate 601 seconds elapsed (beyond the default 600s threshold)
        fake_now = time.monotonic() + 601

        with patch("plugins.onex.hooks.lib.pattern_cache.time") as mock_time:
            mock_time.monotonic.return_value = fake_now
            # _get_stale_threshold uses os.environ, not time — no need to mock it
            # Force the cache's _last_updated_at to be in the past
            with cache._lock:
                cache._last_updated_at = fake_now - 601  # type: ignore[assignment]
            assert cache.is_stale() is True

    def test_cache_staleness_configurable_via_env(
        self, cache: PatternProjectionCache
    ) -> None:
        """Stale threshold is read from PATTERN_CACHE_STALE_SECONDS env var."""
        import os

        cache.update(
            "general", [{"id": "p1", "pattern_signature": "x", "confidence": 0.9}]
        )

        # Set a very short threshold (1 second)
        original = os.environ.get("PATTERN_CACHE_STALE_SECONDS")
        try:
            os.environ["PATTERN_CACHE_STALE_SECONDS"] = "1"
            # Simulate 2 seconds elapsed
            with cache._lock:
                cache._last_updated_at = time.monotonic() - 2  # type: ignore[assignment]
            assert cache.is_stale() is True
        finally:
            if original is None:
                os.environ.pop("PATTERN_CACHE_STALE_SECONDS", None)
            else:
                os.environ["PATTERN_CACHE_STALE_SECONDS"] = original


# =============================================================================
# Clear tests
# =============================================================================


class TestPatternCacheClear:
    """Tests for cache clear operation."""

    def test_clear_resets_to_cold_state(self, cache: PatternProjectionCache) -> None:
        """clear() resets is_warm() to False and empties data."""
        cache.update(
            "general", [{"id": "p1", "pattern_signature": "x", "confidence": 0.9}]
        )
        cache.clear()
        assert cache.is_warm() is False
        assert cache.get("general") == []
