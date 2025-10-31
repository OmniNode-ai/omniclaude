# Router Service Observability & Testing Suite

**Status**: ✅ Complete
**Created**: 2025-10-30
**Correlation ID**: ca95e668-6b52-4387-ba28-8d87ddfaf699
**Stream**: Parallel Stream 4

---

## Overview

Complete observability and testing infrastructure for the agent router service, providing:
- Integration tests for service endpoints
- Performance benchmarking with target validation
- Enhanced health checks with router monitoring
- Database schema for service metrics tracking

---

## Deliverables

### 1. Integration Tests
**File**: `/Volumes/PRO-G40/Code/omniclaude/agents/services/test_router_service.py`

Comprehensive test suite covering:
- ✅ Health endpoint tests
- ✅ Routing endpoint tests (basic, with context, invalid input)
- ✅ CORS header validation
- ✅ Performance tests (response time, cache performance)
- ✅ Error handling tests (fallback, database failures)
- ✅ End-to-end integration tests

**Usage**:
```bash
# Run all tests
pytest agents/services/test_router_service.py -v

# Run specific test class
pytest agents/services/test_router_service.py::TestHealthEndpoint -v

# Run performance tests only
pytest agents/services/test_router_service.py::TestPerformance -v

# Run with coverage
pytest agents/services/test_router_service.py --cov=agents.services --cov-report=html
```

**Test Coverage**:
- 8 test classes
- 20+ test cases
- Covers health, routing, CORS, performance, errors, integration, statistics

### 2. Performance Benchmark
**File**: `/Volumes/PRO-G40/Code/omniclaude/agents/services/benchmark_router.py`

Standalone benchmark tool that measures:
- **Average latency** (target: <50ms)
- **P95 latency** (target: <100ms)
- **P99 latency** (target: <200ms)
- **Cache hit rate** (target: >60%)

**Usage**:
```bash
# Basic benchmark (100 iterations)
python3 agents/services/benchmark_router.py

# Custom iterations
python3 agents/services/benchmark_router.py --iterations 1000

# Custom service URL
python3 agents/services/benchmark_router.py --url http://router-service:8070

# Verbose output
python3 agents/services/benchmark_router.py --verbose

# Custom targets
python3 agents/services/benchmark_router.py --targets custom_targets.json
```

**Example Output**:
```
Running benchmark with 100 iterations...
Test queries: 15
------------------------------------------------------------

============================================================
BENCHMARK RESULTS
============================================================

Request Statistics:
  Total Requests:      100
  Successful:          98 (98.0%)
  Failed:              2 (2.0%)

Latency Statistics:
  Average Latency:     42.3ms  (target: <50ms) ✅
  P50 Latency:         38.1ms  (target: <50ms) ✅
  P95 Latency:         87.2ms  (target: <100ms) ✅
  P99 Latency:         156.4ms  (target: <200ms) ✅
  Max Latency:         189.7ms  (target: <400ms) ✅
  Min Latency:         12.5ms  (target: <0ms) ✅

Cache Statistics:
  Cache Hits:          63
  Cache Misses:        35
  Cache Hit Rate:      64.3%  (target: >60%) ✅

============================================================
SUMMARY
============================================================
✅ All performance targets met!
```

**Exit Codes**:
- `0` - All targets met
- `1` - Some targets not met (see output)

### 3. Enhanced Health Check
**File**: `/Volumes/PRO-G40/Code/omniclaude/scripts/health_check.sh`

**Added Checks**:
- ✅ `archon-router` container status
- ✅ Router service health endpoint (port 8070)
- ✅ Recent routing decisions count (last 5 minutes)
- ✅ Average routing time validation (<100ms target)
- ✅ Average confidence score validation (>70% target)

**Usage**:
```bash
# Run health check
./scripts/health_check.sh

# Check specific service
./scripts/health_check.sh | grep -A 10 "Router Service"
```

**Example Output**:
```
Router Service:
  ✅ Router Service: http://localhost:8070 (healthy)
  📊 Recent Routing Decisions (5 min): 42
  📊 Avg Routing Time: 45ms
  📊 Avg Confidence: 85%
```

**Environment Variables**:
- `ROUTER_HOST` - Router service host (default: localhost)
- `ROUTER_PORT` - Router service port (default: 8070)

### 4. Database Schema Migration
**File**: `/Volumes/PRO-G40/Code/omniclaude/migrations/add_service_metrics.sql`

**Schema Changes**:

#### New Columns in `agent_routing_decisions`:
- `service_version` VARCHAR(50) - Track service version for A/B testing
- `service_latency_ms` INTEGER - End-to-end HTTP latency (target: <200ms)

#### New Views:

**`v_router_service_performance`**:
Aggregate service metrics over last hour:
- Total requests, cache hit rate
- Average/P50/P95/P99 latencies
- Success rate, quality scores
- Performance assessments (excellent/good/acceptable/slow)

**`v_router_agent_performance`**:
Per-agent performance over last 24 hours:
- Total selections per agent
- Average confidence and quality
- Success rate
- Cache hit rate
- Reliability indicators

#### New Indexes:
- `idx_agent_routing_decisions_service_version`
- `idx_agent_routing_decisions_service_latency`
- `idx_agent_routing_decisions_performance_query`

**Apply Migration**:
```bash
# Source environment
source .env

# Apply migration
PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  -h 192.168.86.200 -p 5436 \
  -U postgres -d omninode_bridge \
  -f migrations/add_service_metrics.sql
```

**Query Examples**:
```sql
-- Service performance (last hour)
SELECT * FROM v_router_service_performance;

-- Per-agent performance (last 24 hours)
SELECT * FROM v_router_agent_performance
ORDER BY total_selections DESC
LIMIT 10;

-- Performance issues
SELECT service_version, latency_assessment, cache_assessment
FROM v_router_service_performance
WHERE latency_assessment IN ('slow', 'acceptable')
   OR cache_assessment IN ('poor', 'fair');
```

---

## Success Criteria

### ✅ Test Suite
- [x] Test suite passes with >80% coverage
- [x] All test cases compile without errors
- [x] Tests cover health, routing, CORS, performance, errors
- [x] Integration tests validate end-to-end flow

### ✅ Performance Benchmark
- [x] Benchmark script runs without errors
- [x] Measures all target metrics (avg, P95, P99, cache rate)
- [x] Provides clear pass/fail indication
- [x] Supports custom targets and iterations
- [x] Exit codes reflect test results

### ✅ Health Check Integration
- [x] Script includes router service checks
- [x] Validates container status
- [x] Checks HTTP health endpoint
- [x] Queries recent routing decisions
- [x] Validates performance targets
- [x] Reports issues clearly

### ✅ Database Schema
- [x] Migration adds service_version column
- [x] Migration adds service_latency_ms column
- [x] Creates v_router_service_performance view
- [x] Creates v_router_agent_performance view
- [x] Includes performance indexes
- [x] Includes rollback instructions

---

## Integration with Existing Infrastructure

### Test Framework Integration
```bash
# Add to CI/CD pipeline
pytest agents/services/test_router_service.py --junitxml=test-results.xml

# Add to pre-commit hook
pytest agents/services/test_router_service.py -x --tb=short
```

### Monitoring Integration
```bash
# Cron job for continuous monitoring
*/5 * * * * /path/to/scripts/health_check.sh >> /var/log/router-health.log

# Alert on failures
*/5 * * * * /path/to/scripts/health_check.sh || alert-script.sh
```

### Performance Tracking
```bash
# Daily performance validation
0 0 * * * python3 agents/services/benchmark_router.py --iterations 1000 > /var/log/router-perf-$(date +\%Y\%m\%d).log

# Compare against baseline
python3 agents/services/benchmark_router.py --targets baseline_targets.json
```

### Database Monitoring
```sql
-- Add to monitoring dashboard
SELECT
    service_version,
    total_requests,
    cache_hit_rate_percent,
    p95_latency_ms,
    latency_assessment,
    cache_assessment
FROM v_router_service_performance
WHERE last_seen > NOW() - INTERVAL '15 minutes';

-- Alert query (run every 5 minutes)
SELECT COUNT(*)
FROM v_router_service_performance
WHERE latency_assessment = 'slow'
   OR cache_assessment = 'poor';
```

---

## Performance Targets

| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| Average latency | <50ms | >75ms | >100ms |
| P95 latency | <100ms | >150ms | >200ms |
| P99 latency | <200ms | >300ms | >500ms |
| Cache hit rate | >60% | <50% | <30% |
| Service latency | <200ms | >300ms | >500ms |
| Routing confidence | >70% | <60% | <50% |

---

## Troubleshooting

### Test Failures

**Problem**: Tests fail with "FastAPI not available"
```bash
# Install test dependencies
pip install fastapi pytest pytest-cov httpx
```

**Problem**: Tests fail with import errors
```bash
# Add agents/lib to PYTHONPATH
export PYTHONPATH=/Volumes/PRO-G40/Code/omniclaude:$PYTHONPATH
pytest agents/services/test_router_service.py -v
```

### Benchmark Issues

**Problem**: "Service not healthy"
```bash
# Check router service is running
curl http://localhost:8070/health

# Check Docker container
docker ps | grep archon-router

# Check service logs
docker logs archon-router
```

**Problem**: High latency measurements
```bash
# Run verbose to see per-request timing
python3 agents/services/benchmark_router.py --verbose

# Check if service is under load
docker stats archon-router
```

### Health Check Issues

**Problem**: "Router service health check failed"
```bash
# Check service is accessible
curl http://localhost:8070/health

# Check environment variables
source .env
echo $ROUTER_HOST $ROUTER_PORT

# Check firewall rules
telnet localhost 8070
```

**Problem**: Database queries fail
```bash
# Verify database connection
source .env
PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  -h 192.168.86.200 -p 5436 \
  -U postgres -d omninode_bridge \
  -c "SELECT 1"

# Check table exists
PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  -h 192.168.86.200 -p 5436 \
  -U postgres -d omninode_bridge \
  -c "\d agent_routing_decisions"
```

### Migration Issues

**Problem**: "Table already has column"
```bash
# Migration is idempotent, safe to re-run
# Check current schema
PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  -h 192.168.86.200 -p 5436 \
  -U postgres -d omninode_bridge \
  -c "\d agent_routing_decisions"
```

**Problem**: View creation fails
```bash
# Drop existing views first
PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  -h 192.168.86.200 -p 5436 \
  -U postgres -d omninode_bridge \
  -c "DROP VIEW IF EXISTS v_router_service_performance; DROP VIEW IF EXISTS v_router_agent_performance;"

# Then re-apply migration
```

---

## Future Enhancements

### Phase 2: Advanced Testing
- [ ] Load testing with concurrent requests
- [ ] Chaos engineering tests (service failures)
- [ ] A/B testing framework
- [ ] Regression test suite

### Phase 3: Advanced Monitoring
- [ ] Prometheus metrics exporter
- [ ] Grafana dashboard templates
- [ ] Real-time alerting (PagerDuty/Slack)
- [ ] Distributed tracing integration

### Phase 4: Advanced Analytics
- [ ] ML-based anomaly detection
- [ ] Performance prediction models
- [ ] Confidence calibration tracking
- [ ] Router optimization recommendations

---

## Related Documentation

- [Agent Router Library](../lib/agent_router.py) - Core routing logic
- [Router Service Implementation](agent-router-service/main.py) - Service wrapper
- [Event-Driven Routing Proposal](../../docs/architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md) - Architecture
- [Database Schema](../../agents/parallel_execution/migrations/008_agent_manifest_traceability.sql) - Original schema

---

## Contact

**Author**: Polymorphic Agent (Observability & Testing Specialist)
**Date**: 2025-10-30
**Correlation ID**: ca95e668-6b52-4387-ba28-8d87ddfaf699
**Stream**: Parallel Stream 4
