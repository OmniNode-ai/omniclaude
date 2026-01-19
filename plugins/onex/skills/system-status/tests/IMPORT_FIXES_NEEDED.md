# Test Import Fixes Required

**Status**: 88 test failures due to incorrect import paths
**Impact**: Blocking 63.8% of tests from running correctly
**Priority**: HIGH (required before accurate testing possible)

---

## Problem Summary

All test files are importing from `check-agent-performance/execute.py` regardless of which skill they're testing. This causes `ImportError` and `AttributeError` for functions that don't exist in that file.

### Current Behavior (WRONG)

```python
# In tests/test_check_infrastructure.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-agent-performance"))
from execute import check_kafka  # ❌ Doesn't exist in check-agent-performance/execute.py
```

### Required Behavior (CORRECT)

```python
# In tests/test_check_infrastructure.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-infrastructure"))
from execute import check_kafka  # ✅ Exists in check-infrastructure/execute.py
```

---

## Files Requiring Import Path Fixes

### 1. test_check_infrastructure.py

**Current**: Imports from `check-agent-performance`
**Should Import From**: `check-infrastructure`
**Functions Needed**:
- `check_kafka()`
- `check_postgres()`
- `check_qdrant()`
- `main()`

**Fix**:
```python
# Line 7: Change this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-agent-performance"))

# To this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-infrastructure"))
```

**Tests Affected**: 10 tests (all failing)

---

### 2. test_check_kafka_topics.py

**Current**: Imports from `check-agent-performance`
**Should Import From**: `check-kafka-topics`
**Functions Needed**:
- `list_topics()`
- `filter_topics()`
- `main()`

**Fix**:
```python
# Line 7: Change this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-agent-performance"))

# To this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-kafka-topics"))
```

**Tests Affected**: 4 tests (all failing)

---

### 3. test_check_pattern_discovery.py

**Current**: Imports from `check-agent-performance`
**Should Import From**: `check-pattern-discovery`
**Functions Needed**:
- `get_all_collections_stats()`
- `format_collection_summary()`
- `main()`

**Fix**:
```python
# Line 7: Change this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-agent-performance"))

# To this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-pattern-discovery"))
```

**Tests Affected**: 4 tests (all failing)

---

### 4. test_check_service_status.py

**Current**: Imports from `check-agent-performance`
**Should Import From**: `check-service-status`
**Functions Needed**:
- `get_service_summary()`
- `filter_services()`
- `check_service_health()`
- `main()`

**Fix**:
```python
# Line 7: Change this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-agent-performance"))

# To this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-service-status"))
```

**Tests Affected**: 5 tests (all failing)

---

### 5. test_check_recent_activity.py

**Current**: Imports from `check-agent-performance`
**Should Import From**: `check-recent-activity`
**Functions Needed**:
- `validate_limit()`
- `get_manifest_stats()`
- `get_routing_stats()`
- `get_agent_actions()`
- `main()`

**Fix**:
```python
# Line 7: Change this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-agent-performance"))

# To this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-recent-activity"))
```

**Tests Affected**: 7 tests (failing due to imports and CLI args)

---

### 6. test_check_database_health.py

**Current**: Imports from `check-agent-performance`
**Should Import From**: `check-database-health`
**Functions Needed**:
- `validate_log_lines()`
- `get_connection_pool_stats()`
- `get_query_performance()`
- `get_recent_errors()`
- `main()`

**Fix**:
```python
# Line 7: Change this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-agent-performance"))

# To this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-database-health"))
```

**Tests Affected**: 4 tests (failing due to imports)

---

### 7. test_diagnose_issues.py

**Current**: Imports from `check-agent-performance`
**Should Import From**: `diagnose-issues`
**Functions Needed**:
- `check_infrastructure()`
- `detect_issues()`
- `classify_severity()`
- `main()`

**Fix**:
```python
# Line 7: Change this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-agent-performance"))

# To this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../diagnose-issues"))
```

**Tests Affected**: 5 tests (all failing)

---

### 8. test_generate_status_report.py

**Current**: Imports from `check-agent-performance`
**Should Import From**: `generate-status-report`
**Functions Needed**:
- `check_infrastructure()`
- `generate_report()`
- `format_report()`
- `main()`

**Fix**:
```python
# Line 7: Change this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-agent-performance"))

# To this
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../generate-status-report"))
```

**Tests Affected**: 3 tests (all failing)

---

### 9. test_input_validation.py

**Current**: Imports from `check-agent-performance`
**Should Import From**: Multiple skills (or create shared helpers)
**Functions Needed**:
- `validate_limit()` (from check-recent-activity)
- `validate_log_lines()` (from check-database-health)
- `validate_top_agents()` (from check-agent-performance)

**Fix Option 1 - Import from specific skills**:
```python
# Import from check-recent-activity
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-recent-activity"))
from execute import validate_limit

# Import from check-database-health
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-database-health"))
from execute import validate_log_lines

# Import from check-agent-performance (already correct)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-agent-performance"))
from execute import validate_top_agents
```

**Fix Option 2 - Create shared validators** (RECOMMENDED):
```python
# Create: skills/system-status/helpers/validators.py
def validate_limit(limit: int, min_val: int = 1, max_val: int = 1000) -> int:
    """Validate limit parameter."""
    # Implementation here

def validate_log_lines(lines: int, min_val: int = 1, max_val: int = 10000) -> int:
    """Validate log lines parameter."""
    # Implementation here

def validate_top_agents(count: int, min_val: int = 1, max_val: int = 100) -> int:
    """Validate top agents parameter."""
    # Implementation here

# Then in test file:
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../helpers"))
from validators import validate_limit, validate_log_lines, validate_top_agents
```

**Tests Affected**: 14 tests (all failing)

---

### 10. test_validators.py

**Current**: Imports from `check-agent-performance`
**Should Import From**: Shared helpers (if created) or multiple skills
**Functions Needed**:
- `validate_limit()`
- `validate_log_lines()`
- `validate_top_agents()`

**Fix**: Same as `test_input_validation.py` above

**Tests Affected**: 8 tests (failing due to imports)

---

### 11. test_sql_injection_prevention.py

**Current**: Imports from `check-agent-performance`
**Should Import From**: Multiple skills (tests SQL security across all skills)
**Functions Needed**:
- `validate_limit()` (for parameterization testing)

**Fix**: Use shared validators helper (Option 2 above)

**Tests Affected**: 8 tests (all errors at setup)

---

### 12. test_error_handling.py

**Current**: Imports from `check-agent-performance`
**Should Import From**: Multiple skills (tests error handling across skills)
**Functions Needed**:
- `check_postgres()` (from check-infrastructure)
- `check_kafka()` (from check-infrastructure)
- `check_qdrant()` (from check-infrastructure)

**Fix**:
```python
# Add after existing sys.path line:
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../check-infrastructure"))
from execute import check_postgres, check_kafka, check_qdrant
```

**Tests Affected**: 9 tests (failing due to imports)

---

## Summary of Required Changes

| Test File | Current Import | Should Import From | Tests Affected |
|-----------|----------------|-------------------|----------------|
| test_check_infrastructure.py | check-agent-performance | check-infrastructure | 10 |
| test_check_kafka_topics.py | check-agent-performance | check-kafka-topics | 4 |
| test_check_pattern_discovery.py | check-agent-performance | check-pattern-discovery | 4 |
| test_check_service_status.py | check-agent-performance | check-service-status | 5 |
| test_check_recent_activity.py | check-agent-performance | check-recent-activity | 7 |
| test_check_database_health.py | check-agent-performance | check-database-health | 4 |
| test_diagnose_issues.py | check-agent-performance | diagnose-issues | 5 |
| test_generate_status_report.py | check-agent-performance | generate-status-report | 3 |
| test_input_validation.py | check-agent-performance | Multiple (or helpers) | 14 |
| test_validators.py | check-agent-performance | Multiple (or helpers) | 8 |
| test_sql_injection_prevention.py | check-agent-performance | helpers/validators | 8 |
| test_error_handling.py | check-agent-performance | check-infrastructure | 9 |
| **TOTAL** | | | **81 tests** |

---

## Recommended Approach

### Phase 1: Create Shared Validators Helper (1 hour)

1. Create `skills/system-status/helpers/validators.py`
2. Move validation functions from individual skills:
   - `validate_limit()` (from check-recent-activity)
   - `validate_log_lines()` (from check-database-health)
   - `validate_top_agents()` (from check-agent-performance)
3. Update skills to import from shared helper
4. Update tests to import from shared helper

**Benefits**:
- DRY (Don't Repeat Yourself)
- Consistent validation across all skills
- Easier to test and maintain
- Fixes 30 tests (test_input_validation.py, test_validators.py, test_sql_injection_prevention.py)

---

### Phase 2: Fix Test Import Paths (2 hours)

Go through each test file and update the `sys.path.insert()` line to point to the correct skill directory.

**Order of Priority**:
1. test_check_infrastructure.py (10 tests)
2. test_check_recent_activity.py (7 tests)
3. test_error_handling.py (9 tests)
4. test_check_service_status.py (5 tests)
5. test_diagnose_issues.py (5 tests)
6. test_check_pattern_discovery.py (4 tests)
7. test_check_kafka_topics.py (4 tests)
8. test_check_database_health.py (4 tests)
9. test_generate_status_report.py (3 tests)

**Total**: 51 tests fixed

---

### Phase 3: Verify Fixes (30 minutes)

Run test suite after each phase:

```bash
# After Phase 1
pytest test_input_validation.py test_validators.py test_sql_injection_prevention.py -v

# After Phase 2
pytest -v

# Expected improvement: 81+ additional tests should now run correctly
```

---

## Expected Impact

**Before Fixes**:
- Pass Rate: 32.6% (45/138)
- Import Errors: 88
- Tests Blocked: 81

**After Fixes**:
- Pass Rate: ~70-80% (95-110/138)
- Import Errors: 0
- Tests Blocked: 0

The remaining failures will be actual logic/implementation issues that need to be fixed in the skill code, not test infrastructure problems.

---

## Verification Commands

```bash
# Test individual file after fix
pytest test_check_infrastructure.py -v

# Test all files
pytest -v --tb=short

# Generate new summary
pytest -v > test_results_after_import_fixes.txt 2>&1

# Compare before/after
diff test_results_full.txt test_results_after_import_fixes.txt
```

---

## Notes

- All test files were created from a template that incorrectly used `check-agent-performance` as the import path
- This is a systematic issue affecting 12 of 17 test files
- The fix is straightforward: change one line per file
- Creating shared validators is recommended but optional (can import from individual skills instead)
- After import fixes, tests will reveal actual bugs in the skill implementations
