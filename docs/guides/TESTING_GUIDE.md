# Testing Guide

## Test Structure

```
tests/
├── conftest.py          # Fixtures, Kafka mock, pytest configuration
├── unit/                # Fast, isolated tests (@pytest.mark.unit)
│   ├── config/          # Config module tests
│   └── hooks/
│       └── lib/         # Hook handler module tests
├── integration/         # Require Kafka or PostgreSQL (@pytest.mark.integration)
└── ...                  # Additional test directories (aggregators, nodes, etc.)
```

Unit tests must have the `@pytest.mark.unit` decorator and must not require
running infrastructure. Integration tests are gated behind environment
variables (see below).

---

## Running Tests

```bash
# Unit tests only (no services required)
uv run pytest tests/ -m unit -v

# All tests
uv run pytest tests/ -v

# With coverage
uv run pytest tests/ --cov=src/omniclaude --cov=plugins/onex --cov-report=html

# Integration tests (Kafka mocked via conftest.py, no live broker needed)
KAFKA_INTEGRATION_TESTS=1 uv run pytest -m integration

# Integration tests against a live Kafka broker (disables mock)
KAFKA_INTEGRATION_TESTS=real uv run pytest -m integration

# PostgreSQL integration tests
POSTGRES_INTEGRATION_TESTS=1 uv run pytest -m postgres_integration
```

---

## Kafka Mocking

Kafka is fully mocked in unit and integration tests via `tests/conftest.py`.

The `pytest_configure()` hook installs a mock `AIOKafkaProducer` **before
test collection**, which means no real Kafka connections are made for any
test by default. The mock:

- Provides `AsyncMock` implementations of `start()`, `stop()`, `send()`,
  `send_and_wait()`, and `flush()`
- Supports `async with producer:` context managers
- Returns metadata-like objects from send operations
- Tracks calls for assertion in tests

To run against a real broker, set `KAFKA_INTEGRATION_TESTS=real`. This
bypasses the mock entirely.

---

## Unit Test Patterns

### Testing a Handler Module

Handler modules in `plugins/onex/hooks/lib/` are added to `sys.path` by
`conftest.py`, so they can be imported directly by module name:

```python
import pytest
from handler_my_feature import handle


@pytest.mark.unit
def test_handle_returns_dict():
    result = handle({"sessionId": "test-123", "tool_name": "Read"})
    assert isinstance(result, dict)


@pytest.mark.unit
def test_handle_missing_keys_does_not_raise():
    # Handlers must never raise unhandled exceptions
    result = handle({})
    assert isinstance(result, dict)
```

### Testing without the Emit Daemon

The emit daemon (Unix socket at `/tmp/omniclaude-emit.sock`) is not available
in unit tests. Handler modules that call `emit_client_wrapper` should be
tested with the emitter patched:

```python
import pytest
from unittest.mock import patch
from handler_my_feature import handle


@pytest.mark.unit
def test_handle_with_patched_emit():
    with patch("emit_client_wrapper.emit_via_daemon") as mock_emit:
        mock_emit.return_value = None
        result = handle({"sessionId": "test-123"})

    assert isinstance(result, dict)
    mock_emit.assert_called_once()
```

### Testing Routing Logic

The routing wrapper reads from the event bus, which is mocked. Test routing
behavior by patching the underlying call:

```python
import pytest
from unittest.mock import patch


@pytest.mark.unit
def test_routing_returns_expected_agent():
    mock_candidates = [
        {"name": "agent-api-architect", "score": 0.92},
        {"name": "agent-polymorphic", "score": 0.45},
    ]
    with patch("route_via_events_wrapper.get_candidates") as mock_get:
        mock_get.return_value = mock_candidates
        # call the function under test
        ...
```

### Testing Pydantic Event Schemas

Event schemas use `frozen=True`. Test that they validate correctly and
reject unexpected fields:

```python
import pytest
from omniclaude.hooks.schemas import ModelHookPromptSubmittedPayload


@pytest.mark.unit
def test_schema_rejects_missing_required_field():
    with pytest.raises(Exception):
        ModelHookPromptSubmittedPayload()  # missing required fields


@pytest.mark.unit
def test_schema_ignores_extra_fields():
    payload = ModelHookPromptSubmittedPayload(
        session_id="abc",
        prompt_preview="hello",
        prompt_length=5,
        extra_field="ignored",  # extra="ignore" in schema
    )
    assert payload.session_id == "abc"
```

---

## Test Markers

| Marker | When to Use | Infrastructure Required |
|--------|-------------|------------------------|
| `@pytest.mark.unit` | Fast, isolated, no external services | None |
| `@pytest.mark.integration` | Kafka protocol / consumer group tests | `KAFKA_INTEGRATION_TESTS=1` (mocked) or `=real` (live) |
| `@pytest.mark.postgres_integration` | PostgreSQL read/write tests | `POSTGRES_INTEGRATION_TESTS=1` |
| `@pytest.mark.slow` | Long-running (excluded from default runs) | Depends on test |
| `@pytest.mark.benchmark` | Performance benchmarks | None |

Auto-skip rules from `conftest.py`:

- `@pytest.mark.integration` tests skip unless `KAFKA_INTEGRATION_TESTS` is
  set.
- `@pytest.mark.postgres_integration` tests skip unless
  `POSTGRES_INTEGRATION_TESTS=1` is set.

---

## Available Fixtures (from conftest.py)

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `_mock_kafka_producer_globally` | session, autouse | Mocks `AIOKafkaProducer` for all tests |
| `_cleanup_kafka_producers` | session, autouse | Cleans up producer singletons after tests |
| `restore_sys_modules` | function | Saves/restores `sys.modules` state |
| `restore_module_globals` | function | Saves/restores module-level globals |
| `_cleanup_dynamically_loaded_modules` | function, autouse | Removes modules loaded via `importlib` |
| `correlation_id` | function | Generates a UUID string |
| `temp_output_dir` | function | Temporary directory for output files |
| `temp_models_dir` | function | Temporary directory for model files |
| `wait_for_records` | function | Async helper to poll DB for records |
| `sample_effect_contract_yaml` | function | YAML string for EFFECT contract |
| `sample_compute_contract_yaml` | function | YAML string for COMPUTE contract |
| `sample_reducer_contract_yaml` | function | YAML string for REDUCER contract |
| `sample_orchestrator_contract_yaml` | function | YAML string for ORCHESTRATOR contract |
| `node_type` | function, parametrized | All four ONEX node types |
| `all_node_types` | function | List of all ONEX node types |

---

## CI Test Configuration

Unit tests are split across **5 parallel shards** using `pytest-split`.
Coverage reports from all shards are merged after completion and uploaded to
Codecov.

CI jobs that run tests:

| Job | What it tests |
|-----|---------------|
| `test` | Main pytest suite, 5-way parallel split |
| `hooks-tests` | Hook scripts and handler modules |
| `agent-framework-tests` | Agent YAML loading and framework validation |
| `database-validation` | DB schema consistency checks |

All test jobs contribute to the **Tests Gate** required for merge.

See `docs/standards/CI_CD_STANDARDS.md` for the full CI pipeline setup.

---

## Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: handler_my_feature` | Module not in `plugins/onex/hooks/lib/` | Check file path; `sys.path` includes `lib/` via `conftest.py` |
| `Task was destroyed but it is pending!` | Real Kafka producer created | Ensure `pytest_configure` mock is active; don't bypass `aiokafka` mock |
| Integration test not running | Missing env var | Set `KAFKA_INTEGRATION_TESTS=1` or `POSTGRES_INTEGRATION_TESTS=1` |
| Test passes locally, fails in CI | `.env` loaded locally | CI uses GitHub Actions env vars; ensure test doesn't depend on local `.env` values |
