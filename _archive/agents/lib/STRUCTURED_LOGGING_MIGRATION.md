# Structured Logging Migration Guide

This guide shows how to migrate existing agents to use the new structured JSON logging framework with correlation ID support.

## Quick Start

### Before (Old Logging)
```python
import logging

logger = logging.getLogger(__name__)
logger.info(f"Task started: {task_id}")
```

### After (Structured Logging)
```python
from lib.structured_logger import get_logger
from lib.log_context import async_log_context

logger = get_logger(__name__, component="agent-researcher")

async def execute_task(task_id: str, correlation_id: UUID):
    async with async_log_context(correlation_id=correlation_id):
        logger.info("Task started", metadata={"task_id": task_id})
```

## Migration Patterns

### Pattern 1: Simple Logger Replacement

**Before:**
```python
import logging

logger = logging.getLogger(__name__)

def process_task(task_id: str):
    logger.info(f"Processing task {task_id}")
    try:
        result = do_work()
        logger.info(f"Task {task_id} completed")
        return result
    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        raise
```

**After:**
```python
from lib.structured_logger import get_logger

logger = get_logger(__name__, component="agent-processor")

def process_task(task_id: str):
    logger.info("Processing task", metadata={"task_id": task_id})
    try:
        result = do_work()
        logger.info("Task completed", metadata={"task_id": task_id})
        return result
    except Exception as e:
        logger.error("Task failed", metadata={"task_id": task_id}, exc_info=e)
        raise
```

### Pattern 2: Agent with Correlation IDs

**Before:**
```python
import logging

logger = logging.getLogger(__name__)

async def research_task(query: str):
    logger.info(f"Starting research for: {query}")
    results = await perform_research(query)
    logger.info(f"Research completed: {len(results)} results")
    return results
```

**After:**
```python
from lib.structured_logger import get_logger
from lib.log_context import with_log_context
from uuid import UUID

logger = get_logger(__name__, component="agent-researcher")

@with_log_context(component="agent-researcher")
async def research_task(query: str, correlation_id: UUID):
    logger.info("Starting research", metadata={"query": query})
    results = await perform_research(query)
    logger.info("Research completed", metadata={"results_count": len(results)})
    return results
```

### Pattern 3: Multi-Phase Workflow

**Before:**
```python
import logging

logger = logging.getLogger(__name__)

async def execute_workflow(request: dict):
    logger.info("Workflow started")

    # Phase 1
    logger.info("Phase 1: Research")
    research_results = await research_phase(request)

    # Phase 2
    logger.info("Phase 2: Analysis")
    analysis_results = await analysis_phase(research_results)

    logger.info("Workflow completed")
    return analysis_results
```

**After:**
```python
from lib.structured_logger import get_logger
from lib.log_context import async_log_context
from uuid import uuid4

logger = get_logger(__name__, component="agent-workflow")

async def execute_workflow(request: dict):
    correlation_id = uuid4()

    async with async_log_context(correlation_id=correlation_id):
        logger.info("Workflow started", metadata={"request_id": request.get("id")})

        # Phase 1
        logger.info("Phase started", metadata={"phase": "research"})
        research_results = await research_phase(request, correlation_id)
        logger.info("Phase completed", metadata={"phase": "research", "results_count": len(research_results)})

        # Phase 2
        logger.info("Phase started", metadata={"phase": "analysis"})
        analysis_results = await analysis_phase(research_results, correlation_id)
        logger.info("Phase completed", metadata={"phase": "analysis"})

        logger.info("Workflow completed", metadata={"correlation_id": str(correlation_id)})
        return analysis_results
```

### Pattern 4: Error Handling with Context

**Before:**
```python
import logging

logger = logging.getLogger(__name__)

def process_item(item: dict):
    try:
        result = transform_item(item)
        logger.info(f"Processed item: {item['id']}")
        return result
    except ValueError as e:
        logger.error(f"Validation error for item {item['id']}: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error for item {item['id']}")
        raise
```

**After:**
```python
from lib.structured_logger import get_logger

logger = get_logger(__name__, component="agent-processor")

def process_item(item: dict, correlation_id: str = None):
    if correlation_id:
        logger.set_correlation_id(correlation_id)

    try:
        result = transform_item(item)
        logger.info("Item processed", metadata={"item_id": item['id']})
        return result
    except ValueError as e:
        logger.error(
            "Validation error",
            metadata={"item_id": item['id'], "error_type": "validation"},
            exc_info=e
        )
        return None
    except Exception as e:
        logger.critical(
            "Unexpected error",
            metadata={"item_id": item['id'], "error_type": "unexpected"},
            exc_info=e
        )
        raise
```

## Best Practices

### 1. Use Metadata for Structured Data

**Don't:**
```python
logger.info(f"Task {task_id} completed in {duration}ms with {result_count} results")
```

**Do:**
```python
logger.info("Task completed", metadata={
    "task_id": task_id,
    "duration_ms": duration,
    "result_count": result_count
})
```

### 2. Set Component at Logger Creation

**Don't:**
```python
logger = get_logger(__name__)
```

**Do:**
```python
logger = get_logger(__name__, component="agent-researcher")
```

### 3. Use Context Managers for Correlation IDs

**Don't:**
```python
logger.set_correlation_id(correlation_id)
# ... lots of code ...
# Correlation ID never cleared
```

**Do:**
```python
async with async_log_context(correlation_id=correlation_id):
    # All logs automatically tagged
    # Correlation ID cleared on exit
```

### 4. Use Decorators for Functions with Correlation IDs

**Don't:**
```python
async def task(correlation_id: UUID):
    logger.set_correlation_id(correlation_id)
    # ... rest of function
```

**Do:**
```python
@with_log_context(component="agent-task")
async def task(correlation_id: UUID):
    # Correlation ID automatically set from parameter
    # ... rest of function
```

### 5. Include Exception Info for Errors

**Don't:**
```python
except Exception as e:
    logger.error(f"Task failed: {str(e)}")
```

**Do:**
```python
except Exception as e:
    logger.error("Task failed", metadata={"task_id": task_id}, exc_info=e)
```

## Log Rotation Configuration

### Development Environment

```python
from lib.log_rotation import configure_global_rotation

# Configure rotation for all loggers
configure_global_rotation(environment="development")
```

### Production Environment

```python
from lib.log_rotation import configure_global_rotation, LogRotationConfig

# Custom production config
config = LogRotationConfig(
    log_dir="/var/log/agents",
    max_bytes=100 * 1024 * 1024,  # 100MB
    backup_count=60,  # Keep 60 files
    compression=True
)
configure_global_rotation(config=config)
```

### Per-Logger Rotation

```python
from lib.structured_logger import get_logger
from lib.log_rotation import configure_file_rotation

logger = get_logger(__name__, component="agent-researcher")
configure_file_rotation(
    logger,
    log_dir="/var/log/agents",
    max_bytes=50 * 1024 * 1024,  # 50MB
    backup_count=30,
    filename="researcher.log"
)
```

## JSON Log Output Format

All logs are output as JSON with the following structure:

```json
{
  "timestamp": "2025-01-15T10:30:45.123456+00:00",
  "level": "INFO",
  "logger_name": "agent_researcher",
  "message": "Research task completed",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "component": "agent-researcher",
  "metadata": {
    "task_id": "123",
    "duration_ms": 1234,
    "results_count": 42
  }
}
```

## Monitoring Integration

The structured JSON logs can be easily integrated with monitoring systems:

### ELK Stack (Elasticsearch, Logstash, Kibana)

```
# Logstash config
input {
  file {
    path => "/var/log/agents/*.log"
    codec => "json"
  }
}

filter {
  json {
    source => "message"
  }
}

output {
  elasticsearch {
    hosts => ["localhost:9200"]
    index => "agent-logs-%{+YYYY.MM.dd}"
  }
}
```

### Splunk

```
# inputs.conf
[monitor:///var/log/agents/*.log]
sourcetype = _json
index = agent_logs
```

### CloudWatch Logs

```python
import watchtower
from lib.structured_logger import get_logger

logger = get_logger(__name__, component="agent-researcher")

# Add CloudWatch handler
cloudwatch_handler = watchtower.CloudWatchLogHandler(
    log_group="/aws/agents",
    stream_name="agent-researcher"
)
logger.logger.addHandler(cloudwatch_handler)
```

## Performance Considerations

The structured logging framework is optimized for minimal overhead:

- **Log entry overhead**: <1ms per log
- **Context setup**: <0.1ms
- **JSON serialization**: Optimized for common data types

Performance targets validated in test suite:
- `test_log_overhead`: Validates <1ms per log entry
- `test_context_overhead`: Validates <0.1ms context setup

## Common Migration Issues

### Issue 1: String Formatting in Log Messages

**Problem:**
```python
logger.info(f"Task {task_id} completed in {duration}ms")
```

**Solution:**
```python
logger.info("Task completed", metadata={"task_id": task_id, "duration_ms": duration})
```

### Issue 2: Missing Correlation IDs

**Problem:**
Logs not showing correlation IDs even though they're set.

**Solution:**
Make sure to use context managers or decorators:
```python
async with async_log_context(correlation_id=correlation_id):
    logger.info("Task started")  # Correlation ID included
```

### Issue 3: Correlation IDs Not Propagating

**Problem:**
Calling functions that don't receive correlation_id parameter.

**Solution:**
Use global context instead of passing parameters:
```python
# In caller
async with async_log_context(correlation_id=correlation_id):
    await helper_function()  # No parameter needed

# In helper
def helper_function():
    logger.info("Helper called")  # Correlation ID from context
```

## Testing

Test your logging integration:

```python
import pytest
from uuid import uuid4
from lib.structured_logger import get_logger
from lib.log_context import async_log_context

@pytest.mark.asyncio
async def test_logging_integration():
    logger = get_logger("test", component="test-agent")
    correlation_id = uuid4()

    async with async_log_context(correlation_id=correlation_id):
        logger.info("Test message", metadata={"test_id": "123"})

        # Verify correlation ID is set
        from lib.structured_logger import get_correlation_id
        assert get_correlation_id() == str(correlation_id)
```

## Checklist

When migrating an agent to structured logging:

- [ ] Replace `logging.getLogger()` with `get_logger()`
- [ ] Add `component` parameter to logger creation
- [ ] Replace f-string log messages with message + metadata
- [ ] Add correlation_id parameter to main entry points
- [ ] Use `async_log_context` or `@with_log_context` decorator
- [ ] Update error handling to use `exc_info` parameter
- [ ] Configure log rotation (development or production)
- [ ] Add tests for logging integration
- [ ] Update documentation with correlation_id parameter
- [ ] Verify JSON output format

## Support

For questions or issues with structured logging migration:
- Check test suite: `agents/tests/test_structured_logging.py`
- Review examples in this guide
- Reference implementation: `agents/lib/structured_logger.py`
