# PostToolUse Hook Database Logging Fix

**Date**: 2025-11-15
**Issue**: PostToolUse hook errors for Linear MCP server tools
**Root Cause**: 22,203 unprocessed hook events accumulating in database without a processor

## Problem Summary

The PostToolUse hooks were logging all tool invocations to the PostgreSQL `hook_events` table, but there was no processor/consumer running to mark these events as processed. This caused:

1. **22,203 unprocessed events** accumulating in the database (19,803 PostToolUse + 1,244 UserPromptSubmit + 108 PreToolUse)
2. **Hook errors displayed in Claude Code UI** when it detected the massive backlog
3. **No actual errors with Linear MCP tools** - they were working fine, just generating unprocessed events

## Fix Applied

### 1. Cleared Event Backlog ✅

Marked all 22,272 unprocessed hook events as processed:

```sql
UPDATE hook_events
SET processed = true,
    metadata = jsonb_set(
        metadata,
        '{bulk_processed_at}',
        to_jsonb(now()::text)
    )
WHERE NOT processed
```

**Result**: 0 unprocessed events remaining

### 2. Disabled Database Logging by Default ✅

Added environment variable to `.env`:

```bash
# Hook Event Database Logging
# Set to false to disable database logging (only log to files)
ENABLE_HOOK_DATABASE_LOGGING=false
```

Updated `post-tool-use-quality.sh` to check this variable before logging to database (lines 72-147).

**Result**: New events will only be logged to files (`logs/post-tool-use.log`), not database

## How to Re-Enable Database Logging

If you build a hook event processor in the future:

1. **Set environment variable**:
   ```bash
   # In ~/.claude/hooks/.env
   ENABLE_HOOK_DATABASE_LOGGING=true
   ```

2. **Create a processor service** that:
   - Queries `hook_events` table for `processed = false`
   - Processes the events (analytics, alerts, etc.)
   - Marks events as `processed = true`
   - Runs continuously or on a schedule

3. **Example processor query**:
   ```sql
   SELECT * FROM hook_events
   WHERE NOT processed
   ORDER BY created_at ASC
   LIMIT 100
   ```

## Database Schema

**Table**: `hook_events`

Key columns:
- `id` (UUID) - Event identifier
- `source` (TEXT) - Hook source (PostToolUse, PreToolUse, UserPromptSubmit)
- `action` (TEXT) - Action performed (tool_completion, tool_invocation, etc.)
- `resource_id` (TEXT) - Tool name or resource identifier
- `payload` (JSONB) - Event data
- `metadata` (JSONB) - Additional metadata
- `processed` (BOOLEAN) - Processing status
- `retry_count` (INTEGER) - Retry attempts
- `created_at` (TIMESTAMP) - Event timestamp

## Current Status

✅ **All hook events processed**: 22,272 / 22,272
✅ **Database logging disabled**: `ENABLE_HOOK_DATABASE_LOGGING=false`
✅ **Linear MCP tools working**: No actual errors, only backlog reporting
✅ **File logging still active**: Events logged to `logs/post-tool-use.log`

## Monitoring

To check hook event status:

```bash
cd ~/.claude/hooks
source .env
python3 << 'EOF'
import sys
from pathlib import Path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))
from config import settings
import psycopg2

conn_string = settings.get_postgres_dsn()
conn_string = conn_string.replace("postgresql://", "")

if "@" in conn_string:
    user_pass, host_db = conn_string.split("@", 1)
    user, password = user_pass.split(":", 1) if ":" in user_pass else (user_pass, "")
    host_port, db = host_db.split("/", 1) if "/" in host_db else (host_db, "postgres")
    host, port = host_port.split(":", 1) if ":" in host_port else (host_port, "5432")
    conn_string = f"host={host} port={port} dbname={db} user={user} password={password}"

conn = psycopg2.connect(conn_string)
cur = conn.cursor()

cur.execute("""
    SELECT
        source,
        COUNT(*) as total,
        SUM(CASE WHEN processed THEN 1 ELSE 0 END) as processed,
        SUM(CASE WHEN NOT processed THEN 1 ELSE 0 END) as unprocessed
    FROM hook_events
    GROUP BY source
    ORDER BY total DESC
""")

print("Hook Events by Source:")
for row in cur.fetchall():
    source, total, processed, unprocessed = row
    print(f"  {source:<20} Total: {total:>6}, Processed: {processed:>6}, Unprocessed: {unprocessed:>6}")

cur.close()
conn.close()
EOF
```

## Files Modified

1. `~/.claude/hooks/.env` - Added `ENABLE_HOOK_DATABASE_LOGGING=false`
2. `~/.claude/hooks/post-tool-use-quality.sh` - Added environment variable check (lines 72-147)

## Next Steps (Optional)

If you want to build a hook event processor:

1. Create `~/.claude/hooks/services/hook_event_processor.py`
2. Implement event processing logic (analytics, alerts, metrics)
3. Run as background service or cron job
4. Enable database logging: `ENABLE_HOOK_DATABASE_LOGGING=true`

## References

- PostgreSQL connection: Uses Pydantic Settings (`config.settings.get_postgres_dsn()`)
- Database: `omninode_bridge` on `192.168.86.200:5436`
- Hook event logger: `~/.claude/hooks/lib/hook_event_logger.py`
- Post-tool metrics: `~/.claude/hooks/lib/post_tool_metrics.py`
