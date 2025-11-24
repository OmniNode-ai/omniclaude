"""
Pytest configuration and shared fixtures for system-status tests.

Created: 2025-11-20
"""

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# Add _shared directory to path for imports
_shared_path = Path(__file__).parent.parent.parent / "_shared"
sys.path.insert(0, str(_shared_path))

# Add skills directory to path (for _shared package imports)
skills_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(skills_dir))

# Add system-status directory to path (for skill package imports)
system_status_dir = Path(__file__).parent.parent
sys.path.insert(0, str(system_status_dir))


@pytest.fixture
def mock_db_connection():
    """Mock database connection for testing."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


@pytest.fixture
def mock_kafka_client():
    """Mock Kafka client for testing."""
    mock_client = MagicMock()
    mock_client.list_topics.return_value = MagicMock()
    return mock_client


@pytest.fixture
def mock_qdrant_client():
    """Mock Qdrant client for testing."""
    mock_client = MagicMock()
    mock_client.get_collections.return_value = MagicMock()
    return mock_client


@pytest.fixture
def sample_db_result():
    """Sample database query result."""
    return {
        "success": True,
        "rows": [{"count": 10, "avg_query_time_ms": 150.5, "avg_patterns_count": 25.0}],
        "host": "192.168.86.200",
        "port": "5436",
        "database": "omninode_bridge",
    }


@pytest.fixture
def sample_error_result():
    """Sample error result."""
    return {
        "success": False,
        "error": "Connection timeout",
        "rows": [],
    }


@pytest.fixture(autouse=True)
def reset_env_vars():
    """Reset environment variables before each test."""
    # Store original values
    original_env = os.environ.copy()

    # Set test defaults
    os.environ.setdefault("POSTGRES_HOST", "192.168.86.200")
    os.environ.setdefault("POSTGRES_PORT", "5436")
    os.environ.setdefault("POSTGRES_DATABASE", "omninode_bridge")
    os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:29092")
    os.environ.setdefault("QDRANT_URL", "http://localhost:6333")

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture(autouse=True)
def cleanup_sys_modules():
    """Clean up imported execute modules between tests to avoid import conflicts."""
    # Remove any execute modules from sys.modules before each test
    modules_to_remove = [key for key in sys.modules if key == "execute"]
    for key in modules_to_remove:
        del sys.modules[key]

    yield

    # Clean up after test
    modules_to_remove = [key for key in sys.modules if key == "execute"]
    for key in modules_to_remove:
        del sys.modules[key]


def load_skill_module(skill_name):
    """
    Load a skill's execute.py module explicitly to avoid import conflicts.

    This function uses importlib.util.spec_from_file_location to load the correct
    execute.py module, avoiding conflicts with other skills' execute.py files.

    Args:
        skill_name: Name of the skill directory (e.g., "check-database-health")

    Returns:
        The loaded execute module

    Example:
        execute = load_skill_module("check-database-health")
        execute.main()
    """
    skill_dir = Path(__file__).parent.parent / skill_name
    execute_path = skill_dir / "execute.py"

    if not execute_path.exists():
        raise FileNotFoundError(f"execute.py not found for skill: {skill_name}")

    # Create a unique module name to avoid conflicts
    module_name = f"execute_{skill_name.replace('-', '_')}"

    # Load the module from the file
    spec = importlib.util.spec_from_file_location(module_name, execute_path)
    module = importlib.util.module_from_spec(spec)

    # Execute the module (this runs the code in execute.py)
    spec.loader.exec_module(module)

    return module
