# Logging Event Publisher - Usage Guide

**Module**: `agents/lib/logging_event_publisher.py`
**Created**: 2025-11-13
**Phase**: Event Bus Alignment Phase 2 (OMN-34, OMN-35, OMN-36)

## Overview

The Logging Event Publisher provides structured logging capabilities via Kafka events, enabling real-time log streaming to omnidash and centralized log aggregation. This module publishes three types of logging events:

1. **Application Logs** (`omninode.logging.application.v1`) - Structured application logs
2. **Audit Logs** (`omninode.logging.audit.v1`) - Audit trail for compliance
3. **Security Logs** (`omninode.logging.security.v1`) - Security audit events

## Quick Start

### Basic Usage (One-off Publishing)

```python
from agents.lib.logging_event_publisher import (
    publish_application_log,
    publish_audit_log,
    publish_security_log,
)

# Application log
await publish_application_log(
    service_name="omniclaude",
    instance_id="omniclaude-1",
    level="INFO",
    logger_name="router.pipeline",
    message="Agent execution completed successfully",
    code="AGENT_EXECUTION_COMPLETED",
    context={"agent_name": "agent-api-architect", "duration_ms": 1234},
    correlation_id="abc-123-def-456",
)

# Audit log
await publish_audit_log(
    tenant_id="tenant-123",
    action="agent.execution",
    actor="user-456",
    resource="agent-api-architect",
    outcome="success",
    correlation_id="abc-123-def-456",
)

# Security log
await publish_security_log(
    tenant_id="tenant-123",
    event_type="api_key_used",
    user_id="user-456",
    resource="gemini-api",
    decision="allow",
    correlation_id="abc-123-def-456",
)
```

### Advanced Usage (Persistent Publisher)

For high-frequency logging, use a persistent publisher to avoid connection overhead:

```python
from agents.lib.logging_event_publisher import LoggingEventPublisher

# Initialize publisher
publisher = LoggingEventPublisher(
    bootstrap_servers="localhost:9092",  # Optional: defaults from config
    enable_events=True,  # Feature flag
)

try:
    # Start publisher (creates Kafka producer)
    await publisher.start()

    # Publish multiple logs
    for i in range(100):
        await publisher.publish_application_log(
            service_name="omniclaude",
            instance_id="omniclaude-1",
            level="INFO",
            logger_name="batch.processor",
            message=f"Processed batch {i}",
            code="BATCH_PROCESSED",
            context={"batch_id": i, "items": 50},
        )
finally:
    # Clean up
    await publisher.stop()
```

### Context Manager (Recommended)

```python
from agents.lib.logging_event_publisher import LoggingEventPublisherContext

async with LoggingEventPublisherContext() as publisher:
    await publisher.publish_application_log(
        service_name="omniclaude",
        instance_id="omniclaude-1",
        level="INFO",
        logger_name="router.pipeline",
        message="Agent execution started",
        code="AGENT_EXECUTION_STARTED",
    )

    # Publisher automatically started and stopped
```

## Event Types

### 1. Application Logs (`omninode.logging.application.v1`)

**Purpose**: Structured application logs for real-time monitoring and debugging

**Partition Key**: `service_name` (ensures all logs from same service are ordered)

**Parameters**:
- `service_name` (str, required): Service name (e.g., "omniclaude")
- `instance_id` (str, required): Instance identifier (e.g., "omniclaude-1")
- `level` (str, required): Log level ("INFO", "WARN", "ERROR", "DEBUG")
- `logger_name` (str, required): Logger name (e.g., "router.pipeline", "agent.executor")
- `message` (str, required): Log message
- `code` (str, required): Log code for categorization (e.g., "AGENT_EXECUTION_COMPLETED")
- `context` (dict, optional): Additional context (agent_name, duration_ms, etc.)
- `correlation_id` (str, optional): Correlation ID for request tracing

**Example**:
```python
await publisher.publish_application_log(
    service_name="omniclaude",
    instance_id="omniclaude-1",
    level="INFO",
    logger_name="router.pipeline",
    message="Agent routed successfully",
    code="AGENT_ROUTED",
    context={
        "agent_name": "agent-api-architect",
        "confidence_score": 0.95,
        "routing_time_ms": 7,
    },
    correlation_id="abc-123-def-456",
)
```

**Log Codes** (recommended standard):
- `AGENT_EXECUTION_STARTED` - Agent started
- `AGENT_EXECUTION_COMPLETED` - Agent completed successfully
- `AGENT_EXECUTION_FAILED` - Agent failed
- `AGENT_ROUTED` - Agent routing decision made
- `QUALITY_GATE_PASSED` - Quality gate validation passed
- `QUALITY_GATE_FAILED` - Quality gate validation failed
- `PROVIDER_SELECTED` - AI provider selected
- `KAFKA_EVENT_PUBLISHED` - Event published to Kafka
- `KAFKA_EVENT_FAILED` - Event publish failed

### 2. Audit Logs (`omninode.logging.audit.v1`)

**Purpose**: Audit trail for compliance and regulatory requirements

**Partition Key**: `tenant_id` (ensures all audit logs for same tenant are ordered)

**Parameters**:
- `tenant_id` (str, required): Tenant identifier (UUID or string)
- `action` (str, required): Action performed (e.g., "agent.execution", "api.call")
- `actor` (str, required): User or service that performed the action
- `resource` (str, required): Resource accessed (e.g., agent name, API endpoint)
- `outcome` (str, required): Outcome of the action ("success" or "failure")
- `correlation_id` (str, optional): Correlation ID for request tracing
- `context` (dict, optional): Additional context (duration_ms, quality_score, etc.)

**Example**:
```python
await publisher.publish_audit_log(
    tenant_id="tenant-123",
    action="agent.execution",
    actor="user-456",
    resource="agent-api-architect",
    outcome="success",
    correlation_id="abc-123-def-456",
    context={
        "duration_ms": 5432,
        "quality_score": 0.92,
        "execution_start": "2025-11-13T14:30:00Z",
        "execution_end": "2025-11-13T14:30:05Z",
    },
)
```

**Action Types** (recommended standard):
- `agent.execution` - Agent execution
- `api.call` - API call made
- `data.access` - Data accessed
- `config.change` - Configuration changed
- `user.login` - User login
- `user.logout` - User logout
- `permission.grant` - Permission granted
- `permission.revoke` - Permission revoked

### 3. Security Logs (`omninode.logging.security.v1`)

**Purpose**: Security audit events for monitoring and threat detection

**Partition Key**: `tenant_id` (ensures all security logs for same tenant are ordered)

**Parameters**:
- `tenant_id` (str, required): Tenant identifier (UUID or string)
- `event_type` (str, required): Security event type (e.g., "api_key_used", "permission_check")
- `user_id` (str, required): User identifier
- `resource` (str, required): Resource being accessed
- `decision` (str, required): Security decision ("allow" or "deny")
- `correlation_id` (str, optional): Correlation ID for request tracing
- `context` (dict, optional): Additional context (api_key_hash, ip_address, etc.)

**Example**:
```python
await publisher.publish_security_log(
    tenant_id="tenant-123",
    event_type="api_key_used",
    user_id="user-456",
    resource="gemini-api",
    decision="allow",
    correlation_id="abc-123-def-456",
    context={
        "api_key_hash": "sha256:abc123...",
        "ip_address": "192.168.1.1",
        "user_agent": "omniclaude/1.0.0",
        "request_path": "/api/v1/completion",
    },
)
```

**Event Types** (recommended standard):
- `api_key_used` - API key used for authentication
- `api_key_created` - New API key created
- `api_key_revoked` - API key revoked
- `permission_check` - Permission check performed
- `authentication_success` - Authentication succeeded
- `authentication_failure` - Authentication failed
- `authorization_success` - Authorization granted
- `authorization_failure` - Authorization denied
- `suspicious_activity` - Suspicious activity detected
- `rate_limit_exceeded` - Rate limit exceeded

## Configuration

### Environment Variables

The publisher uses centralized configuration from `config/settings.py`:

```bash
# Kafka configuration (required)
KAFKA_BOOTSTRAP_SERVERS=localhost:9092  # Or 192.168.86.200:29092 for production

# Optional: Feature flag to enable/disable events
KAFKA_ENABLE_LOGGING_EVENTS=true

# Optional: Tenant ID for multi-tenancy
TENANT_ID=default
```

### Publisher Configuration

```python
publisher = LoggingEventPublisher(
    bootstrap_servers="localhost:9092",  # Defaults to settings.kafka_bootstrap_servers
    enable_events=True,  # Feature flag to disable events
)
```

## Integration Examples

### Replace Existing Python Logging

```python
import logging
from agents.lib.logging_event_publisher import LoggingEventPublisher

# Standard Python logger
logger = logging.getLogger(__name__)

# Logging event publisher
logging_publisher = LoggingEventPublisher()
await logging_publisher.start()

try:
    # Your code
    result = await execute_agent_task()

    # Standard logging (file-based)
    logger.info(f"Agent completed: {result}")

    # Event logging (Kafka-based, visible in omnidash)
    await logging_publisher.publish_application_log(
        service_name="omniclaude",
        instance_id="omniclaude-1",
        level="INFO",
        logger_name=__name__,
        message=f"Agent completed: {result}",
        code="AGENT_EXECUTION_COMPLETED",
        context={"result": result},
    )
finally:
    await logging_publisher.stop()
```

### Dual Logging (File + Kafka)

Create a custom logger that logs to both file and Kafka:

```python
import logging
from typing import Optional
from agents.lib.logging_event_publisher import LoggingEventPublisher

class DualLogger:
    """Logger that writes to both file and Kafka."""

    def __init__(self, logger_name: str, service_name: str, instance_id: str):
        self.logger = logging.getLogger(logger_name)
        self.service_name = service_name
        self.instance_id = instance_id
        self.event_publisher = LoggingEventPublisher()

    async def start(self):
        await self.event_publisher.start()

    async def stop(self):
        await self.event_publisher.stop()

    async def info(self, message: str, code: str, context: Optional[dict] = None, correlation_id: Optional[str] = None):
        # File logging (synchronous)
        self.logger.info(message)

        # Event logging (asynchronous)
        await self.event_publisher.publish_application_log(
            service_name=self.service_name,
            instance_id=self.instance_id,
            level="INFO",
            logger_name=self.logger.name,
            message=message,
            code=code,
            context=context or {},
            correlation_id=correlation_id,
        )

    # Similar methods for warn, error, debug...
```

### Audit Trail Integration

```python
async def execute_agent_with_audit(
    tenant_id: str,
    user_id: str,
    agent_name: str,
    user_request: str,
    correlation_id: str,
):
    """Execute agent with complete audit trail."""

    async with LoggingEventPublisherContext() as publisher:
        # Log audit: agent execution started
        await publisher.publish_audit_log(
            tenant_id=tenant_id,
            action="agent.execution.started",
            actor=user_id,
            resource=agent_name,
            outcome="success",
            correlation_id=correlation_id,
        )

        try:
            # Execute agent
            result = await execute_agent(agent_name, user_request, correlation_id)

            # Log audit: agent execution completed
            await publisher.publish_audit_log(
                tenant_id=tenant_id,
                action="agent.execution.completed",
                actor=user_id,
                resource=agent_name,
                outcome="success",
                correlation_id=correlation_id,
                context={"result_summary": result["summary"]},
            )

            return result

        except Exception as e:
            # Log audit: agent execution failed
            await publisher.publish_audit_log(
                tenant_id=tenant_id,
                action="agent.execution.failed",
                actor=user_id,
                resource=agent_name,
                outcome="failure",
                correlation_id=correlation_id,
                context={"error": str(e)},
            )
            raise
```

### Security Monitoring Integration

```python
async def check_api_key_and_log(
    tenant_id: str,
    user_id: str,
    api_key: str,
    resource: str,
    correlation_id: str,
):
    """Check API key validity and log security event."""

    async with LoggingEventPublisherContext() as publisher:
        # Validate API key
        is_valid = await validate_api_key(api_key)

        # Log security event
        await publisher.publish_security_log(
            tenant_id=tenant_id,
            event_type="api_key_used",
            user_id=user_id,
            resource=resource,
            decision="allow" if is_valid else "deny",
            correlation_id=correlation_id,
            context={
                "api_key_hash": hashlib.sha256(api_key.encode()).hexdigest(),
                "validation_result": "valid" if is_valid else "invalid",
            },
        )

        if not is_valid:
            raise UnauthorizedError("Invalid API key")
```

## Event Envelope Structure

All logging events follow the OnexEnvelopeV1 structure:

```json
{
  "event_type": "omninode.logging.application.v1",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2025-11-13T14:30:00.123456Z",
  "tenant_id": "default",
  "namespace": "omninode",
  "source": "omniclaude",
  "correlation_id": "abc-123-def-456",
  "causation_id": "abc-123-def-456",
  "schema_ref": "registry://omninode/logging/application/v1",
  "payload": {
    "service_name": "omniclaude",
    "instance_id": "omniclaude-1",
    "level": "INFO",
    "logger": "router.pipeline",
    "message": "Agent execution completed successfully",
    "code": "AGENT_EXECUTION_COMPLETED",
    "context": {
      "agent_name": "agent-api-architect",
      "duration_ms": 1234
    }
  }
}
```

## Performance Characteristics

**Publisher Lifecycle**:
- Start overhead: ~50ms (Kafka connection)
- Stop overhead: ~20ms (graceful shutdown)
- Memory overhead: <10MB per publisher instance

**Publishing Performance** (local Kafka):
- Publish time (p50): ~3ms
- Publish time (p95): ~10ms
- Publish time (p99): ~25ms
- Throughput: >1000 events/second per publisher

**Production Performance** (remote Kafka):
- Publish time (p50): ~8ms
- Publish time (p95): ~20ms
- Publish time (p99): ~50ms
- Throughput: >500 events/second per publisher

## Error Handling

### Graceful Degradation

The publisher is designed to never block application execution:

```python
# Publishing returns False on error, never raises exceptions
success = await publisher.publish_application_log(...)

if not success:
    # Log to file as fallback
    logger.error("Failed to publish log event, falling back to file logging")
```

### Feature Flag

Disable events in environments where Kafka is not available:

```python
publisher = LoggingEventPublisher(enable_events=False)

# All publish calls will be no-ops
await publisher.publish_application_log(...)  # Returns False immediately
```

### Connection Failures

Publisher handles Kafka connection failures gracefully:

```python
try:
    await publisher.start()
except KafkaError:
    # Handle error (e.g., use file logging only)
    logger.warning("Kafka unavailable, using file logging only")
    publisher = LoggingEventPublisher(enable_events=False)
```

## Testing

### Unit Tests

Run unit tests with mocked Kafka:

```bash
pytest agents/tests/test_logging_event_publisher.py -v
```

### Integration Tests

Run integration tests with actual Kafka (requires running Kafka instance):

```bash
pytest agents/tests/test_logging_event_publisher.py -v -m integration
```

## Monitoring

### Kafka Topics

Monitor these topics for logging events:

- `omninode.logging.application.v1` - Application logs
- `omninode.logging.audit.v1` - Audit logs
- `omninode.logging.security.v1` - Security logs

### Consumer Example

```bash
# Consume application logs
kafkacat -b localhost:9092 -t omninode.logging.application.v1 -C -f '%s\n'

# Consume audit logs
kafkacat -b localhost:9092 -t omninode.logging.audit.v1 -C -f '%s\n'

# Consume security logs
kafkacat -b localhost:9092 -t omninode.logging.security.v1 -C -f '%s\n'
```

## Migration Guide

### Migrating from File-Based Logging

**Before**:
```python
import logging

logger = logging.getLogger(__name__)
logger.info("Agent execution completed")
```

**After** (dual logging):
```python
import logging
from agents.lib.logging_event_publisher import publish_application_log

logger = logging.getLogger(__name__)

# File logging (unchanged)
logger.info("Agent execution completed")

# Event logging (new)
await publish_application_log(
    service_name="omniclaude",
    instance_id="omniclaude-1",
    level="INFO",
    logger_name=__name__,
    message="Agent execution completed",
    code="AGENT_EXECUTION_COMPLETED",
)
```

## Best Practices

1. **Use correlation IDs**: Always include correlation_id for request tracing
2. **Use standard log codes**: Follow the recommended log code conventions
3. **Include rich context**: Add relevant context fields for debugging
4. **Use appropriate log levels**: INFO for normal flow, WARN for recoverable issues, ERROR for failures
5. **Partition key policy**: Application logs use service_name, audit/security use tenant_id
6. **Persistent publishers**: For high-frequency logging, use persistent publishers to avoid connection overhead
7. **Graceful degradation**: Always have fallback to file logging if Kafka unavailable

## Troubleshooting

### Events Not Appearing in Kafka

1. Check Kafka connectivity:
   ```bash
   kafkacat -b localhost:9092 -L
   ```

2. Verify feature flag:
   ```python
   publisher = LoggingEventPublisher(enable_events=True)  # Must be True
   ```

3. Check publisher is started:
   ```python
   await publisher.start()  # Must be called before publishing
   ```

### Slow Publishing

1. Use persistent publisher instead of one-off convenience functions
2. Check network latency to Kafka broker
3. Consider batching logs (e.g., batch 100 logs, publish every 1 second)

### High Memory Usage

1. Stop publishers when no longer needed:
   ```python
   await publisher.stop()
   ```

2. Use context manager for automatic cleanup:
   ```python
   async with LoggingEventPublisherContext() as publisher:
       # Automatically stopped on exit
   ```

## See Also

- [Event Bus Integration Guide](../../docs/events/EVENT_BUS_INTEGRATION_GUIDE.md)
- [Event Alignment Plan](../../docs/events/EVENT_ALIGNMENT_PLAN.md) - Phase 2
- [Agent Execution Publisher](./AGENT_EXECUTION_PUBLISHER_USAGE.md)
- [Partition Key Policy](./README_PARTITION_KEY_POLICY.md)

## Support

For questions or issues:
- GitHub Issues: https://github.com/OmniNode-ai/omniclaude/issues
- Internal Slack: #omniclaude-support
