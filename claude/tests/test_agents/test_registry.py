"""Comprehensive tests for agent registry module.

Tests cover:
- Agent listing
- Agent loading
- Registry loading
- Agent existence checking
- Error handling
"""

import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
import yaml


class TestListAgents:
    """Tests for list_agents function."""

    @pytest.fixture
    def mock_agents_dir(self, tmp_path: Path) -> Path:
        """Create mock agents directory with YAML files."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        # Create some agent files
        (agents_dir / "agent-one.yaml").write_text("name: agent-one")
        (agents_dir / "agent-two.yaml").write_text("name: agent-two")
        (agents_dir / "agent-three.yaml").write_text("name: agent-three")
        (agents_dir / "agent-registry.yaml").write_text("version: 1.0")

        return agents_dir

    def test_list_agents_returns_sorted(self, mock_agents_dir: Path):
        """Test that agents are returned sorted."""
        with patch("claude.agents.registry.AGENTS_DIR", mock_agents_dir):
            from claude.agents.registry import list_agents

            agents = list_agents()

        assert agents == ["agent-one", "agent-three", "agent-two"]

    def test_list_agents_excludes_registry(self, mock_agents_dir: Path):
        """Test that agent-registry is excluded."""
        with patch("claude.agents.registry.AGENTS_DIR", mock_agents_dir):
            from claude.agents.registry import list_agents

            agents = list_agents()

        assert "agent-registry" not in agents

    def test_list_agents_empty_dir(self, tmp_path: Path):
        """Test with empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with patch("claude.agents.registry.AGENTS_DIR", empty_dir):
            from claude.agents.registry import list_agents

            agents = list_agents()

        assert agents == []


class TestLoadAgent:
    """Tests for load_agent function."""

    @pytest.fixture
    def mock_agents_dir(self, tmp_path: Path) -> Path:
        """Create mock agents directory with agent definitions."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        # Create agent definition
        agent_data = {
            "name": "test-agent",
            "title": "Test Agent",
            "description": "An agent for testing",
            "triggers": ["test", "testing"],
            "capabilities": ["testing", "validation"],
        }
        (agents_dir / "test-agent.yaml").write_text(yaml.dump(agent_data))

        return agents_dir

    def test_load_agent_success(self, mock_agents_dir: Path):
        """Test loading valid agent."""
        with patch("claude.agents.registry.AGENTS_DIR", mock_agents_dir):
            from claude.agents.registry import load_agent

            agent = load_agent("test-agent")

        assert agent["name"] == "test-agent"
        assert agent["title"] == "Test Agent"
        assert "testing" in agent["triggers"]

    def test_load_agent_not_found(self, mock_agents_dir: Path):
        """Test loading non-existent agent."""
        with patch("claude.agents.registry.AGENTS_DIR", mock_agents_dir):
            from claude.agents.registry import load_agent

            with pytest.raises(FileNotFoundError) as excinfo:
                load_agent("nonexistent-agent")

        assert "nonexistent-agent" in str(excinfo.value)


class TestLoadRegistry:
    """Tests for load_registry function."""

    @pytest.fixture
    def mock_agents_dir(self, tmp_path: Path) -> Path:
        """Create mock agents directory with registry."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        # Create registry file
        registry_data = {
            "version": "1.0",
            "agents": {
                "agent-one": {"title": "Agent One"},
                "agent-two": {"title": "Agent Two"},
            },
        }
        (agents_dir / "agent-registry.yaml").write_text(yaml.dump(registry_data))

        return agents_dir

    def test_load_registry_success(self, mock_agents_dir: Path):
        """Test loading registry."""
        with patch("claude.agents.registry.AGENTS_DIR", mock_agents_dir):
            from claude.agents.registry import load_registry

            registry = load_registry()

        assert registry["version"] == "1.0"
        assert "agents" in registry
        assert len(registry["agents"]) == 2

    def test_load_registry_not_found(self, tmp_path: Path):
        """Test loading non-existent registry."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with patch("claude.agents.registry.AGENTS_DIR", empty_dir):
            from claude.agents.registry import load_registry

            with pytest.raises(FileNotFoundError):
                load_registry()


class TestGetAgentCount:
    """Tests for get_agent_count function."""

    @pytest.fixture
    def mock_agents_dir(self, tmp_path: Path) -> Path:
        """Create mock agents directory."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        # Create agent files
        (agents_dir / "agent-one.yaml").write_text("name: agent-one")
        (agents_dir / "agent-two.yaml").write_text("name: agent-two")
        (agents_dir / "agent-three.yaml").write_text("name: agent-three")
        (agents_dir / "agent-registry.yaml").write_text("version: 1.0")

        return agents_dir

    def test_get_agent_count(self, mock_agents_dir: Path):
        """Test getting agent count."""
        with patch("claude.agents.registry.AGENTS_DIR", mock_agents_dir):
            from claude.agents.registry import get_agent_count

            count = get_agent_count()

        # Excludes registry
        assert count == 3

    def test_get_agent_count_empty(self, tmp_path: Path):
        """Test count with empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with patch("claude.agents.registry.AGENTS_DIR", empty_dir):
            from claude.agents.registry import get_agent_count

            count = get_agent_count()

        assert count == 0


class TestAgentExists:
    """Tests for agent_exists function."""

    @pytest.fixture
    def mock_agents_dir(self, tmp_path: Path) -> Path:
        """Create mock agents directory."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        # Create agent file
        (agents_dir / "existing-agent.yaml").write_text("name: existing-agent")

        return agents_dir

    def test_agent_exists_true(self, mock_agents_dir: Path):
        """Test agent that exists."""
        with patch("claude.agents.registry.AGENTS_DIR", mock_agents_dir):
            from claude.agents.registry import agent_exists

            result = agent_exists("existing-agent")

        assert result is True

    def test_agent_exists_false(self, mock_agents_dir: Path):
        """Test agent that doesn't exist."""
        with patch("claude.agents.registry.AGENTS_DIR", mock_agents_dir):
            from claude.agents.registry import agent_exists

            result = agent_exists("nonexistent-agent")

        assert result is False


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_agents_dir_is_path(self):
        """Test that AGENTS_DIR is a Path."""
        from claude.agents.registry import AGENTS_DIR

        assert isinstance(AGENTS_DIR, Path)

    def test_agents_dir_is_agents_module(self):
        """Test that AGENTS_DIR points to agents module."""
        from claude.agents.registry import AGENTS_DIR

        # Should be in claude/agents directory
        assert AGENTS_DIR.name == "agents"


class TestYAMLParsing:
    """Tests for YAML parsing edge cases."""

    @pytest.fixture
    def mock_agents_dir(self, tmp_path: Path) -> Path:
        """Create mock agents directory."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        return agents_dir

    def test_load_agent_complex_yaml(self, mock_agents_dir: Path):
        """Test loading agent with complex YAML structure."""
        complex_data = {
            "name": "complex-agent",
            "title": "Complex Agent",
            "nested": {"key1": "value1", "key2": {"deep": "value"}},
            "list_items": ["item1", "item2", "item3"],
            "multiline": "line1\nline2\nline3",
        }
        (mock_agents_dir / "complex-agent.yaml").write_text(yaml.dump(complex_data))

        with patch("claude.agents.registry.AGENTS_DIR", mock_agents_dir):
            from claude.agents.registry import load_agent

            agent = load_agent("complex-agent")

        assert agent["nested"]["key2"]["deep"] == "value"
        assert len(agent["list_items"]) == 3

    def test_load_agent_unicode(self, mock_agents_dir: Path):
        """Test loading agent with unicode content."""
        unicode_data = {
            "name": "unicode-agent",
            "title": "Unicode Agent",
            "description": "エージェント 🤖",
        }
        (mock_agents_dir / "unicode-agent.yaml").write_text(
            yaml.dump(unicode_data, allow_unicode=True)
        )

        with patch("claude.agents.registry.AGENTS_DIR", mock_agents_dir):
            from claude.agents.registry import load_agent

            agent = load_agent("unicode-agent")

        assert "エージェント" in agent["description"]
        assert "🤖" in agent["description"]


class TestIntegration:
    """Integration tests combining multiple functions."""

    @pytest.fixture
    def full_mock_setup(self, tmp_path: Path) -> Path:
        """Create full mock agent setup."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        # Create registry
        registry_data = {
            "version": "1.0",
            "agents": {
                "agent-alpha": {
                    "title": "Alpha Agent",
                    "description": "First agent",
                },
                "agent-beta": {"title": "Beta Agent", "description": "Second agent"},
            },
        }
        (agents_dir / "agent-registry.yaml").write_text(yaml.dump(registry_data))

        # Create agent files
        for agent_name in registry_data["agents"]:
            agent_data = {
                "name": agent_name,
                "title": registry_data["agents"][agent_name]["title"],
            }
            (agents_dir / f"{agent_name}.yaml").write_text(yaml.dump(agent_data))

        return agents_dir

    def test_list_load_roundtrip(self, full_mock_setup: Path):
        """Test listing agents and then loading each one."""
        with patch("claude.agents.registry.AGENTS_DIR", full_mock_setup):
            from claude.agents.registry import list_agents, load_agent

            agents = list_agents()
            loaded = [load_agent(name) for name in agents]

        assert len(loaded) == 2
        assert all("name" in agent for agent in loaded)

    def test_registry_agents_match_files(self, full_mock_setup: Path):
        """Test that registry agents match available files."""
        with patch("claude.agents.registry.AGENTS_DIR", full_mock_setup):
            from claude.agents.registry import list_agents, load_registry

            registry = load_registry()
            available = set(list_agents())
            registered = set(registry["agents"].keys())

        # All registered agents should be available
        assert registered.issubset(available)
