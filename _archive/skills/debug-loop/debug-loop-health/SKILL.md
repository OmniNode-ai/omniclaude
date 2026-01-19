---
name: debug-loop-health
description: Quick sanity check of debug loop system before debugging
category: debugging
version: 1.0.0
author: OmniClaude Team
tags:
  - debug-loop
  - health-check
  - diagnostics
  - postgresql
---

# Debug Loop Health Check

Performs comprehensive health check of debug loop infrastructure to verify system readiness before debugging sessions.

## Overview

This skill provides instant diagnostics of the debug loop system, checking all critical components required for debugging workflows:

- **PostgreSQL database connectivity** - Verifies connection to shared bridge database
- **STF table status** - Checks `debug_transform_functions` table availability and count
- **Model catalog status** - Checks `model_price_catalog` table availability and count
- **Latest STF timestamp** - Shows when the last STF template was created
- **System readiness** - Overall health status with traffic light indicators

## Usage

Invoke this skill when starting a debugging session to verify infrastructure is ready:

```bash
# Skill will automatically:
# 1. Load database credentials from environment
# 2. Test PostgreSQL connection
# 3. Query both critical tables
# 4. Format output with visual indicators
# 5. Return structured health status
```

## Output Format

The skill provides clear visual feedback using traffic light indicators:

- 🟢 **GREEN** - Component healthy and operational
- 🟡 **YELLOW** - Component degraded but functional
- 🔴 **RED** - Component unavailable or failing

## Requirements

### Environment Variables

The following environment variables must be set (typically in `.env`):

- `POSTGRES_HOST` - PostgreSQL server hostname (default: 192.168.86.200)
- `POSTGRES_PORT` - PostgreSQL server port (default: 5436)
- `POSTGRES_DATABASE` - Database name (default: omninode_bridge)
- `POSTGRES_USER` - Database username (default: postgres)
- `POSTGRES_PASSWORD` - Database password (required)

### Dependencies

- Python 3.10+
- `asyncpg` - Async PostgreSQL driver
- `rich` - Terminal formatting and colors
- `python-dotenv` - Environment variable loading

## Error Handling

The skill implements graceful error handling:

- **Database connection failures** - Shows clear error message with troubleshooting hints
- **Missing environment variables** - Reports which variables need to be set
- **Query failures** - Catches and reports SQL errors without crashing
- **Timeout handling** - Aborts long-running queries after 10 seconds

## Example Output

```
🟢 Debug Loop Health Check
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ PostgreSQL: Connected (192.168.86.200:5436/omninode_bridge)
✅ STF Table: 42 templates available
✅ Model Catalog: 15 models configured
✅ Latest STF: Created 2 hours ago (2025-11-11 09:30:00 UTC)
✅ System Status: HEALTHY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Ready for debugging! 🚀
```

## Troubleshooting

### "Connection refused" error
- Verify PostgreSQL service is running: `docker ps | grep postgres`
- Check network connectivity: `ping 192.168.86.200`
- Verify port is accessible: `nc -zv 192.168.86.200 5436`

### "Authentication failed" error
- Verify `POSTGRES_PASSWORD` is set in `.env`
- Try connecting manually: `source .env && psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE`

### "Table does not exist" error
- Verify you're connected to the correct database (`omninode_bridge`)
- Check if tables exist: `\dt debug_transform_functions` in psql
- May need to run database migrations

### "Timeout" error
- Database server may be overloaded
- Check server resources: CPU, memory, disk I/O
- Verify network latency is acceptable

## Related Skills

- `debug-loop/debug-loop-query` - Query STFs by category and signature (planned)
- `debug-loop/debug-loop-stats` - Detailed statistics and analytics (planned)
- `log-execution` - Action logging for debugging workflows

## Technical Details

**Database Schema:**
- Table: `debug_transform_functions`
  - Primary key: `stf_id` (UUID)
  - Index: `stf_hash` (unique)
  - Fields: `stf_name`, `stf_code`, `quality_score`, `usage_count`, etc.

- Table: `model_price_catalog`
  - Primary key: `catalog_id` (UUID)
  - Fields: `provider`, `model_name`, `input_price_per_million`, etc.

**Performance:**
- Connection time: <500ms typical
- Query execution: <100ms typical
- Total skill execution: <1 second typical

## Version History

- **1.0.0** (2025-11-11) - Initial release
  - PostgreSQL connectivity check
  - STF table status
  - Model catalog status
  - Latest STF timestamp
  - Traffic light visual indicators
  - Structured JSON output
  - Graceful error handling
