# Pattern Deduplication Issue

**Date**: 2025-11-06
**Status**: Identified, Needs Fix

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
2. ⏳ Add deduplication in manifest formatter (TODO)
3. ⏳ Fix pattern extraction system (TODO - omniarchon)
4. ⏳ Add pattern quality gates (TODO)

## Files to Modify

1. `agents/lib/manifest_injector.py` - Add `_format_patterns_deduplicated()`
2. `omniarchon/services/intelligence/src/handlers/manifest_intelligence_handler.py` - May need updates
3. Pattern ingestion system in omniarchon - Quality filters

## Success Criteria

- [ ] No duplicate patterns in manifests
- [ ] Token usage reduced by >50% for pattern section
- [ ] Only meaningful patterns with real code examples
- [ ] Pattern quality score >0.7
