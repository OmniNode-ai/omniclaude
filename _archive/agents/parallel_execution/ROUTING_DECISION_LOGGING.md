# Routing Decision Logging

## Overview

The TraceLogger now includes comprehensive routing decision logging to provide full observability into agent selection and routing processes. This enables analysis of routing accuracy, confidence scores, and alternative agent considerations.

## Features

### Core Logging Capabilities
- **ROUTING_DECISION Event Type**: New event type in TraceEventType enum
- **Rich Metadata Capture**: Comprehensive routing context including:
  - User request
  - Selected agent with confidence score
  - Alternative agents considered with their scores
  - Reasoning/explanation for selection
  - Routing strategy used
  - Context information (domain, project type, etc.)
  - Routing performance metrics (time taken)

### Log Levels
Routing decisions are automatically assigned log levels based on confidence:
- **INFO**: Confidence >= 0.5 (normal operations)
- **WARNING**: Confidence < 0.5 (low confidence, needs review)
- **ERROR**: Confidence < 0.3 (very low confidence, potential routing issues)

### Storage Strategy
Routing decisions are stored in two locations:
1. **Coordinator Trace**: Integrated into the main trace timeline
2. **Standalone Files**: Individual JSON files in `traces/routing_decisions/` for easy querying

## Usage

### Logging a Routing Decision

```python
from trace_logger import get_trace_logger

logger = get_trace_logger()

await logger.log_routing_decision(
    user_request="Help me optimize database queries",
    selected_agent="agent-performance-optimizer",
    confidence_score=0.92,
    alternatives=[
        {
            "agent_name": "agent-database-specialist",
            "confidence": 0.85,
            "match_type": "fuzzy"
        }
    ],
    reasoning="Selected due to explicit performance keywords",
    routing_strategy="enhanced_fuzzy_matching",
    context={
        "domain": "performance_optimization",
        "project_type": "database_heavy"
    },
    routing_time_ms=45.3
)
```

### Querying Routing Decisions

#### Get Recent Decisions
```python
recent = await logger.get_recent_routing_decisions(limit=10)
for event in recent:
    metadata = event.metadata
    print(f"Agent: {metadata['selected_agent']}")
    print(f"Confidence: {metadata['confidence_score']:.2%}")
```

#### Get Low Confidence Decisions
```python
low_conf = await logger.get_low_confidence_routing_decisions(
    confidence_threshold=0.7,
    limit=20
)
```

#### Get Decisions for Specific Agent
```python
decisions = await logger.get_routing_decisions_for_agent(
    "agent-performance-optimizer",
    limit=20
)
```

#### Advanced Query with Filters
```python
results = await logger.query_routing_decisions(
    agent_name="agent-debug-intelligence",
    min_confidence=0.5,
    max_confidence=0.8,
    routing_strategy="fuzzy",
    limit=50
)
```

### Routing Statistics

```python
# Get statistics programmatically
stats = await logger.get_routing_statistics()
print(f"Total decisions: {stats['total_decisions']}")
print(f"Average confidence: {stats['avg_confidence']:.2%}")
print(f"Low confidence rate: {stats['low_confidence_rate']:.2%}")

# Print formatted statistics report
await logger.print_routing_statistics()
```

## Data Structure

### Routing Metadata Fields

```json
{
  "user_request": "Original user request text",
  "selected_agent": "agent-name",
  "confidence_score": 0.92,
  "reasoning": "Explanation for selection...",
  "routing_strategy": "enhanced_fuzzy_matching",
  "alternatives": [
    {
      "agent_name": "alternative-agent",
      "confidence": 0.85,
      "match_type": "fuzzy",
      "reason": "Why this was considered"
    }
  ],
  "context": {
    "domain": "performance_optimization",
    "project_type": "database_heavy",
    "previous_agent": null
  },
  "routing_time_ms": 45.3,
  "alternatives_count": 3,
  "top_3_alternatives": [...]
}
```

## Statistics Available

The routing statistics API provides:

1. **Total Decisions**: Count of all routing decisions made
2. **Agents Selected**: Distribution of which agents were selected
3. **Average Confidence**: Mean confidence score across all decisions
4. **Confidence Distribution**: Breakdown by confidence ranges:
   - 0.0-0.3 (critical)
   - 0.3-0.5 (warning)
   - 0.5-0.7 (low)
   - 0.7-0.9 (good)
   - 0.9-1.0 (excellent)
5. **Routing Strategies**: Which strategies were used
6. **Low Confidence Rate**: Percentage of decisions below 0.7 confidence

## File Locations

- **Routing Decisions**: `traces/routing_decisions/routing_YYYYMMDD_HHMMSS_MICROSEC.json`
- **Coordinator Traces**: `traces/coord_TIMESTAMP_ID.json` (includes routing events)

## Integration with Database (Future)

When Stream 1 completes database schema creation, routing decisions will be persisted to:
- Table: `agent_routing_decisions`
- Fields: All metadata fields plus timestamps and IDs
- Benefits:
  - Faster querying with SQL
  - Better analytics and aggregations
  - Historical trend analysis
  - Cross-session routing pattern analysis

## Example Output

### Routing Statistics Report
```
================================================================================
🎯 Routing Decision Statistics
================================================================================
Total Decisions: 150
Average Confidence: 78.50%
Low Confidence Rate: 12.00% (18 decisions)

================================================================================
Agents Selected:
================================================================================
  agent-performance-optimizer                 45 ( 30.0%)
  agent-debug-intelligence                    38 ( 25.3%)
  agent-database-specialist                   32 ( 21.3%)
  agent-code-quality                          20 ( 13.3%)
  agent-workflow-coordinator                  15 ( 10.0%)

================================================================================
Confidence Distribution:
================================================================================
  0.0-0.3        2 (  1.3%)
  0.3-0.5        5 (  3.3%) █
  0.5-0.7       11 (  7.3%) ███
  0.7-0.9       72 ( 48.0%) ████████████████████████
  0.9-1.0       60 ( 40.0%) ████████████████████

================================================================================
Routing Strategies:
================================================================================
  enhanced_fuzzy_matching    85 ( 56.7%)
  exact_match                40 ( 26.7%)
  fallback                   15 ( 10.0%)
  capability_based           10 (  6.7%)
================================================================================
```

## Best Practices

1. **Always Log Routing Decisions**: Every agent selection should be logged for observability
2. **Include Context**: Provide domain, project type, and other relevant context
3. **Explain Reasoning**: Clear reasoning helps debug routing issues
4. **Monitor Low Confidence**: Regularly review low confidence decisions to improve routing
5. **Track Performance**: Include routing_time_ms to identify performance bottlenecks
6. **Analyze Patterns**: Use statistics to identify routing improvements

## Performance Considerations

- File-based storage is efficient for < 10,000 decisions
- Query operations scan files, O(n) complexity
- Consider rotating old routing decision files (30+ days)
- Database persistence (coming in Stream 1) will provide better performance for large datasets

## See Also

- `example_routing_decision_logging.py` - Complete usage examples
- `trace_logger.py` - TraceLogger implementation
- Stream 1 documentation (when available) - Database persistence details
