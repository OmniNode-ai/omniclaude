# Archon Intelligence Service - Issue Report

**Date**: 2025-11-10
**Reporter**: OmniClaude Team
**Service**: archon-intelligence (`192.168.86.101:8053`)
**Status**: ⚠️ Partial Functionality
**Priority**: Medium

---

## Executive Summary

The archon-intelligence service is operational and responding to manifest requests, but **infrastructure scanning** and **database schema introspection** are returning empty results. Additionally, the `code_generation_patterns` Qdrant collection is experiencing HTTP 400 errors.

**Impact**:
- Agents receive incomplete system context
- Missing infrastructure topology awareness
- Missing database schema information
- Reduced pattern discovery (only 48 patterns from `archon_vectors`, 0 from `code_generation_patterns`)

---

## Issues Identified

### 1. Infrastructure Topology Scanning - Empty Results ❌

**Symptom**: Infrastructure section returns empty objects

**Expected**:
```json
{
  "remote_services": {
    "postgresql": {
      "host": "192.168.86.200",
      "port": 5436,
      "database": "omninode_bridge",
      "status": "healthy",
      "table_count": 34
    },
    "kafka": {
      "bootstrap_servers": "192.168.86.200:29092",
      "status": "healthy",
      "topics": 97
    }
  },
  "local_services": {
    "qdrant": {
      "endpoint": "192.168.86.101:6333",
      "status": "healthy",
      "collections": 4
    },
    "archon_mcp": {
      "endpoint": "http://localhost:8051",
      "status": "healthy"
    }
  }
}
```

**Actual**:
```json
{
  "remote_services": {
    "postgresql": {},
    "kafka": {}
  },
  "local_services": {
    "qdrant": {},
    "archon_mcp": {}
  },
  "docker_services": []
}
```

**Root Cause**: Infrastructure scanning logic not populating service details

**Fix Required**:
- Implement PostgreSQL health check and metadata query
- Implement Kafka broker health check and topic enumeration
- Implement Qdrant health check and collection enumeration
- Implement Archon MCP health check

**Verification**:
```bash
# Test each service directly
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';"
# Expected: 34 tables

kcat -L -b 192.168.86.200:29092 | grep topics
# Expected: 97 topics

curl http://192.168.86.101:6333/collections
# Expected: 4 collections

curl http://localhost:8051/health
# Expected: 200 OK
```

---

### 2. Database Schema Introspection - Empty Results ❌

**Symptom**: Database schemas section returns no tables

**Expected**:
```json
{
  "tables": [
    {
      "name": "agent_routing_decisions",
      "columns": 15,
      "row_count": 1234
    },
    {
      "name": "agent_manifest_injections",
      "columns": 12,
      "row_count": 567
    }
    // ... 32 more tables
  ],
  "total_tables": 34
}
```

**Actual**:
```json
{
  "tables": [],
  "total_tables": 0
}
```

**Root Cause**: Database schema introspection query not executing or failing silently

**Fix Required**:
- Query `information_schema.tables` for table listing
- Query `information_schema.columns` for column details
- Add error handling and logging for schema queries

**SQL to Implement**:
```sql
-- Get all tables in public schema
SELECT
    table_name,
    (SELECT COUNT(*) FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = t.table_name) as column_count
FROM information_schema.tables t
WHERE table_schema = 'public'
ORDER BY table_name;
```

**Verification**:
```bash
source .env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';"
# Expected: 34
```

---

### 3. Qdrant Collection Error - HTTP 400 ❌

**Symptom**: `code_generation_patterns` collection returns HTTP 400

**Error Message**:
```
[correlation_id] Qdrant query (search (vector)) failed for code_generation_patterns: HTTP 400
```

**Expected**:
- Collection exists: ✅ (verified via `curl http://192.168.86.101:6333/collections`)
- Vector count: 8,571 vectors
- Query should succeed with pattern results

**Actual**:
- HTTP 400 error on vector search
- 0 patterns returned from this collection

**Possible Causes**:
1. **Vector dimensionality mismatch** - Query vector dimensions don't match collection
2. **Invalid query payload** - Malformed search request
3. **Collection schema issue** - Collection metadata corrupted
4. **Authentication/Authorization** - Permissions issue

**Debug Steps**:
```bash
# 1. Check collection info
curl http://192.168.86.101:6333/collections/code_generation_patterns

# 2. Check vector dimensions
curl http://192.168.86.101:6333/collections/code_generation_patterns | jq '.result.config.params.vectors'

# 3. Try simple search
curl -X POST http://192.168.86.101:6333/collections/code_generation_patterns/points/search \
  -H "Content-Type: application/json" \
  -d '{
    "vector": [0.1, 0.2, 0.3, ...],  # Match collection dimensions
    "limit": 5
  }'
```

**Fix Required**:
- Verify query vector dimensions match collection (likely 384 or 768 or 1536)
- Add error logging to show HTTP 400 response body
- Implement retry logic with exponential backoff
- Add fallback to skip collection if consistently failing

---

### 4. Code Analysis Request Timeouts - Performance ⚠️

**Symptom**: Some code analysis requests timeout after 3000ms

**Error Message**:
```
Code analysis request timeout (correlation_id: 3c10a14f-d7dd-473d-8ab5-d4bc81d6c8ad, timeout: 3000ms)
```

**Impact**:
- Partial manifest data
- Degraded user experience
- Fallback to minimal manifest

**Analysis**:
- 3000ms (3 second) timeout may be too aggressive for complex queries
- Memgraph or Qdrant queries may be slow
- Network latency to remote services

**Fix Required**:
- Increase timeout to 5000ms or 8000ms for complex queries
- Implement caching for repeated queries
- Add query performance logging
- Optimize slow queries (Memgraph graph traversals, Qdrant vector searches)

**Performance Targets**:
- Simple queries: <500ms
- Complex queries: <2000ms
- Timeout threshold: 5000ms (increased from 3000ms)

---

## Working Functionality ✅

These components are working correctly:

1. **Pattern Discovery** - 48 patterns from `archon_vectors` collection
2. **Debug Intelligence** - 20 successful workflow patterns
3. **Archon Search** - 5 results with 194ms query time (excellent performance)
4. **Action Logging Requirements** - Correlation ID tracking
5. **AI Models & ONEX Node Types** - Complete configuration

---

## Verification Checklist

After implementing fixes, verify each component:

### Infrastructure Topology
```bash
# Generate manifest and check infrastructure section
python3 << 'EOF'
import asyncio, sys, uuid, json
sys.path.insert(0, '/Volumes/PRO-G40/Code/omniclaude')
from agents.lib.manifest_injector import ManifestInjector

async def test():
    injector = ManifestInjector()
    manifest = await injector.generate_dynamic_manifest_async(
        correlation_id=str(uuid.uuid4()),
        user_prompt="test infrastructure",
        force_refresh=True
    )
    infra = manifest.get('infrastructure', {})

    # Verify PostgreSQL
    pg = infra['remote_services']['postgresql']
    assert pg.get('host'), "PostgreSQL host missing"
    assert pg.get('port'), "PostgreSQL port missing"
    print("✅ PostgreSQL metadata populated")

    # Verify Kafka
    kafka = infra['remote_services']['kafka']
    assert kafka.get('bootstrap_servers'), "Kafka bootstrap_servers missing"
    print("✅ Kafka metadata populated")

    # Verify Qdrant
    qdrant = infra['local_services']['qdrant']
    assert qdrant.get('endpoint'), "Qdrant endpoint missing"
    print("✅ Qdrant metadata populated")

    print("\n✅ All infrastructure checks passed!")

asyncio.run(test())
EOF
```

### Database Schemas
```bash
# Verify schema introspection
python3 << 'EOF'
import asyncio, sys, uuid
sys.path.insert(0, '/Volumes/PRO-G40/Code/omniclaude')
from agents.lib.manifest_injector import ManifestInjector

async def test():
    injector = ManifestInjector()
    manifest = await injector.generate_dynamic_manifest_async(
        correlation_id=str(uuid.uuid4()),
        user_prompt="test database",
        force_refresh=True
    )
    schemas = manifest.get('database_schemas', {})
    tables = schemas.get('tables', [])

    assert len(tables) > 0, "No tables returned"
    assert schemas.get('total_tables', 0) > 0, "Total tables is 0"
    print(f"✅ Database schemas populated: {len(tables)} tables")

asyncio.run(test())
EOF
```

### Qdrant Collection
```bash
# Verify code_generation_patterns collection query
curl -X POST http://192.168.86.101:6333/collections/code_generation_patterns/points/scroll \
  -H "Content-Type: application/json" \
  -d '{"limit": 5, "with_payload": true, "with_vector": false}'

# Expected: 5 results with pattern payloads, no HTTP 400
```

---

## Priority Recommendations

### High Priority (Fix Immediately)
1. **Qdrant HTTP 400 Error** - Blocking pattern discovery from largest collection (8,571 vectors)
   - Impact: 0 patterns from code examples
   - Fix: Debug HTTP 400 response body, fix query vector dimensions

### Medium Priority (Fix Soon)
2. **Infrastructure Scanning** - Missing critical system context
   - Impact: Agents don't know service endpoints, health status
   - Fix: Implement service health checks and metadata queries

3. **Database Schema Introspection** - Missing database awareness
   - Impact: Agents don't know table structures
   - Fix: Implement information_schema queries

### Low Priority (Optimize Later)
4. **Code Analysis Timeouts** - Performance optimization
   - Impact: Occasional fallback to minimal manifest
   - Fix: Increase timeout, optimize queries, add caching

---

## Contact Information

**Reporting Team**: OmniClaude Development
**Service Owner**: Archon Intelligence Team (`192.168.86.101:8053`)
**Related Services**:
- Qdrant: `192.168.86.101:6333`
- Memgraph: `192.168.86.101:7687`
- PostgreSQL: `192.168.86.200:5436`
- Kafka: `192.168.86.200:29092`

**Test Environment**: Development (`dev.` topic prefixes)
**OmniClaude Version**: Current (observability_fixes branch)

---

## Appendix: Full Test Output

### Infrastructure Section (Current - Empty)
```json
{
  "remote_services": {
    "postgresql": {},
    "kafka": {}
  },
  "local_services": {
    "qdrant": {},
    "archon_mcp": {}
  },
  "docker_services": []
}
```

### Database Schemas Section (Current - Empty)
```json
{
  "tables": [],
  "total_tables": 0
}
```

### Pattern Discovery (Current - Partial)
- `archon_vectors`: ✅ 48 patterns found
- `code_generation_patterns`: ❌ 0 patterns (HTTP 400 error)
- **Expected total**: 15,689+ patterns (48 + 8,571)
- **Actual total**: 48 patterns (99.4% missing)

---

**End of Report**
