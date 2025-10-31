# Pattern Quality Score Enhancement Plan

**Document Version**: 1.0.0
**Created**: 2025-10-29
**Status**: Awaiting Approval
**Correlation ID**: ae7d8734-8e30-4fff-9f61-5066acb2ad99

---

## Executive Summary

Following the successful pattern migration to 1,015 real patterns, analysis revealed that only 1.7% of patterns have `documentation_score` and `maintainability_score` populated, while 95.8% have `overall_quality` and `complexity_score`. This plan outlines a phased approach to implement comprehensive quality scoring across all patterns, with priority given to high-value, low-effort enhancements.

**Recommended Approach**: Implement documentation and maintainability scores (Priority 1 & 2) for 12-20 hours total effort, achieving >95% population for these critical metrics. Defer test coverage and reusability scores pending business value assessment.

**Expected Outcome**: All 973 code patterns will have complete quality profiles including complexity, documentation, and maintainability scores, enabling data-driven pattern selection and quality-based search.

---

## Current State

### Pattern Population Statistics

| Metric | Count | % of Total | Status |
|--------|-------|------------|--------|
| **Total Patterns** | 1,015 | 100% | ✅ |
| **Code Patterns** | 973 | 95.8% | ✅ |
| **Intent Files** | 42 | 4.2% | ✅ (excluded from quality scoring) |

### Quality Score Population Rates

| Score Type | Populated | NULL Count | % Populated | Status |
|------------|-----------|------------|-------------|--------|
| **overall_quality** | 973 | 42 | **95.8%** | ✅ Excellent |
| **complexity_score** | 973 | 42 | **95.8%** | ✅ Excellent |
| **documentation_score** | 17 | 998 | **1.7%** | ⚠️ Critical Gap |
| **maintainability_score** | 17 | 998 | **1.7%** | ⚠️ Critical Gap |
| **test_coverage_score** | 0 | 1,015 | **0.0%** | ⚠️ Not Implemented |
| **reusability_score** | 0 | 1,015 | **0.0%** | ⚠️ Not Implemented |
| **usage_count** | 1,015 | 0 | **100%** | ✅ Good (all = 0) |
| **used_by_agents** | 1,015 | 0 | **100%** | ✅ Good (all = []) |

### Infrastructure Available

- **PatternScorer** exists: `/Volumes/PRO-G40/Code/Omniarchon/services/intelligence/src/services/quality/pattern_scorer.py`
- **Radon library** available: Cyclomatic complexity, maintainability index
- **AST parsing** implemented: Docstring, type hint detection
- **Database schema** supports all quality scores with proper constraints
- **Quality formula** defined: Weighted average of 5 components (30% complexity, 20% documentation, 20% test coverage, 15% reusability, 15% maintainability)

---

## Proposed Enhancements

### Enhancement 1: Documentation Score (PRIORITY 1)

**Goal**: Calculate `documentation_score` for all 973 code patterns

**Current State**: Only 17 patterns (1.7%) have documentation scores

**Business Value**: HIGH
- Documentation quality directly impacts pattern usability
- Easy to calculate from existing AST parsing
- Enables filtering for well-documented patterns
- Supports learning and onboarding

**Technical Complexity**: LOW

**Components to Measure**:
1. **Docstring Presence** (0.5 points)
   - Module-level docstring
   - Class-level docstring
   - Function-level docstring

2. **Type Hints** (0.5 points)
   - Function parameter type hints
   - Function return type hints

**Implementation Approach**:
- Leverage existing `PatternScorer.calculate_documentation_score()` method
- Parse pattern code using AST
- Detect docstrings via `ast.get_docstring()`
- Detect type hints via `ast.FunctionDef.returns` and `ast.arg.annotation`
- Calculate binary score: 0.0 (none), 0.5 (one component), 1.0 (both)

**Script Location**:
- Use existing: `services/intelligence/src/services/quality/pattern_scorer.py`
- Create new: `services/intelligence/scripts/backfill_documentation_scores.py`

**Time Estimate**: **4-8 hours**
- 2 hours: Create backfill script
- 1 hour: Test on sample patterns
- 2 hours: Run on all 973 patterns
- 1-3 hours: Validation and debugging

**Success Criteria**:
- ✅ 95%+ patterns have `documentation_score` populated
- ✅ Score distribution shows variety (not all 0.0 or 1.0)
- ✅ High-quality patterns (overall_quality > 0.8) correlate with high documentation scores
- ✅ Backfill completes in <30 minutes for 973 patterns

---

### Enhancement 2: Maintainability Score (PRIORITY 2)

**Goal**: Calculate `maintainability_score` for all 973 code patterns

**Current State**: Only 17 patterns (1.7%) have maintainability scores

**Business Value**: HIGH
- Maintainability predicts long-term code health
- Helps identify technical debt in patterns
- Supports refactoring prioritization
- Correlates with overall quality

**Technical Complexity**: MEDIUM

**Components to Measure**:
1. **Low Coupling** (0.5 points)
   - 0-5 imports: 1.0 (excellent)
   - 6-10 imports: 0.6 (good)
   - 10+ imports: 0.3 (poor)
   - Detectable via AST: `ast.Import`, `ast.ImportFrom`

2. **High Cohesion** (0.5 points)
   - Based on Radon's Maintainability Index (MI)
   - MI >= 20: 1.0 (high cohesion)
   - MI 10-20: 0.6 (medium cohesion)
   - MI < 10: 0.3 (low cohesion)

**Implementation Approach**:
- Use existing `PatternScorer.calculate_maintainability_score()` method
- **Coupling**: Count imports in AST
- **Cohesion**: Use `radon.metrics.mi_visit()` for maintainability index
- Calculate weighted average: (coupling_score * 0.5) + (cohesion_score * 0.5)

**Script Location**:
- Use existing: `services/intelligence/src/services/quality/pattern_scorer.py`
- Create new: `services/intelligence/scripts/backfill_maintainability_scores.py`

**Time Estimate**: **8-12 hours**
- 3 hours: Create backfill script with radon integration
- 2 hours: Test radon MI calculation on sample patterns
- 2 hours: Handle edge cases (empty files, syntax errors)
- 3 hours: Run on all 973 patterns
- 2 hours: Validation and debugging

**Success Criteria**:
- ✅ 95%+ patterns have `maintainability_score` populated
- ✅ Score distribution shows variety (validate against MI distribution)
- ✅ Low maintainability scores correlate with high complexity
- ✅ Backfill completes in <60 minutes for 973 patterns

---

### Enhancement 3: Test Coverage Score (OPTIONAL - DEFER)

**Goal**: Calculate `test_coverage_score` for patterns where tests exist

**Current State**: 0 patterns (0.0%) have test coverage scores

**Business Value**: MEDIUM
- Test coverage indicates code reliability
- Useful for identifying untested patterns
- Supports quality-driven development

**Technical Complexity**: HIGH

**Why High Complexity?**:
1. Requires test file discovery and mapping to source files
2. Requires running test suite with coverage.py in isolated environment
3. Requires parsing coverage.py output and matching to patterns
4. Patterns from multiple projects have different test structures
5. Performance: Running tests for 973 patterns is time-intensive

**Components to Measure**:
- Percentage of lines covered by tests (0.0-1.0)
- Requires `coverage.py` or `pytest-cov` integration
- Must run tests to generate coverage data

**Implementation Approach** (if approved):
1. **Test File Discovery**:
   ```python
   def find_test_files(pattern_file_path: str) -> List[str]:
       """
       Find test files for a given pattern file.

       Strategies:
       - test_<module>.py (pytest convention)
       - <module>_test.py (Google convention)
       - tests/<module>.py (directory-based)
       """
       base_name = Path(pattern_file_path).stem
       possible_test_paths = [
           f"test_{base_name}.py",
           f"{base_name}_test.py",
           f"tests/{base_name}.py",
           f"tests/test_{base_name}.py",
       ]
       return [p for p in possible_test_paths if Path(p).exists()]
   ```

2. **Coverage Calculation**:
   ```python
   def calculate_coverage(pattern_file: str, test_files: List[str]) -> float:
       """
       Run tests with coverage and extract percentage.
       """
       # Run: pytest --cov=<pattern_file> <test_files> --cov-report=json
       # Parse: coverage.json → extract coverage percentage
       # Return: coverage_percent / 100.0
   ```

3. **Performance Optimization**:
   - Cache coverage results to avoid re-running tests
   - Run tests in parallel batches
   - Skip patterns without discoverable tests (return NULL, not 0.0)

**Script Location**:
- Create new: `services/intelligence/src/services/quality/test_coverage_scorer.py`
- Create new: `services/intelligence/scripts/backfill_test_coverage.py`

**Time Estimate**: **16-24 hours**
- 4 hours: Test file discovery logic
- 6 hours: Coverage.py integration and parsing
- 4 hours: Parallel execution framework
- 4 hours: Testing and debugging
- 2-6 hours: Performance tuning and optimization

**Success Criteria**:
- ✅ Test coverage calculated for all patterns with discoverable tests
- ✅ Patterns without tests have NULL (not 0.0) for test_coverage_score
- ✅ Coverage values validated against manual pytest-cov runs
- ✅ Backfill completes in <4 hours for 973 patterns

**Blockers**:
- ❌ Requires test execution environment (not all patterns have runnable tests)
- ❌ Multi-project patterns have different test frameworks
- ❌ Time-intensive: Running 973 test suites takes significant time

**Decision Required**: Is 16-24 hours of effort justified for this metric?

---

### Enhancement 4: Reusability Score (OPTIONAL - DEFER)

**Goal**: Calculate `reusability_score` based on cross-file usage patterns

**Current State**: 0 patterns (0.0%) have reusability scores

**Business Value**: LOW-MEDIUM
- Reusability indicates pattern adoption and value
- Useful for identifying "golden patterns" used across projects
- Supports pattern curation and recommendations

**Technical Complexity**: MEDIUM

**Why Medium Complexity?**:
1. Requires scanning entire codebase for pattern usage
2. Must identify imports and references to pattern
3. Cross-project patterns require scanning multiple codebases
4. Subjective metric: What counts as "usage"?

**Components to Measure**:
- Number of unique files importing/using the pattern
- Scoring thresholds:
  - 1 file: 0.3 (low reusability)
  - 2-5 files: 0.6 (medium reusability)
  - 5+ files: 1.0 (high reusability)

**Implementation Approach** (if approved):
1. **Usage Detection**:
   ```python
   def find_pattern_usage(pattern_name: str, codebase_roots: List[str]) -> int:
       """
       Scan codebases for imports/references to pattern.

       Strategies:
       - Grep for "from <module> import <pattern>"
       - Grep for "import <module>.<pattern>"
       - Parse import statements in all Python files
       """
       usage_files = set()

       for root in codebase_roots:
           # Use ripgrep or ast parsing to find imports
           for file in find_python_files(root):
               if pattern_imported_in_file(file, pattern_name):
                   usage_files.add(file)

       return len(usage_files)
   ```

2. **Cross-Project Scanning**:
   - Scan: `/Volumes/PRO-G40/Code/omniclaude`
   - Scan: `/Volumes/PRO-G40/Code/Omniarchon`
   - Cache results to avoid re-scanning

3. **Performance Optimization**:
   - Use ripgrep for fast text search
   - Parallel file scanning
   - Cache usage results

**Script Location**:
- Create new: `services/intelligence/src/services/quality/reusability_scorer.py`
- Create new: `services/intelligence/scripts/backfill_reusability_scores.py`

**Time Estimate**: **6-10 hours**
- 2 hours: Usage detection logic (ripgrep + AST parsing)
- 2 hours: Cross-project scanning framework
- 2 hours: Testing and validation
- 2 hours: Performance optimization
- 0-2 hours: Debugging edge cases

**Success Criteria**:
- ✅ Reusability scores calculated for all 973 patterns
- ✅ High-usage patterns (used in 5+ files) correctly identified
- ✅ Unused patterns (used in 1 file only) have reusability_score = 0.3
- ✅ Backfill completes in <2 hours for 973 patterns

**Challenges**:
- ⚠️ Subjective: Pattern "copied and pasted" vs "imported"?
- ⚠️ Dynamic imports not detected
- ⚠️ False positives: Pattern name appears in comments

**Decision Required**: Is this worth 6-10 hours of effort?

---

## Implementation Timeline

### Week 1: Documentation Score (Enhancement 1)
**Estimated Effort**: 4-8 hours

**Tasks**:
- [ ] Day 1: Review existing `PatternScorer.calculate_documentation_score()` logic
- [ ] Day 1: Create `backfill_documentation_scores.py` script
- [ ] Day 2: Test on 10 sample patterns (validate scoring)
- [ ] Day 2: Test on 100 patterns (performance benchmark)
- [ ] Day 3: Run on all 973 patterns
- [ ] Day 3: Validate results (score distribution, correlation with quality)
- [ ] Day 3: Commit migration SQL and script

**Deliverables**:
- ✅ Backfill script: `services/intelligence/scripts/backfill_documentation_scores.py`
- ✅ Migration SQL: `services/intelligence/migrations/add_documentation_scores.sql`
- ✅ Validation report: `DOCUMENTATION_SCORE_VALIDATION.md`

---

### Week 2: Maintainability Score (Enhancement 2)
**Estimated Effort**: 8-12 hours

**Tasks**:
- [ ] Day 1: Review `PatternScorer.calculate_maintainability_score()` logic
- [ ] Day 1: Test radon MI calculation on sample patterns
- [ ] Day 2: Create `backfill_maintainability_scores.py` script
- [ ] Day 2: Handle edge cases (syntax errors, empty files)
- [ ] Day 3: Test on 10 sample patterns (validate scoring)
- [ ] Day 3: Test on 100 patterns (performance benchmark)
- [ ] Day 4: Run on all 973 patterns
- [ ] Day 4: Validate results (MI distribution, correlation with complexity)
- [ ] Day 4: Commit migration SQL and script

**Deliverables**:
- ✅ Backfill script: `services/intelligence/scripts/backfill_maintainability_scores.py`
- ✅ Migration SQL: `services/intelligence/migrations/add_maintainability_scores.sql`
- ✅ Validation report: `MAINTAINABILITY_SCORE_VALIDATION.md`

---

### Week 3: Decision Point + Optional Enhancements

**Decision Meeting**: Review Week 1-2 results and decide on optional enhancements

**Agenda**:
1. Review documentation score implementation (success criteria met?)
2. Review maintainability score implementation (success criteria met?)
3. Assess business value of test coverage score (16-24 hours effort)
4. Assess business value of reusability score (6-10 hours effort)
5. Approve/defer optional enhancements

**If Approved - Test Coverage** (Enhancement 3):
- Week 3-4: Implement test coverage scoring (16-24 hours)
- Week 5: Backfill and validation

**If Approved - Reusability** (Enhancement 4):
- Week 3: Implement reusability scoring (6-10 hours)
- Week 4: Backfill and validation

**If Deferred**:
- Document decision and rationale
- Focus on improving documentation and maintainability score accuracy

---

## Technical Details

### Enhancement 1: Documentation Score Algorithm

**Pseudocode**:
```python
def calculate_documentation_score(code: str) -> float:
    """
    Calculate documentation score based on docstrings and type hints.

    Returns:
        0.0: No docstrings, no type hints
        0.5: Docstrings OR type hints
        1.0: Docstrings AND type hints
    """
    score = 0.0

    # Parse code to AST
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return 0.0  # Unparseable code has no documentation

    # Check for docstrings (0.5 points)
    has_docstring = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
            if ast.get_docstring(node):
                has_docstring = True
                break

    if has_docstring:
        score += 0.5

    # Check for type hints (0.5 points)
    has_type_hints = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Check return type
            if node.returns is not None:
                has_type_hints = True
                break
            # Check parameter type hints
            for arg in node.args.args:
                if arg.annotation is not None:
                    has_type_hints = True
                    break
            if has_type_hints:
                break

    if has_type_hints:
        score += 0.5

    return score
```

**Complexity**: O(n) where n = number of AST nodes

**Performance**: <10ms per pattern on average

---

### Enhancement 2: Maintainability Score Algorithm

**Pseudocode**:
```python
def calculate_maintainability_score(code: str) -> float:
    """
    Calculate maintainability score based on coupling and cohesion.

    Returns:
        0.0-1.0: Weighted average of coupling and cohesion scores
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return 0.0  # Unparseable code is unmaintainable

    # Calculate coupling score (0.5 weight)
    import_count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            import_count += 1

    if import_count <= 5:
        coupling_score = 1.0
    elif import_count <= 10:
        coupling_score = 0.6
    else:
        coupling_score = 0.3

    # Calculate cohesion score using radon MI (0.5 weight)
    try:
        from radon.metrics import mi_visit
        mi_results = mi_visit(code, multi=True)

        if not mi_results:
            cohesion_score = 0.5  # Neutral
        else:
            avg_mi = sum(r.mi for r in mi_results) / len(mi_results)

            if avg_mi >= 20:
                cohesion_score = 1.0
            elif avg_mi >= 10:
                cohesion_score = 0.6
            else:
                cohesion_score = 0.3
    except Exception:
        cohesion_score = 0.5  # Neutral on error

    # Weighted average
    maintainability_score = (coupling_score * 0.5) + (cohesion_score * 0.5)

    return maintainability_score
```

**Complexity**: O(n) for AST + O(m) for radon MI where n = AST nodes, m = code lines

**Performance**: <50ms per pattern on average (radon MI is slower)

---

### Enhancement 3: Test Coverage Score Algorithm (Optional)

**Pseudocode**:
```python
def calculate_test_coverage_score(pattern_file_path: str) -> Optional[float]:
    """
    Calculate test coverage score by running tests with coverage.py.

    Returns:
        None: No tests found (keeps database NULL)
        0.0-1.0: Percentage of lines covered
    """
    # Find associated test files
    test_files = find_test_files(pattern_file_path)

    if not test_files:
        return None  # No tests found → NULL in database

    # Run tests with coverage
    coverage_data = run_pytest_with_coverage(pattern_file_path, test_files)

    if not coverage_data:
        return None  # Coverage failed → NULL in database

    # Extract coverage percentage
    total_lines = coverage_data['summary']['num_statements']
    covered_lines = coverage_data['summary']['covered_lines']

    if total_lines == 0:
        return None  # No executable lines

    coverage_percent = covered_lines / total_lines

    return coverage_percent


def run_pytest_with_coverage(source_file: str, test_files: List[str]) -> dict:
    """
    Run pytest with coverage and return JSON results.
    """
    import subprocess
    import json
    import tempfile

    with tempfile.NamedTemporaryFile(suffix='.json') as tmp:
        # Run: pytest --cov=source_file test_files --cov-report=json:tmp.name
        cmd = [
            'pytest',
            f'--cov={source_file}',
            *test_files,
            f'--cov-report=json:{tmp.name}',
            '--quiet',
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=60)

        if result.returncode != 0:
            return {}  # Tests failed

        # Parse coverage JSON
        with open(tmp.name) as f:
            return json.load(f)
```

**Complexity**: O(tests) where tests = number of test cases

**Performance**: Highly variable
- Fast: <1s per pattern (simple tests)
- Slow: >60s per pattern (complex integration tests)
- Estimated: ~10s per pattern average
- Total: ~9,730s = 2.7 hours for 973 patterns (sequential)
- With parallelization (10 workers): ~16 minutes

---

### Enhancement 4: Reusability Score Algorithm (Optional)

**Pseudocode**:
```python
def calculate_reusability_score(pattern_name: str, codebase_roots: List[str]) -> float:
    """
    Calculate reusability score based on cross-file usage.

    Returns:
        0.3: Used in 1 file only
        0.6: Used in 2-5 files
        1.0: Used in 5+ files
    """
    usage_files = find_pattern_usage(pattern_name, codebase_roots)
    usage_count = len(usage_files)

    if usage_count < 2:
        return 0.3
    elif usage_count < 5:
        return 0.6
    else:
        return 1.0


def find_pattern_usage(pattern_name: str, codebase_roots: List[str]) -> Set[str]:
    """
    Find files that import or reference the pattern.
    """
    import subprocess

    usage_files = set()

    # Extract module and class/function name
    # Example: "node_cache_manager_reducer.py" → "NodeCacheManagerReducer"
    module_name = Path(pattern_name).stem
    class_name = ''.join(word.capitalize() for word in module_name.split('_'))

    for root in codebase_roots:
        # Use ripgrep for fast search
        # Search for: "from <module> import" OR "import <module>"
        cmd = [
            'rg',
            f'(from.*{module_name}.*import|import.*{module_name}|{class_name})',
            root,
            '--files-with-matches',
            '--glob', '*.py',
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if line:
                    usage_files.add(line)

    return usage_files
```

**Complexity**: O(files × pattern_size) where files = codebase files, pattern_size = pattern name length

**Performance**:
- Fast: <100ms per pattern (ripgrep is very fast)
- Total: ~97s = 1.6 minutes for 973 patterns
- With caching: <30 seconds on subsequent runs

---

## Migration Strategy

### Backfill Process Overview

**Safe Backfill Pattern**:
1. Create backfill script with dry-run mode
2. Test on 10 sample patterns
3. Test on 100 patterns for performance
4. Validate results manually
5. Run full backfill with transaction safety
6. Verify results with SQL queries
7. Commit changes

### Backfill Script Template

```python
#!/usr/bin/env python3
"""
Backfill <SCORE_NAME> for all patterns in pattern_lineage_nodes.

Usage:
    python3 backfill_<score_name>.py --dry-run    # Preview changes
    python3 backfill_<score_name>.py --limit 10   # Test on 10 patterns
    python3 backfill_<score_name>.py              # Full backfill
"""

import argparse
import sys
from pathlib import Path

# Add intelligence service to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from services.quality.pattern_scorer import PatternScorer
from utils.database import get_db_connection


def backfill_scores(dry_run: bool = False, limit: int = None):
    """Backfill <score_name> for all patterns."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch patterns without <score_name>
    query = """
        SELECT id, pattern_name, pattern_data
        FROM pattern_lineage_nodes
        WHERE <score_name> IS NULL
          AND pattern_data->>'code' IS NOT NULL
        ORDER BY id
    """

    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query)
    patterns = cursor.fetchall()

    print(f"Found {len(patterns)} patterns to backfill")

    if dry_run:
        print("DRY RUN - no changes will be made")

    # Initialize scorer
    scorer = PatternScorer()

    # Process patterns
    updated_count = 0
    error_count = 0

    for pattern_id, pattern_name, pattern_data in patterns:
        try:
            code = pattern_data.get('code', '')

            if not code or code == '-':
                print(f"  SKIP: {pattern_name} (no code)")
                continue

            # Calculate score
            score = scorer.calculate_<score_name>(code)

            print(f"  {pattern_name}: <score_name> = {score:.4f}")

            if not dry_run:
                # Update database
                cursor.execute(
                    """
                    UPDATE pattern_lineage_nodes
                    SET <score_name> = %s
                    WHERE id = %s
                    """,
                    (score, pattern_id)
                )
                updated_count += 1

        except Exception as e:
            print(f"  ERROR: {pattern_name}: {e}")
            error_count += 1

    if not dry_run:
        conn.commit()
        print(f"\n✅ Updated {updated_count} patterns")
    else:
        print(f"\n📝 Would update {updated_count} patterns")

    if error_count > 0:
        print(f"⚠️  {error_count} errors encountered")

    cursor.close()
    conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backfill <score_name>')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without updating')
    parser.add_argument('--limit', type=int, help='Limit number of patterns to process')

    args = parser.parse_args()

    backfill_scores(dry_run=args.dry_run, limit=args.limit)
```

### Migration SQL Template

```sql
-- Migration: Add <score_name> to existing patterns
-- Created: 2025-10-29
-- Estimated time: <X> minutes for 973 patterns

BEGIN;

-- Backup table (optional but recommended)
CREATE TABLE pattern_lineage_nodes_backup_<date> AS
SELECT * FROM pattern_lineage_nodes;

-- Create index for performance (if needed)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pattern_lineage_<score_name>
ON pattern_lineage_nodes(<score_name>);

-- Run backfill (executed via Python script, not SQL)
-- See: services/intelligence/scripts/backfill_<score_name>.py

-- Validate results
SELECT
    COUNT(*) FILTER (WHERE <score_name> IS NOT NULL) as with_score,
    COUNT(*) FILTER (WHERE <score_name> IS NULL) as without_score,
    ROUND(AVG(<score_name>), 4) as avg_score,
    ROUND(MIN(<score_name>), 4) as min_score,
    ROUND(MAX(<score_name>), 4) as max_score
FROM pattern_lineage_nodes
WHERE pattern_data->>'code' IS NOT NULL
  AND pattern_data->>'code' != '-';

-- Expected results:
--   with_score: ~973 (95.8% of total)
--   without_score: ~42 (intent files)
--   avg_score: <expected_average>
--   min_score: 0.0
--   max_score: 1.0

COMMIT;
```

### Performance Optimization

**For Large Backfills (973 patterns)**:

1. **Batch Processing**:
   ```python
   batch_size = 100
   for i in range(0, len(patterns), batch_size):
       batch = patterns[i:i+batch_size]
       process_batch(batch)
       conn.commit()  # Commit every 100 patterns
   ```

2. **Parallel Processing** (if safe):
   ```python
   from multiprocessing import Pool

   with Pool(processes=4) as pool:
       results = pool.map(calculate_score, patterns)
   ```

3. **Progress Reporting**:
   ```python
   from tqdm import tqdm

   for pattern in tqdm(patterns, desc="Processing patterns"):
       calculate_and_update(pattern)
   ```

---

## Testing Strategy

### Test Levels

**Level 1: Unit Tests (Algorithm Validation)**
- Test documentation score calculation on known patterns
- Test maintainability score calculation on known patterns
- Validate edge cases (empty code, syntax errors)
- Verify score ranges (0.0-1.0)

**Level 2: Integration Tests (Database Updates)**
- Test backfill script on 10 sample patterns
- Verify database updates persist correctly
- Test transaction rollback on errors
- Validate constraints (CHECK score >= 0.0 AND score <= 1.0)

**Level 3: Validation Tests (Result Quality)**
- Compare scores against manual assessment
- Check score distribution (variety, not all same)
- Validate correlations (e.g., high quality → high documentation)
- Check performance (time to process 973 patterns)

### Validation Queries

**Documentation Score Validation**:
```sql
-- Check distribution
SELECT
    CASE
        WHEN documentation_score = 0.0 THEN '0.0 (None)'
        WHEN documentation_score = 0.5 THEN '0.5 (Partial)'
        WHEN documentation_score = 1.0 THEN '1.0 (Complete)'
        ELSE 'Other'
    END as score_bucket,
    COUNT(*) as count
FROM pattern_lineage_nodes
WHERE documentation_score IS NOT NULL
GROUP BY score_bucket
ORDER BY score_bucket;

-- Expected distribution:
--   0.0: ~30-40% (no docstrings or type hints)
--   0.5: ~20-30% (docstrings OR type hints)
--   1.0: ~30-40% (docstrings AND type hints)

-- Check correlation with overall quality
SELECT
    ROUND(overall_quality, 1) as quality_bucket,
    ROUND(AVG(documentation_score), 2) as avg_doc_score,
    COUNT(*) as count
FROM pattern_lineage_nodes
WHERE documentation_score IS NOT NULL
  AND overall_quality IS NOT NULL
GROUP BY ROUND(overall_quality, 1)
ORDER BY quality_bucket DESC;

-- Expected: Higher overall_quality → higher avg_doc_score
```

**Maintainability Score Validation**:
```sql
-- Check distribution
SELECT
    ROUND(maintainability_score, 1) as score_bucket,
    COUNT(*) as count
FROM pattern_lineage_nodes
WHERE maintainability_score IS NOT NULL
GROUP BY score_bucket
ORDER BY score_bucket DESC;

-- Expected: Variety of scores (not all 0.5)

-- Check correlation with complexity
SELECT
    ROUND(complexity_score, 1) as complexity_bucket,
    ROUND(AVG(maintainability_score), 2) as avg_maintainability,
    COUNT(*) as count
FROM pattern_lineage_nodes
WHERE maintainability_score IS NOT NULL
  AND complexity_score IS NOT NULL
GROUP BY ROUND(complexity_score, 1)
ORDER BY complexity_bucket;

-- Expected: Lower complexity → higher maintainability (negative correlation)
```

### Sample Pattern Testing

**Select 10 Representative Patterns**:
```sql
-- Get diverse sample for testing
SELECT pattern_name, pattern_type, overall_quality, complexity_score
FROM pattern_lineage_nodes
WHERE pattern_data->>'code' IS NOT NULL
  AND pattern_data->>'code' != '-'
ORDER BY RANDOM()
LIMIT 10;
```

**Manual Validation**:
For each sample pattern:
1. Read the code manually
2. Assess documentation quality (docstrings, type hints)
3. Assess maintainability (imports, cohesion)
4. Compare manual assessment to calculated score
5. Adjust algorithm if scores don't match expectations

---

## Rollback Plan

### Scenario 1: Incorrect Scores Detected

**Detection**:
- Validation queries show unexpected distribution
- Manual review reveals incorrect scoring
- Correlation checks fail (e.g., no relationship to quality)

**Rollback Steps**:
```sql
-- Restore from backup
BEGIN;

-- Option A: Restore specific column
UPDATE pattern_lineage_nodes
SET <score_name> = backup.<score_name>
FROM pattern_lineage_nodes_backup_<date> backup
WHERE pattern_lineage_nodes.id = backup.id;

-- Option B: Restore entire table
DROP TABLE pattern_lineage_nodes;
ALTER TABLE pattern_lineage_nodes_backup_<date> RENAME TO pattern_lineage_nodes;

COMMIT;
```

### Scenario 2: Performance Issues

**Detection**:
- Backfill takes >2 hours for 973 patterns
- Database locks prevent other operations
- High CPU/memory usage

**Mitigation**:
1. Stop backfill process (Ctrl+C)
2. Rollback partial updates:
   ```sql
   ROLLBACK;  -- If still in transaction

   -- Or manually revert
   UPDATE pattern_lineage_nodes
   SET <score_name> = NULL
   WHERE <score_name> IS NOT NULL
     AND id > <last_known_good_id>;
   ```
3. Optimize script (batch size, parallel processing)
4. Retry with optimizations

### Scenario 3: Data Corruption

**Detection**:
- NULL values where shouldn't be
- Values outside 0.0-1.0 range
- Foreign key violations

**Rollback Steps**:
```sql
-- Restore from backup immediately
BEGIN;

DROP TABLE pattern_lineage_nodes;
ALTER TABLE pattern_lineage_nodes_backup_<date> RENAME TO pattern_lineage_nodes;

COMMIT;

-- Investigate root cause before retry
```

### Backup Strategy

**Before Each Enhancement**:
```sql
-- Create timestamped backup
CREATE TABLE pattern_lineage_nodes_backup_20251029_documentation AS
SELECT * FROM pattern_lineage_nodes;

-- Verify backup
SELECT COUNT(*) FROM pattern_lineage_nodes_backup_20251029_documentation;
-- Expected: 1,015

-- Estimate storage
SELECT pg_size_pretty(pg_total_relation_size('pattern_lineage_nodes_backup_20251029_documentation'));
-- Expected: ~50-100 MB
```

**After Successful Validation**:
```sql
-- Keep backup for 7 days, then drop
DROP TABLE pattern_lineage_nodes_backup_20251029_documentation;
```

---

## Success Metrics

### Enhancement 1: Documentation Score

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Population Rate** | ≥95% | `COUNT(*) WHERE documentation_score IS NOT NULL / COUNT(*) WHERE pattern_data->>'code' != '-'` |
| **Score Variety** | 3 distinct values | `COUNT(DISTINCT documentation_score)` ≥ 3 (0.0, 0.5, 1.0) |
| **Distribution Balance** | No bucket >60% | Each bucket (0.0, 0.5, 1.0) has ≤60% of patterns |
| **Quality Correlation** | Positive | `CORR(overall_quality, documentation_score)` > 0.3 |
| **Backfill Time** | <30 minutes | Time to process 973 patterns |
| **Error Rate** | <5% | Patterns with syntax errors or failures |

### Enhancement 2: Maintainability Score

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Population Rate** | ≥95% | `COUNT(*) WHERE maintainability_score IS NOT NULL / COUNT(*) WHERE pattern_data->>'code' != '-'` |
| **Score Variety** | ≥5 distinct ranges | Score distribution across 0.0-1.0 range |
| **Distribution Balance** | No bucket >40% | Score buckets (0.0-0.2, 0.2-0.4, etc.) each have ≤40% |
| **Complexity Correlation** | Negative | `CORR(complexity_score, maintainability_score)` < -0.2 (lower complexity → higher maintainability) |
| **Backfill Time** | <60 minutes | Time to process 973 patterns |
| **Error Rate** | <5% | Patterns with radon failures or errors |

### Enhancement 3: Test Coverage Score (If Implemented)

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Test Discovery Rate** | ≥30% | Patterns with discoverable tests |
| **Coverage Calculation** | 100% | Successfully calculate coverage for all patterns with tests |
| **NULL Handling** | Correct | Patterns without tests have NULL (not 0.0) |
| **Backfill Time** | <4 hours | Time to process 973 patterns |
| **Error Rate** | <10% | Test execution failures |

### Enhancement 4: Reusability Score (If Implemented)

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Population Rate** | 100% | All patterns have reusability_score |
| **Usage Detection** | ≥90% accuracy | Manual validation of high-usage patterns |
| **Score Variety** | 3 distinct values | 0.3, 0.6, 1.0 all present |
| **Backfill Time** | <2 hours | Time to process 973 patterns |
| **Error Rate** | <5% | Usage detection failures |

### Overall Quality Formula Validation

**After All Enhancements**:
```sql
-- Verify overall_quality formula matches components
SELECT
    pattern_name,
    overall_quality,
    ROUND(
        (complexity_score * 0.30) +
        (COALESCE(documentation_score, 0.5) * 0.20) +
        (COALESCE(test_coverage_score, 0.5) * 0.20) +
        (COALESCE(reusability_score, 0.5) * 0.15) +
        (COALESCE(maintainability_score, 0.5) * 0.15),
        4
    ) as calculated_quality,
    overall_quality - ROUND(...) as difference
FROM pattern_lineage_nodes
WHERE overall_quality IS NOT NULL
ORDER BY ABS(difference) DESC
LIMIT 10;

-- Expected: Difference should be small (<0.1) or explained
```

---

## Decision Points

### Decision 1: Implement Test Coverage Score? (Enhancement 3)

**Business Value**: MEDIUM
- Provides insight into pattern reliability
- Identifies untested code
- Supports quality-driven development

**Technical Complexity**: HIGH
- Requires test execution environment
- Time-intensive (16-24 hours development + 2-4 hours execution)
- Multi-project patterns have different test frameworks

**Cost-Benefit Analysis**:
- **Effort**: 16-24 hours development + ongoing maintenance
- **Benefit**: Test coverage data for ~30% of patterns (estimated)
- **ROI**: Low-Medium (high effort, medium benefit)

**Recommendation**: **DEFER** until business need is clear

**Alternative**: Use manual curation or ML-based quality assessment

---

### Decision 2: Implement Reusability Score? (Enhancement 4)

**Business Value**: LOW-MEDIUM
- Identifies "golden patterns" used across projects
- Supports pattern recommendations
- Helps prioritize pattern maintenance

**Technical Complexity**: MEDIUM
- Requires codebase scanning
- Cross-project complexity
- Subjective: What counts as "usage"?

**Cost-Benefit Analysis**:
- **Effort**: 6-10 hours development + periodic re-scanning
- **Benefit**: Reusability insights for all patterns
- **ROI**: Medium (medium effort, medium benefit)

**Recommendation**: **DEFER** until after Enhancements 1-2 complete

**Alternative**: Track actual usage via `used_by_agents` array (requires agent integration)

---

### Decision 3: Recalculate Overall Quality Score?

**Question**: Should we recalculate `overall_quality` after adding documentation and maintainability scores?

**Current State**:
- `overall_quality` calculated using only `complexity_score` + heuristics
- Formula specifies: 30% complexity + 20% documentation + 20% test + 15% reusability + 15% maintainability

**Options**:

**Option A: Recalculate Now** (After Enhancements 1-2)
- **Pros**: More accurate quality scores using full formula
- **Cons**: Changes existing quality scores (may break comparisons)
- **Effort**: 2-4 hours

**Option B: Recalculate Later** (After All Enhancements)
- **Pros**: Wait until all components available
- **Cons**: Current quality scores remain less accurate
- **Effort**: 2-4 hours (later)

**Option C: Don't Recalculate**
- **Pros**: Preserves existing quality scores for comparisons
- **Cons**: `overall_quality` doesn't match formula
- **Effort**: 0 hours

**Recommendation**: **Option A** - Recalculate after Enhancements 1-2
- Use formula with COALESCE for missing scores:
  ```sql
  overall_quality =
      (complexity_score * 0.30) +
      (COALESCE(documentation_score, 0.5) * 0.20) +
      (COALESCE(test_coverage_score, 0.5) * 0.20) +
      (COALESCE(reusability_score, 0.5) * 0.15) +
      (COALESCE(maintainability_score, 0.5) * 0.15)
  ```
- Missing scores default to 0.5 (neutral)

---

## Next Steps

### Immediate Actions (This Week)

1. **Review This Plan** (1 hour)
   - [ ] Technical review by development team
   - [ ] Business review by stakeholders
   - [ ] Approve Enhancements 1-2 (documentation + maintainability)
   - [ ] Decide on Enhancements 3-4 (test coverage + reusability)

2. **Setup Development Environment** (1 hour)
   - [ ] Clone `Omniarchon` repository
   - [ ] Install dependencies: `radon`, `coverage`, `pytest`
   - [ ] Verify database connectivity to `omninode_bridge`
   - [ ] Create `docs/planning` directory structure

3. **Create Validation Baseline** (30 minutes)
   - [ ] Run validation queries on current state
   - [ ] Document current score distributions
   - [ ] Select 10 sample patterns for manual testing

### Week 1: Documentation Score Implementation

**Day 1** (4 hours):
- [ ] Review existing `PatternScorer.calculate_documentation_score()` logic
- [ ] Test on 10 sample patterns manually
- [ ] Create `backfill_documentation_scores.py` script
- [ ] Test script with `--dry-run --limit 10`

**Day 2** (2 hours):
- [ ] Test on 100 patterns for performance benchmark
- [ ] Validate results with SQL queries
- [ ] Adjust algorithm if needed

**Day 3** (2 hours):
- [ ] Create backup table
- [ ] Run full backfill on 973 patterns
- [ ] Validate results (distribution, correlation)
- [ ] Create validation report: `DOCUMENTATION_SCORE_VALIDATION.md`
- [ ] Commit migration SQL and script

### Week 2: Maintainability Score Implementation

**Day 1** (4 hours):
- [ ] Review `PatternScorer.calculate_maintainability_score()` logic
- [ ] Test radon MI calculation on sample patterns
- [ ] Create `backfill_maintainability_scores.py` script
- [ ] Handle edge cases (syntax errors, empty files)

**Day 2** (4 hours):
- [ ] Test script with `--dry-run --limit 10`
- [ ] Test on 100 patterns for performance benchmark
- [ ] Validate results with SQL queries
- [ ] Adjust algorithm if needed

**Day 3** (4 hours):
- [ ] Create backup table
- [ ] Run full backfill on 973 patterns
- [ ] Validate results (distribution, correlation with complexity)
- [ ] Create validation report: `MAINTAINABILITY_SCORE_VALIDATION.md`
- [ ] Commit migration SQL and script

### Week 3: Decision Point

**Day 1** (2 hours):
- [ ] Review Week 1-2 results
- [ ] Assess success criteria met
- [ ] Present results to stakeholders
- [ ] Decide: Implement Enhancement 3 (test coverage)?
- [ ] Decide: Implement Enhancement 4 (reusability)?
- [ ] Decide: Recalculate overall_quality?

**If Approved - Recalculate Overall Quality** (2 hours):
- [ ] Create `recalculate_overall_quality.py` script
- [ ] Test on sample patterns
- [ ] Run full recalculation
- [ ] Validate new quality scores

### Future Work (If Approved)

**Week 4-5: Test Coverage Score** (16-24 hours):
- [ ] Implement test file discovery
- [ ] Integrate coverage.py
- [ ] Create backfill script with parallel execution
- [ ] Run on patterns with tests
- [ ] Validate coverage percentages

**Week 4: Reusability Score** (6-10 hours):
- [ ] Implement usage detection with ripgrep
- [ ] Create cross-project scanning logic
- [ ] Create backfill script
- [ ] Run on all patterns
- [ ] Validate high-usage patterns

---

## Appendix

### A. Database Schema Reference

**pattern_lineage_nodes table**:
```sql
CREATE TABLE pattern_lineage_nodes (
    id UUID PRIMARY KEY,
    pattern_name TEXT NOT NULL,
    pattern_type TEXT,
    pattern_data JSONB,

    -- Quality Scores (all 0.0-1.0 range)
    overall_quality NUMERIC(5,4) CHECK (overall_quality >= 0.0 AND overall_quality <= 1.0),
    complexity_score NUMERIC(5,4) CHECK (complexity_score >= 0.0 AND complexity_score <= 1.0),
    documentation_score NUMERIC(5,4) CHECK (documentation_score >= 0.0 AND documentation_score <= 1.0),
    maintainability_score NUMERIC(5,4) CHECK (maintainability_score >= 0.0 AND maintainability_score <= 1.0),
    test_coverage_score NUMERIC(5,4) CHECK (test_coverage_score >= 0.0 AND test_coverage_score <= 1.0),
    reusability_score NUMERIC(5,4) CHECK (reusability_score >= 0.0 AND reusability_score <= 1.0),

    -- Usage Tracking
    usage_count INTEGER DEFAULT 0,
    used_by_agents TEXT[] DEFAULT ARRAY[]::TEXT[],
    last_used_at TIMESTAMPTZ,

    -- Metadata
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### B. PatternScorer API Reference

**Class**: `PatternScorer`

**Methods**:
- `__init__(coverage_data: Optional[Dict] = None)` - Initialize scorer
- `calculate_overall_quality(code: str, file_path: str = None, usage_count: int = 1) -> Dict` - Calculate all scores
- `calculate_complexity_score(code: str) -> float` - Cyclomatic complexity score
- `calculate_documentation_score(tree: ast.AST) -> float` - Docstring + type hints score
- `calculate_test_coverage_score(file_path: str) -> float` - Test coverage percentage
- `calculate_reusability_score(usage_count: int) -> float` - Cross-file usage score
- `calculate_maintainability_score(tree: ast.AST, code: str) -> float` - Coupling + cohesion score
- `batch_calculate_quality(patterns: List[Dict]) -> List[Dict]` - Batch scoring

**Return Format**:
```python
{
    'quality_score': 0.7250,
    'components': {
        'complexity': 0.8500,
        'documentation': 0.5000,
        'test_coverage': 0.5000,
        'reusability': 0.6000,
        'maintainability': 0.7000,
    },
    'weights': {
        'complexity': 0.30,
        'documentation': 0.20,
        'test_coverage': 0.20,
        'reusability': 0.15,
        'maintainability': 0.15,
    },
    'reproducible': True
}
```

### C. Validation Query Reference

**Quick Health Check**:
```sql
-- Pattern quality score health check
SELECT
    COUNT(*) as total_patterns,
    COUNT(*) FILTER (WHERE overall_quality IS NOT NULL) as with_overall,
    COUNT(*) FILTER (WHERE complexity_score IS NOT NULL) as with_complexity,
    COUNT(*) FILTER (WHERE documentation_score IS NOT NULL) as with_documentation,
    COUNT(*) FILTER (WHERE maintainability_score IS NOT NULL) as with_maintainability,
    COUNT(*) FILTER (WHERE test_coverage_score IS NOT NULL) as with_test_coverage,
    COUNT(*) FILTER (WHERE reusability_score IS NOT NULL) as with_reusability,
    ROUND(AVG(overall_quality), 4) as avg_overall_quality
FROM pattern_lineage_nodes
WHERE pattern_data->>'code' IS NOT NULL
  AND pattern_data->>'code' != '-';
```

### D. Resources and References

**Documentation**:
- Empty Columns Analysis: `/Volumes/PRO-G40/Code/omniclaude/EMPTY_COLUMNS_ANALYSIS.md`
- PatternScorer: `/Volumes/PRO-G40/Code/Omniarchon/services/intelligence/src/services/quality/pattern_scorer.py`
- Database Schema: `omninode_bridge.pattern_lineage_nodes`

**Tools**:
- Radon: https://radon.readthedocs.io/
- Coverage.py: https://coverage.readthedocs.io/
- Ripgrep: https://github.com/BurntSushi/ripgrep

**SQL Queries**:
- All validation queries in Section 7: Testing Strategy
- Health check in Appendix C

---

## Document Control

**Version History**:
- v1.0.0 (2025-10-29): Initial plan created
- Future: Track implementation progress and learnings

**Approvals Required**:
- [ ] Technical Lead (Development approach)
- [ ] Database Administrator (Migration safety)
- [ ] Product Manager (Business value, priorities)

**Status Tracking**:
- Current Status: **Awaiting Approval**
- Next Review Date: **2025-11-01**
- Implementation Start: **Upon approval**

---

**End of Plan**
