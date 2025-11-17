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

#### --detailed

Controls the level of detail in collection statistics:

**Standard output** (default):
- Uses cached collection summary data
- Returns basic collection names and vector counts
- Faster execution (single query)
- Best for quick status checks

**Detailed output** (with --detailed flag):
- Queries each collection individually
- Returns comprehensive per-collection metrics:
  - Vector counts (total and indexed)
  - Collection health status
  - Indexing progress
- Slower execution (one query per collection)
- Best for troubleshooting or detailed analysis

**Usage examples**:
```bash
# Quick status check (standard)
python3 ~/.claude/skills/system-status/check-pattern-discovery/execute.py

# Comprehensive analysis (detailed)
python3 ~/.claude/skills/system-status/check-pattern-discovery/execute.py --detailed
```

## Example Output

**Standard output** (without --detailed):
```json
{
  "total_patterns": 15689,
  "collection_count": 4,
  "collections": {
    "archon_vectors": {"vectors": 7118},
    "code_generation_patterns": {"vectors": 8571}
  }
}
```

**Detailed output** (with --detailed):

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
