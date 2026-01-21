# Migration 004: Quick Reference Card

## 🚀 Quick Start

```sql
-- View all session intelligence
SELECT * FROM session_intelligence_summary;

-- Check tool performance
SELECT * FROM tool_success_rates WHERE total_uses >= 5;

-- Analyze workflow patterns
SELECT * FROM workflow_pattern_distribution;

-- Get session details
SELECT * FROM get_session_stats('your-session-id');
```

## 📊 Analytics Views

### 1. session_intelligence_summary
**Purpose**: Session-level statistics and metrics

```sql
SELECT
    session_id,
    duration_seconds,
    total_prompts,
    total_tools,
    successful_tools,
    agents_used,
    workflow_pattern
FROM session_intelligence_summary
WHERE duration_seconds > 300
ORDER BY session_start DESC;
```

**Columns**:
- `session_id` - Unique session identifier
- `session_start` - Session start timestamp
- `session_end` - Session end timestamp
- `duration_seconds` - Total session duration
- `total_prompts` - Number of user prompts
- `total_tools` - Number of tool executions
- `unique_tools` - Number of distinct tools used
- `successful_tools` - Number of successful tool executions
- `agents_used` - Array of agents detected
- `workflow_pattern` - Detected workflow pattern

### 2. tool_success_rates
**Purpose**: Tool-level performance metrics

```sql
SELECT
    tool_name,
    total_uses,
    success_rate_pct,
    avg_quality_score
FROM tool_success_rates
WHERE success_rate_pct < 80
ORDER BY total_uses DESC;
```

**Columns**:
- `tool_name` - Tool identifier
- `total_uses` - Total execution count
- `successful_uses` - Full success count
- `partial_success_uses` - Partial success count
- `failed_uses` - Failure count
- `success_rate_pct` - Success percentage (0-100)
- `avg_quality_score` - Average quality (0.0-1.0)
- `min_quality_score` - Minimum quality
- `max_quality_score` - Maximum quality
- `first_used` - First usage timestamp
- `last_used` - Last usage timestamp

### 3. workflow_pattern_distribution
**Purpose**: Workflow pattern frequency and characteristics

```sql
SELECT
    workflow_pattern,
    session_count,
    avg_duration_seconds,
    percentage_of_total
FROM workflow_pattern_distribution
ORDER BY session_count DESC;
```

**Columns**:
- `workflow_pattern` - Pattern identifier
- `session_count` - Number of sessions
- `avg_prompts_per_session` - Average prompts
- `avg_tools_per_session` - Average tools
- `avg_duration_seconds` - Average duration
- `percentage_of_total` - Percentage of all sessions
- `first_seen` - First occurrence
- `last_seen` - Last occurrence

### 4. agent_usage_patterns
**Purpose**: Agent detection and routing analysis

```sql
SELECT
    agent_name,
    detection_count,
    unique_sessions
FROM agent_usage_patterns
ORDER BY detection_count DESC;
```

**Columns**:
- `agent_name` - Detected agent name
- `detection_count` - Total detections
- `unique_sessions` - Number of unique sessions
- `detected_in_sources` - Array of hook sources
- `first_detected` - First detection timestamp
- `last_detected` - Last detection timestamp
- `prompts_with_agent` - Prompt-level detections
- `tools_with_agent` - Tool-level detections

### 5. quality_metrics_summary
**Purpose**: Quality score distribution per tool

```sql
SELECT
    tool_name,
    avg_quality,
    median_quality,
    high_quality_count
FROM quality_metrics_summary
WHERE avg_quality >= 0.8;
```

**Columns**:
- `tool_name` - Tool identifier
- `total_executions` - Total execution count
- `avg_quality` - Average quality score
- `stddev_quality` - Standard deviation
- `median_quality` - Median quality (P50)
- `p25_quality` - 25th percentile
- `p75_quality` - 75th percentile
- `high_quality_count` - Count with quality ≥0.8
- `low_quality_count` - Count with quality <0.5

## 🔧 Helper Functions

### 1. get_session_stats(session_id TEXT)
**Purpose**: Get comprehensive session statistics

```sql
SELECT * FROM get_session_stats('test-session-123');
```

**Returns**:
- `prompts` - Number of prompts
- `tools` - Number of tool executions
- `agents` - Array of detected agents
- `duration_seconds` - Session duration
- `workflow_pattern` - Detected pattern
- `success_rate` - Tool success percentage

### 2. get_tool_performance(tool_name TEXT)
**Purpose**: Get tool performance metrics with trends

```sql
SELECT * FROM get_tool_performance('Read');
```

**Returns**:
- `total_uses` - Total execution count
- `success_rate` - Success percentage
- `avg_quality` - Average quality score
- `last_7_days_uses` - Recent usage count
- `trending` - Trend direction (increasing/decreasing/stable)

### 3. get_recent_workflow_patterns(days INTEGER)
**Purpose**: Get workflow patterns from recent period

```sql
SELECT * FROM get_recent_workflow_patterns(30);
```

**Returns**:
- `workflow_pattern` - Pattern identifier
- `session_count` - Number of sessions
- `avg_duration` - Average duration
- `avg_prompts` - Average prompts
- `avg_tools` - Average tools

### 4. calculate_session_success_score(session_id TEXT)
**Purpose**: Calculate composite success score (0-100)

```sql
SELECT calculate_session_success_score('test-session-123');
```

**Returns**: NUMERIC (0-100)
- Weighted score based on:
  - Tool success rate (40%)
  - Quality score (40%)
  - Response completion (20%)

## 📈 Common Use Cases

### Find High-Performing Sessions
```sql
SELECT
    session_id,
    duration_seconds,
    total_tools,
    successful_tools,
    calculate_session_success_score(session_id::text) as success_score
FROM session_intelligence_summary
WHERE calculate_session_success_score(session_id::text) >= 80
ORDER BY success_score DESC;
```

### Identify Problematic Tools
```sql
SELECT
    tool_name,
    total_uses,
    success_rate_pct,
    failed_uses,
    avg_quality_score
FROM tool_success_rates
WHERE success_rate_pct < 50 AND total_uses >= 10
ORDER BY failed_uses DESC;
```

### Analyze Workflow Trends
```sql
SELECT
    workflow_pattern,
    session_count,
    avg_duration_seconds,
    percentage_of_total
FROM workflow_pattern_distribution
WHERE session_count >= 5
ORDER BY percentage_of_total DESC;
```

### Monitor Agent Usage
```sql
SELECT
    agent_name,
    detection_count,
    unique_sessions,
    ROUND(100.0 * unique_sessions / (SELECT COUNT(DISTINCT session_id) FROM session_intelligence_summary), 2) as session_penetration_pct
FROM agent_usage_patterns
ORDER BY detection_count DESC;
```

### Quality Distribution Analysis
```sql
SELECT
    tool_name,
    total_executions,
    ROUND(avg_quality * 100, 1) as avg_quality_pct,
    ROUND(median_quality * 100, 1) as median_quality_pct,
    ROUND(100.0 * high_quality_count / total_executions, 1) as high_quality_pct
FROM quality_metrics_summary
WHERE total_executions >= 10
ORDER BY avg_quality DESC;
```

### Session Success Distribution
```sql
SELECT
    CASE
        WHEN calculate_session_success_score(session_id::text) >= 80 THEN 'High (80-100)'
        WHEN calculate_session_success_score(session_id::text) >= 60 THEN 'Good (60-79)'
        WHEN calculate_session_success_score(session_id::text) >= 40 THEN 'Fair (40-59)'
        ELSE 'Low (0-39)'
    END as success_tier,
    COUNT(*) as session_count,
    ROUND(AVG(duration_seconds), 0) as avg_duration,
    ROUND(AVG(total_tools), 1) as avg_tools
FROM session_intelligence_summary
GROUP BY success_tier
ORDER BY success_tier DESC;
```

## 🔍 Performance Monitoring

### Check Index Usage
```sql
SELECT
    indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
AND tablename = 'hook_events'
AND indexname LIKE 'idx_hook_events_%'
ORDER BY idx_scan DESC;
```

### Check View Performance
```sql
-- Test session_intelligence_summary
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM session_intelligence_summary LIMIT 10;

-- Test tool_success_rates
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM tool_success_rates LIMIT 10;

-- Test workflow_pattern_distribution
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM workflow_pattern_distribution;
```

### Monitor Query Times
```sql
SELECT
    query,
    calls,
    total_time,
    mean_time,
    max_time
FROM pg_stat_statements
WHERE query LIKE '%session_intelligence_summary%'
   OR query LIKE '%tool_success_rates%'
   OR query LIKE '%workflow_pattern_distribution%'
ORDER BY mean_time DESC;
```

## 🛠️ Maintenance

### Refresh Statistics
```sql
ANALYZE hook_events;
```

### Reindex (if performance degrades)
```sql
REINDEX INDEX CONCURRENTLY idx_hook_events_session;
REINDEX INDEX CONCURRENTLY idx_hook_events_workflow;
REINDEX INDEX CONCURRENTLY idx_hook_events_quality;
```

### Check Data Integrity
```sql
-- Verify view consistency
SELECT
    (SELECT COUNT(DISTINCT metadata->>'session_id') FROM hook_events WHERE metadata->>'session_id' IS NOT NULL) as base_count,
    (SELECT COUNT(*) FROM session_intelligence_summary) as view_count;

-- Check for NULL JSONB fields
SELECT COUNT(*) as corrupted_events
FROM hook_events
WHERE payload IS NULL OR metadata IS NULL;
```

## 📋 Troubleshooting

### Slow Query Performance
```sql
-- Check missing indexes
SELECT schemaname, tablename, attname, n_distinct, correlation
FROM pg_stats
WHERE tablename = 'hook_events'
AND attname IN ('source', 'resource_id', 'created_at')
ORDER BY correlation;

-- Force index usage
SET enable_seqscan = OFF;
SELECT * FROM session_intelligence_summary LIMIT 10;
SET enable_seqscan = ON;
```

### Empty Results
```sql
-- Check data availability
SELECT
    source,
    COUNT(*) as event_count,
    COUNT(DISTINCT metadata->>'session_id') as unique_sessions
FROM hook_events
GROUP BY source
ORDER BY event_count DESC;
```

### Function Errors
```sql
-- Test with known good data
SELECT * FROM get_session_stats((
    SELECT metadata->>'session_id'
    FROM hook_events
    WHERE metadata->>'session_id' IS NOT NULL
    LIMIT 1
));
```

## 📚 Reference

**Migration Files**:
- `004_add_hook_intelligence_indexes.sql` - Main migration
- `004b_fix_function_signatures.sql` - Patch migration
- `004_rollback_hook_intelligence.sql` - Rollback script
- `README_MIGRATION_004.md` - Full documentation
- `test_migration_004.sh` - Test suite

**Performance Targets**:
- All views: <100ms execution time
- Achieved: 0.1-0.8ms (100-1000x faster)

**Database**: omninode_bridge
**Table**: hook_events
**Schema Version**: 004

---

**Quick Help**: See README_MIGRATION_004.md for detailed documentation
**Test Suite**: Run `./test_migration_004.sh` to verify installation
**Support**: Check pg_stat_user_indexes for index performance
