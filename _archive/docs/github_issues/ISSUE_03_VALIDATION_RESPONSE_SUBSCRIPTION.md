# Implement Kafka Subscription for Validation Responses

## Labels
`priority:critical`, `type:feature`, `component:validation`, `component:kafka`

## Description

Validation workflow is incomplete - no consumer for validation responses, causing all validations to fail with `OnexError`.

## Current Behavior

`quality_validator.py` always raises an error when waiting for validation responses:

```python
# agents/lib/quality_validator.py:1048-1054
async def wait_for_validation_response(
    self, correlation_id: str, timeout_seconds: int = 30
) -> CodegenValidationResponse:
    # TODO: Implement Kafka subscription and response matching
    self.logger.info(
        f"Waiting for validation response (correlation_id: {correlation_id}, "
        f"timeout: {timeout_seconds}s)"
    )

    raise OnexError("Validation response handling not implemented")
```

## Impact

- ❌ **Validation Workflow Broken**: Always fails with error
- ❌ **Quality Gates Non-Functional**: Cannot complete validation
- ❌ **Blocks ONEX Compliance**: No way to verify code quality
- ❌ **User Experience**: Validation appears broken

## Expected Behavior

Should:
1. Subscribe to `codegen.validation.completed.v1` topic
2. Match responses by correlation_id
3. Implement timeout with asyncio
4. Handle validation failures from `.failed.v1` topic
5. Return structured validation response

## Implementation Plan

### 1. Add Response Storage

```python
# agents/lib/quality_validator.py
class QualityValidator:
    def __init__(self, ...):
        # ... existing init ...
        self._response_futures: Dict[str, asyncio.Future] = {}
        self._response_consumer_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start validation response consumer."""
        if self._response_consumer_task is None:
            self._response_consumer_task = asyncio.create_task(
                self._consume_responses()
            )

    async def stop(self):
        """Stop validation response consumer."""
        if self._response_consumer_task:
            self._response_consumer_task.cancel()
            try:
                await self._response_consumer_task
            except asyncio.CancelledError:
                pass

        await self.close()  # Close producer
```

### 2. Implement Response Consumer

```python
async def _consume_responses(self):
    """Consume validation responses from Kafka."""
    from aiokafka import AIOKafkaConsumer

    consumer = AIOKafkaConsumer(
        "codegen.validation.completed.v1",
        "codegen.validation.failed.v1",
        bootstrap_servers=self._kafka_bootstrap_servers,
        group_id="quality-validator-responses",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    await consumer.start()

    try:
        async for message in consumer:
            correlation_id = message.key.decode("utf-8")
            payload = message.value

            # Find matching future
            if correlation_id in self._response_futures:
                future = self._response_futures.pop(correlation_id)

                if message.topic == "codegen.validation.completed.v1":
                    # Success response
                    response = CodegenValidationResponse(
                        correlation_id=correlation_id,
                        success=True,
                        validation_result=payload["validation_result"],
                    )
                    future.set_result(response)
                else:
                    # Failed response
                    error = payload.get("error", "Validation failed")
                    future.set_exception(OnexError(f"Validation failed: {error}"))
            else:
                self.logger.warning(
                    f"Received validation response for unknown correlation_id: "
                    f"{correlation_id}"
                )
    finally:
        await consumer.stop()
```

### 3. Implement Response Matching

```python
async def wait_for_validation_response(
    self,
    correlation_id: str,
    timeout_seconds: int = 30
) -> CodegenValidationResponse:
    """
    Wait for validation response from Kafka.

    Args:
        correlation_id: Request correlation ID
        timeout_seconds: Timeout in seconds

    Returns:
        Validation response

    Raises:
        OnexError: If timeout or validation failed
    """
    self.logger.info(
        f"Waiting for validation response (correlation_id: {correlation_id}, "
        f"timeout: {timeout_seconds}s)"
    )

    # Create future for this request
    future = asyncio.Future()
    self._response_futures[correlation_id] = future

    try:
        # Wait for response with timeout
        response = await asyncio.wait_for(
            future,
            timeout=timeout_seconds,
        )

        self.logger.info(
            f"Validation response received (correlation_id: {correlation_id})"
        )

        return response

    except asyncio.TimeoutError:
        # Clean up future
        self._response_futures.pop(correlation_id, None)

        raise OnexError(
            f"Validation response timeout after {timeout_seconds}s "
            f"(correlation_id: {correlation_id})"
        )
    except Exception as e:
        # Clean up future
        self._response_futures.pop(correlation_id, None)
        raise
```

### 4. Update Validation Workflow

```python
async def validate_code(
    self,
    code: str,
    contract: Dict[str, Any],
    node_type: str,
    microservice_name: str,
) -> CodegenValidationResponse:
    """
    Complete validation workflow: request + wait for response.

    Returns:
        Validation response with quality score and issues
    """
    # Start response consumer if not running
    await self.start()

    # Send validation request
    request = await self.request_validation(
        code=code,
        contract=contract,
        node_type=node_type,
        microservice_name=microservice_name,
    )

    # Wait for response
    response = await self.wait_for_validation_response(
        correlation_id=request.correlation_id,
        timeout_seconds=30,
    )

    return response
```

## Testing

```python
# tests/lib/test_quality_validator.py
@pytest.mark.asyncio
async def test_validation_response_received(
    quality_validator,
    kafka_producer,
):
    """Test validation response is received and matched."""
    # Arrange
    correlation_id = str(uuid.uuid4())

    # Start response consumer
    await quality_validator.start()

    # Simulate validation response
    response_payload = {
        "correlation_id": correlation_id,
        "validation_result": {
            "quality_score": 0.95,
            "issues": [],
        },
    }

    # Act: Send response to Kafka (simulating validator service)
    await kafka_producer.send_and_wait(
        "codegen.validation.completed.v1",
        value=json.dumps(response_payload).encode(),
        key=correlation_id.encode(),
    )

    # Act: Wait for response
    response = await quality_validator.wait_for_validation_response(
        correlation_id=correlation_id,
        timeout_seconds=5,
    )

    # Assert
    assert response.success is True
    assert response.correlation_id == correlation_id
    assert response.validation_result["quality_score"] == 0.95

@pytest.mark.asyncio
async def test_validation_timeout():
    """Test timeout when no response received."""
    quality_validator = QualityValidator()
    await quality_validator.start()

    # Wait for non-existent response
    with pytest.raises(OnexError, match="timeout"):
        await quality_validator.wait_for_validation_response(
            correlation_id="non-existent",
            timeout_seconds=1,
        )
```

## Success Criteria

- [ ] Kafka consumer initialized for response topics
- [ ] Responses matched by correlation_id
- [ ] Timeout implemented with asyncio.wait_for()
- [ ] Failed validations handled from `.failed.v1` topic
- [ ] Orphaned futures cleaned up on timeout
- [ ] Consumer started/stopped with validator lifecycle
- [ ] Tests verify response matching and timeout
- [ ] Documentation updated

## Related Issues

- Part of PR #22 review (Issue #21)
- Depends on: Issue #2 (Validation request publishing)
- Completes: ONEX validation workflow

## Files to Modify

- `agents/lib/quality_validator.py` - Add response consumer
- `tests/lib/test_quality_validator.py` - Add response tests
- `docs/architecture/VALIDATION_WORKFLOW.md` - Document workflow

## Estimated Effort

- Implementation: 4-6 hours
- Testing: 3-4 hours
- Documentation: 1-2 hours
- **Total**: 1-2 days

## Priority Justification

**CRITICAL** - Completes the validation workflow. Without response handling, validation requests are sent but never processed, making the entire quality system non-functional.

## Notes

- Must be implemented AFTER Issue #2 (request publishing)
- Requires validation consumer service to be running
- Consider connection pooling for high-volume validation
- Add metrics for validation latency and success rate
