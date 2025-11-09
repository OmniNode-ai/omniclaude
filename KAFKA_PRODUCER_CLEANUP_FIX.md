# AIOKafkaProducer Resource Leak Fix

**Issue**: Unclosed AIOKafkaProducer resource warnings in pytest output

**Impact**: Resource leak warnings from global singleton Kafka producers

## Root Cause

The global singleton Kafka producers in `action_event_publisher.py` and `transformation_event_publisher.py` were never being cleaned up:

1. Producers created with one event loop
2. Event loop closed after `asyncio.run()` completes
3. Producers still exist but can't be cleaned up asynchronously
4. Python garbage collector issues `ResourceWarning: Unclosed AIOKafkaProducer`

## Solution

Three-layer cleanup approach:

### 1. Pytest Fixtures (Primary)

Added session-scoped autouse fixtures in `tests/conftest.py` and `agents/tests/conftest.py` that automatically cleanup producers after all tests complete:

```python
@pytest.fixture(scope="session", autouse=True)
def cleanup_kafka_producers():
    """Automatically cleanup global Kafka producers after all tests complete."""
    yield
    # Cleanup logic runs here
```

**Why this works**: Fixture runs BEFORE asyncio.run() closes the event loop, allowing proper async cleanup.

### 2. Atexit Handlers (Fallback)

Added atexit handlers to both publisher modules that:

1. Try to use existing event loop if available and not closed
2. If loop is closed, directly close internal components:
   - `_kafka_producer._client.close()` - Close underlying Kafka client
   - `_kafka_producer._sender = None` - Clear sender
   - `_kafka_producer._closed = True` - Mark as closed
3. Set producer to None to prevent repeated cleanup

**Why this works**: Synchronous cleanup of internal components prevents resource warnings even when event loop is closed.

### 3. Explicit Cleanup

The `close_producer()` async function already exists and can be called explicitly:

```python
from agents.lib import action_event_publisher

# After using publisher
await action_event_publisher.close_producer()
```

## Files Modified

1. **agents/lib/action_event_publisher.py**
   - Added `atexit` import
   - Added `_cleanup_producer_sync()` function
   - Registered atexit handler

2. **agents/lib/transformation_event_publisher.py**
   - Added `atexit` import
   - Added `_cleanup_producer_sync()` function
   - Registered atexit handler

3. **tests/conftest.py**
   - Added `asyncio` import
   - Added `cleanup_kafka_producers` fixture

4. **agents/tests/conftest.py**
   - Added `asyncio` and `pytest` imports
   - Added `cleanup_kafka_producers` fixture

## Testing

### Manual Test
```bash
# Should show no "Unclosed AIOKafkaProducer" warnings
python3 -c "
from agents.lib import action_event_publisher
import asyncio
asyncio.run(action_event_publisher.publish_action_event(
    agent_name='test', action_type='tool_call', action_name='Read'
))
"
```

### Pytest
```bash
# Should show no resource warnings
python3 -m pytest agents/tests/ -W default
```

## Success Criteria

✅ No "Unclosed AIOKafkaProducer" warnings in pytest output
✅ No "Event loop is closed" errors during cleanup
✅ All existing tests continue to pass
✅ Resource cleanup happens automatically

## Implementation Notes

- **Defensive coding**: All cleanup is best-effort and never raises exceptions
- **Event loop handling**: Properly detects closed loops and uses synchronous cleanup
- **Pytest integration**: Autouse fixture ensures cleanup without test changes
- **Backward compatibility**: Explicit `close_producer()` still works as before

## Related

- Issue: Unclosed AIOKafkaProducer resource warnings
- Tasks: `_md_synchronizer()`, `_sender_routine()`, `_read()` pending tasks
- Correlation ID: 3a8dc13e-6786-42ac-9269-115dac88479a
