# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for cache-first context injection (OMN-2425).

Verifies that HandlerContextInjection._load_patterns_from_database:
1. Uses the projection cache when it is warm and not stale (no API call)
2. Falls back to the HTTP API when the cache is cold
3. Falls back to the HTTP API when the cache is stale
4. Logs the correct cache_miss reason

Part of OMN-2425: consume pattern projection and cache for context injection.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from omniclaude.hooks.context_config import ContextInjectionConfig
from omniclaude.hooks.handler_context_injection import (
    HandlerContextInjection,
    ModelLoadPatternsResult,
    ModelPatternRecord,
)
from plugins.onex.hooks.lib.pattern_cache import PatternProjectionCache

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Helpers
# =============================================================================


def _make_handler(
    *,
    api_enabled: bool = True,
    min_confidence: float = 0.0,
) -> HandlerContextInjection:
    """Create a HandlerContextInjection with known config."""
    config = ContextInjectionConfig(
        enabled=True,
        db_enabled=True,
        api_enabled=api_enabled,
        api_url="http://localhost:8053",
        min_confidence=min_confidence,
    )
    return HandlerContextInjection(config=config)


def _raw_pattern(
    pattern_id: str = "p1",
    signature: str = "test pattern",
    confidence: float = 0.85,
    domain_id: str = "general",
) -> dict[str, Any]:
    """Build a minimal projection event pattern dict."""
    return {
        "id": pattern_id,
        "pattern_signature": signature,
        "confidence": confidence,
        "domain_id": domain_id,
        "quality_score": 0.9,
        "status": "validated",
    }


def _warm_cache(
    domain: str = "general",
    patterns: list[dict[str, Any]] | None = None,
) -> PatternProjectionCache:
    """Build a warm, non-stale cache populated with patterns."""
    cache = PatternProjectionCache()
    cache.update(domain, patterns or [_raw_pattern()])
    return cache


# =============================================================================
# Cache-hit tests
# =============================================================================


class TestContextInjectionCacheHit:
    """Handler uses the projection cache when it is warm and not stale."""

    @pytest.mark.asyncio
    async def test_uses_cache_when_warm_and_not_stale(self) -> None:
        """No API call is made when the cache is warm and fresh."""
        handler = _make_handler()
        cache = _warm_cache()

        with (
            patch(
                "plugins.onex.hooks.lib.pattern_cache.get_pattern_cache",
                return_value=cache,
            ),
            patch(
                "plugins.onex.hooks.lib.pattern_cache.start_projection_consumer_if_configured"
            ),
            patch.object(handler, "_load_patterns_from_api") as mock_api,
        ):
            result = await handler._load_patterns_from_database(domain="general")

        # API must not be called
        mock_api.assert_not_called()

        # Result contains the pattern from the cache
        assert len(result.patterns) == 1
        assert result.patterns[0].pattern_id == "p1"

    @pytest.mark.asyncio
    async def test_cache_hit_maps_fields_correctly(self) -> None:
        """Pattern fields are mapped from raw projection dict to ModelPatternRecord."""
        handler = _make_handler()
        raw = _raw_pattern(
            pattern_id="pat-abc",
            signature="no bare except",
            confidence=0.95,
            domain_id="python",
        )
        cache = _warm_cache(domain="python", patterns=[raw])

        with (
            patch(
                "plugins.onex.hooks.lib.pattern_cache.get_pattern_cache",
                return_value=cache,
            ),
            patch(
                "plugins.onex.hooks.lib.pattern_cache.start_projection_consumer_if_configured"
            ),
        ):
            result = await handler._load_patterns_from_database(domain="python")

        assert len(result.patterns) == 1
        pat = result.patterns[0]
        assert pat.pattern_id == "pat-abc"
        assert pat.title == "no bare except"
        assert pat.confidence == 0.95
        assert pat.domain == "python"
        assert pat.lifecycle_state == "validated"
        assert pat.success_rate == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_cache_hit_logs_cache_hit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Cache hit is logged with domain and count."""
        handler = _make_handler()
        cache = _warm_cache()

        with (
            patch(
                "plugins.onex.hooks.lib.pattern_cache.get_pattern_cache",
                return_value=cache,
            ),
            patch(
                "plugins.onex.hooks.lib.pattern_cache.start_projection_consumer_if_configured"
            ),
            caplog.at_level(logging.INFO),
        ):
            await handler._load_patterns_from_database(domain="general")

        assert "pattern_source=cache_hit" in caplog.text


# =============================================================================
# Cache-miss (cold) tests
# =============================================================================


class TestContextInjectionCacheMissCold:
    """Handler falls back to API when cache is cold."""

    @pytest.mark.asyncio
    async def test_falls_back_to_api_when_cache_is_cold(self) -> None:
        """When the cache is cold, the API is called."""
        handler = _make_handler()
        cold_cache = PatternProjectionCache()  # never updated → cold

        api_result = ModelLoadPatternsResult(
            patterns=[
                ModelPatternRecord(
                    pattern_id="api-p1",
                    domain="general",
                    title="from api",
                    description="from api",
                    confidence=0.8,
                    usage_count=0,
                    success_rate=0.0,
                )
            ],
            source_files=[],
        )

        with (
            patch(
                "plugins.onex.hooks.lib.pattern_cache.get_pattern_cache",
                return_value=cold_cache,
            ),
            patch(
                "plugins.onex.hooks.lib.pattern_cache.start_projection_consumer_if_configured"
            ),
            patch.object(
                handler,
                "_load_patterns_from_api",
                new=AsyncMock(return_value=api_result),
            ) as mock_api,
        ):
            result = await handler._load_patterns_from_database(domain="general")

        mock_api.assert_called_once()
        assert len(result.patterns) == 1
        assert result.patterns[0].pattern_id == "api-p1"

    @pytest.mark.asyncio
    async def test_cache_miss_cold_logs_reason(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Cache miss (cold) is logged with reason=cold."""
        handler = _make_handler()
        cold_cache = PatternProjectionCache()

        with (
            patch(
                "plugins.onex.hooks.lib.pattern_cache.get_pattern_cache",
                return_value=cold_cache,
            ),
            patch(
                "plugins.onex.hooks.lib.pattern_cache.start_projection_consumer_if_configured"
            ),
            patch.object(
                handler,
                "_load_patterns_from_api",
                new=AsyncMock(
                    return_value=ModelLoadPatternsResult(patterns=[], source_files=[])
                ),
            ),
            caplog.at_level(logging.INFO),
        ):
            await handler._load_patterns_from_database(domain="general")

        assert "cache_miss" in caplog.text
        assert "cold" in caplog.text


# =============================================================================
# Cache-miss (stale) tests
# =============================================================================


class TestContextInjectionCacheMissStale:
    """Handler falls back to API when cache is stale."""

    @pytest.mark.asyncio
    async def test_falls_back_to_api_when_cache_is_stale(self) -> None:
        """When the cache is stale, the API is called."""
        handler = _make_handler()
        # Populate the cache, then mark it stale by back-dating _last_updated_at
        stale_cache = _warm_cache()
        import time

        with stale_cache._lock:
            stale_cache._last_updated_at = time.monotonic() - 999  # type: ignore[assignment]

        api_result = ModelLoadPatternsResult(
            patterns=[
                ModelPatternRecord(
                    pattern_id="fresh-api",
                    domain="general",
                    title="fresh from api",
                    description="fresh from api",
                    confidence=0.9,
                    usage_count=0,
                    success_rate=0.0,
                )
            ],
            source_files=[],
        )

        with (
            patch(
                "plugins.onex.hooks.lib.pattern_cache.get_pattern_cache",
                return_value=stale_cache,
            ),
            patch(
                "plugins.onex.hooks.lib.pattern_cache.start_projection_consumer_if_configured"
            ),
            patch.object(
                handler,
                "_load_patterns_from_api",
                new=AsyncMock(return_value=api_result),
            ) as mock_api,
        ):
            result = await handler._load_patterns_from_database(domain="general")

        mock_api.assert_called_once()
        assert result.patterns[0].pattern_id == "fresh-api"

    @pytest.mark.asyncio
    async def test_cache_miss_stale_logs_reason(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Cache miss (stale) is logged with reason=stale."""
        handler = _make_handler()
        stale_cache = _warm_cache()
        import time

        with stale_cache._lock:
            stale_cache._last_updated_at = time.monotonic() - 999  # type: ignore[assignment]

        with (
            patch(
                "plugins.onex.hooks.lib.pattern_cache.get_pattern_cache",
                return_value=stale_cache,
            ),
            patch(
                "plugins.onex.hooks.lib.pattern_cache.start_projection_consumer_if_configured"
            ),
            patch.object(
                handler,
                "_load_patterns_from_api",
                new=AsyncMock(
                    return_value=ModelLoadPatternsResult(patterns=[], source_files=[])
                ),
            ),
            caplog.at_level(logging.INFO),
        ):
            await handler._load_patterns_from_database(domain="general")

        assert "cache_miss" in caplog.text
        assert "stale" in caplog.text


# =============================================================================
# Import failure graceful degradation test
# =============================================================================


class TestContextInjectionCacheImportFailure:
    """Handler falls back to API if pattern_cache module import fails."""

    @pytest.mark.asyncio
    async def test_falls_back_to_api_if_pattern_cache_import_fails(self) -> None:
        """If pattern_cache import raises, handler continues with HTTP API fallback."""
        handler = _make_handler()
        api_result = ModelLoadPatternsResult(
            patterns=[
                ModelPatternRecord(
                    pattern_id="api-fallback",
                    domain="general",
                    title="from api",
                    description="from api",
                    confidence=0.8,
                    usage_count=0,
                    success_rate=0.0,
                )
            ],
            source_files=[],
        )

        # Simulate ImportError from the pattern_cache import inside the handler
        import builtins

        original_import = builtins.__import__

        def _failing_import(name: str, *args: object, **kwargs: object) -> object:
            if "pattern_cache" in name:
                raise ImportError("simulated import failure")
            return original_import(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=_failing_import),
            patch.object(
                handler,
                "_load_patterns_from_api",
                new=AsyncMock(return_value=api_result),
            ) as mock_api,
        ):
            result = await handler._load_patterns_from_database(domain="general")

        mock_api.assert_called_once()
        assert result.patterns[0].pattern_id == "api-fallback"
