# ManifestInjector Context Manager Usage

## Overview

The `ManifestInjector` class now supports async context manager protocol (`__aenter__` / `__aexit__`) for proper resource cleanup. This ensures:

- Cache metrics are logged before cleanup
- Cache entries are invalidated on exit
- Memory is properly freed
- Resources are cleaned up even if errors occur

## Usage Examples

### Recommended: Async Context Manager

```python
from agents.lib.manifest_injector import ManifestInjector
from uuid import uuid4

async def generate_manifest():
    correlation_id = str(uuid4())

    # Recommended: Use async context manager
    async with ManifestInjector(
        enable_intelligence=True,
        enable_cache=True,
        cache_ttl_seconds=300,
    ) as injector:
        # Generate manifest
        manifest = await injector.generate_dynamic_manifest_async(correlation_id)

        # Format for prompt
        formatted = injector.format_for_prompt()

        # Resources automatically cleaned up on exit
        return formatted
```

### Convenience Function

```python
from agents.lib.manifest_injector import inject_manifest_async
from uuid import uuid4

async def quick_manifest():
    # Convenience function (includes context manager internally)
    formatted = await inject_manifest_async(
        correlation_id=str(uuid4()),
        sections=["patterns", "infrastructure", "models"]
    )
    return formatted
```

### Backward Compatible: Sync Wrapper

```python
from agents.lib.manifest_injector import inject_manifest

def legacy_usage():
    # Synchronous wrapper for backward compatibility
    # Note: Prefer async version for better resource management
    formatted = inject_manifest()
    return formatted
```

## Resource Cleanup

The context manager performs the following cleanup on exit:

1. **Log cache metrics** - Records hit rates, query times, and performance stats
2. **Invalidate cache** - Clears all cached manifest data
3. **Clear internal state** - Resets manifest data, formatted cache, and timestamps

### Example Cleanup Flow

```python
async with ManifestInjector() as injector:
    # ... use injector ...
    pass  # On exit:
          # 1. Cache metrics logged
          # 2. Cache invalidated (all entries cleared)
          # 3. Internal state cleared
          # 4. Resources freed
```

## Error Handling

The context manager properly handles errors and still performs cleanup:

```python
try:
    async with ManifestInjector() as injector:
        manifest = await injector.generate_dynamic_manifest_async(correlation_id)
        # Simulate error
        raise ValueError("Processing failed")
except ValueError as e:
    # Context manager cleanup still executed
    # Cache cleared, metrics logged, resources freed
    print(f"Error handled: {e}")
```

## Benefits Over Manual Management

### Before (Manual Cleanup):

```python
# ❌ Manual management - error prone
injector = ManifestInjector()
try:
    manifest = await injector.generate_dynamic_manifest_async(correlation_id)
    formatted = injector.format_for_prompt()
finally:
    # Easy to forget cleanup
    injector.log_cache_metrics()
    injector.invalidate_cache()
```

### After (Context Manager):

```python
# ✅ Automatic cleanup - guaranteed
async with ManifestInjector() as injector:
    manifest = await injector.generate_dynamic_manifest_async(correlation_id)
    formatted = injector.format_for_prompt()
    # Cleanup automatically handled
```

## Performance Considerations

- Cache metrics are logged at DEBUG level during normal operation
- Cache invalidation happens quickly (O(1) dictionary clear)
- No performance overhead compared to manual cleanup
- Guarantees cleanup even on exceptions

## Integration with Existing Code

The context manager is fully backward compatible:

1. **Async code** - Use `async with ManifestInjector() as injector:`
2. **Sync code** - Use `inject_manifest()` convenience function
3. **Legacy code** - Existing usage continues to work unchanged

## Testing

To verify context manager functionality:

```python
import asyncio
from agents.lib.manifest_injector import ManifestInjector
from uuid import uuid4

async def test_context_manager():
    async with ManifestInjector(enable_intelligence=False) as injector:
        manifest = await injector.generate_dynamic_manifest_async(str(uuid4()))
        assert manifest is not None
        print("✓ Context manager working correctly")
    # Resources automatically cleaned up here
    print("✓ Cleanup completed")

asyncio.run(test_context_manager())
```

## Migration Guide

If you have existing code using `ManifestInjector` without context manager:

### Before:

```python
injector = ManifestInjector()
manifest = await injector.generate_dynamic_manifest_async(correlation_id)
formatted = injector.format_for_prompt()
```

### After:

```python
async with ManifestInjector() as injector:
    manifest = await injector.generate_dynamic_manifest_async(correlation_id)
    formatted = injector.format_for_prompt()
```

## Summary

- **Use `async with ManifestInjector() as injector:`** for proper resource management
- **Use `inject_manifest_async()`** for simple one-off manifest generation
- **Context manager guarantees cleanup** even on errors
- **Fully backward compatible** with existing code
- **No performance penalty** - same efficiency as manual cleanup

---

**Created:** 2025-10-28
**Related:** Work Stream 9 - Add context managers to manifest_injector.py
