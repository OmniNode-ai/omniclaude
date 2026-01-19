# Event Validation Utilities - Usage Guide

**Location**: `agents/lib/event_validation.py`
**Test Suite**: `agents/lib/test_event_validation.py`
**Created**: 2025-11-13

## Overview

Event validation utilities for omniclaude event bus integration. Validates events against standards defined in:
- `services/routing_adapter/schemas/model_routing_event_envelope.py`
- `services/routing_adapter/schemas/topics.py`
- `docs/UNIFIED_EVENT_INFRASTRUCTURE.md`

## Quick Start

```python
from agents.lib.event_validation import validate_full_event

# Validate a complete event envelope
envelope = {
    "event_id": "550e8400-e29b-41d4-a716-446655440000",
    "event_type": "AGENT_ROUTING_REQUESTED",
    "correlation_id": "abc-123-def-456",
    "timestamp": "2025-10-30T14:30:00Z",
    "service": "polymorphic-agent",
    "payload": {"user_request": "test"},
    "version": "v1"
}

result = validate_full_event(envelope)

if not result.is_valid:
    print("Validation errors:")
    for error in result.errors:
        print(f"  - {error}")
else:
    print("Event is valid!")
```

## Validation Functions

### 1. Envelope Structure Validation

```python
from agents.lib.event_validation import validate_event_envelope

envelope = {
    "event_id": str(uuid4()),
    "event_type": "AGENT_ROUTING_REQUESTED",
    "correlation_id": str(uuid4()),
    "timestamp": datetime.now(UTC).isoformat(),
    "service": "test-service",
    "payload": {},
    "version": "v1",  # Optional but recommended
}

result = validate_event_envelope(envelope)
```

**Required Fields**:
- `event_id` (string, UUID format)
- `event_type` (string)
- `correlation_id` (string, UUID format)
- `timestamp` (string, ISO 8601 format)
- `service` (string, min_length=1)
- `payload` (dict or object, cannot be None)

**Recommended Fields**:
- `version` (string, default: "v1")
- `causation_id` (string, UUID format)

### 2. UUID Field Validation

```python
from agents.lib.event_validation import validate_uuid_field

# Valid UUID
result = validate_uuid_field("550e8400-e29b-41d4-a716-446655440000", "event_id")
assert result.is_valid

# Invalid UUID
result = validate_uuid_field("not-a-uuid", "event_id")
assert not result.is_valid
```

### 3. Timestamp Validation

```python
from agents.lib.event_validation import validate_timestamp_field

# Valid timestamps
validate_timestamp_field("2025-10-30T14:30:00Z")  # UTC with Z
validate_timestamp_field("2025-10-30T14:30:00+00:00")  # UTC with offset
validate_timestamp_field("2025-10-30T14:30:00.123456Z")  # With microseconds

# Invalid timestamp
result = validate_timestamp_field("2025-10-30 14:30:00")
assert not result.is_valid
```

### 4. Event Type Naming Conventions

```python
from agents.lib.event_validation import validate_event_naming

# Topic format (strict=True)
# Format: {namespace}.{domain}.{entity}.{action}.v{version}
result = validate_event_naming("agent.routing.requested.v1", strict=True)
assert result.is_valid

# Envelope format (strict=False)
# Format: {PREFIX}_{ENTITY}_{ACTION}
result = validate_event_naming("AGENT_ROUTING_REQUESTED", strict=False)
assert result.is_valid

# Invalid - uppercase in topic format
result = validate_event_naming("Agent.Routing.Requested.v1", strict=True)
assert not result.is_valid

# Invalid - lowercase in envelope format
result = validate_event_naming("agent_routing_requested", strict=False)
assert not result.is_valid
```

### 5. Schema Reference Validation

```python
from agents.lib.event_validation import validate_schema_reference

# Valid schema reference
result = validate_schema_reference("registry://omninode/agent/routing_requested/v1")
assert result.is_valid

# Invalid - wrong protocol
result = validate_schema_reference("http://omninode/agent/routing_requested/v1")
assert not result.is_valid
```

### 6. Partition Key Policy Validation

```python
from agents.lib.event_validation import validate_partition_key_policy

envelope = {"correlation_id": "abc-123"}

# Matching partition key (best practice)
result = validate_partition_key_policy(
    "AGENT_ROUTING_REQUESTED",
    "abc-123",
    envelope
)
assert result.is_valid
assert len(result.warnings) == 0

# Mismatched partition key (warning)
result = validate_partition_key_policy(
    "AGENT_ROUTING_REQUESTED",
    "xyz-789",
    envelope
)
assert result.is_valid  # Warning only, not error
assert len(result.warnings) > 0
```

### 7. Full Event Validation

```python
from agents.lib.event_validation import validate_full_event

envelope = {
    "event_id": str(uuid4()),
    "event_type": "AGENT_ROUTING_REQUESTED",
    "correlation_id": str(uuid4()),
    "timestamp": datetime.now(UTC).isoformat(),
    "service": "polymorphic-agent",
    "payload": {"user_request": "test"},
    "version": "v1",
}

# Full validation with all checks
result = validate_full_event(
    envelope,
    validate_uuid_fields=True,  # Validate UUID format
    validate_naming=True,       # Validate event type naming
    strict_naming=False,        # Use envelope format (not topic format)
)

if not result.is_valid:
    print(f"Errors: {result.errors}")
    print(f"Warnings: {result.warnings}")
```

### 8. Batch Validation

```python
from agents.lib.event_validation import (
    validate_event_batch,
    get_validation_summary,
)

envelopes = [
    {"event_id": str(uuid4()), "event_type": "...", ...},
    {"event_id": str(uuid4()), "event_type": "...", ...},
    {"event_id": "invalid-uuid", ...},  # This will fail
]

# Validate all events
results = validate_event_batch(envelopes, validate_uuid_fields=True)

# Generate summary
summary = get_validation_summary(results)
print(f"Valid: {summary['valid']}/{summary['total']}")
print(f"Total errors: {summary['total_errors']}")
print(f"Total warnings: {summary['total_warnings']}")

# Check individual results
for idx, result in results.items():
    if not result.is_valid:
        print(f"Event {idx} failed validation:")
        for error in result.errors:
            print(f"  - {error}")
```

## Integration Examples

### Before Publishing to Kafka

```python
from aiokafka import AIOKafkaProducer
from agents.lib.event_validation import validate_full_event

async def publish_routing_request(envelope: dict):
    # Validate before publishing
    result = validate_full_event(envelope, strict_naming=False)

    if not result.is_valid:
        raise ValueError(f"Invalid event envelope: {result.errors}")

    # Warnings are non-critical but should be logged
    if result.warnings:
        logger.warning(f"Event validation warnings: {result.warnings}")

    # Publish to Kafka
    producer = AIOKafkaProducer(...)
    await producer.send("agent.routing.requested.v1", envelope)
```

### In Event Consumers

```python
from aiokafka import AIOKafkaConsumer
from agents.lib.event_validation import validate_event_envelope

async def consume_routing_events():
    consumer = AIOKafkaConsumer("agent.routing.requested.v1", ...)

    async for msg in consumer:
        envelope = msg.value

        # Validate received event
        result = validate_event_envelope(envelope)

        if not result.is_valid:
            logger.error(f"Received invalid event: {result.errors}")
            # Send to dead letter queue or skip
            continue

        # Process valid event
        await process_routing_request(envelope)
```

### Pre-Flight Validation in Services

```python
from agents.lib.event_validation import validate_event_batch

async def validate_batch_before_publish(envelopes: list[dict]):
    """Validate batch of events before publishing."""
    results = validate_event_batch(envelopes)
    summary = get_validation_summary(results)

    if summary['invalid'] > 0:
        # Log detailed errors
        for idx, result in results.items():
            if not result.is_valid:
                logger.error(f"Event {idx} validation failed: {result.errors}")

        raise ValueError(
            f"Batch validation failed: {summary['invalid']}/{summary['total']} "
            f"events invalid, {summary['total_errors']} total errors"
        )

    logger.info(f"Batch validation passed: {summary['valid']} events valid")
    return True
```

### Unit Testing Event Payloads

```python
import pytest
from agents.lib.event_validation import validate_full_event

def test_routing_request_event_valid():
    """Test routing request event structure."""
    envelope = create_routing_request_envelope(...)

    result = validate_full_event(envelope)

    assert result.is_valid, f"Validation errors: {result.errors}"
    assert len(result.warnings) == 0, f"Unexpected warnings: {result.warnings}"
```

## Validation Options

### Skip Specific Validations

```python
# Skip UUID validation (if using custom ID format)
result = validate_full_event(envelope, validate_uuid_fields=False)

# Skip naming validation (if using custom event types)
result = validate_full_event(envelope, validate_naming=False)

# Use topic format instead of envelope format
result = validate_full_event(envelope, strict_naming=True)
```

### Custom Validation Pipelines

```python
from agents.lib.event_validation import (
    validate_event_envelope,
    validate_uuid_field,
    validate_timestamp_field,
)

def custom_event_validation(envelope: dict) -> ValidationResult:
    """Custom validation with specific requirements."""
    result = ValidationResult()

    # 1. Basic structure
    envelope_result = validate_event_envelope(envelope)
    result.merge(envelope_result)

    if not envelope_result.is_valid:
        return result

    # 2. Custom business rules
    if envelope['service'] not in ALLOWED_SERVICES:
        result.add_error(f"Service {envelope['service']} not allowed")

    if 'user_id' in envelope['payload']:
        # Custom validation for user_id
        user_id = envelope['payload']['user_id']
        if not is_valid_user_id(user_id):
            result.add_error(f"Invalid user_id: {user_id}")

    return result
```

## ValidationResult Model

```python
class ValidationResult:
    is_valid: bool          # Overall validation status
    errors: List[str]       # List of error messages
    warnings: List[str]     # List of warning messages

    def add_error(message: str) -> None
    def add_warning(message: str) -> None
    def merge(other: ValidationResult) -> None
```

## Best Practices

1. **Always validate before publishing**: Catch errors early before events enter Kafka
2. **Log warnings**: Warnings indicate non-critical issues that should be fixed
3. **Use batch validation**: Validate multiple events efficiently
4. **Custom validation**: Extend base validation with business rules
5. **Test event schemas**: Use validation in unit tests to ensure schema compliance
6. **Monitor validation failures**: Track validation errors in production

## Error Handling

```python
from agents.lib.event_validation import validate_full_event

def safe_event_publish(envelope: dict):
    try:
        result = validate_full_event(envelope)

        if not result.is_valid:
            # Log validation errors
            logger.error(
                f"Event validation failed",
                extra={
                    "event_type": envelope.get("event_type"),
                    "errors": result.errors,
                    "warnings": result.warnings,
                }
            )
            return False

        # Publish event
        return True

    except Exception as e:
        logger.exception(f"Validation error: {e}")
        return False
```

## Testing

```bash
# Run all validation tests
pytest agents/lib/test_event_validation.py -v

# Run specific test class
pytest agents/lib/test_event_validation.py::TestValidateEventEnvelope -v

# Run with coverage
pytest agents/lib/test_event_validation.py --cov=agents.lib.event_validation
```

## Standards Reference

- **Envelope Structure**: `services/routing_adapter/schemas/model_routing_event_envelope.py`
- **Topic Naming**: `services/routing_adapter/schemas/topics.py`
- **Event Infrastructure**: `docs/UNIFIED_EVENT_INFRASTRUCTURE.md`
- **Routing Events**: `agents/lib/routing_event_client.py`
- **Database Events**: `agents/lib/database_event_client.py`

## See Also

- [Routing Event Client Usage](ROUTING_EVENT_CLIENT_USAGE.md)
- [Unified Event Infrastructure](../../docs/UNIFIED_EVENT_INFRASTRUCTURE.md)
- [Model Routing Event Envelope](../../services/routing_adapter/schemas/model_routing_event_envelope.py)

---

**Last Updated**: 2025-11-13
**Version**: 1.0.0
**Test Coverage**: 51 tests, 100% passing
