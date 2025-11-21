# Output Format Specification

**Version**: 1.0.0
**Last Updated**: 2025-11-20
**Applies To**: All system-status skills

This document defines standard output formats and exit codes for all system-status skills, ensuring consistent, predictable responses across the skill suite.

---

## Table of Contents

1. [Exit Code Conventions](#exit-code-conventions)
2. [JSON Response Structures](#json-response-structures)
3. [Common Field Standards](#common-field-standards)
4. [Status Value Conventions](#status-value-conventions)
5. [Timestamp Formats](#timestamp-formats)
6. [Metric Representations](#metric-representations)
7. [Output Format Modes](#output-format-modes)
8. [Skill-Specific Outputs](#skill-specific-outputs)
9. [Error Handling](#error-handling)
10. [Examples](#examples)

---

## Exit Code Conventions

All skills follow these standard exit codes:

| Exit Code | Meaning | When Used | Recovery Action |
|-----------|---------|-----------|-----------------|
| **0** | Success / Healthy | All checks pass, no issues found | None - system is healthy |
| **1** | Warning / Degraded | Non-critical issues detected | Review warnings, consider fixes |
| **2** | Critical Issues | Critical problems found | Immediate action required |
| **3** | Execution Error | Script failed to execute | Debug script/environment |

### Exit Code Usage by Skill

| Skill | Exit 0 | Exit 1 | Exit 2 | Exit 3 |
|-------|--------|--------|--------|--------|
| **check-system-health** | All healthy | Degraded state | Critical issues | Execution error |
| **diagnose-issues** | No issues | Warnings found | Critical found | Execution error |
| **check-infrastructure** | N/A* | N/A* | N/A* | Import/runtime error |
| **check-service-status** | N/A* | Service error | N/A* | Import/runtime error |
| **check-database-health** | N/A* | N/A* | N/A* | Import/runtime error |
| **check-agent-performance** | N/A* | N/A* | N/A* | Import/runtime error |
| **check-kafka-topics** | N/A* | N/A* | N/A* | Import/runtime error |
| **check-pattern-discovery** | N/A* | N/A* | N/A* | Import/runtime error |
| **check-recent-activity** | N/A* | N/A* | N/A* | Import/runtime error |
| **generate-status-report** | N/A* | N/A* | N/A* | Import/runtime error |

*N/A = Skill returns 0 on success or 1 on error (no health-based exit codes)

---

## JSON Response Structures

All skills output JSON by default. The structure varies by response type:

### Success Response (Data Available)

Most skills return structured data **without** a top-level `success` field:

```json
{
  "component": "kafka",
  "status": "connected",
  "broker": "192.168.86.200:29092",
  "reachable": true,
  "topics": 15,
  "error": null
}
```

**Characteristics**:
- No `success: true` field (implicit from presence of data)
- Component-specific data fields
- `error` field present but null on success
- Exit code 0

### Error Response

Errors use a standard format with `success: false`:

```json
{
  "success": false,
  "error": "Failed to connect to Kafka broker: Connection refused",
  "timestamp": "2025-11-20T14:30:00Z"
}
```

**Characteristics**:
- `success: false` explicitly indicates error
- `error` field contains descriptive message
- Optional `timestamp` for when error occurred
- Optional `hint` for troubleshooting guidance
- Exit code 1 or 3

### Mixed Response (Multiple Components)

When checking multiple components, responses combine status and errors:

```json
{
  "kafka": {
    "status": "connected",
    "broker": "192.168.86.200:29092",
    "reachable": true,
    "error": null
  },
  "postgres": {
    "status": "error",
    "error": "Connection refused"
  },
  "qdrant": {
    "status": "connected",
    "url": "http://localhost:6333",
    "reachable": true,
    "error": null
  }
}
```

**Characteristics**:
- Each component has its own status
- Individual `error` fields per component
- No top-level `success` field
- Exit code based on most severe issue

### Health Check Response

Health check skills return comprehensive status:

```json
{
  "status": "healthy",
  "timestamp": "2025-11-20T14:30:00Z",
  "check_duration_ms": 450,
  "services": {
    "total": 10,
    "running": 10,
    "stopped": 0,
    "unhealthy": 0
  },
  "infrastructure": {
    "kafka": { "status": "connected", ... },
    "postgres": { "status": "connected", ... },
    "qdrant": { "status": "connected", ... }
  },
  "recent_activity": {
    "timeframe": "5m",
    "agent_executions": 12,
    "routing_decisions": 15
  },
  "issues": [],
  "recommendations": []
}
```

**Characteristics**:
- Top-level `status` field (healthy/degraded/critical)
- `timestamp` in ISO 8601 format
- `check_duration_ms` for performance tracking
- Nested component details
- `issues` array (empty if healthy)
- `recommendations` array for fixes
- Exit code matches status severity

### Diagnostic Response

Diagnostic skills return issue-focused output:

```json
{
  "system_health": "degraded",
  "issues_found": 2,
  "critical": 0,
  "warnings": 2,
  "issues": [
    {
      "severity": "warning",
      "component": "postgres",
      "issue": "Connection pool near capacity",
      "details": "Active connections: 85/100",
      "recommendation": "Consider increasing max_connections",
      "auto_fix_available": false
    }
  ],
  "recommendations": [
    "Consider increasing max_connections or optimizing queries"
  ]
}
```

**Characteristics**:
- `system_health` field (healthy/degraded/critical)
- Issue counts by severity
- Detailed `issues` array
- Structured issue objects with severity
- Actionable `recommendations`
- Exit code based on `system_health`

---

## Common Field Standards

These fields appear consistently across skills:

### Status Fields

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `status` | string | "healthy", "connected", "error", "degraded", "critical", "unknown" | Component health status |
| `reachable` | boolean | true/false | Network connectivity status |
| `running` | boolean | true/false | Service running state |
| `success` | boolean | true/false | Operation success (errors only) |

### Error Fields

| Field | Type | Description | When Present |
|-------|------|-------------|--------------|
| `error` | string/null | Error message | Always (null if no error) |
| `hint` | string | Troubleshooting hint | Optional (import errors) |
| `details` | string | Additional error context | Diagnostic issues |

### Count/Metric Fields

| Field | Type | Format | Description |
|-------|------|--------|-------------|
| `total` | integer | Exact count | Total items |
| `count` | integer | Exact count | Item count |
| `count_5m` | integer | Exact count | Count in last 5 minutes |
| `count_1h` | integer | Exact count | Count in last 1 hour |
| `count_24h` | integer | Exact count | Count in last 24 hours |
| `avg_*` | float | Rounded to 1-2 decimals | Average values |
| `*_percent` | float | Rounded to 1-2 decimals | Percentage values |
| `*_ms` | integer/float | Milliseconds | Duration/latency |

### Metadata Fields

| Field | Type | Format | Description |
|-------|------|--------|-------------|
| `timestamp` | string | ISO 8601 | When data was collected |
| `check_duration_ms` | integer | Milliseconds | How long check took |
| `timeframe` | string | "5m", "1h", "24h", "7d" | Time period analyzed |

---

## Status Value Conventions

### Standard Status Values

| Status | Indicator | Meaning | Exit Impact |
|--------|-----------|---------|-------------|
| `"healthy"` | ✓ | Component fully operational | Exit 0 |
| `"ok"` | ✓ | Operation succeeded | Exit 0 |
| `"connected"` | ✓ | Network connection established | Exit 0 |
| `"running"` | ✓ | Service is running | Exit 0 |
| `"success"` | ✓ | Operation completed successfully | Exit 0 |
| `"degraded"` | ⚠ | Partial functionality | Exit 1 |
| `"warning"` | ⚠ | Non-critical issue | Exit 1 |
| `"timeout"` | ⚠ | Operation timed out | Exit 1 |
| `"stopped"` | ⚠ | Service not running | Exit 1 |
| `"critical"` | ✗ | Severe problem | Exit 2 |
| `"error"` | ✗ | Operation failed | Exit 2 |
| `"failed"` | ✗ | Component failed | Exit 2 |
| `"unhealthy"` | ✗ | Health check failing | Exit 2 |
| `"unreachable"` | ✗ | Cannot connect | Exit 2 |
| `"unknown"` | ℹ | Status cannot be determined | Exit 1 |

### Severity Levels (Diagnostic Skills)

| Severity | Symbol | Meaning | Examples |
|----------|--------|---------|----------|
| `"critical"` | ✗ | Must fix immediately | Service down, DB unreachable |
| `"warning"` | ⚠ | Should fix soon | High restart count, pool near capacity |
| `"info"` | ℹ | Informational | Configuration notice |

---

## Timestamp Formats

All timestamps use **ISO 8601 UTC format**:

```
YYYY-MM-DDTHH:MM:SSZ
```

**Example**: `"2025-11-20T14:30:00Z"`

**Implementation**:
```python
from datetime import datetime, timezone

timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

**Fields using timestamps**:
- `timestamp` - When data was collected
- `started_at` - When service/container started
- `created_at` - When record was created (database)

---

## Metric Representations

### Counts

Always integers, never null:

```json
{
  "total_decisions": 150,
  "count_5m": 12,
  "count_1h": 145,
  "count_24h": 2840
}
```

**Null handling**: Convert null to 0:
```python
count = row["count"] or 0
```

### Percentages

Float with 1-2 decimal precision:

```json
{
  "cpu_percent": 45.2,
  "memory_percent": 67.8,
  "success_rate": 0.95,
  "avg_confidence": 0.87
}
```

**Rounding**:
```python
avg_confidence = round(float(row["avg_confidence"] or 0), 2)
cpu_percent = round(float(stats["cpu_percent"]), 1)
```

### Durations

Milliseconds as integer or float:

```json
{
  "routing_time_ms": 7,
  "avg_routing_time_ms": 8.5,
  "total_query_time_ms": 1842,
  "check_duration_ms": 450
}
```

**Rounding**:
```python
avg_time_ms = round(float(row["avg_time_ms"] or 0), 1)
duration_ms = int((time.time() - start_time) * 1000)
```

### Sizes

Strings with human-readable format from PostgreSQL:

```json
{
  "table_sizes": {
    "agent_routing_decisions": "128 kB",
    "agent_manifest_injections": "2048 kB"
  }
}
```

**PostgreSQL function**: `pg_size_pretty(pg_total_relation_size('table'))`

### Resource Stats

CPU and memory with percentage:

```json
{
  "resources": {
    "cpu_percent": 12.5,
    "memory_usage": "256 MB",
    "memory_percent": 15.3
  }
}
```

---

## Output Format Modes

Some skills support multiple output formats via `--format` flag:

### JSON Format (Default)

**Flag**: `--format json` (or omit flag)

**Characteristics**:
- Pretty-printed with 2-space indentation
- Custom JSON encoder for Decimal/datetime types
- Machine-readable, parseable

**Example**:
```json
{
  "status": "healthy",
  "timestamp": "2025-11-20T14:30:00Z",
  "services": {
    "running": 10,
    "total": 10
  }
}
```

### Text Format

**Flag**: `--format text`

**Characteristics**:
- Human-readable console output
- Uses Unicode status indicators (✓, ✗, ⚠)
- Formatted tables and sections
- No parsing required

**Example**:
```
============================================================
SYSTEM HEALTH CHECK
============================================================
Status: HEALTHY
Timestamp: 2025-11-20T14:30:00Z
Duration: 450ms

Services:
  Running: 10/10
  Unhealthy: 0

Infrastructure:
  ✓ Kafka: connected
  ✓ Postgres: connected
  ✓ Qdrant: connected
```

### Summary Format

**Flag**: `--format summary`

**Characteristics**:
- Ultra-brief single-line or few-line output
- Status indicator + key metrics only
- Ideal for monitoring dashboards

**Example**:
```
✓ System Status: HEALTHY
  Services: 10/10 running
  Issues: 0
  Duration: 450ms
```

---

## Skill-Specific Outputs

### check-system-health

**Default Output** (JSON):
```json
{
  "status": "healthy",
  "timestamp": "2025-11-20T14:30:00Z",
  "check_duration_ms": 450,
  "services": {
    "success": true,
    "total": 10,
    "running": 10,
    "stopped": 0,
    "unhealthy": 0,
    "healthy": 8,
    "details": {
      "archon": {...},
      "omninode": {...},
      "app": {...}
    }
  },
  "infrastructure": {
    "kafka": {
      "status": "connected",
      "broker": "192.168.86.200:29092",
      "reachable": true,
      "topics": 15,
      "error": null
    },
    "postgres": {
      "status": "connected",
      "host": "192.168.86.200:5436",
      "database": "omninode_bridge",
      "tables": 34,
      "error": null
    },
    "qdrant": {
      "status": "connected",
      "url": "http://localhost:6333",
      "reachable": true,
      "collections": 4,
      "total_vectors": 15689,
      "error": null
    }
  },
  "recent_activity": {
    "timeframe": "5m",
    "agent_executions": 12,
    "routing_decisions": 15,
    "agent_actions": 45
  },
  "issues": [],
  "recommendations": []
}
```

**Exit Codes**: 0 (healthy), 1 (degraded), 2 (critical), 3 (error)

### diagnose-issues

**Default Output** (JSON):
```json
{
  "system_health": "degraded",
  "issues_found": 2,
  "critical": 0,
  "warnings": 2,
  "issues": [
    {
      "severity": "warning",
      "component": "archon-intelligence",
      "issue": "High restart count",
      "details": "Restarted 8 times",
      "recommendation": "Investigate crashes: docker logs archon-intelligence",
      "auto_fix_available": false
    },
    {
      "severity": "warning",
      "component": "postgres",
      "issue": "Connection pool near capacity",
      "details": "Active connections: 85/100",
      "recommendation": "Consider increasing max_connections or optimizing queries",
      "auto_fix_available": false
    }
  ],
  "recommendations": [
    "Investigate crashes: docker logs archon-intelligence",
    "Consider increasing max_connections or optimizing queries"
  ]
}
```

**Exit Codes**: 0 (no issues), 1 (warnings), 2 (critical), 3 (error)

### check-infrastructure

**Default Output** (JSON):
```json
{
  "kafka": {
    "status": "connected",
    "broker": "192.168.86.200:29092",
    "reachable": true,
    "topics": 15,
    "error": null
  },
  "postgres": {
    "status": "connected",
    "host": "192.168.86.200:5436",
    "database": "omninode_bridge",
    "tables": 34,
    "connections": 25,
    "error": null
  },
  "qdrant": {
    "status": "connected",
    "url": "http://localhost:6333",
    "reachable": true,
    "collections": 4,
    "total_vectors": 15689,
    "collections_detail": {
      "archon_vectors": 7118,
      "code_generation_patterns": 8571,
      "archon-intelligence": 0,
      "quality_vectors": 0
    },
    "error": null
  }
}
```

**Exit Codes**: 0 (success), 1 (error), 3 (execution error)

**Detailed Mode** (`--detailed`):
- Includes topic counts for Kafka
- Includes connection counts for PostgreSQL
- Includes collection details for Qdrant

### check-service-status

**Default Output** (JSON):
```json
{
  "service": "archon-intelligence",
  "status": "running",
  "health": "healthy",
  "running": true,
  "started_at": "2025-11-15T10:00:00Z",
  "restart_count": 0,
  "image": "archon-intelligence:latest"
}
```

**With Stats** (`--include-stats`):
```json
{
  "service": "archon-intelligence",
  "status": "running",
  "health": "healthy",
  "running": true,
  "started_at": "2025-11-15T10:00:00Z",
  "restart_count": 0,
  "image": "archon-intelligence:latest",
  "resources": {
    "cpu_percent": 12.5,
    "memory_usage": "256 MB",
    "memory_percent": 15.3
  }
}
```

**With Logs** (`--include-logs`):
```json
{
  "service": "archon-intelligence",
  "status": "running",
  "health": "healthy",
  "running": true,
  "started_at": "2025-11-15T10:00:00Z",
  "restart_count": 0,
  "image": "archon-intelligence:latest",
  "logs": {
    "total_lines": 500,
    "error_count": 2,
    "recent_errors": [
      "2025-11-20T14:25:00Z - ERROR - Connection timeout to Qdrant",
      "2025-11-20T14:25:05Z - ERROR - Retrying connection..."
    ]
  }
}
```

**Exit Codes**: 0 (success), 1 (service error), 3 (execution error)

### check-database-health

**Default Output** (JSON):
```json
{
  "connection": "healthy",
  "total_tables": 34,
  "connections": {
    "active": 12,
    "idle": 13,
    "total": 25
  },
  "recent_activity": {
    "agent_manifest_injections": {
      "5m": 12,
      "1h": 145,
      "24h": 2840
    },
    "agent_routing_decisions": {
      "5m": 15,
      "1h": 180,
      "24h": 3520
    },
    "agent_actions": {
      "5m": 45,
      "1h": 520,
      "24h": 10240
    }
  }
}
```

**With Sizes** (`--include-sizes`):
```json
{
  "connection": "healthy",
  "total_tables": 34,
  "connections": {
    "active": 12,
    "idle": 13,
    "total": 25
  },
  "recent_activity": {...},
  "table_sizes": {
    "agent_manifest_injections": "2048 kB",
    "agent_routing_decisions": "128 kB",
    "agent_actions": "5120 kB"
  }
}
```

**Error Response**:
```json
{
  "connection": "healthy",
  "total_tables": 34,
  "error": "Invalid table name: 'users'. Must be one of: agent_routing_decisions, ..."
}
```

**Exit Codes**: 0 (success), 1 (validation/connection error), 3 (execution error)

### check-agent-performance

**Default Output** (JSON):
```json
{
  "timeframe": "1h",
  "routing": {
    "total_decisions": 180,
    "avg_routing_time_ms": 8.5,
    "avg_confidence": 0.87,
    "threshold_violations": 2
  },
  "top_agents": [
    {
      "agent": "agent-code",
      "count": 85,
      "avg_confidence": 0.92
    },
    {
      "agent": "agent-architecture",
      "count": 45,
      "avg_confidence": 0.85
    },
    {
      "agent": "agent-debug",
      "count": 30,
      "avg_confidence": 0.78
    }
  ],
  "transformations": {
    "total": 12,
    "success_rate": 0.92,
    "avg_duration_ms": 450.5
  }
}
```

**Exit Codes**: 0 (success), 1 (validation error), 3 (execution error)

### check-kafka-topics

**Default Output** (JSON):
```json
{
  "topics": [
    {
      "name": "agent.routing.requested.v1",
      "partitions": 3,
      "replication": 1
    },
    {
      "name": "agent.routing.completed.v1",
      "partitions": 3,
      "replication": 1
    },
    {
      "name": "dev.archon-intelligence.intelligence.code-analysis-requested.v1",
      "partitions": 1,
      "replication": 1
    }
  ],
  "total": 15
}
```

**Exit Codes**: 0 (success), 1 (connection error), 3 (execution error)

### check-pattern-discovery

**Default Output** (JSON):
```json
{
  "collections": {
    "archon_vectors": {
      "vectors": 7118,
      "status": "active"
    },
    "code_generation_patterns": {
      "vectors": 8571,
      "status": "active"
    },
    "archon-intelligence": {
      "vectors": 0,
      "status": "empty"
    },
    "quality_vectors": {
      "vectors": 0,
      "status": "empty"
    }
  },
  "total_patterns": 15689,
  "recent_discoveries": {
    "5m": 12,
    "1h": 145
  }
}
```

**Exit Codes**: 0 (success), 1 (connection error), 3 (execution error)

### check-recent-activity

**Default Output** (JSON):
```json
{
  "timeframe": "5m",
  "agent_executions": 12,
  "routing_decisions": 15,
  "manifest_injections": 12,
  "agent_actions": 45,
  "transformations": 3,
  "intelligence_queries": 8
}
```

**Exit Codes**: 0 (success), 1 (database error), 3 (execution error)

### generate-status-report

**Default Output** (Markdown):
```markdown
# System Status Report

**Generated**: 2025-11-20T14:30:00Z

## System Health

Status: ✓ HEALTHY

## Services

| Service | Status | Health |
| --- | --- | --- |
| archon-intelligence | running | healthy |
| archon-qdrant | running | healthy |
| archon-bridge | running | healthy |

## Infrastructure

| Component | Status | Details |
| --- | --- | --- |
| Kafka | ✓ connected | 192.168.86.200:29092 (15 topics) |
| PostgreSQL | ✓ connected | 192.168.86.200:5436 (34 tables) |
| Qdrant | ✓ connected | http://localhost:6333 (15689 vectors) |

## Recent Activity (5m)

- Agent Executions: 12
- Routing Decisions: 15
- Agent Actions: 45

## Issues

No issues detected.
```

**Exit Codes**: 0 (success), 1 (error), 3 (execution error)

---

## Error Handling

### Import Errors

**Format**:
```json
{
  "success": false,
  "error": "Import failed: No module named 'kafka_helper'",
  "hint": "Ensure _shared helpers are installed"
}
```

**Exit Code**: 3

### Connection Errors

**Format**:
```json
{
  "kafka": {
    "status": "error",
    "broker": "192.168.86.200:29092",
    "reachable": false,
    "error": "Connection refused"
  }
}
```

**Exit Code**: Varies by skill (typically 1)

### Validation Errors

**Format** (table name validation):
```json
{
  "connection": "healthy",
  "total_tables": 34,
  "error": "Invalid table name: 'users'. Must be one of: agent_routing_decisions, agent_manifest_injections, ..."
}
```

**Exit Code**: 1

**Format** (timeframe validation):
```json
{
  "success": false,
  "error": "Invalid timeframe: 2h. Valid options: 15m, 1h, 24h, 5m, 7d"
}
```

**Exit Code**: 1

### Runtime Errors

**Format**:
```json
{
  "success": false,
  "error": "Unexpected error: division by zero",
  "timestamp": "2025-11-20T14:30:00Z"
}
```

**Exit Code**: 1 or 3 (depending on severity)

---

## Examples

### Example 1: Healthy System Check

**Command**:
```bash
python3 check-system-health/execute.py --format summary
```

**Output**:
```
✓ System Status: HEALTHY
  Services: 10/10 running
  Issues: 0
  Duration: 450ms
```

**Exit Code**: 0

### Example 2: Degraded System with Warnings

**Command**:
```bash
python3 diagnose-issues/execute.py --format json
```

**Output**:
```json
{
  "system_health": "degraded",
  "issues_found": 1,
  "critical": 0,
  "warnings": 1,
  "issues": [
    {
      "severity": "warning",
      "component": "postgres",
      "issue": "Connection pool near capacity",
      "details": "Active connections: 85/100",
      "recommendation": "Consider increasing max_connections or optimizing queries",
      "auto_fix_available": false
    }
  ],
  "recommendations": [
    "Consider increasing max_connections or optimizing queries"
  ]
}
```

**Exit Code**: 1

### Example 3: Critical Infrastructure Failure

**Command**:
```bash
python3 check-infrastructure/execute.py --components kafka
```

**Output**:
```json
{
  "kafka": {
    "status": "error",
    "broker": "192.168.86.200:29092",
    "reachable": false,
    "topics": null,
    "error": "Connection refused"
  }
}
```

**Exit Code**: 0 (skill doesn't use health-based exit codes, but data shows error)

### Example 4: Service Not Found

**Command**:
```bash
python3 check-service-status/execute.py --service nonexistent-service
```

**Output**:
```json
{
  "success": false,
  "error": "Container not found: nonexistent-service"
}
```

**Exit Code**: 1

### Example 5: Agent Performance Metrics

**Command**:
```bash
python3 check-agent-performance/execute.py --timeframe 24h --top-agents 5
```

**Output**:
```json
{
  "timeframe": "24h",
  "routing": {
    "total_decisions": 3520,
    "avg_routing_time_ms": 7.8,
    "avg_confidence": 0.89,
    "threshold_violations": 15
  },
  "top_agents": [
    {
      "agent": "agent-code",
      "count": 1680,
      "avg_confidence": 0.93
    },
    {
      "agent": "agent-architecture",
      "count": 920,
      "avg_confidence": 0.87
    },
    {
      "agent": "agent-debug",
      "count": 540,
      "avg_confidence": 0.82
    },
    {
      "agent": "agent-database",
      "count": 240,
      "avg_confidence": 0.85
    },
    {
      "agent": "agent-frontend",
      "count": 140,
      "avg_confidence": 0.88
    }
  ],
  "transformations": {
    "total": 245,
    "success_rate": 0.94,
    "avg_duration_ms": 520.3
  }
}
```

**Exit Code**: 0

### Example 6: Database Health with Table Sizes

**Command**:
```bash
python3 check-database-health/execute.py --tables agent_routing_decisions,agent_actions --include-sizes
```

**Output**:
```json
{
  "connection": "healthy",
  "total_tables": 34,
  "connections": {
    "active": 8,
    "idle": 17,
    "total": 25
  },
  "recent_activity": {
    "agent_routing_decisions": {
      "5m": 15,
      "1h": 180,
      "24h": 3520
    },
    "agent_actions": {
      "5m": 45,
      "1h": 520,
      "24h": 10240
    }
  },
  "table_sizes": {
    "agent_routing_decisions": "128 kB",
    "agent_actions": "5120 kB"
  }
}
```

**Exit Code**: 0

### Example 7: Import Error

**Command**:
```bash
python3 check-infrastructure/execute.py
```

**Output** (if kafka_helper missing):
```json
{
  "success": false,
  "error": "Import failed: No module named 'kafka_helper'"
}
```

**Exit Code**: 1

### Example 8: SQL Injection Prevention

**Command**:
```bash
python3 check-database-health/execute.py --tables "users; DROP TABLE--"
```

**Output**:
```json
{
  "connection": "healthy",
  "total_tables": 34,
  "error": "Invalid table name: 'users; DROP TABLE--'. Must be one of: agent_routing_decisions, agent_manifest_injections, ..."
}
```

**Exit Code**: 1

---

## Quick Reference Table

| Skill | Default Format | Exit 0 | Exit 1 | Exit 2 | Exit 3 | Supports --format |
|-------|----------------|--------|--------|--------|--------|-------------------|
| check-system-health | JSON | Healthy | Degraded | Critical | Error | Yes (json/text/summary) |
| diagnose-issues | JSON | No issues | Warnings | Critical | Error | Yes (json/text) |
| check-infrastructure | JSON | Success | Error | N/A | Error | No |
| check-service-status | JSON | Success | Error | N/A | Error | No |
| check-database-health | JSON | Success | Error | N/A | Error | No |
| check-agent-performance | JSON | Success | Error | N/A | Error | No |
| check-kafka-topics | JSON | Success | Error | N/A | Error | No |
| check-pattern-discovery | JSON | Success | Error | N/A | Error | No |
| check-recent-activity | JSON | Success | Error | N/A | Error | No |
| generate-status-report | Markdown | Success | Error | N/A | Error | No |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-11-20 | Initial specification |

---

## Related Documentation

- [System Status Skills README](README.md) - Overview and usage guide
- [Individual SKILL.md files](*/SKILL.md) - Skill-specific documentation
- [status_formatter.py](../_shared/status_formatter.py) - Formatting utilities
- [timeframe_helpers.py](lib/helpers/timeframe_helpers.py) - Timeframe validation
