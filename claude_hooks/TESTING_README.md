# Polymorphic Agent Framework - Testing Guide

**Version**: 1.0.0
**Last Updated**: 2025-10-10
**Status**: Ready for Testing

## Quick Start

```bash
# Install dependencies
cd ~/.claude/hooks
pip3 install pytest pytest-cov pytest-xdist pyyaml

# Run all tests
./run_tests.sh all

# Run fast tests only (recommended for development)
./run_tests.sh fast

# Run with coverage
./run_tests.sh coverage
```

## Test Structure

```
~/.claude/hooks/
├── tests/
│   ├── test_agent_detection.py      # 3-stage detection pipeline tests
│   ├── test_hook_lifecycle.py       # Complete hook integration tests
│   ├── test_database_integration.py # Database and event logging tests
│   └── hook_validation/             # Existing validation tests
├── run_tests.sh                     # Test runner script
├── pytest.ini                       # Pytest configuration
└── TESTING_README.md               # This file
```

## Test Categories

### 1. Unit Tests (`-m unit`)

**Fast, isolated tests (<100ms per test)**

- Agent detection (pattern, trigger, AI)
- Metadata extraction
- Correlation management
- Quality enforcement
- Individual hook components

**Run:**
```bash
./run_tests.sh unit
```

**Coverage Target**: ≥95%

### 2. Integration Tests (`-m integration`)

**Moderate speed tests (<500ms per test)**

- Hook pipeline integration
- Database event logging
- Correlation ID propagation
- Intelligence system integration
- Multi-hook workflows

**Run:**
```bash
./run_tests.sh integration
```

**Coverage Target**: ≥90%

### 3. End-to-End Tests (`-m e2e`)

**Full system tests (<5s per test)**

- Complete agent workflows
- UserPromptSubmit → PreToolUse → PostToolUse
- Session lifecycle (start → work → end)
- Multi-agent coordination
- Real-world scenarios

**Run:**
```bash
./run_tests.sh e2e
```

**Coverage Target**: ≥85%

### 4. Performance Tests (`-m performance`)

**Benchmarking and load tests**

- Hook overhead measurement
- Database query performance
- Agent detection latency
- Concurrent session handling
- Load testing (100+ concurrent)

**Run:**
```bash
./run_tests.sh performance
```

**Performance Targets**:
- Pattern detection: <2ms
- Trigger matching: <10ms
- AI selection: <3000ms
- Hook overhead: <50ms

## Test Runner Commands

### Basic Commands

```bash
# Run all tests (full suite, ~5-10 minutes)
./run_tests.sh all

# Run fast tests (unit + integration, ~1-2 minutes)
./run_tests.sh fast

# Run specific category
./run_tests.sh unit
./run_tests.sh integration
./run_tests.sh e2e
./run_tests.sh performance

# Run specific test file
./run_tests.sh specific tests/test_agent_detection.py

# Run specific test function
cd ~/.claude/hooks
pytest tests/test_agent_detection.py::TestPatternDetection::test_explicit_at_syntax -v
```

### Advanced Commands

```bash
# Run with coverage analysis
./run_tests.sh coverage
# Opens htmlcov/index.html with coverage report

# Run in parallel (faster)
./run_tests.sh parallel

# Watch mode (auto-rerun on changes)
./run_tests.sh watch

# CI/CD optimized
./run_tests.sh ci

# Check dependencies
./run_tests.sh check

# Install test dependencies
./run_tests.sh install

# Show test statistics
./run_tests.sh stats

# Generate test report
./run_tests.sh report
```

### Custom Pytest Commands

```bash
cd ~/.claude/hooks

# Run tests matching keyword
pytest -k "agent_detection" -v

# Run tests with detailed output
pytest tests/ -vv --tb=long

# Run tests and stop on first failure
pytest tests/ -x

# Run tests with print statements
pytest tests/ -s

# Run only failed tests from last run
pytest --lf

# Show 20 slowest tests
pytest --durations=20

# Run with specific markers
pytest -m "unit and not slow"
pytest -m "integration or e2e"
```

## Test Configuration

### Pytest Markers

Tests are organized using pytest markers:

```python
@pytest.mark.unit           # Unit tests
@pytest.mark.integration    # Integration tests
@pytest.mark.e2e            # End-to-end tests
@pytest.mark.performance    # Performance benchmarks
@pytest.mark.slow           # Slow tests (>1s)
@pytest.mark.database       # Requires database
@pytest.mark.ai             # Requires AI model
@pytest.mark.network        # Requires network
```

### Environment Variables

Configure test behavior with environment variables:

```bash
# Disable AI selection (use pattern + trigger only)
export ENABLE_AI_AGENT_SELECTION=false

# AI model preference
export AI_MODEL_PREFERENCE=5090  # or auto, gemini, glm

# AI confidence threshold
export AI_AGENT_CONFIDENCE_THRESHOLD=0.8

# AI selection timeout
export AI_SELECTION_TIMEOUT_MS=3000

# Database connection (for integration tests)
export PGHOST=localhost
export PGPORT=5436
export PGDATABASE=omninode_bridge
export PGUSER=postgres
export PGPASSWORD="${PGPASSWORD}"  # Set your database password

# Archon MCP URLs
export ARCHON_MCP_URL=http://localhost:8051
export ARCHON_INTELLIGENCE_URL=http://localhost:8053
```

## Writing New Tests

### Test Template

```python
#!/usr/bin/env python3
"""
Test module description.

Tests:
- Feature 1
- Feature 2
"""

import pytest
import sys
from pathlib import Path

# Add lib to path
HOOKS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(HOOKS_DIR / "lib"))

from my_module import MyClass


@pytest.fixture
def my_fixture():
    """Fixture description."""
    return MyClass()


@pytest.mark.unit
class TestMyFeature:
    """Test class description."""

    def test_basic_functionality(self, my_fixture):
        """Test description."""
        result = my_fixture.do_something()
        assert result == expected

    @pytest.mark.performance
    def test_performance(self, my_fixture):
        """Test meets performance target."""
        import time

        start = time.time()
        my_fixture.do_something()
        elapsed_ms = (time.time() - start) * 1000

        assert elapsed_ms < 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

### Best Practices

1. **Use Descriptive Names**
   ```python
   # Good
   def test_agent_detection_with_explicit_pattern():
       pass

   # Bad
   def test_1():
       pass
   ```

2. **One Assertion Per Test** (when possible)
   ```python
   # Good
   def test_returns_agent_name():
       assert result.agent_name == "agent-testing"

   def test_returns_high_confidence():
       assert result.confidence > 0.9
   ```

3. **Use Fixtures for Setup**
   ```python
   @pytest.fixture
   def sample_data():
       return {"key": "value"}

   def test_with_fixture(sample_data):
       assert sample_data["key"] == "value"
   ```

4. **Mark Tests Appropriately**
   ```python
   @pytest.mark.unit
   def test_fast():
       pass

   @pytest.mark.integration
   @pytest.mark.database
   def test_with_db():
       pass
   ```

5. **Test Error Conditions**
   ```python
   def test_handles_missing_file():
       with pytest.raises(FileNotFoundError):
           load_config("nonexistent.yaml")
   ```

## Continuous Integration

### GitHub Actions

```yaml
# .github/workflows/test.yml
name: Test Polymorphic Agents

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          cd ~/.claude/hooks  # Adjust path
          pip install -r requirements.txt
          pip install pytest pytest-cov

      - name: Run tests
        run: |
          cd ~/.claude/hooks
          ./run_tests.sh ci

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

### Pre-commit Hook

```bash
# .git/hooks/pre-commit
#!/bin/bash
cd ~/.claude/hooks
./run_tests.sh fast

if [ $? -ne 0 ]; then
    echo "Tests failed! Commit aborted."
    exit 1
fi
```

## Troubleshooting

### Common Issues

#### 1. Import Errors
```bash
# Ensure lib directory is in Python path
export PYTHONPATH="${HOME}/.claude/hooks/lib:${PYTHONPATH}"
```

#### 2. Database Connection Errors
```bash
# Check database is running
psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"

# Check environment variables
echo $PGHOST $PGPORT $PGDATABASE
```

#### 3. AI Selection Timeouts
```bash
# Disable AI for faster tests
export ENABLE_AI_AGENT_SELECTION=false

# Or increase timeout
export AI_SELECTION_TIMEOUT_MS=5000
```

#### 4. Slow Tests
```bash
# Run unit tests only
./run_tests.sh unit

# Skip slow tests
pytest -m "not slow"

# Run in parallel
./run_tests.sh parallel
```

### Debug Mode

```bash
# Run with verbose output
pytest tests/ -vv --tb=long

# Show print statements
pytest tests/ -s

# Drop into debugger on failure
pytest tests/ --pdb

# Show local variables on failure
pytest tests/ -l
```

## Performance Optimization

### Speed Up Tests

1. **Use Mocks** for external dependencies
   ```python
   @patch('module.external_api')
   def test_with_mock(mock_api):
       mock_api.return_value = "mocked"
   ```

2. **Run in Parallel**
   ```bash
   ./run_tests.sh parallel
   ```

3. **Skip Slow Tests** during development
   ```bash
   pytest -m "not slow and not e2e"
   ```

4. **Use Fixtures Wisely**
   ```python
   @pytest.fixture(scope="module")  # Share across tests
   def expensive_setup():
       pass
   ```

## Test Coverage

### View Coverage Report

```bash
# Generate HTML coverage report
./run_tests.sh coverage

# Open in browser
open ~/.claude/hooks/htmlcov/index.html
```

### Coverage Targets

| Component | Target | Current |
|-----------|--------|---------|
| Agent Detection | 100% | TBD |
| Hook Lifecycle | 100% | TBD |
| Database Integration | 95% | TBD |
| Metadata Extraction | 95% | TBD |
| Correlation Manager | 95% | TBD |
| **Overall** | **90%** | **TBD** |

### Improve Coverage

```bash
# Find untested code
pytest --cov=lib --cov-report=term-missing

# Focus on specific module
pytest --cov=lib.hybrid_agent_selector --cov-report=html tests/test_agent_detection.py
```

## Test Results

### Expected Test Counts

```
tests/test_agent_detection.py      ~40 tests
tests/test_hook_lifecycle.py       ~35 tests
tests/test_database_integration.py ~30 tests
───────────────────────────────────────────
Total:                             ~105 tests
```

### Performance Benchmarks

```
Pattern Detection:      <2ms avg
Trigger Matching:       <10ms avg
Metadata Extraction:    <15ms avg
UserPromptSubmit Hook:  <50ms avg
PreToolUse Hook:        <150ms avg
PostToolUse Hook:       <250ms avg
Full Test Suite:        <5 minutes
```

## Support

### Getting Help

1. **Check Test Plan**: `POLYMORPHIC_AGENT_TEST_PLAN.md`
2. **Review Implementation**: Check `tests/` directory
3. **Run Diagnostics**: `./run_tests.sh check`
4. **View Logs**: Check `~/.claude/hooks/logs/`

### Reporting Issues

When reporting test failures, include:

1. Test command used
2. Full error output
3. Environment variables
4. Python version
5. Pytest version

```bash
# Gather diagnostics
python3 --version
pytest --version
./run_tests.sh stats
```

---

**Ready to Test!** Start with: `./run_tests.sh fast`
