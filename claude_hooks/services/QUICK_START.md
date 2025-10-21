# Quick Start - Hook Event Processor

**TL;DR**: Background service to process hook events from the database.

## Install & Run (5 minutes)

### 1. Quick Test (Manual)
```bash
cd /Volumes/PRO-G40/Code/omniclaude/claude_hooks/services
./run_processor.sh --once
```

### 2. Install as Service
```bash
# User-level systemd service
mkdir -p ~/.config/systemd/user/
cp hook-event-processor.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable hook-event-processor
systemctl --user start hook-event-processor
```

### 3. Monitor
```bash
# Live logs
journalctl --user -u hook-event-processor -f

# Service status
systemctl --user status hook-event-processor
```

### 4. Check Database
```bash
PGPASSWORD="omninode-bridge-postgres-dev-2024" psql \
  -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT COUNT(*) FROM hook_events WHERE processed = FALSE;"
```

## Common Commands

### Service Control
```bash
# Start
systemctl --user start hook-event-processor

# Stop
systemctl --user stop hook-event-processor

# Restart
systemctl --user restart hook-event-processor

# Status
systemctl --user status hook-event-processor

# Logs (last 50 lines)
journalctl --user -u hook-event-processor -n 50

# Logs (live)
journalctl --user -u hook-event-processor -f
```

### Database Queries
```sql
-- Unprocessed count
SELECT COUNT(*) FROM hook_events WHERE processed = FALSE;

-- Processing statistics
SELECT
    COUNT(*) FILTER (WHERE processed = TRUE) as processed,
    COUNT(*) FILTER (WHERE processed = FALSE) as pending,
    COUNT(*) FILTER (WHERE retry_count > 0) as errors
FROM hook_events;

-- Error analysis
SELECT source, action, retry_count, processing_errors
FROM hook_events
WHERE retry_count > 0
ORDER BY created_at DESC
LIMIT 10;
```

## Configuration

Edit `.env` file:
```bash
DB_PASSWORD=omninode-bridge-postgres-dev-2024
POLL_INTERVAL=1.0        # Polling interval (seconds)
BATCH_SIZE=100           # Events per batch
MAX_RETRY_COUNT=3        # Max retry attempts
```

## Troubleshooting

**Service won't start**:
```bash
journalctl --user -u hook-event-processor -n 100
```

**Database connection failed**:
```bash
# Test database connection
PGPASSWORD="omninode-bridge-postgres-dev-2024" \
psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"
```

**Events not processing**:
```bash
# Check for locks
PGPASSWORD="omninode-bridge-postgres-dev-2024" \
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
-c "SELECT * FROM pg_locks WHERE relation = 'hook_events'::regclass;"
```

## Documentation

- **Full Documentation**: `README_PROCESSOR.md`
- **Implementation Summary**: `IMPLEMENTATION_SUMMARY.md`
- **Source Code**: `hook_event_processor.py`, `event_handlers.py`
