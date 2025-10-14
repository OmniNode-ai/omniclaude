# Polymorphic Agent Framework - Comprehensive Test Plan

**Version**: 1.0.0
**Date**: 2025-10-10
**Status**: Implementation Ready

## Executive Summary

This document outlines a comprehensive testing strategy for the polymorphic agent framework driven by Claude Code hooks. The framework consists of:

- **4 Hook Types**: UserPromptSubmit, PreToolUse, PostToolUse, Session Lifecycle
- **3-Stage Agent Detection**: Pattern (1ms) → Trigger (5ms) → AI (2.5s)
- **Database Integration**: PostgreSQL event logging with correlation tracking
- **Intelligence System**: Background RAG queries via Archon MCP

## Test Coverage Objectives

| Category | Target Coverage | Priority |
|----------|----------------|----------|
| Agent Detection | 100% | Critical |
| Hook Lifecycle | 100% | Critical |
| Database Integration | 95% | High |
| Intelligence Gathering | 90% | High |
| Error Handling | 95% | High |
| Performance | 90% | Medium |
| End-to-End Workflows | 85% | Medium |

## Test Architecture

### 1. Unit Tests (Fast, Isolated)

**Target**: <100ms per test, 100% code coverage

#### 1.1 Agent Detection Tests (`test_agent_detection.py`)
- **Pattern Detection** (Stage 1)
  - ✅ Explicit `@agent-name` syntax
  - ✅ `use agent-name` pattern
  - ✅ `Task(agent="agent-name")` pattern
  - ✅ Case sensitivity handling
  - ✅ Multiple agent references
  - ✅ Malformed patterns (negative tests)

- **Trigger Matching** (Stage 2)
  - ✅ Single trigger match
  - ✅ Multiple trigger matches (confidence scoring)
  - ✅ Partial trigger matches
  - ✅ Trigger priority handling
  - ✅ Agent config loading
  - ✅ Missing config handling

- **AI Selection** (Stage 3)
  - ✅ RTX 5090 vLLM integration
  - ✅ Confidence threshold filtering
  - ✅ Timeout handling (3s max)
  - ✅ Fallback to trigger matching
  - ✅ Model preference selection
  - ✅ Alternative agent suggestions

#### 1.2 Hook Component Tests

**`test_metadata_extractor.py`**
- ✅ Prompt metadata extraction (<15ms)
- ✅ Working directory detection
- ✅ File reference extraction
- ✅ Correlation context integration
- ✅ Session statistics calculation
- ✅ Malformed input handling

**`test_correlation_manager.py`**
- ✅ Correlation ID generation
- ✅ Context persistence across hooks
- ✅ Context retrieval
- ✅ Context cleanup
- ✅ Thread safety
- ✅ Concurrent access handling

**`test_hook_event_logger.py`**
- ✅ UserPromptSubmit event logging
- ✅ PreToolUse event logging
- ✅ PostToolUse event logging
- ✅ Database connection pooling
- ✅ Async logging (non-blocking)
- ✅ Retry logic on failures

#### 1.3 Quality Enforcement Tests

**`test_quality_enforcer.py`**
- ✅ ONEX naming validation
- ✅ Type annotation checking
- ✅ Import statement ordering
- ✅ Docstring validation
- ✅ Error handling patterns
- ✅ Exit code handling (0=pass, 1=block, 2=error)

**`test_post_tool_enforcer.py`**
- ✅ Auto-fix application
- ✅ Metrics collection
- ✅ Success classification
- ✅ Quality scoring
- ✅ Performance metrics
- ✅ Non-blocking operation

### 2. Integration Tests (Moderate, Connected)

**Target**: <500ms per test, 95% integration coverage

#### 2.1 Hook Pipeline Tests (`test_hook_pipeline.py`)

**UserPromptSubmit → PreToolUse → PostToolUse Flow**
```python
def test_complete_hook_pipeline():
    """Test complete hook execution pipeline."""
    # 1. UserPromptSubmit with agent detection
    # 2. Context injection
    # 3. PreToolUse quality validation
    # 4. PostToolUse metrics collection
    # 5. Correlation ID preservation
    # 6. Database event chain
```

**Test Cases**:
- ✅ Happy path: agent detected → quality pass → metrics collected
- ✅ Agent detection failure → pass through
- ✅ Quality violation → blocked execution
- ✅ Auto-fix success → metrics recorded
- ✅ Correlation ID propagation across all hooks
- ✅ Multiple tool invocations in single session

#### 2.2 Database Integration Tests (`test_database_integration.py`)

**Connection Management**
- ✅ Connection pool initialization
- ✅ Connection reuse
- ✅ Connection failure handling
- ✅ Pool exhaustion recovery
- ✅ Graceful degradation

**Event Logging**
- ✅ UserPromptSubmit events
- ✅ PreToolUse events
- ✅ PostToolUse events
- ✅ Session lifecycle events
- ✅ Correlation ID linking
- ✅ Enhanced metadata storage

**Query Performance**
- ✅ Event insertion <50ms
- ✅ Correlation lookup <100ms
- ✅ Session statistics <200ms
- ✅ Index effectiveness
- ✅ Concurrent writes

#### 2.3 Intelligence System Tests (`test_intelligence_integration.py`)

**RAG Query Execution**
- ✅ Background query triggering
- ✅ Archon MCP connectivity
- ✅ Query result storage (/tmp/agent_intelligence_*)
- ✅ Timeout handling
- ✅ Network failure graceful degradation
- ✅ Concurrent query handling

**Agent Configuration**
- ✅ Config loading from ~/.claude/agent-definitions/
- ✅ Intelligence query extraction
- ✅ Domain query generation
- ✅ Implementation query generation
- ✅ Missing config handling
- ✅ Malformed YAML handling

### 3. End-to-End Tests (Slow, Full System)

**Target**: <5s per test, 85% workflow coverage

#### 3.1 Agent Workflow Tests (`test_agent_workflows.py`)

**Workflow: Testing Agent**
```bash
User: "we need to test the polymorphic agents"
  ↓ UserPromptSubmit
  ↓ AI Detection: agent-testing (confidence: 0.95)
  ↓ Context Injection: @MANDATORY_FUNCTIONS, quality gates
  ↓ RAG Queries: pytest patterns, test automation
  ↓ PreToolUse: Validate test file creation
  ↓ PostToolUse: Collect test metrics
  ↓ Database: Full event chain logged
```

**Workflow: Debug Intelligence Agent**
```bash
User: "help debug this database performance issue"
  ↓ UserPromptSubmit
  ↓ AI Detection: agent-debug-intelligence (confidence: 0.92)
  ↓ Context Injection: Debug patterns, performance thresholds
  ↓ RAG Queries: database optimization, profiling
  ↓ PreToolUse: Validate diagnostic code
  ↓ PostToolUse: Collect performance metrics
  ↓ Database: Full event chain logged
```

**Test Cases**:
- ✅ Complete agent-testing workflow
- ✅ Complete agent-debug-intelligence workflow
- ✅ Complete agent-parallel-dispatcher workflow
- ✅ Agent delegation within workflow
- ✅ Multi-agent coordination
- ✅ Intelligence application verification

#### 3.2 Session Lifecycle Tests (`test_session_lifecycle.py`)

**Session Start → Work → Session End**
- ✅ Session initialization
- ✅ Correlation ID generation
- ✅ Multiple prompts in session
- ✅ State preservation
- ✅ Session end cleanup
- ✅ Statistics aggregation

**Session Interruption Scenarios**
- ✅ Stop hook triggered mid-session
- ✅ Unexpected termination
- ✅ Session recovery
- ✅ Correlation chain reconstruction

### 4. Performance Tests (Benchmarking)

**Target**: All hooks <50ms overhead, 95th percentile

#### 4.1 Hook Performance (`test_hook_performance.py`)

**UserPromptSubmit Performance**
- ✅ Pattern detection: <2ms
- ✅ Trigger matching: <10ms
- ✅ AI selection: <3000ms
- ✅ Context injection: <5ms
- ✅ Database logging: <50ms (async)
- ✅ Total overhead: <50ms (without AI), <3050ms (with AI)

**PreToolUse Performance**
- ✅ Quality validation: <100ms
- ✅ Database logging: <50ms (async)
- ✅ Total overhead: <150ms

**PostToolUse Performance**
- ✅ Metrics collection: <50ms
- ✅ Auto-fix application: <200ms
- ✅ Database logging: <50ms (async)
- ✅ Total overhead: <250ms

#### 4.2 Load Tests (`test_load_scenarios.py`)

**Concurrent Sessions**
- ✅ 10 concurrent sessions
- ✅ 50 concurrent sessions
- ✅ 100 concurrent sessions
- ✅ Database connection pool behavior
- ✅ Memory usage monitoring
- ✅ CPU usage monitoring

**High-Volume Event Logging**
- ✅ 1000 events/minute
- ✅ 5000 events/minute
- ✅ Database write performance
- ✅ Event queue handling
- ✅ Backpressure management

### 5. Error Handling Tests

**Target**: 95% error scenario coverage

#### 5.1 Resilience Tests (`test_error_resilience.py`)

**Database Failures**
- ✅ Database unavailable
- ✅ Connection timeout
- ✅ Write failures
- ✅ Connection pool exhaustion
- ✅ Graceful degradation

**Intelligence Service Failures**
- ✅ Archon MCP unavailable
- ✅ RAG query timeout
- ✅ Malformed responses
- ✅ Network errors
- ✅ Fallback behavior

**AI Selection Failures**
- ✅ RTX 5090 server down
- ✅ vLLM timeout
- ✅ Malformed AI responses
- ✅ Confidence too low
- ✅ Fallback to triggers

**File System Failures**
- ✅ Agent config missing
- ✅ Log directory permissions
- ✅ Temp file creation failures
- ✅ Disk space exhaustion

#### 5.2 Security Tests (`test_security.py`)

**Input Validation**
- ✅ SQL injection attempts in prompts
- ✅ Path traversal in file paths
- ✅ Command injection in tool inputs
- ✅ JSON injection in metadata
- ✅ XXE attacks in agent configs

**Resource Limits**
- ✅ Maximum prompt length
- ✅ Maximum correlation chain depth
- ✅ Maximum metadata size
- ✅ Memory leak prevention
- ✅ CPU usage limits

## Test Infrastructure

### Test Fixtures

**Database Fixtures** (`conftest.py`)
```python
@pytest.fixture
def test_db():
    """Isolated test database with schema."""
    # Create test DB
    # Apply migrations
    # Yield connection
    # Cleanup

@pytest.fixture
def mock_archon_mcp():
    """Mock Archon MCP server for RAG queries."""
    # Start mock server
    # Configure responses
    # Yield URL
    # Shutdown
```

**Agent Fixtures**
```python
@pytest.fixture
def test_agent_config():
    """Minimal agent configuration for testing."""

@pytest.fixture
def mock_5090_vllm():
    """Mock RTX 5090 vLLM server for AI selection."""
```

### Test Data

**Sample Prompts** (`test_data/prompts.json`)
```json
{
  "explicit_pattern": "@agent-testing help me write tests",
  "trigger_match": "we need to test the API endpoints",
  "ai_required": "optimize the database query performance",
  "no_agent": "what's the weather today",
  "ambiguous": "help me with the code"
}
```

**Sample Agent Configs** (`test_data/agent_configs/`)
- `agent-testing.yaml`
- `agent-debug-intelligence.yaml`
- `agent-parallel-dispatcher.yaml`
- `agent-invalid.yaml` (for error testing)

### Mock Services

**Mock Archon MCP** (`mocks/mock_archon.py`)
```python
class MockArchonMCP:
    """Mock Archon MCP server for testing."""
    def __init__(self, port=8051):
        self.port = port

    def setup_rag_response(self, query, response):
        """Configure RAG query response."""

    def start(self):
        """Start mock server."""
```

**Mock vLLM Server** (`mocks/mock_vllm.py`)
```python
class MockVLLMServer:
    """Mock vLLM server for AI selection testing."""
    def __init__(self, port=8001):
        self.port = port

    def setup_completion(self, prompt, response):
        """Configure completion response."""
```

## Test Execution

### Test Runner

**pytest Configuration** (`pytest.ini`)
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
markers =
    unit: Unit tests (fast, isolated)
    integration: Integration tests (moderate)
    e2e: End-to-end tests (slow)
    performance: Performance benchmarks
    security: Security tests
    slow: Slow-running tests (>1s)
```

**Run Commands**
```bash
# All tests
pytest

# Unit tests only (fast)
pytest -m unit

# Integration tests
pytest -m integration

# End-to-end tests
pytest -m e2e

# Performance tests
pytest -m performance

# With coverage
pytest --cov=lib --cov-report=html

# Parallel execution
pytest -n auto
```

### Continuous Integration

**GitHub Actions** (`.github/workflows/test-agents.yml`)
```yaml
name: Polymorphic Agent Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.9, 3.10, 3.11]

    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov pytest-xdist

      - name: Run unit tests
        run: pytest -m unit --cov

      - name: Run integration tests
        run: pytest -m integration

      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

## Success Criteria

### Coverage Targets
- **Unit Test Coverage**: ≥95%
- **Integration Test Coverage**: ≥90%
- **End-to-End Test Coverage**: ≥85%
- **Overall Code Coverage**: ≥90%

### Performance Targets
- **Unit Tests**: <100ms per test
- **Integration Tests**: <500ms per test
- **End-to-End Tests**: <5s per test
- **Full Test Suite**: <5 minutes

### Quality Targets
- **Zero Critical Bugs**: Before production
- **All Security Tests Pass**: 100%
- **All Performance Benchmarks Meet SLA**: 95th percentile
- **CI/CD Pipeline**: <10 minutes

## Test Implementation Priority

### Phase 1: Foundation (Week 1)
1. ✅ Test infrastructure setup
2. ✅ Database fixtures
3. ✅ Mock services
4. ✅ Basic unit tests

### Phase 2: Core Coverage (Week 2)
1. ✅ Agent detection tests (all 3 stages)
2. ✅ Hook lifecycle tests
3. ✅ Database integration tests
4. ✅ Quality enforcement tests

### Phase 3: Advanced Testing (Week 3)
1. ✅ End-to-end workflow tests
2. ✅ Performance benchmarks
3. ✅ Load tests
4. ✅ Error handling tests

### Phase 4: Polish (Week 4)
1. ✅ Security tests
2. ✅ CI/CD integration
3. ✅ Documentation
4. ✅ Coverage review

## Maintenance

### Test Maintenance
- Review test coverage monthly
- Update tests for new agents
- Refactor flaky tests
- Performance regression monitoring

### Documentation
- Keep test plan updated
- Document new test patterns
- Maintain test data catalog
- Update CI/CD documentation

---

**Next Steps**: Begin implementation with Phase 1 (Foundation)
