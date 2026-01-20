# Integration Tests Guide

## Overview

The integration tests workflow (`.github/workflows/integration-tests.yml`) provides comprehensive automated testing to catch issues before they reach production. This workflow was created in response to manually discovered bugs like UUID field handling errors and logging gaps.

## What Gets Tested

### 1. Database Integration Tests

**Purpose**: Verify database schema, operations, and data integrity

**Tests Include**:
- Database schema initialization
- Table creation verification (34+ tables)
- Index verification
- UUID field handling (catches UUID bugs)
- Database operations (INSERT, UPDATE, SELECT)
- Transaction handling
- Connection pooling

**Catches Issues Like**:
- ✅ UUID field type mismatches (the bug that was manually discovered)
- ✅ Missing database tables
- ✅ Index creation failures
- ✅ Schema migration errors
- ✅ Data type incompatibilities

**Example Test**:
```yaml
- name: Test UUID field handling
  run: |
    # Insert test record with UUID
    INSERT INTO agent_routing_decisions (
      request_id,  # UUID field
      user_request,
      selected_agent,
      confidence_score
    ) VALUES (
      gen_random_uuid(),
      'Test request',
      'test-agent',
      0.95
    );
```

### 2. Kafka Integration Tests

**Purpose**: Verify event bus connectivity and message flow

**Tests Include**:
- Kafka/Redpanda connectivity
- Producer functionality
- Consumer functionality
- Topic creation
- Message serialization/deserialization
- Event publishing
- Routing event flow

**Catches Issues Like**:
- ✅ Kafka connection failures
- ✅ Message serialization errors
- ✅ Topic configuration issues
- ✅ Consumer group problems
- ✅ Event publishing failures

### 3. Agent Observability Tests

**Purpose**: Verify all agent actions are properly logged and traceable

**Tests Include**:
- Agent execution logging
- Action logging end-to-end
- Transformation event logging
- Correlation ID propagation
- Logging completeness verification

**Catches Issues Like**:
- ✅ Logging gaps (actions not being logged)
- ✅ NULL correlation IDs
- ✅ Missing agent execution records
- ✅ Incomplete observability data
- ✅ Traceability breaks

**Example Test**:
```yaml
- name: Verify logging completeness
  run: |
    # Verify correlation IDs are not NULL
    NULL_CORR_COUNT=$(psql -c "
      SELECT COUNT(*)
      FROM agent_execution_logs
      WHERE correlation_id IS NULL
    ")

    if [ "$NULL_CORR_COUNT" -gt 0 ]; then
      echo "❌ Found execution logs with NULL correlation_id"
      exit 1
    fi
```

### 4. Full Pipeline Integration Tests

**Purpose**: Test complete end-to-end workflows

**Tests Include**:
- Agent routing → execution → logging flow
- Multi-node generation workflows
- Contract validation integration
- Cross-service communication
- State management

**Catches Issues Like**:
- ✅ Integration failures between services
- ✅ Workflow orchestration bugs
- ✅ State management issues
- ✅ Cross-cutting concerns

## How to Run Locally

### Prerequisites

```bash
# Install Docker and Docker Compose
docker --version
docker-compose --version

# Install Poetry
poetry --version
```

### Run All Integration Tests

```bash
# Start infrastructure services
docker-compose -f deployment/docker-compose.yml up -d postgres redis

# Run database integration tests
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_USER=test_user
export POSTGRES_PASSWORD=test_password
export POSTGRES_DATABASE=test_omninode_bridge

poetry run pytest tests/test_database_event_client.py -v

# Run Kafka integration tests (if Redpanda is running)
export KAFKA_BOOTSTRAP_SERVERS=localhost:9092
poetry run pytest tests/test_kafka_logging.py -v

# Run agent observability tests
poetry run pytest tests/test_agent_execution_logging.py -v
poetry run pytest tests/test_e2e_agent_logging.py -v

# Run full pipeline tests
poetry run pytest tests/integration/test_full_pipeline.py -v -m integration

# Cleanup
docker-compose -f deployment/docker-compose.yml down
```

### Run Specific Test Suites

```bash
# Database only
pytest tests/test_database_*.py -v

# Kafka only
pytest tests/test_kafka_*.py -v

# Agent observability only
pytest tests/test_*_logging.py -v

# Integration tests only
pytest -m integration -v
```

## CI/CD Integration

### When Tests Run

The integration tests workflow runs:
- ✅ On every push to `main` or `develop` branches
- ✅ On every pull request to `main` or `develop`
- ✅ On manual trigger (workflow_dispatch)

### PR Requirements

**PRs CANNOT merge if**:
- ❌ Database integration tests fail
- ❌ Kafka integration tests fail
- ❌ Agent observability tests fail
- ❌ Full pipeline integration tests fail

### Test Results

**Where to Find Results**:
1. GitHub Actions tab → "Integration Tests" workflow
2. PR checks section → "Integration Tests Summary"
3. Codecov report (coverage data)
4. Artifacts (detailed test logs)

**Example PR Check**:
```
Integration Tests Summary

✅ Database Integration: Passed
✅ Kafka Integration: Passed
✅ Agent Observability: Passed
✅ Full Pipeline: Passed

Coverage: 87.3% (+2.1%)
```

## Adding New Integration Tests

### Database Tests

Add tests to verify new database tables or operations:

```python
# tests/test_new_feature_db.py
import pytest

@pytest.mark.integration
async def test_new_table_creation():
    """Verify new feature table is created correctly."""
    # Test implementation
    pass
```

### Kafka Tests

Add tests for new event types or topics:

```python
# tests/test_new_event_type.py
import pytest

@pytest.mark.integration
async def test_new_event_publishing():
    """Verify new event type publishes correctly."""
    # Test implementation
    pass
```

### Observability Tests

Add tests for new logging requirements:

```python
# tests/test_new_logging_feature.py
import pytest

@pytest.mark.integration
async def test_new_action_logged():
    """Verify new action type is logged."""
    # Test implementation
    pass
```

## Troubleshooting

### Common Issues

#### PostgreSQL Connection Timeout

```bash
# Error: Connection timed out
# Solution: Wait longer for PostgreSQL to be ready

until psql -h localhost -U test_user -d test_db -c '\q'; do
  echo "Waiting for PostgreSQL..."
  sleep 2
done
```

#### Kafka Connection Refused

```bash
# Error: Connection refused to localhost:9092
# Solution: Ensure Redpanda is running and healthy

docker ps | grep redpanda
docker logs redpanda-container
```

#### Missing Dependencies

```bash
# Error: ModuleNotFoundError
# Solution: Reinstall dependencies

poetry install --with dev
```

### Debug Mode

Run tests with verbose output:

```bash
# Maximum verbosity
pytest -vvv --tb=long --log-cli-level=DEBUG

# Capture print statements
pytest -s

# Stop on first failure
pytest -x
```

## Performance Targets

### Expected Test Times

| Test Suite | Target | Acceptable | Critical |
|------------|--------|------------|----------|
| Database Integration | <30s | <60s | >120s |
| Kafka Integration | <20s | <40s | >80s |
| Agent Observability | <45s | <90s | >180s |
| Full Pipeline | <60s | <120s | >240s |
| **Total** | **<155s** | **<310s** | **>680s** |

### Coverage Targets

| Component | Target | Minimum |
|-----------|--------|---------|
| Database Operations | >90% | >80% |
| Kafka Integration | >85% | >75% |
| Agent Logging | >95% | >85% |
| Overall Integration | >87% | >80% |

## Related Documentation

- [Test Coverage Plan](../../TEST_COVERAGE_PLAN.md)
- [Agent Observability](../observability/AGENT_TRACEABILITY.md)
- [Database Schema](../database/SCHEMA.md)
- [Kafka Integration](../architecture/KAFKA_INTEGRATION.md)

## Changelog

### 2025-11-09 - Initial Version

- Created comprehensive integration tests workflow
- Added database integration tests (catches UUID bug)
- Added Kafka integration tests
- Added agent observability tests (catches logging gaps)
- Added full pipeline integration tests
- Added PR check requirements
- Added coverage reporting

## Contributing

When adding new features:

1. **Write integration tests FIRST**
   - Think about what could go wrong
   - Test database schema changes
   - Test event publishing/consuming
   - Test logging and traceability

2. **Run tests locally**
   - Before committing
   - Before creating PR
   - After addressing review comments

3. **Update this guide**
   - Document new test suites
   - Update performance targets
   - Add troubleshooting tips

## Contact

For questions or issues with integration tests:
- Check workflow logs in GitHub Actions
- Review test output in artifacts
- Consult this guide for troubleshooting
- Ask in #omniclaude-dev channel
