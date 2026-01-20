#!/usr/bin/env python3
"""
Pytest Configuration File (conftest.py)

NOTE: This conftest.py uses sys.path manipulation for pytest test discovery and imports.
This is a standard pytest pattern when tests need to import from parent directories
and when test fixtures/mocks need to be accessible.

BETTER APPROACH: Instead of sys.path manipulation in conftest.py, consider:
1. Installing the package in development mode: `pip install -e .`
2. Configuring PYTHONPATH in pytest.ini or pyproject.toml:
   [tool.pytest.ini_options]
   pythonpath = ["."]
3. Using proper package structure with __init__.py files

However, for standalone test directories, conftest.py sys.path manipulation is acceptable
and is a common pytest pattern. This runs once during test collection and is isolated
to the test execution environment.
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Load environment variables from .env file before any tests run
# This ensures database credentials and other config are available
from dotenv import load_dotenv

# Ensure project root is on sys.path for test imports
# This allows tests to import from the agents package
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Only load .env in local development (not in CI)
# In CI, environment variables are set by GitHub Actions and should not be overridden
if not os.getenv("CI"):
    # Load .env from project root
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        # Fallback: try to load from current directory
        load_dotenv()
else:
    print("Running in CI environment - using GitHub Actions environment variables")

# Add mocks directory for omnibase_core stub
# This allows tests to use mock implementations of external dependencies
MOCKS_DIR = Path(__file__).parent / "mocks"
if str(MOCKS_DIR) not in sys.path:
    sys.path.insert(0, str(MOCKS_DIR))


# ============================================================================
# Mock Kafka Producer - Prevents Real Connections During Tests
# ============================================================================

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
    """
    mock = MagicMock()
    mock.start = AsyncMock()
    mock.stop = AsyncMock()
    mock.send = AsyncMock(return_value=MagicMock())  # Returns RecordMetadata-like
    mock.send_and_wait = AsyncMock(return_value=MagicMock())
    mock.flush = AsyncMock()
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


def pytest_configure(config):
    """
    Mock AIOKafkaProducer at the earliest possible point.

    This prevents real Kafka connections during tests, which eliminates
    the "Task was destroyed but it is pending!" warnings from background tasks.
    """
    try:
        import aiokafka

        # Store original for potential restoration
        config._original_aiokafka_producer = aiokafka.AIOKafkaProducer

        # Replace with mock factory
        aiokafka.AIOKafkaProducer = _get_mock_kafka_producer

        # Also patch in sys.modules to catch imports that happen later
        if "aiokafka" in sys.modules:
            sys.modules["aiokafka"].AIOKafkaProducer = _get_mock_kafka_producer

    except ImportError:
        # aiokafka not installed, no need to mock
        pass


def pytest_collection_modifyitems(config, items):
    """
    Auto-skip integration tests when Kafka is mocked.

    Integration tests that require real Kafka infrastructure will be skipped
    automatically when running with the mocked producer.
    """
    if os.getenv("KAFKA_INTEGRATION_TESTS") == "1":
        # User explicitly wants to run integration tests
        return

    skip_integration = pytest.mark.skip(
        reason="Skipping integration test: Kafka is mocked. "
        "Set KAFKA_INTEGRATION_TESTS=1 to run with real Kafka."
    )

    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


# ============================================================================
# Kafka Producer Cleanup Fixtures
# ============================================================================


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
        ("agents.lib.action_event_publisher", "_kafka_producer", "close_producer"),
        (
            "agents.lib.transformation_event_publisher",
            "_kafka_producer",
            "close_producer",
        ),
        (
            "agents.lib.confidence_scoring_publisher",
            "_kafka_producer",
            "close_producer",
        ),
        ("agents.lib.quality_gate_publisher", "_kafka_producer", "close_producer"),
        (
            "agents.lib.provider_selection_publisher",
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
        from agents.lib import logging_event_publisher

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
            else:
                if publisher._producer is not None:
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

    Args:
        producer: AIOKafkaProducer instance to force-close
    """
    if producer is None:
        return

    try:
        # Cancel background tasks first
        if hasattr(producer, "_sender") and producer._sender is not None:
            if hasattr(producer._sender, "_sender_task"):
                task = producer._sender._sender_task
                if task is not None and not task.done():
                    task.cancel()

        # Close the client connection
        if hasattr(producer, "_client") and producer._client is not None:
            producer._client.close()

        # Mark as closed
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
                sys.modules["aiokafka"].AIOKafkaProducer = (
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
    for edge cases where real producers might have been created.
    """
    # Reset global mock instance
    global _mock_kafka_producer_instance
    _mock_kafka_producer_instance = None

    # Safety cleanup for any edge cases where real producers were created
    _cleanup_all_kafka_producers_sync()


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
