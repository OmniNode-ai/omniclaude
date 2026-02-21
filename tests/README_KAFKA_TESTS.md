# Kafka Agent Logging Test Suite

Comprehensive testing infrastructure for Kafka-based agent action logging system.

## Overview

This test suite provides end-to-end testing for the agent logging pipeline:

```
Agent Actions → Kafka Skill → Kafka/Redpanda → Consumer → PostgreSQL
```

**Test Coverage**: >80% (unit + integration + e2e + performance)

## Test Categories

### 1. Unit Tests (`test_kafka_logging.py`)

**Purpose**: Fast, isolated tests with mocked Kafka

**Coverage**:
- ✅ Event serialization/deserialization
- ✅ Debug mode filtering
- ✅ Correlation ID generation
- ✅ Partition key routing
- ✅ Error handling
- ✅ Producer configuration
- ✅ Timeout handling
- ✅ Invalid JSON handling

**Run**:
```bash
pytest tests/test_kafka_logging.py -v
```

**Expected Runtime**: ~5 seconds

---

### 2. Integration Tests (`test_kafka_consumer.py`)

**Purpose**: Test consumer with real Kafka + PostgreSQL

**Coverage**:
- ✅ Kafka message consumption
- ✅ Batch inserts to PostgreSQL
- ✅ Idempotency (duplicate handling)
- ✅ Error handling and retry logic
- ✅ Offset commits
- ✅ Graceful shutdown
- ✅ High throughput (1000+ events)

**Requirements**: Docker with Kafka + PostgreSQL running

**Run**:
```bash
# Start infrastructure
docker-compose -f docker-compose.test.yml up -d redpanda postgres

# Run tests
pytest tests/test_kafka_consumer.py -v

# Cleanup
docker-compose -f docker-compose.test.yml down
```

**Expected Runtime**: ~30 seconds

---

### 3. End-to-End Tests (`test_e2e_agent_logging.py`)

**Purpose**: Test complete workflow from skill → database

**Coverage**:
- ✅ Complete workflow simulation
- ✅ Data integrity verification
- ✅ Multi-agent scenarios
- ✅ Latency measurements (<5s p95)
- ✅ Error recovery
- ✅ Consumer restart handling

**Requirements**: Docker with full stack running

**Run**:
```bash
# Start full stack
docker-compose -f docker-compose.test.yml up -d

# Ensure consumer is running
docker-compose -f docker-compose.test.yml up -d consumer

# Run tests
pytest tests/test_e2e_agent_logging.py -v

# Cleanup
docker-compose -f docker-compose.test.yml down
```

**Expected Runtime**: ~60 seconds

---

### 4. Performance Tests (`test_logging_performance.py`)

**Purpose**: Validate performance targets under load

**Performance Targets**:
- ✅ Publish latency: <10ms p95
- ✅ Consumer throughput: >1000 events/sec
- ✅ End-to-end latency: <5s p95
- ✅ Consumer lag: <100 messages
- ✅ Memory usage: <500MB

**Run**:
```bash
# Start infrastructure
docker-compose -f docker-compose.test.yml up -d

# Run performance tests
pytest tests/test_logging_performance.py -v -m performance

# Cleanup
docker-compose -f docker-compose.test.yml down
```

**Expected Runtime**: ~2 minutes

---

## Quick Start

### Option 1: Automated Testing (Recommended)

```bash
# Start test environment
docker-compose -f docker-compose.test.yml up -d

# Validate setup
./scripts/validate-kafka-setup.sh

# Run all tests
docker-compose -f docker-compose.test.yml --profile test up test-runner

# View results
cat test-results/unit.xml
cat test-results/integration.xml
cat test-results/e2e.xml
cat test-results/performance.xml
```

### Option 2: Manual Testing

```bash
# Start infrastructure
docker-compose -f docker-compose.test.yml up -d redpanda postgres

# Validate setup
./scripts/validate-kafka-setup.sh

# Run individual test suites
pytest tests/test_kafka_logging.py -v          # Unit tests
pytest tests/test_kafka_consumer.py -v         # Integration tests
pytest tests/test_e2e_agent_logging.py -v      # E2E tests
pytest tests/test_logging_performance.py -v -m performance  # Performance tests

# Manual E2E test
./scripts/test-agent-logging.sh
```

### Option 3: CI/CD Integration

```yaml
# .github/workflows/kafka-tests.yml
name: Kafka Agent Logging Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Start test infrastructure
        run: docker-compose -f docker-compose.test.yml up -d

      - name: Validate setup
        run: ./scripts/validate-kafka-setup.sh

      - name: Run tests
        run: docker-compose -f docker-compose.test.yml --profile test up --exit-code-from test-runner test-runner

      - name: Upload test results
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: test-results
          path: test-results/

      - name: Cleanup
        if: always()
        run: docker-compose -f docker-compose.test.yml down -v
```

---

## Infrastructure

### Docker Compose Services

**`docker-compose.test.yml`** provides:

1. **redpanda** - Kafka-compatible broker
   - Ports: 29092 (Kafka), 28081 (Schema Registry)
   - Healthcheck: `rpk cluster health`

2. **postgres** - PostgreSQL database
   - Port: 5436
   - Auto-initialization with schema

3. **consumer** - Kafka consumer service
   - Reads from `agent-actions` topic
   - Persists to PostgreSQL with batching

4. **test-runner** - Pytest container
   - Runs all test suites
   - Generates JUnit XML reports

5. **console** - Redpanda Console (debug)
   - Port: 8080
   - Start with: `--profile debug`

### Environment Variables

```bash
# Kafka
KAFKA_BROKERS=localhost:29092

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5436
POSTGRES_USER=postgres
POSTGRES_PASSWORD=omninode-bridge-postgres-dev-2024
POSTGRES_DATABASE=omniclaude

# Consumer
BATCH_SIZE=100
BATCH_TIMEOUT_SECONDS=2.0

# Testing
DEBUG=true
```

---

## Validation Scripts

### `validate-kafka-setup.sh`

Comprehensive validation of the test environment:

✅ Checks required tools (Docker, psql)
✅ Verifies containers are running
✅ Tests Kafka connectivity
✅ Tests PostgreSQL connectivity
✅ Validates topic exists
✅ Validates table schema
✅ Tests Kafka publish/consume
✅ Tests database write/read

**Usage**:
```bash
./scripts/validate-kafka-setup.sh
```

### `test-agent-logging.sh`

Manual end-to-end workflow test:

✅ Simulates 4-action agent workflow
✅ Verifies events in Kafka
✅ Waits for consumer processing
✅ Validates data integrity in PostgreSQL
✅ Tests idempotency (duplicate handling)
✅ Measures end-to-end latency
✅ Cleans up test data

**Usage**:
```bash
./scripts/test-agent-logging.sh
```

---

## Test Data Management

### Cleanup Test Data

```sql
-- Cleanup function (auto-created)
SELECT cleanup_test_data();

-- Manual cleanup
DELETE FROM agent_actions WHERE correlation_id LIKE 'test-%';
DELETE FROM agent_actions WHERE correlation_id LIKE 'perf-test-%';
DELETE FROM agent_actions WHERE correlation_id LIKE 'e2e-test-%';
```

### Correlation ID Prefixes

- `test-*` - Unit and integration tests
- `perf-test-*` - Performance tests
- `e2e-test-*` - End-to-end tests
- `manual-test-*` - Manual validation script

---

## Debugging

### View Kafka Messages

```bash
# View all messages
docker exec omniclaude_test_redpanda rpk topic consume agent-actions --num 10

# View with specific correlation ID
docker exec omniclaude_test_redpanda rpk topic consume agent-actions --num 1000 | grep "correlation-id-here"

# View topic info
docker exec omniclaude_test_redpanda rpk topic describe agent-actions
```

### View Consumer Lag

```bash
docker exec omniclaude_test_redpanda rpk group describe agent-action-consumer
```

### View Database Records

```bash
# Connect to PostgreSQL
docker exec -it omniclaude_test_postgres psql -U postgres -d omniclaude

# Query agent actions
SELECT
    correlation_id,
    agent_name,
    action_type,
    action_name,
    duration_ms,
    created_at
FROM agent_actions
ORDER BY created_at DESC
LIMIT 10;
```

### View Consumer Logs

```bash
docker-compose -f docker-compose.test.yml logs -f consumer
```

### Redpanda Console (Web UI)

```bash
# Start with debug profile
docker-compose -f docker-compose.test.yml --profile debug up -d console

# Access at http://localhost:8080
```

---

## Performance Benchmarks

**Hardware**: MacBook Pro M3 Max, 128GB RAM

| Metric | Target | Actual |
|--------|--------|--------|
| Publish latency (p50) | <5ms | ~2ms |
| Publish latency (p95) | <10ms | ~4ms |
| Publish latency (p99) | <20ms | ~8ms |
| Consumer throughput | >1000 events/sec | ~2500 events/sec |
| E2E latency (p95) | <5s | ~2s |
| Consumer lag | <100 messages | ~10 messages |
| Memory usage | <500MB | ~150MB |

**Note**: Performance may vary based on hardware and Docker configuration.

---

## Troubleshooting

### Kafka Connection Refused

```bash
# Check if Redpanda is running
docker ps | grep redpanda

# Check Redpanda logs
docker logs omniclaude_test_redpanda

# Restart Redpanda
docker-compose -f docker-compose.test.yml restart redpanda
```

### PostgreSQL Connection Refused

```bash
# Check if PostgreSQL is running
docker ps | grep postgres

# Check PostgreSQL logs
docker logs omniclaude_test_postgres

# Restart PostgreSQL
docker-compose -f docker-compose.test.yml restart postgres
```

### Consumer Not Processing Messages

```bash
# Check consumer logs
docker-compose -f docker-compose.test.yml logs consumer

# Restart consumer
docker-compose -f docker-compose.test.yml restart consumer

# Check consumer group
docker exec omniclaude_test_redpanda rpk group describe agent-action-consumer
```

### Tests Failing

```bash
# Run with verbose output
pytest tests/test_kafka_logging.py -vvs

# Run specific test
pytest tests/test_kafka_logging.py::TestKafkaLoggingUnit::test_debug_mode_enabled -vvs

# Check Docker services
./scripts/validate-kafka-setup.sh
```

---

## Contributing

When adding new tests:

1. ✅ Follow existing naming conventions
2. ✅ Use correlation ID prefixes (`test-*`, `perf-test-*`)
3. ✅ Clean up test data in teardown
4. ✅ Add performance targets for new scenarios
5. ✅ Update this README with new test coverage

---

## References

- **Kafka Skill**: `skills/agent-tracking/log-agent-action/execute_kafka.py`
- **Consumer**: `agents/lib/kafka_agent_action_consumer.py`
- **Database Schema**: `tests/init-test-db.sql`
- **Docker Compose**: `docker-compose.test.yml`
- **Validation Script**: `scripts/validate-kafka-setup.sh`
- **Manual Test**: `scripts/test-agent-logging.sh`

---

## License

Internal testing infrastructure for OmniClaude agent logging system.
