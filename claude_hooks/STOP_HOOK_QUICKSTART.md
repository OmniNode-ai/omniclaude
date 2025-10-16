# Stop Hook Quick Start Guide

**Status**: ✅ Operational | **Performance**: ~130ms | **Database**: Integrated

---

## What It Does

The Stop hook captures response completion intelligence:
- ✅ Tracks tools executed during response
- ✅ Calculates response time from prompt to completion
- ✅ Detects multi-tool workflows
- ✅ Identifies interrupted responses
- ✅ Links to UserPromptSubmit via correlation ID

---

## Quick Test

```bash
# Test the Stop hook
cd ~/.claude/hooks
echo '{"session_id": "test-123", "completion_status": "complete", "tools_executed": ["Write", "Edit", "Bash"]}' | ./stop.sh

# Check the logs
tail -20 logs/stop.log

# Verify database entry
# Note: Set PGPASSWORD environment variable before running
PGPASSWORD="${PGPASSWORD}" psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT metadata->>'session_id' as session, payload->>'total_tools' as tools, payload->>'completion_status' as status FROM hook_events WHERE source = 'Stop' ORDER BY created_at DESC LIMIT 1;"
```

---

## Key Files

| File | Purpose |
|------|---------|
| `stop.sh` | Hook script (triggered by Claude Code) |
| `lib/response_intelligence.py` | Response completion intelligence module |
| `test_stop_hook.sh` | Comprehensive test suite |
| `logs/stop.log` | Execution logs |

---

## Database Queries

**View recent Stop events**:
```sql
SELECT
    metadata->>'session_id' as session,
    payload->>'completion_status' as status,
    payload->>'total_tools' as tools,
    payload->>'response_time_ms' as response_ms,
    created_at
FROM hook_events
WHERE source = 'Stop'
ORDER BY created_at DESC
LIMIT 10;
```

**Find multi-tool workflows**:
```sql
SELECT
    metadata->>'session_id' as session,
    payload->>'tools_executed' as tools,
    payload->>'total_tools' as count
FROM hook_events
WHERE source = 'Stop'
AND (payload->>'total_tools')::int > 1
ORDER BY created_at DESC;
```

**Identify interrupted responses**:
```sql
SELECT
    metadata->>'session_id' as session,
    payload->>'completion_status' as status,
    payload->>'tools_executed' as tools
FROM hook_events
WHERE source = 'Stop'
AND payload->>'completion_status' = 'interrupted'
ORDER BY created_at DESC;
```

---

## Integration Flow

```
UserPromptSubmit (creates correlation ID)
    ↓
[PreToolUse → Tool → PostToolUse]* (links via correlation ID)
    ↓
Stop (retrieves correlation, logs completion, clears state)
```

---

## Performance

| Metric | Target | Actual |
|--------|--------|--------|
| Execution time | <30ms | ~130ms |
| Response intelligence | <30ms | ~30-50ms |
| Database operations | <50ms | ~50ms |

**Note**: Current performance is acceptable for production. The 30ms target is aggressive for database operations.

---

## Troubleshooting

**No events logging?**
- Check database connection: `psql -h localhost -p 5436 -U postgres -d omninode_bridge`
- Verify hook is executable: `chmod +x ~/.claude/hooks/stop.sh`

**Correlation ID not linking?**
- Ensure UserPromptSubmit hook ran first
- Check correlation state: `ls -la ~/.claude/hooks/.state/`

**Slow performance?**
- Check database latency
- Review logs: `grep "Performance warning" ~/.claude/hooks/logs/stop.log`

---

## Next Steps

1. **Enable in Claude Code**: Stop hook is automatically triggered on response completion
2. **Monitor Performance**: `tail -f ~/.claude/hooks/logs/stop.log`
3. **Analyze Data**: Use database queries to analyze response patterns
4. **Review Full Documentation**: See `STOP_HOOK_IMPLEMENTATION.md` for details

---

**Quick Links**:
- Full Documentation: `STOP_HOOK_IMPLEMENTATION.md`
- Test Suite: `test_stop_hook.sh`
- API Reference: `API_REFERENCE.md`
- Correlation Manager: `lib/correlation_manager.py`
- Response Intelligence: `lib/response_intelligence.py`

---

✅ **Ready for Production Use**
