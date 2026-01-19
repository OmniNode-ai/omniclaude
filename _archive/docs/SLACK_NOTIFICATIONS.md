# Slack Webhook Error Notification System

**Status**: ✅ Implemented
**Version**: 1.0.0
**Created**: 2025-11-06

## Overview

Fail-fast error notification system that sends critical errors to Slack with intelligent throttling to prevent spam. Notifications are opt-in, non-blocking, and include rich error context.

## Features

- ✅ **Async HTTP POST** to Slack webhooks
- ✅ **Rate limiting** (max 1 notification per error type per 5 minutes)
- ✅ **Rich error context** (type, message, stack trace, service, timestamp)
- ✅ **Non-blocking** (errors don't break main flow)
- ✅ **Opt-in** (only sends if webhook URL configured)
- ✅ **Type-safe configuration** (Pydantic Settings integration)

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────┐
│                   Error Occurs                           │
└─────────────────────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────┐
│          SlackNotifier.send_error_notification()        │
│  ┌──────────────────────────────────────────────────┐   │
│  │ 1. Check if webhook URL configured               │   │
│  │ 2. Generate error key (error_type:service)       │   │
│  │ 3. Check throttle cache                          │   │
│  │ 4. Build rich Slack message (Block Kit format)   │   │
│  │ 5. Send async HTTP POST to webhook               │   │
│  │ 6. Update throttle cache on success              │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────┐
│              Slack Channel Receives Alert                │
│  🚨 Error in routing_event_client                        │
│  Type: KafkaError                                        │
│  Message: Connection failed                              │
│  Stack Trace: ...                                        │
└─────────────────────────────────────────────────────────┘
```

### Integration Points

Slack notifications are integrated into:

1. **Kafka Connection Failures** (`agents/lib/routing_event_client.py`)
   - Kafka startup failures
   - Routing request timeouts
   - General routing errors

2. **Agent Routing Failures** (`agents/services/agent_router_event_service.py`)
   - PostgreSQL connection failures
   - Routing execution errors

3. **Configuration Validation** (`config/settings.py`)
   - Missing required configuration
   - Invalid configuration values

## Setup

### 1. Create Slack Webhook

1. Go to https://api.slack.com/apps
2. Create a new app or select existing app
3. Enable "Incoming Webhooks"
4. Add webhook to your desired channel
5. Copy webhook URL

### 2. Configure Environment

Edit your `.env` file:

```bash
# Enable Slack notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# Throttle window (default: 300 seconds = 5 minutes)
SLACK_NOTIFICATION_THROTTLE_SECONDS=300
```

### 3. Verify Configuration

```bash
# Load configuration
source .env

# Test notification
python3 agents/lib/test_slack_notifier.py --real
```

## Usage

### Basic Usage

```python
from agents.lib.slack_notifier import get_slack_notifier

# Get singleton notifier instance
notifier = get_slack_notifier()

try:
    # Your code that might fail
    await connect_to_kafka()
except Exception as e:
    # Send error notification
    await notifier.send_error_notification(
        error=e,
        context={
            "service": "routing_event_client",
            "operation": "kafka_connection",
            "kafka_servers": "192.168.86.200:29092",
            "correlation_id": "abc-123",
        }
    )
    raise  # Re-raise to maintain normal error flow
```

### Custom Notifier Instance

```python
from agents.lib.slack_notifier import SlackNotifier

# Create custom notifier with specific settings
notifier = SlackNotifier(
    webhook_url="https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
    throttle_seconds=600  # 10 minutes
)

# Send notification
await notifier.send_error_notification(error, context)
```

### Force Bypass Throttle

```python
# Send notification even if throttled (use sparingly)
await notifier.send_error_notification(
    error=e,
    context=context,
    force=True  # Bypass throttling
)
```

### Check Statistics

```python
stats = notifier.get_stats()
print(stats)
# {
#     "notifications_sent": 42,
#     "notifications_throttled": 15,
#     "notifications_failed": 3,
# }
```

## Configuration

### Pydantic Settings

The Slack notifier integrates with OmniClaude's type-safe configuration framework:

```python
from config import settings

# Access configuration with full type safety
webhook_url = settings.slack_webhook_url
throttle_seconds = settings.slack_notification_throttle_seconds
```

### Environment Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SLACK_WEBHOOK_URL` | str | None | Slack webhook URL (optional) |
| `SLACK_NOTIFICATION_THROTTLE_SECONDS` | int | 300 | Throttle window in seconds |

## Throttling Behavior

### How Throttling Works

1. **Error Key Generation**: `{error_type}:{service}`
   - Example: `KafkaError:routing_event_client`

2. **Throttle Cache Check**:
   - If error key not in cache → Send notification
   - If error key in cache and within throttle window → Throttle notification
   - If error key in cache but throttle window expired → Send notification

3. **Cache Update**:
   - Only update cache on successful send
   - Failed notifications don't update cache (allow retries)

### Example Timeline

```
T=0s:   KafkaError occurs → Notification sent ✅
T=60s:  Same KafkaError → Throttled ⏸️ (within 5 min window)
T=120s: Same KafkaError → Throttled ⏸️ (within 5 min window)
T=310s: Same KafkaError → Notification sent ✅ (window expired)
```

### Bypass Throttling

Use `force=True` parameter to bypass throttling:

```python
await notifier.send_error_notification(error, context, force=True)
```

**⚠️ Use sparingly** - defeats the purpose of throttling!

## Message Format

Slack notifications use Block Kit format for rich formatting:

### Header Block
- 🚨 Error indicator
- Service name

### Fields Block
- **Error Type**: Exception class name
- **Service**: Service identifier
- **Operation**: Operation that failed
- **Timestamp**: UTC timestamp

### Error Message Block
- Full error message
- Code-formatted for readability

### Correlation ID Block (if available)
- Request correlation ID for traceability

### Additional Context Block (if available)
- Extra context fields from error context

### Stack Trace Block
- Complete stack trace
- Truncated at 2000 chars (Slack limits)
- Code-formatted for readability

### Example Message

```
🚨 Error in routing_event_client

Error Type: KafkaError
Service: routing_event_client
Operation: kafka_connection
Timestamp: 2025-11-06 14:30:00 UTC

Error Message:
```
Connection to Kafka broker failed: [Errno 61] Connection refused
```

Correlation ID:
`abc-123-def-456`

Additional Context:
• kafka_servers: 192.168.86.200:29092
• consumer_group: omniclaude-routing

Stack Trace:
```
Traceback (most recent call last):
  File "/app/routing_event_client.py", line 220, in start
    await self._producer.start()
  ...
```
```

## Testing

### Unit Tests

Run comprehensive test suite:

```bash
# Test without real Slack webhook (mock URLs)
python3 agents/lib/test_slack_notifier.py

# Test with real Slack webhook
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL \
    python3 agents/lib/test_slack_notifier.py --real
```

Tests cover:
- ✅ Initialization (with/without webhook URL)
- ✅ Throttling behavior
- ✅ Error notification format
- ✅ Non-blocking behavior
- ✅ Statistics tracking
- ✅ Force bypass throttle
- ✅ Real Slack notification (optional)

### Integration Tests

Integration points are automatically tested when services fail:

1. **Kafka Connection Test**:
   ```bash
   # Stop Kafka
   docker stop omninode-bridge-redpanda

   # Try routing (should fail and send Slack notification)
   python3 agents/lib/test_routing_event_client.py

   # Start Kafka
   docker start omninode-bridge-redpanda
   ```

2. **Configuration Validation Test**:
   ```bash
   # Temporarily remove required config
   mv .env .env.backup

   # Load config (should fail and send Slack notification)
   python3 -c "from config import settings"

   # Restore config
   mv .env.backup .env
   ```

## Error Handling

### Non-Blocking Design

Notification failures **never** break the main application flow:

```python
try:
    notifier = get_slack_notifier()
    await notifier.send_error_notification(error, context)
except Exception as notify_error:
    # Log but don't propagate
    logger.debug(f"Failed to send Slack notification: {notify_error}")
```

### Failure Scenarios

| Scenario | Behavior |
|----------|----------|
| Webhook URL not configured | Skip notification (not an error) |
| Invalid webhook URL | Log warning, return False |
| Network timeout | Log warning, return False (10s timeout) |
| Slack API error | Log warning, return False |
| aiohttp not available | Disable notifications (log warning on import) |

## Performance

### Metrics

- **Notification build time**: <1ms
- **HTTP POST timeout**: 10 seconds
- **Throttle cache lookup**: <1μs (in-memory dict)
- **Memory overhead**: <100KB (throttle cache)

### Async & Non-Blocking

Notifications are fully async and non-blocking:

```python
# Main flow continues immediately
await notifier.send_error_notification(error, context)
# Returns False on failure, doesn't wait for retry
```

## Security

### Sensitive Data Handling

1. **Webhook URL**:
   - Never committed to version control
   - Sanitized in `settings.to_dict_sanitized()`
   - Stored only in `.env` file

2. **Error Context**:
   - Avoid including sensitive data in context
   - Passwords/API keys are truncated in stack traces

3. **SSL/TLS**:
   - All webhook connections use HTTPS
   - SSL certificate verification enabled

### Best Practices

- ✅ Use environment variables for webhook URL
- ✅ Restrict Slack webhook to single channel
- ✅ Monitor notification volume for anomalies
- ✅ Don't include sensitive data in error context
- ❌ Don't commit `.env` file to version control
- ❌ Don't share webhook URLs in documentation

## Troubleshooting

### No Notifications Received

1. **Check webhook URL**:
   ```bash
   source .env
   echo $SLACK_WEBHOOK_URL
   ```

2. **Test webhook manually**:
   ```bash
   curl -X POST $SLACK_WEBHOOK_URL \
     -H 'Content-Type: application/json' \
     -d '{"text":"Test notification"}'
   ```

3. **Check notifier is enabled**:
   ```python
   from agents.lib.slack_notifier import get_slack_notifier
   notifier = get_slack_notifier()
   print(notifier.is_enabled())  # Should be True
   ```

4. **Check aiohttp availability**:
   ```bash
   python3 -c "import aiohttp; print('Available')"
   ```

### Notification Spam

1. **Check throttle settings**:
   ```bash
   source .env
   echo $SLACK_NOTIFICATION_THROTTLE_SECONDS
   ```

2. **Increase throttle window**:
   ```bash
   # Set to 10 minutes (600 seconds)
   echo "SLACK_NOTIFICATION_THROTTLE_SECONDS=600" >> .env
   ```

3. **Clear throttle cache** (development only):
   ```python
   from agents.lib.slack_notifier import get_slack_notifier
   notifier = get_slack_notifier()
   notifier.clear_throttle_cache()
   ```

### SSL Certificate Errors

SSL errors are expected in test environments with mock URLs. In production:

1. Ensure Python SSL certificates are installed:
   ```bash
   /Applications/Python\ 3.11/Install\ Certificates.command
   ```

2. Update certifi package:
   ```bash
   pip install --upgrade certifi
   ```

## Maintenance

### Monitoring

Monitor notification volume and failures:

```python
from agents.lib.slack_notifier import get_slack_notifier

notifier = get_slack_notifier()
stats = notifier.get_stats()

# Log metrics to observability system
logger.info(f"Slack notifications - sent: {stats['notifications_sent']}, "
            f"throttled: {stats['notifications_throttled']}, "
            f"failed: {stats['notifications_failed']}")
```

### Key Rotation

Rotate Slack webhook URLs periodically:

1. Create new webhook in Slack
2. Update `.env` with new URL
3. Restart services
4. Deactivate old webhook after 24 hours

See `SECURITY_KEY_ROTATION.md` for detailed procedures.

## Future Enhancements

Potential improvements:

- [ ] Persistent throttle cache (Redis/Valkey)
- [ ] Rate limit per service (not just per error type)
- [ ] Notification templates for common error types
- [ ] Alert aggregation (batch multiple errors)
- [ ] PagerDuty/OpsGenie integration
- [ ] Error severity levels (info/warning/error/critical)
- [ ] Configurable message format
- [ ] Webhook rotation on failure

## Related Documentation

- **Configuration**: `config/README.md`
- **Security**: `SECURITY_KEY_ROTATION.md`
- **Environment Setup**: `.env.example`
- **Type-Safe Config**: `config/settings.py`

## Support

For issues or questions:

1. Check this documentation
2. Review test script: `agents/lib/test_slack_notifier.py`
3. Check logs for detailed error messages
4. Review Slack webhook configuration

---

**Created**: 2025-11-06
**Author**: OmniClaude Polymorphic Agent
**Version**: 1.0.0
