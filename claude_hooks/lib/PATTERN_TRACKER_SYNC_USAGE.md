# PatternTrackerSync - Usage Guide

## Overview

`PatternTrackerSync` is a synchronous (blocking) version of the Pattern Tracker designed specifically for use in Claude Code hooks where async execution causes premature script exit.

## Key Features

✅ **Synchronous HTTP calls** using `requests` library
✅ **Blocks until API response** - ensures patterns are saved before script exit
✅ **Comprehensive error handling** with clear logging
✅ **Quality score calculation** built-in
✅ **Deterministic pattern IDs** based on file path + code content

## Quick Start

### Basic Usage

```python
from lib.pattern_tracker_sync import PatternTrackerSync

# Create tracker (performs health check automatically)
tracker = PatternTrackerSync()

# Track a pattern
code = """
def example_function():
    return "Hello, World!"
"""

context = {
    "event_type": "pattern_created",
    "file_path": "/path/to/file.py",
    "language": "python",
    "reason": "Code generation via Claude Code",
    "quality_score": 0.95,
    "violations_found": 1
}

pattern_id = tracker.track_pattern_creation(code, context)

if pattern_id:
    print(f"✅ Pattern tracked: {pattern_id}")
else:
    print("❌ Pattern tracking failed")
```

## Use in Hooks

### Example: Write Hook Integration

```python
#!/usr/bin/env python3
"""Claude Code write hook with pattern tracking."""

import sys
from lib.pattern_tracker_sync import PatternTrackerSync

def main():
    # Read input from Claude Code
    file_path = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    code = sys.stdin.read()

    # Initialize tracker
    tracker = PatternTrackerSync()

    # Track the pattern
    context = {
        "event_type": "code_written",
        "file_path": file_path,
        "language": detect_language(file_path),
        "reason": "File write via Claude Code",
        "quality_score": 1.0,
        "violations_found": 0
    }

    # This will BLOCK until the API responds
    pattern_id = tracker.track_pattern_creation(code, context)

    if pattern_id:
        print(f"✅ Pattern tracked: {pattern_id}", file=sys.stderr)

    # Write the code to stdout for Claude Code
    sys.stdout.write(code)

if __name__ == "__main__":
    main()
```

## Context Dictionary

The `context` parameter accepts the following fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event_type` | str | No | Event type (default: "pattern_created") |
| `file_path` | str | Yes | Path to the file being tracked |
| `language` | str | Yes | Programming language (python, typescript, etc.) |
| `reason` | str | No | Reason for tracking |
| `quality_score` | float | No | Quality score 0.0-1.0 (default: 1.0) |
| `violations_found` | int | No | Number of violations (default: 0) |

## Quality Score Calculation

Use the built-in quality score calculator:

```python
tracker = PatternTrackerSync()

# Calculate score from violations list
violations = ["missing_docstring", "unused_variable"]
score = tracker.calculate_quality_score(violations)
# Returns: 0.8 (1.0 - 0.1 per violation)
```

**Scoring Formula:**
- No violations: 1.0
- Each violation: -0.1
- Minimum score: 0.0

## Error Handling

The tracker has comprehensive error handling:

```python
pattern_id = tracker.track_pattern_creation(code, context)

if pattern_id is None:
    # Tracking failed - check stderr for details
    # Possible reasons:
    # - Intelligence service not running
    # - Network timeout
    # - HTTP error from API
    # - Invalid request format
    pass
```

### Error Messages

| Symbol | Meaning |
|--------|---------|
| ✅ | Success - operation completed |
| ❌ | Error - operation failed |
| ⚠️ | Warning - degraded functionality |
| 📤 | Info - sending data |

## Configuration

### Service URL

Default: `http://localhost:8053`

To change:
```python
tracker = PatternTrackerSync()
tracker.base_url = "http://custom-host:8053"
```

### Timeout

Default: 5 seconds

To change:
```python
tracker = PatternTrackerSync()
tracker.timeout = 10  # seconds
```

## Testing

Run the built-in tests:

```bash
# From hooks directory
cd ${HOME}/.claude/hooks
python test_pattern_tracker_sync_verify.py
```

Or test the module directly:

```bash
cd ${HOME}/.claude/hooks
python -m lib.pattern_tracker_sync
```

## Troubleshooting

### Import Error: logging module conflict

**Problem:** `ImportError: cannot import name 'NullHandler' from 'logging'`

**Solution:** Run from parent directory:
```bash
cd ${HOME}/.claude/hooks  # Not hooks/lib
python -m lib.pattern_tracker_sync
```

### Connection Error: API unreachable

**Problem:** `❌ Connection failed: Connection refused`

**Solution:** Verify Intelligence service is running:
```bash
curl http://localhost:8053/health
```

Or check Docker:
```bash
docker ps | grep intelligence
```

### Pattern Not Found After Tracking

**Problem:** Pattern tracked successfully but can't retrieve it

**Notes:**
- The tracking endpoint returns success when pattern is accepted
- Pattern retrieval endpoints may have different paths
- Check OpenAPI docs: http://localhost:8053/docs

## Comparison: Sync vs Async

| Feature | PatternTrackerSync | PatternTracker (Async) |
|---------|-------------------|------------------------|
| Execution | Blocking | Non-blocking |
| Library | `requests` | `httpx` |
| Hook Compatible | ✅ Yes | ❌ No (exits early) |
| Performance | Slower (blocks) | Faster (concurrent) |
| Use Case | Hooks, scripts | Services, APIs |

## Best Practices

1. **Always check return value**
   ```python
   pattern_id = tracker.track_pattern_creation(code, context)
   if pattern_id:
       # Success
   else:
       # Handle failure
   ```

2. **Use stderr for logging**
   ```python
   print("Debug info", file=sys.stderr)  # Won't interfere with stdout
   ```

3. **Provide meaningful context**
   ```python
   context = {
       "file_path": "/real/path/to/file.py",  # Not "unknown"
       "language": "python",                   # Specific language
       "reason": "Descriptive reason",         # Clear reason
       "quality_score": calculated_score       # Actual score
   }
   ```

4. **Handle errors gracefully**
   ```python
   try:
       pattern_id = tracker.track_pattern_creation(code, context)
   except Exception as e:
       print(f"Pattern tracking failed: {e}", file=sys.stderr)
       # Continue with normal operation
   ```

## API Endpoints Used

- **Health Check:** `GET http://localhost:8053/health`
- **Track Pattern:** `POST http://localhost:8053/api/pattern-traceability/lineage/track`

## Session Management

Each tracker instance has a unique session ID:

```python
tracker = PatternTrackerSync()
print(tracker.session_id)  # UUID for this session

# Or provide your own:
tracker = PatternTrackerSync(session_id="my-session-123")
```

## Pattern ID Generation

Pattern IDs are deterministic based on:
- File path
- First 200 characters of code

This ensures the same code generates the same ID for deduplication.

```python
# These will generate the same pattern ID:
pattern_id_1 = tracker.track_pattern_creation(code, context)
pattern_id_2 = tracker.track_pattern_creation(code, context)
# pattern_id_1 == pattern_id_2
```

## Performance Notes

- **Health check:** ~50ms (cached after first call)
- **Pattern tracking:** ~100-500ms depending on network
- **Timeout:** 5 seconds (configurable)

For hooks, this blocking behavior is **desired** - ensures patterns are saved before script exits.

## Related Documentation

- **Async Version:** `pattern_tracker.py` - For services and APIs
- **Phase 4 API Client:** `phase4_api_client.py` - Full API integration
- **Resilience Library:** `resilience.py` - Retry and circuit breaker patterns
- **Pattern ID System:** `pattern_id_system.py` - Advanced pattern management

---

**Last Updated:** 2025-10-03
**Version:** 1.0.0
**Status:** Production Ready
