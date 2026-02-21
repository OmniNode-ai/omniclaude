# Agent Tracking Skills

Comprehensive PostgreSQL-backed skills for tracking agent routing decisions, detection failures, transformations, and performance metrics. These skills replace manual SQL operations in the routing system.

## Overview

The agent tracking system provides 4 specialized skills for complete observability:

1. **log-routing-decision** - Track successful routing decisions
2. **log-detection-failure** - Track detection failures (critical gap)
3. **log-transformation** - Track agent transformations
4. **log-performance-metrics** - Track router performance

All skills use shared database connection pooling, consistent error handling, and correlation ID tracking.

## Skills

### 1. log-routing-decision

**Purpose**: Log routing decisions made by the agent workflow coordinator.

**Database Table**: `agent_routing_decisions`

**Usage**:
```bash
/log-routing-decision \
  --agent agent-api-architect \
  --confidence 0.92 \
  --strategy enhanced_fuzzy_matching \
  --latency-ms 45
```

**Required Arguments**:
- `--agent` - Selected agent name
- `--confidence` - Confidence score (0.0-1.0)
- `--strategy` - Routing strategy used
- `--latency-ms` - Routing latency in milliseconds

**Optional Arguments**:
- `--correlation-id` - Correlation ID for tracking (auto-generated if not provided)
- `--user-request` - Original user request text
- `--alternatives` - JSON array of alternative agents considered
- `--reasoning` - Reasoning for agent selection
- `--context` - JSON object with additional context

**Example with Full Options**:
```bash
/log-routing-decision \
  --agent agent-api-architect \
  --confidence 0.92 \
  --strategy enhanced_fuzzy_matching \
  --latency-ms 45 \
  --user-request "optimize my API performance" \
  --alternatives '[{"agent": "agent-performance-optimizer", "confidence": 0.89}]' \
  --reasoning "Strong trigger match and context alignment" \
  --context '{"domain": "api_development", "previous_agent": "agent-workflow-coordinator"}'
```

**Output**:
```json
{
  "success": true,
  "routing_decision_id": "uuid",
  "correlation_id": "uuid",
  "selected_agent": "agent-api-architect",
  "confidence_score": 0.92,
  "routing_strategy": "enhanced_fuzzy_matching",
  "routing_time_ms": 45,
  "created_at": "2025-10-20T16:30:00Z"
}
```

### 2. log-detection-failure

**Purpose**: Log failures in agent detection (critical observability gap).

**Database Table**: `agent_detection_failures`

**Usage**:
```bash
/log-detection-failure \
  --prompt "user request text" \
  --reason "no matching triggers found" \
  --candidates-evaluated 5
```

**Required Arguments**:
- `--prompt` - User prompt that failed detection
- `--reason` - Reason for detection failure
- `--candidates-evaluated` - Number of agents evaluated

**Optional Arguments**:
- `--correlation-id` - Correlation ID for tracking (auto-generated if not provided)
- `--status` - Detection status (default: no_detection)
  - Valid values: `no_detection`, `low_confidence`, `wrong_agent`, `timeout`, `error`
- `--detected-agent` - Agent that was detected (if any)
- `--confidence` - Detection confidence score (0.0-1.0)
- `--expected-agent` - Expected agent name (if known)
- `--detection-method` - Method used for detection
- `--trigger-matches` - JSON array of trigger match results
- `--capability-scores` - JSON object with capability scores
- `--fuzzy-results` - JSON array of fuzzy match results
- `--metadata` - Additional JSON metadata

**Example with Full Options**:
```bash
/log-detection-failure \
  --prompt "optimize database queries" \
  --reason "no matching triggers found" \
  --candidates-evaluated 5 \
  --status low_confidence \
  --detected-agent agent-debug-intelligence \
  --confidence 0.45 \
  --expected-agent agent-performance-optimizer \
  --detection-method enhanced_fuzzy_matching \
  --trigger-matches '[{"trigger": "optimize", "score": 0.6}]' \
  --capability-scores '{"performance": 0.5, "database": 0.3}' \
  --fuzzy-results '[{"agent": "agent-debug-intelligence", "score": 0.45}]'
```

**Output**:
```json
{
  "success": true,
  "failure_id": 123,
  "correlation_id": "uuid",
  "detection_status": "low_confidence",
  "failure_reason": "no matching triggers found",
  "candidates_evaluated": 5,
  "prompt_length": 25,
  "created_at": "2025-10-20T16:30:00Z"
}
```

### 3. log-transformation

**Purpose**: Log agent transformation events during workflow execution.

**Database Table**: `agent_transformation_events`

**Usage**:
```bash
/log-transformation \
  --from-agent agent-workflow-coordinator \
  --to-agent agent-api-architect \
  --success true \
  --duration-ms 85
```

**Required Arguments**:
- `--from-agent` - Source agent name
- `--to-agent` - Target agent name
- `--success` - Whether transformation succeeded (true/false)
- `--duration-ms` - Transformation duration in milliseconds

**Optional Arguments**:
- `--correlation-id` - Correlation ID for tracking (auto-generated if not provided)
- `--reason` - Transformation reason/description
- `--confidence` - Routing confidence score that led to transformation (0.0-1.0)

**Example with Full Options**:
```bash
/log-transformation \
  --from-agent agent-workflow-coordinator \
  --to-agent agent-api-architect \
  --success true \
  --duration-ms 85 \
  --reason "User request matched API architecture domain" \
  --confidence 0.92
```

**Output**:
```json
{
  "success": true,
  "transformation_id": "uuid",
  "correlation_id": "uuid",
  "source_agent": "agent-workflow-coordinator",
  "target_agent": "agent-api-architect",
  "transformation_success": true,
  "duration_ms": 85,
  "created_at": "2025-10-20T16:30:00Z"
}
```

### 4. log-performance-metrics

**Purpose**: Log router performance metrics for optimization analysis.

**Database Table**: `router_performance_metrics`

**Usage**:
```bash
/log-performance-metrics \
  --query "optimize API performance" \
  --duration-ms 45 \
  --cache-hit false \
  --candidates 5
```

**Required Arguments**:
- `--query` - Query text that was routed
- `--duration-ms` - Routing duration in milliseconds (must be < 1000)
- `--cache-hit` - Whether result was from cache (true/false)
- `--candidates` - Number of candidate agents evaluated

**Optional Arguments**:
- `--correlation-id` - Correlation ID for tracking (auto-generated if not provided)
- `--strategy` - Trigger match strategy used
- `--confidence-components` - JSON object with confidence breakdown

**Example with Full Options**:
```bash
/log-performance-metrics \
  --query "optimize API performance" \
  --duration-ms 45 \
  --cache-hit false \
  --candidates 5 \
  --strategy enhanced_fuzzy_matching \
  --confidence-components '{"trigger": 0.92, "context": 0.85, "capability": 0.78, "historical": 0.90}'
```

**Output**:
```json
{
  "success": true,
  "metric_id": "uuid",
  "correlation_id": "uuid",
  "query_text": "optimize API performance",
  "routing_duration_ms": 45,
  "cache_hit": false,
  "candidates_evaluated": 5,
  "created_at": "2025-10-20T16:30:00Z"
}
```

## Complete Workflow Example

Here's a complete workflow showing all 4 skills in action:

```bash
# 1. Log performance metrics (start of routing)
CORRELATION_ID=$(uuidgen)
/log-performance-metrics \
  --query "optimize my database queries" \
  --duration-ms 52 \
  --cache-hit false \
  --candidates 7 \
  --correlation-id $CORRELATION_ID

# 2a. If routing succeeds - log the decision
/log-routing-decision \
  --agent agent-performance-optimizer \
  --confidence 0.89 \
  --strategy enhanced_fuzzy_matching \
  --latency-ms 52 \
  --correlation-id $CORRELATION_ID \
  --user-request "optimize my database queries"

# 2b. If routing fails - log the failure instead
/log-detection-failure \
  --prompt "optimize my database queries" \
  --reason "low confidence match" \
  --candidates-evaluated 7 \
  --status low_confidence \
  --correlation-id $CORRELATION_ID

# 3. Log transformation (when coordinator transforms)
/log-transformation \
  --from-agent agent-workflow-coordinator \
  --to-agent agent-performance-optimizer \
  --success true \
  --duration-ms 85 \
  --correlation-id $CORRELATION_ID \
  --confidence 0.89
```

## Database Configuration

All skills use shared database configuration from `skills/_shared/db_helper.py`:

```python
DB_CONFIG = {
    "host": "localhost",
    "port": 5436,
    "database": "omniclaude",
    "user": "postgres",
    "password": "<your-postgres-password>",  # Set via POSTGRES_PASSWORD env var
}
```

## Shared Features

### Correlation ID Tracking

All skills support correlation ID tracking for linking related operations:

- Auto-generated using `uuid.uuid4()` if not provided
- Can be explicitly set via `--correlation-id` flag
- Automatically reads from `CORRELATION_ID` environment variable
- Essential for tracing complete workflow execution

### Error Handling

All skills use consistent error handling:

```json
{
  "success": false,
  "error": "Error description",
  "operation": "operation_name",
  "timestamp": "2025-10-20T16:30:00Z"
}
```

### Connection Pooling

Shared connection pool configuration:
- Min connections: 1
- Max connections: 5
- Automatic connection lifecycle management
- Graceful error recovery

### JSON Parameter Parsing

All JSON parameters are safely parsed with error handling:
- Validates JSON syntax
- Returns meaningful error messages
- Supports complex nested structures

## Integration with Agent Workflow Coordinator

The agent workflow coordinator should use these skills at key decision points:

### 1. Pre-Routing Intelligence
```python
# Before routing decision
start_time = time.time()
recommendations = router.route(user_request, context)
duration_ms = int((time.time() - start_time) * 1000)

# Log performance metrics
/log-performance-metrics \
  --query "$user_request" \
  --duration-ms $duration_ms \
  --cache-hit false \
  --candidates ${#recommendations[@]}
```

### 2. Routing Decision
```python
# If routing succeeds
if recommendations:
    selected = recommendations[0]
    /log-routing-decision \
      --agent $selected.agent_name \
      --confidence $selected.confidence \
      --strategy $selected.routing_strategy \
      --latency-ms $duration_ms

# If routing fails
else:
    /log-detection-failure \
      --prompt "$user_request" \
      --reason "no matching agents" \
      --candidates-evaluated 0 \
      --status no_detection
```

### 3. Agent Transformation
```python
# When transforming to selected agent
start_time = time.time()
success = load_agent_definition(selected.definition_path)
duration_ms = int((time.time() - start_time) * 1000)

/log-transformation \
  --from-agent agent-workflow-coordinator \
  --to-agent $selected.agent_name \
  --success $success \
  --duration-ms $duration_ms
```

## Observability Queries

### Find Detection Failures
```sql
SELECT user_prompt, failure_reason, detection_status, candidates_evaluated
FROM agent_detection_failures
WHERE reviewed = false
ORDER BY created_at DESC
LIMIT 20;
```

### Analyze Routing Performance
```sql
SELECT
  trigger_match_strategy,
  AVG(routing_duration_ms) as avg_duration,
  COUNT(*) as total_routes
FROM router_performance_metrics
GROUP BY trigger_match_strategy
ORDER BY avg_duration DESC;
```

### Track Agent Transformations
```sql
SELECT
  target_agent,
  COUNT(*) as transformation_count,
  AVG(transformation_duration_ms) as avg_duration,
  SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / COUNT(*) as success_rate
FROM agent_transformation_events
GROUP BY target_agent
ORDER BY transformation_count DESC;
```

### Routing Decision Analysis
```sql
SELECT
  selected_agent,
  AVG(confidence_score) as avg_confidence,
  COUNT(*) as decision_count,
  AVG(routing_time_ms) as avg_routing_time
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY selected_agent
ORDER BY decision_count DESC;
```

## Troubleshooting

### Skill Not Found
Ensure the skill is executable:
```bash
chmod +x skills/agent-tracking/*/execute.py
```

### Database Connection Failed
Check database is running:
```bash
pg_isready -h localhost -p 5436
```

### Invalid JSON Parameter
Use single quotes around JSON, double quotes inside:
```bash
--alternatives '[{"agent": "name", "confidence": 0.9}]'
```

### Correlation ID Not Propagating
Set environment variable before skill execution:
```bash
export CORRELATION_ID=$(uuidgen)
/log-routing-decision --agent agent-name ...
```

## Performance Considerations

- **Connection Pooling**: Reuses database connections for efficiency
- **Async Ready**: Skills can be called asynchronously in Python
- **Batch Operations**: Consider batching multiple log calls in high-throughput scenarios
- **Index Usage**: All tables have proper indexes for common query patterns

## Security

- **Parameterized Queries**: All SQL uses parameterized queries to prevent injection
- **Credential Management**: Database credentials in shared config file
- **Input Validation**: All inputs validated before database insertion
- **Error Messages**: Sensitive data not exposed in error messages
