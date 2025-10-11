# Phase 4 Pattern Traceability Troubleshooting Guide

**Version**: 1.0.0
**Last Updated**: 2025-10-03

---

## Table of Contents

1. [Common Issues](#common-issues)
2. [Diagnostic Commands](#diagnostic-commands)
3. [Log Analysis](#log-analysis)
4. [Performance Issues](#performance-issues)
5. [Database Problems](#database-problems)
6. [Service Connectivity](#service-connectivity)
7. [Debug Mode](#debug-mode)

---

## Common Issues

### Issue 1: Pattern Not Tracked

**Symptoms**:
- Patterns created but not appearing in database
- `POST /lineage/track` returns success but no data in database
- Ancestry queries return empty results

**Possible Causes**:
1. Phase 4 service not running
2. Database connection not configured
3. Circuit breaker open (too many failures)
4. Silent failure in background task

**Diagnosis**:

```bash
# 1. Check Phase 4 service health
curl http://localhost:8053/api/pattern-traceability/health

# 2. Check database connection
docker exec archon-postgres psql -U postgres -d archon -c "\dt pattern_*"

# 3. Check for errors in logs
tail -f ~/.claude/hooks/logs/quality_enforcer.log | grep -i error

# 4. Query database directly
docker exec archon-postgres psql -U postgres -d archon \
  -c "SELECT count(*) FROM pattern_lineage_nodes WHERE created_at > now() - interval '1 hour';"
```

**Solutions**:

1. **Start Phase 4 service**:
```bash
cd /Volumes/PRO-G40/Code/Archon
docker compose up -d intelligence
```

2. **Configure database connection**:
```bash
export TRACEABILITY_DB_URL_EXTERNAL="postgresql://user:pass@host:5432/archon"
```

3. **Reset circuit breaker** (if using one):
```bash
rm ~/.claude/hooks/.cache/circuit_state.json
```

4. **Enable debug logging**:
```yaml
# ~/.claude/hooks/config.yaml
logging:
  level: "DEBUG"
```

---

### Issue 2: Database Not Updated

**Symptoms**:
- Traces created but no records in database
- `execution_traces` table is empty
- Hook executions not logged

**Possible Causes**:
1. PostgreSQL not running
2. Database connection string incorrect
3. Database schema not initialized
4. Connection pool exhausted

**Diagnosis**:

```bash
# 1. Check PostgreSQL is running
docker ps | grep postgres

# 2. Verify database connection
psql "$TRACEABILITY_DB_URL_EXTERNAL" -c "SELECT 1"

# 3. Check if tables exist
docker exec archon-postgres psql -U postgres -d archon \
  -c "\dt execution_traces"

# 4. Check connection pool status
docker compose logs intelligence | grep -i "pool"
```

**Solutions**:

1. **Start PostgreSQL**:
```bash
docker compose up -d postgres
```

2. **Fix connection string**:
```bash
# Check current value
echo $TRACEABILITY_DB_URL_EXTERNAL

# Set correct value
export TRACEABILITY_DB_URL_EXTERNAL="postgresql://postgres:password@localhost:5432/archon"
```

3. **Initialize database schema**:
```bash
cd /Volumes/PRO-G40/Code/Archon
docker compose exec intelligence alembic upgrade head
```

4. **Restart services to reset connection pool**:
```bash
docker compose restart intelligence
```

---

### Issue 3: Performance Issues

**Symptoms**:
- Hook execution taking >2 seconds
- Database queries timing out
- High CPU usage during tracing

**Possible Causes**:
1. Missing database indexes
2. Too many connections
3. Slow network to database
4. Large payload sizes

**Diagnosis**:

```bash
# 1. Check query performance
docker exec archon-postgres psql -U postgres -d archon \
  -c "SELECT query, mean_exec_time, calls FROM pg_stat_statements
      WHERE query LIKE '%execution_traces%'
      ORDER BY mean_exec_time DESC LIMIT 10;"

# 2. Check connection count
docker exec archon-postgres psql -U postgres -d archon \
  -c "SELECT count(*) FROM pg_stat_activity WHERE datname = 'archon';"

# 3. Measure hook execution time
tail -f ~/.claude/hooks/logs/hook_executions.log | grep duration_ms

# 4. Check database size
docker exec archon-postgres psql -U postgres -d archon \
  -c "SELECT pg_size_pretty(pg_database_size('archon'));"
```

**Solutions**:

1. **Create missing indexes**:
```sql
-- Run in PostgreSQL
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_execution_traces_correlation
  ON execution_traces(correlation_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_execution_traces_session
  ON execution_traces(session_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hook_executions_trace
  ON hook_executions(trace_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hook_executions_order
  ON hook_executions(trace_id, execution_order);
```

2. **Adjust connection pool size**:
```python
# In PostgresTracingClient initialization
client = PostgresTracingClient(
    min_pool_size=10,  # Increase from 5
    max_pool_size=30   # Increase from 20
)
```

3. **Reduce payload sizes**:
```yaml
# ~/.claude/hooks/config.yaml
enforcement:
  # Reduce max violations to log
  validation:
    max_violations_per_file: 20  # Down from 50
```

4. **Archive old data**:
```sql
-- Archive traces older than 30 days
DELETE FROM execution_traces
WHERE created_at < now() - interval '30 days';
```

---

### Issue 4: Hook Timeout

**Symptoms**:
- Hook execution exceeds performance budget
- "Timeout exceeded" errors in logs
- Claude Code becomes unresponsive

**Possible Causes**:
1. Database query taking too long
2. Network latency to services
3. RAG query timeout
4. AI quorum timeout

**Diagnosis**:

```bash
# 1. Check hook execution times
tail -f ~/.claude/hooks/logs/hook_executions.log | \
  awk '{if ($NF > 2000) print}'  # Show hooks > 2s

# 2. Check database query times
docker compose logs intelligence | grep "processing_time_ms" | \
  awk -F'processing_time_ms.:' '{print $2}' | \
  awk -F',' '{if ($1 > 2000) print $1}'

# 3. Test RAG endpoint
time curl -X POST http://localhost:8181/api/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "match_count": 3}'

# 4. Test Phase 4 endpoint
time curl http://localhost:8053/api/pattern-traceability/health
```

**Solutions**:

1. **Increase performance budget**:
```yaml
# ~/.claude/hooks/config.yaml
enforcement:
  performance_budget_seconds: 5.0  # Increase from 2.0
```

2. **Reduce RAG timeout**:
```yaml
# ~/.claude/hooks/config.yaml
rag:
  timeout_seconds: 0.3  # Reduce from 0.5
```

3. **Disable slow components temporarily**:
```yaml
# ~/.claude/hooks/config.yaml
quorum:
  enabled: false  # Disable AI quorum

rag:
  enabled: false  # Disable RAG
```

4. **Use faster models**:
```yaml
# ~/.claude/hooks/config.yaml
quorum:
  models:
    pro:
      enabled: false  # Disable slow pro model
```

---

### Issue 5: Circuit Breaker Open

**Symptoms**:
- Patterns not tracked despite service being healthy
- "Circuit breaker open" messages in logs
- Tracking requests not reaching Phase 4 API

**Possible Causes**:
1. Too many consecutive failures
2. Circuit breaker threshold too low
3. Transient network issues

**Diagnosis**:

```bash
# 1. Check circuit breaker state
cat ~/.claude/hooks/.cache/circuit_state.json

# 2. Check recent failure rate
tail -100 ~/.claude/hooks/logs/quality_enforcer.log | \
  grep -c "Failed to track pattern"

# 3. Test Phase 4 API directly
for i in {1..10}; do
  curl -w "%{http_code}\n" -o /dev/null -s \
    http://localhost:8053/api/pattern-traceability/health
done
```

**Solutions**:

1. **Reset circuit breaker**:
```bash
rm ~/.claude/hooks/.cache/circuit_state.json
```

2. **Adjust circuit breaker thresholds**:
```python
# In resilience.py (if using circuit breaker)
circuit_breaker = CircuitBreaker(
    failure_threshold=10,  # Increase from 5
    reset_timeout=30       # Reduce from 60
)
```

3. **Monitor and fix underlying issues**:
```bash
# Check Phase 4 service logs for errors
docker compose logs intelligence | tail -100
```

---

## Diagnostic Commands

### System Health Check

```bash
#!/bin/bash
# comprehensive_health_check.sh

echo "=== Phase 4 Pattern Traceability Health Check ==="
echo

echo "1. Phase 4 API Health:"
curl -s http://localhost:8053/api/pattern-traceability/health | jq .
echo

echo "2. Database Connection:"
docker exec archon-postgres pg_isready -U postgres
echo

echo "3. Table Counts:"
docker exec archon-postgres psql -U postgres -d archon -c "
  SELECT
    'execution_traces' as table_name, count(*) as count
  FROM execution_traces
  UNION ALL
  SELECT
    'hook_executions' as table_name, count(*) as count
  FROM hook_executions
  UNION ALL
  SELECT
    'pattern_lineage_nodes' as table_name, count(*) as count
  FROM pattern_lineage_nodes;
"
echo

echo "4. Recent Activity (last hour):"
docker exec archon-postgres psql -U postgres -d archon -c "
  SELECT count(*) as recent_traces
  FROM execution_traces
  WHERE created_at > now() - interval '1 hour';
"
echo

echo "5. Average Hook Duration:"
docker exec archon-postgres psql -U postgres -d archon -c "
  SELECT
    round(avg(duration_ms)::numeric, 2) as avg_duration_ms,
    round(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)::numeric, 2) as p95_duration_ms
  FROM hook_executions
  WHERE created_at > now() - interval '1 hour'
    AND duration_ms IS NOT NULL;
"
echo

echo "6. Error Rate (last hour):"
docker exec archon-postgres psql -U postgres -d archon -c "
  SELECT
    count(*) FILTER (WHERE status = 'failed') as failures,
    count(*) as total,
    round(100.0 * count(*) FILTER (WHERE status = 'failed') / count(*), 2) as failure_rate_pct
  FROM hook_executions
  WHERE created_at > now() - interval '1 hour';
"
```

### Quick Diagnostics

```bash
# Check if services are running
docker compose ps | grep -E "intelligence|postgres"

# Check logs for errors (last 5 minutes)
docker compose logs --since 5m intelligence | grep -i error

# Check database connectivity
timeout 3 psql "$TRACEABILITY_DB_URL_EXTERNAL" -c "SELECT 1" 2>&1

# Check hook execution log
tail -20 ~/.claude/hooks/logs/hook_executions.log

# Check Phase 4 API responsiveness
time curl -s http://localhost:8053/api/pattern-traceability/health > /dev/null
```

---

## Log Analysis

### Log Locations

```bash
# Hook execution log (lightweight)
~/.claude/hooks/logs/hook_executions.log

# Quality enforcer log (detailed)
~/.claude/hooks/logs/quality_enforcer.log

# Intelligence service log
docker compose logs intelligence

# PostgreSQL log
docker compose logs postgres
```

### Useful Log Queries

**Find slow hook executions**:
```bash
tail -1000 ~/.claude/hooks/logs/hook_executions.log | \
  awk '{if ($NF > 2000) print}' | \
  sort -k12 -rn
```

**Find errors in quality enforcer**:
```bash
tail -500 ~/.claude/hooks/logs/quality_enforcer.log | \
  grep -i "error\|exception\|failed"
```

**Find database connection errors**:
```bash
docker compose logs intelligence | \
  grep -i "database\|connection\|pool" | \
  tail -50
```

**Find pattern tracking failures**:
```bash
docker compose logs intelligence | \
  grep -i "pattern.*failed\|lineage.*error" | \
  tail -50
```

**Analyze hook execution distribution**:
```bash
# Group by hook name, show count and avg duration
tail -1000 ~/.claude/hooks/logs/hook_executions.log | \
  awk '{print $8, $NF}' | \
  awk '{sum[$1]+=$2; count[$1]++} END {for (hook in sum) print hook, count[hook], sum[hook]/count[hook]}' | \
  sort -k3 -rn
```

---

## Performance Issues

### Slow Database Queries

**Problem**: Queries taking >100ms

**Diagnosis**:
```sql
-- Enable query logging
ALTER SYSTEM SET log_min_duration_statement = 100;
SELECT pg_reload_conf();

-- View slow queries
SELECT
  query,
  calls,
  total_exec_time,
  mean_exec_time,
  max_exec_time
FROM pg_stat_statements
WHERE mean_exec_time > 100
ORDER BY mean_exec_time DESC
LIMIT 20;
```

**Solution**:
```sql
-- Add missing indexes
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_execution_traces_created
  ON execution_traces(created_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hook_executions_created
  ON hook_executions(created_at DESC);

-- Analyze tables for better query planning
ANALYZE execution_traces;
ANALYZE hook_executions;
ANALYZE pattern_lineage_nodes;
ANALYZE pattern_lineage_edges;
```

### High Memory Usage

**Problem**: Service consuming excessive memory

**Diagnosis**:
```bash
# Check service memory usage
docker stats archon-intelligence --no-stream

# Check connection pool size
docker exec archon-postgres psql -U postgres -d archon -c "
  SELECT count(*), state
  FROM pg_stat_activity
  WHERE datname = 'archon'
  GROUP BY state;
"

# Check Python memory usage
docker compose exec intelligence python -c "
import psutil
process = psutil.Process()
print(f'Memory: {process.memory_info().rss / 1024 / 1024:.2f} MB')
"
```

**Solution**:
```python
# Reduce connection pool size
client = PostgresTracingClient(
    min_pool_size=3,   # Reduce from 5
    max_pool_size=10   # Reduce from 20
)

# Implement connection timeout
client = PostgresTracingClient(
    command_timeout=5.0  # Reduce from 10.0
)
```

---

## Database Problems

### Missing Tables

**Problem**: "relation does not exist" errors

**Diagnosis**:
```bash
docker exec archon-postgres psql -U postgres -d archon -c "\dt"
```

**Solution**:
```bash
# Run database migrations
cd /Volumes/PRO-G40/Code/Archon
docker compose exec intelligence alembic upgrade head
```

### Connection Pool Exhausted

**Problem**: "Connection pool exhausted" errors

**Diagnosis**:
```sql
SELECT
  count(*) as active_connections,
  max_connections::int - count(*) as available
FROM pg_stat_activity,
  (SELECT setting::int as max_connections FROM pg_settings WHERE name='max_connections') s;
```

**Solution**:
```bash
# Increase max_connections in PostgreSQL
docker exec archon-postgres psql -U postgres -c "
  ALTER SYSTEM SET max_connections = 200;
"

# Restart PostgreSQL
docker compose restart postgres
```

### Lock Contention

**Problem**: Queries waiting on locks

**Diagnosis**:
```sql
SELECT
  blocked_locks.pid AS blocked_pid,
  blocked_activity.usename AS blocked_user,
  blocking_locks.pid AS blocking_pid,
  blocking_activity.usename AS blocking_user,
  blocked_activity.query AS blocked_statement,
  blocking_activity.query AS blocking_statement
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

**Solution**:
```sql
-- Kill blocking query
SELECT pg_terminate_backend(blocking_pid);

-- Reduce lock contention by using NOWAIT
-- (implement in application code)
```

---

## Service Connectivity

### Can't Reach Phase 4 API

**Problem**: Connection refused or timeout

**Diagnosis**:
```bash
# Check if service is running
docker compose ps intelligence

# Check if port is listening
netstat -an | grep 8053

# Test connectivity
curl -v http://localhost:8053/api/pattern-traceability/health

# Check Docker network
docker network inspect archon_default
```

**Solution**:
```bash
# Start service
docker compose up -d intelligence

# Check logs for startup errors
docker compose logs intelligence | tail -50

# Restart service
docker compose restart intelligence
```

### Database Connection Refused

**Problem**: Can't connect to PostgreSQL

**Diagnosis**:
```bash
# Check if PostgreSQL is running
docker compose ps postgres

# Test connection
psql "$TRACEABILITY_DB_URL_EXTERNAL" -c "SELECT 1"

# Check PostgreSQL logs
docker compose logs postgres | tail -50
```

**Solution**:
```bash
# Start PostgreSQL
docker compose up -d postgres

# Wait for PostgreSQL to be ready
docker compose exec postgres pg_isready -U postgres

# Fix connection string
export TRACEABILITY_DB_URL_EXTERNAL="postgresql://postgres:password@localhost:5432/archon"
```

---

## Debug Mode

### Enable Debug Logging

**Hook System**:
```yaml
# ~/.claude/hooks/config.yaml
logging:
  level: "DEBUG"
```

**Intelligence Service**:
```bash
# Set environment variable
export LOG_LEVEL=DEBUG

# Restart service
docker compose restart intelligence
```

### Trace Individual Requests

```bash
# Enable query logging in PostgreSQL
docker exec archon-postgres psql -U postgres -c "
  ALTER SYSTEM SET log_statement = 'all';
  SELECT pg_reload_conf();
"

# Watch queries in real-time
docker compose logs -f postgres | grep "LOG:"
```

### Monitor Network Traffic

```bash
# Install tcpdump in container
docker compose exec intelligence apt-get update && apt-get install -y tcpdump

# Monitor traffic to PostgreSQL
docker compose exec intelligence tcpdump -i any -n port 5432
```

### Python Debugging

```python
# Add to intelligence service code
import pdb; pdb.set_trace()

# Or use remote debugger
import debugpy
debugpy.listen(5678)
debugpy.wait_for_client()
```

---

## Emergency Procedures

### Complete System Reset

```bash
#!/bin/bash
# emergency_reset.sh

echo "WARNING: This will reset all Phase 4 data!"
read -p "Continue? (yes/no): " confirm
[ "$confirm" != "yes" ] && exit 1

# Stop services
docker compose stop intelligence

# Clear cache
rm -rf ~/.claude/hooks/.cache/*

# Reset database
docker exec archon-postgres psql -U postgres -d archon -c "
  TRUNCATE execution_traces CASCADE;
  TRUNCATE pattern_lineage_nodes CASCADE;
"

# Restart services
docker compose up -d intelligence

echo "System reset complete"
```

### Data Recovery

```bash
# Backup current state
docker exec archon-postgres pg_dump -U postgres archon > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore from backup
docker exec -i archon-postgres psql -U postgres archon < backup_20250303_100000.sql
```

---

## Getting Help

### Information to Collect

When reporting issues, please provide:

1. **Service versions**:
```bash
docker compose exec intelligence python --version
docker exec archon-postgres psql --version
```

2. **Service status**:
```bash
docker compose ps
curl http://localhost:8053/api/pattern-traceability/health
```

3. **Recent logs**:
```bash
tail -100 ~/.claude/hooks/logs/quality_enforcer.log
docker compose logs --tail=100 intelligence
```

4. **Database state**:
```bash
docker exec archon-postgres psql -U postgres -d archon -c "
  SELECT count(*) FROM execution_traces;
  SELECT count(*) FROM hook_executions;
  SELECT count(*) FROM pattern_lineage_nodes;
"
```

5. **Configuration**:
```bash
cat ~/.claude/hooks/config.yaml
env | grep -E "TRACEABILITY|SUPABASE|INTELLIGENCE"
```

### Support Channels

- **Documentation**: Check `PHASE4_INTEGRATION_GUIDE.md` and `API_REFERENCE.md`
- **Health Checks**: Monitor `/health` endpoints
- **Logs**: Review detailed logs in `~/.claude/hooks/logs/`
- **Database**: Query PostgreSQL directly for trace data

---

**End of Troubleshooting Guide**

For integration details, see `PHASE4_INTEGRATION_GUIDE.md`
For API details, see `API_REFERENCE.md`
For quick start, see `PHASE4_QUICKSTART.md`
