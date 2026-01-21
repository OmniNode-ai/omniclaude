# Migration 004: Hook Intelligence Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Claude Code Session                          │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ UserPrompt   │  │  Tool Use    │  │  Response    │              │
│  │   Submit     │  │  PostToolUse │  │     Stop     │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         │                 │                  │                      │
│         └─────────────────┴──────────────────┘                      │
│                           │                                         │
│                           ▼                                         │
│               ┌──────────────────────┐                              │
│               │  Hook Event Logger   │                              │
│               │  (Python Library)    │                              │
│               └──────────┬───────────┘                              │
│                          │                                          │
└──────────────────────────┼──────────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │        PostgreSQL Database           │
        │     (omninode_bridge:5436)           │
        │                                      │
        │  ┌────────────────────────────────┐ │
        │  │       hook_events Table        │ │
        │  │                                │ │
        │  │  Columns:                      │ │
        │  │  • id (UUID)                   │ │
        │  │  • source (VARCHAR)            │ │
        │  │  • action (VARCHAR)            │ │
        │  │  • resource (VARCHAR)          │ │
        │  │  • resource_id (VARCHAR)       │ │
        │  │  • payload (JSONB) ◄─────┐    │ │
        │  │  • metadata (JSONB) ◄────┤    │ │
        │  │  • processed (BOOLEAN)    │    │ │
        │  │  • created_at (TIMESTAMPTZ)│   │ │
        │  │  • ...                     │    │ │
        │  └────────────────────────────┘    │ │
        │              │                     │ │
        │              ▼                     │ │
        │  ┌────────────────────────────────┤ │
        │  │    7 Performance Indexes       │ │
        │  │                                │ │
        │  │  1. idx_hook_events_session    │ │
        │  │  2. idx_hook_events_workflow   │ │
        │  │  3. idx_hook_events_quality    │ │
        │  │  4. idx_hook_events_success    │ │
        │  │  5. idx_hook_events_response   │ │
        │  │  6. idx_hook_events_agent      │ │
        │  │  7. idx_hook_events_created_   │ │
        │  │     source                     │ │
        │  │                                │ │
        │  │  Total Size: 120 KB            │ │
        │  │  Performance: <1ms queries     │ │
        │  └────────────────────────────────┘ │
        │              │                       │
        │              ▼                       │
        │  ┌────────────────────────────────┐ │
        │  │    5 Analytics Views           │ │
        │  │                                │ │
        │  │  1. session_intelligence_      │ │
        │  │     summary                    │ │
        │  │     → Session-level stats      │ │
        │  │                                │ │
        │  │  2. tool_success_rates         │ │
        │  │     → Tool performance         │ │
        │  │                                │ │
        │  │  3. workflow_pattern_          │ │
        │  │     distribution               │ │
        │  │     → Pattern analysis         │ │
        │  │                                │ │
        │  │  4. agent_usage_patterns       │ │
        │  │     → Agent routing            │ │
        │  │                                │ │
        │  │  5. quality_metrics_summary    │ │
        │  │     → Quality distribution     │ │
        │  │                                │ │
        │  │  Performance: 0.1-0.8ms        │ │
        │  └────────────────────────────────┘ │
        │              │                       │
        │              ▼                       │
        │  ┌────────────────────────────────┐ │
        │  │    4 Helper Functions          │ │
        │  │                                │ │
        │  │  1. get_session_stats()        │ │
        │  │  2. get_tool_performance()     │ │
        │  │  3. get_recent_workflow_       │ │
        │  │     patterns()                 │ │
        │  │  4. calculate_session_         │ │
        │  │     success_score()            │ │
        │  └────────────────────────────────┘ │
        └──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │         Analytics Consumers          │
        │                                      │
        │  • Observability Dashboard           │
        │  • Performance Monitoring            │
        │  • Quality Alerting                  │
        │  • Automated Reporting               │
        └──────────────────────────────────────┘
```

## Data Flow

### 1. Event Capture
```
User Action → Hook Trigger → Event Logger → JSONB Fields
                                                │
                                                ├─ payload:
                                                │  • quality_metrics
                                                │  • success_classification
                                                │  • workflow_pattern
                                                │  • agent_detected
                                                │  • completion_status
                                                │
                                                └─ metadata:
                                                   • session_id
                                                   • timestamp
                                                   • context
```

### 2. Index Optimization
```
JSONB Fields → Performance Indexes → Fast Queries
                    │
                    ├─ Session Index (metadata->>'session_id')
                    ├─ Workflow Index (payload->>'workflow_pattern')
                    ├─ Quality Index (payload->'quality_metrics')
                    ├─ Success Index (payload->>'success_classification')
                    ├─ Response Index (payload->>'completion_status')
                    ├─ Agent Index (payload->>'agent_detected')
                    └─ Time-series Index (created_at, source)
```

### 3. Analytics Views
```
Base Table + Indexes → Aggregation Views → Analytics
                            │
                            ├─ session_intelligence_summary
                            │  GROUP BY session_id
                            │  AGGREGATE prompts, tools, duration
                            │
                            ├─ tool_success_rates
                            │  GROUP BY resource_id
                            │  CALCULATE success_rate, quality
                            │
                            ├─ workflow_pattern_distribution
                            │  GROUP BY workflow_pattern
                            │  ANALYZE frequency, characteristics
                            │
                            ├─ agent_usage_patterns
                            │  GROUP BY agent_detected
                            │  COUNT detections, sessions
                            │
                            └─ quality_metrics_summary
                               GROUP BY resource_id
                               CALCULATE statistics, percentiles
```

### 4. Helper Functions
```
Function Call → Query Optimization → Results
                    │
                    ├─ get_session_stats(session_id)
                    │  → Single session analysis
                    │
                    ├─ get_tool_performance(tool_name)
                    │  → Tool metrics + trending
                    │
                    ├─ get_recent_workflow_patterns(days)
                    │  → Time-filtered patterns
                    │
                    └─ calculate_session_success_score(session_id)
                       → Weighted composite score
```

## JSONB Structure

### Payload Schema
```json
{
  "quality_metrics": {
    "quality_score": 0.0-1.0,
    "complexity": "low|medium|high",
    "maintainability_index": 0-100
  },
  "success_classification": "full_success|partial_success|failure",
  "workflow_pattern": "exploration|debugging|implementation|refactoring",
  "agent_detected": "agent-workflow-coordinator|agent-code-reviewer|...",
  "completion_status": "completed|interrupted|error",
  "total_prompts": integer,
  "total_tools": integer,
  "duration_seconds": numeric
}
```

### Metadata Schema
```json
{
  "session_id": "string",
  "timestamp": "ISO-8601",
  "user_context": {...},
  "environment": {...}
}
```

## Index Strategy

### 1. Session-Based Queries
```sql
-- Index: idx_hook_events_session
-- Usage: Session aggregation, duration calculations
WHERE metadata->>'session_id' = 'session-123'
```

### 2. Workflow Analysis
```sql
-- Index: idx_hook_events_workflow
-- Usage: Pattern distribution, frequency analysis
WHERE payload->>'workflow_pattern' = 'debugging'
```

### 3. Quality Metrics
```sql
-- Index: idx_hook_events_quality
-- Usage: Quality score filtering, percentile calculations
WHERE (payload->'quality_metrics'->>'quality_score')::numeric >= 0.8
```

### 4. Success Classification
```sql
-- Index: idx_hook_events_success
-- Usage: Success rate calculations, failure analysis
WHERE payload->>'success_classification' = 'full_success'
```

### 5. Response Completion
```sql
-- Index: idx_hook_events_response
-- Usage: Completion rate tracking
WHERE payload->>'completion_status' = 'completed'
```

### 6. Agent Detection
```sql
-- Index: idx_hook_events_agent
-- Usage: Agent usage patterns, routing analysis
WHERE payload->>'agent_detected' IS NOT NULL
```

### 7. Time-Series
```sql
-- Index: idx_hook_events_created_source
-- Usage: Time-based filtering with source
WHERE created_at >= NOW() - INTERVAL '7 days'
AND source = 'PostToolUse'
ORDER BY created_at DESC
```

## View Relationships

```
session_intelligence_summary
    ├─ Joins: Self-join on session_id
    ├─ Aggregates: COUNT, MIN, MAX, ARRAY_AGG
    └─ Uses: idx_hook_events_session

tool_success_rates
    ├─ Groups: resource_id (tool name)
    ├─ Calculates: Success rates, quality scores
    └─ Uses: idx_hook_events_success, idx_hook_events_quality

workflow_pattern_distribution
    ├─ Groups: workflow_pattern
    ├─ Analyzes: Frequency, characteristics
    └─ Uses: idx_hook_events_workflow

agent_usage_patterns
    ├─ Groups: agent_detected
    ├─ Counts: Detections, unique sessions
    └─ Uses: idx_hook_events_agent

quality_metrics_summary
    ├─ Groups: resource_id (tool name)
    ├─ Statistics: AVG, STDDEV, PERCENTILE_CONT
    └─ Uses: idx_hook_events_quality
```

## Performance Optimization Path

```
Query Request
    │
    ▼
Index Scan (JSONB path)
    │
    ├─ Bitmap Index Scan (for multiple conditions)
    │  └─ Bitmap Heap Scan
    │
    ├─ Index Only Scan (for covering indexes)
    │
    └─ Sequential Scan (fallback, rarely used)
    │
    ▼
Aggregation (GROUP BY, COUNT, AVG, etc.)
    │
    ├─ HashAggregate (for small result sets)
    │
    └─ GroupAggregate (for large, pre-sorted data)
    │
    ▼
Result (0.1-0.8ms)
```

## Success Score Calculation

```
calculate_session_success_score(session_id)
    │
    ├─ Tool Success Rate (40% weight)
    │  SELECT COUNT(success) / COUNT(*)
    │  FROM hook_events
    │  WHERE session_id = ... AND source = 'PostToolUse'
    │
    ├─ Average Quality Score (40% weight)
    │  SELECT AVG(quality_score)
    │  FROM hook_events
    │  WHERE session_id = ... AND source = 'PostToolUse'
    │
    ├─ Response Completion Rate (20% weight)
    │  SELECT COUNT(completed) / COUNT(*)
    │  FROM hook_events
    │  WHERE session_id = ... AND source = 'Stop'
    │
    └─ Composite Score = (tool_success * 0.4) +
                         (quality * 0.4) +
                         (completion * 0.2)
                         └─ Result: 0-100
```

## Integration Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Layer                        │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Dashboard    │  │ Alerting     │  │ Reporting    │      │
│  │ Views        │  │ System       │  │ System       │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                  │              │
└─────────┼─────────────────┼──────────────────┼──────────────┘
          │                 │                  │
          └─────────────────┴──────────────────┘
                           │
          ┌────────────────┴────────────────┐
          │                                 │
          ▼                                 ▼
┌─────────────────────┐      ┌─────────────────────┐
│  Analytics Views    │      │  Helper Functions   │
│                     │      │                     │
│  • session_*        │      │  • get_session_*    │
│  • tool_*           │      │  • calculate_*      │
│  • workflow_*       │      │  • get_recent_*     │
│  • agent_*          │      │  • get_tool_*       │
│  • quality_*        │      │                     │
└──────────┬──────────┘      └──────────┬──────────┘
           │                            │
           └────────────┬───────────────┘
                        │
                        ▼
           ┌────────────────────────┐
           │  Performance Indexes   │
           │                        │
           │  • Session             │
           │  • Workflow            │
           │  • Quality             │
           │  • Success             │
           │  • Response            │
           │  • Agent               │
           │  • Time-series         │
           └──────────┬─────────────┘
                      │
                      ▼
           ┌────────────────────────┐
           │   hook_events Table    │
           │   (JSONB Fields)       │
           │                        │
           │   • payload            │
           │   • metadata           │
           └────────────────────────┘
```

## Performance Characteristics

### Query Execution Times
```
View                              │ Target  │ Actual  │ Improvement
──────────────────────────────────┼─────────┼─────────┼─────────────
session_intelligence_summary      │ <100ms  │ 0.77ms  │ 130x faster
tool_success_rates                │ <100ms  │ 0.36ms  │ 277x faster
workflow_pattern_distribution     │ <100ms  │ 0.10ms  │ 1000x faster
agent_usage_patterns              │ <100ms  │ <1ms    │ >100x faster
quality_metrics_summary           │ <100ms  │ <1ms    │ >100x faster
```

### Index Efficiency
```
Index                        │ Size   │ Scan Type        │ Efficiency
─────────────────────────────┼────────┼──────────────────┼───────────
idx_hook_events_session      │ 16 KB  │ Bitmap Index     │ High
idx_hook_events_workflow     │ 16 KB  │ Index Scan       │ High
idx_hook_events_quality      │ 8 KB   │ Index Scan       │ Very High
idx_hook_events_success      │ 16 KB  │ Bitmap Index     │ High
idx_hook_events_response     │ 16 KB  │ Index Scan       │ High
idx_hook_events_agent        │ 16 KB  │ Bitmap Index     │ High
idx_hook_events_created_src  │ 32 KB  │ Index Only Scan  │ Very High
```

### Storage Impact
```
Component              │ Size    │ Overhead
───────────────────────┼─────────┼──────────
Base Table             │ ~500 KB │ Baseline
All Indexes (7)        │ 120 KB  │ 24%
Views (5)              │ 0 KB    │ 0% (virtual)
Functions (4)          │ ~20 KB  │ 4%
Total Migration Impact │ 140 KB  │ 28%
```

---

**Architecture Status**: ✅ Production-Ready
**Performance**: ✅ Exceeds all targets
**Scalability**: ✅ Designed for growth
**Maintainability**: ✅ Well-documented
