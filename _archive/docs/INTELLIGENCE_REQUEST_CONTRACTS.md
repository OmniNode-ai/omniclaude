# Intelligence Request Contracts

**Version**: 2.0.0
**Last Updated**: 2025-10-26
**Purpose**: Define request/response contracts for manifest_injector ↔ archon-intelligence-adapter communication

## Overview

This document specifies the event bus contracts used by `manifest_injector.py` to query `archon-intelligence-adapter` for dynamic system manifest data.

**Architecture**:
```
manifest_injector.py
  → Publishes to Kafka "dev.archon-intelligence.intelligence.code-analysis-requested.v1"
  → archon-intelligence-adapter consumes and queries backends (Qdrant, Memgraph, PostgreSQL)
  → Publishes response to "dev.archon-intelligence.intelligence.code-analysis-completed.v1"
  → manifest_injector formats response for agent
```

## Kafka Topics

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `dev.archon-intelligence.intelligence.code-analysis-requested.v1` | Request | Intelligence queries from omniclaude |
| `dev.archon-intelligence.intelligence.code-analysis-completed.v1` | Response | Successful query results |
| `dev.archon-intelligence.intelligence.code-analysis-failed.v1` | Response | Error responses |

## Base Event Structure

All events follow this base structure:

```json
{
  "event_id": "uuid",
  "event_type": "CODE_ANALYSIS_REQUESTED|CODE_ANALYSIS_COMPLETED|CODE_ANALYSIS_FAILED",
  "correlation_id": "uuid",
  "timestamp": "ISO8601 datetime",
  "service": "omniclaude|archon-intelligence-adapter",
  "payload": {
    // Operation-specific payload
  }
}
```

## Operation Types

### 1. PATTERN_EXTRACTION

Query available code generation patterns from Qdrant vector database.

**Request Payload**:
```json
{
  "source_path": "node_*_*.py",
  "content": null,
  "language": "python",
  "operation_type": "PATTERN_EXTRACTION",
  "options": {
    "include_patterns": true,
    "include_metrics": false,
    "pattern_types": ["CRUD", "Transformation", "Orchestration", "Aggregation"]
  },
  "project_id": "omniclaude",
  "user_id": "system"
}
```

**Response Payload** (CODE_ANALYSIS_COMPLETED):
```json
{
  "patterns": [
    {
      "name": "CRUD Pattern",
      "file_path": "path/to/node_crud_effect.py",
      "description": "Create, Read, Update, Delete operations",
      "node_types": ["EFFECT", "REDUCER"],
      "confidence": 0.95,
      "use_cases": ["Database operations", "API endpoints"],
      "metadata": {
        "complexity": "medium",
        "last_updated": "2025-10-26T12:00:00Z"
      }
    }
  ],
  "query_time_ms": 150,
  "total_count": 4
}
```

**Error Response** (CODE_ANALYSIS_FAILED):
```json
{
  "error_code": "PATTERN_QUERY_FAILED",
  "error_message": "Qdrant connection timeout",
  "error_details": {
    "backend": "qdrant",
    "collection": "code_generation_patterns",
    "reason": "Connection timeout after 5000ms"
  }
}
```

### 2. INFRASTRUCTURE_SCAN

Query current infrastructure topology (databases, Kafka topics, Docker services).

**Request Payload**:
```json
{
  "source_path": "infrastructure",
  "content": null,
  "language": "yaml",
  "operation_type": "INFRASTRUCTURE_SCAN",
  "options": {
    "include_databases": true,
    "include_kafka_topics": true,
    "include_qdrant_collections": true,
    "include_docker_services": true
  },
  "project_id": "omniclaude",
  "user_id": "system"
}
```

**Response Payload** (CODE_ANALYSIS_COMPLETED):
```json
{
  "postgresql": {
    "host": "192.168.86.200",
    "port": 5436,
    "database": "omninode_bridge",
    "status": "connected",
    "tables": [
      {
        "name": "agent_routing_decisions",
        "row_count": 1234,
        "size_mb": 5.2
      }
    ]
  },
  "kafka": {
    "bootstrap_servers": "192.168.86.200:29102",
    "status": "connected",
    "topics": [
      {
        "name": "agent-routing-decisions",
        "partitions": 3,
        "replication_factor": 1,
        "message_count": 5678
      }
    ]
  },
  "qdrant": {
    "endpoint": "localhost:6333",
    "status": "connected",
    "collections": [
      {
        "name": "code_generation_patterns",
        "vector_size": 1536,
        "point_count": 234
      }
    ]
  },
  "docker_services": [
    {
      "name": "archon-intelligence",
      "status": "running",
      "port": 8053,
      "health": "healthy"
    }
  ],
  "query_time_ms": 250
}
```

### 3. MODEL_DISCOVERY

Query available AI models and ONEX data models.

**Request Payload**:
```json
{
  "source_path": "models",
  "content": null,
  "language": "python",
  "operation_type": "MODEL_DISCOVERY",
  "options": {
    "include_ai_models": true,
    "include_onex_models": true,
    "include_quorum_config": true
  },
  "project_id": "omniclaude",
  "user_id": "system"
}
```

**Response Payload** (CODE_ANALYSIS_COMPLETED):
```json
{
  "ai_models": {
    "providers": [
      {
        "name": "Anthropic",
        "models": ["claude-sonnet-4", "claude-opus-4"],
        "status": "available",
        "rate_limit": "Check API dashboard"
      },
      {
        "name": "Google Gemini",
        "models": ["gemini-2.5-flash", "gemini-1.5-pro"],
        "status": "available",
        "rate_limit": "See console"
      }
    ],
    "quorum_config": {
      "total_weight": 7.5,
      "consensus_thresholds": {
        "auto_apply": 0.80,
        "suggest_with_review": 0.60
      }
    }
  },
  "onex_models": {
    "node_types": [
      {
        "name": "EFFECT",
        "naming_pattern": "Node<Name>Effect",
        "file_pattern": "node_*_effect.py",
        "execute_method": "async def execute_effect(self, contract: ModelContractEffect) -> Any",
        "count": 45
      }
    ],
    "contracts": [
      "ModelContractEffect",
      "ModelContractCompute",
      "ModelContractReducer",
      "ModelContractOrchestrator"
    ]
  },
  "intelligence_models": [
    {
      "file": "agents/lib/models/intelligence_context.py",
      "class": "IntelligenceContext",
      "description": "RAG-gathered intelligence for template generation"
    }
  ],
  "query_time_ms": 100
}
```

### 4. SCHEMA_DISCOVERY

Query database schemas and table definitions.

**Request Payload**:
```json
{
  "source_path": "database_schemas",
  "content": null,
  "language": "sql",
  "operation_type": "SCHEMA_DISCOVERY",
  "options": {
    "include_tables": true,
    "include_columns": true,
    "include_indexes": false
  },
  "project_id": "omniclaude",
  "user_id": "system"
}
```

**Response Payload** (CODE_ANALYSIS_COMPLETED):
```json
{
  "tables": [
    {
      "name": "agent_routing_decisions",
      "schema": "public",
      "columns": [
        {
          "name": "id",
          "type": "UUID",
          "nullable": false,
          "primary_key": true
        },
        {
          "name": "user_request",
          "type": "TEXT",
          "nullable": false
        },
        {
          "name": "confidence_score",
          "type": "NUMERIC(5,4)",
          "nullable": false
        }
      ],
      "row_count": 1234,
      "size_mb": 5.2
    }
  ],
  "total_tables": 15,
  "query_time_ms": 200
}
```

## Error Codes

| Error Code | Description | Recommended Action |
|------------|-------------|-------------------|
| `PATTERN_QUERY_FAILED` | Qdrant pattern query failed | Use built-in patterns |
| `INFRASTRUCTURE_SCAN_FAILED` | Infrastructure scan failed | Use connection details only |
| `MODEL_DISCOVERY_FAILED` | Model discovery failed | Use minimal model list |
| `SCHEMA_DISCOVERY_FAILED` | Database schema query failed | Omit schema details |
| `TIMEOUT` | Query exceeded timeout | Reduce query scope or increase timeout |
| `BACKEND_UNAVAILABLE` | Backend service (Qdrant/Memgraph/PostgreSQL) unavailable | Check service health |
| `INVALID_OPERATION` | Unknown operation_type | Check operation_type value |

## Timeout Handling

**Default Timeout**: 2000ms per query

**Parallel Queries**: manifest_injector executes 4 queries in parallel:
- Total expected time: ~2000ms (queries run concurrently)
- Individual query timeout: 2000ms each
- Overall timeout: ~2500ms (with overhead)

**Fallback Strategy**:
1. Individual query fails → Use empty result for that section
2. All queries fail → Use minimal fallback manifest
3. Timeout → Use minimal fallback manifest

## Caching

**Client-Side Cache** (manifest_injector):
- TTL: 300 seconds (5 minutes)
- Cache key: Combined manifest data
- Invalidation: Manual refresh or TTL expiry

**Server-Side Cache** (archon-intelligence-adapter):
- Implementation-specific
- Recommended TTL: 60-300 seconds
- Cache key: Operation type + options hash

## Testing

**Manual Test**:
```bash
# Test manifest generation
cd /Volumes/PRO-G40/Code/omniclaude
python3 claude_hooks/lib/manifest_loader.py
```

**Expected Output**:
```
Testing manifest load (correlation_id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
======================================================================
SYSTEM MANIFEST - Dynamic Context via Event Bus
======================================================================
Version: 2.0.0
Generated: 2025-10-26T...
Source: archon-intelligence-adapter

AVAILABLE PATTERNS:
  • CRUD Pattern (95% confidence)
    File: path/to/node_crud_effect.py
    Node Types: EFFECT, REDUCER
...
```

**Integration Test**:
```python
# Test with IntelligenceEventClient directly
import asyncio
from agents.lib.manifest_injector import ManifestInjector

async def test():
    injector = ManifestInjector()
    manifest = await injector.generate_dynamic_manifest_async("test-correlation-id")
    print(manifest)

asyncio.run(test())
```

## Implementation Notes

### archon-intelligence-adapter Requirements

To support these contracts, archon-intelligence-adapter must:

1. **Consume from correct topic**:
   - Topic: `dev.archon-intelligence.intelligence.code-analysis-requested.v1`
   - Consumer group: `intelligence_adapter_consumers`

2. **Route operations to correct backends**:
   - `PATTERN_EXTRACTION` → Qdrant vector search
   - `INFRASTRUCTURE_SCAN` → PostgreSQL + Docker API + Qdrant admin API + Kafka admin API
   - `MODEL_DISCOVERY` → File system scan + Memgraph query
   - `SCHEMA_DISCOVERY` → PostgreSQL information_schema queries

3. **Publish responses**:
   - Success: `dev.archon-intelligence.intelligence.code-analysis-completed.v1`
   - Failure: `dev.archon-intelligence.intelligence.code-analysis-failed.v1`

4. **Handle correlation tracking**:
   - Preserve `correlation_id` from request to response
   - Use for logging and debugging

5. **Implement timeouts**:
   - Query timeout: 1500ms (allows 500ms for serialization/network)
   - Respond with error if timeout exceeded

### manifest_injector.py Implementation

The implementation:
1. Creates `IntelligenceEventClient` instance
2. Starts client (connects to Kafka)
3. Executes 4 parallel queries using `asyncio.gather()`
4. Waits for responses with 2000ms timeout per query
5. Formats responses into structured manifest
6. Stops client (disconnects from Kafka)
7. Falls back to minimal manifest on error/timeout

## Migration Path

**Phase 1** (Current): Event bus implementation complete
- ✅ manifest_injector.py rewritten for event bus
- ✅ manifest_loader.py updated
- ✅ Contracts documented

**Phase 2** (Next): archon-intelligence-adapter implementation
- ⏳ Implement operation handlers in adapter
- ⏳ Add backend query logic (Qdrant, Memgraph, PostgreSQL)
- ⏳ Deploy and test end-to-end

**Phase 3**: Optimization
- Cache implementation (client + server)
- Performance tuning
- Monitoring and alerting

**Phase 4**: Cleanup
- Remove static YAML files
- Update documentation
- Announce to team

## Related Documentation

- [EVENT_INTELLIGENCE_INTEGRATION_PLAN.md](./EVENT_INTELLIGENCE_INTEGRATION_PLAN.md) - Original integration plan
- [MANIFEST_INJECTION_INTEGRATION.md](./MANIFEST_INJECTION_INTEGRATION.md) - Hook integration
- [IntelligenceEventClient](../agents/lib/intelligence_event_client.py) - Event bus client implementation

## Change Log

| Version | Date | Changes |
|---------|------|---------|
| 2.0.0 | 2025-10-26 | Initial event bus contracts specification |
