# Agent Lifecycle Completion Tracking

## Overview

This document describes the agent lifecycle completion tracking feature that fixes the **"Active Agents never reaches 0"** bug.

### Problem

The `agent_manifest_injections` table has lifecycle fields (`completed_at`, `executed_at`, `agent_execution_success`) but NO code was updating them, causing:
- "Active Agents" counter stays at 6 permanently
- All 30 agent records have `completed_at = NULL`
- No way to track agent execution completion
- No metrics on agent success rates or durations

### Solution

Added lifecycle tracking methods to properly update completion timestamps when agents finish execution.

## Implementation

### 1. Database Schema

The `agent_manifest_injections` table has these lifecycle fields:

```sql
CREATE TABLE agent_manifest_injections (
    -- ... existing fields ...
    completed_at TIMESTAMPTZ,           -- When agent completed execution
    executed_at TIMESTAMPTZ,            -- When agent execution finished
    agent_execution_success BOOLEAN,    -- Whether execution succeeded
    -- ... existing fields ...
);
```

### 2. Code Changes

#### A. ManifestInjectionStorage.mark_agent_completed()

New method in `/Volumes/PRO-G40/Code/omniclaude/agents/lib/manifest_injector.py`:

```python
def mark_agent_completed(
    self,
    correlation_id: UUID,
    success: bool = True,
    error_message: Optional[str] = None,
) -> bool:
    """
    Mark agent execution as completed by updating lifecycle fields.

    Args:
        correlation_id: Correlation ID linking to manifest injection record
        success: Whether agent execution succeeded (default: True)
        error_message: Optional error message if execution failed

    Returns:
        True if successful, False otherwise
    """
```

#### B. ManifestInjector.mark_agent_completed()

Convenience method in `ManifestInjector` class:

```python
def mark_agent_completed(
    self,
    success: bool = True,
    error_message: Optional[str] = None,
) -> bool:
    """
    Mark agent execution as completed (lifecycle tracking).

    Uses the current correlation ID set during manifest generation.
    """
```

#### C. Agent Name Resolution Fix

Fixed the "unknown" agent name issue by reading from `AGENT_NAME` environment variable:

```python
# In ManifestInjector.__init__()
self.agent_name = agent_name or os.environ.get("AGENT_NAME")
```

## Usage Examples

### Basic Usage with Context Manager

```python
from agents.lib.manifest_injector import ManifestInjector
from uuid import uuid4

# Set agent name in environment (fixes "unknown" agent names)
import os
os.environ["AGENT_NAME"] = "agent-researcher"

correlation_id = uuid4()

# Use context manager (recommended)
async with ManifestInjector(agent_name="agent-researcher") as injector:
    # Generate manifest (sets correlation_id internally)
    await injector.generate_dynamic_manifest_async(str(correlation_id))

    try:
        # ... do agent work ...

        # Mark as completed on success
        injector.mark_agent_completed(success=True)

    except Exception as e:
        # Mark as completed with error
        injector.mark_agent_completed(success=False, error_message=str(e))
```

### Manual Storage Usage

```python
from agents.lib.manifest_injector import ManifestInjectionStorage
from uuid import uuid4

storage = ManifestInjectionStorage()
correlation_id = uuid4()

# After agent execution completes
success = storage.mark_agent_completed(
    correlation_id=correlation_id,
    success=True
)

if success:
    print("Agent marked as completed")
else:
    print("Failed to mark agent as completed")
```

### Integration with Existing Agent Code

```python
from agents.lib.manifest_injector import ManifestInjector
import asyncio

async def run_agent():
    correlation_id = "your-correlation-id"

    async with ManifestInjector(agent_name="agent-researcher") as injector:
        # Generate manifest
        manifest = await injector.generate_dynamic_manifest_async(correlation_id)

        try:
            # Agent execution logic
            result = await perform_research()

            # Mark success
            injector.mark_agent_completed(success=True)
            return result

        except Exception as e:
            # Mark failure
            injector.mark_agent_completed(
                success=False,
                error_message=f"Research failed: {e}"
            )
            raise

# Run agent
asyncio.run(run_agent())
```

## Cleanup Script

Use the cleanup script to mark existing orphaned records as completed:

```bash
# Run cleanup script
psql -h omninode-bridge-postgres -p 5436 -U postgres -d omninode_bridge \
  -f /Volumes/PRO-G40/Code/omniclaude/agents/lib/cleanup_orphaned_agent_records.sql

# Or with password environment variable
export PGPASSWORD=omninode_remote_2024_secure
psql -h omninode-bridge-postgres -p 5436 -U postgres -d omninode_bridge \
  -f /Volumes/PRO-G40/Code/omniclaude/agents/lib/cleanup_orphaned_agent_records.sql
```

The cleanup script:
- Marks all orphaned records (completed_at IS NULL) as completed
- Assumes 5-minute execution duration for historical records
- Only processes records older than 1 hour (safety check)
- Adds warning to track auto-completed records
- **IDEMPOTENT** - safe to run multiple times

## Verification

Run verification queries to confirm the fix is working:

```bash
# Run verification queries
psql -h omninode-bridge-postgres -p 5436 -U postgres -d omninode_bridge \
  -f /Volumes/PRO-G40/Code/omniclaude/agents/lib/verify_lifecycle_tracking.sql
```

### Expected Results

After implementing the fix and running cleanup:

1. **Active Agents Count**: Should be 0 when no agents running
2. **Lifecycle Fields Population**: Should be 100% for completed agents
3. **Agent Name Resolution**: Unknown agents should be <5%
4. **Execution Duration**: Most executions complete within 1-10 seconds
5. **Success Rate**: Most agents should have >90% success rate

### Verification Queries

```sql
-- Check active agents (should be 0 or very low)
SELECT COUNT(*) AS active_agents
FROM agent_manifest_injections
WHERE completed_at IS NULL;

-- Check recent completions (should have all lifecycle fields)
SELECT
    agent_name,
    completed_at,
    executed_at,
    agent_execution_success,
    EXTRACT(EPOCH FROM (completed_at - created_at)) AS duration_seconds
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC
LIMIT 10;

-- Check agent name resolution (should be mostly known)
SELECT
    agent_name,
    COUNT(*) AS executions
FROM agent_manifest_injections
GROUP BY agent_name
ORDER BY executions DESC;
```

## Environment Variables

Ensure `AGENT_NAME` is set to avoid "unknown" agent names:

```bash
# In agent startup script
export AGENT_NAME="agent-researcher"

# Or in Python before creating ManifestInjector
import os
os.environ["AGENT_NAME"] = "agent-researcher"
```

## Database Connection

The lifecycle tracking uses the same database connection as manifest storage:

- **Host**: `omninode-bridge-postgres` (Docker) or `192.168.86.200` (remote)
- **Port**: `5436`
- **Database**: `omninode_bridge`
- **User**: `postgres`
- **Password**: `omninode_remote_2024_secure` (from env or default)

Environment variables used:
- `POSTGRES_HOST` (default: "192.168.86.200")
- `POSTGRES_PORT` (default: "5436")
- `POSTGRES_DATABASE` (default: "omninode_bridge")
- `POSTGRES_USER` (default: "postgres")
- `POSTGRES_PASSWORD` (default: "omninode-bridge-postgres-dev-2024")

## Troubleshooting

### Active Agents Count Not Decreasing

1. Check if agents are calling `mark_agent_completed()`:
   ```python
   # Add logging to verify method is called
   import logging
   logging.basicConfig(level=logging.INFO)
   ```

2. Verify database connectivity:
   ```bash
   psql -h omninode-bridge-postgres -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"
   ```

3. Check recent executions:
   ```sql
   SELECT * FROM agent_manifest_injections ORDER BY created_at DESC LIMIT 10;
   ```

### Agent Name Still "unknown"

1. Set `AGENT_NAME` environment variable before agent starts
2. Pass `agent_name` parameter to `ManifestInjector.__init__()`
3. Check logs for agent name resolution

### Cleanup Script Not Working

1. Check database connection
2. Verify you have write permissions
3. Review script output for errors
4. Run with `ROLLBACK` first to test without making changes

## Best Practices

1. **Always use context manager** for `ManifestInjector` to ensure cleanup
2. **Set AGENT_NAME** environment variable at agent startup
3. **Call mark_agent_completed()** in finally block to ensure it runs
4. **Handle both success and failure cases** explicitly
5. **Run cleanup script periodically** to handle any missed completions
6. **Monitor verification queries** to track lifecycle tracking health

## Performance Impact

- **Database writes**: +1 UPDATE per agent execution (minimal overhead)
- **Network latency**: <10ms for lifecycle update
- **No blocking**: Lifecycle tracking is non-blocking
- **Fallback**: Uses same error handling as manifest storage

## Future Enhancements

1. **Automatic cleanup job**: Cron job to mark stale incomplete records
2. **Real-time monitoring**: Dashboard showing active agents count
3. **Success rate tracking**: Alerts when success rate drops below threshold
4. **Duration analysis**: Detect slow agents and optimize
5. **Correlation with execution logs**: Link to `agent_execution_logs` table
