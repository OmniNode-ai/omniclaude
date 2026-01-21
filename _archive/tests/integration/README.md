# Integration Tests - Agent Observability System

Comprehensive integration tests for the OmniClaude agent observability system.

## Overview

This test suite provides end-to-end testing of the complete agent observability infrastructure:

- **Agent Action Logging** - All 4 action types (tool_call, decision, error, success)
- **Agent Transformation Events** - Kafka → Database flow
- **Agent Manifest Injections** - Creation, storage, and retrieval
- **Correlation ID Tracking** - Cross-table traceability
- **Database Schema Validation** - Constraints, indexes, and views

## Test Coverage

### test_agent_observability_integration.py

Comprehensive integration test suite with 4 test classes:

#### 1. TestAgentActionsLogging (6 tests)
- `test_tool_call_logging` - Tool invocation logging (Read, Write, Edit, Bash)
- `test_decision_logging` - Routing decision logging
- `test_error_logging` - **Would catch bug: 0 errors logged**
- `test_success_logging` - **Would catch bug: 0 successes logged**
- `test_all_action_types_together` - Complete trace reconstruction

#### 2. TestTransformationEvents (4 tests)
- `test_transformation_complete_event` - **Would catch UUID serialization bug**
- `test_transformation_failed_event` - Failed transformation flow
- `test_transformation_start_event` - Start event flow
- `test_polymorphic_agent_switching` - Multi-event workflows

#### 3. TestManifestInjections (2 tests)
- `test_manifest_injection_schema_compliance` - Schema validation
- `test_correlation_id_tracking_across_tables` - Cross-table traceability

#### 4. TestDatabaseSchemaValidation (5 tests)
- `test_agent_actions_table_exists` - Table existence
- `test_agent_transformation_events_table_exists` - Table existence
- `test_agent_manifest_injections_table_exists` - Table existence
- `test_agent_routing_decisions_table_exists` - Table existence
- `test_required_indexes_exist` - Performance indexes
- `test_analytical_views_exist` - Query views
- `test_action_type_constraint` - Constraint enforcement

**Total**: 17 comprehensive integration tests

## Prerequisites

### 1. Environment Setup

Load environment variables from `.env` file:

```bash
# Copy template and edit
cp .env.example .env
nano .env

# Load environment
source .env
```

Required environment variables:
```bash
# PostgreSQL
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<your-password>

# Kafka
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092
```

### 2. Infrastructure Services

Ensure these services are running:

```bash
# PostgreSQL (check connection)
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT 1"

# Kafka (check topics)
docker exec omninode-bridge-redpanda rpk topic list

# Consumer services (check running)
ps aux | grep agent_actions_consumer
docker ps | grep consumer
```

### 3. Python Dependencies

```bash
pip install pytest pytest-asyncio psycopg2-binary python-dotenv
```

## Running Tests

### Run All Integration Tests

```bash
# From project root
pytest tests/integration/test_agent_observability_integration.py -v

# With detailed output
pytest tests/integration/test_agent_observability_integration.py -v -s
```

### Run Specific Test Class

```bash
# Test only action logging
pytest tests/integration/test_agent_observability_integration.py::TestAgentActionsLogging -v

# Test only transformation events
pytest tests/integration/test_agent_observability_integration.py::TestTransformationEvents -v

# Test only manifest injections
pytest tests/integration/test_agent_observability_integration.py::TestManifestInjections -v

# Test only schema validation
pytest tests/integration/test_agent_observability_integration.py::TestDatabaseSchemaValidation -v
```

### Run Specific Test

```bash
# Test error logging only (would catch bug)
pytest tests/integration/test_agent_observability_integration.py::TestAgentActionsLogging::test_error_logging -v

# Test UUID serialization (would catch bug)
pytest tests/integration/test_agent_observability_integration.py::TestTransformationEvents::test_transformation_complete_event -v
```

### Run with Markers

```bash
# Run all integration tests
pytest -m integration -v

# Skip integration tests
pytest -m "not integration" -v
```

### Quick Test Script

```bash
# Run comprehensive test suite
./tests/integration/run_observability_tests.sh

# Run with verbose output
./tests/integration/run_observability_tests.sh --verbose

# Run specific class
./tests/integration/run_observability_tests.sh --class=TestAgentActionsLogging
```

## Expected Failures (Known Issues)

These tests are **designed to fail** for known issues:

### 1. Error Logging Test
```bash
pytest tests/integration/test_agent_observability_integration.py::TestAgentActionsLogging::test_error_logging -v
```

**Expected Failure**: `FAILED: Expected at least 1 error action in database - ERROR LOGGING NOT WORKING!`

**Cause**: Error events published to Kafka but consumer not processing them correctly.

**Fix**: Implement error event handling in agent_actions_consumer.py

### 2. Success Logging Test
```bash
pytest tests/integration/test_agent_observability_integration.py::TestAgentActionsLogging::test_success_logging -v
```

**Expected Failure**: `FAILED: Expected at least 1 success action in database - SUCCESS LOGGING NOT WORKING!`

**Cause**: Success events published to Kafka but consumer not processing them correctly.

**Fix**: Implement success event handling in agent_actions_consumer.py

### 3. Transformation Event Test
```bash
pytest tests/integration/test_agent_observability_integration.py::TestTransformationEvents::test_transformation_complete_event -v
```

**Expected Failure**: `FAILED: Expected at least 1 transformation event - UUID SERIALIZATION MAY BE BROKEN!`

**Cause**: UUID objects serialized to Kafka as objects instead of strings, causing deserialization failures.

**Fix**: Convert UUIDs to strings before Kafka serialization in transformation_event_publisher.py

## CI/CD Integration

### GitHub Actions

Add to `.github/workflows/tests.yml`:

```yaml
name: Integration Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  integration-tests:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test_password
          POSTGRES_DB: omninode_bridge
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

      kafka:
        image: vectorized/redpanda:latest
        ports:
          - 9092:9092

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio psycopg2-binary

      - name: Run database migrations
        run: |
          psql -h localhost -U postgres -d omninode_bridge -f migrations/005_create_agent_actions_table.sql
          psql -h localhost -U postgres -d omninode_bridge -f agents/parallel_execution/migrations/002_create_agent_transformation_events.sql

      - name: Run integration tests
        env:
          POSTGRES_HOST: localhost
          POSTGRES_PORT: 5432
          POSTGRES_DATABASE: omninode_bridge
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: test_password
          KAFKA_BOOTSTRAP_SERVERS: localhost:9092
        run: |
          pytest tests/integration/test_agent_observability_integration.py -v -m integration
```

## Debugging Failed Tests

### Check Database Connectivity

```bash
# Test database connection
source .env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT NOW()"

# Check table existence
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "\dt"

# Query recent actions
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT * FROM agent_actions ORDER BY created_at DESC LIMIT 10;"
```

### Check Kafka Connectivity

```bash
# List topics
docker exec omninode-bridge-redpanda rpk topic list

# Check consumer group
docker exec omninode-bridge-redpanda rpk group list

# Consume messages from topic
docker exec omninode-bridge-redpanda rpk topic consume agent-actions --num 10
```

### Check Consumer Status

```bash
# Check if consumer is running
ps aux | grep agent_actions_consumer
docker ps | grep consumer

# View consumer logs
docker logs -f <consumer-container-name>

# Restart consumer
docker restart <consumer-container-name>
```

### Manual Database Query

```bash
# Query by correlation_id
source .env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} << EOF
SELECT
    correlation_id,
    action_type,
    action_name,
    created_at
FROM agent_actions
WHERE correlation_id = '<your-correlation-id>'
ORDER BY created_at ASC;
EOF
```

## Test Data Cleanup

After running tests, you may want to clean up test data:

```sql
-- Delete test actions (from last hour)
DELETE FROM agent_actions
WHERE agent_name LIKE 'test-%'
  AND created_at > NOW() - INTERVAL '1 hour';

-- Delete test transformation events
DELETE FROM agent_transformation_events
WHERE source_agent LIKE 'test-%'
  OR target_agent LIKE 'test-%';

-- Delete test manifest injections
DELETE FROM agent_manifest_injections
WHERE agent_name LIKE 'test-%';

-- Delete test routing decisions
DELETE FROM agent_routing_decisions
WHERE selected_agent LIKE 'test-%';
```

Or use the cleanup script:

```bash
# Clean test data from last 1 hour
./tests/integration/cleanup_test_data.sh --hours=1

# Clean all test data (be careful!)
./tests/integration/cleanup_test_data.sh --all
```

## Performance Benchmarks

Expected test execution times:

| Test Class | Tests | Expected Duration | Notes |
|------------|-------|------------------|-------|
| TestAgentActionsLogging | 5 | ~30 seconds | 5s wait per test for consumer |
| TestTransformationEvents | 4 | ~25 seconds | 5s wait per test for consumer |
| TestManifestInjections | 2 | ~5 seconds | Database queries only |
| TestDatabaseSchemaValidation | 5 | ~2 seconds | Schema queries only |
| **Total** | **17** | **~62 seconds** | End-to-end with consumers |

Optimize by:
- Reducing `consumer_wait_time` fixture (default: 5s)
- Running schema tests separately (no Kafka dependency)
- Using faster consumer processing

## Troubleshooting

### Test Timeout

If tests timeout waiting for consumer:

1. Increase `consumer_wait_time` fixture in conftest.py
2. Check consumer logs for errors
3. Verify Kafka connectivity

### Database Connection Errors

If database connection fails:

1. Verify `.env` file is loaded: `echo $POSTGRES_PASSWORD`
2. Check PostgreSQL is running: `docker ps | grep postgres`
3. Test connection: `psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U postgres -c "SELECT 1"`

### Missing Tables

If tables don't exist:

1. Run migrations: `./scripts/init-db.sh`
2. Check migration status: `psql ... -c "\dt"`
3. Manually run migration files if needed

## Contributing

When adding new observability features:

1. Add integration tests to this suite
2. Follow existing test patterns
3. Use descriptive test names
4. Add docstrings explaining what bug the test would catch
5. Update this README with new test coverage

## Related Documentation

- [Agent Observability Architecture](../../docs/observability/AGENT_TRACEABILITY.md)
- [Action Logging Guide](../../docs/observability/AGENT_ACTION_LOGGING.md)
- [Database Schema](../../agents/parallel_execution/migrations/)
- [Test Coverage Plan](../../TEST_COVERAGE_PLAN.md)

---

**Last Updated**: 2025-11-09
**Test Suite Version**: 1.0.0
**Total Tests**: 17 comprehensive integration tests
**Known Issues**: 3 expected failures (documented above)
