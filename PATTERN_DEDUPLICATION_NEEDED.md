# Pattern Deduplication Issue

**Date**: 2025-11-06
**Status**: ✅ FIXED (2025-11-07)

## Problem

The manifest injection system shows duplicate patterns, wasting tokens:

```
• Private methods naming pattern (75% confidence) - EFFECT
• Private methods naming pattern (75% confidence) - EFFECT
• Private methods naming pattern (75% confidence) - EFFECT
... (8 times total)
```

## Root Causes

1. **Pattern extraction extracts duplicates** - Same pattern extracted from multiple files
2. **No deduplication in manifest formatting** - Patterns displayed as-is without grouping
3. **Useless generic patterns** - Extracting basic Python conventions (private methods, exception handling)

## Actions Taken (2025-11-06)

### ✅ Cleanup: Deleted 785 useless patterns from Qdrant

**Deleted categories:**
- Generic naming patterns ("Private methods naming pattern")
- Generic exception handling ("Typed exception handling")
- ONEX naming conventions (too generic)
- Test data patterns (domain: test, service: test_*)
- Stress test patterns (domain: stress_*)

**Script**: `clean_patterns.py` (deleted 709 in bulk, 76 initial batch)

### Remaining: ~50 useful patterns
- Dependency injection (23x from different services - needs deduplication!)
- ONEX Node* class patterns (specific: UserManagementEffect, CsvJSONTransformerCompute)
- Parallel orchestration pattern
- Real domain context: identity, data_processing, analytics

## Solution Needed

### Immediate Fix (Manifest Formatting)

**Location**: `agents/lib/manifest_injector.py` OR `omniarchon/services/intelligence/src/handlers/manifest_intelligence_handler.py`

**Add deduplication in pattern formatting:**

```python
def _format_patterns_deduplicated(patterns: List[Dict]) -> str:
    """Deduplicate patterns by (name, confidence, description)."""

    # Group patterns
    pattern_groups = {}
    for p in patterns:
        key = (p['name'], p.get('confidence', 0), p.get('description', ''))
        if key not in pattern_groups:
            pattern_groups[key] = {
                'pattern': p,
                'count': 0,
                'node_types': set(),
                'domains': set(),
                'services': set()
            }

        group = pattern_groups[key]
        group['count'] += 1
        group['node_types'].update(p.get('node_types', []))

        source = p.get('source_context', {})
        if source.get('domain'):
            group['domains'].add(source['domain'])
        if source.get('service_name'):
            group['services'].add(source['service_name'])

    # Format output
    output = []
    for (name, confidence, description), group in pattern_groups.items():
        output.append(f"• {name} ({confidence} confidence)")
        if group['count'] > 1:
            output.append(f"  Found in: {group['count']} services")
            output.append(f"  Domains: {', '.join(sorted(group['domains']))}")
        output.append(f"  Node types: {', '.join(sorted(group['node_types']))}")
        if description:
            output.append(f"  Description: {description}")

    return "\n".join(output)
```

### Long-term Fix (Pattern Extraction)

**Location**: Pattern ingestion system in `omniarchon`

**Improvements needed:**
1. Extract meaningful architectural patterns, not basic Python conventions
2. Include actual code snippets (20-50 lines)
3. Include file path and line numbers
4. Filter out test/stress test data during ingestion
5. Add pattern quality scoring

**Example useful pattern:**
```python
{
    "pattern_name": "Event Bus Publisher with Retry Logic",
    "confidence": 0.9,
    "source_file": "agents/lib/event_publisher.py",
    "source_lines": "45-78",
    "code_snippet": "async def publish_with_retry(...): ...",
    "description": "Publishes events with exponential backoff retry",
    "use_cases": ["Critical event delivery", "Kafka publishing", "Fault tolerance"]
}
```

## Impact

**Before cleanup:**
- 76% of patterns were useless
- Manifests wasted 2000-3000 tokens on duplicates
- Agents received no useful pattern information

**After cleanup:**
- Only useful patterns remain
- Still need deduplication (23x dependency injection)
- Token waste reduced but not eliminated

## Next Steps

1. ✅ Delete useless patterns (DONE - 785 deleted)
2. ✅ Add deduplication in manifest formatter (DONE - 2025-11-07)
3. ⏳ Fix pattern extraction system (TODO - omniarchon)
4. ⏳ Add pattern quality gates (TODO)

## Files to Modify

1. `agents/lib/manifest_injector.py` - Add `_format_patterns_deduplicated()`
2. `omniarchon/services/intelligence/src/handlers/manifest_intelligence_handler.py` - May need updates
3. Pattern ingestion system in omniarchon - Quality filters

## Success Criteria

- [x] No duplicate patterns in manifests (grouped by name with instance count)
- [x] Token usage reduced by >50% for pattern section (93% reduction in test: 575 → 40 tokens)
- [ ] Only meaningful patterns with real code examples (depends on omniarchon improvements)
- [ ] Pattern quality score >0.7 (depends on omniarchon quality gates)

---

## Implementation Summary (2025-11-07)

### Changes Made

**File**: `agents/lib/manifest_injector.py`

1. **Enhanced `_deduplicate_patterns()` method** (lines 3455-3529):
   - Groups patterns by name
   - Tracks instance count for each pattern name
   - Keeps highest confidence version as representative
   - Aggregates metadata from all instances:
     - `all_node_types` - All node types across instances
     - `all_domains` - All domains where pattern appears
     - `all_services` - All services using the pattern
     - `all_files` - All file paths containing the pattern
   - Adds `instance_count` field to each deduplicated pattern

2. **Updated `_format_patterns_result()` method** (lines 3531-3569):
   - Passes through enhanced metadata fields to the `available` list
   - Includes `instance_count`, `all_node_types`, `all_domains`, `all_services`, `all_files`

3. **Updated `_format_patterns()` method** (lines 3818-3893):
   - Displays instance count for multi-instance patterns
   - Shows aggregated node types from all instances
   - Shows domains for multi-instance patterns
   - Shows file count for multi-instance patterns
   - Example output:
     ```
     • Dependency Injection (80% confidence) [23 instances]
       Node Types: COMPUTE, EFFECT
       Domains: analytics, data_processing, identity
       Files: 23 files across services
     ```

### Test Results

**Test Script**: `test_pattern_deduplication.py`

✅ **Test 1 (Basic deduplication)**: 4 patterns → 2 unique (2 duplicates removed)
✅ **Test 2 (No duplicates)**: 2 patterns → 2 unique (0 duplicates removed)
✅ **Test 3 (Many duplicates)**: 23 patterns → 1 unique (22 duplicates removed)
✅ **Test 4 (Token savings)**: 93% reduction (575 → 40 tokens)

### Benefits

1. **Massive token reduction**: 93% reduction for heavily duplicated patterns (575 → 40 tokens)
2. **Better readability**: No repetitive pattern listings, grouped by name with count
3. **Richer context**: Shows domains and node types across all instances
4. **Maintains quality**: Still keeps highest confidence version as representative
5. **Backward compatible**: Single-instance patterns display normally

### Next Steps (Omniarchon)

The following improvements require changes in the `omniarchon` repository:

1. **Pattern quality filters** during ingestion (prevent generic patterns from being stored)
2. **Code snippets** (20-50 lines) with line numbers
3. **Pattern scoring** based on usefulness and specificity
4. **Enhanced metadata** during extraction (domain, service, use cases)
