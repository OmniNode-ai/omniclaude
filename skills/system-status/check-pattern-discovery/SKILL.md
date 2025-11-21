---
name: check-pattern-discovery
description: Qdrant pattern collections status, vector counts, and pattern retrieval performance
---

# Check Pattern Discovery

Monitor Qdrant pattern collections and discovery performance.

## What It Checks

- Collection sizes and vector counts
- Recent pattern retrievals
- Pattern quality distribution
- Collection health status
- Search performance

## How to Use

```bash
python3 ~/.claude/skills/system-status/check-pattern-discovery/execute.py
```

### Arguments

- `--detailed`: Include collection-specific statistics

## Exit Codes

- **0**: Healthy - Pattern discovery working normally
- **1**: Degraded - Performance issues or warnings
- **2**: Critical - Cannot access Qdrant or other critical failure

## Example Output

```json
{
  "collections": {
    "archon_vectors": {
      "vectors": 7118,
      "status": "green",
      "indexed_vectors": 7118
    },
    "code_generation_patterns": {
      "vectors": 8571,
      "status": "green",
      "indexed_vectors": 8571
    }
  },
  "total_patterns": 15689,
  "collection_count": 4
}
```

## Prerequisites

- Qdrant must be running and accessible
- Collections must exist (archon_vectors, code_generation_patterns)

## Collection Status Values

- **green**: Collection is healthy and fully operational
- **yellow**: Collection is operational but may have warnings
- **red**: Collection has critical issues or is unavailable

## Output Format & Exit Codes

For complete details on output structures, exit codes, field standards, and examples, see:

**[Output Format Specification](../OUTPUT_FORMAT_SPECIFICATION.md)**

This includes:
- Detailed JSON schema and field descriptions
- All exit code scenarios with examples
- Status value conventions and indicators
- Error response formats
- Edge case handling
