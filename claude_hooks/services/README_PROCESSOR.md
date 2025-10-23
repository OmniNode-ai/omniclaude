# Hook Event Processor Service

Background service for processing unprocessed hook events from the database.

**Correlation ID**: `fe9bbe61-39d7-4124-b6ec-d61de1e0ee41-P0`

## Overview

The Hook Event Processor is a production-ready background service that:

- ✅ Polls the `hook_events` table for unprocessed events
- ✅ Routes events to appropriate handlers based on `source` and `action`
- ✅ Implements retry mechanism with exponential backoff
- ✅ Tracks errors and processing metrics
- ✅ Auto-restarts on failure via systemd
- ✅ Gracefully handles shutdown signals

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ HookEventProcessor                                          │
│                                                             │
│  ┌───────────────┐    ┌──────────────┐    ┌─────────────┐ │
│  │ Polling Loop  │───▶│ Event Router │───▶│  Handlers   │ │
│  │  (1s interval)│    │              │    │             │ │
│  └───────────────┘    └──────────────┘    └─────────────┘ │
│         │                     │                   │        │
│         ▼                     ▼                   ▼        │
│  ┌───────────────────────────────────────────────────────┐ │
│  │           Database (hook_events table)                │ │
│  │  • Fetch unprocessed (FOR UPDATE SKIP LOCKED)         │ │
│  │  • Mark processed or increment retry_count            │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. HookEventProcessor (`hook_event_processor.py`)

Main service class that:
- Polls database for unprocessed events
- Processes events in batches (default: 100)
- Handles graceful shutdown (SIGTERM/SIGINT)
- Tracks metrics and performance

**Key Methods**:
- `fetch_unprocessed_events()` - Query database with `FOR UPDATE SKIP LOCKED`
- `process_event()` - Route event to handler
- `mark_event_processed()` - Update database with success/failure
- `run()` - Main service loop

### 2. EventHandlerRegistry (`event_handlers.py`)

Handler routing system with:
- Exact match: `(source, action)` → handler
- Wildcard match: `(source, *)` → handler
- Global wildcard: `(*, *)` → default handler

**Default Handlers**:
- `PreToolUse/tool_invocation` → `handle_pretooluse_invocation()`
- `PostToolUse/tool_completion` → `handle_posttooluse_completion()`
- `UserPromptSubmit/prompt_submitted` → `handle_userprompt_submitted()`
- `Stop/session_stopped` → `handle_session_stopped()`
- `SessionEnd/session_ended` → `handle_session_ended()`
- `*/unknown` → `handle_unknown_event()`

### 3. Systemd Service (`hook-event-processor.service`)

Production deployment with:
- Auto-restart on failure (max 5 retries in 5 minutes)
- Resource limits (512MB RAM, 50% CPU)
- Security hardening (PrivateTmp, ProtectSystem)
- Graceful shutdown (30s timeout)

## Installation

### 1. Prerequisites

```bash
# Ensure PostgreSQL is running
psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "SELECT COUNT(*) FROM hook_events"

# Ensure Python dependencies are installed
cd .
poetry install
```

### 2. Environment Configuration

Create/verify `.env` file:

```bash
# Required for database connection
DB_PASSWORD=omninode-bridge-postgres-dev-2024

# Optional configuration
POLL_INTERVAL=1.0        # Polling interval in seconds
BATCH_SIZE=100           # Events per batch
MAX_RETRY_COUNT=3        # Maximum retry attempts
```

### 3. Manual Testing

Test the processor manually before installing as a service:

```bash
cd claude_hooks/services
python3 hook_event_processor.py
```

**Expected Output**:
```
2025-10-19 18:00:00 [INFO] HookEventProcessor: HookEventProcessor initialized
2025-10-19 18:00:00 [INFO] EventHandlerRegistry: Registered 6 default event handlers
2025-10-19 18:00:00 [INFO] HookEventProcessor: 🚀 Starting Hook Event Processor Service
2025-10-19 18:00:00 [INFO] HookEventProcessor: Processing batch of 100 events
2025-10-19 18:00:01 [INFO] handle_posttooluse_completion: PostToolUse event: tool=Bash, file=None, auto_fix=False
...
```

### 4. Install Systemd Service (Production)

**Option 1: System-wide installation** (requires sudo):

```bash
# Copy service file
sudo cp hook-event-processor.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable hook-event-processor

# Start service
sudo systemctl start hook-event-processor

# Check status
sudo systemctl status hook-event-processor
```

**Option 2: User-level installation** (recommended for development):

```bash
# Create user systemd directory
mkdir -p ~/.config/systemd/user/

# Copy service file
cp hook-event-processor.service ~/.config/systemd/user/

# Reload user systemd
systemctl --user daemon-reload

# Enable service
systemctl --user enable hook-event-processor

# Start service
systemctl --user start hook-event-processor

# Check status
systemctl --user status hook-event-processor
```

## Monitoring

### Service Logs

**View live logs**:
```bash
# System service
sudo journalctl -u hook-event-processor -f

# User service
journalctl --user -u hook-event-processor -f

# Alternative: direct log file
tail -f /tmp/hook_event_processor.log
```

**Search for errors**:
```bash
journalctl --user -u hook-event-processor | grep ERROR
```

### Metrics

The processor logs metrics every 60 seconds:

```
📊 Metrics: Processed=419, Succeeded=415, Failed=4, Retried=2, Errors=0, Uptime=120s
```

**Query metrics from database**:

```sql
-- Processing statistics
SELECT
    COUNT(*) FILTER (WHERE processed = TRUE) as processed_count,
    COUNT(*) FILTER (WHERE processed = FALSE) as pending_count,
    COUNT(*) FILTER (WHERE retry_count > 0) as retry_count,
    AVG(EXTRACT(EPOCH FROM (processed_at - created_at))) as avg_processing_time_sec
FROM hook_events
WHERE created_at > NOW() - INTERVAL '1 hour';

-- Error analysis
SELECT
    source,
    action,
    COUNT(*) as error_count,
    array_agg(DISTINCT processing_errors[array_length(processing_errors, 1)]) as recent_errors
FROM hook_events
WHERE retry_count > 0
GROUP BY source, action
ORDER BY error_count DESC;
```

### Performance Monitoring

**Check if target is met** (< 5 seconds processing time):

```sql
SELECT
    id,
    source,
    action,
    EXTRACT(EPOCH FROM (processed_at - created_at)) as processing_time_sec
FROM hook_events
WHERE processed = TRUE
  AND processed_at > NOW() - INTERVAL '1 hour'
  AND EXTRACT(EPOCH FROM (processed_at - created_at)) > 5
ORDER BY processing_time_sec DESC;
```

**Error rate check** (should be < 1%):

```sql
SELECT
    COUNT(*) FILTER (WHERE retry_count = 0) as successful,
    COUNT(*) FILTER (WHERE retry_count > 0) as failed,
    ROUND(100.0 * COUNT(*) FILTER (WHERE retry_count > 0) / COUNT(*), 2) as error_rate_pct
FROM hook_events
WHERE processed = TRUE
  AND processed_at > NOW() - INTERVAL '1 hour';
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PASSWORD` | - | **Required** PostgreSQL password |
| `POLL_INTERVAL` | `1.0` | Polling interval (seconds) |
| `BATCH_SIZE` | `100` | Events per batch |
| `MAX_RETRY_COUNT` | `3` | Maximum retry attempts |

### Database Schema

The processor interacts with the `hook_events` table:

```sql
CREATE TABLE hook_events (
    id UUID PRIMARY KEY,
    source VARCHAR(255) NOT NULL,
    action VARCHAR(255) NOT NULL,
    resource VARCHAR(255) NOT NULL,
    resource_id VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    processing_errors TEXT[],
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0 AND retry_count <= 10),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    CONSTRAINT processing_time_valid CHECK (processed_at IS NULL OR processed_at >= created_at),
    CONSTRAINT retry_count_limit CHECK (retry_count <= 10)
);

-- Indexes for performance
CREATE INDEX idx_hook_events_processed ON hook_events (processed, created_at DESC) WHERE NOT processed;
CREATE INDEX idx_hook_events_source_action ON hook_events (source, action);
CREATE INDEX idx_hook_events_retry ON hook_events (retry_count, created_at) WHERE retry_count > 0;
```

## Extending Handlers

### Add Custom Handler

Create a new handler function:

```python
# In event_handlers.py or custom module

def handle_custom_event(event: Dict[str, Any]) -> HandlerResult:
    """Handle custom event type."""
    try:
        payload = event.get("payload", {})
        # Process event

        return HandlerResult(
            success=True,
            message="Custom event processed",
            metadata={"custom_data": "..."}
        )
    except Exception as e:
        return HandlerResult(
            success=False,
            message=f"Failed: {e}",
            error=str(e)
        )
```

Register the handler:

```python
# In hook_event_processor.py, modify __init__

from services.event_handlers import register_custom_handler, handle_custom_event

class HookEventProcessor:
    def __init__(self, ...):
        # ... existing code ...

        # Register custom handler
        register_custom_handler(
            self.handler_registry,
            source="CustomSource",
            action="custom_action",
            handler=handle_custom_event
        )
```

## Troubleshooting

### Service Won't Start

**Check logs**:
```bash
journalctl --user -u hook-event-processor -n 50
```

**Common issues**:
1. **Database connection failed**: Verify `DB_PASSWORD` in `.env`
2. **Python not found**: Use full path `/usr/bin/python3`
3. **Import errors**: Ensure all dependencies installed with Poetry

### Events Not Processing

**Check for unprocessed events**:
```sql
SELECT COUNT(*) FROM hook_events WHERE processed = FALSE;
```

**Check retry counts**:
```sql
SELECT id, source, action, retry_count, processing_errors
FROM hook_events
WHERE retry_count >= 3
ORDER BY created_at DESC
LIMIT 10;
```

**Check for handler issues**:
```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python3 hook_event_processor.py
```

### High Memory Usage

**Check batch size**:
```bash
# Reduce batch size
export BATCH_SIZE=50
systemctl --user restart hook-event-processor
```

**Monitor memory**:
```bash
ps aux | grep hook_event_processor
```

### Database Lock Issues

The processor uses `FOR UPDATE SKIP LOCKED` to avoid blocking:

```sql
-- Check for locks
SELECT * FROM pg_locks WHERE relation = 'hook_events'::regclass;

-- Check for long-running transactions
SELECT pid, state, query_start, query
FROM pg_stat_activity
WHERE datname = 'omninode_bridge'
  AND state != 'idle'
ORDER BY query_start;
```

## Maintenance

### Clear Old Events

Archive processed events older than 30 days:

```sql
-- Archive to backup table
CREATE TABLE hook_events_archive AS
SELECT * FROM hook_events
WHERE processed = TRUE
  AND processed_at < NOW() - INTERVAL '30 days';

-- Delete archived events
DELETE FROM hook_events
WHERE processed = TRUE
  AND processed_at < NOW() - INTERVAL '30 days';
```

### Reset Failed Events

Manually reset events stuck in retry loop:

```sql
-- Reset retry count for specific events
UPDATE hook_events
SET retry_count = 0,
    processing_errors = NULL
WHERE retry_count >= 3
  AND source = 'PreToolUse'
  AND created_at > NOW() - INTERVAL '1 day';
```

## Success Criteria Validation

### ✅ All 419 Backlogged Events Processed

```sql
SELECT COUNT(*) FROM hook_events WHERE processed = TRUE;
-- Expected: >= 419
```

### ✅ New Events Processed Within 5 Seconds

```sql
SELECT
    AVG(EXTRACT(EPOCH FROM (processed_at - created_at))) as avg_sec,
    MAX(EXTRACT(EPOCH FROM (processed_at - created_at))) as max_sec
FROM hook_events
WHERE processed_at > NOW() - INTERVAL '1 hour';
-- Expected: avg_sec < 5, max_sec < 10
```

### ✅ Error Rate < 1%

```sql
SELECT
    ROUND(100.0 * COUNT(*) FILTER (WHERE retry_count > 0) / NULLIF(COUNT(*), 0), 2) as error_rate_pct
FROM hook_events
WHERE processed_at > NOW() - INTERVAL '1 hour';
-- Expected: < 1.0
```

### ✅ Service Auto-Restarts on Failure

```bash
# Kill service
pkill -9 -f hook_event_processor

# Wait 5 seconds
sleep 5

# Check if restarted
systemctl --user status hook-event-processor
# Expected: active (running)
```

## References

- **Database Schema**: See migration files in `agents/parallel_execution/migrations/`
- **Hook Event Logger**: `claude_hooks/lib/hook_event_logger.py`
- **Event Types**: `AGENT_DISPATCH_SYSTEM.md`
- **Systemd Documentation**: https://www.freedesktop.org/software/systemd/man/systemd.service.html

## Support

For issues or questions:
1. Check logs: `journalctl --user -u hook-event-processor -f`
2. Verify database connection: `psql -h localhost -p 5436 -U postgres -d omninode_bridge`
3. Review handler code: `event_handlers.py`
4. Check service configuration: `hook-event-processor.service`
