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
python3 ./check-pattern-discovery/execute.py
```

### Arguments

- `--detailed`: Include collection-specific statistics

## Output Formats

### Non-Detailed Mode (Default)

Returns basic collection statistics with full field names. Suitable for programmatic parsing and data processing.

```bash
python3 ./check-pattern-discovery/execute.py
```

**JSON Structure**:
```json
{
  "success": true,
  "total_patterns": 15689,
  "collection_count": 4,
  "collections": {
    "archon_vectors": {
      "vectors_count": 7118,
      "indexed_vectors_count": 7118,
      "status": "green"
    },
    "code_generation_patterns": {
      "vectors_count": 8571,
      "indexed_vectors_count": 8571,
      "status": "green"
    },
    "archon-intelligence": {
      "vectors_count": 0,
      "indexed_vectors_count": 0,
      "status": "green"
    },
    "quality_vectors": {
      "vectors_count": 0,
      "indexed_vectors_count": 0,
      "status": "green"
    }
  },
  "timestamp": "2025-11-21T14:30:00.123456+00:00"
}
```

**Fields**:
- `success` (boolean): Whether the operation succeeded
- `total_patterns` (integer): Sum of all vectors across collections
- `collection_count` (integer): Number of collections found
- `collections` (object): Per-collection statistics with full field names
  - `vectors_count` (integer): Total vectors in collection
  - `indexed_vectors_count` (integer): Vectors that are indexed
  - `status` (string): Collection health status ("green", "yellow", "red")
- `timestamp` (string): ISO 8601 timestamp in UTC

**When to use**: Scripts, automation, data pipelines, JSON parsing

### Detailed Mode

Returns collection statistics with simplified field names for better readability. Suitable for human consumption and dashboards.

```bash
python3 ./check-pattern-discovery/execute.py --detailed
```

**JSON Structure**:
```json
{
  "success": true,
  "total_patterns": 15689,
  "collection_count": 4,
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
    },
    "archon-intelligence": {
      "vectors": 0,
      "status": "green",
      "indexed_vectors": 0
    },
    "quality_vectors": {
      "vectors": 0,
      "status": "green",
      "indexed_vectors": 0
    }
  },
  "timestamp": "2025-11-21T14:30:00.123456+00:00"
}
```

**Fields**:
- `success` (boolean): Whether the operation succeeded
- `total_patterns` (integer): Sum of all vectors across collections
- `collection_count` (integer): Number of collections found
- `collections` (object): Per-collection statistics with simplified field names
  - `vectors` (integer): Total vectors in collection
  - `indexed_vectors` (integer): Vectors that are indexed
  - `status` (string): Collection health status ("green", "yellow", "red")
- `timestamp` (string): ISO 8601 timestamp in UTC

**When to use**: Human-readable output, dashboards, reports, debugging

### Error Response Format

When an error occurs (Qdrant unreachable, connection timeout, etc.):

```json
{
  "success": false,
  "error": "Connection error: Not Found",
  "timestamp": "2025-11-21T14:30:00.123456+00:00"
}
```

**Fields**:
- `success` (boolean): Always `false` for errors
- `error` (string): Error description
- `timestamp` (string): ISO 8601 timestamp in UTC

## Exit Codes

Exit codes enable reliable scripting and automation:

- **0**: Success - Pattern collections retrieved successfully
  - All collections accessible
  - Statistics retrieved without errors
  - Qdrant connection healthy

- **1**: Error - Failed to retrieve pattern statistics
  - Qdrant connection failed (unreachable, timeout, refused)
  - Collection query error (invalid response, permission denied)
  - Network error or configuration issue
  - Check `error` field in JSON output for details
