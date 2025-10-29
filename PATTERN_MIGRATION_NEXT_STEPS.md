# Pattern Migration Recovery Plan

**Status**: ❌ Migration Failed - Recovery Required
**Date**: 2025-10-28
**Correlation ID**: 672a37fa-02a2-40ab-989c-20b2c12daeee

---

## Current Situation

### Migration Results (FAILED)
- ✅ Step 1: Partial cleanup (some patterns deleted)
- ✅ Step 2: (Attempted but incomplete)
- ❌ Step 3: Pattern population from Qdrant (FAILED)
- ❌ Step 4: Quality score calculation (FAILED)
- ❌ Step 5: Validation (FAILED - this document)

### Critical Statistics
- **Before**: 1,305 patterns (97% filenames, all quality=0.85)
- **After**: 49 patterns (96% filenames, all quality=NULL)
- **Target**: 200-500 real patterns with varied quality scores
- **Achievement**: 0% of goals met

---

## Root Cause

The migration script steps 2-3 either:
1. **Never executed** (script error, permissions, or manual intervention)
2. **Executed but failed silently** (no error logs, no rollback)
3. **Executed but source data insufficient** (Qdrant has only 20 patterns)

**Evidence**:
```sql
-- Expected after migration
200-500 patterns with real names and quality scores

-- Actual in database
49 patterns, 47 are filenames, 0 quality scores

-- Available in Qdrant
execution_patterns: 20 patterns (real names, NULL quality)
code_patterns: 1,065 patterns (filenames, NULL quality)
```

**Conclusion**: Even if migration ran perfectly, Qdrant only has 20 usable patterns. Need to populate Qdrant first.

---

## Recovery Options

### Option 1: Quick Fix (2-4 hours) - NOT RECOMMENDED
**Goal**: Get basic pattern data for immediate use

**Steps**:
1. Manually curate 50-100 real patterns from codebase
2. Add to database with estimated quality scores
3. Use for dashboard temporarily

**Pros**:
- Fast turnaround
- Dashboard becomes usable quickly

**Cons**:
- Manual work, not scalable
- Quality scores estimated, not data-driven
- No long-term solution

### Option 2: Automated Discovery (1-2 days) - RECOMMENDED
**Goal**: Build proper pattern discovery pipeline

**Steps**:
1. Extract patterns from Archon/Omniclaude codebases
2. Use ML/algorithmic quality scoring
3. Populate Qdrant execution_patterns (target: 300-500)
4. Re-run migration with validation gates

**Pros**:
- Sustainable, repeatable process
- Data-driven quality scores
- Scales to future pattern discovery

**Cons**:
- Takes 1-2 days
- Requires pattern extraction implementation

### Option 3: Restore + Enhance (3-5 days) - COMPREHENSIVE
**Goal**: Build complete intelligence pipeline

**Steps**:
1. Restore database from pre-migration backup (if exists)
2. Build pattern discovery pipeline
3. Implement quality scoring ML model
4. Populate Qdrant with 500+ patterns
5. Run migration with full validation
6. Enable continuous pattern discovery

**Pros**:
- Complete solution with monitoring
- Best long-term outcome
- Continuous improvement

**Cons**:
- Most time-intensive
- Requires ML model training

---

## Recommended Path: Option 2 (Automated Discovery)

### Phase 1: Pattern Extraction (4-8 hours)

**Extract from Archon codebase**:
```python
# Target directories
/Volumes/PRO-G40/Code/Archon/services/intelligence/src/
/Volumes/PRO-G40/Code/Archon/services/onextree/src/

# Pattern types to extract
- ONEX node patterns (Effect, Compute, Reducer, Orchestrator)
- Service patterns (Intelligence, Search, Vector, Graph)
- Handler patterns (Request handlers, Event processors)
- Algorithm patterns (Scoring, Matching, Caching)

# Target: 200-300 patterns
```

**Extract from OmniClaude codebase**:
```python
# Target directories
/Volumes/PRO-G40/Code/omniclaude/agents/
/Volumes/PRO-G40/Code/omniclaude/hooks/

# Pattern types to extract
- Agent patterns (Polymorphic, Specialized, Coordination)
- Routing patterns (Fuzzy matching, Confidence scoring)
- Intelligence patterns (Manifest injection, RAG queries)
- Hook patterns (Git hooks, Pre-commit, Post-commit)

# Target: 100-200 patterns
```

**Quality Scoring Algorithm**:
```python
def calculate_quality_score(pattern):
    score = 0.0

    # Code complexity (25%)
    complexity = analyze_complexity(pattern.code)
    score += 0.25 * (1.0 - complexity / max_complexity)

    # Documentation quality (25%)
    doc_quality = analyze_documentation(pattern)
    score += 0.25 * doc_quality

    # Usage frequency (20%)
    usage = count_usage_in_codebase(pattern)
    score += 0.20 * min(1.0, usage / 10)

    # ONEX compliance (20%)
    compliance = check_onex_compliance(pattern)
    score += 0.20 * compliance

    # Recent usage (10%)
    recency = check_recent_usage(pattern)
    score += 0.10 * recency

    return score  # Range: 0.0 - 1.0
```

**Output**:
- 300-500 patterns in Qdrant execution_patterns
- All with quality scores (0.0-1.0, varied)
- All with pattern_type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR, etc.)
- All with metadata (file_path, description, use_cases)

### Phase 2: Quality Scoring (2-4 hours)

**Implement scoring**:
```bash
# Create quality scoring script
/Volumes/PRO-G40/Code/omniclaude/scripts/calculate_pattern_quality.py

# Run on extracted patterns
python3 scripts/calculate_pattern_quality.py \
  --input extracted_patterns.json \
  --output patterns_with_quality.json

# Upload to Qdrant
python3 scripts/upload_to_qdrant.py \
  --collection execution_patterns \
  --input patterns_with_quality.json
```

**Validation**:
```python
# Verify Qdrant data before migration
assert qdrant_count >= 300, "Need at least 300 patterns"
assert all_have_quality_scores(), "All patterns need quality"
assert all_have_pattern_type(), "All patterns need type"
assert quality_variance > 0.1, "Need quality variance"
assert no_filenames(), "No filename patterns allowed"
```

### Phase 3: Re-run Migration (1-2 hours)

**Pre-migration checks**:
```bash
# Verify Qdrant data
curl http://localhost:6333/collections/execution_patterns | jq '.result.points_count'
# Expected: >= 300

# Check sample pattern
curl -s http://localhost:6333/collections/execution_patterns/points/scroll \
  -H "Content-Type: application/json" \
  -d '{"limit": 1, "with_payload": true}' | jq '.result.points[0].payload'
# Expected: {pattern_name: "...", pattern_type: "...", overall_quality: 0.X, ...}
```

**Run migration**:
```bash
# Block pattern ingestion
# (stop any services that write to pattern_lineage_nodes)

# Clean database
PGPASSWORD='***REDACTED***' psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge << 'EOF'
TRUNCATE TABLE pattern_lineage_nodes CASCADE;
TRUNCATE TABLE pattern_lineage_edges CASCADE;
EOF

# Run migration script
python3 scripts/migrate_patterns_from_qdrant.py \
  --collection execution_patterns \
  --validate-each-batch \
  --rollback-on-failure

# Validate
./scripts/validate_patterns.sh
```

**Post-migration checks**:
```bash
# Expected results
Total patterns: 300-500 ✓
Patterns with quality: 100% ✓
Filename patterns: 0 ✓
Quality variance: > 0.1 ✓
Average quality: >= 0.65 ✓
Pattern types: Multiple (EFFECT, COMPUTE, etc.) ✓
```

---

## Timeline Estimate

### Option 2: Automated Discovery (Recommended)

| Phase | Task | Duration | Owner |
|-------|------|----------|-------|
| 1 | Pattern extraction from Archon | 4 hours | Developer |
| 1 | Pattern extraction from OmniClaude | 2 hours | Developer |
| 1 | Pattern deduplication & validation | 1 hour | Developer |
| 2 | Implement quality scoring algorithm | 2 hours | Developer |
| 2 | Run quality scoring on all patterns | 1 hour | Automated |
| 2 | Upload to Qdrant execution_patterns | 1 hour | Developer |
| 3 | Verify Qdrant data | 0.5 hour | Developer |
| 3 | Clean database & re-run migration | 0.5 hour | Developer |
| 3 | Validate results | 0.5 hour | Developer |
| **Total** | **End-to-end** | **12-14 hours** | **~1.5 days** |

---

## Validation Criteria for Success

### Data Quality
- [ ] Total patterns: 300-500 (target 400+)
- [ ] Real pattern names: 100% (0% filenames)
- [ ] Quality scores populated: 100%
- [ ] Quality variance: > 0.1 (well distributed)
- [ ] Average quality: >= 0.65
- [ ] Pattern types: Multiple types present

### Database Integrity
- [ ] No NULL quality scores
- [ ] All metadata populated
- [ ] Pattern relationships present
- [ ] No duplicate patterns
- [ ] All patterns have created_at timestamp

### Qdrant Source
- [ ] execution_patterns: >= 300 points
- [ ] All points have quality scores
- [ ] All points have pattern_type
- [ ] All points have metadata
- [ ] No filename patterns in collection

### Migration Process
- [ ] Pre-migration validation passed
- [ ] Each batch validated during migration
- [ ] Post-migration validation passed
- [ ] Rollback capability tested
- [ ] No data loss during migration

---

## Scripts Needed

### 1. Pattern Extraction Script
```bash
scripts/extract_patterns_from_codebase.py
  --source /Volumes/PRO-G40/Code/Archon
  --pattern-types ONEX,SERVICE,HANDLER,ALGORITHM
  --output archon_patterns.json
  --min-quality 0.5
```

### 2. Quality Scoring Script
```bash
scripts/calculate_pattern_quality.py
  --input archon_patterns.json
  --output patterns_with_quality.json
  --algorithm hybrid  # complexity + docs + usage + onex
```

### 3. Qdrant Upload Script
```bash
scripts/upload_to_qdrant.py
  --collection execution_patterns
  --input patterns_with_quality.json
  --batch-size 50
  --validate
```

### 4. Migration Script (Fixed)
```bash
scripts/migrate_patterns_from_qdrant.py
  --collection execution_patterns
  --database omninode_bridge
  --validate-each-batch
  --rollback-on-failure
  --min-quality 0.3  # Allow low quality patterns for diversity
```

---

## Monitoring & Rollback

### Pre-migration Backup
```bash
# Backup current state (even if failed)
PGPASSWORD='***REDACTED***' pg_dump \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -t pattern_lineage_nodes -t pattern_lineage_edges \
  > pattern_backup_20251028.sql
```

### Rollback Plan
```bash
# If migration fails, restore backup
PGPASSWORD='***REDACTED***' psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  < pattern_backup_20251028.sql
```

### Monitoring During Migration
```python
# Migration script should log:
- Patterns processed (count)
- Patterns inserted successfully (count)
- Quality scores populated (count)
- Errors encountered (with details)
- Validation checks (pass/fail per batch)

# Example output:
# [Batch 1/10] Processing patterns 0-50...
#   Inserted: 48/50 (2 skipped: duplicate names)
#   Quality populated: 48/48
#   Validation: PASS
# [Batch 2/10] Processing patterns 50-100...
#   Inserted: 50/50
#   Quality populated: 50/50
#   Validation: PASS
```

---

## Next Immediate Actions

1. **Decide on recovery option** (recommend Option 2)
2. **Backup current database state** (even failed state)
3. **Create pattern extraction script** (priority 1)
4. **Implement quality scoring algorithm** (priority 2)
5. **Test on small dataset** (10-20 patterns)
6. **Run full extraction** (300-500 patterns)
7. **Validate Qdrant data thoroughly**
8. **Re-run migration with validation**

---

## Questions to Answer

1. **Do we have a backup** from before the migration?
2. **What caused the migration to fail** (logs available)?
3. **Which pattern extraction approach** (automated vs manual)?
4. **Quality scoring algorithm** (ML vs algorithmic vs hybrid)?
5. **Timeline constraints** (urgent vs can wait 1-2 days)?

---

## Success Metrics

After successful recovery:

| Metric | Before Migration | After Recovery | Status |
|--------|-----------------|----------------|---------|
| Total Patterns | 1,305 | 300-500 | ✅ Quality over quantity |
| Real Patterns | 40 (3%) | 300-500 (100%) | ✅ Complete improvement |
| Avg Quality | 0.85 (fake) | 0.70+ (real) | ✅ Data-driven |
| Quality Variance | 0.0 | 0.15+ | ✅ Well distributed |
| Filename Patterns | 97% | 0% | ✅ Eliminated |
| Dashboard Value | 3% useful | 90%+ useful | ✅ Mission accomplished |

---

**Document Version**: 1.0
**Last Updated**: 2025-10-28 19:50:00 UTC
**Status**: Ready for execution pending decision
