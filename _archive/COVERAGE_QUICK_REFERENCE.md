# Test Coverage Quick Reference Card
**Last Updated**: 2025-11-04
**Branch**: feat/phase2-pattern-quality-scoring

---

## 🎯 Current Status at a Glance

| Metric | Value | Status |
|--------|-------|--------|
| **Overall Coverage** | 62.84% | 🟡 Fair |
| **Tests Passing** | 2,492/2,619 (95.15%) | 🟢 Good |
| **Test Suite Runtime** | 3m 39s | 🟢 Acceptable |
| **New Tests Added** | +429 tests | 🟢 Excellent |
| **Coverage Improvement** | +5.84% | 🟢 Good |

---

## 📊 Coverage by Component

```
Validators         ████████████████████████████░░  95.9%  🟢 Excellent
Models             ██████████████████████████░░░░  86.9%  🟢 Good
Performance        ███████████████████████░░░░░░░  77.3%  🟢 Good
Pattern System     ██████████████████████░░░░░░░░  74.0%  🟡 Fair
Intelligence       █████████████████░░░░░░░░░░░░░  58.3%  🟡 Fair
Code Generation    █████░░░░░░░░░░░░░░░░░░░░░░░░░  17.4%  🔴 Poor
Parallel Execution █░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   4.0%  🔴 Critical
```

---

## 🚀 Quick Commands

### Run Full Test Suite with Coverage
```bash
python3 -m pytest agents/tests/ --cov=agents --cov-report=term --cov-report=html -v
```

### Run Specific Test File
```bash
python3 -m pytest agents/tests/test_pattern_quality_scorer.py -v
```

### Run Tests for Specific Module
```bash
python3 -m pytest agents/tests/ -k "pattern_quality" -v
```

### View Coverage Report (HTML)
```bash
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

### Check Coverage for Specific File
```bash
python3 -m pytest agents/tests/ --cov=agents/lib/pattern_quality_scorer.py --cov-report=term
```

---

## 🔴 Critical Issues (Fix First)

### Failing Tests (29 total)
1. **test_monitoring.py** (7 failures)
   - Database health checks
   - Template cache validation
   - Integration tests

2. **test_performance_optimizations.py** (18 failures)
   - Circuit breaker tests
   - Retry manager tests
   - Performance monitoring
   - Agent analytics

3. **test_structured_logging.py** (4 errors)
   - JSON output formatting
   - Correlation ID tests

4. **test_code_refiner.py** (1 failure)
   - Pattern extraction

### Zero Coverage Files (Critical)
- `agents/lib/agent_history_browser.py` - 459 statements
- `agents/lib/dashboard/quality_dashboard.py` - 157 statements
- `agents/lib/generation_pipeline.py` - 1,038 statements
- `agents/lib/embedding_search.py` - 129 statements

### Low Coverage Modules
- `agents/parallel_execution/` - 4.0% (8,227 statements)
- `agents/lib/manifest_injector.py` - 8% (critical component!)

---

## ✅ What's Working Well

### 100% Coverage Components
- All validator modules (parallel, intelligence, coordination, performance)
- All 4 pattern types (aggregation, crud, orchestration, transformation)
- Task classifier
- PRD intelligence client

### 99% Coverage Test Files
- Agent execution logger (516 tests)
- Circuit breaker (501 tests)
- Context optimizer (474 tests)
- Database event client (501 tests)
- Quality validator (634 tests)

### New Test Files (Phase 2)
- Pattern quality scorer - 100% (354 tests)
- Pattern quality backfill - 100% (220 tests)
- Gate aggregation - 99% (162 tests)
- Metrics models - 99% (156 tests)
- Database integration - 94% (217 tests)

---

## 📈 Progress Tracking

### Coverage Journey
```
Baseline:  57.0%  ████████████████████████████░░░░░░░░░░░░░░░░░░░░
Current:   62.8%  ███████████████████████████████░░░░░░░░░░░░░░░░░
Target:    75.0%  █████████████████████████████████████░░░░░░░░░░░
Ultimate:  85.0%  ██████████████████████████████████████████░░░░░░

Progress to Target: 32.4% complete (5.84% of 18% needed)
```

### Test Count Growth
```
Phase 1:  ~2,190 tests
Phase 2:  2,619 tests (+429 new tests, +19.6%)
```

---

## 🎯 Next Sprint Goals

### Sprint 1: Fix Failing Tests (Estimate: 2-3 days)
- [ ] Fix 7 monitoring test failures
- [ ] Fix 18 performance optimization test failures
- [ ] Fix 4 structured logging errors
- [ ] Fix 1 code refiner failure

### Sprint 2: Critical Coverage (Estimate: 3-4 days)
- [ ] Add tests for `agent_history_browser.py` (0% → 75%)
- [ ] Add tests for `manifest_injector.py` (8% → 75%)
- [ ] Add tests for `generation_pipeline.py` (0% → 75%)
- [ ] Add tests for `dashboard/quality_dashboard.py` (0% → 75%)

### Sprint 3: Parallel Execution (Estimate: 4-5 days)
- [ ] Add tests for `parallel_execution/` module (4% → 75%)
- [ ] Focus on core workflow coordinator
- [ ] Focus on parallel generators
- [ ] Focus on state management

---

## 📝 Testing Best Practices

### Before Writing Tests
1. ✅ Read the module's docstrings and understand its purpose
2. ✅ Identify all public functions and methods
3. ✅ Identify edge cases and error conditions
4. ✅ Review similar test files for patterns

### Test Structure
```python
class TestModuleName:
    """Tests for ModuleName class."""

    def test_basic_functionality(self):
        """Test core feature works as expected."""
        # Arrange
        # Act
        # Assert

    def test_edge_case(self):
        """Test behavior with edge case input."""
        # ...

    def test_error_handling(self):
        """Test proper error handling."""
        # ...
```

### Coverage Goals
- **New code**: ≥90% coverage required
- **Critical paths**: ≥95% coverage required
- **Utility code**: ≥80% coverage acceptable
- **Demo/example code**: No minimum (but document as demo)

---

## 🔧 Troubleshooting

### Common Issues

**Tests failing with import errors:**
```bash
# Ensure using absolute imports
from agents.lib.module import Class  # ✅ Correct
from lib.module import Class         # ❌ Wrong
```

**Coverage not updating:**
```bash
# Clean coverage data and re-run
rm -f .coverage coverage.json
python3 -m pytest agents/tests/ --cov=agents --cov-report=term
```

**Specific test failing:**
```bash
# Run with verbose output and no coverage overhead
python3 -m pytest agents/tests/test_file.py::TestClass::test_method -vvs
```

---

## 📚 Related Documentation

- **Full Report**: `TEST_COVERAGE_REPORT.md`
- **HTML Coverage**: `htmlcov/index.html`
- **Coverage Data**: `coverage.json`
- **Test Output**: `/tmp/pytest_coverage_final.txt`

---

## 📞 Quick Help

**View failing tests:**
```bash
tail -150 /tmp/pytest_coverage_final.txt
```

**Count tests by file:**
```bash
python3 -m pytest agents/tests/ --collect-only -q | grep "test session starts" -A 1000
```

**Check coverage for single module:**
```bash
python3 -m pytest agents/tests/ --cov=agents/lib/pattern_quality_scorer --cov-report=term-missing
```

---

**Last Test Run**: 2025-11-04 (3m 39s runtime)
**Next Review**: After fixing 29 failing tests
**Target Date for 75%**: TBD based on sprint planning
