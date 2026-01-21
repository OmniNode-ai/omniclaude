# Pytest Markers Reference

## Test Categorization Markers

OmniClaude uses pytest markers to categorize tests for efficient CI/CD execution.

### Available Markers

#### `@pytest.mark.unit`
**Purpose**: Fast unit tests with no external dependencies
**Requirements**: None - should mock all external services
**Execution Time**: <100ms per test
**CI Usage**: Run on every commit (fast feedback loop)

**Example**:
```python
import pytest

@pytest.mark.unit
def test_routing_logic():
    """Test agent routing logic with mocked dependencies"""
    # Test implementation with mocks
    pass
```

#### `@pytest.mark.integration`
**Purpose**: Integration tests requiring external services
**Requirements**: PostgreSQL, Kafka, Qdrant, or other external services
**Execution Time**: 100ms - 5s per test
**CI Usage**: Run on PR merge or nightly builds

**Example**:
```python
import pytest

@pytest.mark.integration
async def test_kafka_message_flow():
    """Test actual Kafka message publishing and consumption"""
    # Requires running Kafka instance
    pass
```

#### `@pytest.mark.e2e`
**Purpose**: End-to-end tests requiring full system
**Requirements**: All services running (app, routing, consumers, DB, Kafka, Qdrant)
**Execution Time**: 5s+ per test
**CI Usage**: Run on release candidates only

**Example**:
```python
import pytest

@pytest.mark.e2e
async def test_full_agent_workflow():
    """Test complete agent execution from request to completion"""
    # Requires full system running
    pass
```

### Other Available Markers

- `@pytest.mark.benchmark`: Performance benchmark tests (pytest-benchmark)
- `@pytest.mark.database`: Tests requiring database connectivity
- `@pytest.mark.slow`: Tests that take a long time to run

## Running Tests by Category

### Unit Tests Only (CI Default)
```bash
pytest -m unit
```

### Integration Tests
```bash
pytest -m integration
```

### End-to-End Tests
```bash
pytest -m e2e
```

### All Tests Except E2E
```bash
pytest -m "not e2e"
```

### Multiple Categories
```bash
pytest -m "unit or integration"
```

### Skip Slow Tests
```bash
pytest -m "not slow"
```

## CI/CD Integration

### GitHub Actions Workflow Example

```yaml
# Fast CI - Unit tests only
- name: Run Unit Tests
  run: pytest -m unit --cov --cov-report=xml

# Nightly CI - Integration tests
- name: Run Integration Tests
  run: pytest -m integration
  if: github.event_name == 'schedule'

# Release CI - Full test suite
- name: Run All Tests
  run: pytest
  if: github.ref == 'refs/heads/main'
```

## Best Practices

1. **Mark all new tests** with appropriate category marker
2. **Unit tests should be fast** (<100ms) - use mocks liberally
3. **Integration tests should verify actual service behavior** - avoid mocking external services
4. **E2E tests should cover critical user workflows** - keep count low (<10 tests)
5. **Use multiple markers when appropriate**: `@pytest.mark.integration @pytest.mark.slow`

## Migration Guide

If you have existing tests without markers:

1. **Default to `@pytest.mark.integration`** for safety (existing tests likely have external dependencies)
2. **Identify pure unit tests** and mark with `@pytest.mark.unit`
3. **Mark full system tests** with `@pytest.mark.e2e`
4. **Run CI to verify** marker coverage is sufficient

## Verification

Check marker registration:
```bash
pytest --markers
```

List tests by marker:
```bash
pytest --collect-only -m unit
pytest --collect-only -m integration
pytest --collect-only -m e2e
```

---

**Last Updated**: 2025-11-16
**Related**: PR #36 (Test categorization), CI/CD workflow optimization
