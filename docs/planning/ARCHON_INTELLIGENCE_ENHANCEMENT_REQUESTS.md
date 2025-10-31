# Archon Intelligence Enhancement Requests

**Target Repository**: OmniNode-ai/omniarchon
**Planning Folder**: `docs/planning/` or `docs/enhancements/`
**Created**: 2025-10-30
**From**: OmniClaude integration team

## Overview

This document contains enhancement requests for the Archon Intelligence service based on integration experience with OmniClaude. These improvements would benefit all Archon Intelligence consumers.

---

## Enhancement 1: Qdrant Vector Indexing

### Current State
- **Status**: Vectors stored but not indexed
- **Impact**: Full collection scans for similarity searches
- **Metrics**:
  - `code_patterns` collection: 1,065 vectors, 0 indexed
  - `execution_patterns` collection: 20 vectors, 0 indexed
  - Vector size: 768 dimensions (cosine distance)

### Problem
Qdrant HNSW indexing is not enabled, causing:
- Slower similarity searches (linear scan vs HNSW graph traversal)
- Higher CPU usage during pattern queries
- Degraded performance as vector count grows

### Proposed Solution

**Phase 1: Enable HNSW Indexing (1-2 hours)**
```python
# In archon-intelligence initialization or migration
async def enable_qdrant_indexing():
    """Enable HNSW indexing for faster similarity search"""

    collections = ["code_patterns", "execution_patterns", "quality_vectors"]

    for collection in collections:
        # HNSW params optimized for 768-dim vectors
        await qdrant_client.update_collection(
            collection_name=collection,
            hnsw_config={
                "m": 16,                    # Number of bi-directional links
                "ef_construct": 100,        # Size of dynamic candidate list
                "full_scan_threshold": 20000  # Use HNSW when >20k points
            }
        )
```

**Phase 2: Add Keyword Indexing (30 min)**
```python
# Add payload indexes for common filters
indexes = [
    {"field_name": "pattern_name", "field_schema": "keyword"},
    {"field_name": "language", "field_schema": "keyword"},
    {"field_name": "node_type", "field_schema": "keyword"},
    {"field_name": "complexity", "field_schema": "keyword"}
]

for index in indexes:
    await qdrant_client.create_payload_index(
        collection_name="code_patterns",
        **index
    )
```

### Expected Impact
- **Query time**: 50-70% reduction for similarity searches
- **Scalability**: Supports 100k+ vectors efficiently
- **Resource usage**: Lower CPU utilization

### Testing Checklist
- [ ] Measure search latency before/after (should see <100ms for p95)
- [ ] Verify index build completes without memory issues
- [ ] Test with varying vector counts (100, 1k, 10k)
- [ ] Monitor CPU/memory during index rebuild

---

## Enhancement 2: Query Response Time Optimization

### Current State
- **Avg response time**: 7,500ms (from OmniClaude metrics)
- **Target**: <2,000ms
- **Bottleneck**: Unknown (requires profiling)

### Problem
Intelligence queries from OmniClaude timeout frequently:
- 34% of manifest injections discover <50 patterns (should be 120)
- Timeouts set to 10s to compensate
- Impacts user experience in Claude Code hooks

### Proposed Investigation

**Phase 1: Add Response Time Metrics (2 hours)**
```python
# In archon-intelligence request handlers
import time
from prometheus_client import Histogram

response_time = Histogram(
    'intelligence_response_time_seconds',
    'Response time for intelligence queries',
    ['operation_type', 'collection']
)

@response_time.labels(operation_type='pattern_query', collection='code_patterns').time()
async def query_patterns(request):
    # Existing code...
    pass
```

**Phase 2: Profile Key Operations (4 hours)**
Identify which stage is slow:
1. Kafka message consumption (should be <10ms)
2. Qdrant vector search (should be <100ms with indexing)
3. Memgraph relationship queries (should be <200ms)
4. PostgreSQL schema queries (should be <50ms)
5. Response serialization (should be <10ms)
6. Kafka message production (should be <10ms)

**Phase 3: Implement Optimizations**

Based on profiling results:

**A. Database Connection Pooling**
```python
# Use asyncpg connection pool
pool = await asyncpg.create_pool(
    dsn=DATABASE_URL,
    min_size=5,
    max_size=20,
    command_timeout=2.0  # Fail fast
)
```

**B. Parallel Query Execution**
```python
# Execute Qdrant + Memgraph + PostgreSQL in parallel
results = await asyncio.gather(
    qdrant_client.search(...),
    memgraph_client.query(...),
    postgres_pool.fetch(...),
    return_exceptions=True  # Graceful degradation
)
```

**C. Query Result Caching**
```python
# Cache frequently requested patterns in Valkey
async def get_patterns_cached(collection: str, query_hash: str):
    """Check Valkey cache before querying Qdrant"""
    cache_key = f"patterns:{collection}:{query_hash}"

    # Try cache first (TTL: 5 minutes)
    cached = await valkey_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # Cache miss - query Qdrant
    results = await qdrant_client.search(...)
    await valkey_client.setex(cache_key, 300, json.dumps(results))

    return results
```

### Expected Impact
- **Query time**: 7,500ms → 1,500ms (80% reduction)
- **Success rate**: 66% → 90%+ manifest injections with full patterns
- **Timeout reduction**: 10s → 3s (less waiting on failures)

### Metrics to Track
- Response time by operation type (p50, p95, p99)
- Cache hit rate (target: >60%)
- Database connection pool utilization
- Failed query rate

---

## Enhancement 3: Graceful Degradation

### Current State
- **Failure mode**: All-or-nothing (timeout returns empty manifest)
- **User impact**: No patterns available on any component failure

### Problem
Single component failure (e.g., Qdrant slow) cascades to total failure:
```
Qdrant timeout → Entire query fails → Empty manifest → No intelligence
```

### Proposed Solution

**Partial Results with Quality Indicators**
```python
class IntelligenceResponse:
    patterns: List[Pattern]
    infrastructure: Optional[InfrastructureInfo]  # None if failed
    models: Optional[ModelInfo]  # None if failed
    schemas: Optional[SchemaInfo]  # None if failed

    # Quality metadata
    completeness_score: float  # 0.0-1.0
    failed_components: List[str]  # ["infrastructure", "schemas"]
    query_time_ms: int
    partial_results: bool  # True if any component failed
```

**Component-Level Timeouts**
```python
# Don't wait 10s for all components - timeout each individually
async def gather_intelligence(request):
    """Gather intelligence with per-component timeouts"""

    results = await asyncio.gather(
        asyncio.wait_for(query_patterns(), timeout=2.0),
        asyncio.wait_for(query_infrastructure(), timeout=1.0),
        asyncio.wait_for(query_models(), timeout=1.0),
        asyncio.wait_for(query_schemas(), timeout=1.0),
        return_exceptions=True  # Continue on timeout
    )

    # Build response from successful components
    return build_partial_response(results)
```

### Expected Impact
- **Availability**: 66% → 95%+ (some intelligence always returned)
- **User experience**: Partial intelligence better than none
- **Debugging**: Clear indication of which component failed

---

## Enhancement 4: Standardized Error Responses

### Current State
- **Error handling**: Inconsistent across operations
- **Consumer impact**: Hard to distinguish timeout vs failure vs empty result

### Problem
OmniClaude can't tell the difference between:
- Query timeout (should retry with backoff)
- No patterns found (expected, use fallback)
- Service error (should log and alert)

### Proposed Solution

**Standardized Error Event Schema**
```python
# Publish to *.intelligence.code-analysis-failed.v1
class IntelligenceFailed(BaseModel):
    correlation_id: UUID
    operation_type: str
    error_code: str  # TIMEOUT, NOT_FOUND, SERVICE_ERROR, VALIDATION_ERROR
    error_message: str
    error_category: str  # transient, permanent, client_error
    retry_after_ms: Optional[int]  # Suggest retry delay
    failed_component: str  # qdrant, memgraph, postgres
    partial_results_available: bool
```

**Error Code Catalog**
```python
ERROR_CODES = {
    "TIMEOUT": "transient",           # Retry with backoff
    "NOT_FOUND": "permanent",         # Don't retry, use fallback
    "SERVICE_ERROR": "transient",     # Retry up to 3 times
    "VALIDATION_ERROR": "client_error",  # Don't retry, fix request
    "RATE_LIMIT": "transient",        # Retry after N seconds
}
```

### Expected Impact
- **Client integration**: Easier error handling logic
- **Debugging**: Clear error categorization
- **Reliability**: Smarter retry strategies

---

## Implementation Priority

### High Priority (Do First)
1. ✅ **Qdrant Indexing** - Biggest performance win (1-2 hours)
2. ✅ **Response Time Profiling** - Identify actual bottleneck (4 hours)
3. ✅ **Graceful Degradation** - Improve reliability immediately (4 hours)

### Medium Priority
4. ⏸ **Query Optimization** - Based on profiling results (varies)
5. ⏸ **Error Standardization** - Improve client integration (2 hours)

### Low Priority (Nice to Have)
6. ⏸ **Caching Layer** - After other optimizations proven (4 hours)

---

## Testing & Validation

### Performance Benchmarks
```bash
# Before optimization baseline
./scripts/benchmark_intelligence.sh --iterations 100

# Expected results:
# - p50: <500ms
# - p95: <1500ms
# - p99: <2500ms
# - Success rate: >95%
```

### Load Testing
```bash
# Simulate OmniClaude load (10 concurrent manifest injections)
./scripts/load_test_intelligence.sh --concurrency 10 --duration 60s

# Monitor:
# - Response times under load
# - Cache hit rates
# - Resource utilization (CPU, memory, network)
```

---

## Questions for Archon Team

1. **Qdrant Indexing**: Is there a reason indexing is disabled? Memory constraints?
2. **Performance Targets**: What are Archon's internal SLOs for query response time?
3. **Caching Strategy**: Does Archon already have caching (Valkey/Redis)? Can we leverage it?
4. **Monitoring**: What metrics are currently tracked? Can we get access to dashboards?
5. **Profiling**: Can we run profiling tools (py-spy, cProfile) in production?

---

## Integration Context

**OmniClaude Usage Patterns**:
- **Frequency**: Every agent execution (~100-200/hour)
- **Query Types**: Pattern discovery (80%), infrastructure (15%), schemas (5%)
- **Timeout Budget**: 5s total (2s Qdrant, 1s Memgraph, 1s Postgres, 1s overhead)
- **Acceptable Failure Rate**: <5%
- **Cache TTL Preferences**: Patterns (5min), Infrastructure (1hr), Schemas (30min)

**Current Metrics** (from OmniClaude observability):
- 270 manifest injections (last 7 days)
- 178 high-pattern-count (>100 patterns) = 66% success
- 92 low-pattern-count (<50 patterns) = 34% degraded
- Avg query time: 7,488ms (successful queries only)

---

## Document Maintenance

**Move to Archon Repository**:
```bash
# Target location (adjust based on Archon's structure)
omniarchon/docs/planning/OMNICLAUDE_ENHANCEMENT_REQUESTS.md

# or
omniarchon/docs/enhancements/query-performance-optimization.md
```

**Update Tracking**:
- Link to GitHub issues once created
- Track implementation status
- Document performance improvements achieved

---

**Contact**: OmniClaude Team
**Related Docs**:
- OmniClaude: `docs/planning/OMNICLAUDE_INTELLIGENCE_OPTIMIZATION_PLAN.md`
- Architecture: `docs/EVENT_BUS_INTELLIGENCE_IMPLEMENTATION.md`
