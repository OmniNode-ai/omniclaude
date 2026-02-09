# Data Flow Analysis - System Diagnostic Report

**Generated**: 2025-11-06 14:00 EST
**Analysis Tool**: Diagnostic scripts in `scripts/observability/`

---

## Executive Summary

Ran comprehensive diagnostic scripts to analyze data flow through the OmniClaude system. Found significant gaps in data collection and schema mismatches preventing observability tools from working correctly.

### Overall Status

| Component | Status | Issues |
|-----------|--------|--------|
| **Database Connectivity** | ✅ Working | Password configured correctly |
| **Routing Pipeline** | ✅ Working | 13 routing decisions logged |
| **Manifest Injection** | ⚠️ Partial | 293 injections, 78% show "unknown" agent |
| **Execution Logging** | ⚠️ Limited | Only router service logged |
| **Transformation Events** | ❌ Missing | 0 records |
| **Performance Metrics** | ❌ Missing | 0 records |
| **Agent Actions** | ❌ Missing | 0 records |
| **Intelligence Usage** | ❌ Missing | 0 records |
| **Dashboard Views** | ❌ Broken | Schema mismatches |

---

## Data We ARE Getting

### ✅ Agent Routing Decisions (13 records)

**Table**: `agent_routing_decisions`
**Sample Data**:

```
selected_agent      | confidence_score | routing_time_ms | user_request
--------------------|------------------|-----------------|----------------------------------
polymorphic-agent   | 0.6600          | 64              | @polymorphic-agent analyze this code
api-architect       | 0.7500          | 82              | Create a REST API
debug-intelligence  | 0.7500          | 70              | Debug my database queries
frontend-developer  | 0.4786          | 210             | Help me implement ONEX patterns
```

**Performance**:
- Routing time: 16-241ms (avg ~90ms)
- Most recent: 2025-11-06 18:25:14

**Issues**:
- ⚠️ Average confidence 0.653 (below 0.7 threshold)
- ⚠️ Some low confidence scores (0.478)
- ⚠️ No execution success tracking linked back

---

### ✅ Agent Execution Logs (9 records)

**Table**: `agent_execution_logs`
**Sample Data**:

```
agent_name              | status  | duration_ms | user_prompt
------------------------|---------|-------------|----------------------------------
agent-router-service    | success | 149         | @polymorphic-agent analyze this code
agent-router-service    | success | 161         | Create a REST API
agent-router-service    | success | 148         | Debug my database queries
agent-router-service    | success | 349         | Help me implement ONEX patterns
```

**Issues**:
- ❌ **CRITICAL**: Only "agent-router-service" is being logged
- ❌ No actual agent executions (polymorphic-agent, debug-intelligence, etc.) are being logged
- ❌ This means agent execution tracking is not working for actual agent runs

---

### ⚠️ Manifest Injections (293 records)

**Table**: `agent_manifest_injections`
**Performance by Agent**:

```
agent_name         | total_injections | avg_query_time_ms | avg_patterns_count
-------------------|------------------|-------------------|-------------------
unknown            | 229              | 651.3             | 3.6
test-agent         | 20               | 1378.7            | 12.8
polymorphic-agent  | 19               | 1165.9            | 9.5
hook-agent         | 9                | 672.1             | 4.0
pr-review          | 3                | 1138.7            | 20.0
```

**Issues**:
- ❌ **CRITICAL**: 78% (229/293) showing agent_name as "unknown"
- ⚠️ Query times acceptable (651-1378ms)
- ⚠️ Pattern counts low (3.6-20 patterns avg)
- ❌ Zero debug intelligence captured (all 0 values)
- ❌ Zero quality scores captured

**Root Cause**: `AGENT_NAME` environment variable not being set during manifest generation

---

## Data We Are NOT Getting

### ❌ Agent Transformation Events (0 records)

**Table**: `agent_transformation_events`
**Expected Data**: Polymorphic agent transformations (source → target agent)
**Impact**: Cannot monitor self-transformation rate, routing bypass attempts

**Why Missing**: Transformation events not being published to Kafka or not being consumed

---

### ❌ Router Performance Metrics (0 records)

**Table**: `router_performance_metrics`
**Expected Data**: Detailed routing performance, trigger matching strategy, confidence components
**Impact**: Cannot analyze routing performance trends, strategy effectiveness

**Why Missing**: Router service not publishing performance metrics to database

---

### ❌ Agent Actions (0 records)

**Table**: `agent_actions`
**Expected Data**: Tool calls, decisions, errors during agent execution
**Impact**: Cannot trace agent decision-making process, debug agent behavior

**Why Missing**: Agent action logging not implemented or not being consumed from Kafka

---

### ❌ Agent Intelligence Usage (0 records)

**Table**: `agent_intelligence_usage`
**Expected Data**: Which intelligence was retrieved and applied, effectiveness tracking
**Impact**: Cannot measure intelligence effectiveness, pattern usage

**Why Missing**: Intelligence usage tracking not implemented

---

### ❌ Database Views Broken

**Missing View**: `v_agent_execution_summary`
**Error**: `relation "v_agent_execution_summary" does not exist`

**Impact**: Dashboard scripts fail with missing view

---

## Schema Mismatches

### SQL Query Failures

**File**: `scripts/observability/routing_metrics.sql`

**Column Name Mismatches**:

| Query Expects | Actual Column | Table | Impact |
|---------------|--------------|-------|--------|
| `created_at` | N/A | agent_transformation_events | Metric 1, 7 fail |
| `timestamp` | `created_at` | agent_routing_decisions | Queries fail |
| `user_request_preview` | N/A | agent_routing_decisions | Use `LEFT(user_request, 50)` |
| `start_time` | `started_at` | agent_execution_logs | Queries fail |
| `routing_duration_ms` | `routing_time_ms` | agent_routing_decisions | Metric 8 fails |
| `trigger_match_strategy` | `routing_strategy` | agent_routing_decisions | Performance analysis fails |

**Fix Required**: Update SQL queries to use correct column names

---

## Kafka Topics Status

**Topics Exist**:
```
agent-actions                                    ✅ Exists (0 consumers?)
agent-execution-logs                             ✅ Exists (active)
agent-transformation-events                      ✅ Exists (0 consumers?)
onex.evt.omniclaude.routing-decision.v1          ✅ Exists (active)
agent.routing.requested.v1                       ✅ Exists (active)
```

**Intelligence Topics**:
```
dev.archon-intelligence.intelligence.code-analysis-completed.v1  ✅ Exists
dev.archon-intelligence.intelligence.code-analysis-failed.v1     ✅ Exists
dev.archon-intelligence.intelligence.code-analysis-requested.v1  ✅ Exists
```

**Issue**: Topics exist but some have no active consumers, so data published but not persisted to database

---

## Diagnostic Script Issues

### 1. dashboard_stats.sh

**Error**: Missing view `v_agent_execution_summary`

**Fix Required**: Create missing database view or update script

---

### 2. monitor_routing_health.sh

**Errors**:
- Column `created_at` doesn't exist in `agent_transformation_events`
- Column `routing_duration_ms` doesn't exist (should be `routing_time_ms`)
- Column `trigger_match_strategy` doesn't exist (should be `routing_strategy`)

**Success**:
- ✅ Routing confidence distribution working
- ✅ Bypass attempt detection working (0 attempts found)
- ✅ Frontend routing accuracy working

**Warnings**:
- ⚠️ Average confidence 0.653 below threshold 0.7

---

## Kafka Event Bus Analysis

**Connected Topics**:
- 20+ agent/intelligence topics found
- Topics properly partitioned
- Consumer groups need verification

**Next Steps**:
1. Verify which consumers are active
2. Check which topics have messages
3. Verify message schemas match expected format

---

## Root Causes Summary

### 1. Agent Name "Unknown" (78% of manifest injections)

**Issue**: `AGENT_NAME` environment variable not set during agent execution
**Location**: `agents/lib/manifest_injector.py` (or caller)
**Fix**: Ensure `AGENT_NAME` is set before manifest injection

---

### 2. Missing Execution Logs for Actual Agents

**Issue**: Only "agent-router-service" execution logged, not actual agents
**Location**: Agent execution logging in polymorphic agent framework
**Fix**: Implement execution logging in agent lifecycle

---

### 3. Zero Transformation Events

**Issue**: Transformations not being logged to database
**Location**: Polymorphic agent transformation logic
**Fix**: Publish transformation events to Kafka `agent-transformation-events` topic

---

### 4. Zero Performance Metrics

**Issue**: Router not publishing detailed performance metrics
**Location**: `agents/services/agent_router_event_service.py`
**Fix**: Add performance metric publishing after routing decisions

---

### 5. Zero Agent Actions

**Issue**: Agent tool calls/decisions not being logged
**Location**: Agent framework tool execution
**Fix**: Implement agent action logging in tool call wrappers

---

### 6. SQL Schema Mismatches

**Issue**: SQL queries use wrong column names
**Location**: `scripts/observability/routing_metrics.sql`
**Fix**: Update queries to use correct column names from actual schema

---

### 7. Missing Database Views

**Issue**: View `v_agent_execution_summary` doesn't exist
**Location**: Database migrations
**Fix**: Create missing view or update scripts to not rely on it

---

## Intelligence Collection Status

**What's Working**:
- ✅ Pattern discovery (3.6-20 patterns per manifest)
- ✅ Query time acceptable (651-1378ms)
- ✅ Qdrant collections accessible

**What's NOT Working**:
- ❌ Debug intelligence capture (all 0 values)
- ❌ Success/failure pattern tracking (no records)
- ❌ Intelligence effectiveness metrics (empty view)

---

## Recommended Fixes (Priority Order)

### 🔴 Critical (Blocks observability)

1. **Fix agent name tracking**
   - Set `AGENT_NAME` env var in agent execution context
   - Update manifest injector to validate agent name
   - **Impact**: 78% of data currently unusable

2. **Implement agent execution logging**
   - Add execution logger to polymorphic agent lifecycle
   - Log start/progress/complete for all agents
   - **Impact**: No visibility into actual agent runs

3. **Create missing database views**
   - Create `v_agent_execution_summary` view
   - Update dashboard scripts
   - **Impact**: Dashboard scripts completely broken

---

### 🟡 High (Reduces effectiveness)

4. **Fix SQL schema mismatches**
   - Update `routing_metrics.sql` column names
   - Test all queries
   - **Impact**: 5 of 8 metrics failing

5. **Implement transformation event logging**
   - Publish to `agent-transformation-events` Kafka topic
   - Consume and persist to database
   - **Impact**: Cannot detect routing bypass attempts

6. **Implement router performance metrics**
   - Publish detailed metrics to database
   - Track strategy effectiveness
   - **Impact**: Cannot optimize routing performance

---

### 🟢 Medium (Improves intelligence)

7. **Implement agent action logging**
   - Log all tool calls and decisions
   - Link to correlation IDs
   - **Impact**: Cannot debug agent decision-making

8. **Implement intelligence usage tracking**
   - Track which patterns/intelligence used
   - Measure effectiveness
   - **Impact**: Cannot optimize intelligence collection

9. **Implement debug intelligence capture**
   - Capture success/failure patterns
   - Store in manifest injections
   - **Impact**: Cannot learn from past executions

---

## Testing Commands

```bash
# Test database connectivity
PGPASSWORD="omninode_remote_2024_secure" psql \
  -h omninode-bridge-postgres -p 5436 -U postgres -d omninode_bridge

# Check routing decisions
PGPASSWORD="omninode_remote_2024_secure" psql \
  -h omninode-bridge-postgres -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT COUNT(*), AVG(confidence_score), AVG(routing_time_ms) FROM agent_routing_decisions;"

# Check manifest injections with agent names
PGPASSWORD="omninode_remote_2024_secure" psql \
  -h omninode-bridge-postgres -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT agent_name, COUNT(*) FROM agent_manifest_injections GROUP BY agent_name ORDER BY COUNT(*) DESC;"

# List Kafka topics
docker exec omninode-bridge-redpanda rpk topic list | grep agent

# Check Kafka consumer groups
docker exec omninode-bridge-redpanda rpk group list

# Run health check
./scripts/health_check.sh

# Run routing health monitor (expect some failures)
./scripts/observability/monitor_routing_health.sh
```

---

## Conclusion

**System is partially operational but observability is severely limited**:

- ✅ Core routing pipeline works (13 decisions logged)
- ✅ Database connectivity works
- ✅ Kafka event bus operational
- ⚠️ Manifest injection works but 78% show "unknown" agent
- ❌ Agent execution tracking broken (only router service logged)
- ❌ Transformation, performance, actions, intelligence tracking: 0 records
- ❌ Dashboard/monitoring scripts broken due to schema mismatches

**Next Steps**: Address critical fixes (1-3) to restore basic observability, then high-priority fixes (4-6) to enable performance monitoring and optimization.

---

**Report Generated By**: OmniClaude Data Flow Analysis
**Data Sources**: PostgreSQL (omninode_bridge), Kafka (Redpanda), diagnostic scripts
**Database Tables Analyzed**: 27 tables, 14 views
