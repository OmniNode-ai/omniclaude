# Pattern System Fix Plan

**Created**: 2025-10-28
**Priority**: HIGH (blocking MVP quality)
**Estimated Effort**: 3-4 weeks

## Executive Summary

**Problem**: The pattern system is tracking FILES instead of CODE PATTERNS, making the dashboard data useless.

**Current State**:
- 1,259 "patterns" in database (all are filenames like `__init__.py`, `model_complex_filter.py`)
- Pattern relationships show file imports, not code pattern usage
- Quality scores hardcoded to 0.85 (mock data)
- Usage counts hardcoded to 1 (not tracked)
- Dashboard Pattern Learning page shows meaningless file list

**Impact**:
- Developers cannot discover reusable patterns
- Dashboard provides zero value for pattern learning
- Pattern analytics are misleading
- Knowledge graph shows file dependencies, not design patterns

**Solution**: Implement AST-based code pattern extraction to capture actual functions, classes, and design patterns from source code.

---

## Problem Analysis

### Issue 1: File Tracking Instead of Pattern Extraction

**What's Happening**:
```sql
-- Current database content (WRONG):
SELECT pattern_name FROM pattern_lineage_nodes LIMIT 5;

pattern_name
------------------
__init__.py
typed_dict_discovery_stats.py
model_complex_filter.py
model_argument_value.py
tree_stamping_events.py
```

**What Should Happen**:
```sql
-- Desired database content (RIGHT):
pattern_name                              pattern_type        quality  usage
---------------------------------------- ------------------- -------- -----
Async Database Transaction with Retry    function_pattern    0.92     15
Singleton Pattern using Metaclass        class_pattern       0.88     8
Event Publisher Pattern with Kafka       design_pattern      0.91     23
CRUD Repository Pattern                  class_pattern       0.85     12
Validation Decorator with Type Checking  function_pattern    0.79     6
```

**Root Cause**: Pattern ingestion pipeline extracts file metadata instead of parsing code.

**Location**: Need to investigate:
- `/Volumes/PRO-G40/Code/Omniarchon/services/intelligence/` - Pattern ingestion
- Database table: `pattern_lineage_nodes`

### Issue 2: Pattern Relationships

**Current**: Shows file import graph (not useful)
**Should Be**: Shows code pattern usage graph

Example desired relationship:
- "CRUD Pattern" → USES → "Database Transaction Pattern"
- "Event Publisher" → USES → "Validation Decorator"
- "Factory Method" → CREATES → "ONEX Effect Nodes"

### Issue 3: Mock Quality Scores

**Current**: All patterns have quality_score = 0.85 (hardcoded)

**Should Calculate**:
```python
quality_score = (
    complexity_score * 0.3 +      # Cyclomatic complexity < 10
    documentation_score * 0.2 +   # Has docstring + type hints
    test_coverage_score * 0.2 +   # % covered by tests
    reusability_score * 0.15 +    # Used in multiple files
    maintainability_score * 0.15  # Low coupling, high cohesion
)
```

### Issue 4: Usage Not Tracked

**Current**: All patterns show usage_count = 1

**Should Track**:
- How many times pattern appears in manifests
- Which agents use this pattern
- When pattern was last used
- Trend: usage increasing/decreasing

---

## Solution Design

### Phase 1: Pattern Extraction Engine

**Goal**: Parse Python source code and extract actual patterns

**Technology**:
- `ast` module - Parse Python abstract syntax tree
- `radon` - Calculate cyclomatic complexity
- `astroid` - Advanced code analysis

**Pattern Types to Extract**:

1. **Function Patterns**:
   - Async functions with retry logic
   - Validation decorators
   - Error handling wrappers
   - Database transaction managers

2. **Class Patterns**:
   - Singleton implementations
   - Factory patterns
   - Repository patterns
   - CRUD operations
   - ONEX node types (Effect, Compute, Reducer, Orchestrator)

3. **Design Patterns**:
   - Observer/Event patterns
   - Strategy patterns
   - Decorator patterns
   - Context managers

**Example Extraction**:

Input file: `src/database/transaction_manager.py`
```python
async def execute_with_retry(operation, max_attempts=3):
    """Execute database operation with automatic retry on failure."""
    for attempt in range(max_attempts):
        try:
            async with self.transaction():
                result = await operation()
                return result
        except DatabaseError as e:
            if attempt == max_attempts - 1:
                raise
            await asyncio.sleep(2 ** attempt)
```

Output pattern:
```json
{
  "pattern_name": "Async Database Transaction with Retry",
  "pattern_type": "function_pattern",
  "category": "database_operations",
  "file_path": "src/database/transaction_manager.py",
  "line_range": [45, 67],
  "implementation": "...",
  "complexity": 7,
  "quality_score": 0.92,
  "tags": ["async", "database", "retry", "error_handling"],
  "dependencies": ["asyncpg", "asyncio"],
  "docstring": "Execute database operation with automatic retry on failure"
}
```

### Phase 2: Quality Scoring

**Metrics**:

1. **Complexity Score** (30%):
   - Cyclomatic complexity < 10: score = 1.0
   - Complexity 10-20: score = 0.7
   - Complexity > 20: score = 0.4

2. **Documentation Score** (20%):
   - Has docstring: +0.5
   - Has type hints: +0.5

3. **Test Coverage Score** (20%):
   - % of lines covered by tests

4. **Reusability Score** (15%):
   - Used in 1 file: 0.3
   - Used in 2-5 files: 0.6
   - Used in 5+ files: 1.0

5. **Maintainability Score** (15%):
   - Low coupling: +0.5
   - High cohesion: +0.5

### Phase 3: Usage Tracking

**Track From**:
1. Agent manifest injections (patterns referenced)
2. Code generation outputs (patterns applied)
3. Import analysis (patterns imported)

**Database Schema**:
```sql
ALTER TABLE pattern_lineage_nodes
ADD COLUMN usage_count INTEGER DEFAULT 0,
ADD COLUMN last_used_at TIMESTAMP,
ADD COLUMN used_by_agents TEXT[];
```

**Trigger**:
```sql
CREATE TRIGGER increment_pattern_usage
AFTER INSERT ON agent_manifest_injections
FOR EACH ROW
EXECUTE FUNCTION increment_pattern_usage();
```

### Phase 4: Relationship Building

**Relationship Types**:
- `USES` - Pattern A uses Pattern B
- `EXTENDS` - Pattern A extends Pattern B
- `SIMILAR_TO` - Pattern A similar to Pattern B
- `COMPOSED_OF` - Pattern A composed of Pattern B

**Detection Methods**:
1. Import analysis (what does this import?)
2. Inheritance analysis (what does it extend?)
3. Call analysis (what functions does it call?)
4. Semantic similarity (AST structure similarity)

---

## Implementation Plan

### Week 1: Pattern Extraction Engine

**Deliverable**: Working code pattern extractor

**Tasks**:
1. Create `PatternExtractor` class
2. Implement AST parsing for functions
3. Implement AST parsing for classes
4. Add pattern classification logic
5. Calculate complexity metrics
6. Write unit tests

**Files to Create**:
```
services/intelligence/src/pattern_extraction/
├── __init__.py
├── extractor.py          # Main PatternExtractor class
├── ast_parser.py         # AST parsing utilities
├── classifier.py         # Pattern type classification
├── metrics.py            # Quality metrics calculation
└── tests/
    └── test_extractor.py
```

**Success Criteria**:
- Can parse Python file and extract 5+ patterns
- Correctly identifies function vs class patterns
- Calculates complexity scores

### Week 2: Quality Scoring & Storage

**Deliverable**: Patterns stored with real quality scores

**Tasks**:
1. Implement quality score calculator
2. Create database migrations
3. Update Qdrant schema for vectors
4. Batch pattern ingestion script
5. API endpoint for pattern extraction

**Files to Modify**:
- Add migration `services/intelligence/migrations/XXX_pattern_quality.sql`
- `services/intelligence/src/services/quality/pattern_scorer.py`
- `services/intelligence/src/api/patterns/routes.py`

**Migration**:
```sql
-- Add quality columns
ALTER TABLE pattern_lineage_nodes
ADD COLUMN complexity_score DECIMAL(3,2),
ADD COLUMN documentation_score DECIMAL(3,2),
ADD COLUMN test_coverage_score DECIMAL(3,2),
ADD COLUMN reusability_score DECIMAL(3,2),
ADD COLUMN maintainability_score DECIMAL(3,2),
ADD COLUMN overall_quality DECIMAL(3,2);

-- Update existing rows with calculated scores
UPDATE pattern_lineage_nodes
SET overall_quality = 0.0
WHERE overall_quality IS NULL;
```

### Week 3: Usage Tracking & Relationships

**Deliverable**: Real usage stats and pattern relationships

**Tasks**:
1. Create usage tracking trigger
2. Implement relationship builder
3. Update manifest handler to track usage
4. Build similarity index
5. Create pattern graph API

**Database Changes**:
```sql
-- Add usage tracking
ALTER TABLE pattern_lineage_nodes
ADD COLUMN usage_count INTEGER DEFAULT 0,
ADD COLUMN last_used_at TIMESTAMP,
ADD COLUMN used_by_agents TEXT[];

-- Add relationships table
CREATE TABLE pattern_relationships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_pattern_id UUID REFERENCES pattern_lineage_nodes(id),
  target_pattern_id UUID REFERENCES pattern_lineage_nodes(id),
  relationship_type VARCHAR(50) NOT NULL,
  confidence DECIMAL(3,2),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_pattern_rel_source ON pattern_relationships(source_pattern_id);
CREATE INDEX idx_pattern_rel_target ON pattern_relationships(target_pattern_id);
```

### Week 4: Integration & Re-ingestion

**Deliverable**: Dashboard showing real pattern data

**Tasks**:
1. Backup current database
2. Clear bad file-based patterns
3. Run pattern extraction on entire codebase
4. Ingest real patterns
5. Validate dashboard data
6. Performance optimization
7. Documentation

**Re-ingestion Script**:
```bash
#!/bin/bash
# scripts/reingest_patterns.sh

# Backup
pg_dump -h 192.168.86.200 -p 5436 -U postgres omninode_bridge \
  --table pattern_lineage_nodes > backup_patterns.sql

# Clear bad data
psql -h 192.168.86.200 -p 5436 -U postgres omninode_bridge <<EOF
DELETE FROM pattern_lineage_nodes
WHERE pattern_name LIKE '%__init__%'
   OR pattern_name LIKE '%.py';
EOF

# Extract patterns from codebase
python3 scripts/extract_patterns.py \
  --source /Volumes/PRO-G40/Code \
  --output /tmp/patterns.json \
  --min-quality 0.5

# Ingest to database
python3 scripts/ingest_patterns.py \
  --input /tmp/patterns.json \
  --database omninode_bridge \
  --batch-size 100

# Validate
psql -h 192.168.86.200 -p 5436 -U postgres omninode_bridge <<EOF
SELECT COUNT(*) as total_patterns,
       AVG(overall_quality) as avg_quality,
       COUNT(DISTINCT pattern_type) as pattern_types
FROM pattern_lineage_nodes;
EOF
```

---

## Migration Strategy

### Step 1: Backup (15 minutes)
```bash
# Backup entire database
pg_dump -h 192.168.86.200 -p 5436 -U postgres omninode_bridge \
  > backup_$(date +%Y%m%d).sql

# Backup just patterns table
pg_dump -h 192.168.86.200 -p 5436 -U postgres omninode_bridge \
  --table pattern_lineage_nodes \
  --table pattern_lineage_edges \
  > backup_patterns_$(date +%Y%m%d).sql
```

### Step 2: Schema Migration (30 minutes)
```sql
-- Run all migrations
\i migrations/XXX_pattern_quality.sql
\i migrations/XXX_pattern_usage.sql
\i migrations/XXX_pattern_relationships.sql
```

### Step 3: Data Cleanup (10 minutes)
```sql
-- Delete file-based patterns
BEGIN;
  DELETE FROM pattern_lineage_edges
  WHERE source_id IN (
    SELECT id FROM pattern_lineage_nodes
    WHERE pattern_name LIKE '%.py'
  );

  DELETE FROM pattern_lineage_nodes
  WHERE pattern_name LIKE '%__init__%'
     OR pattern_name LIKE '%.py'
     OR pattern_name LIKE '%test_%';
COMMIT;
```

### Step 4: Pattern Extraction (2-4 hours)
```bash
# Extract from all repositories
python3 scripts/extract_patterns.py \
  --sources \
    /Volumes/PRO-G40/Code/omniclaude \
    /Volumes/PRO-G40/Code/Omniarchon \
    /Volumes/PRO-G40/Code/omnidash \
  --output /tmp/all_patterns.json \
  --min-quality 0.6 \
  --max-complexity 15 \
  --parallel 4
```

### Step 5: Pattern Ingestion (30 minutes)
```bash
python3 scripts/ingest_patterns.py \
  --input /tmp/all_patterns.json \
  --database omninode_bridge \
  --batch-size 100 \
  --skip-duplicates
```

### Step 6: Validation (15 minutes)
```sql
-- Check pattern counts
SELECT pattern_type, COUNT(*) as count
FROM pattern_lineage_nodes
GROUP BY pattern_type;

-- Check quality distribution
SELECT
  CASE
    WHEN overall_quality >= 0.8 THEN 'High'
    WHEN overall_quality >= 0.6 THEN 'Medium'
    ELSE 'Low'
  END as quality_tier,
  COUNT(*) as count
FROM pattern_lineage_nodes
GROUP BY quality_tier;

-- Check usage stats
SELECT
  pattern_name,
  usage_count,
  array_length(used_by_agents, 1) as agent_count
FROM pattern_lineage_nodes
WHERE usage_count > 0
ORDER BY usage_count DESC
LIMIT 20;
```

---

## Testing Strategy

### Unit Tests
- Pattern extraction from sample files
- Quality score calculation
- Relationship detection
- AST parsing edge cases

### Integration Tests
- End-to-end pattern ingestion
- API response validation
- Dashboard data rendering

### Acceptance Tests
- [ ] No filenames in pattern list
- [ ] All patterns have quality 0.0-1.0
- [ ] Usage counts update correctly
- [ ] Relationships show code deps
- [ ] Dashboard renders patterns
- [ ] Pattern search works
- [ ] Export functionality works

---

## Success Metrics

| Metric | Before (Bad) | After (Good) | Target |
|--------|--------------|--------------|--------|
| Total Patterns | 1,259 | 200-500 | 300+ |
| Pattern Type | Filenames | Code patterns | ✅ |
| Quality Score | 85% (mock) | 0.0-1.0 (real) | Avg 0.75+ |
| Usage Tracking | 1 (hardcoded) | Dynamic | ✅ |
| Relationships | File imports | Code usage | ✅ |
| Dashboard Value | 0% useful | 90% useful | ✅ |

---

## Rollback Plan

If migration fails:

```bash
# Restore from backup
psql -h 192.168.86.200 -p 5436 -U postgres omninode_bridge \
  < backup_patterns_$(date +%Y%m%d).sql

# Or restore full database
dropdb -h 192.168.86.200 -p 5436 -U postgres omninode_bridge
createdb -h 192.168.86.200 -p 5436 -U postgres omninode_bridge
psql -h 192.168.86.200 -p 5436 -U postgres omninode_bridge \
  < backup_$(date +%Y%m%d).sql
```

---

## Next Steps

1. **Review this plan** with team (30 min meeting)
2. **Approve 4-week timeline** and assign developers
3. **Create GitHub issues** for each week's tasks
4. **Start Week 1** - Pattern extraction engine
5. **Weekly check-ins** to track progress

---

## Open Questions

1. Should we extract patterns from TypeScript/JavaScript files too?
2. Minimum quality threshold to include a pattern?
3. Should we use ML for pattern similarity detection?
4. How to handle patterns spanning multiple files?
5. Integration with existing Qdrant vector store?

---

## Appendix: Investigation Commands

```bash
# Find current pattern code
cd /Volumes/PRO-G40/Code/Omniarchon
find services/intelligence -name "*pattern*" -type f -name "*.py"

# Check database schema
PGPASSWORD='***REDACTED***' psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "\d pattern_lineage_nodes"

# Check current data
PGPASSWORD='***REDACTED***' psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT pattern_name, pattern_type, quality_score, usage_count
      FROM pattern_lineage_nodes
      ORDER BY created_at DESC
      LIMIT 20;"
```

---

**Document Version**: 1.0
**Last Updated**: 2025-10-28
**Status**: Ready for Review
