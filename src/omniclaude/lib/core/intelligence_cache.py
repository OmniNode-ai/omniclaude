"""
Intelligence Cache - Valkey-backed caching for pattern queries

Caches:
- Pattern discovery results (TTL: 5 min)
- Infrastructure topology (TTL: 1 hour)
- Database schemas (TTL: 30 min)
- Model information (TTL: 1 hour)

Performance targets:
- Cache hit rate: >60%
- Cache lookup: <10ms p95
- Reduces Archon load by 60%+

Architecture:
- Uses Valkey (Redis-compatible) for distributed caching
- JSON serialization for complex data structures
- MD5 hash-based cache keys for deterministic lookups
- Configurable TTLs per operation type
- Graceful degradation on cache failures

Integration:
- Used by ManifestInjector for pattern/infrastructure/model queries
- Transparent to callers (cache hit/miss handled internally)
- Non-blocking (failures don't break intelligence queries)

Usage:
    # Initialize cache
    cache = IntelligenceCache()
    await cache.connect()

    # Query with cache
    params = {"collection": "code_patterns", "limit": 50}
    cached = await cache.get("pattern_discovery", params)
    if cached:
        return cached  # Cache hit

    # Cache miss - query backend
    result = await query_backend(params)
    await cache.set("pattern_discovery", params, result)

    # Close connection
    await cache.close()

Created: 2025-10-30
"""

import hashlib
import json
import logging
import os
from typing import Any

# Import Pydantic Settings for type-safe configuration
settings: Any | None = None
try:
    from config import settings as _settings

    settings = _settings
except ImportError:
    pass

logger = logging.getLogger(__name__)


class IntelligenceCache:
    """Valkey-backed cache for intelligence queries"""

    def __init__(
        self,
        redis_url: str | None = None,
        enabled: bool = True,
    ):
        """
        Initialize cache client.

        Args:
            redis_url: Valkey connection URL (default: from env)
            enabled: Enable/disable caching (default: True)
        """
        # Use Pydantic Settings if available, otherwise fall back to os.getenv
        if settings is not None:
            cache_enabled_str = str(settings.enable_intelligence_cache).lower()
            self.enabled = enabled and cache_enabled_str == "true"
        else:
            self.enabled = (
                enabled and os.getenv("ENABLE_INTELLIGENCE_CACHE", "true").lower() == "true"
            )

        if not self.enabled:
            logger.info("Intelligence cache disabled via configuration")
            return

        # Default uses Docker hostname (archon-valkey:6379); override with VALKEY_URL in .env for localhost development
        # Password must be set via VALKEY_PASSWORD environment variable (no hardcoded defaults)
        valkey_password = os.getenv("VALKEY_PASSWORD", "")
        if valkey_password:
            default_url = f"redis://:{valkey_password}@archon-valkey:6379/0"
        else:
            default_url = "redis://archon-valkey:6379/0"
        if settings is not None:
            self.redis_url = redis_url or settings.valkey_url or default_url
        else:
            self.redis_url = redis_url or os.getenv("VALKEY_URL", default_url)
        self._client: Any | None = None

        # Default TTLs by operation type (in seconds) - declare once
        self._default_ttls: dict[str, int]
        if settings is not None:
            self._default_ttls = {
                "pattern_discovery": settings.cache_ttl_patterns,
                "infrastructure_query": settings.cache_ttl_infrastructure,
                "schema_query": settings.cache_ttl_schemas,
                "model_query": settings.cache_ttl_infrastructure,
                "debug_intelligence_query": settings.cache_ttl_patterns,
                "filesystem_query": settings.cache_ttl_patterns,
            }
        else:
            self._default_ttls = {
                "pattern_discovery": int(os.getenv("CACHE_TTL_PATTERNS", "300")),  # 5 min
                "infrastructure_query": int(
                    os.getenv("CACHE_TTL_INFRASTRUCTURE", "3600")
                ),  # 1 hour
                "schema_query": int(os.getenv("CACHE_TTL_SCHEMAS", "1800")),  # 30 min
                "model_query": int(os.getenv("CACHE_TTL_INFRASTRUCTURE", "3600")),  # 1 hour
                "debug_intelligence_query": int(os.getenv("CACHE_TTL_PATTERNS", "300")),  # 5 min
                "filesystem_query": int(os.getenv("CACHE_TTL_PATTERNS", "300")),  # 5 min
            }

        # Redact credentials from URL before logging
        safe_url = self.redis_url
        if "@" in safe_url:
            # URL format: redis://[:password]@host:port/db - redact password portion
            prefix_end = safe_url.find("://") + 3
            at_pos = safe_url.find("@")
            safe_url = safe_url[:prefix_end] + "***REDACTED***" + safe_url[at_pos:]
        logger.info(f"Intelligence cache initialized: enabled={self.enabled}, url={safe_url}")

    async def connect(self):
        """Establish connection to Valkey"""
        if not self.enabled:
            return

        try:
            # Import redis.asyncio here to avoid import errors if not installed
            from redis.asyncio import Redis

            self._client = await Redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )

            # Test connection
            await self._client.ping()
            logger.info("Successfully connected to Valkey cache")

        except ImportError as e:
            logger.warning(
                f"redis.asyncio not available - caching disabled: {e}. "
                "Install with: pip install redis[asyncio]"
            )
            self.enabled = False
        except Exception as e:
            logger.warning(f"Failed to connect to Valkey cache - caching disabled: {e}")
            self.enabled = False

    async def close(self):
        """Close connection"""
        if self._client:
            try:
                await self._client.aclose()
                logger.debug("Valkey cache connection closed")
            except Exception as e:
                logger.warning(f"Error closing Valkey connection: {e}")

    def _generate_cache_key(self, operation_type: str, params: dict[str, Any]) -> str:
        """Generate deterministic cache key from query parameters"""
        # Sort params for consistent hashing
        sorted_params = json.dumps(params, sort_keys=True)
        # MD5 used for cache key generation (non-cryptographic), not security
        params_hash = hashlib.md5(  # noqa: S324 # nosec B324
            sorted_params.encode()
        ).hexdigest()[:12]

        return f"intelligence:{operation_type}:{params_hash}"

    async def get(self, operation_type: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Get cached result if available"""
        if not self.enabled or not self._client:
            return None

        cache_key = self._generate_cache_key(operation_type, params)

        try:
            cached_json = await self._client.get(cache_key)
            if cached_json:
                logger.debug(f"Cache HIT: {operation_type} (key: {cache_key})")
                result: dict[str, Any] = json.loads(cached_json)
                return result
            else:
                logger.debug(f"Cache MISS: {operation_type} (key: {cache_key})")
                return None
        except Exception as e:
            # Log but don't fail on cache errors
            logger.warning(f"Cache get failed for {operation_type}: {e}")
            return None

    async def set(
        self,
        operation_type: str,
        params: dict[str, Any],
        result: dict[str, Any],
        ttl_seconds: int | None = None,
    ):
        """Cache query result with TTL"""
        if not self.enabled or not self._client:
            return

        cache_key = self._generate_cache_key(operation_type, params)

        # Default TTLs by operation type
        if ttl_seconds is None:
            ttl_seconds = self._default_ttls.get(operation_type, 300)

        try:
            result_json = json.dumps(result)
            await self._client.setex(cache_key, ttl_seconds, result_json)
            logger.debug(f"Cache SET: {operation_type} (key: {cache_key}, ttl: {ttl_seconds}s)")
        except Exception as e:
            # Log but don't fail on cache errors
            logger.warning(f"Cache set failed for {operation_type}: {e}")

    async def invalidate_pattern(self, pattern: str):
        """Invalidate cache entries matching pattern"""
        if not self.enabled or not self._client:
            return

        try:
            keys = await self._client.keys(f"intelligence:*{pattern}*")
            if keys:
                await self._client.delete(*keys)
                logger.info(f"Cache invalidated: {len(keys)} keys matching '{pattern}'")
        except Exception as e:
            logger.warning(f"Cache invalidation failed: {e}")

    async def invalidate_all(self):
        """Invalidate all intelligence cache entries"""
        if not self.enabled or not self._client:
            return

        try:
            keys = await self._client.keys("intelligence:*")
            if keys:
                await self._client.delete(*keys)
                logger.info(f"Cache cleared: {len(keys)} keys deleted")
        except Exception as e:
            logger.warning(f"Cache clear failed: {e}")

    async def get_stats(self) -> dict[str, Any]:
        """Get cache statistics"""
        if not self.enabled or not self._client:
            return {"enabled": False}

        try:
            info = await self._client.info("stats")
            total_hits = info.get("keyspace_hits", 0)
            total_misses = info.get("keyspace_misses", 0)
            total_requests = total_hits + total_misses

            hit_rate = total_hits / total_requests if total_requests > 0 else 0.0

            return {
                "enabled": True,
                "keyspace_hits": total_hits,
                "keyspace_misses": total_misses,
                "hit_rate": round(hit_rate, 3),
                "hit_rate_percent": round(hit_rate * 100, 1),
            }
        except Exception as e:
            logger.warning(f"Failed to get cache stats: {e}")
            return {"enabled": True, "error": "Stats unavailable"}


__all__ = ["IntelligenceCache"]
