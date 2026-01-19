# Implement Dead Letter Queue for Failed Kafka Messages

## Labels
`priority:critical`, `type:bug`, `component:kafka`, `reliability`

## Description

Failed messages in the Kafka agent action consumer are currently raised but not sent to a dead letter queue, causing permanent message loss.

## Current Behavior

When batch processing fails in `kafka_agent_action_consumer.py`, the exception is logged and re-raised, but the failed messages are lost:

```python
# agents/lib/kafka_agent_action_consumer.py:254-257
except Exception as e:
    logger.error(f"Batch processing failed: {e}", exc_info=True)
    # TODO: Send to dead letter queue
    raise
```

## Impact

- ❌ **Data Loss**: Failed messages are permanently lost
- ❌ **No Retry**: Transient failures cannot be retried
- ❌ **Debugging**: Production issues difficult to investigate
- ❌ **Observability**: No visibility into failure patterns

## Expected Behavior

Failed messages should be:
1. Published to a dead letter queue (DLQ) topic
2. Tagged with error metadata (exception type, message, timestamp)
3. Include retry counter and correlation_id
4. Preserved for manual inspection and replay

## Implementation Plan

### 1. Create DLQ Topic
```bash
# Kafka topic for failed messages
kafka-topics.sh --create --topic agent-actions-dlq \
  --partitions 3 \
  --replication-factor 1 \
  --config retention.ms=604800000  # 7 days
```

### 2. Update Exception Handler
```python
async def _process_batch(self, messages: List[ConsumerRecord]):
    try:
        # ... existing batch processing ...
    except Exception as e:
        logger.error(f"Batch processing failed: {e}", exc_info=True)

        # Send to dead letter queue
        await self._send_to_dlq(messages, e)

        # Don't re-raise to avoid consumer shutdown
        # (configurable behavior)
```

### 3. Implement DLQ Publisher
```python
async def _send_to_dlq(
    self,
    messages: List[ConsumerRecord],
    exception: Exception
):
    """Send failed messages to dead letter queue."""
    for msg in messages:
        dlq_message = {
            "original_topic": msg.topic,
            "original_partition": msg.partition,
            "original_offset": msg.offset,
            "original_key": msg.key,
            "original_value": msg.value,
            "original_timestamp": msg.timestamp,
            "error_type": type(exception).__name__,
            "error_message": str(exception),
            "error_traceback": traceback.format_exc(),
            "retry_count": self._get_retry_count(msg),
            "failed_at": datetime.now(UTC).isoformat(),
        }

        await self._dlq_producer.send_and_wait(
            "agent-actions-dlq",
            value=dlq_message,
            key=msg.key,
        )
```

### 4. Add Configuration
```python
# .env
KAFKA_DLQ_TOPIC=agent-actions-dlq
KAFKA_DLQ_ENABLED=true
KAFKA_MAX_RETRIES=3
KAFKA_RETRY_DELAY_MS=1000
```

### 5. Add DLQ Consumer (Optional)
Create separate service to:
- Monitor DLQ for patterns
- Alert on threshold (e.g., >100 messages/hour)
- Support manual replay of failed messages
- Automatic retry with exponential backoff

## Testing

```python
# test_kafka_agent_action_consumer.py
@pytest.mark.asyncio
async def test_failed_batch_sent_to_dlq(kafka_consumer, dlq_consumer):
    """Test failed messages are sent to DLQ."""
    # Arrange: Create message that will cause processing failure
    bad_message = create_invalid_agent_action()

    # Act: Process batch (should fail)
    await kafka_consumer._process_batch([bad_message])

    # Assert: Message appears in DLQ
    dlq_messages = await dlq_consumer.consume(timeout=5000)
    assert len(dlq_messages) == 1
    assert dlq_messages[0]["error_type"] == "ValidationError"
    assert dlq_messages[0]["original_value"] == bad_message.value
```

## Success Criteria

- [ ] DLQ topic created and configured
- [ ] Failed messages published to DLQ with error metadata
- [ ] Retry counter incremented on each attempt
- [ ] Consumer continues processing after failure (no crash)
- [ ] Tests verify DLQ behavior
- [ ] Monitoring/alerting configured for DLQ depth
- [ ] Documentation updated

## Related Issues

- Part of PR #22 review (Issue #21)
- Related to reliability improvements

## Files to Modify

- `agents/lib/kafka_agent_action_consumer.py` - Add DLQ logic
- `.env.example` - Add DLQ configuration
- `config/settings.py` - Add DLQ settings (if using Pydantic)
- `tests/lib/test_kafka_agent_action_consumer.py` - Add DLQ tests
- `docs/architecture/KAFKA_DLQ.md` - Document DLQ architecture

## Estimated Effort

- Implementation: 4-6 hours
- Testing: 2-3 hours
- Documentation: 1 hour
- **Total**: 1-2 days

## Priority Justification

**CRITICAL** - This is a production data loss issue. Any message processing failure results in permanent loss of agent actions, breaking observability and debugging capabilities.
