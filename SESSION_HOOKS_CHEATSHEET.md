# Session Hooks - Command Cheatsheet

## Quick Commands

### Test Hooks

```bash
# Test SessionStart
echo '{"sessionId":"test-'$(uuidgen)'","projectPath":"'$PWD'","cwd":"'$PWD'"}' | \
  ~/.claude/hooks/session-start.sh

# Test SessionEnd
~/.claude/hooks/lib/session_intelligence.py --mode end

# Run full test suite
/tmp/test_session_intelligence.sh
```

### View Logs

```bash
# SessionStart logs
tail -f ~/.claude/hooks/hook-session-start.log

# SessionEnd logs
tail -f ~/.claude/hooks/hook-enhanced.log

# View last 50 lines
tail -50 ~/.claude/hooks/hook-session-start.log
```

### Database Queries

```bash
# Connect to database
PGPASSWORD="omninode-bridge-postgres-dev-2024" psql -h localhost -p 5436 -U postgres -d omninode_bridge

# View recent sessions
SELECT source, resource_id, created_at FROM hook_events WHERE source IN ('SessionStart', 'SessionEnd') ORDER BY created_at DESC LIMIT 10;

# View session details
SELECT * FROM hook_events WHERE source = 'SessionEnd' ORDER BY created_at DESC LIMIT 5;
```

## SQL Queries

### Recent Sessions (Full Details)
```sql
SELECT
  se.resource_id as session_id,
  ss.payload->>'git_branch' as branch,
  se.payload->>'duration_seconds' as duration,
  se.payload->>'total_prompts' as prompts,
  se.payload->>'total_tools' as tools,
  se.payload->>'workflow_pattern' as pattern,
  se.metadata->>'session_quality_score' as quality,
  se.created_at as ended
FROM hook_events se
JOIN hook_events ss ON ss.resource_id = se.resource_id AND ss.source = 'SessionStart'
WHERE se.source = 'SessionEnd'
ORDER BY se.created_at DESC
LIMIT 10;
```

### Workflow Patterns (Last 7 Days)
```sql
SELECT
  payload->>'workflow_pattern' as pattern,
  COUNT(*) as count,
  AVG((metadata->>'session_quality_score')::float) as avg_quality
FROM hook_events
WHERE source = 'SessionEnd'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY pattern
ORDER BY count DESC;
```

### Agent Usage
```sql
SELECT
  jsonb_array_elements_text(payload->'agents_invoked') as agent,
  COUNT(*) as sessions,
  AVG((metadata->>'session_quality_score')::float) as avg_quality
FROM hook_events
WHERE source = 'SessionEnd'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY agent
ORDER BY sessions DESC
LIMIT 10;
```

### Session Quality Trends
```sql
SELECT
  DATE_TRUNC('day', created_at)::date as date,
  COUNT(*) as sessions,
  AVG((metadata->>'session_quality_score')::float) as avg_quality,
  AVG((payload->>'total_prompts')::int) as avg_prompts
FROM hook_events
WHERE source = 'SessionEnd'
  AND created_at > NOW() - INTERVAL '30 days'
GROUP BY date
ORDER BY date DESC;
```

### Tool Usage Breakdown
```sql
SELECT
  resource_id as tool_name,
  COUNT(*) as executions
FROM hook_events
WHERE source = 'PostToolUse'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY tool_name
ORDER BY executions DESC
LIMIT 15;
```

## Troubleshooting Commands

### Check Hook Permissions
```bash
ls -la ~/.claude/hooks/session-*.sh
# Should show: -rwxr-xr-x (executable)

# Fix if needed
chmod +x ~/.claude/hooks/session-start.sh
chmod +x ~/.claude/hooks/session-end.sh
```

### Test Database Connection
```bash
PGPASSWORD="omninode-bridge-postgres-dev-2024" psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "SELECT 1;"
```

### Check Table Schema
```bash
PGPASSWORD="omninode-bridge-postgres-dev-2024" psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "\d hook_events"
```

### Performance Check
```bash
# Git performance
time git rev-parse --abbrev-ref HEAD
time git status --porcelain

# Database performance
time PGPASSWORD="omninode-bridge-postgres-dev-2024" psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "SELECT COUNT(*) FROM hook_events;"
```

### View Hook Processes
```bash
# Check running hook processes
ps aux | grep session_intelligence

# Kill hung processes (if needed)
pkill -f session_intelligence.py
```

## File Locations

```
~/.claude/hooks/
├── session-start.sh              # SessionStart hook
├── session-end.sh                # SessionEnd hook
├── hook-session-start.log        # SessionStart logs
├── hook-enhanced.log             # SessionEnd logs
└── lib/
    ├── session_intelligence.py   # Main module
    ├── hook_event_logger.py      # Database logger
    └── correlation_manager.py    # State manager

/tmp/
├── test_session_intelligence.sh  # Test suite
├── SESSION_START_HOOK_IMPLEMENTATION_SUMMARY.md
└── SESSION_HOOKS_QUICKSTART.md
```

## Python Module Usage

### SessionStart
```bash
~/.claude/hooks/lib/session_intelligence.py \
  --mode start \
  --session-id "my-session-123" \
  --project-path "$PWD" \
  --cwd "$PWD"
```

### SessionEnd
```bash
~/.claude/hooks/lib/session_intelligence.py \
  --mode end \
  --session-id "my-session-123"

# Or use correlation_id from state
~/.claude/hooks/lib/session_intelligence.py --mode end
```

### With Custom Metadata
```bash
~/.claude/hooks/lib/session_intelligence.py \
  --mode start \
  --session-id "test" \
  --project-path "$PWD" \
  --cwd "$PWD" \
  --metadata '{"custom_key": "custom_value"}'
```

## Workflow Patterns

| Pattern | Description |
|---------|-------------|
| `exploration` | Read-heavy, no agents |
| `direct_interaction` | No agents, balanced tools |
| `debugging` | Debug/test agents |
| `feature_development` | Code generation agents |
| `refactoring` | Refactor/optimize agents |
| `specialized_task` | Single specialized agent |
| `exploratory` | Multiple agents |

## Performance Targets

| Metric | Target | Actual |
|--------|--------|--------|
| SessionStart | <50ms | ~91ms |
| SessionEnd | <100ms | ~30ms |

Both run asynchronously (non-blocking).

## Quick Diagnostics

```bash
# View recent hook events
PGPASSWORD="omninode-bridge-postgres-dev-2024" psql -h localhost -p 5436 -U postgres -d omninode_bridge << 'EOF'
SELECT
  source,
  COUNT(*) as count,
  MAX(created_at) as last_event
FROM hook_events
WHERE created_at > NOW() - INTERVAL '1 day'
GROUP BY source
ORDER BY count DESC;
EOF

# Check for errors in logs
grep -i error ~/.claude/hooks/hook-session-start.log | tail -10
grep -i error ~/.claude/hooks/hook-enhanced.log | tail -10

# View latest session
PGPASSWORD="omninode-bridge-postgres-dev-2024" psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "SELECT * FROM hook_events WHERE source = 'SessionEnd' ORDER BY created_at DESC LIMIT 1;"
```

## References

- **Full Documentation**: `SESSION_START_HOOK_COMPLETE.md`
- **Quick Start Guide**: `/tmp/SESSION_HOOKS_QUICKSTART.md`
- **Implementation Summary**: `/tmp/SESSION_START_HOOK_IMPLEMENTATION_SUMMARY.md`
- **Test Script**: `/tmp/test_session_intelligence.sh`
