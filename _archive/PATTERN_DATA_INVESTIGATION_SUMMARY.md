# Pattern Data Investigation - Executive Summary

**Date**: 2025-11-10
**Issue**: Synthetic pattern data appearing in manifest
**Status**: ✅ Root cause identified

---

## 🎯 Key Finding

**The synthetic "domain_0" and "service_0" values ARE coming from Qdrant**, but from **test patterns with placeholder metadata**, not from a transformation bug.

### Evidence:

From Claude hooks log (`post-tool-use.log`):

```json
{
  "pattern_name": "ONEX NodeService0Effect class pattern",
  "source_context": {
    "domain": "domain_0",
    "service_name": "service_0",
    "framework": "onex",
    "node_type": "EFFECT",
    "quality_score": 0.9,
    "generation_date": "2025-11-04T15:14:04.395901+00:00"
  }
}
```

**These are TEST PATTERNS stored in Qdrant during development/testing.**

---

## 🔍 Two Types of Qdrant Data

### Type 1: Test Patterns (with metadata)

**Source**: Pattern learning system during testing
**Structure**: Complete pattern metadata
**Example**:
```json
{
  "pattern_name": "ONEX NodeService0Effect class pattern",
  "pattern_description": "ONEX node class: NodeService0Effect",
  "node_types": ["EFFECT"],
  "confidence_score": 0.9,
  "source_context": {
    "domain": "domain_0",        ← Synthetic placeholder
    "service_name": "service_0"  ← Synthetic placeholder
  }
}
```

**Problem**: These test patterns pollute production queries with synthetic data.

### Type 2: Raw Code Data (without metadata)

**Source**: Code ingestion pipeline
**Structure**: File content only
**Example**:
```json
{
  "file_path": "/Volumes/PRO-G40/Code/omniarchon/python/src/server/services/prompt_service.py",
  "content": "prompt_service.py\n\n\"\"\"Prompt Service Module...",
  "project_name": "omniarchon",
  "language": "python"
}
```

**Problem**: Pattern extraction handler expects metadata that doesn't exist.

---

## 🚨 Root Cause

### Immediate Issue: Test Data Pollution

Qdrant collections contain **test patterns with synthetic placeholder values** that are being returned in production queries.

**Impact**:
- Agents see "domain_0" and "service_0" instead of real domains/services
- Test patterns mixed with real code patterns
- Confusing, low-value pattern recommendations

### Underlying Issue: Schema Heterogeneity

Qdrant has **two different data schemas** in the same collections:
1. Test patterns: Full metadata (pattern_name, source_context, confidence_score)
2. Real code data: Raw content (file_path, content, project_name)

**Impact**:
- Pattern extraction handler can't handle both schemas
- Defaults/fallbacks create "Unknown Pattern" entries
- Inconsistent pattern quality

---

## ✅ Solutions

### Solution 1: Filter Out Test Data (IMMEDIATE - 15 minutes)

**Where**: `pattern_extraction_handler.py` line 168 (in scroll query)

**Add filter**:
```python
# Build query filter based on options
filter_conditions = []

# CRITICAL: Filter out test patterns with synthetic data
# Test patterns have source_context.domain starting with "domain_" or "test"
filter_conditions.append(
    models.Filter(
        must_not=[
            models.FieldCondition(
                key="source_context.domain",
                match=models.MatchValue(value="domain_0"),
            ),
            models.FieldCondition(
                key="source_context.domain",
                match=models.MatchText(text="test"),
            ),
        ]
    )
)
```

**Result**:
- ✅ Test patterns excluded from production queries
- ✅ Only real code patterns returned
- ✅ No more "domain_0" or "service_0" in manifest

### Solution 2: Separate Collections (RECOMMENDED - 1 hour)

**Create dedicated collections**:

1. **`test_patterns`** collection
   - All patterns with `source_context.domain` matching "test*" or "domain_*"
   - Used for testing/development only
   - Never queried in production

2. **`code_generation_patterns`** collection (existing, but cleaned)
   - Only real code patterns
   - Real file paths from omniarchon codebase
   - Production queries go here

3. **`enriched_patterns`** collection (future)
   - Real code patterns with LLM-generated metadata
   - High-quality descriptions, use cases, confidence scores
   - Ultimate production collection

**Migration script**:
```python
async def migrate_test_patterns():
    """Move test patterns to separate collection."""
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.http import models

    client = AsyncQdrantClient(url="http://localhost:6333")

    # Query all test patterns
    test_patterns, _ = await client.scroll(
        collection_name="code_generation_patterns",
        scroll_filter=models.Filter(
            should=[
                models.FieldCondition(
                    key="source_context.domain",
                    match=models.MatchText(text="test"),
                ),
                models.FieldCondition(
                    key="source_context.domain",
                    match=models.MatchText(text="domain_0"),
                ),
            ]
        ),
        limit=1000,
    )

    # Create test_patterns collection
    await client.create_collection(
        collection_name="test_patterns",
        vectors_config=models.VectorParams(
            size=384,  # Match existing collection
            distance=models.Distance.COSINE,
        ),
    )

    # Copy test patterns to new collection
    for pattern in test_patterns:
        await client.upsert(
            collection_name="test_patterns",
            points=[pattern],
        )

    # Delete test patterns from production collection
    await client.delete(
        collection_name="code_generation_patterns",
        points_selector=models.FilterSelector(
            filter=models.Filter(
                should=[
                    models.FieldCondition(
                        key="source_context.domain",
                        match=models.MatchText(text="test"),
                    ),
                    models.FieldCondition(
                        key="source_context.domain",
                        match=models.MatchText(text="domain_0"),
                    ),
                ]
            )
        ),
    )

    print(f"Migrated {len(test_patterns)} test patterns to test_patterns collection")
```

### Solution 3: Transform Raw Code Data (LONG-TERM - 1 day)

**As documented in main investigation report**, implement metadata extraction from raw code:

1. Extract pattern name from file path
2. Extract description from docstrings
3. Infer node types from file naming
4. Extract domain/service from path structure
5. Calculate confidence scores

**See**: `PATTERN_DATA_INVESTIGATION_REPORT.md` for detailed implementation

---

## 📋 Action Plan

### Immediate (Today - 30 minutes)

1. ✅ **Filter test patterns** in `pattern_extraction_handler.py`
   - Add `must_not` filter for "domain_0" and "test*"
   - Test queries to verify no synthetic data returned

2. ✅ **Verify in manifest**
   - Generate manifest and check pattern section
   - Confirm no "domain_0" or "service_0" values

### Short-term (This Week - 2 hours)

3. **Migrate test patterns** to separate collection
   - Create `test_patterns` collection
   - Move all test data out of production collection
   - Update tests to use new collection

4. **Clean up code_generation_patterns**
   - Remove any remaining test data
   - Document expected schema

### Long-term (Next Sprint - 1 day)

5. **Implement metadata extraction**
   - Add helper methods to extract metadata from raw code
   - Transform file paths to meaningful pattern names
   - Extract domain/service from path structure

6. **Create enriched_patterns collection**
   - LLM-based code analysis for descriptions
   - Quality scoring for confidence values
   - Semantic use case extraction

---

## 🎯 Success Metrics

### Immediate Success (Filter Test Data):
- ✅ Zero patterns with "domain_0" or "service_0" in manifest
- ✅ All patterns have real file paths or meaningful names
- ✅ Query performance unchanged (<1500ms)

### Short-term Success (Separate Collections):
- ✅ Clean production collection with only real patterns
- ✅ Test collection for development work
- ✅ Clear documentation of collection purposes

### Long-term Success (Metadata Extraction):
- ✅ Pattern names extracted from file paths (e.g., "Prompt Service Pattern")
- ✅ Descriptions from code docstrings
- ✅ Node types inferred correctly (EFFECT, COMPUTE, etc.)
- ✅ Real domains/services from path analysis

---

## 📁 Files to Modify

### Immediate (Filter)

1. **`/Volumes/PRO-G40/Code/omniarchon/services/intelligence/src/handlers/operations/pattern_extraction_handler.py`**
   - Line 168: Add filter for test patterns
   - Estimated time: 15 minutes

### Short-term (Migration)

2. **Create**: `/Volumes/PRO-G40/Code/omniarchon/scripts/migrate_test_patterns.py`
   - Migration script to move test data
   - Estimated time: 1 hour

### Long-term (Metadata Extraction)

3. **`/Volumes/PRO-G40/Code/omniarchon/services/intelligence/src/handlers/operations/pattern_extraction_handler.py`**
   - Lines 178-196: Implement metadata extraction helpers
   - Estimated time: 3-4 hours

---

## 🔎 Additional Findings

### Test Pattern Examples Found:

1. **"ONEX NodeService0Effect class pattern"**
   - Domain: "domain_0"
   - Service: "service_0"
   - Confidence: 0.9
   - **SYNTHETIC TEST DATA**

2. **"Private methods naming pattern"**
   - Domain: "test_1"
   - Service: "cleanup_test_2_1"
   - Confidence: 0.75
   - **SYNTHETIC TEST DATA**

3. **"ONEX NodeUserManagementEffect class pattern"**
   - Domain: "identity"
   - Service: "user_management"
   - Confidence: 0.9
   - **REAL PATTERN** (from stress testing)

### Pattern Distribution (from logs):

- 23x Dependency injection pattern
- 16x ONEX NodeUserManagementEffect class pattern
- 3x Parallel orchestration pattern
- 3x ONEX NodeCsvJSONTransformerCompute class pattern
- 2x ONEX NodeAnalyticsAggregatorReducer class pattern
- **1x ONEX NodeService0Effect class pattern** ← TEST PATTERN
- 1x ONEX NodeWorkflowCoordinatorOrchestrator class pattern
- 1x ONEX NodeTransformerCompute class pattern

**Only 1 out of 50 patterns is synthetic test data**, but it's visible enough to cause confusion.

---

## 📊 Impact Assessment

### Current Impact:
- ⚠️ **Low visibility** but **high confusion** when synthetic data appears
- ⚠️ Test patterns dilute pattern quality signals
- ⚠️ Inconsistent schema causes transformation errors

### Post-Fix Impact:
- ✅ **Zero synthetic data** in production queries
- ✅ **Consistent schema** enables reliable transformations
- ✅ **Clean separation** between test and production data

---

## 🚀 Quick Start

**To implement the immediate fix (15 minutes)**:

```bash
# 1. Open pattern extraction handler
code /Volumes/PRO-G40/Code/omniarchon/services/intelligence/src/handlers/operations/pattern_extraction_handler.py

# 2. Find line 168 (filter_conditions = [])
# 3. Add test data filter (see Solution 1 above)
# 4. Test query
python3 -c "
from agents.lib.intelligence_event_client import IntelligenceEventClient
import asyncio

async def test():
    client = IntelligenceEventClient()
    await client.start()
    patterns = await client.request_pattern_discovery('*.py', 'python', timeout_ms=5000)

    # Verify no synthetic data
    for pattern in patterns[:10]:
        name = pattern.get('name', 'Unknown')
        domain = pattern.get('source_context', {}).get('domain', 'N/A')
        service = pattern.get('source_context', {}).get('service_name', 'N/A')
        print(f'{name} | Domain: {domain} | Service: {service}')

    await client.stop()

asyncio.run(test())
"

# 5. Verify no "domain_0" or "test" domains appear
```

---

**For detailed implementation guide, see**: `PATTERN_DATA_INVESTIGATION_REPORT.md`

**Status**: ✅ Investigation complete, solution ready for implementation
