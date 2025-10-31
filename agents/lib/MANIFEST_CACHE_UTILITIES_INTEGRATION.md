# Manifest Cache Utilities Integration Guide

## Overview

The `manifest_cache_utilities.py` module provides a mixin class (`ManifestCacheUtilitiesMixin`) that extracts cache management functionality into a reusable component.

## Problem Solved

Previously, cache utility methods were embedded directly in `ManifestInjector`, making them difficult to:
- Test independently
- Reuse in other components
- Maintain separately

This mixin extracts these utilities while maintaining full compatibility with the existing `ManifestInjector` implementation.

## Module Structure

```python
class ManifestCacheUtilitiesMixin:
    """Mixin providing cache utilities for ManifestInjector."""

    def get_cache_metrics(self, query_type: Optional[str] = None) -> Dict[str, Any]:
        """Get cache performance metrics."""

    def invalidate_cache(self, query_type: Optional[str] = None) -> int:
        """Invalidate cache entries."""

    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache information and statistics."""

    def log_cache_metrics(self) -> None:
        """Log current cache metrics for monitoring."""

    def clear_cache(self, query_type: Optional[str] = None) -> int:
        """Clear cache entries (alias for invalidate_cache)."""
```

## Integration with ManifestInjector

### Current State (Before Integration)

```python
# agents/lib/manifest_injector.py
class ManifestInjector:
    def __init__(self, ...):
        self.enable_cache = enable_cache
        self._cache = cache_instance
        self.logger = logging.getLogger(__name__)

    def get_cache_metrics(self, query_type=None):
        # Implementation here
        pass

    def invalidate_cache(self, query_type=None):
        # Implementation here
        pass

    # ... etc
```

### After Integration (Recommended)

```python
# agents/lib/manifest_injector.py
from agents.lib.manifest_cache_utilities import ManifestCacheUtilitiesMixin

class ManifestInjector(ManifestCacheUtilitiesMixin):
    def __init__(self, ...):
        self.enable_cache = enable_cache
        self._cache = cache_instance
        self.logger = logging.getLogger(__name__)

    # Remove duplicate cache methods - now inherited from mixin
    # def get_cache_metrics(self, query_type=None):  ← DELETE
    # def invalidate_cache(self, query_type=None):   ← DELETE
    # def get_cache_info(self):                      ← DELETE
    # def log_cache_metrics(self):                   ← DELETE
```

## Required Attributes

The mixin expects these attributes to be present in the inheriting class:

| Attribute | Type | Description |
|-----------|------|-------------|
| `self.enable_cache` | `bool` | Whether caching is enabled |
| `self._cache` | Cache instance | The cache implementation (must have `get_metrics()`, `invalidate()`, `get_cache_info()` methods) |
| `self.logger` | `logging.Logger` | Logger instance for metrics logging |

## Usage Examples

### Basic Usage

```python
from agents.lib.manifest_cache_utilities import ManifestCacheUtilitiesMixin

class MyManifestHandler(ManifestCacheUtilitiesMixin):
    def __init__(self):
        self.enable_cache = True
        self._cache = SomeCacheImplementation()
        self.logger = logging.getLogger(__name__)

handler = MyManifestHandler()

# Get metrics
metrics = handler.get_cache_metrics()
print(f"Cache hit rate: {metrics['overall']['hit_rate_percent']:.1f}%")

# Clear cache
cleared = handler.clear_cache()
print(f"Cleared {cleared} cache entries")

# Log metrics
handler.log_cache_metrics()
```

### With Caching Disabled

```python
handler = MyManifestHandler()
handler.enable_cache = False

# All methods return safe defaults
metrics = handler.get_cache_metrics()  # Returns {"error": "Caching disabled"}
cleared = handler.invalidate_cache()    # Returns 0
info = handler.get_cache_info()        # Returns {"error": "Caching disabled"}
handler.log_cache_metrics()            # Logs "Cache metrics: caching disabled"
```

## Testing

### Import Test

```bash
python3 -c "from agents.lib.manifest_cache_utilities import ManifestCacheUtilitiesMixin; print('✅ Import successful')"
```

### Functionality Test

```python
from agents.lib.manifest_cache_utilities import ManifestCacheUtilitiesMixin
import logging

class TestInjector(ManifestCacheUtilitiesMixin):
    def __init__(self):
        self.enable_cache = False
        self._cache = None
        self.logger = logging.getLogger(__name__)

injector = TestInjector()
assert injector.get_cache_metrics() == {"error": "Caching disabled"}
assert injector.invalidate_cache() == 0
print("✅ All tests passed")
```

## Migration Steps

To migrate `ManifestInjector` to use this mixin:

1. **Add import** at top of `manifest_injector.py`:
   ```python
   from agents.lib.manifest_cache_utilities import ManifestCacheUtilitiesMixin
   ```

2. **Update class definition**:
   ```python
   class ManifestInjector(ManifestCacheUtilitiesMixin):
   ```

3. **Remove duplicate methods**:
   - Delete `get_cache_metrics()` (line ~2279)
   - Delete `invalidate_cache()` (line ~2294)
   - Delete `get_cache_info()` (line ~2309)
   - Delete `log_cache_metrics()` (line ~2321)

4. **Test functionality**:
   ```bash
   python3 agents/lib/test_manifest_traceability.py
   ```

## Benefits

- ✅ **Modularity**: Cache utilities separated from main injector logic
- ✅ **Reusability**: Can be used by other classes needing cache management
- ✅ **Testability**: Mixin can be tested independently
- ✅ **Maintainability**: Single source of truth for cache utilities
- ✅ **No NameError**: Proper class structure prevents `self` reference errors
- ✅ **Backward Compatible**: Same method signatures and behavior

## Troubleshooting

### NameError: name 'self' is not defined

**Cause**: Trying to use standalone functions instead of a class.

**Solution**: This mixin is a proper class - inherit from it:
```python
class MyClass(ManifestCacheUtilitiesMixin):  # ✅ Correct
    pass

# NOT standalone function calls:
get_cache_metrics(self)  # ❌ Wrong
```

### AttributeError: 'MyClass' object has no attribute 'enable_cache'

**Cause**: Required attributes not initialized.

**Solution**: Ensure all required attributes are set in `__init__`:
```python
class MyClass(ManifestCacheUtilitiesMixin):
    def __init__(self):
        self.enable_cache = True   # Required
        self._cache = cache_inst   # Required
        self.logger = logger       # Required
```

### Cache methods return {"error": "Caching disabled"}

**Cause**: Either `enable_cache=False` or `_cache=None`.

**Solution**: Verify cache is properly initialized:
```python
# Check configuration
print(f"Cache enabled: {injector.enable_cache}")
print(f"Cache instance: {injector._cache}")
```

## See Also

- `agents/lib/manifest_injector.py` - Main ManifestInjector class
- `agents/lib/result_cache.py` - Cache implementation
- `agents/lib/test_manifest_traceability.py` - Integration tests
