# Quick Start: Phase 4 Pattern Traceability Integration

**Get up and running in 5 minutes**

---

## Prerequisites

✅ Docker & Docker Compose installed
✅ PostgreSQL database (Supabase or self-hosted)
✅ Archon Intelligence Service
✅ Claude Code with hooks configured

---

## Step 1: Verify Phase 4 Service Running

```bash
# Check if intelligence service is running
docker compose ps intelligence

# If not running, start it
docker compose up -d intelligence

# Verify health
curl http://localhost:8053/api/pattern-traceability/health
```

**Expected output**:
```json
{
  "status": "healthy",
  "components": {
    "lineage_tracker": "operational",
    "usage_analytics": "operational",
    "feedback_orchestrator": "operational"
  }
}
```

---

## Step 2: Configure Database Connection

```bash
# Option A: Use Supabase
export SUPABASE_URL="https://YOUR-PROJECT.supabase.co"
export SUPABASE_SERVICE_KEY="your-service-key"

# Option B: Use direct PostgreSQL connection
export TRACEABILITY_DB_URL_EXTERNAL="postgresql://user:pass@host:5432/archon"
```

**Verify connection**:
```bash
psql "$TRACEABILITY_DB_URL_EXTERNAL" -c "SELECT 1"
```

---

## Step 3: Initialize Database Schema

```bash
# Run migrations
cd ${ARCHON_ROOT}
docker compose exec intelligence alembic upgrade head

# Verify tables exist
docker exec archon-postgres psql -U postgres -d archon -c "\dt pattern_*"
docker exec archon-postgres psql -U postgres -d archon -c "\dt execution_*"
```

**Expected tables**:
- `execution_traces`
- `hook_executions`
- `pattern_lineage_nodes`
- `pattern_lineage_edges`
- `pattern_lineage_events`
- `pattern_ancestry_cache`

---

## Step 4: Test Pattern Tracking

**Create a test pattern**:
```bash
curl -X POST http://localhost:8053/api/pattern-traceability/lineage/track \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "pattern_created",
    "pattern_id": "test_pattern_v1",
    "pattern_name": "Test Pattern",
    "pattern_type": "code",
    "pattern_version": "1.0.0",
    "pattern_data": {"code": "def hello(): pass"},
    "triggered_by": "quickstart_test"
  }'
```

**Expected output**:
```json
{
  "success": true,
  "data": {
    "node_id": "550e8400-e29b-41d4-a716-446655440000",
    "pattern_id": "test_pattern_v1",
    "generation": 0,
    "event_recorded": true
  }
}
```

**Verify in database**:
```bash
docker exec archon-postgres psql -U postgres -d archon \
  -c "SELECT pattern_id, pattern_name, pattern_version FROM pattern_lineage_nodes WHERE pattern_id = 'test_pattern_v1';"
```

---

## Step 5: Test Execution Tracing

**Python test**:
```python
import asyncio
from uuid import uuid4
import sys
sys.path.append('${HOME}/.claude/hooks')

from lib.tracing.tracer import ExecutionTracer

async def test_tracing():
    tracer = ExecutionTracer()

    # Start trace
    session_id = str(uuid4())
    corr_id = await tracer.start_trace(
        source="quickstart_test",
        prompt_text="Test execution trace",
        session_id=session_id,
        tags=["test", "quickstart"]
    )
    print(f"✓ Started trace: {corr_id}")

    # Track hook
    await tracer.track_hook_execution(
        correlation_id=corr_id,
        hook_name="test_hook",
        tool_name="Write",
        duration_ms=50.5,
        success=True
    )
    print("✓ Tracked hook execution")

    # Complete trace
    await tracer.complete_trace(corr_id, success=True)
    print("✓ Completed trace")

    # Close tracer
    await tracer.close()

asyncio.run(test_tracing())
```

**Run test**:
```bash
python quickstart_test.py
```

**Verify in database**:
```bash
docker exec archon-postgres psql -U postgres -d archon \
  -c "SELECT count(*) FROM execution_traces WHERE source = 'quickstart_test';"

docker exec archon-postgres psql -U postgres -d archon \
  -c "SELECT count(*) FROM hook_executions WHERE hook_name = 'test_hook';"
```

---

## Step 6: Monitor Logs

```bash
# Hook execution log (lightweight, every hook trigger)
tail -f ~/.claude/hooks/logs/hook_executions.log

# Quality enforcer log (detailed diagnostics)
tail -f ~/.claude/hooks/logs/quality_enforcer.log

# Intelligence service log
docker compose logs -f intelligence
```

---

## Step 7: Query Pattern Analytics

**Query pattern lineage**:
```bash
curl http://localhost:8053/api/pattern-traceability/lineage/test_pattern_v1
```

**Compute usage analytics**:
```bash
curl -X POST http://localhost:8053/api/pattern-traceability/analytics/compute \
  -H "Content-Type: application/json" \
  -d '{
    "pattern_id": "test_pattern_v1",
    "time_window_type": "weekly",
    "include_performance": true,
    "include_trends": true
  }'
```

---

## Verification Checklist

✅ **Phase 4 service health**: `curl http://localhost:8053/api/pattern-traceability/health`
✅ **Database connection**: `psql "$TRACEABILITY_DB_URL_EXTERNAL" -c "SELECT 1"`
✅ **Tables created**: `\dt pattern_*` and `\dt execution_*` show all tables
✅ **Pattern tracking works**: Test pattern created successfully
✅ **Execution tracing works**: Test trace created successfully
✅ **Logs are being written**: Files exist in `~/.claude/hooks/logs/`
✅ **Analytics work**: Analytics endpoint returns data

---

## Common Quick Fixes

### Database Connection Failed

```bash
# Check if PostgreSQL is running
docker compose ps postgres

# Start if not running
docker compose up -d postgres

# Test connection
psql "$TRACEABILITY_DB_URL_EXTERNAL" -c "SELECT 1"
```

### Phase 4 Service Not Responding

```bash
# Check service status
docker compose ps intelligence

# Restart service
docker compose restart intelligence

# Check logs for errors
docker compose logs intelligence | tail -50
```

### Tables Don't Exist

```bash
# Run migrations
cd ${ARCHON_ROOT}
docker compose exec intelligence alembic upgrade head
```

### Can't Import Tracer

```bash
# Verify hooks directory
ls -la ${HOME}/.claude/hooks/lib/tracing/

# Verify Python can find module
python -c "import sys; sys.path.append('${HOME}/.claude/hooks'); from lib.tracing.tracer import ExecutionTracer; print('OK')"
```

---

## What's Next?

### Integration with Claude Code Hooks

1. **Read the integration guide**: `PHASE4_INTEGRATION_GUIDE.md`
2. **Explore API details**: `API_REFERENCE.md`
3. **Learn troubleshooting**: `TROUBLESHOOTING.md`

### Start Tracking Real Patterns

The integration automatically tracks patterns when you:
- Use Claude Code to write files
- Edit existing code
- Run quality checks
- Perform RAG queries

All execution data flows into PostgreSQL and becomes available for:
- Pattern lineage tracking
- Usage analytics
- Feedback loop optimization
- A/B testing

### Monitor Your System

**Dashboard queries**:
```sql
-- Total patterns tracked today
SELECT count(*) FROM pattern_lineage_nodes
WHERE created_at > CURRENT_DATE;

-- Total executions today
SELECT count(*) FROM execution_traces
WHERE created_at > CURRENT_DATE;

-- Average hook execution time today
SELECT round(avg(duration_ms)::numeric, 2) as avg_ms
FROM hook_executions
WHERE created_at > CURRENT_DATE AND duration_ms IS NOT NULL;

-- Top 5 most used patterns this week
SELECT
  pattern_id,
  count(*) as usage_count
FROM pattern_lineage_events
WHERE created_at > CURRENT_DATE - 7
GROUP BY pattern_id
ORDER BY count(*) DESC
LIMIT 5;
```

**Real-time monitoring**:
```bash
# Watch traces being created
watch -n 1 "docker exec archon-postgres psql -U postgres -d archon \
  -c \"SELECT count(*) FROM execution_traces WHERE created_at > now() - interval '1 minute';\""

# Watch hook executions
watch -n 1 "docker exec archon-postgres psql -U postgres -d archon \
  -c \"SELECT count(*) FROM hook_executions WHERE created_at > now() - interval '1 minute';\""
```

---

## Configuration Tips

### Optimize for Your Environment

**Low-latency setup** (local development):
```yaml
# ~/.claude/hooks/config.yaml
enforcement:
  performance_budget_seconds: 1.0  # Strict budget

rag:
  timeout_seconds: 0.3  # Fast RAG

quorum:
  enabled: false  # Disable for speed
```

**High-quality setup** (production):
```yaml
# ~/.claude/hooks/config.yaml
enforcement:
  performance_budget_seconds: 5.0  # Generous budget
  mode: "block"  # Block violations

rag:
  enabled: true
  timeout_seconds: 1.0

quorum:
  enabled: true  # Multi-model consensus
  thresholds:
    auto_apply: 0.90  # High confidence
```

**Balanced setup** (recommended):
```yaml
# ~/.claude/hooks/config.yaml
enforcement:
  performance_budget_seconds: 2.0
  mode: "warn"  # Warn but don't block

rag:
  enabled: true
  timeout_seconds: 0.5

quorum:
  enabled: true
  thresholds:
    auto_apply: 0.80
```

---

## Support

### Quick Help

- **Health check fails**: See `TROUBLESHOOTING.md` → "Service Connectivity"
- **Database errors**: See `TROUBLESHOOTING.md` → "Database Problems"
- **Slow performance**: See `TROUBLESHOOTING.md` → "Performance Issues"
- **Pattern not tracked**: See `TROUBLESHOOTING.md` → "Pattern Not Tracked"

### Documentation

- **Full integration guide**: `PHASE4_INTEGRATION_GUIDE.md`
- **API reference**: `API_REFERENCE.md`
- **Troubleshooting**: `TROUBLESHOOTING.md`

### Diagnostics

Run the comprehensive health check:
```bash
# Save and run this script
cat > ~/check_phase4.sh << 'EOF'
#!/bin/bash
echo "=== Phase 4 Health Check ==="
echo

echo "1. Service Health:"
curl -s http://localhost:8053/api/pattern-traceability/health | jq .

echo
echo "2. Database Connection:"
timeout 3 psql "$TRACEABILITY_DB_URL_EXTERNAL" -c "SELECT 1" 2>&1

echo
echo "3. Recent Activity:"
docker exec archon-postgres psql -U postgres -d archon -c "
  SELECT
    count(*) FILTER (WHERE created_at > now() - interval '1 hour') as traces_last_hour,
    count(*) as total_traces
  FROM execution_traces;
"

echo
echo "4. Hook Performance:"
docker exec archon-postgres psql -U postgres -d archon -c "
  SELECT
    round(avg(duration_ms)::numeric, 2) as avg_ms,
    round(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)::numeric, 2) as p95_ms
  FROM hook_executions
  WHERE created_at > now() - interval '1 hour' AND duration_ms IS NOT NULL;
"

echo
echo "✓ Health check complete"
EOF

chmod +x ~/check_phase4.sh
~/check_phase4.sh
```

---

## Success Criteria

You're all set when:

✅ Health check returns "healthy"
✅ Test pattern tracked successfully
✅ Test trace created successfully
✅ Database contains data
✅ Logs are being written
✅ No errors in service logs
✅ Queries return expected data

**Time to success**: ~5 minutes

**Next steps**: Start using Claude Code with automatic pattern tracking!

---

**End of Quick Start Guide**

Pattern learning is now active. Happy coding! 🚀
