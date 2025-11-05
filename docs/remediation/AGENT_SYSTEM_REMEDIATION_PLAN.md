# Agent System Remediation Plan
**Generated**: 2025-11-04 21:30 UTC
**Status**: READY FOR EXECUTION
**Estimated Time**: 15-20 minutes
**Priority**: CRITICAL

---

## Executive Summary

**Current State**: Agent system is critically broken with ZERO observability and 100% routing failures.

**Target State**: Fully operational agent system with complete observability and event-based routing.

**Impact**:
- Restore visibility into all agent decisions
- Enable event-based routing (eliminate 5000ms timeouts)
- Restore metrics recording for performance analysis
- Fix 3 unhealthy services

---

## Issues Identified

### 🔴 Critical Issues (4)

1. **Database Schema Incomplete**
   - Only 17 of 34 tables exist
   - ALL agent observability tables missing
   - Root Cause: Migration 008 not applied
   - Impact: ZERO traceability, ZERO metrics

2. **Agent Router Service Not Running**
   - Container `omniclaude_archon_router_consumer` doesn't exist
   - Root Cause: Missing environment variables in docker-compose
   - Impact: 100% routing timeouts (5000ms), all fallback to 0.5 confidence

3. **Service Health Degradation**
   - 3 services unhealthy: archon-bridge, archon-search, archon-langextract
   - Root Cause: Incorrect memgraph hostname (`memgraph` vs `archon-memgraph`)
   - Impact: Reduced intelligence service functionality

4. **Event Processing Stopped**
   - 224 events unprocessed (last 24h)
   - Processing stopped ~2.5 hours ago
   - Impact: No event-driven workflows

---

## Remediation Steps

### Step 1: Apply Database Migration 008
**Priority**: CRITICAL
**Time**: 2 minutes
**Dependencies**: None

**Action**:
```bash
PGPASSWORD='omninode_remote_2024_secure' psql \
  -h 192.168.86.200 \
  -p 5436 \
  -U postgres \
  -d omninode_bridge \
  -f agents/parallel_execution/migrations/008_agent_manifest_traceability.sql
```

**Creates Tables**:
- `agent_routing_decisions`
- `agent_manifest_injections`
- `agent_execution_logs`
- `agent_actions`
- `router_performance_metrics`
- `agent_transformation_events`

**Verification**:
```bash
PGPASSWORD='omninode_remote_2024_secure' psql \
  -h 192.168.86.200 \
  -p 5436 \
  -U postgres \
  -d omninode_bridge \
  -c "\dt agent_*"
```

**Success Criteria**: All 6 agent tables created

---

### Step 2: Fix Docker-Compose Environment Variables
**Priority**: CRITICAL
**Time**: 3 minutes
**Dependencies**: None

**Action**:
Update `.env` file with missing variables:
```bash
# Add to .env file:
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_USER=postgres
POSTGRES_DATABASE=omninode_bridge
POSTGRES_PASSWORD=omninode_remote_2024_secure
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:9092
```

**Alternative**: Export before docker-compose:
```bash
export POSTGRES_HOST=192.168.86.200
export POSTGRES_PORT=5436
export POSTGRES_USER=postgres
export POSTGRES_DATABASE=omninode_bridge
export POSTGRES_PASSWORD='omninode_remote_2024_secure'
export KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:9092
```

**Verification**: Check env vars are set:
```bash
echo $POSTGRES_HOST
echo $POSTGRES_PORT
```

**Success Criteria**: All variables set correctly

---

### Step 3: Start Agent Router Consumer Service
**Priority**: CRITICAL
**Time**: 2 minutes
**Dependencies**: Step 1 (database tables), Step 2 (env vars)

**Action**:
```bash
cd /Volumes/PRO-G40/Code/omniclaude
docker-compose -f deployment/docker-compose.yml up -d archon-router-consumer
```

**Verification**:
```bash
# Check container running
docker ps | grep router-consumer

# Check logs for startup success
docker logs omniclaude_archon_router_consumer --tail 50

# Check consuming from Kafka
docker logs omniclaude_archon_router_consumer | grep "subscribed to topic"
```

**Success Criteria**:
- Container running and healthy
- Logs show Kafka subscription successful
- No errors in logs

---

### Step 4: Fix Memgraph Hostname in Docker-Compose
**Priority**: HIGH
**Time**: 3 minutes
**Dependencies**: None

**File**: `deployment/docker-compose.archon-intelligence.yml` (or wherever archon services are defined)

**Changes Required**:
Find all instances of `MEMGRAPH_URI=bolt://memgraph:7687` and change to:
```yaml
environment:
  MEMGRAPH_URI: bolt://archon-memgraph:7687
```

**Affected Services**:
- archon-bridge
- archon-search
- archon-langextract

**Alternative Solution** (if can't modify docker-compose):
Add network alias to archon-memgraph service:
```yaml
archon-memgraph:
  networks:
    app-network:
      aliases:
        - memgraph
```

**Apply Changes**:
```bash
docker-compose -f deployment/docker-compose.archon-intelligence.yml restart archon-bridge
docker-compose -f deployment/docker-compose.archon-intelligence.yml restart archon-search
docker-compose -f deployment/docker-compose.archon-intelligence.yml restart archon-langextract
```

**Verification**:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "(archon-bridge|archon-search|archon-langextract)"
```

**Success Criteria**: All 3 services show "healthy" status

---

### Step 5: Verify End-to-End System Health
**Priority**: HIGH
**Time**: 5 minutes
**Dependencies**: Steps 1-4 complete

**Action**:
```bash
# Run health check script
./scripts/health_check.sh

# Check database tables have data
PGPASSWORD='omninode_remote_2024_secure' psql \
  -h 192.168.86.200 \
  -p 5436 \
  -U postgres \
  -d omninode_bridge \
  -c "SELECT COUNT(*) FROM agent_routing_decisions;"

# Check routing is working (should see data from last 5 min)
PGPASSWORD='omninode_remote_2024_secure' psql \
  -h 192.168.86.200 \
  -p 5436 \
  -U postgres \
  -d omninode_bridge \
  -c "SELECT correlation_id, selected_agent, confidence_score, routing_time_ms, created_at
      FROM agent_routing_decisions
      WHERE created_at > NOW() - INTERVAL '5 minutes'
      ORDER BY created_at DESC
      LIMIT 5;"

# Check manifest injections (should see data from last 5 min)
PGPASSWORD='omninode_remote_2024_secure' psql \
  -h 192.168.86.200 \
  -p 5436 \
  -U postgres \
  -d omninode_bridge \
  -c "SELECT correlation_id, patterns_count, total_query_time_ms, created_at
      FROM agent_manifest_injections
      WHERE created_at > NOW() - INTERVAL '5 minutes'
      ORDER BY created_at DESC
      LIMIT 5;"
```

**Success Criteria**:
- ✅ Health check script exits 0 (no errors)
- ✅ agent_routing_decisions has rows from last 5 minutes
- ✅ agent_manifest_injections has rows from last 5 minutes
- ✅ Routing time <100ms (not 5000ms timeout)
- ✅ Confidence scores >0.5 (not fallback)
- ✅ All services healthy

---

## Execution Order (Sequential vs Parallel)

### Can Run in Parallel:
- ✅ Step 1 (Apply migration)
- ✅ Step 2 (Fix env vars)
- ✅ Step 4 (Fix memgraph hostname)

### Must Run Sequential:
- Step 3 depends on Steps 1 & 2 (needs DB tables and env vars)
- Step 5 depends on all previous steps (verification)

### Recommended Execution:
1. **Parallel Wave 1**: Run Steps 1, 2, 4 simultaneously
2. **Sequential**: Run Step 3 after Steps 1 & 2 complete
3. **Sequential**: Run Step 5 after all complete

---

## Rollback Plan

If anything fails:

**Rollback Step 1 (Database)**:
```bash
# Drop created tables
PGPASSWORD='omninode_remote_2024_secure' psql \
  -h 192.168.86.200 \
  -p 5436 \
  -U postgres \
  -d omninode_bridge \
  -c "DROP TABLE IF EXISTS agent_routing_decisions, agent_manifest_injections,
      agent_execution_logs, agent_actions, router_performance_metrics,
      agent_transformation_events CASCADE;"
```

**Rollback Step 3 (Router Consumer)**:
```bash
docker stop omniclaude_archon_router_consumer
docker rm omniclaude_archon_router_consumer
```

**Rollback Step 4 (Memgraph)**:
```bash
# Revert docker-compose.yml changes
git checkout deployment/docker-compose.archon-intelligence.yml

# Restart services
docker-compose -f deployment/docker-compose.archon-intelligence.yml restart archon-bridge archon-search archon-langextract
```

---

## Expected Outcomes

**Before**:
- Database: 17/34 tables (50% missing)
- Routing: 100% timeout (5000ms), 0.5 confidence (fallback)
- Observability: ZERO visibility
- Services: 3 unhealthy
- Event Processing: 0% (224 unprocessed)

**After**:
- Database: 34/34 tables (100% complete)
- Routing: <100ms response, >0.5 confidence (intelligent)
- Observability: FULL visibility (all metrics captured)
- Services: 0 unhealthy (all healthy)
- Event Processing: >90% success rate

**Metrics Improvement**:
- Routing time: 5000ms → <100ms (98% improvement)
- Observability coverage: 0% → 100%
- Service health: 75% → 100%
- Event processing: 0% → 90%+

---

## Post-Remediation Tasks

1. **Monitor for 24 hours**:
   - Check routing decisions accumulating
   - Verify no timeouts
   - Monitor service health

2. **Update Documentation**:
   - Update CLAUDE.md with actual table count (34 not 34)
   - Update pattern count (14,638 not 120)
   - Document migration 008 applied

3. **Performance Baseline**:
   - Capture routing performance metrics
   - Document cache hit rates
   - Track manifest injection quality

---

## Files to Modify

1. `.env` - Add missing environment variables
2. `deployment/docker-compose.archon-intelligence.yml` - Fix MEMGRAPH_URI
3. Database - Apply migration 008

---

## Commands Reference

**Quick Start (All Steps)**:
```bash
# Step 1: Apply migration
PGPASSWORD='omninode_remote_2024_secure' psql -h 192.168.86.200 -p 5436 \
  -U postgres -d omninode_bridge \
  -f agents/parallel_execution/migrations/008_agent_manifest_traceability.sql

# Step 2: Set env vars (add to .env)
cat >> .env << 'EOF'
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_USER=postgres
POSTGRES_DATABASE=omninode_bridge
POSTGRES_PASSWORD=omninode_remote_2024_secure
EOF

# Step 3: Start router
source .env
docker-compose -f deployment/docker-compose.yml up -d archon-router-consumer

# Step 4: Fix memgraph (requires manual edit, then restart)
# Edit deployment/docker-compose.archon-intelligence.yml
# Change memgraph:7687 to archon-memgraph:7687
docker-compose -f deployment/docker-compose.archon-intelligence.yml restart archon-bridge archon-search archon-langextract

# Step 5: Verify
./scripts/health_check.sh
```

---

**Plan Status**: READY FOR EXECUTION
**Next Action**: Execute via /parallel-solve
**Estimated Completion**: 2025-11-04 21:45 UTC (~15 minutes from now)
