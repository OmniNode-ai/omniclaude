#!/usr/bin/env python3
"""Mock MixinCaching for testing"""


class MixinCaching:
    """Mock caching mixin"""

    async def cache_get(self, key: str):
        """Get value from cache"""
        return None

    async def cache_set(self, key: str, value: any, ttl: int = 3600):
        """Set value in cache"""
        pass

    async def cache_invalidate(self, key: str):
        """Invalidate cache entry"""
        pass
