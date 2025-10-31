# Filesystem Manifest Feature

## Overview

The filesystem manifest feature provides agents with complete visibility into the project file structure, preventing duplicate file creation and providing context-aware file navigation.

## Implementation

**Added**: 2025-10-27
**File**: `agents/lib/manifest_injector.py`
**Status**: ✅ Fully Implemented and Tested

## Features

### 1. Filesystem Tree Scanning

- **Recursive directory traversal** up to 5 levels deep
- **Smart filtering** of ignored directories (.git, node_modules, __pycache__, etc.)
- **File metadata collection** (size, modified time, extension)
- **ONEX node type detection** (Effect, Compute, Reducer, Orchestrator)

### 2. Performance

- **Query time**: ~23ms average (well under 500ms target)
- **Local operation**: No dependency on external intelligence services
- **Cached results**: 5-minute TTL for efficiency

### 3. Output Format

The filesystem section in the manifest includes:

```
FILESYSTEM STRUCTURE:
  Root: /Volumes/PRO-G40/Code/omniclaude
  Total Files: 1062
  Total Directories: 156
  Total Size: 1235.1MB

  Key Directories:
    agents/ (25 files, 12 subdirs)
    claude_hooks/ (76 files, 10 subdirs)
    docs/ (36 files, 8 subdirs)
    ...

  File Types:
    .py: 498 files
    .md: 261 files
    .yaml: 116 files
    ...

  ONEX Compliance:
    EFFECT nodes: 3 files
    COMPUTE nodes: 2 files
    REDUCER nodes: 2 files
    ORCHESTRATOR nodes: 2 files

  ⚠️  DUPLICATE PREVENTION GUIDANCE:
  Before creating new files, check if similar files exist in:
    • agents/ - Agent implementations and patterns
    • lib/ - Library modules and utilities
    • tests/ - Test files
    • claude_hooks/ - Hook scripts
    • Root *.md files - Documentation

  💡 TIP: Use Glob or Grep tools to search for existing files
       before creating duplicates with similar names or purposes.
```

## Architecture

### Query Method: `_query_filesystem()`

```python
async def _query_filesystem(
    self,
    client: IntelligenceEventClient,
    correlation_id: str,
) -> Dict[str, Any]:
    """
    Query filesystem tree and metadata.

    Returns:
        {
            "root_path": str,
            "file_tree": List[Dict],
            "total_files": int,
            "total_directories": int,
            "total_size_bytes": int,
            "file_types": Dict[str, int],
            "onex_files": Dict[str, List[str]],
            "query_time_ms": int,
        }
    """
```

### Formatting Method: `_format_filesystem()`

```python
def _format_filesystem(self, filesystem_data: Dict) -> str:
    """
    Format filesystem section for manifest display.

    Includes:
    - Summary statistics (files, directories, size)
    - Key directories with file counts
    - File types breakdown
    - ONEX compliance summary
    - Duplicate prevention guidance
    """
```

### Integration Points

1. **Parallel Query Execution**: Filesystem query runs alongside other manifest queries
2. **Always Enabled**: Works even when intelligence services are disabled
3. **Cache Support**: Results cached with 5-minute TTL
4. **Database Storage**: Filesystem counts tracked in manifest injection records

## Testing

### Test Files

- `agents/lib/test_filesystem_manifest.py` - Basic functionality test
- `agents/lib/test_filesystem_integration.py` - Comprehensive integration tests

### Test Results

```
✅ PASS: Minimal Manifest Integration
✅ PASS: Performance (avg: 23.0ms < 500ms)
✅ PASS: Caching
✅ PASS: ONEX Detection (9 files detected)
✅ PASS: Duplicate Prevention

Results: 5/5 tests passed
```

## Performance Metrics

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Query Time | <500ms | ~23ms | ✅ Excellent |
| File Detection | All non-ignored | 1062 files | ✅ Complete |
| Directory Depth | 5 levels | 5 levels | ✅ Correct |
| ONEX Detection | All node types | 9 files detected | ✅ Accurate |

## Usage

### In Agent Code

The filesystem section is automatically included in all manifest injections:

```python
from manifest_injector import ManifestInjector

injector = ManifestInjector()
manifest = injector.generate_dynamic_manifest(correlation_id)
formatted = injector.format_for_prompt()

# Filesystem data available in manifest["filesystem"]
filesystem = manifest["filesystem"]
print(f"Total files: {filesystem['total_files']}")
```

### In Agent Prompts

Agents receive the filesystem structure in their system manifest:

```
FILESYSTEM STRUCTURE:
  Root: /path/to/project
  Total Files: 1062
  ...
```

This helps agents:
1. **Avoid creating duplicate files**
2. **Navigate existing code structure**
3. **Find ONEX-compliant implementations**
4. **Understand project organization**

## Benefits

### 1. Duplicate File Prevention

Agents can check if similar files exist before creating new ones:
- Pattern files in `agents/lib/patterns/`
- Test files in `agents/tests/`
- Hook scripts in `claude_hooks/`
- Documentation in `docs/` or root `*.md` files

### 2. Context-Aware Development

Agents understand:
- Project size and complexity
- File organization patterns
- ONEX compliance coverage
- Common file locations

### 3. Improved Navigation

Agents can:
- Locate existing implementations
- Find related files by type
- Understand directory purposes
- Navigate to appropriate locations

## Configuration

### Ignored Paths

Default ignored directories:
- `.git`, `.venv`, `node_modules`
- `__pycache__`, `.pytest_cache`, `.mypy_cache`
- `dist`, `build`, `.egg-info`
- `.DS_Store`

### Ignored Extensions

Default ignored file extensions:
- `.pyc`, `.pyo`, `.pyd`
- `.so`, `.dylib`, `.dll`
- `.exe`

### Cache Configuration

```python
# Default TTL: 5 minutes
"filesystem": default_ttl_seconds,  # 300 seconds

# Can be overridden via environment variable:
MANIFEST_CACHE_TTL_SECONDS=600  # 10 minutes
```

## Database Schema

The `agent_manifest_injections` table tracks filesystem data:

```sql
-- Additional columns for filesystem tracking
filesystem_files_count INTEGER,
filesystem_directories_count INTEGER
```

## Future Enhancements

### Potential Improvements

1. **File Content Indexing**: Index file purposes/descriptions from docstrings
2. **Change Detection**: Track file modifications since last manifest generation
3. **Smart Recommendations**: Suggest similar files based on name patterns
4. **Git Integration**: Show uncommitted/untracked files
5. **Semantic Search**: Use embeddings to find related files by purpose

### Performance Optimizations

1. **Incremental Updates**: Only re-scan changed directories
2. **Parallel Scanning**: Use multiple threads for large projects
3. **Selective Depth**: Adjust max depth based on project size
4. **Smart Caching**: Invalidate cache only for changed paths

## Troubleshooting

### Issue: Filesystem query slow (>500ms)

**Diagnosis**:
```bash
python3 agents/lib/test_filesystem_integration.py
# Check "TEST 2: Filesystem Query Performance"
```

**Solutions**:
1. Reduce max depth from 5 to 3 levels
2. Add more directories to ignored list
3. Check for large binary files being scanned

### Issue: ONEX files not detected

**Diagnosis**:
```python
# Check onex_files in manifest
filesystem = manifest["filesystem"]
print(filesystem.get("onex_files"))
```

**Solutions**:
1. Verify file naming follows pattern: `*_effect.py`, `*_compute.py`, etc.
2. Check files are not in ignored directories
3. Verify files are within max depth (5 levels)

### Issue: Filesystem section missing from manifest

**Diagnosis**:
```python
# Check if filesystem key exists
print("filesystem" in manifest)
```

**Solutions**:
1. Ensure latest `manifest_injector.py` version
2. Check logs for filesystem query errors
3. Verify working directory is accessible

## Version History

- **2025-10-27**: Initial implementation
  - Filesystem tree scanning
  - ONEX node type detection
  - Duplicate prevention guidance
  - Performance optimization (<25ms average)
  - Comprehensive test suite

## References

- **Implementation**: `agents/lib/manifest_injector.py` (lines 1096-1320)
- **Format Method**: `agents/lib/manifest_injector.py` (lines 1850-1964)
- **Tests**: `agents/lib/test_filesystem_*.py`
- **Documentation**: `/Volumes/PRO-G40/Code/omniclaude/CLAUDE.md` (Manifest Integration section)
