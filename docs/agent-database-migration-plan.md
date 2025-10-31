# Agent Database Migration Plan: Direct asyncpg → DatabaseEventClient

**Document Version**: 1.0.0
**Created**: 2025-10-30
**Correlation ID**: CDC031BA-FDAC-4270-AA38-461CFBA06BB2
**Status**: Planning Phase

**📊 Implementation Status**: See [EVENT_DRIVEN_DATABASE_IMPLEMENTATION_STATUS.md](EVENT_DRIVEN_DATABASE_IMPLEMENTATION_STATUS.md) for current progress

---

## Executive Summary

This document outlines the migration strategy for transitioning 9 agent files from direct asyncpg/psycopg2 database access to the new event-driven DatabaseEventClient architecture. The migration will improve decoupling, resilience, traceability, and scalability while maintaining backward compatibility.

**Key Metrics:**
- **Files to migrate**: 9 (3 simple, 3 medium, 3 complex)
- **Estimated effort**: 24-32 hours
- **Risk level**: Medium (breaking changes possible)
- **Timeline**: 2-3 weeks with phased rollout

---

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Migration Strategy](#migration-strategy)
3. [File-by-File Migration Plan](#file-by-file-migration-plan)
4. [Code Examples (Before/After)](#code-examples-beforeafter)
5. [Dependencies & Execution Order](#dependencies--execution-order)
6. [Testing Strategy](#testing-strategy)
7. [Rollback Plan](#rollback-plan)
8. [Timeline & Effort Estimates](#timeline--effort-estimates)
9. [Risk Assessment](#risk-assessment)
10. [Success Criteria](#success-criteria)

---

## Current State Analysis

### Files Using Direct Database Access

| File | Library | Complexity | Query Types | LOC | Priority |
|------|---------|------------|-------------|-----|----------|
| `agents/lib/db.py` | asyncpg | ⭐ Low | SELECT, DML | 96 | High |
| `agents/lib/kafka_agent_action_consumer.py` | asyncpg | ⭐ Low | INSERT (batch) | 288 | High |
| `agents/lib/manifest_injector.py` | psycopg2 | ⭐⭐ Medium | INSERT (upsert), UPDATE | 2496 | High |
| `agents/parallel_execution/observability_report.py` | psycopg2 | ⭐⭐ Medium | SELECT (complex) | 368 | Medium |
| `agents/migrations/validate_002_migration.py` | psycopg2 | ⭐⭐ Medium | SELECT (schema), SELECT (data) | 390 | Low |
| `agents/lib/persistence.py` | asyncpg | ⭐⭐⭐ High | Full CRUD, transactions, functions | 552 | High |
| `agents/parallel_execution/database_integration.py` | asyncpg | ⭐⭐⭐ High | Batch INSERT, SELECT, circuit breaker | 949 | Medium |
| `agents/parallel_execution/db_connection_pool.py` | asyncpg | ⭐⭐⭐ High | Pool management, migrations | 336 | Medium |

**Total Lines of Code**: ~5,475 lines across 9 files

### Query Pattern Distribution

```
INSERT Operations: 5 files (batch: 3, single: 2, upsert: 2)
SELECT Operations: 7 files (simple: 2, complex: 5)
UPDATE Operations: 3 files
DELETE Operations: 2 files
Schema Queries: 2 files
Stored Functions: 1 file
Transactions: 4 files
Connection Pooling: 3 files
```

### Current Issues Addressed by Migration

1. **Tight Coupling**: Direct database connections in agent code
2. **No Traceability**: Missing correlation ID tracking for queries
3. **No Circuit Breaker**: Cascading failures possible
4. **Credential Management**: Passwords in code/env files
5. **No Centralized Logging**: Each file implements own logging
6. **Connection Pool Duplication**: Multiple pool implementations

---

## Migration Strategy

### Approach: Phased Migration

**Phase 1: Simple Files (Week 1)**
- Migrate `agents/lib/db.py`
- Migrate `agents/lib/kafka_agent_action_consumer.py`
- Validate basic CRUD operations
- **Effort**: 4-6 hours

**Phase 2: Medium Complexity Files (Week 2)**
- Migrate `agents/lib/manifest_injector.py`
- Migrate `agents/parallel_execution/observability_report.py`
- Migrate `agents/migrations/validate_002_migration.py`
- **Effort**: 12-16 hours

**Phase 3: High Complexity Files (Week 3)**
- Migrate `agents/lib/persistence.py`
- Migrate `agents/parallel_execution/database_integration.py`
- Migrate `agents/parallel_execution/db_connection_pool.py`
- **Effort**: 12-16 hours

### Migration Principles

1. **Backward Compatibility**: Maintain existing APIs where possible
2. **Feature Parity**: All current operations must be supported
3. **Performance**: Target <100ms p95 query latency (same as direct)
4. **Traceability**: Add correlation ID tracking to all operations
5. **Graceful Degradation**: Fallback to minimal functionality on timeout

---

## File-by-File Migration Plan

### 1. agents/lib/db.py

**Complexity**: ⭐ Low
**Priority**: High
**Estimated Effort**: 1-2 hours

**Current Implementation:**
- Simple pool-based wrapper around asyncpg
- 2 functions: `execute_query()`, `execute_command()`
- Used for basic agent framework operations

**Migration Tasks:**
1. Replace `get_pg_pool()` with `DatabaseEventClient()`
2. Replace `execute_query()` with `client.query()`
3. Replace `execute_command()` with `client.execute()`
4. Add correlation ID parameter
5. Update error handling

**Breaking Changes:**
- None (API compatible)

**Testing:**
- Unit tests for query/execute operations
- Integration test with real database

**Dependencies:**
- None (standalone utility)

---

### 2. agents/lib/kafka_agent_action_consumer.py

**Complexity**: ⭐ Low
**Priority**: High
**Estimated Effort**: 2-3 hours

**Current Implementation:**
- Kafka consumer with asyncpg batch insert
- Uses `ON CONFLICT` for idempotency
- Manual transaction management

**Migration Tasks:**
1. Replace `asyncpg.create_pool()` with `DatabaseEventClient()`
2. Replace `conn.fetch()` with `client.insert()`
3. Update batch processing to use event client
4. Maintain idempotency with upsert operations
5. Update error handling

**Breaking Changes:**
- None (internal implementation only)

**Testing:**
- Unit tests for batch insert
- Integration test with Kafka + database
- Idempotency test (duplicate detection)

**Dependencies:**
- None (consumer service)

---

### 3. agents/lib/manifest_injector.py

**Complexity**: ⭐⭐ Medium
**Priority**: High
**Estimated Effort**: 4-5 hours

**Current Implementation:**
- Uses psycopg2 (sync) for storage
- `ManifestInjectionStorage` class with 2 methods:
  - `store_manifest_injection()` - Complex INSERT with many fields
  - `mark_agent_completed()` - UPDATE with lifecycle tracking

**Migration Tasks:**
1. Convert `ManifestInjectionStorage` to use `DatabaseEventClient`
2. Replace psycopg2 context managers with async client
3. Replace `INSERT` with `client.insert()`
4. Replace `UPDATE` with `client.update()`
5. Handle JSONB fields (psycopg2.extras.Json → dict)
6. Update error handling

**Breaking Changes:**
- Method signatures change from sync to async
- `store_manifest_injection()` → `async def store_manifest_injection()`
- `mark_agent_completed()` → `async def mark_agent_completed()`

**Testing:**
- Unit tests for manifest storage
- Unit tests for agent completion tracking
- Integration test for full lifecycle

**Dependencies:**
- Used by `ManifestInjector` class (same file)
- Must maintain async compatibility with context manager

---

### 4. agents/parallel_execution/observability_report.py

**Complexity**: ⭐⭐ Medium
**Priority**: Medium
**Estimated Effort**: 3-4 hours

**Current Implementation:**
- Uses psycopg2 (sync) for reporting
- Read-only queries (no writes)
- Complex aggregations and joins

**Migration Tasks:**
1. Replace `psycopg2.connect()` with `DatabaseEventClient()`
2. Replace all `cur.execute()` with `client.query()`
3. Replace `RealDictCursor` with dict conversion
4. Update `generate_report()` to be async
5. Handle datetime conversions

**Breaking Changes:**
- `ObservabilityReporter` methods become async
- `generate_report()` → `async def generate_report()`

**Testing:**
- Unit tests for each query method
- Integration test for full report generation
- Verify aggregation accuracy

**Dependencies:**
- None (standalone reporting tool)

---

### 5. agents/migrations/validate_002_migration.py

**Complexity**: ⭐⭐ Medium
**Priority**: Low
**Estimated Effort**: 2-3 hours

**Current Implementation:**
- Uses psycopg2 (sync) for validation
- Schema queries and data validation
- Read-only operations

**Migration Tasks:**
1. Replace `psycopg2.connect()` with `DatabaseEventClient()`
2. Replace schema queries with `client.query()`
3. Replace data validation queries with `client.query()`
4. Update `MigrationValidator` to be async
5. Handle schema introspection queries

**Breaking Changes:**
- `MigrationValidator` methods become async
- `check_pre_migration_state()` → `async def check_pre_migration_state()`
- `check_post_migration_state()` → `async def check_post_migration_state()`

**Testing:**
- Unit tests for validation methods
- Integration test with migration schema
- Verify schema query accuracy

**Dependencies:**
- None (standalone migration tool)

---

### 6. agents/lib/persistence.py

**Complexity**: ⭐⭐⭐ High
**Priority**: High
**Estimated Effort**: 6-8 hours

**Current Implementation:**
- Uses asyncpg (async)
- `CodegenPersistence` class with many operations:
  - Session management (upsert, complete)
  - Artifact management (insert)
  - Mixin compatibility (update, get, summary)
  - Pattern feedback (record, analyze)
  - Performance metrics (insert, summary)
  - Template cache (upsert, update metrics, efficiency)
  - Event processing (insert, health)
- Complex CRUD operations with stored functions
- Transaction management
- JSONB handling

**Migration Tasks:**
1. Replace `asyncpg.create_pool()` with `DatabaseEventClient()`
2. Replace `conn.execute()` with `client.execute()` or `client.insert()`
3. Replace `conn.fetch()` with `client.query()`
4. Replace `conn.fetchrow()` with `client.query()` + `[0]`
5. Replace `conn.fetchval()` with `client.query()` + `[0][column]`
6. Handle stored function calls (may need custom support)
7. Update transaction management
8. Handle JSONB serialization
9. Update error handling

**Breaking Changes:**
- None (methods already async)
- Internal implementation changes only

**Testing:**
- Unit tests for each operation type
- Integration tests for full workflows
- Performance tests (batch operations)
- Transaction rollback tests

**Dependencies:**
- Used by many agent workflows
- Critical for code generation pipeline

---

### 7. agents/parallel_execution/database_integration.py

**Complexity**: ⭐⭐⭐ High
**Priority**: Medium
**Estimated Effort**: 5-6 hours

**Current Implementation:**
- Uses asyncpg (async)
- `DatabaseIntegrationLayer` class with:
  - Connection pooling with health monitoring
  - Batch write buffers (4 types)
  - Circuit breaker for failure handling
  - Query API for observability data
  - Data retention and archival
  - Background tasks (flush, health check, retention)
- Very complex with multiple background tasks

**Migration Tasks:**
1. **Option A (Recommended)**: Replace entire layer with DatabaseEventClient
   - Remove custom pooling (use client's Kafka pool)
   - Remove circuit breaker (use client's built-in)
   - Simplify batch writes (use client's batch operations)
   - Remove background tasks (use client's async processing)
2. **Option B (Conservative)**: Wrap DatabaseEventClient
   - Keep existing API
   - Replace pool with client internally
   - Maintain circuit breaker wrapper

**Breaking Changes:**
- Major API changes if using Option A
- `DatabaseIntegrationLayer` → `DatabaseEventClient` usage
- Background tasks removed (handled by omninode-bridge)

**Testing:**
- Unit tests for batch operations
- Integration tests for observability workflow
- Circuit breaker tests
- Health monitoring tests
- Performance tests (1000+ events/sec)

**Dependencies:**
- Used by parallel execution framework
- Critical for observability system

---

### 8. agents/parallel_execution/db_connection_pool.py

**Complexity**: ⭐⭐⭐ High
**Priority**: Medium
**Estimated Effort**: 4-5 hours

**Current Implementation:**
- Uses asyncpg (async)
- `NodeDatabasePoolEffect` - ONEX Effect node pattern
- Connection pool management
- Health checks
- Migration execution
- Global pool instance

**Migration Tasks:**
1. **Option A (Recommended)**: Replace with DatabaseEventClient wrapper
   - Remove pool management (use client)
   - Keep ONEX Effect pattern
   - Simplify health checks
   - Remove migration execution (use separate tool)
2. **Option B (Conservative)**: Keep as wrapper around DatabaseEventClient
   - Maintain ONEX Effect interface
   - Replace pool with client internally

**Breaking Changes:**
- None if using Option B (wrapper approach)
- Major changes if using Option A (direct client)

**Testing:**
- Unit tests for ONEX Effect pattern
- Integration tests for pool lifecycle
- Health check tests
- Migration execution tests (if kept)

**Dependencies:**
- Used by `database_integration.py`
- Part of parallel execution framework

---

## Code Examples (Before/After)

### Example 1: agents/lib/db.py

**Before (Direct asyncpg):**
```python
import asyncpg

_pool: Optional[asyncpg.Pool] = None

async def get_pg_pool() -> Optional[asyncpg.Pool]:
    global _pool
    if _pool is not None:
        return _pool

    dsn = os.getenv("PG_DSN") or _build_dsn_from_env()
    if not dsn:
        return None

    _pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
    return _pool

async def execute_query(query: str, *args) -> Any:
    pool = await get_pg_pool()
    if pool is None:
        return None

    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)
```

**After (DatabaseEventClient):**
```python
from database_event_client import DatabaseEventClient, DatabaseEventClientContext

_client: Optional[DatabaseEventClient] = None

async def get_database_client() -> Optional[DatabaseEventClient]:
    global _client
    if _client is not None:
        return _client

    _client = DatabaseEventClient()
    await _client.start()
    return _client

async def execute_query(query: str, *args, correlation_id: Optional[str] = None) -> Any:
    client = await get_database_client()
    if client is None:
        return None

    # Convert asyncpg-style positional params to list
    params = list(args) if args else None

    return await client.query(
        query=query,
        params=params,
        timeout_ms=10000,
    )
```

**Key Changes:**
- ✅ Replaced pool with client
- ✅ Added correlation ID support
- ✅ Event-driven query execution
- ✅ Maintained same API signature
- ✅ No breaking changes

---

### Example 2: agents/lib/manifest_injector.py

**Before (psycopg2 sync):**
```python
import psycopg2
import psycopg2.extras

def store_manifest_injection(
    self,
    correlation_id: UUID,
    agent_name: str,
    manifest_data: Dict[str, Any],
    formatted_text: str,
    query_times: Dict[str, int],
    sections_included: List[str],
    **kwargs,
) -> bool:
    try:
        with (
            psycopg2.connect(
                host=self.db_host,
                port=self.db_port,
                dbname=self.db_name,
                user=self.db_user,
                password=self.db_password,
            ) as conn,
            conn.cursor() as cursor,
        ):
            cursor.execute(
                """
                INSERT INTO agent_manifest_injections (
                    correlation_id,
                    agent_name,
                    manifest_version,
                    ...
                ) VALUES (%s, %s, %s, ...)
                """,
                (
                    str(correlation_id),
                    agent_name,
                    manifest_version,
                    ...
                ),
            )
            conn.commit()

        return True
    except Exception as e:
        logger.error(f"Failed to store manifest: {e}")
        return False
```

**After (DatabaseEventClient async):**
```python
from database_event_client import DatabaseEventClient

async def store_manifest_injection(
    self,
    correlation_id: UUID,
    agent_name: str,
    manifest_data: Dict[str, Any],
    formatted_text: str,
    query_times: Dict[str, int],
    sections_included: List[str],
    **kwargs,
) -> bool:
    try:
        # Create client (reuse instance in production)
        async with DatabaseEventClientContext() as client:
            # Prepare data dictionary
            data = {
                "correlation_id": str(correlation_id),
                "agent_name": agent_name,
                "manifest_version": manifest_version,
                "generation_source": generation_source,
                "is_fallback": is_fallback,
                "sections_included": sections_included,
                "patterns_count": patterns_count,
                # ... more fields
                "full_manifest_snapshot": manifest_data,  # JSONB as dict
                "formatted_manifest_text": formatted_text,
                "manifest_size_bytes": manifest_size_bytes,
                "intelligence_available": not is_fallback,
                "query_failures": query_failures,  # JSONB as dict
                "warnings": warnings,
            }

            # Insert with event-driven client
            result = await client.insert(
                table="agent_manifest_injections",
                data=data,
                returning="correlation_id",
                timeout_ms=5000,
            )

            logger.info(
                f"Stored manifest injection: correlation_id={correlation_id}, "
                f"agent={agent_name}, patterns={patterns_count}"
            )

            return True

    except Exception as e:
        logger.error(f"Failed to store manifest: {e}", exc_info=True)
        return False
```

**Key Changes:**
- ✅ Changed from sync to async
- ✅ Replaced psycopg2 with DatabaseEventClient
- ✅ Removed manual connection management
- ✅ JSONB as dict (not psycopg2.extras.Json)
- ✅ Added timeout handling
- ⚠️ **Breaking**: Method signature changed to async

---

### Example 3: agents/lib/persistence.py

**Before (asyncpg with stored function):**
```python
async def update_mixin_compatibility(
    self,
    mixin_a: str,
    mixin_b: str,
    node_type: str,
    success: bool,
    conflict_reason: Optional[str] = None,
    resolution_pattern: Optional[str] = None,
) -> UUID:
    pool = await self._ensure_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            """
            SELECT update_mixin_compatibility($1, $2, $3, $4, $5, $6)
            """,
            mixin_a,
            mixin_b,
            node_type,
            success,
            conflict_reason,
            resolution_pattern,
        )
        return result
```

**After (DatabaseEventClient with stored function support):**
```python
async def update_mixin_compatibility(
    self,
    mixin_a: str,
    mixin_b: str,
    node_type: str,
    success: bool,
    conflict_reason: Optional[str] = None,
    resolution_pattern: Optional[str] = None,
) -> UUID:
    # Option 1: If DatabaseEventClient supports stored functions
    result = await self.client.query(
        query="SELECT update_mixin_compatibility($1, $2, $3, $4, $5, $6)",
        params=[mixin_a, mixin_b, node_type, success, conflict_reason, resolution_pattern],
        timeout_ms=5000,
    )
    return result[0]['update_mixin_compatibility']

    # Option 2: If stored function not supported, inline SQL
    # (This shows that some operations may need refactoring)
    result = await self.client.upsert(
        table="mixin_compatibility_matrix",
        data={
            "mixin_a": mixin_a,
            "mixin_b": mixin_b,
            "node_type": node_type,
            "success": success,
            "conflict_reason": conflict_reason,
            "resolution_pattern": resolution_pattern,
            "test_count": 1,  # Will be incremented on conflict
        },
        conflict_columns=["mixin_a", "mixin_b", "node_type"],
        returning="id",
    )
    return result['rows'][0]['id']
```

**Key Changes:**
- ✅ Replaced pool with client
- ✅ Event-driven query execution
- ⚠️ **Decision needed**: Stored function support in DatabaseEventClient?
- ⚠️ **Alternative**: Refactor stored functions to client-side logic

---

### Example 4: agents/parallel_execution/database_integration.py

**Before (Complex batch writes with circuit breaker):**
```python
class DatabaseIntegrationLayer:
    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or DatabaseConfig.from_env()
        self.pool: Optional[asyncpg.Pool] = None
        self.circuit_breaker = CircuitBreaker(...)

        # Batch write buffers
        self.trace_event_buffer = BatchWriteBuffer(...)
        self.routing_decision_buffer = BatchWriteBuffer(...)
        # ...

    async def initialize(self) -> bool:
        self.pool = await asyncpg.create_pool(...)
        # Start background tasks
        self.flush_task = asyncio.create_task(self._flush_loop())
        # ...

    async def write_trace_event(self, trace_id: str, event_type: str, ...):
        query = "INSERT INTO agent_observability.trace_events ..."
        params = [trace_id, event_type, ...]
        await self.trace_event_buffer.add(query, params)

    async def _flush_buffer(self, buffer: BatchWriteBuffer):
        batch = await buffer.get_batch()
        async with self.acquire() as conn:
            async with conn.transaction():
                for query, params in batch:
                    await conn.execute(query, *params)
```

**After (Simplified with DatabaseEventClient):**
```python
class DatabaseIntegrationLayer:
    """Simplified wrapper around DatabaseEventClient for observability."""

    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or DatabaseConfig.from_env()
        self.client = DatabaseEventClient(
            bootstrap_servers=config.kafka_brokers,
            request_timeout_ms=config.query_timeout * 1000,
        )
        # No need for circuit breaker - client has it built-in
        # No need for batch buffers - client handles batching

    async def initialize(self) -> bool:
        await self.client.start()
        return await self.client.health_check()

    async def write_trace_event(self, trace_id: str, event_type: str, level: str, ...):
        # Direct insert - client handles batching internally
        await self.client.insert(
            table="agent_observability.trace_events",
            data={
                "trace_id": trace_id,
                "event_type": event_type,
                "level": level,
                "message": message,
                "metadata": metadata or {},
                "agent_name": agent_name,
                "task_id": task_id,
                "duration_ms": duration_ms,
            },
            timeout_ms=5000,
        )

    # No need for _flush_buffer - client handles this
    # No need for background tasks - client manages these
```

**Key Changes:**
- ✅ Removed custom pooling
- ✅ Removed circuit breaker (client has it)
- ✅ Removed batch buffers (client handles batching)
- ✅ Removed background tasks (client manages these)
- ✅ Simplified code by ~60%
- ✅ Better separation of concerns

---

## Dependencies & Execution Order

### Dependency Graph

```
┌─────────────────────────────────────────────────────────────┐
│                    DatabaseEventClient                       │
│                  (Ready - No Migration)                      │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ (all depend on)
                            ↓
        ┌──────────────────────────────────────────┐
        │                                          │
        ↓                                          ↓
┌─────────────────┐                    ┌──────────────────────┐
│  PHASE 1 (Week 1)                    │  PHASE 1 (Week 1)    │
│  - db.py        │                    │  - kafka_agent_      │
│                 │                    │    action_consumer   │
└─────────────────┘                    └──────────────────────┘
        │                                          │
        │ (no dependencies)                        │
        ↓                                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    PHASE 2 (Week 2)                          │
│  - manifest_injector.py (uses db.py functions)              │
│  - observability_report.py (independent)                    │
│  - validate_002_migration.py (independent)                  │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ (all validated)
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    PHASE 3 (Week 3)                          │
│  - persistence.py (uses db.py pool pattern)                 │
│  - db_connection_pool.py (independent ONEX node)            │
│  - database_integration.py (uses db_connection_pool)        │
└─────────────────────────────────────────────────────────────┘
```

### Execution Order

**Week 1: Phase 1 (Simple Migrations)**
1. ✅ Migrate `agents/lib/db.py`
2. ✅ Test `db.py` with existing usages
3. ✅ Migrate `agents/lib/kafka_agent_action_consumer.py`
4. ✅ Test consumer with Kafka + database

**Week 2: Phase 2 (Medium Complexity)**
5. ✅ Migrate `agents/lib/manifest_injector.py` (depends on db.py pattern)
6. ✅ Test manifest injection workflow
7. ✅ Migrate `agents/parallel_execution/observability_report.py`
8. ✅ Migrate `agents/migrations/validate_002_migration.py`
9. ✅ Test all Phase 2 files

**Week 3: Phase 3 (High Complexity)**
10. ✅ Migrate `agents/lib/persistence.py`
11. ✅ Test code generation workflows
12. ✅ Migrate `agents/parallel_execution/db_connection_pool.py`
13. ✅ Migrate `agents/parallel_execution/database_integration.py`
14. ✅ Test observability framework end-to-end
15. ✅ Performance testing (1000+ events/sec)

---

## Testing Strategy

### Unit Tests

**For Each File:**
1. ✅ Test basic CRUD operations
2. ✅ Test error handling (timeout, connection failure)
3. ✅ Test correlation ID tracking
4. ✅ Test parameter passing
5. ✅ Test result conversion (asyncpg.Record → dict)

**Example Test (db.py):**
```python
import pytest
from agents.lib.db import execute_query, execute_command

@pytest.mark.asyncio
async def test_execute_query():
    """Test query execution with DatabaseEventClient."""
    # Setup
    correlation_id = str(uuid4())

    # Execute
    rows = await execute_query(
        "SELECT * FROM agent_routing_decisions WHERE confidence_score > $1",
        0.8,
        correlation_id=correlation_id,
    )

    # Assert
    assert isinstance(rows, list)
    assert all(isinstance(row, dict) for row in rows)
    assert all(row['confidence_score'] > 0.8 for row in rows)

@pytest.mark.asyncio
async def test_execute_command():
    """Test command execution with DatabaseEventClient."""
    # Setup
    correlation_id = str(uuid4())

    # Execute
    result = await execute_command(
        "INSERT INTO test_table (name) VALUES ($1)",
        "test_value",
        correlation_id=correlation_id,
    )

    # Assert
    assert result is not None
```

### Integration Tests

**End-to-End Workflows:**
1. ✅ Manifest injection → storage → retrieval
2. ✅ Kafka consumer → batch insert → query
3. ✅ Observability report generation
4. ✅ Code generation persistence workflow
5. ✅ Parallel execution observability

**Example Integration Test:**
```python
@pytest.mark.asyncio
async def test_manifest_injection_workflow():
    """Test complete manifest injection workflow."""
    # Generate manifest
    async with ManifestInjector(agent_name="test-agent") as injector:
        correlation_id = str(uuid4())
        manifest = await injector.generate_dynamic_manifest_async(correlation_id)

        # Verify storage
        storage = ManifestInjectionStorage()
        success = await storage.store_manifest_injection(
            correlation_id=UUID(correlation_id),
            agent_name="test-agent",
            manifest_data=manifest,
            formatted_text=injector.format_for_prompt(),
            query_times={"patterns": 450, "infrastructure": 320},
            sections_included=["patterns", "infrastructure"],
            patterns_count=120,
        )

        assert success

        # Query back
        async with DatabaseEventClientContext() as client:
            rows = await client.query(
                query="SELECT * FROM agent_manifest_injections WHERE correlation_id = $1",
                params=[correlation_id],
            )

            assert len(rows) == 1
            assert rows[0]['agent_name'] == "test-agent"
            assert rows[0]['patterns_count'] == 120
```

### Performance Tests

**Targets:**
- Query latency p95: <100ms
- Batch insert throughput: >1000 events/sec
- Concurrent queries: >100 queries/sec
- Memory usage: <50MB per client

**Example Performance Test:**
```python
import time
import asyncio

@pytest.mark.asyncio
async def test_query_latency():
    """Test query latency meets p95 target."""
    async with DatabaseEventClientContext() as client:
        latencies = []

        for _ in range(100):
            start = time.time()
            await client.query("SELECT 1")
            latency_ms = (time.time() - start) * 1000
            latencies.append(latency_ms)

        p95 = sorted(latencies)[94]  # 95th percentile
        assert p95 < 100, f"p95 latency {p95:.2f}ms exceeds 100ms target"

@pytest.mark.asyncio
async def test_batch_insert_throughput():
    """Test batch insert throughput meets target."""
    async with DatabaseEventClientContext() as client:
        batch_size = 1000
        start = time.time()

        # Insert 1000 events
        tasks = [
            client.insert(
                table="test_events",
                data={"event_id": i, "data": f"test_{i}"},
            )
            for i in range(batch_size)
        ]
        await asyncio.gather(*tasks)

        duration = time.time() - start
        throughput = batch_size / duration

        assert throughput > 1000, f"Throughput {throughput:.0f} events/sec below 1000 target"
```

---

## Rollback Plan

### Rollback Strategy

Each migration phase has a rollback path to revert to direct asyncpg if issues arise.

### Phase 1 Rollback

**If `db.py` migration fails:**
1. Restore original `db.py` from git history
2. Remove DatabaseEventClient import
3. Restore asyncpg pool implementation
4. Redeploy affected services

**Rollback Time**: ~15 minutes

**Command:**
```bash
git checkout HEAD~1 agents/lib/db.py
# Test
python -m pytest tests/agents/lib/test_db.py
# Deploy
```

### Phase 2 Rollback

**If `manifest_injector.py` migration fails:**
1. Restore original `ManifestInjectionStorage` class
2. Revert async → sync conversion
3. Restore psycopg2 imports
4. Update callers to use sync methods

**Rollback Time**: ~30 minutes

**Command:**
```bash
git checkout HEAD~1 agents/lib/manifest_injector.py
# Fix async callers
# Redeploy
```

### Phase 3 Rollback

**If `database_integration.py` migration fails:**
1. Restore original implementation
2. Restore custom pooling, circuit breaker, batch buffers
3. Restore background tasks
4. Redeploy observability framework

**Rollback Time**: ~45 minutes

**Command:**
```bash
git checkout HEAD~1 agents/parallel_execution/database_integration.py
# Restore dependencies
# Redeploy
```

### Rollback Decision Criteria

**Trigger rollback if:**
- ❌ Query latency p95 > 200ms (2x target)
- ❌ Error rate > 5%
- ❌ Data loss detected
- ❌ Critical service downtime > 5 minutes
- ❌ Performance degradation > 50%

**Monitor:**
- Query latency metrics
- Error logs
- Database event counts
- Service health checks

---

## Timeline & Effort Estimates

### Detailed Timeline

| Phase | Files | Tasks | Effort | Duration | Start Date | End Date |
|-------|-------|-------|--------|----------|------------|----------|
| **Phase 1** | 2 | Migrate simple files | 4-6 hours | 1 week | Week 1 Mon | Week 1 Fri |
| **Phase 2** | 3 | Migrate medium files | 12-16 hours | 1 week | Week 2 Mon | Week 2 Fri |
| **Phase 3** | 3 | Migrate complex files | 12-16 hours | 1 week | Week 3 Mon | Week 3 Fri |
| **Testing** | All | Integration & perf tests | 8 hours | Ongoing | Week 1 | Week 3 |
| **Total** | 9 | Complete migration | 28-40 hours | 3 weeks | - | - |

### Task Breakdown

**Phase 1 (Week 1): Simple Migrations**
- [ ] Day 1-2: Migrate `agents/lib/db.py` (1-2h)
  - [ ] Replace pool with client
  - [ ] Update execute_query
  - [ ] Update execute_command
  - [ ] Write unit tests
- [ ] Day 2-3: Migrate `agents/lib/kafka_agent_action_consumer.py` (2-3h)
  - [ ] Replace asyncpg with client
  - [ ] Update batch insert
  - [ ] Test idempotency
  - [ ] Integration test
- [ ] Day 4-5: Testing & validation
  - [ ] Run full test suite
  - [ ] Performance testing
  - [ ] Fix any issues

**Phase 2 (Week 2): Medium Complexity**
- [ ] Day 1-2: Migrate `agents/lib/manifest_injector.py` (4-5h)
  - [ ] Convert to async
  - [ ] Replace psycopg2 with client
  - [ ] Test storage workflow
- [ ] Day 3: Migrate `agents/parallel_execution/observability_report.py` (3-4h)
  - [ ] Replace psycopg2 with client
  - [ ] Convert to async
  - [ ] Test report generation
- [ ] Day 4: Migrate `agents/migrations/validate_002_migration.py` (2-3h)
  - [ ] Replace psycopg2 with client
  - [ ] Test validation workflow
- [ ] Day 5: Testing & validation
  - [ ] Integration tests
  - [ ] Performance tests

**Phase 3 (Week 3): High Complexity**
- [ ] Day 1-3: Migrate `agents/lib/persistence.py` (6-8h)
  - [ ] Replace pool with client
  - [ ] Handle stored functions
  - [ ] Update transactions
  - [ ] Test all operations
- [ ] Day 3-4: Migrate `agents/parallel_execution/db_connection_pool.py` (4-5h)
  - [ ] Wrap DatabaseEventClient
  - [ ] Maintain ONEX pattern
  - [ ] Test lifecycle
- [ ] Day 4-5: Migrate `agents/parallel_execution/database_integration.py` (5-6h)
  - [ ] Simplify with client
  - [ ] Remove custom batching
  - [ ] Test observability
- [ ] Day 5: Final testing & performance validation
  - [ ] End-to-end tests
  - [ ] Performance benchmarks
  - [ ] Production readiness check

### Resource Allocation

**Team**: 1 developer (full-time for 3 weeks)

**Skills Required:**
- Python async/await proficiency
- asyncpg/psycopg2 experience
- Kafka event-driven architecture
- PostgreSQL query optimization
- Testing (unit, integration, performance)

---

## Risk Assessment

### High Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **Breaking async changes** | High | High | Maintain async-compatible APIs; comprehensive testing |
| **Performance degradation** | Medium | High | Performance tests in each phase; rollback plan |
| **Data loss during migration** | Low | Critical | Read-only testing first; backup database |
| **Stored function incompatibility** | Medium | Medium | Test stored functions early; fallback to inline SQL |
| **Circuit breaker bypass** | Low | Medium | Verify client's circuit breaker works correctly |

### Medium Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **JSONB handling differences** | Medium | Medium | Test JSONB operations thoroughly; document differences |
| **Transaction semantics** | Low | Medium | Verify event-driven transactions behave correctly |
| **Connection pool exhaustion** | Low | Medium | Monitor client pool usage; adjust limits |
| **Timeout tuning** | Medium | Low | Test various timeout values; document recommendations |

### Low Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **Import errors** | Low | Low | Update imports systematically; test imports |
| **Type conversion issues** | Low | Low | Test type conversions; document differences |
| **Logging inconsistencies** | Low | Low | Standardize logging format |

### Risk Mitigation Strategies

**1. Comprehensive Testing**
- Unit tests for each migration
- Integration tests for workflows
- Performance tests for benchmarks
- Rollback tests for safety

**2. Phased Rollout**
- Start with simple files
- Validate before proceeding
- Monitor metrics continuously

**3. Feature Flags**
- Use environment variable to toggle between old/new implementations
- Gradual rollout in production
- Quick rollback if issues arise

**4. Documentation**
- Document all breaking changes
- Update migration guides
- Provide code examples

---

## Success Criteria

### Technical Success Criteria

**Performance:**
- ✅ Query latency p95 < 100ms (same as direct asyncpg)
- ✅ Batch insert throughput > 1000 events/sec
- ✅ Concurrent queries > 100 queries/sec
- ✅ Memory usage < 50MB per client
- ✅ Error rate < 1%

**Functionality:**
- ✅ All CRUD operations work correctly
- ✅ Transactions behave as expected
- ✅ JSONB handling works correctly
- ✅ Stored functions supported (or refactored)
- ✅ Idempotency maintained
- ✅ Circuit breaker functions correctly

**Quality:**
- ✅ 100% test coverage for migrated code
- ✅ No regressions in existing functionality
- ✅ All integration tests pass
- ✅ Performance tests meet targets
- ✅ Documentation complete and accurate

### Business Success Criteria

**Operational:**
- ✅ Zero data loss during migration
- ✅ < 1 hour total downtime (planned maintenance)
- ✅ Successful rollback capability validated
- ✅ Monitoring and alerting in place
- ✅ Team trained on new architecture

**Strategic:**
- ✅ Improved decoupling between agents and database
- ✅ Better traceability with correlation IDs
- ✅ Centralized logging and monitoring
- ✅ Easier scaling (Kafka event bus)
- ✅ Reduced operational complexity

### Validation Checklist

**Pre-Migration:**
- [ ] DatabaseEventClient fully tested and production-ready
- [ ] All dependencies documented
- [ ] Team trained on new architecture
- [ ] Rollback plan tested
- [ ] Monitoring dashboards created

**During Migration:**
- [ ] Each phase validated before proceeding
- [ ] Performance metrics tracked continuously
- [ ] Error logs monitored
- [ ] Rollback plan ready to execute

**Post-Migration:**
- [ ] All tests passing
- [ ] Performance targets met
- [ ] No regressions detected
- [ ] Documentation updated
- [ ] Team retrospective completed

---

## Appendix

### A. Query Pattern Reference

**DatabaseEventClient API:**

```python
# Query (SELECT)
rows = await client.query(
    query="SELECT * FROM table WHERE column = $1",
    params=[value],
    limit=100,
    offset=0,
    timeout_ms=10000,
)

# Insert
result = await client.insert(
    table="table_name",
    data={"column1": value1, "column2": value2},
    returning="id",
    timeout_ms=5000,
)

# Update
result = await client.update(
    table="table_name",
    data={"column1": new_value},
    filters={"id": record_id},
    timeout_ms=5000,
)

# Delete
result = await client.delete(
    table="table_name",
    filters={"id": record_id},
    timeout_ms=5000,
)

# Upsert
result = await client.upsert(
    table="table_name",
    data={"id": 1, "value": "updated"},
    conflict_columns=["id"],
    update_columns=["value"],
    returning="id",
    timeout_ms=5000,
)
```

### B. Common Migration Patterns

**Pattern 1: Simple SELECT**
```python
# Before (asyncpg)
rows = await conn.fetch("SELECT * FROM table WHERE id = $1", table_id)

# After (DatabaseEventClient)
rows = await client.query(
    query="SELECT * FROM table WHERE id = $1",
    params=[table_id],
)
```

**Pattern 2: INSERT with RETURNING**
```python
# Before (asyncpg)
record_id = await conn.fetchval(
    "INSERT INTO table (name) VALUES ($1) RETURNING id",
    name,
)

# After (DatabaseEventClient)
result = await client.insert(
    table="table",
    data={"name": name},
    returning="id",
)
record_id = result['rows'][0]['id']
```

**Pattern 3: Transaction**
```python
# Before (asyncpg)
async with conn.transaction():
    await conn.execute("INSERT INTO table1 ...")
    await conn.execute("INSERT INTO table2 ...")

# After (DatabaseEventClient)
# Note: Client handles transactions internally per operation
# For multi-operation transactions, use execute() with BEGIN/COMMIT
await client.execute("BEGIN")
try:
    await client.insert(table="table1", data=...)
    await client.insert(table="table2", data=...)
    await client.execute("COMMIT")
except Exception:
    await client.execute("ROLLBACK")
    raise
```

### C. Environment Variables

**Required for DatabaseEventClient:**
```bash
# Kafka Configuration
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:9092

# Optional (with defaults)
KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS}
KAFKA_REQUEST_TIMEOUT_MS=10000
```

**PostgreSQL (for omninode-bridge database adapter):**
```bash
# Connection details
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=***REDACTED***
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2025-10-30 | polymorphic-agent | Initial migration plan |

---

## Contact & Support

**Questions or Issues:**
- Review: `docs/database-event-client-usage.md`
- Test: `agents/lib/test_database_event_client.py`
- Reference: `agents/lib/database_event_client.py`

**Escalation Path:**
1. Review documentation
2. Test with sample code
3. Check Kafka/database logs
4. Review correlation ID traces

---

**End of Migration Plan**
