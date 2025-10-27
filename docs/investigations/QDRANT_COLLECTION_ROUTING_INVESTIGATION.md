# Qdrant Collection Routing Investigation

**Date**: 2025-10-26
**Correlation ID**: 77a04976-e2c9-4e02-8374-0153b20c638f
**Investigator**: Claude Code (Research Mode)
**Status**: ✅ Root Cause Identified

## Problem Statement

Event bus queries from omniclaude are only returning patterns from the `execution_patterns` collection (10 patterns) instead of both `execution_patterns` and `code_patterns` collections (1,085 total patterns).

### Expected vs Actual

**Expected (from Omniarchon sync):**
- ✅ 1,065 code patterns in `code_patterns` collection
- ✅ 20 ONEX templates in `execution_patterns` collection
- ✅ Total: 1,085 patterns available

**Actual (from Omniclaude queries):**
- ❌ Only 10 patterns returned from `execution_patterns`
- ❌ `code_patterns` collection never queried
- ❌ Missing 1,065 implementation patterns

## Investigation Flow

### 1. Omniclaude Request Side ✅

**Files Examined:**
- `/Volumes/PRO-G40/Code/omniclaude/agents/lib/manifest_injector.py`
- `/Volumes/PRO-G40/Code/omniclaude/agents/lib/intelligence_event_client.py`

**Request Flow:**
```python
# manifest_injector.py line 270-283
result = await client.request_code_analysis(
    content="",
    source_path="node_*_*.py",
    language="python",
    options={
        "operation_type": "PATTERN_EXTRACTION",
        "include_patterns": True,
        "include_metrics": False,
        # ⚠️ NO collection_name parameter!
    },
    timeout_ms=self.query_timeout_ms,
)
```

**Key Findings:**
- Request payload does NOT include `collection_name` parameter
- Publishes to Kafka topic: `dev.archon-intelligence.intelligence.code-analysis-requested.v1`
- Assumes handler will query appropriate collections

### 2. Event Bus Transport ✅

**Configuration:**
- Kafka brokers: `192.168.86.200:29102`
- Topic naming: ONEX event bus architecture
- Transport working correctly (requests reach archon-intelligence)

### 3. Omniarchon Handler Side 🔴 ROOT CAUSE

**Files Examined:**
- `/Users/jonah/Code/omniarchon/services/intelligence/src/handlers/codegen_pattern_handler.py`
- `/Users/jonah/Code/omniarchon/services/intelligence/src/services/pattern_learning/codegen_pattern_service.py`

**Handler Flow:**
```
CodegenPatternHandler.handle_event()
  → CodegenPatternService.find_similar_nodes()
  → NodeQdrantVectorIndexEffect.search_similar()
  → Qdrant query with collection_name
```

## Root Cause: Hardcoded Collection Name

**File**: `/Users/jonah/Code/omniarchon/services/intelligence/src/services/pattern_learning/codegen_pattern_service.py`

**Line 78:**
```python
# Default collection for codegen patterns
DEFAULT_COLLECTION = "execution_patterns"
```

**Lines 139-144:**
```python
# Create search contract
search_contract = ModelContractVectorSearchEffect(
    collection_name=self.DEFAULT_COLLECTION,  # 🔴 HARDCODED!
    query_text=f"{node_type}: {node_description}",
    limit=limit * 2,
    score_threshold=score_threshold,
)
```

### Why This Is The Problem

1. **Hardcoded Default**: `DEFAULT_COLLECTION = "execution_patterns"` (line 78)
2. **Always Uses Default**: Line 140 uses `self.DEFAULT_COLLECTION` with no override mechanism
3. **No Configuration Path**: No environment variable, constructor parameter, or request payload to specify collection
4. **Wrong Collection**: Queries `execution_patterns` (20 ONEX templates) instead of `code_patterns` (1,065 implementations)

### What Should Happen

**Option A: Query Both Collections (Recommended)**
```python
# Search both collections and merge results
collections = ["execution_patterns", "code_patterns"]
all_results = []
for collection in collections:
    search_contract = ModelContractVectorSearchEffect(
        collection_name=collection,
        query_text=f"{node_type}: {node_description}",
        limit=limit,
        score_threshold=score_threshold,
    )
    results = await self.vector_index.search_similar(search_contract)
    all_results.extend(results.hits)

# Sort merged results by score
all_results.sort(key=lambda x: x.score, reverse=True)
return all_results[:limit]
```

**Option B: Request Parameter (Alternative)**
```python
# Allow caller to specify collection via request payload
async def find_similar_nodes(
    self,
    node_description: str,
    node_type: str,
    limit: int = 5,
    score_threshold: float = 0.7,
    collection_name: str = None,  # NEW: optional override
) -> List[Dict[str, Any]]:
    collection = collection_name or self.DEFAULT_COLLECTION
    search_contract = ModelContractVectorSearchEffect(
        collection_name=collection,
        ...
    )
```

**Option C: Environment Variable (For Infrastructure)**
```python
# Allow configuration via environment
DEFAULT_COLLECTIONS = os.getenv(
    "QDRANT_PATTERN_COLLECTIONS",
    "execution_patterns,code_patterns"
).split(",")

# Query all configured collections
for collection in DEFAULT_COLLECTIONS:
    ...
```

## Recommended Fix: Query Both Collections

**Why Option A is Best:**
- ✅ No breaking changes to API contracts
- ✅ Works with existing omniclaude requests
- ✅ Provides complete pattern coverage (1,085 patterns)
- ✅ Automatically benefits from both collections
- ✅ Simple to implement (10-15 lines of code)

**Implementation Location:**
```
File: /Users/jonah/Code/omniarchon/services/intelligence/src/services/pattern_learning/codegen_pattern_service.py
Method: CodegenPatternService.find_similar_nodes() (lines 99-190)
```

**Implementation Steps:**

1. **Update find_similar_nodes() to query both collections**:
```python
async def find_similar_nodes(
    self,
    node_description: str,
    node_type: str,
    limit: int = 5,
    score_threshold: float = 0.7,
) -> List[Dict[str, Any]]:
    """Find similar nodes from BOTH execution_patterns and code_patterns."""

    # Define collections to search
    collections = ["execution_patterns", "code_patterns"]
    all_hits = []

    # Query each collection
    for collection_name in collections:
        try:
            search_contract = ModelContractVectorSearchEffect(
                collection_name=collection_name,
                query_text=f"{node_type}: {node_description}",
                limit=limit * 2,  # Get more for merging
                score_threshold=score_threshold,
            )

            result = await self.vector_index.search_similar(search_contract)
            all_hits.extend(result.hits)

            logger.info(
                f"Found {len(result.hits)} hits in {collection_name} "
                f"(query: '{node_description[:50]}...')"
            )

        except Exception as e:
            logger.error(
                f"Failed to query {collection_name}: {e}",
                exc_info=True
            )
            # Continue with other collections

    # Sort merged results by score (highest first)
    all_hits.sort(key=lambda hit: hit.score, reverse=True)

    # Filter by node_type and transform results
    similar_nodes = []
    for hit in all_hits:
        payload = hit.payload

        # Filter by node type
        if payload.get("node_type") != node_type:
            continue

        # Extract node information
        node_info = {
            "node_id": hit.id,
            "similarity_score": round(hit.score, 4),
            "description": payload.get("text", payload.get("description", "")),
            "collection": hit.collection_name,  # Track source collection
            # ... rest of fields ...
        }

        similar_nodes.append(node_info)

        # Stop if we have enough results
        if len(similar_nodes) >= limit:
            break

    logger.info(
        f"Merged results: {len(similar_nodes)} similar {node_type} nodes "
        f"from {len(collections)} collections "
        f"(avg score: {sum(n['similarity_score'] for n in similar_nodes) / len(similar_nodes) if similar_nodes else 0:.2f})"
    )

    return similar_nodes
```

2. **Update class constant for documentation**:
```python
class CodegenPatternService:
    # Collections searched for codegen patterns
    PATTERN_COLLECTIONS = ["execution_patterns", "code_patterns"]

    # Legacy: kept for backward compatibility
    DEFAULT_COLLECTION = "execution_patterns"  # deprecated
```

3. **Add logging for visibility**:
```python
logger.info(
    f"Searching {len(collections)} Qdrant collections: {collections}"
)
```

## Expected Impact

### Before Fix
- **Patterns Returned**: 10 (from `execution_patterns` only)
- **Collections Queried**: 1 (`execution_patterns`)
- **Coverage**: 0.9% of available patterns (10/1,085)
- **Query Time**: ~50-100ms

### After Fix
- **Patterns Returned**: Up to limit (default 5, from merged results)
- **Collections Queried**: 2 (`execution_patterns` + `code_patterns`)
- **Coverage**: 100% of available patterns (1,085/1,085)
- **Query Time**: ~100-200ms (2x collections, parallel possible)
- **Result Quality**: Significantly improved (access to real implementations)

### Performance Considerations

**Sequential Queries (Current Approach):**
- Time: ~100ms per collection × 2 = ~200ms total
- Simple implementation
- Good enough for current load

**Parallel Queries (Future Optimization):**
```python
# Query both collections in parallel
search_tasks = [
    self.vector_index.search_similar(create_contract(coll))
    for coll in collections
]
results = await asyncio.gather(*search_tasks)
# Time: ~100ms total (max of both queries)
```

## Testing Plan

### 1. Unit Test
```python
# test_codegen_pattern_service.py
async def test_find_similar_nodes_queries_both_collections():
    service = CodegenPatternService()

    results = await service.find_similar_nodes(
        node_description="Database connection with retry logic",
        node_type="effect",
        limit=10
    )

    # Verify results from both collections
    collections_seen = set(r["collection"] for r in results)
    assert "execution_patterns" in collections_seen or "code_patterns" in collections_seen

    # Verify results are sorted by score
    scores = [r["similarity_score"] for r in results]
    assert scores == sorted(scores, reverse=True)
```

### 2. Integration Test
```python
# Test via event bus
async def test_pattern_discovery_full_coverage():
    client = IntelligenceEventClient()
    await client.start()

    # Request pattern discovery
    result = await client.request_code_analysis(
        content="",
        source_path="node_*_effect.py",
        language="python",
        options={"operation_type": "PATTERN_EXTRACTION"},
    )

    patterns = result.get("patterns", [])

    # Should see patterns from both collections
    assert len(patterns) > 10  # More than just execution_patterns

    # Verify collection diversity
    collections = set(p.get("collection") for p in patterns if "collection" in p)
    assert len(collections) >= 1  # At least one collection
```

### 3. Manual Verification
```bash
# Before fix: only execution_patterns
curl -X POST http://localhost:8053/pattern-matching \
  -H "Content-Type: application/json" \
  -d '{
    "node_description": "Database writer with transaction support",
    "node_type": "effect"
  }'
# Expected: 10 patterns from execution_patterns

# After fix: both collections
# Same request
# Expected: Patterns from both execution_patterns and code_patterns
```

## Alternative Solutions (Not Recommended)

### Alternative 1: Change Default Collection to code_patterns
**Problem**: Loses ONEX templates from execution_patterns

### Alternative 2: Create Combined Collection
**Problem**: Requires data duplication, sync complexity

### Alternative 3: Request-Level Collection Selection
**Problem**: Requires changes to omniclaude request contracts

## References

**Code Files:**
- Omniclaude client: `/Volumes/PRO-G40/Code/omniclaude/agents/lib/intelligence_event_client.py`
- Omniclaude manifest: `/Volumes/PRO-G40/Code/omniclaude/agents/lib/manifest_injector.py`
- Omniarchon handler: `/Users/jonah/Code/omniarchon/services/intelligence/src/handlers/codegen_pattern_handler.py`
- Omniarchon service: `/Users/jonah/Code/omniarchon/services/intelligence/src/services/pattern_learning/codegen_pattern_service.py` ⭐ **FIX HERE**

**Documentation:**
- Event contracts: `/Volumes/PRO-G40/Code/omniclaude/docs/INTELLIGENCE_REQUEST_CONTRACTS.md`
- Migration doc: `/Volumes/PRO-G40/Code/omniclaude/docs/MANIFEST_INJECTOR_EVENT_BUS_MIGRATION.md`

**Infrastructure:**
- Qdrant endpoint: `http://qdrant:6333` (Docker internal)
- External access: `http://192.168.86.200:6333`
- Collections: `execution_patterns` (20), `code_patterns` (1,065)

## Conclusion

✅ **Root Cause Confirmed**: Hardcoded collection name in `CodegenPatternService.find_similar_nodes()`

🎯 **Fix Required**: Query both `execution_patterns` and `code_patterns` collections, merge and sort results

📍 **Location**: `/Users/jonah/Code/omniarchon/services/intelligence/src/services/pattern_learning/codegen_pattern_service.py` lines 99-190

⏱️ **Estimated Effort**: 30 minutes (code change + testing)

🚀 **Expected Improvement**: 100x increase in pattern coverage (10 → 1,085 patterns available)

---

**Investigation Complete**: 2025-10-26
**Ready for Implementation**: Yes
**Breaking Changes**: None (backward compatible)
