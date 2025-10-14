# Resilience Layer Integration Guide

Complete guide for integrating the bulletproof resilience layer into Claude Code hooks for pattern tracking.

## 🎯 Overview

The resilience layer ensures pattern tracking **NEVER** disrupts Claude Code workflows through:

- **Fire-and-forget execution**: Non-blocking pattern tracking
- **Circuit breaker**: Prevents repeated failures to unavailable APIs
- **Local caching**: Stores events offline, syncs when API recovers
- **Health checking**: Smart routing based on API availability
- **Graceful degradation**: All errors are caught and logged, never propagated

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Claude Code Hook                            │
│  (pre-tool-use-quality.sh, post-tool-use-quality.sh, etc.)     │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PatternTracker                               │
│  • track_pattern_creation()                                     │
│  • track_pattern_modification()                                 │
│  • track_pattern_application()                                  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 ResilientAPIClient                              │
│  ┌─────────────────┬────────────────┬────────────────────────┐ │
│  │ HealthChecker   │ CircuitBreaker │ PatternCache           │ │
│  │ • check_health()│ • call()       │ • cache_pattern_event()│ │
│  │ • auto-recovery │ • state mgmt   │ • sync_cached_events() │ │
│  └─────────────────┴────────────────┴────────────────────────┘ │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              Phase 4 Pattern Traceability API                   │
│  http://localhost:8053/api/pattern-traceability                 │
│  • POST /lineage/track                                          │
│  • GET /lineage/{pattern_id}                                    │
│  • GET /health                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 📦 Components

### 1. ResilientExecutor
Fire-and-forget async execution that never blocks.

```python
from lib.resilience import ResilientExecutor

executor = ResilientExecutor()

# Fire and forget - returns immediately
executor.fire_and_forget(
    track_pattern_creation(code, context)
)

# Claude workflow continues immediately
# Tracking happens in background
```

### 2. CircuitBreaker
Prevents repeated failures to unavailable services.

```python
from lib.resilience import CircuitBreaker

breaker = CircuitBreaker(failure_threshold=3, timeout=60)

# Call through circuit breaker
result = await breaker.call(
    lambda: api_client.track_lineage(...)
)

if result is None:
    # Circuit is open, API is down
    await cache.cache_pattern_event(event)
```

**States:**
- **CLOSED**: Normal operation, requests pass through
- **OPEN**: Too many failures (≥3), requests blocked for 60s
- **HALF_OPEN**: Testing recovery, limited requests allowed

### 3. PatternCache
Local caching for offline scenarios.

```python
from lib.resilience import PatternCache

cache = PatternCache()

# Cache event when API is down
event_id = await cache.cache_pattern_event({
    "event_type": "pattern_created",
    "pattern_id": "auth-001",
    "pattern_data": {...}
})

# Sync when API recovers
sync_stats = await cache.sync_cached_events(api_client)
print(f"Synced {sync_stats['synced']} events")
```

**Features:**
- Stores events at `~/.claude/hooks/.cache/patterns/`
- Auto-sync when API becomes available
- Retry logic with exponential backoff
- Automatic cleanup of old events (7 days default)

### 4. Phase4HealthChecker
Monitors API health with minimal overhead.

```python
from lib.resilience import Phase4HealthChecker

health_checker = Phase4HealthChecker(
    base_url="http://localhost:8053",
    check_interval=30  # Cache results for 30s
)

# Check health (cached for 30s)
is_healthy = await health_checker.check_health()

if is_healthy:
    # Safe to call API
    result = await api_client.track_lineage(...)
```

**Features:**
- Caches health status for 30s (configurable)
- Auto-recovery detection
- Component-level health tracking
- Minimal overhead (<1ms when cached)

### 5. Graceful Degradation Decorator
Ensures functions never fail the main workflow.

```python
from lib.resilience import graceful_tracking

@graceful_tracking(fallback_return={})
async def track_pattern_creation(code: str, context: Dict) -> Dict:
    # This can fail, but will never raise
    return await api_client.track_lineage(...)

# Usage
result = await track_pattern_creation(code, context)
# Returns {} if tracking fails, actual result if successful
```

## 🔌 Integration with Claude Code Hooks

### Option 1: Pre-Tool-Use Hook Integration

Add pattern tracking to `pre-tool-use-quality.sh`:

```python
#!/usr/bin/env python3
"""
Pre-Tool-Use Quality Hook with Pattern Tracking
"""
import asyncio
from lib.pattern_tracker import PatternTracker

async def main():
    # ... existing quality enforcement code ...

    # Track pattern if this is a Write/Edit operation
    if tool_name in ["Write", "Edit"]:
        tracker = await PatternTracker.get_instance()

        # Fire-and-forget tracking (non-blocking)
        if tool_name == "Write":
            asyncio.create_task(
                tracker.track_pattern_creation(
                    code=content,
                    context={
                        "file_path": file_path,
                        "language": detect_language(file_path),
                        "tool_name": tool_name,
                        "pattern_type": "code"
                    }
                )
            )

    # ... continue with quality enforcement ...

if __name__ == "__main__":
    asyncio.run(main())
```

### Option 2: Post-Tool-Use Hook Integration

Add pattern tracking to `post-tool-use-quality.sh`:

```python
#!/usr/bin/env python3
"""
Post-Tool-Use Hook with Pattern Tracking
"""
import asyncio
from lib.pattern_tracker import (
    PatternTracker,
    track_write_tool_pattern,
    track_edit_tool_pattern
)

async def main():
    # Parse tool use result
    tool_name = get_tool_name()
    file_path = get_file_path()

    # Track pattern (fire-and-forget)
    if tool_name == "Write":
        asyncio.create_task(
            track_write_tool_pattern(
                file_path=file_path,
                content=read_file(file_path),
                language=detect_language(file_path)
            )
        )

    elif tool_name == "Edit":
        asyncio.create_task(
            track_edit_tool_pattern(
                file_path=file_path,
                pattern_id=get_pattern_id(file_path),
                new_content=read_file(file_path),
                language=detect_language(file_path),
                reason="User edit via Claude Code"
            )
        )

if __name__ == "__main__":
    asyncio.run(main())
```

### Option 3: Standalone Background Tracker

Create a background process that monitors file changes:

```python
#!/usr/bin/env python3
"""
Background Pattern Tracker
Monitors Claude Code activity and tracks patterns asynchronously
"""
import asyncio
import os
from pathlib import Path
from lib.pattern_tracker import PatternTracker

async def background_tracker():
    """Run pattern tracker in background"""
    tracker = await PatternTracker.get_instance()

    # Monitor hook execution log
    log_file = Path.home() / ".claude/hooks/logs/hook_executions.log"

    # Tail log and track patterns
    # ... implementation ...

    # Periodically sync offline events
    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        await tracker.sync_offline_events()
        await tracker.cleanup_cache()

if __name__ == "__main__":
    asyncio.run(background_tracker())
```

## 🧪 Testing the Integration

### Test 1: Basic Pattern Tracking

```bash
cd /Users/jonah/.claude/hooks
python3 -c "
import asyncio
from lib.pattern_tracker import PatternTracker

async def test():
    tracker = await PatternTracker.get_instance()

    result = await tracker.track_pattern_creation(
        code='function test() { return true; }',
        context={
            'file_path': 'test.js',
            'language': 'javascript',
            'tool_name': 'Write'
        }
    )

    print(f'Result: {result}')

    # Get stats
    stats = await tracker.get_tracker_stats()
    print(f'Stats: {stats}')

asyncio.run(test())
"
```

### Test 2: Offline Caching

```bash
# Stop intelligence service to simulate API down
docker compose stop archon-intelligence

# Track pattern (should cache locally)
python3 -c "
import asyncio
from lib.pattern_tracker import PatternTracker

async def test():
    tracker = await PatternTracker.get_instance()

    result = await tracker.track_pattern_creation(
        code='function offline() { return true; }',
        context={'file_path': 'offline.js', 'language': 'javascript'}
    )

    print(f'Result: {result}')
    # Should show: cached=True

asyncio.run(test())
"

# Check cache directory
ls -la ~/.claude/hooks/.cache/patterns/

# Restart service
docker compose start archon-intelligence

# Sync cached events
python3 -c "
import asyncio
from lib.pattern_tracker import PatternTracker

async def test():
    tracker = await PatternTracker.get_instance()
    result = await tracker.sync_offline_events()
    print(f'Sync result: {result}')

asyncio.run(test())
"
```

### Test 3: Circuit Breaker Behavior

```bash
python3 -c "
import asyncio
from lib.resilience import CircuitBreaker

async def test():
    breaker = CircuitBreaker(failure_threshold=3, timeout=1)

    async def failing_call():
        raise ConnectionError('API down')

    # Open the circuit with failures
    for i in range(3):
        result = await breaker.call(failing_call)
        print(f'Call {i+1}: {result}')
        print(f'State: {breaker.get_state()}')

    # Circuit should be open
    print(f'Final state: {breaker.get_state()}')

asyncio.run(test())
"
```

### Test 4: Complete Workflow

```bash
# Run comprehensive test suite
cd /Users/jonah/.claude/hooks
python -m pytest lib/test_resilience.py -v

# Run integration test
python -m pytest lib/test_resilience.py::test_complete_resilience_workflow -v
```

## 📊 Monitoring & Observability

### Get Resilience Statistics

```python
from lib.pattern_tracker import PatternTracker

tracker = await PatternTracker.get_instance()
stats = await tracker.get_tracker_stats()

print(f"""
Tracker Stats:
  Enabled: {stats['tracker']['enabled']}
  Cached Patterns: {stats['tracker']['cached_patterns']}

Executor Stats:
  Total Tasks: {stats['resilience']['executor']['total_tasks']}
  Success Rate: {stats['resilience']['executor']['success_rate']:.2%}

Circuit Breaker:
  State: {stats['resilience']['circuit_breaker']['state']}
  Failure Count: {stats['resilience']['circuit_breaker']['failure_count']}

Cache Stats:
  Pending Events: {stats['resilience']['cache']['pending_events']}
  Total Synced: {stats['resilience']['cache']['total_synced']}

Health:
  Is Healthy: {stats['resilience']['health']['is_healthy']}
  Consecutive Successes: {stats['resilience']['health']['consecutive_successes']}
""")
```

### Check Cache Status

```bash
# View cached events
ls -la ~/.claude/hooks/.cache/patterns/

# View cache metadata
cat ~/.claude/hooks/.cache/patterns/cache_metadata.json

# Check cache size
du -sh ~/.claude/hooks/.cache/patterns/
```

### Monitor Health Checks

```bash
# Check Phase 4 API health directly
curl http://localhost:8053/api/pattern-traceability/health

# Monitor health check logs
tail -f ~/.claude/hooks/logs/quality_enforcer.log | grep "PatternTracker.*health"
```

## 🔧 Configuration

### Environment Variables

```bash
# Intelligence service URL (default: http://localhost:8053)
export INTELLIGENCE_SERVICE_URL="http://localhost:8053"

# Enable/disable pattern tracking
export PATTERN_TRACKING_ENABLED="true"

# Cache configuration
export PATTERN_CACHE_DIR="~/.claude/hooks/.cache/patterns"
export PATTERN_CACHE_MAX_AGE_DAYS="7"
export PATTERN_CACHE_MAX_SIZE_MB="50"

# Circuit breaker configuration
export CIRCUIT_BREAKER_FAILURE_THRESHOLD="3"
export CIRCUIT_BREAKER_TIMEOUT="60"

# Health check configuration
export HEALTH_CHECK_INTERVAL="30"
export HEALTH_CHECK_TIMEOUT="1.0"
```

### Programmatic Configuration

```python
from lib.pattern_tracker import PatternTracker
from lib.resilience import ResilientAPIClient

# Custom configuration
tracker = PatternTracker(
    base_url="http://custom-host:8053",
    enable_tracking=True
)

# Configure resilient client
tracker.api_client = ResilientAPIClient(
    base_url="http://custom-host:8053",
    enable_caching=True,
    enable_circuit_breaker=True
)

# Configure circuit breaker
tracker.api_client.circuit_breaker.failure_threshold = 5
tracker.api_client.circuit_breaker.timeout = 120

# Configure cache
tracker.api_client.cache.max_age_days = 14
```

## 🚨 Troubleshooting

### Issue: Pattern tracking is blocking Claude workflows

**Symptom**: Claude Code is slow or hangs during Write/Edit operations

**Solution**:
```python
# Ensure fire-and-forget execution
executor = ResilientExecutor()
executor.fire_and_forget(tracker.track_pattern_creation(...))
# NOT: await tracker.track_pattern_creation(...)
```

### Issue: Events not syncing after API recovery

**Symptom**: Cached events remain in cache directory after API is back online

**Solution**:
```bash
# Manually trigger sync
python3 -c "
import asyncio
from lib.pattern_tracker import PatternTracker

async def sync():
    tracker = await PatternTracker.get_instance()
    result = await tracker.sync_offline_events()
    print(result)

asyncio.run(sync())
"
```

### Issue: Circuit breaker stuck in open state

**Symptom**: Circuit breaker won't close even though API is healthy

**Solution**:
```python
from lib.pattern_tracker import PatternTracker

tracker = await PatternTracker.get_instance()

# Reset circuit breaker
tracker.api_client.circuit_breaker.reset()

# Force health check
is_healthy = await tracker.api_client.health_checker.check_health(force=True)
print(f"API healthy: {is_healthy}")
```

### Issue: Cache directory filling up

**Symptom**: Cache directory growing too large

**Solution**:
```bash
# Manual cleanup
python3 -c "
import asyncio
from lib.pattern_tracker import PatternTracker

async def cleanup():
    tracker = await PatternTracker.get_instance()
    result = await tracker.cleanup_cache()
    print(result)

asyncio.run(cleanup())
"

# Or delete old cache manually
find ~/.claude/hooks/.cache/patterns -name "pending_*.json" -mtime +7 -delete
```

## 📚 Best Practices

### ✅ DO

1. **Always use fire-and-forget for pattern tracking**
   ```python
   executor.fire_and_forget(tracker.track_pattern_creation(...))
   ```

2. **Check health before critical operations**
   ```python
   is_healthy = await health_checker.check_health()
   if is_healthy:
       result = await api_client.track_lineage(...)
   ```

3. **Use graceful degradation decorators**
   ```python
   @graceful_tracking(fallback_return={})
   async def track_pattern(...):
       # Implementation
   ```

4. **Periodically sync offline events**
   ```python
   # Every 5 minutes
   await tracker.sync_offline_events()
   ```

5. **Monitor resilience statistics**
   ```python
   stats = await tracker.get_tracker_stats()
   # Log or send to monitoring system
   ```

### ❌ DON'T

1. **Don't block on pattern tracking**
   ```python
   # BAD - blocks Claude workflow
   result = await tracker.track_pattern_creation(...)

   # GOOD - fire and forget
   executor.fire_and_forget(tracker.track_pattern_creation(...))
   ```

2. **Don't raise exceptions in tracking code**
   ```python
   # BAD - exception propagates
   async def track_pattern(...):
       result = await api_client.track_lineage(...)
       if not result:
           raise ValueError("Tracking failed")

   # GOOD - graceful degradation
   @graceful_tracking(fallback_return={})
   async def track_pattern(...):
       return await api_client.track_lineage(...)
   ```

3. **Don't bypass the circuit breaker**
   ```python
   # BAD - direct API call
   result = await api_client._call_api(...)

   # GOOD - through circuit breaker
   result = await circuit_breaker.call(lambda: api_client._call_api(...))
   ```

4. **Don't ignore cache maintenance**
   ```python
   # GOOD - regular cleanup
   await tracker.cleanup_cache()
   ```

## 🎓 Examples

See complete examples in:
- `lib/resilience.py` - Example usage at bottom of file
- `lib/pattern_tracker.py` - Example usage at bottom of file
- `lib/test_resilience.py` - Comprehensive test suite

## 📞 Support

For issues or questions:
1. Check logs: `~/.claude/hooks/logs/quality_enforcer.log`
2. Review test suite: `lib/test_resilience.py`
3. Check resilience stats: `await tracker.get_tracker_stats()`
4. Consult architecture diagrams above

---

**Built with ❤️ for bulletproof pattern tracking in Claude Code**
