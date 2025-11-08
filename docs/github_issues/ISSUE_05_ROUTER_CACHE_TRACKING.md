# Implement Cache Hit Tracking in Agent Router

## Labels
`priority:medium`, `type:feature`, `component:router`, `observability`

## Description

Router response metadata hardcodes `cache_hit: False` instead of tracking actual cache statistics, preventing cache effectiveness measurement.

## Current Behavior

`agent_router_event_service.py` always reports cache miss:

```python
# agents/services/agent_router_event_service.py:866
"routing_metadata": {
    "routing_time_ms": routing_time_ms,
    "cache_hit": False,  # TODO: Get from router cache stats
}
```

## Impact

- ❌ **No Cache Metrics**: Cannot measure cache effectiveness
- ❌ **Missing Optimization Data**: No visibility into performance gains
- ❌ **Planning Blocked**: Universal Router planning needs cache hit rate data
- ⚠️ **Misleading Analytics**: Dashboards show 0% cache hit rate

## Expected Behavior

Should:
1. Track cache hits/misses in EnhancedAgentRouter
2. Return cache statistics from route() method
3. Include cache_hit boolean in response metadata
4. Expose cache metrics via Prometheus

## Implementation Plan

### 1. Add Cache Statistics to Router

```python
# agents/services/router.py (or wherever EnhancedAgentRouter is defined)
from dataclasses import dataclass
from typing import Optional

@dataclass
class RoutingResult:
    """Router result with cache metadata."""
    agent_name: str
    confidence: float
    cache_hit: bool
    cache_key: Optional[str] = None
    routing_time_ms: float = 0.0

class EnhancedAgentRouter:
    def __init__(self, ...):
        # ... existing init ...
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache: Dict[str, RoutingResult] = {}  # Simple in-memory cache
        self._cache_ttl_seconds = 300  # 5 minutes

    def _get_cache_key(self, user_request: str) -> str:
        """Generate cache key for request."""
        # Normalize request for cache key
        normalized = user_request.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()

    async def route(
        self,
        user_request: str,
        use_cache: bool = True,
    ) -> RoutingResult:
        """Route request to agent with cache support."""
        start_time = time.perf_counter()

        # Check cache first
        cache_key = self._get_cache_key(user_request)
        if use_cache and cache_key in self._cache:
            cached_result = self._cache[cache_key]

            # Check if cache entry is still valid
            if self._is_cache_valid(cache_key):
                self._cache_hits += 1
                routing_time_ms = (time.perf_counter() - start_time) * 1000

                return RoutingResult(
                    agent_name=cached_result.agent_name,
                    confidence=cached_result.confidence,
                    cache_hit=True,
                    cache_key=cache_key,
                    routing_time_ms=routing_time_ms,
                )

        # Cache miss - perform routing
        self._cache_misses += 1
        recommendations = await self._perform_routing(user_request)
        primary = recommendations[0]

        routing_time_ms = (time.perf_counter() - start_time) * 1000

        result = RoutingResult(
            agent_name=primary.agent_name,
            confidence=primary.confidence.total,
            cache_hit=False,
            cache_key=cache_key,
            routing_time_ms=routing_time_ms,
        )

        # Store in cache
        if use_cache:
            self._cache[cache_key] = result
            self._set_cache_timestamp(cache_key)

        return result

    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_requests = self._cache_hits + self._cache_misses
        hit_rate = self._cache_hits / total_requests if total_requests > 0 else 0.0

        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "total_requests": total_requests,
            "hit_rate": hit_rate,
            "cache_size": len(self._cache),
        }
```

### 2. Update Event Service to Use Cache Stats

```python
# agents/services/agent_router_event_service.py
async def _handle_routing_request(self, message: ConsumerRecord):
    # ... existing code ...

    # Route request (now returns RoutingResult with cache info)
    result = await self._router.route(
        user_request=user_request,
        use_cache=True,
    )

    routing_time_ms = result.routing_time_ms

    # Build response
    response_envelope = {
        "correlation_id": correlation_id,
        "payload": {
            "recommendations": [
                {
                    "agent_name": result.agent_name,
                    "confidence": result.confidence,
                    "reason": "...",
                }
            ],
            "routing_metadata": {
                "routing_time_ms": routing_time_ms,
                "cache_hit": result.cache_hit,  # ✅ Now accurate
                "cache_key": result.cache_key,
            },
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # ... publish response ...
```

### 3. Add Prometheus Metrics

```python
# agents/services/agent_router_event_service.py
from prometheus_client import Counter, Histogram, Gauge

# Metrics
ROUTING_CACHE_HITS = Counter(
    'router_cache_hits_total',
    'Total number of router cache hits'
)

ROUTING_CACHE_MISSES = Counter(
    'router_cache_misses_total',
    'Total number of router cache misses'
)

ROUTING_CACHE_HIT_RATE = Gauge(
    'router_cache_hit_rate',
    'Router cache hit rate (0.0 to 1.0)'
)

ROUTING_CACHE_SIZE = Gauge(
    'router_cache_size',
    'Number of entries in router cache'
)

class AgentRouterEventService:
    async def _handle_routing_request(self, message: ConsumerRecord):
        # ... existing code ...

        result = await self._router.route(user_request, use_cache=True)

        # Update metrics
        if result.cache_hit:
            ROUTING_CACHE_HITS.inc()
        else:
            ROUTING_CACHE_MISSES.inc()

        # Update cache statistics
        stats = self._router.get_cache_statistics()
        ROUTING_CACHE_HIT_RATE.set(stats["hit_rate"])
        ROUTING_CACHE_SIZE.set(stats["cache_size"])

        # ... rest of code ...
```

### 4. Add Cache Statistics Endpoint

```python
# agents/services/agent_router_event_service.py (if HTTP server exists)
# OR create new endpoints.py file

from fastapi import APIRouter

router = APIRouter()

@router.get("/router/cache/stats")
async def get_cache_stats():
    """Get router cache statistics."""
    # Access router instance (inject as dependency)
    stats = router_instance.get_cache_statistics()
    return {
        "cache_hits": stats["cache_hits"],
        "cache_misses": stats["cache_misses"],
        "total_requests": stats["total_requests"],
        "hit_rate": f"{stats['hit_rate']:.2%}",
        "cache_size": stats["cache_size"],
    }

@router.delete("/router/cache")
async def clear_cache():
    """Clear router cache."""
    router_instance.clear_cache()
    return {"message": "Cache cleared"}
```

### 5. Add Configuration

```python
# .env
ROUTER_CACHE_ENABLED=true
ROUTER_CACHE_TTL_SECONDS=300  # 5 minutes
ROUTER_CACHE_MAX_SIZE=1000  # Max cache entries
```

## Testing

```python
# tests/services/test_agent_router.py
@pytest.mark.asyncio
async def test_cache_hit_on_duplicate_request(router):
    """Test cache hit on duplicate request."""
    request = "Help me implement ONEX patterns"

    # First request - cache miss
    result1 = await router.route(request, use_cache=True)
    assert result1.cache_hit is False

    # Second request - cache hit
    result2 = await router.route(request, use_cache=True)
    assert result2.cache_hit is True
    assert result2.agent_name == result1.agent_name

@pytest.mark.asyncio
async def test_cache_statistics():
    """Test cache statistics tracking."""
    router = EnhancedAgentRouter()

    # Make requests
    await router.route("request 1", use_cache=True)
    await router.route("request 1", use_cache=True)  # Cache hit
    await router.route("request 2", use_cache=True)

    stats = router.get_cache_statistics()
    assert stats["cache_hits"] == 1
    assert stats["cache_misses"] == 2
    assert stats["hit_rate"] == 1/3
    assert stats["cache_size"] == 2
```

## Success Criteria

- [ ] Router tracks cache hits/misses
- [ ] RoutingResult includes cache_hit boolean
- [ ] Cache statistics exposed via get_cache_statistics()
- [ ] Prometheus metrics configured
- [ ] Cache TTL configurable
- [ ] Cache size limits configurable
- [ ] HTTP endpoint for cache stats (if applicable)
- [ ] Tests verify cache behavior
- [ ] Documentation updated

## Related Issues

- Part of PR #22 review (Issue #21)
- Supports Universal Router planning (cache hit rate target: 60-70%)
- Improves observability

## Files to Modify

- Router implementation file (enhance cache tracking)
- `agents/services/agent_router_event_service.py` - Use cache stats
- `.env.example` - Add cache configuration
- `config/settings.py` - Add cache settings
- `tests/services/test_agent_router.py` - Add cache tests
- `docs/architecture/ROUTER_CACHING.md` - Document caching

## Estimated Effort

- Router changes: 2-3 hours
- Prometheus metrics: 1-2 hours
- HTTP endpoints: 1-2 hours
- Testing: 2-3 hours
- Documentation: 1 hour
- **Total**: 1-2 days

## Priority Justification

**MEDIUM** - Cache metrics are important for performance monitoring and Universal Router planning, but router is currently functional. Can be added incrementally without breaking existing functionality.
