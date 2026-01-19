"""Shared pytest fixtures for claude package tests."""

import json
import os
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

# =============================================================================
# Path Fixtures
# =============================================================================


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory that's cleaned up after test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_home_dir(temp_dir: Path) -> Generator[Path, None, None]:
    """Mock home directory for testing ~/.claude paths."""
    home = temp_dir / "home"
    home.mkdir()
    with patch.object(Path, "home", return_value=home):
        yield home


@pytest.fixture
def mock_claude_dir(mock_home_dir: Path) -> Path:
    """Create mock ~/.claude directory structure."""
    claude_dir = mock_home_dir / ".claude"
    claude_dir.mkdir()

    # Create subdirectories
    (claude_dir / "agents" / "onex").mkdir(parents=True)
    (claude_dir / ".cache").mkdir()

    return claude_dir


# =============================================================================
# Hook Fixtures
# =============================================================================


@pytest.fixture
def hook_input_bash() -> dict[str, Any]:
    """Sample hook input for Bash tool."""
    return {
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"},
        "session_id": "test-session-123",
    }


@pytest.fixture
def hook_input_write() -> dict[str, Any]:
    """Sample hook input for Write tool."""
    return {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/tmp/test.txt",
            "content": "test content",
        },
        "session_id": "test-session-123",
    }


@pytest.fixture
def hook_input_destructive() -> dict[str, Any]:
    """Sample hook input with destructive command."""
    return {
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf /important"},
        "session_id": "test-session-123",
    }


# =============================================================================
# Agent Registry Fixtures
# =============================================================================


@pytest.fixture
def sample_agent_definition() -> dict[str, Any]:
    """Sample agent definition for testing."""
    return {
        "name": "test-agent",
        "title": "Test Agent",
        "description": "An agent for testing purposes",
        "triggers": ["test", "testing", "run tests"],
        "capabilities": ["testing", "validation"],
        "definition_path": "test-agent.yaml",
    }


@pytest.fixture
def sample_registry(temp_dir: Path, sample_agent_definition: dict[str, Any]) -> Path:
    """Create a sample agent registry file."""
    registry_path = temp_dir / "agent-registry.yaml"
    registry_data = {
        "version": "1.0",
        "agents": {
            "test-agent": sample_agent_definition,
            "polymorphic-agent": {
                "name": "polymorphic-agent",
                "title": "Polymorphic Agent",
                "description": "Multi-purpose agent",
                "triggers": ["help", "analyze", "investigate"],
                "capabilities": ["general"],
                "definition_path": "polymorphic-agent.yaml",
            },
        },
    }
    with open(registry_path, "w") as f:
        yaml.dump(registry_data, f)
    return registry_path


@pytest.fixture
def _mock_registry_env(sample_registry: Path) -> Generator[None, None, None]:
    """Set up environment variable for registry path."""
    with patch.dict(os.environ, {"AGENT_REGISTRY_PATH": str(sample_registry)}):
        yield


# =============================================================================
# Settings Fixtures
# =============================================================================


@pytest.fixture
def mock_settings(mock_claude_dir: Path) -> Path:
    """Create mock settings.json file."""
    settings_path = mock_claude_dir / "settings.json"
    settings_data = {
        "model": "claude-3-sonnet",
        "permissions": {
            "allow": ["Bash:ls", "Read"],
            "deny": ["Write:/etc/*"],
        },
    }
    with open(settings_path, "w") as f:
        json.dump(settings_data, f)
    return settings_path


# =============================================================================
# Cache Fixtures
# =============================================================================


@pytest.fixture
def empty_cache(mock_claude_dir: Path) -> Path:
    """Create empty cache directory."""
    cache_dir = mock_claude_dir / ".cache"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir


@pytest.fixture
def populated_cache(empty_cache: Path) -> Path:
    """Create cache with some test data."""
    cache_file = empty_cache / "test-cache.json"
    cache_data = {
        "key1": {"value": "data1", "timestamp": 1000000},
        "key2": {"value": "data2", "timestamp": 1000001},
    }
    with open(cache_file, "w") as f:
        json.dump(cache_data, f)
    return empty_cache


# =============================================================================
# Mock Service Fixtures
# =============================================================================


@pytest.fixture
def mock_kafka_producer() -> Generator[MagicMock, None, None]:
    """Mock Kafka producer for event publishing tests."""
    with patch("aiokafka.AIOKafkaProducer") as mock:
        producer = MagicMock()
        producer.send_and_wait = MagicMock()
        mock.return_value = producer
        yield producer


@pytest.fixture
def mock_postgres_connection() -> Generator[MagicMock, None, None]:
    """Mock PostgreSQL connection for database tests."""
    with patch("asyncpg.connect") as mock:
        conn = MagicMock()
        conn.execute = MagicMock()
        conn.fetch = MagicMock(return_value=[])
        conn.fetchrow = MagicMock(return_value=None)
        mock.return_value = conn
        yield conn


# =============================================================================
# Async Test Configuration
# =============================================================================
# pytest-asyncio automatically manages event loop lifecycle.
# Configure async mode in pyproject.toml: [tool.pytest.ini_options] asyncio_mode = "auto"
# For custom event loop policies, use the pytest-asyncio event_loop fixture instead.
