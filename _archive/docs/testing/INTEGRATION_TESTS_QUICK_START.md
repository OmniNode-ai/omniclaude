# Integration Tests - Quick Start

## 🚀 TL;DR

Integration tests run **automatically** on every PR and commit to main/develop. They catch database bugs, logging gaps, and integration issues before production.

## ✅ What Tests Catch

| Issue Type | Example | Test That Catches It |
|------------|---------|----------------------|
| **UUID Bugs** | UUID field type mismatches | Database Integration |
| **Logging Gaps** | Actions not being logged | Agent Observability |
| **Kafka Failures** | Event publishing breaks | Kafka Integration |
| **Schema Errors** | Missing tables/indexes | Database Integration |
| **Integration Breaks** | Service-to-service failures | Full Pipeline |

## 🏃 Run Locally (Fast)

### Minimum Test (1 minute)

```bash
# Start PostgreSQL
docker-compose -f deployment/docker-compose.yml up -d postgres

# Run database tests
export POSTGRES_HOST=localhost POSTGRES_PORT=5432
export POSTGRES_USER=test_user POSTGRES_PASSWORD=test_password
export POSTGRES_DATABASE=test_omninode_bridge

poetry run pytest tests/test_database_event_client.py -v

# Cleanup
docker-compose -f deployment/docker-compose.yml down
```

### Full Integration Suite (5 minutes)

```bash
# Start all services
docker-compose -f deployment/docker-compose.yml up -d

# Run all integration tests
poetry run pytest -m integration -v --cov

# Cleanup
docker-compose -f deployment/docker-compose.yml down
```

## 🔍 Check PR Status

### GitHub UI

1. Go to your PR
2. Scroll to checks section
3. Look for **"Integration Tests"**
4. Click for details if failed

### Expected Output (Passing)

```
✅ Database Integration: Passed
✅ Kafka Integration: Passed
✅ Agent Observability: Passed
✅ Full Pipeline: Passed

Coverage: 87.3%
```

### Expected Output (Failing)

```
❌ Database Integration: Failed
  → Error: UUID field handling test failed
  → See logs: database-test-results artifact

✅ Kafka Integration: Passed
✅ Agent Observability: Passed
✅ Full Pipeline: Passed
```

## 🐛 Debug Failed Tests

### 1. Check Logs

```bash
# Download artifacts from GitHub Actions
# Or run locally with verbose output
pytest -vvv --tb=long --log-cli-level=DEBUG
```

### 2. Common Fixes

| Error | Fix |
|-------|-----|
| "Connection refused (PostgreSQL)" | Wait longer: `sleep 5` before tests |
| "Connection refused (Kafka)" | Check Redpanda is running: `docker ps` |
| "ModuleNotFoundError" | Reinstall: `poetry install --with dev` |
| "UUID type error" | Check schema: `\d table_name` in psql |
| "NULL correlation_id" | Fix logging: ensure UUID is passed |

### 3. Interactive Debugging

```bash
# Start services
docker-compose -f deployment/docker-compose.yml up -d postgres

# Connect to database
psql -h localhost -U test_user -d test_omninode_bridge

# Check table structure
\d agent_routing_decisions

# Check for issues
SELECT * FROM agent_execution_logs WHERE correlation_id IS NULL;

# Exit
\q
```

## 📊 Coverage Report

### View in PR

Coverage report automatically posted as comment:

```
Coverage Report

agents/
  lib/
    agent_execution_logger.py    95.2% (+2.1%)
    database_event_client.py     89.7% (+1.3%)
    kafka_logging.py              87.4% (-0.8%)

Overall: 87.3% (+1.2%)
```

### View Locally

```bash
# Generate HTML report
poetry run pytest --cov --cov-report=html

# Open in browser
open htmlcov/index.html
```

## 🚫 PR Merge Requirements

Your PR **CANNOT merge** if:

- ❌ Any integration test suite fails
- ❌ Coverage drops below 80%
- ❌ Database schema validation fails
- ❌ Agent observability tests fail

## ⚡ Quick Commands

```bash
# Run database tests only
pytest tests/test_database_*.py -v

# Run Kafka tests only
pytest tests/test_kafka_*.py -v

# Run observability tests only
pytest tests/test_*_logging.py -v

# Run integration tests only
pytest -m integration -v

# Run with coverage
pytest -m integration --cov --cov-report=term-missing

# Stop on first failure
pytest -m integration -x
```

## 📚 Full Documentation

For detailed information:
- [Integration Tests Guide](./INTEGRATION_TESTS_GUIDE.md) - Complete guide
- [Test Coverage Plan](../../TEST_COVERAGE_PLAN.md) - Coverage strategy
- [Agent Observability](../observability/AGENT_TRACEABILITY.md) - Logging details

## 🆘 Need Help?

1. Check the [Troubleshooting section](./INTEGRATION_TESTS_GUIDE.md#troubleshooting)
2. Review workflow logs in GitHub Actions
3. Download test artifacts for detailed logs
4. Ask in #omniclaude-dev channel

## 📝 Examples

### Adding a New Database Test

```python
# tests/test_my_new_feature.py
import pytest

@pytest.mark.integration
async def test_my_new_table():
    """Verify my_new_table is created correctly."""
    # Your test here
    pass
```

### Adding a New Observability Test

```python
# tests/test_my_new_logging.py
import pytest

@pytest.mark.integration
async def test_my_action_is_logged():
    """Verify MyAction is logged to database."""
    # Your test here
    pass
```

## ⏱️ Performance

| Test Suite | Expected Time |
|------------|---------------|
| Database Integration | ~30s |
| Kafka Integration | ~20s |
| Agent Observability | ~45s |
| Full Pipeline | ~60s |
| **Total** | **~155s** |

## 🎯 Success Criteria

✅ All 4 test suites pass
✅ Coverage ≥ 87%
✅ No NULL correlation_ids
✅ No UUID field errors
✅ All tables created
✅ All indexes present
✅ All events published
✅ All actions logged

---

**Last Updated**: 2025-11-09
**Version**: 1.0.0
**Workflow**: `.github/workflows/integration-tests.yml`
