# Agent Name Tracking Fix

**Date**: 2025-11-06
**Priority**: Critical
**Status**: Implemented

## Problem Summary

78% of manifest injections (229/293 records) showed `agent_name` as "unknown" in the `agent_manifest_injections` table, blocking observability and traceability.

## Root Cause Analysis

### Investigation Findings

1. **Database Analysis** revealed that:
   - 229 records had `agent_name = "unknown"` (78%)
   - 64 records had actual agent names (22%)
   - Zero matching correlation_ids between `agent_routing_decisions` and `agent_manifest_injections` tables

2. **Code Flow Analysis** identified the issue:
   ```
   user-prompt-submit.sh (generates CORRELATION_ID)
     ↓
   routing service (stores decision with CORRELATION_ID)
     ↓
   manifest_loader.py (generates NEW correlation_id - PROBLEM!)
     ↓
   manifest_injector.py (stores with NEW correlation_id)
   ```

3. **Key Problems**:
   - `manifest_loader.py` was generating a new `correlation_id` instead of using the one from the hook
   - `CORRELATION_ID` was not being passed to `manifest_loader.py`
   - No linkage between routing decisions and manifest injections

## Solution Implemented

### Changes Made

#### 1. Updated `manifest_loader.py` (3 files)
- `/Users/jonah/.claude/hooks/lib/manifest_loader.py`
- `/Volumes/PRO-G40/Code/omniclaude/claude_hooks/lib/manifest_loader.py`
- `/Volumes/PRO-G40/Code/omniclaude/claude_hooks/manifest_loader.py`

**Key Changes**:
```python
# Added command-line argument parsing
import argparse

parser = argparse.ArgumentParser(description="Load dynamic system manifest")
parser.add_argument("--correlation-id", help="Correlation ID for tracking")
parser.add_argument("--agent-name", help="Agent name for logging/traceability")
args = parser.parse_args()

# Priority order: CLI args > environment vars > auto-generate
correlation_id = args.correlation_id or os.environ.get("CORRELATION_ID") or str(uuid4())
agent_name = args.agent_name or os.environ.get("AGENT_NAME")

# Pass to load_manifest function
print(load_manifest(correlation_id, agent_name))
```

#### 2. Updated `user-prompt-submit.sh`
- `/Volumes/PRO-G40/Code/omniclaude/claude_hooks/user-prompt-submit.sh`

**Before**:
```bash
SYSTEM_MANIFEST="$(PROJECT_PATH="$PROJECT_PATH" AGENT_NAME="${AGENT_NAME:-unknown}" python3 "$MANIFEST_LOADER" 2>>"$LOG_FILE" || echo "System Manifest: Not available")"
```

**After**:
```bash
SYSTEM_MANIFEST="$(PROJECT_PATH="$PROJECT_PATH" CORRELATION_ID="$CORRELATION_ID" AGENT_NAME="${AGENT_NAME:-unknown}" python3 "$MANIFEST_LOADER" --correlation-id "$CORRELATION_ID" --agent-name "${AGENT_NAME:-unknown}" 2>>"$LOG_FILE" || echo "System Manifest: Not available")"
```

## Expected Results

### Immediate Improvements

1. **Agent Name Capture**: Future manifest injections will capture the actual agent name from routing decisions
   - `polymorphic-agent`, `debug-intelligence`, `api-architect`, etc.
   - Instead of "unknown"

2. **Correlation ID Linkage**: Manifest injections and routing decisions will share the same correlation_id
   - Enables joining tables: `agent_routing_decisions` ⟷ `agent_manifest_injections`
   - Complete traceability from routing → manifest → execution

3. **Observability Improvements**:
   - Query routing decisions by agent: `SELECT * FROM agent_routing_decisions WHERE selected_agent = 'debug-intelligence'`
   - Link to manifests: `JOIN agent_manifest_injections USING (correlation_id)`
   - View complete decision chain with `v_agent_execution_trace` view

### Verification Queries

Once the fix is deployed and new prompts are processed:

```sql
-- Check if new records have proper agent names
SELECT
    agent_name,
    correlation_id,
    created_at
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC
LIMIT 10;

-- Verify correlation_id linkage
SELECT
    m.agent_name as manifest_agent,
    r.selected_agent as routing_agent,
    m.correlation_id,
    m.created_at
FROM agent_manifest_injections m
INNER JOIN agent_routing_decisions r ON m.correlation_id = r.correlation_id
WHERE m.created_at > NOW() - INTERVAL '1 hour'
ORDER BY m.created_at DESC;

-- Count matching correlation IDs (should be > 0 after fix)
SELECT COUNT(*) as matching_ids
FROM agent_routing_decisions r
INNER JOIN agent_manifest_injections m ON r.correlation_id = m.correlation_id
WHERE m.created_at > NOW() - INTERVAL '1 hour';
```

## Testing Recommendations

### Manual Testing
1. Submit a prompt through Claude Code (this will trigger the hook)
2. Check the logs: `tail -f ~/.claude/hooks/hooks.log`
3. Query the database to verify:
   - Agent name is captured correctly
   - Correlation ID matches between tables

### Automated Testing
Create a test script that:
1. Generates a test correlation_id
2. Calls manifest_loader.py with explicit arguments
3. Verifies database storage

## Rollback Plan

If issues are encountered, revert the following changes:

1. **manifest_loader.py**:
   ```bash
   git checkout HEAD~1 claude_hooks/lib/manifest_loader.py
   cp claude_hooks/lib/manifest_loader.py ~/.claude/hooks/lib/
   ```

2. **user-prompt-submit.sh**:
   ```bash
   git checkout HEAD~1 claude_hooks/user-prompt-submit.sh
   ```

## Success Metrics

- [ ] Agent name capture rate increases from 22% to >95%
- [ ] Correlation ID match rate increases from 0% to >95%
- [ ] No "unknown" agent names in new records
- [ ] Complete traceability chain: routing → manifest → execution

## Related Files

- `agents/lib/manifest_injector.py` (line 681, 3801) - Agent name handling
- `claude_hooks/lib/manifest_loader.py` - Updated CLI arg parsing
- `claude_hooks/user-prompt-submit.sh` (line 410) - Updated hook invocation
- `agent_manifest_injections` table - Database schema
- `agent_routing_decisions` table - Database schema

## Follow-up Actions

1. Monitor agent_name capture rate for next 24 hours
2. Verify correlation_id linkage with JOIN queries
3. Update observability dashboards to use joined data
4. Consider adding foreign key constraint: `agent_manifest_injections.routing_decision_id → agent_routing_decisions.id`

## Notes

- The fix maintains backward compatibility (falls back to environment variables if CLI args not provided)
- No database schema changes required
- The fix is non-breaking and safe to deploy immediately
- Historical "unknown" records will remain, but new records will be correct
