# Database Event Client Usage Guide

**Service**: Database Query Event Client
**Version**: 1.0.0
**Library Location**: `agents/lib/database_event_client.py`
**Correlation ID**: 88b8fcab-4eb9-4a7d-942b-8894c7f840f8

**📊 Implementation Status**: Ready for testing (blocked by registry implementation)
**🔗 Current Progress**: See [EVENT_DRIVEN_DATABASE_IMPLEMENTATION_STATUS.md](EVENT_DRIVEN_DATABASE_IMPLEMENTATION_STATUS.md)

## Overview

The Database Event Client provides a Kafka-based interface for querying the PostgreSQL database through event-driven communication. Instead of direct database connections, agents publish query request events and receive results asynchronously.

**Key Features**:
- Event-driven architecture with Kafka request-response pattern
- Correlation ID tracking for complete traceability
- Timeout handling with configurable limits
- Circuit breaker integration for resilience
- Support for all CRUD operations (SELECT, INSERT, UPDATE, DELETE)
- Connection pooling handled server-side
- Automatic retry with exponential backoff
- Type-safe query results

**Benefits Over Direct Database Access**:
- ✅ **Decoupling**: Agents don't manage database connections
- ✅ **Resilience**: Circuit breaker prevents cascading failures
- ✅ **Traceability**: Complete audit trail via correlation IDs
- ✅ **Scalability**: Connection pooling handled centrally
- ✅ **Security**: Query validation and sanitization server-side
- ✅ **Observability**: All queries logged and monitored

---

## Architecture

### Event Flow

```
AGENT/CLIENT
  ↓ (publish)
Kafka Topic: dev.omninode-bridge.database.query-requested.v1
  ↓ (consume)
DATABASE ADAPTER EFFECT NODE
  ↓ (executes)
PostgreSQL Database
  ↓ (publish)
Kafka Topic: dev.omninode-bridge.database.query-completed.v1
  ↓ (consume)
AGENT/CLIENT receives results
```

### Component Diagram

```
┌─────────────────────┐
│   Agent/Service     │
│                     │
│  DatabaseEventClient│
└──────────┬──────────┘
           │ publish request
           ↓
┌──────────────────────────────────────┐
│         Kafka Event Bus              │
│  - query-requested.v1                │
│  - query-completed.v1                │
│  - query-failed.v1                   │
└──────────┬───────────────────────────┘
           │ consume request
           ↓
┌─────────────────────┐
│ Database Adapter    │
│ Effect Node         │
│                     │
│ - Circuit Breaker   │
│ - Connection Pool   │
│ - Query Validation  │
└──────────┬──────────┘
           │ execute
           ↓
┌─────────────────────┐
│   PostgreSQL        │
│   omninode_bridge   │
└─────────────────────┘
```

---

## Quick Start

### Installation

```python
# The client is part of the agents/lib package
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".claude" / "agents" / "lib"))

from database_event_client import DatabaseEventClient
```

### Basic Usage

```python
import asyncio
from database_event_client import DatabaseEventClient

async def main():
    # Initialize client
    client = DatabaseEventClient(
        bootstrap_servers="192.168.86.200:9092",
        request_timeout_ms=10000,  # 10 seconds
    )

    try:
        # Start client (establishes Kafka connections)
        await client.start()

        # Query example
        rows = await client.query(
            sql="SELECT * FROM agent_routing_decisions WHERE confidence_score > $1 ORDER BY created_at DESC LIMIT $2",
            params=[0.8, 10],
        )

        print(f"Found {len(rows)} high-confidence routing decisions")
        for row in rows:
            print(f"  - {row['selected_agent']}: {row['confidence_score']:.2%}")

    finally:
        # Always cleanup
        await client.stop()

# Run
asyncio.run(main())
```

### Context Manager (Recommended)

```python
from database_event_client import DatabaseEventClientContext

async def main():
    async with DatabaseEventClientContext() as client:
        # Query agent execution history
        rows = await client.query(
            sql="""
                SELECT
                    execution_id,
                    agent_name,
                    status,
                    quality_score,
                    duration_ms
                FROM agent_execution_logs
                WHERE status = $1
                ORDER BY created_at DESC
                LIMIT $2
            """,
            params=["success", 20],
        )

        print(f"Recent successful executions: {len(rows)}")
```

---

## API Reference

### DatabaseEventClient

Main client class for database event operations.

#### Constructor

```python
DatabaseEventClient(
    bootstrap_servers: Optional[str] = None,
    request_timeout_ms: int = 10000,
    consumer_group_id: Optional[str] = None,
    enable_circuit_breaker: bool = True,
    max_retries: int = 3,
)
```

**Parameters**:
- `bootstrap_servers`: Kafka broker address (default: from environment)
  - External: `"192.168.86.200:9092"` or `"localhost:9092"`
  - Docker internal: `"omninode-bridge-redpanda:9092"`
- `request_timeout_ms`: Timeout for query responses (default: 10000ms)
- `consumer_group_id`: Consumer group ID (default: auto-generated)
- `enable_circuit_breaker`: Enable circuit breaker (default: True)
- `max_retries`: Maximum retry attempts on failure (default: 3)

#### Methods

##### start()

```python
async def start() -> None
```

Initialize Kafka producer and consumer. Must be called before making queries.

**Raises**:
- `KafkaError`: If Kafka connection fails
- `TimeoutError`: If consumer partition assignment times out

**Example**:
```python
client = DatabaseEventClient()
await client.start()
```

---

##### stop()

```python
async def stop() -> None
```

Close Kafka connections gracefully. Cancels pending requests.

**Example**:
```python
await client.stop()
```

---

##### query()

```python
async def query(
    sql: str,
    params: Optional[List[Any]] = None,
    timeout_ms: Optional[int] = None,
) -> List[Dict[str, Any]]
```

Execute SELECT query and return rows as list of dictionaries.

**Parameters**:
- `sql`: SQL query string (use `$1`, `$2`, etc. for parameters)
- `params`: Query parameters list (optional)
- `timeout_ms`: Query timeout in milliseconds (default: request_timeout_ms)

**Returns**:
- `List[Dict[str, Any]]`: List of rows as dictionaries

**Raises**:
- `TimeoutError`: If query exceeds timeout
- `KafkaError`: If Kafka communication fails
- `DatabaseError`: If query execution fails

**Example**:
```python
# Simple query
rows = await client.query("SELECT * FROM agent_routing_decisions LIMIT 10")

# Parameterized query
rows = await client.query(
    sql="SELECT * FROM agent_execution_logs WHERE agent_name = $1 AND status = $2",
    params=["agent-researcher", "success"],
)

# Custom timeout
rows = await client.query(
    sql="SELECT * FROM large_table WHERE complex_condition",
    timeout_ms=30000,  # 30 seconds
)
```

---

##### insert()

```python
async def insert(
    table: str,
    data: Dict[str, Any],
    returning: Optional[str] = "id",
    timeout_ms: Optional[int] = None,
) -> Optional[Dict[str, Any]]
```

Insert a single row and optionally return generated values.

**Parameters**:
- `table`: Table name
- `data`: Dictionary of column-value pairs
- `returning`: Column(s) to return (default: "id", use "*" for all columns)
- `timeout_ms`: Query timeout in milliseconds

**Returns**:
- `Optional[Dict[str, Any]]`: Dictionary with returned columns, or None

**Raises**:
- `TimeoutError`: If insert exceeds timeout
- `DatabaseError`: If insert fails (e.g., constraint violation)

**Example**:
```python
# Insert with ID return
result = await client.insert(
    table="agent_execution_logs",
    data={
        "execution_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "correlation_id": "88b8fcab-4eb9-4a7d-942b-8894c7f840f8",
        "agent_name": "agent-researcher",
        "status": "in_progress",
        "started_at": "2025-10-30T10:00:00Z",
    },
    returning="execution_id",
)
print(f"Inserted execution: {result['execution_id']}")

# Insert with all columns returned
result = await client.insert(
    table="agent_routing_decisions",
    data={
        "correlation_id": "88b8fcab-4eb9-4a7d-942b-8894c7f840f8",
        "selected_agent": "agent-researcher",
        "confidence_score": 0.92,
        "routing_strategy": "enhanced_fuzzy_matching",
    },
    returning="*",
)
print(f"Inserted decision: {result}")
```

---

##### update()

```python
async def update(
    table: str,
    data: Dict[str, Any],
    where: Dict[str, Any],
    returning: Optional[str] = None,
    timeout_ms: Optional[int] = None,
) -> Optional[Dict[str, Any]]
```

Update rows matching WHERE clause.

**Parameters**:
- `table`: Table name
- `data`: Dictionary of columns to update
- `where`: Dictionary of WHERE clause conditions (AND combined)
- `returning`: Column(s) to return (optional)
- `timeout_ms`: Query timeout in milliseconds

**Returns**:
- `Optional[Dict[str, Any]]`: First row with returned columns, or None

**Raises**:
- `TimeoutError`: If update exceeds timeout
- `DatabaseError`: If update fails

**Example**:
```python
# Update execution status
result = await client.update(
    table="agent_execution_logs",
    data={
        "status": "success",
        "completed_at": "2025-10-30T10:15:00Z",
        "quality_score": 0.95,
        "duration_ms": 900000,
    },
    where={
        "execution_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    },
    returning="execution_id",
)
print(f"Updated execution: {result['execution_id']}")

# Update with multiple conditions
await client.update(
    table="agent_manifest_injections",
    data={"processed": True},
    where={
        "agent_name": "agent-researcher",
        "patterns_count": 0,
    },
)
```

---

##### delete()

```python
async def delete(
    table: str,
    where: Dict[str, Any],
    timeout_ms: Optional[int] = None,
) -> int
```

Delete rows matching WHERE clause.

**Parameters**:
- `table`: Table name
- `where`: Dictionary of WHERE clause conditions (AND combined)
- `timeout_ms`: Query timeout in milliseconds

**Returns**:
- `int`: Number of rows deleted

**Raises**:
- `TimeoutError`: If delete exceeds timeout
- `DatabaseError`: If delete fails

**Example**:
```python
# Delete specific execution
deleted = await client.delete(
    table="agent_execution_logs",
    where={"execution_id": "old-execution-id"},
)
print(f"Deleted {deleted} execution(s)")

# Delete with multiple conditions
deleted = await client.delete(
    table="agent_routing_decisions",
    where={
        "confidence_score": {"$lt": 0.5},  # Less than 0.5
        "created_at": {"$lt": "2025-01-01"},  # Before 2025
    },
)
print(f"Deleted {deleted} low-confidence decisions")
```

---

##### execute()

```python
async def execute(
    sql: str,
    params: Optional[List[Any]] = None,
    timeout_ms: Optional[int] = None,
) -> int
```

Execute DML statement (INSERT, UPDATE, DELETE) without returning rows.

**Parameters**:
- `sql`: SQL statement string
- `params`: Query parameters list (optional)
- `timeout_ms`: Query timeout in milliseconds

**Returns**:
- `int`: Number of rows affected

**Raises**:
- `TimeoutError`: If execution exceeds timeout
- `DatabaseError`: If execution fails

**Example**:
```python
# Bulk update
affected = await client.execute(
    sql="UPDATE agent_execution_logs SET processed = TRUE WHERE status = $1",
    params=["success"],
)
print(f"Marked {affected} executions as processed")

# Cleanup old data
affected = await client.execute(
    sql="DELETE FROM agent_routing_decisions WHERE created_at < NOW() - INTERVAL '90 days'",
)
print(f"Deleted {affected} old routing decisions")
```

---

##### health_check()

```python
async def health_check() -> bool
```

Check Kafka connection health.

**Returns**:
- `bool`: True if healthy, False otherwise

**Example**:
```python
if await client.health_check():
    rows = await client.query("SELECT * FROM agent_execution_logs")
else:
    # Fallback to in-memory data or retry
    print("Database client unhealthy, using fallback")
```

---

## Event Schemas

### Request Events

#### Query Request

**Topic**: `dev.omninode-bridge.database.query-requested.v1`

```json
{
  "event_id": "uuid",
  "event_type": "DATABASE_QUERY_REQUESTED",
  "correlation_id": "uuid",
  "timestamp": "2025-10-30T10:00:00.000Z",
  "service": "omniclaude",
  "payload": {
    "operation_type": "SELECT",
    "sql": "SELECT * FROM agent_execution_logs WHERE agent_name = $1",
    "params": ["agent-researcher"],
    "options": {
      "timeout_ms": 10000,
      "max_rows": 1000
    }
  }
}
```

**Operation Types**:
- `SELECT`: Query rows
- `INSERT`: Insert single row
- `UPDATE`: Update rows
- `DELETE`: Delete rows
- `EXECUTE`: Execute DML without returning rows

---

#### Insert Request

**Topic**: `dev.omninode-bridge.database.query-requested.v1`

```json
{
  "event_id": "uuid",
  "event_type": "DATABASE_QUERY_REQUESTED",
  "correlation_id": "uuid",
  "timestamp": "2025-10-30T10:00:00.000Z",
  "service": "omniclaude",
  "payload": {
    "operation_type": "INSERT",
    "table": "agent_execution_logs",
    "data": {
      "execution_id": "uuid",
      "agent_name": "agent-researcher",
      "status": "in_progress"
    },
    "returning": "execution_id",
    "options": {
      "timeout_ms": 5000
    }
  }
}
```

---

#### Update Request

**Topic**: `dev.omninode-bridge.database.query-requested.v1`

```json
{
  "event_id": "uuid",
  "event_type": "DATABASE_QUERY_REQUESTED",
  "correlation_id": "uuid",
  "timestamp": "2025-10-30T10:00:00.000Z",
  "service": "omniclaude",
  "payload": {
    "operation_type": "UPDATE",
    "table": "agent_execution_logs",
    "data": {
      "status": "success",
      "quality_score": 0.95
    },
    "where": {
      "execution_id": "uuid"
    },
    "returning": "*",
    "options": {
      "timeout_ms": 5000
    }
  }
}
```

---

### Response Events

#### Query Completed

**Topic**: `dev.omninode-bridge.database.query-completed.v1`

```json
{
  "event_id": "uuid",
  "event_type": "DATABASE_QUERY_COMPLETED",
  "correlation_id": "uuid",
  "timestamp": "2025-10-30T10:00:00.500Z",
  "service": "database-adapter-effect",
  "payload": {
    "operation_type": "SELECT",
    "rows": [
      {
        "execution_id": "uuid",
        "agent_name": "agent-researcher",
        "status": "success",
        "quality_score": 0.95
      }
    ],
    "row_count": 1,
    "execution_time_ms": 15,
    "metadata": {
      "cached": false,
      "circuit_breaker_state": "CLOSED"
    }
  }
}
```

---

#### Query Failed

**Topic**: `dev.omninode-bridge.database.query-failed.v1`

```json
{
  "event_id": "uuid",
  "event_type": "DATABASE_QUERY_FAILED",
  "correlation_id": "uuid",
  "timestamp": "2025-10-30T10:00:00.500Z",
  "service": "database-adapter-effect",
  "payload": {
    "operation_type": "SELECT",
    "error_code": "DATABASE_OPERATION_FAILED",
    "error_message": "syntax error at or near \"SELET\"",
    "error_type": "PostgresError",
    "metadata": {
      "sql": "SELET * FROM agent_execution_logs",
      "circuit_breaker_state": "CLOSED"
    }
  }
}
```

**Error Codes**:
- `DATABASE_CONNECTION_FAILED`: PostgreSQL connection failed
- `DATABASE_OPERATION_FAILED`: Query execution failed
- `VALIDATION_ERROR`: Input validation failed
- `TIMEOUT_ERROR`: Query exceeded timeout
- `CIRCUIT_BREAKER_OPEN`: Circuit breaker is open

---

## Common Usage Patterns

### Pattern 1: Agent Execution Logging

```python
from database_event_client import DatabaseEventClientContext
from datetime import datetime
from uuid import uuid4

async def log_agent_execution():
    async with DatabaseEventClientContext() as db:
        # Start execution
        execution_id = str(uuid4())
        correlation_id = str(uuid4())

        await db.insert(
            table="agent_execution_logs",
            data={
                "execution_id": execution_id,
                "correlation_id": correlation_id,
                "agent_name": "agent-researcher",
                "status": "in_progress",
                "started_at": datetime.utcnow().isoformat(),
            },
        )

        # ... agent executes work ...

        # Complete execution
        await db.update(
            table="agent_execution_logs",
            data={
                "status": "success",
                "completed_at": datetime.utcnow().isoformat(),
                "quality_score": 0.92,
                "duration_ms": 15000,
            },
            where={"execution_id": execution_id},
        )
```

---

### Pattern 2: Routing Decision Tracking

```python
async def track_routing_decision(user_request: str, selected_agent: str, confidence: float):
    async with DatabaseEventClientContext() as db:
        result = await db.insert(
            table="agent_routing_decisions",
            data={
                "correlation_id": str(uuid4()),
                "user_request": user_request,
                "selected_agent": selected_agent,
                "confidence_score": confidence,
                "routing_strategy": "enhanced_fuzzy_matching",
                "alternatives": json.dumps([
                    {"agent": "agent-api-architect", "confidence": 0.85},
                    {"agent": "agent-database-architect", "confidence": 0.78},
                ]),
            },
            returning="id",
        )

        print(f"Tracked routing decision: {result['id']}")
```

---

### Pattern 3: Historical Analysis

```python
async def analyze_agent_performance():
    async with DatabaseEventClientContext() as db:
        # Query successful executions
        rows = await db.query(
            sql="""
                SELECT
                    agent_name,
                    COUNT(*) as execution_count,
                    AVG(quality_score) as avg_quality,
                    AVG(duration_ms) as avg_duration_ms
                FROM agent_execution_logs
                WHERE status = $1
                  AND created_at > NOW() - INTERVAL '7 days'
                GROUP BY agent_name
                ORDER BY avg_quality DESC
            """,
            params=["success"],
        )

        print("Agent Performance (Last 7 Days)")
        print("=" * 60)
        for row in rows:
            print(f"{row['agent_name']:30s} | "
                  f"Executions: {row['execution_count']:4d} | "
                  f"Quality: {row['avg_quality']:.2%} | "
                  f"Avg Time: {row['avg_duration_ms']/1000:.1f}s")
```

---

### Pattern 4: Manifest Injection Traceability

```python
async def query_manifest_history(agent_name: str):
    async with DatabaseEventClientContext() as db:
        # Query manifest injections
        rows = await db.query(
            sql="""
                SELECT
                    ami.correlation_id,
                    ami.agent_name,
                    ami.patterns_count,
                    ami.total_query_time_ms,
                    ami.created_at,
                    ael.status,
                    ael.quality_score
                FROM agent_manifest_injections ami
                LEFT JOIN agent_execution_logs ael
                    ON ami.correlation_id = ael.correlation_id
                WHERE ami.agent_name = $1
                ORDER BY ami.created_at DESC
                LIMIT $2
            """,
            params=[agent_name, 10],
        )

        print(f"Manifest Injection History: {agent_name}")
        print("=" * 80)
        for row in rows:
            print(f"Correlation: {row['correlation_id']}")
            print(f"  Patterns: {row['patterns_count']}, "
                  f"Query Time: {row['total_query_time_ms']}ms, "
                  f"Status: {row['status']}, "
                  f"Quality: {row['quality_score']:.2%}")
```

---

## Error Handling

### Timeout Handling

```python
from database_event_client import DatabaseEventClientContext

async def query_with_timeout():
    async with DatabaseEventClientContext() as db:
        try:
            rows = await db.query(
                sql="SELECT * FROM large_table WHERE complex_condition",
                timeout_ms=5000,  # 5 second timeout
            )
            return rows
        except TimeoutError:
            # Fallback strategy
            print("Query timeout, using cached data")
            return load_cached_data()
```

---

### Circuit Breaker

```python
async def resilient_query():
    async with DatabaseEventClientContext(enable_circuit_breaker=True) as db:
        try:
            rows = await db.query("SELECT * FROM agent_execution_logs")
            return rows
        except Exception as e:
            if "CIRCUIT_BREAKER_OPEN" in str(e):
                print("Circuit breaker open, database temporarily unavailable")
                # Wait and retry, or use fallback
                await asyncio.sleep(60)  # Wait for circuit to close
                return await resilient_query()
            else:
                raise
```

---

### Retry with Exponential Backoff

```python
async def retry_query(max_attempts: int = 3):
    async with DatabaseEventClientContext(max_retries=max_attempts) as db:
        # Client automatically retries on transient failures
        # with exponential backoff: 1s, 2s, 4s
        rows = await db.query("SELECT * FROM agent_execution_logs")
        return rows
```

---

## Performance Considerations

### Query Optimization

**Use parameterized queries** (prevents SQL injection and enables caching):
```python
# ✅ GOOD - Parameterized
rows = await db.query(
    sql="SELECT * FROM agent_execution_logs WHERE agent_name = $1",
    params=["agent-researcher"],
)

# ❌ BAD - String interpolation
agent_name = "agent-researcher"
rows = await db.query(
    sql=f"SELECT * FROM agent_execution_logs WHERE agent_name = '{agent_name}'",
)
```

---

### Batch Operations

**Batch inserts** (use explicit SQL for bulk operations):
```python
# For multiple inserts, use batch SQL
await db.execute(
    sql="""
        INSERT INTO agent_execution_logs (execution_id, agent_name, status)
        VALUES
            ($1, $2, $3),
            ($4, $5, $6),
            ($7, $8, $9)
    """,
    params=[
        "id1", "agent-1", "success",
        "id2", "agent-2", "success",
        "id3", "agent-3", "success",
    ],
)
```

---

### Connection Pooling

The database adapter handles connection pooling server-side:
- **Pool size**: 10-50 connections
- **Pool timeout**: 30 seconds
- **Connection lifetime**: 1 hour
- **Health check interval**: 30 seconds

**No client-side connection management required**.

---

### Performance Targets

| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| Query latency (p95) | <100ms | >200ms | >500ms |
| Insert latency (p95) | <50ms | >100ms | >300ms |
| Update latency (p95) | <75ms | >150ms | >400ms |
| Event round-trip | <150ms | >300ms | >1000ms |
| Throughput | >500 queries/sec | <200 queries/sec | <50 queries/sec |

---

## Migration Guide from Direct asyncpg

### Before (Direct asyncpg)

```python
import asyncpg

async def query_executions():
    # Manage connection manually
    conn = await asyncpg.connect(
        host="192.168.86.200",
        port=5436,
        database="omninode_bridge",
        user="postgres",
        password=os.getenv("POSTGRES_PASSWORD"),
    )

    try:
        rows = await conn.fetch(
            "SELECT * FROM agent_execution_logs WHERE agent_name = $1",
            "agent-researcher",
        )

        # Convert to dictionaries
        result = [dict(row) for row in rows]
        return result
    finally:
        await conn.close()
```

**Issues**:
- ❌ Connection management overhead
- ❌ No connection pooling
- ❌ No circuit breaker protection
- ❌ Credentials in code
- ❌ No centralized logging
- ❌ No event traceability

---

### After (DatabaseEventClient)

```python
from database_event_client import DatabaseEventClientContext

async def query_executions():
    async with DatabaseEventClientContext() as db:
        rows = await db.query(
            sql="SELECT * FROM agent_execution_logs WHERE agent_name = $1",
            params=["agent-researcher"],
        )
        return rows
```

**Benefits**:
- ✅ Automatic connection management
- ✅ Server-side connection pooling
- ✅ Circuit breaker protection
- ✅ No credentials in code
- ✅ Centralized logging and monitoring
- ✅ Complete event traceability
- ✅ Kafka event bus integration

---

### Migration Checklist

- [ ] Replace `asyncpg.connect()` with `DatabaseEventClient()`
- [ ] Replace `conn.fetch()` with `client.query()`
- [ ] Replace `conn.execute()` with `client.execute()`
- [ ] Replace `conn.fetchrow()` with `client.query()` + `[0]`
- [ ] Remove connection management code
- [ ] Remove credentials from code (use environment variables)
- [ ] Add correlation ID tracking
- [ ] Update error handling (TimeoutError, DatabaseError)
- [ ] Test with circuit breaker scenarios
- [ ] Update monitoring to track Kafka events

---

## Troubleshooting

### Issue: Client cannot connect to Kafka

**Symptoms**:
- `KafkaError: Failed to start Kafka client`
- `bootstrap_servers must be provided`

**Solution**:
```bash
# Check environment variable
echo $KAFKA_BOOTSTRAP_SERVERS

# Set if missing
export KAFKA_BOOTSTRAP_SERVERS="192.168.86.200:9092"

# Or pass explicitly
client = DatabaseEventClient(bootstrap_servers="192.168.86.200:9092")
```

---

### Issue: Query timeout

**Symptoms**:
- `TimeoutError: Request timeout after 10000ms`

**Solution**:
```python
# Increase timeout
rows = await client.query(
    sql="SELECT * FROM large_table",
    timeout_ms=30000,  # 30 seconds
)

# Or optimize query with indexes, limits
rows = await client.query(
    sql="SELECT * FROM large_table WHERE indexed_column = $1 LIMIT 100",
    params=["value"],
)
```

---

### Issue: Circuit breaker open

**Symptoms**:
- `DatabaseError: CIRCUIT_BREAKER_OPEN: Circuit breaker open`

**Solution**:
```python
# Wait for circuit to close (60 seconds default)
await asyncio.sleep(60)

# Or check health first
if await client.health_check():
    rows = await client.query(...)
else:
    # Use fallback data source
    rows = load_from_cache()
```

---

### Issue: No response received

**Symptoms**:
- Request hangs indefinitely
- No error or timeout

**Diagnosis**:
```bash
# Check database adapter is running
docker ps | grep database-adapter-effect

# Check Kafka topics exist
docker exec -it omninode-bridge-redpanda rpk topic list | grep database

# Check consumer is subscribed
docker logs database-adapter-effect | grep "Subscribed to topics"
```

**Solution**:
```bash
# Restart database adapter
docker restart database-adapter-effect

# Verify topics exist (create if missing)
docker exec -it omninode-bridge-redpanda rpk topic create \
    dev.omninode-bridge.database.query-requested.v1 \
    dev.omninode-bridge.database.query-completed.v1 \
    dev.omninode-bridge.database.query-failed.v1
```

---

## References

- **Database Adapter Documentation**: [docs/database-adapter-kafka-topics.md](database-adapter-kafka-topics.md)
- **Intelligence Event Client** (similar pattern): `agents/lib/intelligence_event_client.py`
- **Kafka Configuration**: `~/.claude/lib/kafka_config.py`
- **Environment Variables**: `.env` file in project root

---

**Last Updated**: 2025-10-30
**Correlation ID**: 88b8fcab-4eb9-4a7d-942b-8894c7f840f8
**Author**: OmniClaude Documentation Team
