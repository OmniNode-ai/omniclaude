# Agent Transformation Tracker

## Overview

The Agent Transformation Tracker provides comprehensive observability for agent identity transformations in the OmniClaude polymorphic agent framework. It tracks when the workflow coordinator assumes specialized agent identities, measuring performance, analyzing patterns, and generating dashboard metrics.

## Features

### Core Capabilities

1. **Transformation Event Tracking**
   - Full context capture (source, target, reasoning)
   - Capability inheritance tracking
   - Performance measurement (<50ms target)
   - File-based persistence with daily organization

2. **Pattern Recognition**
   - Automatic pattern detection (min 3 occurrences)
   - Common transformation pairs analysis
   - Success rate tracking per pattern
   - Transformation frequency analysis

3. **Performance Monitoring**
   - Overhead measurement per transformation
   - Threshold compliance tracking (CTX-002: 50ms)
   - Alert generation for threshold violations
   - Performance trend analysis

4. **Dashboard Metrics**
   - Comprehensive transformation statistics
   - Identity usage analysis (source/target)
   - Time-based activity metrics
   - Confidence score distributions

5. **TraceLogger Integration**
   - Automatic AGENT_TRANSFORM event logging
   - Parent-child trace relationships
   - Unified observability across systems

## Architecture

### Components

```
transformation_tracker.py
├── TransformationEvent          # Single transformation event model
├── TransformationPattern         # Identified transformation pattern
├── TransformationMetrics         # Dashboard-ready metrics
└── AgentTransformationTracker    # Main tracking class
```

### Event Types

**AGENT_TRANSFORM**: New event type added to `TraceEventType` enum for transformation tracking.

### Storage Structure

```
traces/
└── transformations/
    └── YYYYMMDD/                    # Daily subdirectories
        └── transform_HHMMSS_source_to_target.json
```

## Usage

### Basic Transformation Tracking

```python
from transformation_tracker import get_transformation_tracker

tracker = get_transformation_tracker()

# Track a transformation
event = await tracker.track_transformation(
    source_identity="agent-workflow-coordinator",
    target_identity="agent-debug-intelligence",
    user_request="Analyze performance bottleneck",
    transformation_reason="Debug intelligence required",
    capabilities_inherited=[
        "systematic_debugging",
        "performance_profiling"
    ],
    routing_confidence=0.92,
    task_id="task-123"
)

print(f"Overhead: {event.transformation_overhead_ms:.2f}ms")
```

### With Pre-Measured Timing

```python
# When you've already measured agent load time
event = await tracker.track_transformation_with_timing(
    source_identity="agent-workflow-coordinator",
    target_identity="agent-api-architect",
    user_request="Design REST API",
    transformation_reason="API design specialist required",
    agent_load_time_ms=12.5,  # Pre-measured
    routing_confidence=0.95
)
```

### Pattern Analysis

```python
# Analyze transformation patterns
patterns = await tracker.analyze_patterns(min_occurrences=3)

for pattern in patterns:
    print(f"{pattern.source_target_pair[0]} → {pattern.source_target_pair[1]}")
    print(f"  Occurrences: {pattern.occurrence_count}")
    print(f"  Avg Time: {pattern.avg_transformation_time_ms:.2f}ms")
    print(f"  Success Rate: {pattern.success_rate:.2%}")
```

### Dashboard Metrics

```python
# Get comprehensive metrics
metrics = await tracker.get_metrics()

print(f"Total Transformations: {metrics.total_transformations}")
print(f"Avg Overhead: {metrics.avg_transformation_overhead_ms:.2f}ms")
print(f"Threshold Compliance: {metrics.threshold_compliance_rate:.2%}")
print(f"Most Common: {metrics.most_common_transformation}")

# Or print formatted summary
await tracker.print_metrics_summary()
```

### Transformation History

```python
# Get recent history
history = await tracker.get_transformation_history(
    source_identity="agent-workflow-coordinator",  # Optional filter
    target_identity="agent-debug-intelligence",     # Optional filter
    limit=50
)

for event in history:
    print(f"{event.datetime_str}: {event.source_identity} → {event.target_identity}")
```

## Integration Points

### Enhanced Router Integration

```python
from enhanced_router import EnhancedAgentRouter
from transformation_tracker import get_transformation_tracker

router = EnhancedAgentRouter()
tracker = get_transformation_tracker()

# Route request
recommendations = router.route(user_request)
selected = recommendations[0]

# Track transformation
await tracker.track_transformation(
    source_identity="agent-workflow-coordinator",
    target_identity=selected.agent_name,
    user_request=user_request,
    transformation_reason=selected.reason,
    routing_confidence=selected.confidence.total,
    agent_definition_path=selected.definition_path
)
```

### Agent Dispatcher Integration

```python
# In agent_dispatcher.py
async def _execute_agent_task(self, agent_name: str, task: Dict[str, Any]):
    tracker = get_transformation_tracker()

    # Measure agent loading time
    load_start = time.time()
    agent = await self._load_agent(agent_name)
    load_time_ms = (time.time() - load_start) * 1000

    # Track transformation
    await tracker.track_transformation_with_timing(
        source_identity=self.coordinator_identity,
        target_identity=agent_name,
        user_request=task['description'],
        transformation_reason=f"Task requires {agent_name} capabilities",
        agent_load_time_ms=load_time_ms,
        task_id=task['id']
    )

    # Execute agent
    result = await agent.execute(task)
    return result
```

## Performance Thresholds

From `performance-thresholds.yaml`:

- **CTX-002**: Context Preservation Latency = 25ms (preservation time)
- **Target**: Total transformation overhead <50ms

### Threshold Monitoring

```python
metrics = await tracker.get_metrics()

if metrics.threshold_compliance_rate < 0.95:
    print(f"⚠️  Warning: Only {metrics.threshold_compliance_rate:.2%} compliance")
    print(f"   {metrics.transformations_over_threshold} transformations exceeded 50ms")

    # Analyze slow transformations
    history = await tracker.get_transformation_history(limit=100)
    slow_transformations = [e for e in history
                           if e.transformation_overhead_ms > 50]

    for event in slow_transformations:
        print(f"   {event.target_identity}: {event.transformation_overhead_ms:.2f}ms")
```

## Quality Gates

Implements validation for quality gates:

- **CV-001**: Context Inheritance (validation during delegation)
- **PF-001**: Performance Thresholds (real-time monitoring)
- **KV-001**: UAKS Integration (pattern learning contribution)

## Database Migration (Future)

When Stream 1 (database schema) is complete:

1. **Migration Path**:
   - Current: File-based JSON storage
   - Future: PostgreSQL `agent_transformation_events` table
   - Code structure supports easy migration

2. **Database Schema** (from Stream 1):
   ```sql
   CREATE TABLE agent_transformation_events (
       transformation_id UUID PRIMARY KEY,
       timestamp TIMESTAMPTZ NOT NULL,
       source_identity VARCHAR(255),
       target_identity VARCHAR(255),
       transformation_reason TEXT,
       user_request TEXT,
       routing_confidence FLOAT,
       capabilities_inherited JSONB,
       context_preserved JSONB,
       transformation_overhead_ms FLOAT,
       agent_load_time_ms FLOAT,
       total_time_ms FLOAT,
       task_id VARCHAR(255),
       coordinator_id VARCHAR(255),
       success BOOLEAN DEFAULT true,
       error TEXT
   );
   ```

3. **Migration Steps**:
   - Add `asyncpg` connection pool
   - Implement `_write_to_database()` method
   - Keep file-based writes for redundancy
   - Migrate historical data from JSON files

## Demo & Testing

Run the comprehensive demo:

```bash
cd agents/parallel_execution
python demo_transformation_tracking.py
```

This demonstrates:
1. Basic transformation tracking
2. Pattern recognition
3. Performance monitoring
4. Dashboard metrics generation
5. TraceLogger integration
6. Statistics reporting

## Monitoring & Alerts

### Key Metrics to Monitor

1. **Performance**:
   - Average transformation overhead
   - Threshold compliance rate
   - Max transformation time

2. **Patterns**:
   - Most common transformations
   - Success rates per pattern
   - Transformation frequency

3. **Activity**:
   - Transformations per hour
   - Recent activity trends
   - Identity usage distribution

### Alert Thresholds

- **Warning**: Transformation overhead >50ms
- **Error**: Success rate <95%
- **Critical**: Threshold compliance <90%

## Best Practices

1. **Always track transformations**: Every agent identity switch should be tracked
2. **Include full context**: Capture reasoning, capabilities, and context preservation
3. **Measure performance**: Use timing data to identify optimization opportunities
4. **Analyze patterns**: Regular pattern analysis reveals optimization targets
5. **Monitor thresholds**: Watch for threshold violations indicating performance issues
6. **Integrate with routing**: Combine with routing confidence for quality insights

## Troubleshooting

### High Transformation Overhead

If transformations consistently exceed 50ms:

1. Profile agent loading time
2. Check agent definition size
3. Review capability inheritance complexity
4. Consider agent pre-loading/caching

### Low Confidence Transformations

If routing confidence is consistently low:

1. Review trigger matching quality
2. Analyze user request patterns
3. Improve agent definition triggers
4. Consider expanding capability index

### Pattern Recognition Issues

If patterns aren't being identified:

1. Ensure min_occurrences threshold is appropriate
2. Check transformation cache size
3. Verify sufficient transformation volume
4. Review pattern matching logic

## Future Enhancements

1. **Database Integration**: Migrate to PostgreSQL for queryability
2. **Real-time Dashboard**: Web-based visualization of metrics
3. **Predictive Analytics**: ML-based transformation prediction
4. **Auto-optimization**: Automatic agent pre-loading based on patterns
5. **Cross-project Analysis**: Compare transformation patterns across projects
6. **Alert System**: Automated threshold violation notifications

## Files

- `transformation_tracker.py`: Main tracker implementation
- `demo_transformation_tracking.py`: Comprehensive demo
- `trace_logger.py`: Extended with AGENT_TRANSFORM event type
- Storage: `traces/transformations/YYYYMMDD/*.json`

## Dependencies

- Stream 1: Database schema (for future migration)
- Stream 2: Enhanced router (for routing integration)
- TraceLogger: Event propagation and unified observability
- Pydantic: Data models and validation
- asyncio: Async/await patterns

## Acceptance Criteria Status

- ✅ All agent transformations logged with full context
- ✅ Identity assumption reasoning captured
- ✅ Transformation patterns analyzed and reported
- ✅ Performance impact measured (<50ms target)
- ✅ Dashboard-ready metrics generated
- ✅ File-based persistence implemented
- ✅ TraceLogger integration complete
- ✅ Pattern recognition working
- ⏳ Database integration (pending Stream 1)
- ⏳ Enhanced router integration (pending Stream 2)

## Contact

For questions or issues with the transformation tracker:
- See: `agents/parallel_execution/TRANSFORMATION_TRACKER_README.md`
- Demo: Run `python demo_transformation_tracking.py`
- Integration: Check `demo_transformation_tracking.py` for patterns
