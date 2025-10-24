# Request Intelligence Skill

Request intelligence operations from the Omni Archon intelligence adapter.

## Operations

### Pattern Discovery
Find similar code patterns in the codebase:
```bash
/request-intelligence --operation pattern-discovery --source-path "node_*_effect.py" --language python
```

### Code Analysis
Analyze code for quality, compliance, and issues:
```bash
/request-intelligence --operation code-analysis --file path/to/file.py --language python
```

### Quality Assessment
Assess code quality and ONEX compliance:
```bash
/request-intelligence --operation quality-assessment --content "code here" --language python --include-metrics
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--operation` | Yes | Operation type: `pattern-discovery`, `code-analysis`, `quality-assessment` |
| `--source-path` | Conditional | File pattern (required for pattern-discovery) |
| `--file` | Conditional | Specific file path (required for analysis operations if no --content) |
| `--content` | Conditional | Inline code content (alternative to --file) |
| `--language` | No | Programming language (default: python) |
| `--timeout-ms` | No | Request timeout in milliseconds (default: 10000) |
| `--include-metrics` | No | Include detailed metrics in response (default: false) |
| `--correlation-id` | No | Correlation ID for tracking (auto-generated if not provided) |
| `--kafka-brokers` | No | Kafka bootstrap servers (default: localhost:29092) |

## Response Format

### Success Response
```json
{
  "success": true,
  "operation": "pattern-discovery",
  "correlation_id": "uuid",
  "patterns_found": 5,
  "patterns": [...]
}
```

### Error Response
```json
{
  "success": false,
  "operation": "pattern-discovery",
  "correlation_id": "uuid",
  "error": "Request timeout after 10000ms",
  "hint": "Intelligence adapter may be down or overloaded..."
}
```

## Requirements

- Kafka broker running on localhost:29092 (or configured via --kafka-brokers)
- Omni Archon intelligence adapter service running and healthy
- OMNICLAUDE_PATH environment variable set (or defaults to script's project root)

## Integration

This skill uses the `IntelligenceEventClient` from omniclaude to dispatch requests
through the event-driven intelligence architecture, ensuring:
- Request-response pattern with correlation tracking
- Timeout handling with graceful degradation
- Wire compatibility with Omni Archon's confluent-kafka handler
- Performance targets: <100ms p95 response time

## See Also

- EVENT_INTELLIGENCE_INTEGRATION_PLAN.md - Complete architecture documentation
- intelligence_event_client.py - Client implementation
