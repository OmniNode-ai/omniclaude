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
    print("ℹ️  Running in CI environment - using GitHub Actions environment variables")

# Add mocks directory for omnibase_core stub
# This allows tests to use mock implementations of external dependencies
MOCKS_DIR = Path(__file__).parent / "mocks"
if str(MOCKS_DIR) not in sys.path:
    sys.path.insert(0, str(MOCKS_DIR))


# ============================================================================
# Kafka Producer Cleanup Fixtures
# ============================================================================


@pytest.fixture(scope="session", autouse=True)
def _cleanup_kafka_producers():
    """
    Automatically cleanup global Kafka producers after all tests complete.

    This fixture ensures that singleton Kafka producers in action_event_publisher
    and transformation_event_publisher are properly closed, preventing
    "Unclosed AIOKafkaProducer" resource warnings.

    Scope: session (runs once after all tests)
    Autouse: True (runs automatically without being requested)
    """
    # Yield to run all tests
    yield

    # Cleanup after all tests complete
    async def cleanup():
        try:
            # Import here to avoid issues if modules aren't used
            from agents.lib import (
                action_event_publisher,
                transformation_event_publisher,
            )

            # Close action event publisher
            if action_event_publisher._kafka_producer is not None:
                await action_event_publisher.close_producer()

            # Close transformation event publisher
            if transformation_event_publisher._kafka_producer is not None:
                await transformation_event_publisher.close_producer()

        except Exception as e:
            # Log but don't fail - cleanup is best-effort
            print(f"Warning: Error during Kafka producer cleanup: {e}")

    # Run cleanup in event loop
    try:
        # Try to get existing event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, get or create one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Always use run_until_complete to ensure cleanup completes before fixture exits
        # This is safe in pytest fixtures which are not async contexts
        loop.run_until_complete(cleanup())
    except Exception as e:
        # Fallback to asyncio.run if event loop management fails
        print(f"Warning: Event loop error during cleanup, using asyncio.run: {e}")
        asyncio.run(cleanup())
