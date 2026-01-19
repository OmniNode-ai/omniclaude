# Implement Kafka Publishing for Code Validation Requests

## Labels
`priority:critical`, `type:feature`, `component:validation`, `component:kafka`

## Description

Code validation requests are prepared but never published to Kafka, leaving the validation service non-functional.

## Current Behavior

`quality_validator.py` prepares validation requests but doesn't publish them:

```python
# agents/lib/quality_validator.py:1014-1029
async def request_validation(
    self, code: str, contract: Dict[str, Any], ...
) -> CodegenValidationRequest:
    # TODO: Implement Kafka publishing
    request = CodegenValidationRequest(
        correlation_id=correlation_id,
        payload={"code": code, "contract": contract, ...},
    )

    self.logger.info(
        f"Validation request prepared for {microservice_name} "
        f"(correlation_id: {correlation_id})"
    )

    # Missing: Kafka publish logic
    return request
```

## Impact

- ❌ **Validation Broken**: Code validation service is non-functional
- ❌ **Quality Gates Bypassed**: ONEX compliance checks not running
- ❌ **Silent Failure**: Appears to work but does nothing
- ❌ **Technical Debt**: Incomplete feature in production code

## Expected Behavior

Validation requests should be:
1. Published to Kafka topic `codegen.validation.requested.v1`
2. Include correlation_id for response matching
3. Include timeout configuration
4. Return request object for tracking

## Implementation Plan

### 1. Create Kafka Topics

```bash
# Request topic
kafka-topics.sh --create --topic codegen.validation.requested.v1 \
  --partitions 3 --replication-factor 1

# Response topics
kafka-topics.sh --create --topic codegen.validation.completed.v1 \
  --partitions 3 --replication-factor 1

kafka-topics.sh --create --topic codegen.validation.failed.v1 \
  --partitions 3 --replication-factor 1
```

### 2. Initialize Kafka Producer

```python
# agents/lib/quality_validator.py
class QualityValidator:
    def __init__(self, ...):
        self.logger = logging.getLogger(__name__)
        self._producer = None
        self._kafka_bootstrap_servers = os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS",
            "omninode-bridge-redpanda:9092"
        )

    async def _ensure_producer(self):
        """Initialize Kafka producer if not already initialized."""
        if self._producer is None:
            from aiokafka import AIOKafkaProducer
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._kafka_bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            await self._producer.start()

    async def close(self):
        """Close Kafka producer."""
        if self._producer:
            await self._producer.stop()
```

### 3. Implement Publishing Logic

```python
async def request_validation(
    self,
    code: str,
    contract: Dict[str, Any],
    node_type: str,
    microservice_name: str,
    correlation_id: Optional[str] = None,
    timeout_seconds: int = 30,
) -> CodegenValidationRequest:
    """
    Request code validation via Kafka.

    Returns:
        Validation request event
    """
    # Generate correlation ID if not provided
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    # Prepare request
    request = CodegenValidationRequest(
        correlation_id=correlation_id,
        payload={
            "code": code,
            "contract": contract,
            "node_type": node_type,
            "microservice_name": microservice_name,
        },
    )

    # Ensure producer is initialized
    await self._ensure_producer()

    # Publish to Kafka
    request_envelope = {
        "correlation_id": correlation_id,
        "payload": request.payload,
        "timeout_seconds": timeout_seconds,
        "requested_at": datetime.now(UTC).isoformat(),
    }

    try:
        await self._producer.send_and_wait(
            "codegen.validation.requested.v1",
            value=request_envelope,
            key=correlation_id.encode("utf-8"),
        )

        self.logger.info(
            f"Validation request published for {microservice_name} "
            f"(correlation_id: {correlation_id})"
        )
    except Exception as e:
        self.logger.error(
            f"Failed to publish validation request: {e}",
            exc_info=True,
        )
        raise OnexError(f"Validation request publishing failed: {e}")

    return request
```

### 4. Add Configuration

```python
# .env
KAFKA_VALIDATION_REQUEST_TOPIC=codegen.validation.requested.v1
KAFKA_VALIDATION_COMPLETED_TOPIC=codegen.validation.completed.v1
KAFKA_VALIDATION_FAILED_TOPIC=codegen.validation.failed.v1
KAFKA_VALIDATION_TIMEOUT_SECONDS=30
```

### 5. Create Validation Consumer Service

Create new service `agents/services/validation_consumer.py`:
- Consume from `codegen.validation.requested.v1`
- Perform validation using QualityValidator methods
- Publish results to `codegen.validation.completed.v1` or `.failed.v1`
- Match responses by correlation_id

## Testing

```python
# tests/lib/test_quality_validator.py
@pytest.mark.asyncio
async def test_validation_request_published(
    quality_validator,
    kafka_consumer,
):
    """Test validation request is published to Kafka."""
    # Arrange
    code = "async def execute_effect(self, contract): pass"
    contract = {"type": "effect", "methods": ["execute_effect"]}

    # Act
    request = await quality_validator.request_validation(
        code=code,
        contract=contract,
        node_type="EFFECT",
        microservice_name="test_service",
    )

    # Assert: Message published to Kafka
    messages = await kafka_consumer.getmany(timeout_ms=5000)
    assert len(messages) == 1

    message = messages[0]
    assert message.topic == "codegen.validation.requested.v1"
    assert message.key.decode() == request.correlation_id

    payload = json.loads(message.value.decode())
    assert payload["correlation_id"] == request.correlation_id
    assert payload["payload"]["node_type"] == "EFFECT"
```

## Success Criteria

- [ ] Kafka producer initialized in QualityValidator
- [ ] Validation requests published to Kafka
- [ ] Correlation ID included in message key
- [ ] Timeout configuration supported
- [ ] Error handling for publish failures
- [ ] Tests verify publishing behavior
- [ ] Producer cleanup on shutdown
- [ ] Documentation updated

## Related Issues

- Part of PR #22 review (Issue #21)
- Blocks: Issue #3 (Validation response subscription)
- Blocks: ONEX compliance validation workflow

## Files to Modify

- `agents/lib/quality_validator.py` - Add Kafka producer
- `.env.example` - Add validation topics
- `config/settings.py` - Add validation settings
- `tests/lib/test_quality_validator.py` - Add publishing tests
- `agents/services/validation_consumer.py` - Create new service
- `deployment/docker-compose.yml` - Add validation-consumer service

## Estimated Effort

- Implementation: 4-6 hours
- Consumer service: 4-6 hours
- Testing: 3-4 hours
- Documentation: 1-2 hours
- **Total**: 2-3 days

## Priority Justification

**CRITICAL** - Code validation is a core quality feature. Without Kafka publishing, all validation is bypassed, allowing non-compliant code into production.
