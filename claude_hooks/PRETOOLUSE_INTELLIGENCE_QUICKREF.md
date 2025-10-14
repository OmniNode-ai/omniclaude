# PreToolUse Intelligence - Quick Reference

## What It Does

Captures **why** Claude selected a tool and what alternatives were considered, with sub-millisecond performance overhead.

## Enhanced Metadata Captured

### 1. Tool Selection
```json
{
  "tool_chosen": "Write",
  "selection_reason": "file_creation_required",
  "alternative_tools_considered": [
    {
      "tool": "Edit",
      "reason_not_used": "full_rewrite_preferred"
    }
  ]
}
```

### 2. Context Information
```json
{
  "file_exists": false,
  "file_writable": true,
  "directory_exists": true,
  "file_extension": ".py"
}
```

### 3. Execution Expectations
```json
{
  "expected_path": "create_new_file",
  "estimated_time_ms": 50,
  "expected_side_effects": ["file_created", "disk_write"]
}
```

### 4. Quality Checks
```json
{
  "checks_passed": ["syntax_validation"],
  "checks_warnings": ["missing_docstring"],
  "checks_failed": ["naming_convention"],
  "violations_found": 3,
  "corrections_suggested": 2,
  "enforcement_mode": "warn"
}
```

### 5. Performance
```json
{
  "analysis_time_ms": 0.54
}
```

## Selection Reasons by Tool

| Tool | Reason |
|------|--------|
| Write (new) | `file_creation_required` |
| Write (existing) | `file_overwrite_required` |
| Edit | `file_modification_required` |
| Edit (targeted) | `targeted_string_replacement` |
| Read | `information_gathering` |
| Bash (git) | `version_control_operation` |
| Bash (npm/pip) | `package_management` |
| Bash (pytest) | `test_execution` |
| Bash (other) | `command_execution_required` |
| Glob | `file_pattern_matching` |
| Grep | `content_search_required` |
| NotebookEdit | `notebook_cell_modification` |

## Alternative Tools Logic

| Tool Used | Suggests | Reason Not Used |
|-----------|----------|-----------------|
| Write (on existing file) | Edit | `full_rewrite_preferred_over_partial_edit` |
| Edit | Write | `targeted_edit_preferred_over_full_rewrite` |
| Bash (cat) | Read | `command_output_needed_not_raw_file` |
| Bash (find) | Glob | `complex_find_logic_required` |
| Bash (grep) | Grep | `command_line_grep_preferred` |
| Read | Bash | `direct_read_more_efficient_than_cat` |
| Glob | Bash | `glob_pattern_simpler_than_find` |
| Grep | Bash | `structured_grep_preferred_over_command` |

## Database Queries

### Query tool selection patterns
```sql
SELECT
    payload->'enhanced_metadata'->'tool_selection'->>'selection_reason' as reason,
    COUNT(*) as count
FROM hook_events
WHERE source = 'PreToolUse'
GROUP BY reason
ORDER BY count DESC;
```

### Query alternative tools considered
```sql
SELECT
    resource_id as tool,
    jsonb_array_elements(
        payload->'enhanced_metadata'->'tool_selection'->'alternative_tools_considered'
    )->>'tool' as alternative
FROM hook_events
WHERE source = 'PreToolUse'
    AND payload->'enhanced_metadata'->'tool_selection'->'alternative_tools_considered' != '[]'::jsonb;
```

### Query quality check failures
```sql
SELECT
    payload->'enhanced_metadata'->'quality_checks' as quality,
    COUNT(*) as count
FROM hook_events
WHERE source = 'PreToolUse'
    AND (payload->'enhanced_metadata'->'quality_checks'->>'violations_found')::int > 0
GROUP BY quality
ORDER BY count DESC;
```

### Performance analysis
```sql
SELECT
    resource_id as tool,
    AVG((payload->'enhanced_metadata'->'performance'->>'analysis_time_ms')::float) as avg_ms,
    MIN((payload->'enhanced_metadata'->'performance'->>'analysis_time_ms')::float) as min_ms,
    MAX((payload->'enhanced_metadata'->'performance'->>'analysis_time_ms')::float) as max_ms
FROM hook_events
WHERE source = 'PreToolUse'
    AND payload->'enhanced_metadata'->'performance'->>'analysis_time_ms' IS NOT NULL
GROUP BY resource_id
ORDER BY avg_ms DESC;
```

## Testing

```bash
# Run full test suite
cd /Users/jonah/.claude/hooks
python3 test_enhanced_metadata.py

# Test specific tool
python3 -c "
from lib.tool_selection_intelligence import ToolSelectionIntelligence
intelligence = ToolSelectionIntelligence()
result = intelligence.analyze_tool_selection(
    'Write',
    {'file_path': '/tmp/test.py', 'content': 'test'}
)
print(f'Reason: {result.selection_reason}')
print(f'Time: {result.analysis_time_ms:.2f}ms')
"
```

## Performance Benchmarks

**Target**: <10ms per analysis
**Achieved**: 0.07ms average (142x faster)

| Tool | Time |
|------|------|
| Write (new) | 0.54ms |
| Write (existing) | 0.05ms |
| Edit | 0.03ms |
| Bash | 0.00-0.01ms |
| Read | 0.03ms |
| Glob | 0.01ms |
| Grep | 0.00ms |

## Integration Points

1. **PreToolUse Hook** (`pre-tool-use-quality.sh`)
   - Invokes quality_enforcer.py
   - Extracts enhanced metadata from result
   - Logs to database via hook_event_logger.py

2. **Quality Enforcer** (`quality_enforcer.py`)
   - Captures tool selection at workflow start
   - Updates quality check metadata after validation
   - Returns enhanced metadata in output

3. **Database Logger** (`lib/hook_event_logger.py`)
   - Stores enhanced metadata in JSONB payload
   - No changes required (existing structure supports it)

## Key Files

- `/Users/jonah/.claude/hooks/lib/tool_selection_intelligence.py` - Intelligence module
- `/Users/jonah/.claude/hooks/quality_enforcer.py` - Integration
- `/Users/jonah/.claude/hooks/pre-tool-use-quality.sh` - Hook script
- `/Users/jonah/.claude/hooks/test_enhanced_metadata.py` - Test suite

## Example Output

```
[Intelligence] Tool selection captured: Write
  (reason: file_creation_required, analysis: 0.54ms)
[Intelligence] Quality checks updated:
  1 passed, 0 warnings, 0 failed
```

## Troubleshooting

**Issue**: High analysis time (>5ms)
- Check file system performance
- Verify no network calls in context gathering

**Issue**: Missing alternatives
- Review `_get_alternative_tools()` logic
- Check context_info for expected fields

**Issue**: Wrong selection reason
- Update `_infer_selection_reason()` heuristics
- Add new patterns to TOOL_REASONS mapping

**Issue**: Database not logging metadata
- Verify enhanced_metadata in hook output JSON
- Check bash hook extraction logic
- Verify JSONB column in hook_events table
