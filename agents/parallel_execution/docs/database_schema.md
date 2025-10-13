# Agent Observability Framework - Database Schema Documentation

**Author**: agent-workflow-coordinator
**Created**: 2025-10-09
**Database**: PostgreSQL 14+ (omninode_bridge)
**ONEX Compliance**: Effect node patterns for all persistence operations

---

## Overview

The Agent Observability Framework provides comprehensive tracking and analytics for polymorphic agent transformations, routing decisions, and performance metrics. The schema consists of three core tables optimized for time-series queries and JSONB-based flexible storage.

### Performance Targets
- Connection acquisition: <50ms
- Migration execution: <5s total
- Query performance: <100ms for standard queries
- Pool initialization: <300ms

---

## Table: `agent_definitions`

**Purpose**: Storage for agent YAML configurations and metadata for dynamic agent loading.

### Schema

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | gen_random_uuid() | Primary key |
| `agent_name` | VARCHAR(255) | NO | - | Unique agent identifier |
| `agent_version` | VARCHAR(50) | NO | '1.0.0' | Semantic version |
| `agent_type` | VARCHAR(100) | NO | - | coordinator, specialist, transformer |
| `yaml_config` | JSONB | NO | - | Full YAML configuration |
| `parsed_metadata` | JSONB | YES | NULL | Extracted metadata for fast queries |
| `capabilities` | TEXT[] | YES | {} | Array of capability tags |
| `domain` | VARCHAR(100) | YES | NULL | general, api_development, debugging, etc. |
| `triggers` | TEXT[] | YES | {} | Trigger phrases for router |
| `trigger_patterns` | TEXT[] | YES | {} | Regex patterns for matching |
| `avg_execution_time_ms` | INTEGER | YES | NULL | Average execution time |
| `success_rate` | DECIMAL(5,4) | YES | NULL | 0.0000 to 1.0000 |
| `quality_score` | DECIMAL(5,4) | YES | NULL | 0.0000 to 1.0000 |
| `is_active` | BOOLEAN | NO | TRUE | Active status flag |
| `status` | VARCHAR(50) | NO | 'active' | active, deprecated, testing |
| `registry_path` | TEXT | YES | NULL | Path to YAML file |
| `definition_hash` | VARCHAR(64) | YES | NULL | SHA-256 hash of YAML |
| `created_at` | TIMESTAMPTZ | NO | NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | NOW() | Last update timestamp |
| `last_loaded_at` | TIMESTAMPTZ | YES | NULL | Last load timestamp |

### Indexes

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `agent_definitions_pkey` | PRIMARY KEY | id | Primary key constraint |
| `agent_definitions_name_version_unique` | UNIQUE | agent_name, agent_version | Prevent duplicates |
| `idx_agent_definitions_name` | BTREE | agent_name | Fast name lookup |
| `idx_agent_definitions_type` | BTREE | agent_type | Type filtering |
| `idx_agent_definitions_domain` | BTREE | domain | Domain filtering |
| `idx_agent_definitions_active` | BTREE | is_active (WHERE is_active=TRUE) | Active agents only |
| `idx_agent_definitions_capabilities` | GIN | capabilities | Array search |
| `idx_agent_definitions_triggers` | GIN | triggers | Array search |
| `idx_agent_definitions_yaml_config` | GIN | yaml_config | JSONB queries |
| `idx_agent_definitions_metadata` | GIN | parsed_metadata | JSONB queries |
| `idx_agent_definitions_performance` | BTREE | success_rate DESC, quality_score DESC, avg_execution_time_ms ASC | Performance sorting |

### Constraints

- **Unique**: (agent_name, agent_version) - Prevent duplicate versions
- **Check**: success_rate BETWEEN 0 AND 1
- **Check**: quality_score BETWEEN 0 AND 1

### Triggers

- **update_agent_definitions_timestamp**: Auto-updates `updated_at` on UPDATE

### Usage Examples

```sql
-- Load agent definition by name (latest version)
SELECT * FROM agent_definitions
WHERE agent_name = 'agent-debug-intelligence'
  AND is_active = TRUE
ORDER BY agent_version DESC
LIMIT 1;

-- Search by capabilities
SELECT agent_name, capabilities, success_rate
FROM agent_definitions
WHERE capabilities && ARRAY['debugging', 'code_analysis']
  AND is_active = TRUE
ORDER BY success_rate DESC;

-- Query YAML config
SELECT agent_name, yaml_config->'metadata'->>'description'
FROM agent_definitions
WHERE yaml_config @> '{"domain": "api_development"}';
```

---

## Table: `agent_transformation_events`

**Purpose**: Tracks agent identity transformations and execution for observability and learning.

### Schema

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | gen_random_uuid() | Primary key |
| `event_type` | VARCHAR(100) | NO | - | transformation_start, complete, failed |
| `correlation_id` | UUID | NO | - | Links related workflow events |
| `session_id` | UUID | YES | NULL | Links conversation session events |
| `source_agent` | VARCHAR(255) | YES | NULL | Original agent |
| `target_agent` | VARCHAR(255) | NO | - | Agent being assumed |
| `transformation_reason` | TEXT | YES | NULL | Why transformation occurred |
| `context_snapshot` | JSONB | YES | NULL | Full context at transformation time |
| `context_keys` | TEXT[] | YES | NULL | Keys passed to target agent |
| `context_size_bytes` | INTEGER | YES | NULL | Size for performance tracking |
| `user_request` | TEXT | YES | NULL | Original user request |
| `routing_confidence` | DECIMAL(5,4) | YES | NULL | Router confidence (0-1) |
| `routing_strategy` | VARCHAR(100) | YES | NULL | explicit, fuzzy_match, capability_match |
| `transformation_duration_ms` | INTEGER | YES | NULL | Transformation time |
| `initialization_duration_ms` | INTEGER | YES | NULL | Target agent init time |
| `total_execution_duration_ms` | INTEGER | YES | NULL | Total execution time |
| `success` | BOOLEAN | YES | NULL | Success/failure flag |
| `error_message` | TEXT | YES | NULL | Error details |
| `error_type` | VARCHAR(100) | YES | NULL | Error classification |
| `quality_score` | DECIMAL(5,4) | YES | NULL | Output quality (0-1) |
| `agent_definition_id` | UUID | YES | NULL | FK to agent_definitions |
| `parent_event_id` | UUID | YES | NULL | FK to self (nested transformations) |
| `started_at` | TIMESTAMPTZ | NO | NOW() | Event start timestamp |
| `completed_at` | TIMESTAMPTZ | YES | NULL | Event completion timestamp |

### Indexes

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `agent_transformation_events_pkey` | PRIMARY KEY | id | Primary key |
| `idx_agent_transformation_events_correlation` | BTREE | correlation_id | Workflow tracing |
| `idx_agent_transformation_events_session` | BTREE | session_id | Session tracing |
| `idx_agent_transformation_events_target` | BTREE | target_agent | Agent filtering |
| `idx_agent_transformation_events_source` | BTREE | source_agent | Source filtering |
| `idx_agent_transformation_events_type` | BTREE | event_type | Type filtering |
| `idx_agent_transformation_events_started_at` | BTREE | started_at DESC | Time-series queries |
| `idx_agent_transformation_events_success_time` | BTREE | success, started_at DESC (WHERE success IS NOT NULL) | Success analysis |
| `idx_agent_transformation_events_performance` | BTREE | target_agent, total_execution_duration_ms, quality_score | Performance analysis |
| `idx_agent_transformation_events_context` | GIN | context_snapshot | JSONB queries |
| `idx_agent_transformation_events_parent` | BTREE | parent_event_id (WHERE parent_event_id IS NOT NULL) | Hierarchy queries |
| `idx_agent_transformation_events_definition` | BTREE | agent_definition_id (WHERE agent_definition_id IS NOT NULL) | Definition lookup |

### Constraints

- **Check**: routing_confidence BETWEEN 0 AND 1
- **Check**: quality_score IS NULL OR (quality_score BETWEEN 0 AND 1)

### Foreign Keys

- `agent_definition_id` → `agent_definitions(id)`
- `parent_event_id` → `agent_transformation_events(id)` (self-reference)

### Usage Examples

```sql
-- Track complete workflow by correlation_id
SELECT
    event_type,
    target_agent,
    routing_confidence,
    total_execution_duration_ms,
    success,
    started_at
FROM agent_transformation_events
WHERE correlation_id = '550e8400-e29b-41d4-a716-446655440000'
ORDER BY started_at;

-- Performance analysis by agent
SELECT
    target_agent,
    COUNT(*) as executions,
    AVG(total_execution_duration_ms) as avg_duration_ms,
    AVG(quality_score) as avg_quality,
    SUM(CASE WHEN success THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as success_rate
FROM agent_transformation_events
WHERE started_at > NOW() - INTERVAL '7 days'
GROUP BY target_agent
ORDER BY success_rate DESC;

-- Context snapshot analysis
SELECT
    target_agent,
    context_snapshot->'files' as files_provided,
    quality_score
FROM agent_transformation_events
WHERE context_snapshot IS NOT NULL
  AND quality_score > 0.8;
```

---

## Table: `router_performance_metrics`

**Purpose**: Time-series performance metrics for enhanced router monitoring and optimization.

### Schema

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | gen_random_uuid() | Primary key |
| `metric_type` | VARCHAR(100) | NO | - | routing_decision, cache_hit, cache_miss |
| `correlation_id` | UUID | YES | NULL | Links to transformation events |
| `user_request_hash` | VARCHAR(64) | YES | NULL | Hash for deduplication |
| `context_hash` | VARCHAR(64) | YES | NULL | Hash for cache key generation |
| `selected_agent` | VARCHAR(255) | YES | NULL | Agent selected by router |
| `selection_strategy` | VARCHAR(100) | YES | NULL | explicit, fuzzy, capability, historical |
| `confidence_score` | DECIMAL(5,4) | YES | NULL | Router confidence (0-1) |
| `alternative_agents` | JSONB | YES | NULL | Array of {agent, confidence, reason} |
| `alternatives_count` | INTEGER | YES | 0 | Count of alternatives |
| `cache_lookup_us` | INTEGER | YES | NULL | Cache lookup time (μs) |
| `trigger_matching_us` | INTEGER | YES | NULL | Trigger matching time (μs) |
| `confidence_scoring_us` | INTEGER | YES | NULL | Confidence calc time (μs) |
| `total_routing_time_us` | INTEGER | YES | NULL | Total routing time (μs) **Target: <100,000μs** |
| `trigger_confidence` | DECIMAL(5,4) | YES | NULL | 40% weight component |
| `context_confidence` | DECIMAL(5,4) | YES | NULL | 30% weight component |
| `capability_confidence` | DECIMAL(5,4) | YES | NULL | 20% weight component |
| `historical_confidence` | DECIMAL(5,4) | YES | NULL | 10% weight component |
| `cache_hit` | BOOLEAN | YES | NULL | Cache hit flag |
| `cache_key` | VARCHAR(255) | YES | NULL | Cache key used |
| `cache_age_seconds` | INTEGER | YES | NULL | Age of cached result |
| `selection_validated` | BOOLEAN | YES | NULL | Post-execution validation flag |
| `actual_success` | BOOLEAN | YES | NULL | Actual execution success |
| `actual_quality_score` | DECIMAL(5,4) | YES | NULL | Actual quality achieved |
| `prediction_error` | DECIMAL(5,4) | YES | NULL | Confidence vs quality difference |
| `feedback_provided` | BOOLEAN | YES | FALSE | Feedback flag |
| `feedback_type` | VARCHAR(50) | YES | NULL | positive, negative, correction |
| `feedback_details` | JSONB | YES | NULL | Feedback details |
| `measured_at` | TIMESTAMPTZ | NO | NOW() | Measurement timestamp |
| `validated_at` | TIMESTAMPTZ | YES | NULL | Validation timestamp |

### Indexes

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `router_performance_metrics_pkey` | PRIMARY KEY | id | Primary key |
| `idx_router_performance_metrics_measured_at` | BTREE | measured_at DESC | Time-series queries |
| `idx_router_performance_metrics_type_time` | BTREE | metric_type, measured_at DESC | Type-based time series |
| `idx_router_performance_metrics_agent_time` | BTREE | selected_agent, measured_at DESC | Agent performance trends |
| `idx_router_performance_metrics_correlation` | BTREE | correlation_id (WHERE correlation_id IS NOT NULL) | Link to events |
| `idx_router_performance_metrics_cache` | BTREE | cache_hit, cache_age_seconds (WHERE cache_hit IS NOT NULL) | Cache analysis |
| `idx_router_performance_metrics_timing` | BTREE | total_routing_time_us, measured_at DESC | Performance monitoring |
| `idx_router_performance_metrics_prediction` | BTREE | confidence_score, actual_quality_score, prediction_error (WHERE selection_validated=TRUE) | Learning analysis |
| `idx_router_performance_metrics_request_hash` | BTREE | user_request_hash, context_hash | Deduplication |
| `idx_router_performance_metrics_alternatives` | GIN | alternative_agents | JSONB queries |
| `idx_router_performance_metrics_feedback` | BTREE | feedback_provided, feedback_type (WHERE feedback_provided=TRUE) | Feedback analysis |

### Constraints

- **Check**: confidence_score BETWEEN 0 AND 1
- **Check**: All confidence components (trigger, context, capability, historical) BETWEEN 0 AND 1 OR NULL

### Usage Examples

```sql
-- Router performance monitoring (last hour)
SELECT
    AVG(total_routing_time_us) as avg_routing_time_us,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_routing_time_us) as p95_routing_time_us,
    COUNT(*) as routing_decisions,
    SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as cache_hit_rate
FROM router_performance_metrics
WHERE measured_at > NOW() - INTERVAL '1 hour';

-- Confidence component analysis
SELECT
    selected_agent,
    AVG(trigger_confidence) as avg_trigger,
    AVG(context_confidence) as avg_context,
    AVG(capability_confidence) as avg_capability,
    AVG(historical_confidence) as avg_historical,
    AVG(confidence_score) as avg_total
FROM router_performance_metrics
WHERE measured_at > NOW() - INTERVAL '24 hours'
  AND confidence_score IS NOT NULL
GROUP BY selected_agent
ORDER BY avg_total DESC;

-- Prediction accuracy (learning loop)
SELECT
    selected_agent,
    AVG(confidence_score) as predicted_confidence,
    AVG(actual_quality_score) as actual_quality,
    AVG(ABS(prediction_error)) as avg_prediction_error,
    COUNT(*) as samples
FROM router_performance_metrics
WHERE selection_validated = TRUE
  AND measured_at > NOW() - INTERVAL '7 days'
GROUP BY selected_agent
HAVING COUNT(*) >= 10
ORDER BY avg_prediction_error;
```

---

## Database Connection Pool Configuration

### Configuration Class: `DatabaseConfig`

```python
from agents.parallel_execution.db_connection_pool import DatabaseConfig

config = DatabaseConfig(
    host="localhost",
    port=5436,
    database="omninode_bridge",
    user="postgres",
    password="omninode-bridge-postgres-dev-2024",
    min_size=5,
    max_size=20,
    max_queries=50000,
    max_inactive_connection_lifetime=300.0,  # 5 minutes
    timeout=60.0,
    command_timeout=60.0
)
```

### Usage Example

```python
from agents.parallel_execution.db_connection_pool import (
    database_pool_context,
    get_database_pool
)

# Context manager (recommended for scoped operations)
async with database_pool_context() as pool:
    async with pool.acquire() as conn:
        result = await conn.fetchrow(
            "SELECT * FROM agent_definitions WHERE agent_name = $1",
            "agent-debug-intelligence"
        )

# Global pool (for long-running services)
pool = await get_database_pool()
async with pool.acquire() as conn:
    result = await conn.fetch("SELECT * FROM agent_transformation_events")
```

---

## Migration Management

### Applying Migrations

```bash
cd /Volumes/PRO-G40/Code/omniclaude/agents/parallel_execution/migrations
./apply_migrations.sh
```

### Rolling Back All Migrations

```bash
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -f rollback_all.sql
```

### Migration Files

1. `001_create_agent_definitions.sql` - Agent registry table
2. `002_create_agent_transformation_events.sql` - Transformation tracking
3. `003_create_router_performance_metrics.sql` - Performance metrics

---

## Performance Considerations

### Query Optimization

- **Use indexed columns in WHERE clauses**: All time-based queries use `measured_at`, `started_at` indexes
- **JSONB queries**: Use `@>`, `->`, `->>` operators with GIN indexes
- **Array searches**: Use `&&` operator with GIN indexes on `capabilities`, `triggers`
- **Partial indexes**: Active agents, non-null values have specialized indexes

### Connection Pooling

- **Min connections**: 5 (always ready)
- **Max connections**: 20 (prevents database overload)
- **Connection reuse**: Up to 50,000 queries per connection
- **Idle timeout**: 5 minutes (reclaims unused connections)

### Time-Series Optimization

- **Time-based partitioning**: Consider partitioning `agent_transformation_events` and `router_performance_metrics` by month for high-volume scenarios
- **Index maintenance**: Run `VACUUM ANALYZE` regularly on time-series tables
- **Archival strategy**: Archive events older than 90 days to separate tables

---

## ONEX Compliance

All database operations follow ONEX Effect node patterns:

- **Naming**: `NodeDatabasePoolEffect` for connection pool
- **Error handling**: Proper exception chaining with context preservation
- **Lifecycle management**: Initialize → Execute → Cleanup pattern
- **Performance tracking**: All operations monitored for threshold compliance

---

## Security Considerations

### Credentials Management

- **Environment variables**: Use `.env` file for local development
- **Production**: Use secret management systems (Vault, AWS Secrets Manager)
- **Connection strings**: Never commit credentials to version control

### Database Security

- **SSL/TLS**: Enable for production deployments
- **Row-level security**: Consider implementing for multi-tenant scenarios
- **Audit logging**: Enable PostgreSQL audit logging for compliance

---

## Monitoring & Observability

### Key Metrics to Monitor

1. **Pool health**: Connection count, idle connections
2. **Query performance**: P95 query times, slow query log
3. **Router performance**: Routing decision times, cache hit rates
4. **Agent success rates**: Per-agent success/failure rates
5. **Quality trends**: Quality score trends over time

### Alerting Thresholds

- Connection acquisition > 50ms
- Query execution > 100ms
- Cache hit rate < 60%
- Agent success rate < 80%
- Routing time > 100ms (100,000μs)

---

## Future Enhancements

### Phase 2 Considerations

1. **pgvector extension**: For semantic search on agent capabilities
2. **TimescaleDB**: For advanced time-series analytics
3. **Partitioning**: Monthly partitions for high-volume tables
4. **Read replicas**: For analytics queries without impacting writes
5. **CDC (Change Data Capture)**: Real-time streaming to analytics systems

---

## References

- PostgreSQL 14 Documentation: https://www.postgresql.org/docs/14/
- asyncpg Documentation: https://magicstack.github.io/asyncpg/
- ONEX Architecture Patterns: `/Volumes/PRO-G40/Code/Archon/docs/ONEX_ARCHITECTURE_PATTERNS_COMPLETE.md`

---

**Document Version**: 1.0
**Last Updated**: 2025-10-09
**Maintained By**: agent-workflow-coordinator
