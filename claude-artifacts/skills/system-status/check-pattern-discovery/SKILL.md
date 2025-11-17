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
