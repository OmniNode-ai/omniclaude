#!/usr/bin/env python3
"""
Test fixtures and configuration for omniclaude testing.

Provides comprehensive fixtures for:
- Kafka producer mocking (prevents real connections during tests)
- Sample contract YAML fixtures
- Database wait helpers
- Performance benchmarking
"""

import os
import sys
from pathlib import Path

# CRITICAL: sys.path manipulation for proper package discovery
#
# Why this is necessary (not removable without breaking tests):
# 1. The project has both src/omniclaude/ (new) and legacy omniclaude/ directory
# 2. pytest's pythonpath setting in pyproject.toml doesn't guarantee import order
# 3. Without this, tests may import from the legacy directory causing import errors
# 4. This runs BEFORE any imports to ensure src/omniclaude takes precedence
#
# Alternative considered: Using pytest's pythonpath in pyproject.toml alone doesn't
# work reliably because the legacy directory name conflicts with the package name.
# This explicit path manipulation is the most reliable solution until the legacy
# directory is fully archived/removed.
_src_path = str(Path(__file__).parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

# Plugin lib path for session_marker and other plugin library imports
# This is needed by tests that import from plugins/onex/hooks/lib/
_plugin_lib_path = str(
    Path(__file__).parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if _plugin_lib_path not in sys.path:
    sys.path.insert(0, _plugin_lib_path)

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from dotenv import load_dotenv

# Only load .env in local development (not in CI)
# In CI, environment variables are set by GitHub Actions and should not be overridden
if not os.getenv("CI"):
    # Load environment variables from .env file for distributed testing
    # This ensures tests use the correct remote infrastructure configuration
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
        print(f"Loaded .env configuration from {env_path}")
    else:
        print(f"No .env file found at {env_path}, using system environment variables")
else:
    print("Running in CI environment - using GitHub Actions environment variables")

# -------------------------------------------------------------------------
# Mock Kafka Producer - Prevents Real Connections During Tests
# -------------------------------------------------------------------------
#
# This section implements a comprehensive mocking strategy for AIOKafkaProducer
# to prevent real Kafka connections during tests and eliminate background task
# warnings ("Task was destroyed but it is pending!").
#
# Strategy:
# 1. pytest_configure() hook (line ~410) - Patches aiokafka.AIOKafkaProducer
#    BEFORE test collection - this is the earliest point to install the mock
# 2. mock_kafka_producer_globally() fixture (line ~757) - Session-scoped autouse
#    fixture that serves as explicit documentation and backup verification
# 3. pytest_sessionfinish() hook (line ~740) - Cleanup after all tests complete
# 4. pytest_unconfigure() hook (line ~718) - Final cleanup to restore original
#
# Result:
# - No real AIOKafkaProducer instances created during tests
# - No background tasks (_md_synchronizer, _sender_routine, _read, etc.)
# - No "Task was destroyed" warnings with pytest -n 0
# - Single mock instance reused across all tests (efficient)
# - All async methods properly mocked with AsyncMock
# - Supports context managers (async with producer:)
# - Returns metadata-like objects from send operations
#
# The hook-based approach (pytest_configure) is superior to fixtures alone
# because it runs even earlier in pytest lifecycle, before test collection.
# The fixture serves as documentation and verification that the mock is active.

# Global mock producer instance - reused across all tests
_mock_kafka_producer_instance = None


def _create_mock_kafka_producer():
    """
    Create a mock AIOKafkaProducer that doesn't start real connections.

    This mock:
    - Has all the async methods as AsyncMock
    - Doesn't create background tasks
    - Doesn't connect to Kafka
    - Tracks calls for assertion in tests
    - Returns proper metadata-like objects from send operations

    Methods mocked:
    - start() - AsyncMock, called when producer is started
    - stop() - AsyncMock, called when producer is stopped
    - send() - AsyncMock, returns FutureRecordMetadata-like object
    - send_and_wait() - AsyncMock, returns RecordMetadata-like object
    - flush() - AsyncMock, waits for pending sends
    """
    mock = MagicMock()

    # Async methods - using AsyncMock so they can be awaited
    mock.start = AsyncMock()
    mock.stop = AsyncMock()

    # send() returns a FutureRecordMetadata-like object that can be awaited
    metadata_mock = MagicMock()
    metadata_mock.topic = "test-topic"
    metadata_mock.partition = 0
    metadata_mock.offset = 0

    mock.send = AsyncMock(return_value=metadata_mock)
    mock.send_and_wait = AsyncMock(return_value=metadata_mock)
    mock.flush = AsyncMock()

    # Support for async context manager (async with producer:)
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)

    # Internal attributes that some code might check
    mock._closed = False
    mock._sender = None
    mock._client = None

    return mock


def _get_mock_kafka_producer(*args, **kwargs):
    """
    Factory function that returns the global mock producer instance.

    Called when AIOKafkaProducer() is instantiated anywhere in the codebase.
    """
    global _mock_kafka_producer_instance
    if _mock_kafka_producer_instance is None:
        _mock_kafka_producer_instance = _create_mock_kafka_producer()
    return _mock_kafka_producer_instance


# Flag to indicate if Kafka is mocked (used by integration tests)
KAFKA_IS_MOCKED = True


# -------------------------------------------------------------------------
# Sample Contract Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def sample_effect_contract_yaml() -> str:
    """Sample EFFECT contract YAML for testing."""
    return """
name: NodeDatabaseWriterEffect
version: "1.0.0"
description: "Writes data to PostgreSQL database"
node_type: EFFECT
input_model: ModelDatabaseInput
output_model: ModelDatabaseOutput
error_model: ModelOnexError
io_operations:
  - operation_type: database_write
    target: postgresql
    is_async: true
lifecycle:
  initialization: ["connect_to_database"]
  cleanup: ["close_connection"]
dependencies:
  - name: asyncpg
    module: asyncpg
    dependency_type: module
  - name: psycopg2-binary
    module: psycopg2
    dependency_type: module
performance:
  expected_duration_ms: 100
  timeout_ms: 5000
"""


@pytest.fixture
def sample_compute_contract_yaml() -> str:
    """Sample COMPUTE contract YAML for testing."""
    return """
name: NodeDataTransformerCompute
version: "1.0.0"
description: "Transforms data using pure computation"
node_type: COMPUTE
input_model: ModelDataInput
output_model: ModelDataOutput
algorithm:
  algorithm_type: transformation
  factors:
    factor_1:
      weight: 0.6
      calculation_method: linear
    factor_2:
      weight: 0.4
      calculation_method: exponential
dependencies:
  - name: numpy
    module: numpy
    dependency_type: module
performance:
  expected_duration_ms: 50
  timeout_ms: 2000
  single_operation_max_ms: 100
"""


@pytest.fixture
def sample_reducer_contract_yaml() -> str:
    """Sample REDUCER contract YAML for testing."""
    return """
name: NodeAggregationReducer
version: "1.0.0"
description: "Aggregates data and emits intents"
node_type: REDUCER
input_model: ModelAggregationInput
output_model: ModelAggregationOutput
aggregation_strategy: sum
state_management:
  state_management_enabled: true
  state_scope: node_local
intent_emissions:
  - intent_type: data_aggregated
    destination: event_bus
dependencies:
  - name: redis
    module: redis
    dependency_type: module
performance:
  expected_duration_ms: 200
  timeout_ms: 10000
"""


@pytest.fixture
def sample_orchestrator_contract_yaml() -> str:
    """Sample ORCHESTRATOR contract YAML for testing."""
    return """
name: NodeWorkflowOrchestrator
version: "1.0.0"
description: "Orchestrates multi-step workflow"
node_type: ORCHESTRATOR
input_model: ModelWorkflowInput
output_model: ModelWorkflowOutput
workflow_coordination:
  workflow_coordination_enabled: true
  orchestration_pattern: sequential
dependencies:
  - name: redis
    module: redis
    dependency_type: module
  - name: asyncio
    module: asyncio
    dependency_type: module
performance:
  single_operation_max_ms: 500
  expected_duration_ms: 500
  timeout_ms: 30000
"""


@pytest.fixture
def invalid_contract_yaml() -> str:
    """Invalid contract YAML for testing validation errors."""
    return """
name: InvalidNode
# Missing required fields: version, description, node_type
input_model: ModelInput
"""


# -------------------------------------------------------------------------
# Temporary Directory Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def temp_output_dir(tmp_path: Path) -> Path:
    """Create temporary output directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


@pytest.fixture
def temp_models_dir(tmp_path: Path) -> Path:
    """Create temporary models directory."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    return models_dir


# -------------------------------------------------------------------------
# Sample Prompt Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def sample_effect_prompt() -> str:
    """Sample prompt for EFFECT node generation."""
    return "Create EFFECT node for PostgreSQL database write operations"


@pytest.fixture
def sample_compute_prompt() -> str:
    """Sample prompt for COMPUTE node generation."""
    return "Create COMPUTE node for data transformation using numpy"


@pytest.fixture
def sample_reducer_prompt() -> str:
    """Sample prompt for REDUCER node generation."""
    return "Create REDUCER node for data aggregation with intent emission"


@pytest.fixture
def sample_orchestrator_prompt() -> str:
    """Sample prompt for ORCHESTRATOR node generation."""
    return "Create ORCHESTRATOR node for multi-step workflow coordination"


# -------------------------------------------------------------------------
# Node Type Fixtures
# -------------------------------------------------------------------------


@pytest.fixture(params=["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"])
def node_type(request) -> str:
    """Parametrized fixture for all node types."""
    return str(request.param)


@pytest.fixture
def all_node_types() -> list[str]:
    """List of all supported node types."""
    return ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]


# -------------------------------------------------------------------------
# Mock Data Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def mock_parsed_data() -> dict:
    """Mock parsed data from prompt parser."""
    return {
        "node_type": "EFFECT",
        "service_name": "test_service",
        "domain": "test_domain",
        "description": "Test node for testing purposes",
        "operations": ["write", "read"],
        "features": ["async", "caching"],
        "confidence": 0.85,
    }


@pytest.fixture
def correlation_id() -> str:
    """Generate correlation ID for testing."""
    return str(uuid4())


# -------------------------------------------------------------------------
# Performance Benchmark Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def benchmark_iterations() -> int:
    """Number of iterations for performance benchmarks."""
    return 10


@pytest.fixture
def performance_thresholds() -> dict[str, float]:
    """Performance thresholds for different operations."""
    return {
        "contract_validation_ms": 200,
        "effect_generation_s": 45,
        "compute_generation_s": 40,
        "reducer_generation_s": 50,
        "orchestrator_generation_s": 55,
        "average_generation_s": 48,
    }


# -------------------------------------------------------------------------
# pytest configuration
# -------------------------------------------------------------------------


def pytest_configure(config):
    """
    Configure pytest with custom markers and mock Kafka producer.

    This hook runs BEFORE any tests are collected, making it the ideal place
    to install mocks that prevent real Kafka connections. This eliminates the
    "Task was destroyed but it is pending!" warnings that occur when real
    Kafka producers are created but not properly cleaned up.
    """
    # Add custom markers
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (deselect with '-m \"not integration\"')",
    )
    config.addinivalue_line(
        "markers",
        "benchmark: marks tests as performance benchmarks (deselect with '-m \"not benchmark\"')",
    )
    config.addinivalue_line(
        "markers",
        "postgres_integration: marks tests as PostgreSQL integration tests",
    )

    # Mock AIOKafkaProducer at the earliest possible point
    # This prevents real Kafka connections during tests, which eliminates
    # the "Task was destroyed but it is pending!" warnings from background tasks
    # like _md_synchronizer(), _sender_routine(), and _read() that can't be
    # properly cleaned up when the event loop closes.
    try:
        import aiokafka

        # Store original for potential restoration
        config._original_aiokafka_producer = aiokafka.AIOKafkaProducer

        # Replace with mock factory
        aiokafka.AIOKafkaProducer = _get_mock_kafka_producer

        # Also patch in sys.modules to catch imports that happen later
        if "aiokafka" in sys.modules:
            sys.modules["aiokafka"].AIOKafkaProducer = _get_mock_kafka_producer  # type: ignore[attr-defined]

    except ImportError:
        # aiokafka not installed, no need to mock
        pass


def pytest_collection_modifyitems(config, items):
    """
    Auto-skip integration tests when infrastructure is mocked.

    Integration tests that require real infrastructure will be skipped
    automatically when running with mocked producers. To run integration
    tests, either:
    1. Use environment variable: KAFKA_INTEGRATION_TESTS=1 pytest ... (for Kafka tests)
    2. Use environment variable: POSTGRES_INTEGRATION_TESTS=1 pytest ... (for Postgres tests)
    3. Mark specific tests to always run with @pytest.mark.force_real_kafka

    Note: Tests marked with @pytest.mark.postgres_integration will only run when
    POSTGRES_INTEGRATION_TESTS=1, even if KAFKA_INTEGRATION_TESTS=1 is also set.
    """
    kafka_enabled = os.getenv("KAFKA_INTEGRATION_TESTS") == "1"
    postgres_enabled = os.getenv("POSTGRES_INTEGRATION_TESTS") == "1"

    # If either integration test type is enabled, check individual tests
    skip_kafka = pytest.mark.skip(
        reason="Skipping Kafka integration test: Kafka is mocked. "
        "Set KAFKA_INTEGRATION_TESTS=1 to run with real Kafka."
    )
    skip_postgres = pytest.mark.skip(
        reason="Skipping PostgreSQL integration test. "
        "Set POSTGRES_INTEGRATION_TESTS=1 to run with real PostgreSQL."
    )

    for item in items:
        # Check if test is specifically a postgres integration test
        # (by checking for postgres_integration marker instead of brittle path detection)
        is_postgres_test = "postgres_integration" in item.keywords

        if "integration" in item.keywords:
            if is_postgres_test:
                # PostgreSQL integration test - needs POSTGRES_INTEGRATION_TESTS
                if not postgres_enabled:
                    item.add_marker(skip_postgres)
            else:
                # Kafka integration test - needs KAFKA_INTEGRATION_TESTS
                if not kafka_enabled:
                    item.add_marker(skip_kafka)


# -------------------------------------------------------------------------
# Database Wait Helper for Kafka Consumer Tests
# -------------------------------------------------------------------------


async def wait_for_db_condition(
    db_pool,
    query: str,
    expected_condition,
    timeout_seconds: float = 10.0,
    poll_interval: float = 0.2,
    *query_args,
):
    """
    Wait for a database condition to be met with retry logic.

    Args:
        db_pool: asyncpg connection pool
        query: SQL query to execute
        expected_condition: Callable that takes query result and returns True if condition met
        timeout_seconds: Maximum time to wait
        poll_interval: Time between polls
        *query_args: Arguments for the query

    Returns:
        Query result when condition is met

    Raises:
        TimeoutError: If condition not met within timeout
    """
    start_time = asyncio.get_running_loop().time()

    while (asyncio.get_running_loop().time() - start_time) < timeout_seconds:
        async with db_pool.acquire() as conn:
            result = (
                await conn.fetchval(query, *query_args)
                if query_args
                else await conn.fetchval(query)
            )

            if expected_condition(result):
                return result

        await asyncio.sleep(poll_interval)

    # Timeout - get final result for error message
    async with db_pool.acquire() as conn:
        final_result = (
            await conn.fetchval(query, *query_args)
            if query_args
            else await conn.fetchval(query)
        )

    raise TimeoutError(
        f"Database condition not met within {timeout_seconds}s. Final result: {final_result}"
    )


@pytest.fixture
async def wait_for_records():
    """
    Fixture that provides a helper to wait for records in database.

    Usage in tests:
        count = await wait_for_records(
            db_pool,
            correlation_id=correlation_id,
            expected_count=4,
            timeout_seconds=10.0
        )
    """

    async def _wait_for_records(
        db_pool,
        correlation_id: str | None = None,
        agent_name: str | None = None,
        expected_count: int = 1,
        timeout_seconds: float = 10.0,
        poll_interval: float = 0.2,
    ):
        """Wait for expected number of records to appear in agent_actions table."""
        args: tuple[str, ...] = ()
        if correlation_id:
            query = "SELECT COUNT(*) FROM agent_actions WHERE correlation_id = $1"
            args = (correlation_id,)
        elif agent_name:
            query = "SELECT COUNT(*) FROM agent_actions WHERE agent_name = $1"
            args = (agent_name,)
        else:
            raise ValueError("Must provide either correlation_id or agent_name")

        return await wait_for_db_condition(
            db_pool,
            query,
            lambda count: count >= expected_count,
            timeout_seconds,
            poll_interval,
            *args if args else (),
        )

    return _wait_for_records


# -------------------------------------------------------------------------
# Kafka Producer Cleanup Fixtures
# -------------------------------------------------------------------------


def _cleanup_all_kafka_producers_sync():
    """
    Synchronously cleanup ALL global Kafka producers.

    This function handles cleanup of all 5 Kafka producer singletons in the codebase:
    - action_event_publisher._kafka_producer
    - transformation_event_publisher._kafka_producer
    - confidence_scoring_publisher._kafka_producer
    - quality_gate_publisher._kafka_producer
    - provider_selection_publisher._kafka_producer

    Plus the logging_event_publisher global singleton:
    - logging_event_publisher._global_publisher

    The function handles various event loop states:
    1. Running loop: Cannot cleanup synchronously, skip (async cleanup handles it)
    2. Available non-closed loop: Use run_until_complete
    3. Closed loop: Force-close producer internals directly
    """
    # List of all Kafka producer modules and their global variable names
    producer_modules = [
        ("claude.lib.action_event_publisher", "_kafka_producer", "close_producer"),
        (
            "claude.lib.transformation_event_publisher",
            "_kafka_producer",
            "close_producer",
        ),
        (
            "claude.lib.confidence_scoring_publisher",
            "_kafka_producer",
            "close_producer",
        ),
        ("claude.lib.quality_gate_publisher", "_kafka_producer", "close_producer"),
        (
            "claude.lib.provider_selection_publisher",
            "_kafka_producer",
            "close_producer",
        ),
    ]

    # Check event loop state once
    loop = None
    loop_is_available = False

    try:
        loop = asyncio.get_running_loop()
        # Loop is running, can't cleanup synchronously
        print(
            "Warning: Event loop is running during Kafka cleanup, skipping sync cleanup"
        )
        return
    except RuntimeError:
        pass

    # Try to get event loop without triggering deprecation warning
    # In Python 3.10+, get_event_loop() raises DeprecationWarning when no running loop
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop = asyncio.get_event_loop_policy().get_event_loop()
            if loop is not None and not loop.is_closed():
                loop_is_available = True
        except RuntimeError:
            # No event loop exists, we'll use force cleanup
            pass

    # Cleanup each producer module
    for module_name, producer_var, close_func in producer_modules:
        try:
            module = __import__(module_name, fromlist=[producer_var])
            producer = getattr(module, producer_var, None)

            if producer is None:
                continue

            if loop_is_available and loop is not None:
                # Use async cleanup with available loop
                close_coro = getattr(module, close_func)
                try:
                    loop.run_until_complete(close_coro())
                except Exception as e:
                    print(f"Warning: Async cleanup failed for {module_name}: {e}")
                    # Fall through to force cleanup
                    _force_close_producer(producer)
            else:
                # Force close without event loop
                _force_close_producer(producer)

            # Clear the global variable
            setattr(module, producer_var, None)

        except ImportError:
            # Module not used, skip
            pass
        except Exception as e:
            print(f"Warning: Error cleaning up {module_name}: {e}")

    # Cleanup logging_event_publisher._global_publisher
    try:
        from omniclaude.lib import logging_event_publisher

        publisher = logging_event_publisher._global_publisher
        if publisher is not None:
            if loop_is_available and loop is not None:
                try:
                    loop.run_until_complete(publisher.stop())
                except Exception as e:
                    print(
                        f"Warning: Async cleanup failed for logging_event_publisher: {e}"
                    )
                    if publisher._producer is not None:
                        _force_close_producer(publisher._producer)
            elif publisher._producer is not None:
                _force_close_producer(publisher._producer)
            logging_event_publisher._global_publisher = None
    except ImportError:
        pass
    except Exception as e:
        print(f"Warning: Error cleaning up logging_event_publisher: {e}")


def _force_close_producer(producer):
    """
    Force-close a Kafka producer without async operations.

    This directly closes the underlying client connection to prevent
    "Unclosed AIOKafkaProducer" warnings when the event loop is closed.

    Note:
        This function accesses private attributes of AIOKafkaProducer because
        the public `close()` method is async and cannot be called from sync
        pytest hooks where the event loop may not be running. This is intentional
        for test teardown and uses getattr() for safer access in case internal
        implementation changes.

    Args:
        producer: AIOKafkaProducer instance to force-close
    """
    if producer is None:
        return

    try:
        # Cancel background tasks first
        # Note: Accessing private _sender attribute for test cleanup
        sender = getattr(producer, "_sender", None)
        if sender is not None:
            sender_task = getattr(sender, "_sender_task", None)
            if sender_task is not None and not sender_task.done():
                sender_task.cancel()

        # Close the client connection
        # Note: Accessing private _client attribute because async close()
        # cannot be called from sync context during pytest teardown
        client = getattr(producer, "_client", None)
        if client is not None:
            close_method = getattr(client, "close", None)
            if callable(close_method):
                close_method()

        # Mark as closed
        # Note: Setting private _closed attribute to prevent double-close
        if hasattr(producer, "_closed"):
            producer._closed = True

    except Exception as e:
        print(f"Warning: Error during force close of producer: {e}")


def pytest_unconfigure(config):
    """
    Restore original AIOKafkaProducer after all tests complete.

    This hook runs after pytest_sessionfinish, ensuring that if any other
    code (e.g., plugins) needs the real producer, it's available.
    """
    try:
        import aiokafka

        if hasattr(config, "_original_aiokafka_producer"):
            aiokafka.AIOKafkaProducer = config._original_aiokafka_producer
            if "aiokafka" in sys.modules:
                sys.modules["aiokafka"].AIOKafkaProducer = (  # type: ignore[attr-defined]
                    config._original_aiokafka_producer
                )
    except ImportError:
        pass

    # Reset the global mock instance for clean state
    global _mock_kafka_producer_instance
    _mock_kafka_producer_instance = None


def pytest_sessionfinish(session, exitstatus):
    """
    Pytest hook called after all tests complete, BEFORE fixture teardown.

    With the mock Kafka producer installed in pytest_configure, real producers
    are never created, so cleanup is minimal. This hook is kept as a safety net
    for edge cases where real producers might have been created (e.g., if a test
    explicitly restored the original producer).
    """
    # Reset global mock instance
    global _mock_kafka_producer_instance
    _mock_kafka_producer_instance = None

    # Safety cleanup for any edge cases where real producers were created
    _cleanup_all_kafka_producers_sync()


@pytest.fixture(scope="session", autouse=True)
def _mock_kafka_producer_globally():
    """
    Session-scoped autouse fixture to mock AIOKafkaProducer globally.

    This fixture works in conjunction with pytest_configure() hook to ensure
    that AIOKafkaProducer is mocked before ANY tests run, preventing real
    Kafka connections and the "Task was destroyed but it is pending!" warnings.

    Why session-scoped + autouse:
    - session: Single mock instance reused across all tests (efficient)
    - autouse: No need to import or request in tests (implicit)

    Why both fixture AND hook:
    - pytest_configure runs even earlier (before collection)
    - Fixture serves as explicit documentation and backup
    - Together they ensure all import paths are covered

    The fixture yields after the hook has already mocked AIOKafkaProducer,
    confirming the mock is active for the session.
    """
    # Hook has already installed the mock in pytest_configure()
    # Verify it's active by checking the global instance
    global _mock_kafka_producer_instance
    assert (
        _mock_kafka_producer_instance is not None
        or _get_mock_kafka_producer() is not None
    )

    # Yield to run all tests with the mock active
    yield

    # Reset after tests complete (backup, primary cleanup in pytest_sessionfinish)
    _mock_kafka_producer_instance = None


@pytest.fixture(scope="session", autouse=True)
def _cleanup_kafka_producers():
    """
    Automatically cleanup global Kafka producers after all tests complete.

    This fixture ensures that singleton Kafka producers are properly closed,
    preventing "Unclosed AIOKafkaProducer" resource warnings.

    Note: The primary cleanup happens in pytest_sessionfinish hook.
    This fixture serves as a backup and handles any edge cases.

    Scope: session (runs once after all tests)
    Autouse: True (runs automatically without being requested)
    """
    # Yield to run all tests
    yield

    # Backup cleanup - primary cleanup is in pytest_sessionfinish
    # This handles edge cases where sessionfinish didn't run
    _cleanup_all_kafka_producers_sync()


# -------------------------------------------------------------------------
# Module Reload Cleanup Fixtures
# -------------------------------------------------------------------------
# These fixtures prevent test pollution when tests reload modules or modify
# global state. PR #92 review identified this as a potential source of flaky
# tests when module reloads affect subsequent tests.


@pytest.fixture
def restore_sys_modules():
    """
    Fixture to capture and restore sys.modules state after a test.

    Use this fixture in tests that modify sys.modules or use importlib.reload()
    to prevent test pollution affecting subsequent tests.

    Usage:
        def test_something(restore_sys_modules):
            # Test that modifies sys.modules
            import importlib
            import mymodule
            importlib.reload(mymodule)
            # sys.modules will be restored after test

    Warning:
        This is a function-scoped fixture. For module reloads that affect
        global state (like singletons), consider using restore_module_globals
        or creating a custom cleanup fixture.
    """
    # Capture the current state of sys.modules
    original_modules = sys.modules.copy()
    original_keys = set(sys.modules.keys())

    yield

    # Restore sys.modules to original state
    # Remove any modules that were added
    current_keys = set(sys.modules.keys())
    added_keys = current_keys - original_keys
    for key in added_keys:
        del sys.modules[key]

    # Restore any modules that were modified (replaced with different objects)
    for key, module in original_modules.items():
        if key in sys.modules and sys.modules[key] is not module:
            sys.modules[key] = module


@pytest.fixture
def restore_module_globals():
    """
    Factory fixture to restore global state in a module after a test.

    Use this when tests modify module-level globals (like singletons) that
    need to be reset to prevent test pollution.

    Usage:
        def test_something(restore_module_globals):
            import mymodule

            # Register the module and globals to restore
            restore = restore_module_globals(mymodule, ['_singleton', '_cache'])

            # Test that modifies globals
            mymodule._singleton = "test_value"
            mymodule._cache = {"key": "value"}

            # Globals will be restored after test

    Args:
        module: The module object containing globals to restore
        global_names: List of global variable names to capture and restore

    Returns:
        A cleanup function (called automatically via fixture teardown)
    """
    restore_actions: list[tuple] = []

    def _register_restore(module, global_names: list[str]):
        """Register a module's globals to be restored after test."""
        original_values = {}
        for name in global_names:
            if hasattr(module, name):
                original_values[name] = getattr(module, name)
            else:
                # Track that the attribute didn't exist (so we can delete it)
                original_values[name] = _SENTINEL_NOT_EXISTS

        restore_actions.append((module, original_values))

    yield _register_restore

    # Restore all registered globals
    for module, original_values in restore_actions:
        for name, value in original_values.items():
            if value is _SENTINEL_NOT_EXISTS:
                # Attribute didn't exist before, delete if it was added
                if hasattr(module, name):
                    delattr(module, name)
            else:
                setattr(module, name, value)


# Sentinel value to track attributes that didn't exist
class _SentinelNotExists:
    """Sentinel to indicate an attribute did not exist."""

    pass


_SENTINEL_NOT_EXISTS = _SentinelNotExists()


@pytest.fixture(autouse=True)
def _cleanup_dynamically_loaded_modules():
    """
    Auto-cleanup for dynamically loaded modules added during tests.

    This fixture automatically removes modules that were dynamically loaded
    via importlib.util.spec_from_file_location() during tests. These modules
    are registered in sys.modules with custom names (like "transformation_event_publisher")
    that could pollute subsequent tests.

    Modules cleaned up:
    - transformation_event_publisher (from test_transformation_event_publisher.py)
    - Any module with a path containing "omniclaude3/tests" but not the standard
      package path

    This runs after every test to ensure a clean module state.
    """
    yield

    # List of known dynamically-loaded test modules to cleanup
    dynamic_modules = [
        "transformation_event_publisher",  # From test_transformation_event_publisher.py
    ]

    for module_name in dynamic_modules:
        if module_name in sys.modules:
            del sys.modules[module_name]
