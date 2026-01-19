# Coverage Gap Analysis - OmniClaude

**Date**: 2025-11-09
**Analysis Scope**: Recent production issues (WP3)
**Test Coverage Run**: `pytest --cov=consumers --cov=agents/lib --cov-report=term-missing`

---

## Executive Summary

**Finding**: Critical integration points have 0-15% test coverage, allowing production bugs to escape detection.

**Impact**: Three production issues were missed by unit tests:
1. UUID serialization bug (psycopg2)
2. Missing error/success logging
3. Incomplete tool call tracking

**Root Cause**: Over-reliance on unit tests with mocked dependencies, lacking integration tests with real PostgreSQL and Kafka.

**Recommendation**: Implement integration test suite with testcontainers (PostgreSQL, Kafka) targeting 100% coverage of critical data flows.

---

## Coverage Analysis by File

### Critical Files with Low Coverage

#### 1. Action Event Publisher (0% coverage)

**File**: `agents/lib/action_event_publisher.py`
**Lines**: 168 total, 168 uncovered (0% coverage)
**Risk Level**: 🔴 CRITICAL

**What This File Does**:
- Publishes agent action events to Kafka
- Handles 4 event types: tool_call, decision, error, success
- Serializes data to JSON for Kafka

**Why Low Coverage**:
- No integration tests with real Kafka
- Unit tests mock Kafka producer
- Event serialization not validated

**Production Risk**:
- Events may not be published correctly
- Serialization errors not caught (UUID bug)
- DLQ handling not tested

**Required Tests**:
```
✅ test_publish_tool_call_event_to_kafka
✅ test_publish_decision_event_to_kafka
✅ test_publish_error_event_to_kafka
✅ test_publish_success_event_to_kafka
✅ test_event_serialization_with_uuid
✅ test_dlq_handling_on_publish_failure
✅ test_kafka_connection_retry_logic
```

---

#### 2. Action Logger (0% coverage)

**File**: `agents/lib/action_logger.py`
**Lines**: 115 total, 115 uncovered (0% coverage)
**Risk Level**: 🔴 CRITICAL

**What This File Does**:
- Logs agent actions to PostgreSQL
- Handles 4 event types: tool_call, decision, error, success
- Serializes UUID to string for database

**Why Low Coverage**:
- No integration tests with real PostgreSQL
- Unit tests mock database connection
- UUID → str conversion not tested

**Production Risk**:
- Database insertion may fail (UUID serialization bug)
- Missing event types not detected (error/success)
- Schema validation not tested

**Required Tests**:
```
✅ test_log_tool_call_to_database
✅ test_log_decision_to_database
✅ test_log_error_to_database
✅ test_log_success_to_database
✅ test_complete_lifecycle_all_4_events
✅ test_uuid_serialization_to_database
✅ test_schema_validation_before_insert
```

---

#### 3. Agent Execution Logger (15% coverage)

**File**: `agents/lib/agent_execution_logger.py`
**Lines**: 199 total, 169 uncovered (15% coverage)
**Risk Level**: 🟠 HIGH

**What This File Does**:
- Logs agent execution lifecycle to PostgreSQL
- Tracks start, progress, complete stages
- Records quality scores and errors

**Why Low Coverage**:
- Only basic unit tests exist
- No integration tests for database operations
- Progress tracking not tested

**Production Risk**:
- Execution tracking may be incomplete
- Progress updates may not persist
- Quality scores may not be recorded

**Required Tests**:
```
✅ test_log_execution_start
✅ test_log_execution_progress
✅ test_log_execution_complete
✅ test_log_execution_failure
✅ test_quality_score_persistence
✅ test_execution_with_errors
✅ test_complete_lifecycle_tracking
```

---

#### 4. Database Event Client (14% coverage)

**File**: `agents/lib/database_event_client.py`
**Lines**: 254 total, 219 uncovered (14% coverage)
**Risk Level**: 🟠 HIGH

**What This File Does**:
- Handles all database operations
- Inserts routing decisions, manifest injections, execution logs
- Manages transactions and retries

**Why Low Coverage**:
- No integration tests for database operations
- Transaction boundaries not tested
- Retry logic not validated

**Production Risk**:
- Database operations may fail silently
- Transactions may not rollback correctly
- Retries may not work as expected

**Required Tests**:
```
✅ test_insert_routing_decision
✅ test_insert_manifest_injection
✅ test_insert_execution_log
✅ test_transaction_commit
✅ test_transaction_rollback_on_error
✅ test_retry_on_connection_failure
✅ test_schema_validation
```

---

#### 5. Intelligence Event Client (15% coverage)

**File**: `agents/lib/intelligence_event_client.py`
**Lines**: 215 total, 182 uncovered (15% coverage)
**Risk Level**: 🟠 HIGH

**What This File Does**:
- Queries archon-intelligence via Kafka
- Handles pattern discovery, debug intelligence
- Manages correlation IDs and timeouts

**Why Low Coverage**:
- No integration tests with Kafka
- Request-response pattern not tested
- Timeout handling not validated

**Production Risk**:
- Intelligence queries may fail
- Correlation ID tracking may break
- Timeouts may not work correctly

**Required Tests**:
```
✅ test_query_patterns_via_kafka
✅ test_request_response_correlation
✅ test_timeout_handling
✅ test_fallback_on_timeout
✅ test_error_handling
```

---

## Gap Analysis by Test Type

### Unit Test Gaps

**Current Status**: 3206 unit tests, varying coverage

**Gaps Identified**:
1. **Business Logic Coverage**: Good (60-80%)
2. **Error Handling**: Moderate (40-60%)
3. **Edge Cases**: Low (20-40%)

**Recommendation**: Continue unit test expansion for business logic, but **don't add more mocked database/Kafka tests**. These need integration tests instead.

---

### Integration Test Gaps

**Current Status**: ~20 integration tests, mostly for contract validation

**Gaps Identified**:

#### Database Integration (0 tests)
- ❌ No tests for `agent_actions` table inserts
- ❌ No tests for `agent_routing_decisions` table inserts
- ❌ No tests for `agent_manifest_injections` table inserts
- ❌ No tests for `agent_execution_logs` table inserts
- ❌ No tests for UUID serialization
- ❌ No tests for schema validation

**Impact**: High - Production bugs escaping to production

**Priority**: 🔴 CRITICAL - Implement immediately

---

#### Kafka Integration (0 tests)
- ❌ No tests for `agent-actions` topic
- ❌ No tests for `agent-routing-decisions` topic
- ❌ No tests for `intelligence-events` topic
- ❌ No tests for event serialization
- ❌ No tests for DLQ handling

**Impact**: High - Event loss not detected

**Priority**: 🔴 CRITICAL - Implement immediately

---

#### Service Integration (0 tests)
- ❌ No tests for Kafka → Consumer → Database flow
- ❌ No tests for API → Database flow
- ❌ No tests for multi-service workflows

**Impact**: High - Integration failures not caught

**Priority**: 🔴 CRITICAL - Implement immediately

---

### System Test Gaps

**Current Status**: ~5 system tests, mostly for WP2 validation

**Gaps Identified**:
- ❌ No tests for complete agent execution workflow
- ❌ No tests for multi-agent coordination
- ❌ No tests for error recovery and retries
- ❌ No tests for performance under load

**Impact**: Medium - Workflow regressions not caught

**Priority**: 🟠 HIGH - Implement in next sprint

---

## Why Unit Tests Didn't Catch These Issues

### Issue 1: UUID Serialization Bug

**What Unit Tests Did**:
```python
@pytest.mark.asyncio
async def test_log_action():
    mock_db = AsyncMock()
    logger = ActionLogger(db=mock_db)

    action_id = uuid.uuid4()  # UUID object
    await logger.log_action(action_id, "tool_call", {})

    # ✅ Passes: mock accepts any type
    mock_db.execute.assert_called_once()
```

**Why It Passed**:
- `AsyncMock()` accepts any data type
- No validation of psycopg2 serialization
- No actual database connection

**What Integration Test Would Do**:
```python
@pytest.mark.integration
async def test_log_action_with_real_db(postgres_connection):
    logger = ActionLogger(db=postgres_connection)

    action_id = uuid.uuid4()  # UUID object
    await logger.log_action(action_id, "tool_call", {})

    # ❌ Would have failed with TypeError
    # psycopg2 cannot serialize UUID objects
```

**Conclusion**: Unit tests with mocks hide serialization bugs.

---

### Issue 2: Missing Error/Success Logging

**What Unit Tests Did**:
```python
@pytest.mark.asyncio
async def test_log_tool_call():
    mock_db = AsyncMock()
    logger = ActionLogger(db=mock_db)

    await logger.log_tool_call("correlation-123", "bash", {})

    # ✅ Passes: function works correctly
    mock_db.execute.assert_called_once()
```

**Why It Passed**:
- Unit test only checks if **function exists**
- Doesn't verify **function is called in production**
- No validation of system-wide instrumentation

**What Integration Test Would Do**:
```python
@pytest.mark.integration
async def test_complete_agent_lifecycle(postgres_connection):
    """Verify all 4 event types are logged during complete lifecycle."""
    correlation_id = str(uuid.uuid4())

    # Simulate complete agent execution
    await log_tool_call(correlation_id, "bash", {})
    await log_decision(correlation_id, "Selected agent-test")
    await log_error(correlation_id, "Connection timeout")
    await log_success(correlation_id, "Task completed")

    # Query database for all events
    result = await postgres_connection.fetch(
        "SELECT action_type FROM agent_actions WHERE correlation_id = $1",
        correlation_id
    )

    action_types = {row['action_type'] for row in result}

    # ❌ Would have failed: only tool_call and decision exist
    assert action_types == {'tool_call', 'decision', 'error', 'success'}
```

**Conclusion**: Unit tests verify individual functions, not system-wide instrumentation.

---

### Issue 3: Incomplete Tool Call Tracking

**What Unit Tests Did**:
```python
@pytest.mark.asyncio
async def test_log_tool_call():
    mock_db = AsyncMock()
    logger = ActionLogger(db=mock_db)

    await logger.log_tool_call("correlation-123", "bash", {})

    # ✅ Passes: function called
    mock_db.execute.assert_called_once()
```

**Why It Passed**:
- Unit test only checks if database insert was called
- Doesn't verify **linkage to parent execution**
- No validation of relationships

**What Integration Test Would Do**:
```python
@pytest.mark.integration
async def test_tool_call_traceability(postgres_connection):
    """Verify tool calls are linked to parent execution."""
    correlation_id = str(uuid.uuid4())

    # Create parent execution
    await log_agent_execution(
        agent_name="test-agent",
        user_prompt="Test prompt",
        correlation_id=correlation_id
    )

    # Log tool call
    await log_tool_call(correlation_id, "bash", {})

    # Verify linkage via JOIN
    result = await postgres_connection.fetchrow("""
        SELECT ae.correlation_id, aa.action_type
        FROM agent_execution_logs ae
        JOIN agent_actions aa ON ae.correlation_id = aa.correlation_id
        WHERE ae.correlation_id = $1
    """, correlation_id)

    # ❌ Would have failed: JOIN returns no rows
    assert result is not None
```

**Conclusion**: Unit tests verify inserts, not relationships.

---

## Recommendations

### Immediate Actions (This Week)

1. **Set Up Testcontainers** (1 day)
   ```bash
   pip install testcontainers[postgres] testcontainers[kafka]
   ```

2. **Create Integration Test Fixtures** (1 day)
   - PostgreSQL container fixture
   - Kafka/Redpanda container fixture
   - Database migration fixture
   - Test data fixtures

3. **Add Critical Integration Tests** (3 days)
   - Kafka → Database flow (10 tests)
   - Complete action lifecycle (5 tests)
   - UUID serialization (5 tests)

4. **Update CI/CD Pipeline** (1 day)
   - Add integration test stage
   - Set up testcontainers in CI
   - Configure merge gates

---

### Short-Term Actions (Next Sprint)

1. **Achieve 80% Unit Test Coverage** (1 week)
   - Focus on business logic
   - Add error handling tests
   - Add edge case tests

2. **Achieve 100% Integration Coverage for Critical Flows** (1 week)
   - All database tables covered
   - All Kafka topics covered
   - All API endpoints covered

3. **Add System Tests** (3 days)
   - Complete agent execution
   - Multi-agent coordination
   - Error recovery

---

### Long-Term Actions (Next Month)

1. **Contract Testing**
   - Implement Pact for service contracts
   - Ensure backward compatibility

2. **Performance Testing**
   - Load tests (100+ concurrent users)
   - Stress tests (find breaking points)

3. **Chaos Engineering**
   - Network partition tests
   - Database failover tests
   - Kafka broker failure tests

---

## Success Metrics

### Coverage Targets

- **Unit Test Coverage**: ≥80% line coverage
- **Integration Test Coverage**: 100% of critical data flows
- **System Test Coverage**: 100% of critical user workflows

### Quality Metrics

- **Bug Escape Rate**: <5% (bugs in production vs staging)
- **Test Execution Time**:
  - Unit tests: <2 minutes
  - Integration tests: <10 minutes
  - System tests: <30 minutes

### Process Metrics

- **Test-First Development**: >50% of features
- **Regression Rate**: <10%
- **Coverage Trend**: Increasing month-over-month

---

## Implementation Priority

### Priority 1 (Critical - This Week)

| Test | File | Priority | Estimated Effort |
|------|------|----------|------------------|
| Kafka → Database flow | `action_event_publisher.py` | 🔴 CRITICAL | 2 hours |
| Complete action lifecycle | `action_logger.py` | 🔴 CRITICAL | 2 hours |
| UUID serialization | `action_logger.py` | 🔴 CRITICAL | 1 hour |
| Database schema validation | `database_event_client.py` | 🔴 CRITICAL | 2 hours |

**Total**: 7 hours (< 1 day)

---

### Priority 2 (High - Next Week)

| Test | File | Priority | Estimated Effort |
|------|------|----------|------------------|
| Agent execution lifecycle | `agent_execution_logger.py` | 🟠 HIGH | 3 hours |
| Intelligence event flow | `intelligence_event_client.py` | 🟠 HIGH | 2 hours |
| Transaction boundaries | `database_event_client.py` | 🟠 HIGH | 2 hours |
| Retry logic | `database_event_client.py` | 🟠 HIGH | 2 hours |

**Total**: 9 hours (1.5 days)

---

### Priority 3 (Medium - Following Week)

| Test | File | Priority | Estimated Effort |
|------|------|----------|------------------|
| Complete agent execution | System test | 🟡 MEDIUM | 4 hours |
| Multi-agent coordination | System test | 🟡 MEDIUM | 4 hours |
| Error recovery | System test | 🟡 MEDIUM | 3 hours |

**Total**: 11 hours (1.5 days)

---

## Conclusion

**Key Finding**: Unit tests validate logic, but integration tests are needed to catch:
- Serialization bugs (UUID → str)
- Schema mismatches (Pydantic → PostgreSQL)
- Instrumentation gaps (missing event types)
- Cross-service failures (Kafka → Database)

**Next Steps**:
1. Set up testcontainers infrastructure
2. Add critical integration tests (7 hours)
3. Update CI/CD pipeline (1 day)
4. Monitor coverage metrics

**Expected Outcome**: Zero production bugs related to serialization, schema validation, or instrumentation gaps.

---

**Document Owner**: Testing Team
**Date**: 2025-11-09
**Status**: Active
