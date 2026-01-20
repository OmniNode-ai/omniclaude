# Test Coverage Plan: 50% → 60%

**Generated:** 2025-11-01
**Correlation ID:** be2cd24c-b2cc-4149-8e18-6433bd0fba00
**Agent:** polymorphic-agent

---

## Executive Summary

**Current State:**
- Coverage: **50.2%** (13,750 / 27,384 statements covered)
- Missing: 13,634 statements

**Target State:**
- Coverage: **60.0%** (16,430 / 27,384 statements)
- Additional coverage needed: **2,680 statements**

**Strategy:**
Focus on high-impact files with low or zero coverage. By covering the **first 9 files** from the priority list, we will exceed the 60% target.

---

## Coverage Analysis Results

### Distribution by Coverage Level

| Coverage Range | Files | Statements | Impact |
|---------------|-------|-----------|--------|
| 0% (No tests) | 18 files | 1,386 stmts | High Priority |
| 1-20% (Critical gaps) | 23 files | 5,847 stmts | High Priority |
| 21-40% (Partial) | 12 files | 2,891 stmts | Medium Priority |
| 41-60% (Moderate) | 8 files | 1,423 stmts | Low Priority |
| 61%+ (Good) | 90+ files | 15,837 stmts | Maintain |

### Top 20 Highest Impact Files (Ranked by Missing Statements)

| Rank | File | Statements | Missing | Coverage | Impact |
|------|------|-----------|---------|----------|--------|
| 1 | `agents/lib/quality_validator.py` | 591 | 521 | 11.8% | **Critical** |
| 2 | `agents/lib/omninode_template_engine.py` | 609 | 470 | 22.8% | **Critical** |
| 3 | `tools/compatibility_validator.py` | 305 | 305 | 0.0% | **High** |
| 4 | `agents/tests/test_template_cache.py` | 333 | 292 | 12.3% | High |
| 5 | `agents/tests/test_performance_optimizations.py` | 292 | 283 | 3.1% | High |
| 6 | `agents/tests/test_pattern_quality_scorer.py` | 347 | 273 | 21.3% | High |
| 7 | `agents/tests/test_performance_tracking.py` | 303 | 267 | 11.9% | High |
| 8 | `agents/lib/validators/quality_compliance_validators.py` | 282 | 252 | 10.6% | **Critical** |
| 9 | `agents/lib/warning_fixer.py` | 286 | 251 | 12.2% | **Critical** |
| 10 | `agents/lib/mixin_learner.py` | 299 | 233 | 22.1% | High |
| 11 | `agents/lib/manifest_injector.py` | 980 | 206 | 79.0% | Medium |
| 12 | `agents/lib/codegen_workflow.py` | 211 | 177 | 16.1% | **Critical** |
| 13 | `cli/commands/query.py` | 177 | 177 | 0.0% | **High** |
| 14 | `agents/lib/agent_router.py` | 205 | 174 | 15.1% | **Critical** |
| 15 | `cli/hook_agent_health_dashboard.py` | 174 | 174 | 0.0% | **High** |
| 16 | `agents/lib/validators/sequential_validators.py` | 199 | 182 | 8.5% | **Critical** |
| 17 | `agents/lib/validators/parallel_validators.py` | 170 | 158 | 7.1% | **Critical** |
| 18 | `cli/generate_node.py` | 153 | 153 | 0.0% | **High** |
| 19 | `agents/lib/prompt_parser.py` | 167 | 149 | 10.8% | High |
| 20 | `tools/node_gen/file_writer.py` | 124 | 124 | 0.0% | **High** |

**Key Insight:** Covering files ranked 1-9 alone provides 2,967 missing statements, exceeding our 2,680 target by 287 statements.

---

## Priority-Based Test Plan

### Priority 1: Quick Wins (0% Coverage CLI/Tools) 🎯

**Impact:** 933 missing statements
**Complexity:** Low
**Dependencies:** None
**Parallel:** Yes

| File | Statements | Type | Suggested Tests |
|------|-----------|------|-----------------|
| `tools/compatibility_validator.py` | 305 | Unit | - Validation logic tests<br>- Error handling<br>- Edge cases for compatibility checks |
| `cli/commands/query.py` | 177 | Unit | - Query parsing tests<br>- Database query execution<br>- Output formatting |
| `cli/hook_agent_health_dashboard.py` | 174 | Unit | - Dashboard rendering<br>- Health status collection<br>- Metrics display |
| `cli/generate_node.py` | 153 | Unit | - Node generation workflow<br>- Template application<br>- File creation |
| `tools/node_gen/file_writer.py` | 124 | Unit | - File write operations<br>- Path validation<br>- Overwrite protection |

**Test File Locations:**
- `agents/tests/tools/test_compatibility_validator.py`
- `agents/tests/cli/test_query_commands.py`
- `agents/tests/cli/test_health_dashboard.py`
- `agents/tests/cli/test_generate_node.py`
- `agents/tests/tools/test_file_writer.py`

---

### Priority 2: Core Library (Low Coverage, High Impact) 🔥

**Impact:** 1,770 missing statements
**Complexity:** Medium-High
**Dependencies:** Moderate (may need mocking)
**Parallel:** Partially

| File | Statements | Missing | Type | Suggested Tests |
|------|-----------|---------|------|-----------------|
| `agents/lib/quality_validator.py` | 591 | 521 | Unit | - Each validation rule (23 quality gates)<br>- Threshold checks<br>- Validation result aggregation<br>- Error handling for malformed input |
| `agents/lib/omninode_template_engine.py` | 609 | 470 | Unit | - Template parsing<br>- Variable substitution<br>- Include directives<br>- Error handling for invalid templates |
| `agents/lib/warning_fixer.py` | 286 | 251 | Unit | - Warning detection<br>- Fix application<br>- Code preservation<br>- Batch processing |
| `agents/lib/mixin_learner.py` | 299 | 233 | Unit | - Pattern learning<br>- Capability extraction<br>- Confidence scoring<br>- Cache behavior |
| `agents/lib/agent_router.py` | 205 | 174 | Unit | - Route matching<br>- Agent selection<br>- Confidence scoring<br>- Fallback logic |
| `agents/lib/pattern_library.py` | 137 | 119 | Unit | - Pattern storage/retrieval<br>- Pattern matching<br>- Similarity scoring<br>- Cache behavior |

**Test File Locations:**
- `agents/tests/test_quality_validator_extended.py` (extend existing)
- `agents/tests/test_template_engine_extended.py` (new)
- `agents/tests/test_warning_fixer_extended.py` (extend existing)
- `agents/tests/test_mixin_learner_extended.py` (new)
- `agents/tests/test_agent_router_extended.py` (new)
- `agents/tests/test_pattern_library_extended.py` (extend existing)

---

### Priority 3: Validators (Critical Quality Gates) ⚠️

**Impact:** 592 missing statements
**Complexity:** Medium
**Dependencies:** Low (mostly pure logic)
**Parallel:** Yes

| File | Statements | Missing | Type | Suggested Tests |
|------|-----------|---------|------|-----------------|
| `agents/lib/validators/quality_compliance_validators.py` | 282 | 252 | Unit | - ONEX compliance checks<br>- File naming validation<br>- Contract validation<br>- Type hint validation |
| `agents/lib/validators/sequential_validators.py` | 199 | 182 | Unit | - Input validation tests<br>- Process validation tests<br>- Output validation tests<br>- Error propagation |
| `agents/lib/validators/parallel_validators.py` | 170 | 158 | Unit | - Coordination validation<br>- Result aggregation<br>- Timeout handling<br>- Failure scenarios |

**Test File Locations:**
- `agents/tests/test_quality_compliance_validators_extended.py` (extend existing)
- `agents/tests/test_sequential_validators_extended.py` (extend existing)
- `agents/tests/test_parallel_validators_extended.py` (extend existing)

---

### Priority 4: Workflow & Routing (Integration Critical) 🔄

**Impact:** 351 missing statements
**Complexity:** High
**Dependencies:** High (integration tests)
**Parallel:** No

| File | Statements | Missing | Type | Suggested Tests |
|------|-----------|---------|------|-----------------|
| `agents/lib/codegen_workflow.py` | 211 | 177 | Integration | - End-to-end workflow execution<br>- Stage transitions<br>- Error recovery<br>- State management |

**Test File Locations:**
- `agents/tests/test_codegen_workflow_integration.py` (new)

---

### Priority 5: Pattern Systems (Feature Enhancement) 🧩

**Impact:** 352 missing statements
**Complexity:** Medium
**Dependencies:** Medium
**Parallel:** Yes

| File | Statements | Missing | Type | Suggested Tests |
|------|-----------|---------|------|-----------------|
| `agents/lib/pattern_feedback.py` | 176 | 127 | Unit | - Feedback collection<br>- Rating aggregation<br>- Feedback analysis<br>- Storage operations |
| `agents/lib/patterns/pattern_storage.py` | 146 | 106 | Unit | - Pattern persistence<br>- Query operations<br>- Cache invalidation<br>- Concurrent access |

**Test File Locations:**
- `agents/tests/test_pattern_feedback_extended.py` (extend existing)
- `agents/tests/patterns/test_pattern_storage.py` (new)

---

## Parallel Execution Strategy

### Group A: CLI Commands (Fully Independent)
**Developers:** 1-2
**Timeline:** 0.5 day
**Coverage Gain:** +500 statements

```
cli/
├── test_query_commands.py       (177 stmts)
├── test_health_dashboard.py     (174 stmts)
└── test_generate_node.py        (153 stmts)
```

### Group B: Tools & Validators (Independent)
**Developers:** 2
**Timeline:** 1 day
**Coverage Gain:** +1,000 statements

```
agents/tests/
├── tools/
│   ├── test_compatibility_validator.py    (305 stmts)
│   └── test_file_writer.py                (124 stmts)
└── validators/
    ├── test_quality_compliance_extended.py (252 stmts)
    ├── test_sequential_extended.py         (182 stmts)
    └── test_parallel_extended.py           (158 stmts)
```

### Group C: Core Libraries (Some Dependencies)
**Developers:** 2-3
**Timeline:** 1.5 days
**Coverage Gain:** +1,500 statements

```
agents/tests/
├── test_quality_validator_extended.py   (521 stmts)
├── test_template_engine_extended.py     (470 stmts)
├── test_warning_fixer_extended.py       (251 stmts)
├── test_mixin_learner_extended.py       (233 stmts)
├── test_agent_router_extended.py        (174 stmts)
└── test_pattern_library_extended.py     (119 stmts)
```

### Group D: Pattern Systems (Integration)
**Developers:** 1
**Timeline:** 0.5 day
**Coverage Gain:** +350 statements

```
agents/tests/
├── test_pattern_feedback_extended.py      (127 stmts)
└── patterns/test_pattern_storage.py       (106 stmts)
```

---

## Test Development Guidelines

### Test Structure Template

```python
"""
Test module for [MODULE_NAME]
Coverage target: [TARGET]%
Current coverage: [CURRENT]%
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from [module] import [ClassOrFunction]


class Test[Feature]:
    """Test suite for [feature] functionality."""

    @pytest.fixture
    def setup(self):
        """Setup test fixtures."""
        # Initialize test data
        pass

    def test_[scenario]_success(self, setup):
        """Test successful [scenario]."""
        # Arrange
        # Act
        # Assert
        pass

    def test_[scenario]_failure(self, setup):
        """Test failure handling for [scenario]."""
        # Arrange
        # Act
        # Assert
        pass

    def test_[scenario]_edge_case(self, setup):
        """Test edge case for [scenario]."""
        # Arrange
        # Act
        # Assert
        pass


class Test[Component]Integration:
    """Integration tests for [component]."""

    @pytest.mark.integration
    def test_end_to_end_workflow(self):
        """Test complete workflow from start to finish."""
        pass
```

### Coverage Best Practices

1. **Aim for meaningful coverage, not just line coverage**
   - Test behavior, not implementation
   - Focus on critical paths and error handling
   - Include edge cases and boundary conditions

2. **Use appropriate test types**
   - Unit tests: Single function/method behavior
   - Integration tests: Component interaction
   - End-to-end tests: Complete workflows

3. **Mock external dependencies**
   - Database connections
   - API calls
   - File system operations
   - Kafka/event bus interactions

4. **Leverage existing patterns**
   - Check `agents/tests/test_*.py` for examples
   - Reuse test fixtures from `conftest.py`
   - Follow existing naming conventions

5. **Performance considerations**
   - Keep unit tests under 100ms
   - Use `@pytest.mark.slow` for longer tests
   - Parallelize test execution with pytest-xdist

---

## Execution Plan

### Phase 1: Reach 60% (Primary Goal) ✅

**Timeline:** 3-4 days with 3 developers
**Coverage Gain:** +10% (50% → 60%)

#### Week 1, Day 1-2
- **Developer 1:** Group A (CLI Commands) - 500 statements
- **Developer 2:** Group B Part 1 (Tools) - 429 statements
- **Developer 3:** Priority 2 File #1 (quality_validator.py) - 521 statements

**Total Day 1-2:** +1,450 statements (55.5% coverage)

#### Week 1, Day 3-4
- **Developer 1:** Group B Part 2 (Validators) - 592 statements
- **Developer 2:** Priority 2 File #2 (template_engine.py) - 470 statements
- **Developer 3:** Priority 2 File #3 (warning_fixer.py) - 251 statements

**Total Day 3-4:** +1,313 statements (60.3% coverage) ✅

### Phase 2: Reach 70% (Stretch Goal) 🎯

**Timeline:** Additional 5-6 days
**Coverage Gain:** +10% (60% → 70%)

Focus on next 20 files from impact ranking.

---

## Test Estimation Summary

| Priority | Files | Statements | Tests Needed | Effort (days) | Developers |
|----------|-------|-----------|--------------|---------------|-----------|
| Priority 1 | 5 | 933 | 80-120 | 0.5 | 1-2 |
| Priority 2 | 6 | 1,770 | 150-200 | 1.5 | 2-3 |
| Priority 3 | 3 | 592 | 50-70 | 1.0 | 2 |
| Priority 4 | 1 | 177 | 20-30 | 0.5 | 1 |
| Priority 5 | 2 | 233 | 25-35 | 0.5 | 1 |
| **Total** | **17** | **3,705** | **325-455** | **4.0** | **3** |

---

## Success Metrics

### Coverage Targets
- [x] Current: 50.2%
- [ ] Target: 60.0%
- [ ] Stretch: 70.0%

### Quality Metrics
- Minimum 80% pass rate on first run
- No test failures in CI/CD
- Test execution time: <5 minutes for full suite
- Code review approval for all new tests

### File-Level Targets

| File | Current | Target | Tests |
|------|---------|--------|-------|
| quality_validator.py | 11.8% | 60%+ | 40-50 |
| omninode_template_engine.py | 22.8% | 60%+ | 35-45 |
| compatibility_validator.py | 0% | 80%+ | 30-40 |
| quality_compliance_validators.py | 10.6% | 60%+ | 25-30 |
| warning_fixer.py | 12.2% | 60%+ | 25-30 |

---

## Tools & Commands

### Run Coverage Analysis
```bash
# Full coverage report
python -m pytest --cov=. --cov-report=term --cov-report=html

# Coverage for specific module
python -m pytest --cov=agents/lib --cov-report=term agents/tests/

# Generate JSON report for analysis
python -m pytest --cov=. --cov-report=json

# HTML report (opens in browser)
python -m pytest --cov=. --cov-report=html && open htmlcov/index.html
```

### Run Specific Test Groups
```bash
# Run CLI tests only
pytest agents/tests/cli/

# Run validator tests
pytest agents/tests/ -k "validator"

# Run with parallel execution
pytest -n auto agents/tests/

# Run only fast tests
pytest -m "not slow" agents/tests/
```

### Monitor Progress
```bash
# Track coverage over time
python -m coverage report --skip-covered | grep -E "TOTAL|quality_validator|template_engine"

# Check specific file coverage
python -m coverage report --include="agents/lib/quality_validator.py"
```

---

## Risk Mitigation

### Potential Blockers

1. **Complex Dependencies**
   - Risk: Difficult to mock Kafka, PostgreSQL, Qdrant
   - Mitigation: Use test containers or in-memory alternatives
   - Fallback: Integration tests with real services

2. **Test Isolation**
   - Risk: Tests interfere with each other
   - Mitigation: Proper fixture cleanup, unique test data
   - Fallback: Run tests sequentially with `pytest -n0`

3. **Long Test Execution**
   - Risk: CI/CD pipeline becomes slow
   - Mitigation: Mark slow tests, parallelize with xdist
   - Fallback: Split test suite into fast/slow categories

4. **Flaky Tests**
   - Risk: Non-deterministic test failures
   - Mitigation: Proper mocking, avoid sleep/timing dependencies
   - Fallback: Use `pytest-rerunfailures` for retry logic

---

## Appendix

### Coverage by Module

| Module | Files | Statements | Coverage |
|--------|-------|-----------|----------|
| agents/lib | 45 | 8,234 | 48.3% |
| agents/tests | 72 | 10,567 | 52.1% |
| cli | 12 | 1,823 | 5.2% |
| tools | 8 | 1,456 | 12.7% |
| shared_lib | 3 | 234 | 15.8% |

### References

- [Python Coverage Documentation](https://coverage.readthedocs.io/)
- [Pytest Best Practices](https://docs.pytest.org/en/stable/goodpractices.html)
- [Testing Best Practices (Internal)](docs/testing/BEST_PRACTICES.md)
- [ONEX Testing Standards](docs/onex/TESTING_STANDARDS.md)

---

**Document Version:** 1.0
**Last Updated:** 2025-11-01
**Next Review:** After reaching 60% coverage target
