"""Comprehensive tests for agent_router module.

Tests cover:
- Router initialization
- Agent routing with confidence scoring
- Explicit agent requests
- Cache behavior
- Trigger matching
- Performance timing
- Error handling
"""

import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
import yaml

from claude.lib.core.agent_router import (
    AgentRecommendation,
    AgentRouter,
    RoutingTiming,
    _get_default_registry_path,
)


class TestGetDefaultRegistryPath:
    """Tests for default registry path resolution."""

    def test_uses_agent_registry_path_env(self):
        """Test AGENT_REGISTRY_PATH environment variable."""
        with patch.dict(os.environ, {"AGENT_REGISTRY_PATH": "/custom/path.yaml"}):
            path = _get_default_registry_path()
            assert path == "/custom/path.yaml"

    def test_uses_registry_path_env(self):
        """Test REGISTRY_PATH environment variable (Docker compat)."""
        with patch.dict(
            os.environ,
            {"REGISTRY_PATH": "/docker/registry.yaml"},
            clear=True,
        ):
            # Clear AGENT_REGISTRY_PATH
            os.environ.pop("AGENT_REGISTRY_PATH", None)
            path = _get_default_registry_path()
            assert path == "/docker/registry.yaml"

    def test_default_path(self):
        """Test default path when no env vars set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AGENT_REGISTRY_PATH", None)
            os.environ.pop("REGISTRY_PATH", None)
            path = _get_default_registry_path()
            assert "agent-registry.yaml" in path
            assert ".claude" in path


class TestAgentRouterInitialization:
    """Tests for AgentRouter initialization."""

    @pytest.fixture
    def sample_registry_file(self, tmp_path: Path) -> Path:
        """Create a sample registry file for testing."""
        registry_data = {
            "version": "1.0",
            "agents": {
                "test-agent": {
                    "title": "Test Agent",
                    "description": "An agent for testing",
                    "triggers": ["test", "testing"],
                    "capabilities": ["testing"],
                    "definition_path": "test-agent.yaml",
                },
                "polymorphic-agent": {
                    "title": "Polymorphic Agent",
                    "description": "Multi-purpose agent",
                    "triggers": ["help", "analyze"],
                    "capabilities": ["general"],
                    "definition_path": "polymorphic-agent.yaml",
                },
            },
        }
        registry_path = tmp_path / "agent-registry.yaml"
        with open(registry_path, "w") as f:
            yaml.dump(registry_data, f)

        # Create agent definition files
        for agent_name in registry_data["agents"]:
            agent_file = tmp_path / f"{agent_name}.yaml"
            with open(agent_file, "w") as f:
                yaml.dump({"name": agent_name}, f)

        return registry_path

    def test_init_with_valid_registry(self, sample_registry_file: Path):
        """Test initialization with valid registry."""
        router = AgentRouter(str(sample_registry_file))

        assert router.registry is not None
        assert "agents" in router.registry
        assert len(router.registry["agents"]) == 2

    def test_init_with_missing_registry(self, tmp_path: Path):
        """Test initialization with missing registry file."""
        with pytest.raises(FileNotFoundError):
            AgentRouter(str(tmp_path / "nonexistent.yaml"))

    def test_init_with_invalid_yaml(self, tmp_path: Path):
        """Test initialization with invalid YAML."""
        invalid_file = tmp_path / "invalid.yaml"
        with open(invalid_file, "w") as f:
            f.write("invalid: yaml: content: [[[")

        with pytest.raises(yaml.YAMLError):
            AgentRouter(str(invalid_file))

    def test_init_stats_initialized(self, sample_registry_file: Path):
        """Test that routing stats are initialized."""
        router = AgentRouter(str(sample_registry_file))

        assert router.routing_stats["total_routes"] == 0
        assert router.routing_stats["cache_hits"] == 0
        assert router.routing_stats["cache_misses"] == 0

    def test_init_cache_ttl(self, sample_registry_file: Path):
        """Test custom cache TTL."""
        router = AgentRouter(str(sample_registry_file), cache_ttl=7200)
        assert router.cache is not None


class TestAgentRouting:
    """Tests for agent routing functionality."""

    @pytest.fixture
    def router(self, tmp_path: Path) -> AgentRouter:
        """Create a router with test registry."""
        registry_data = {
            "version": "1.0",
            "agents": {
                "test-agent": {
                    "title": "Test Agent",
                    "description": "An agent for testing",
                    "triggers": ["test", "testing", "run tests"],
                    "capabilities": ["testing", "validation"],
                    "definition_path": "test-agent.yaml",
                },
                "debug-agent": {
                    "title": "Debug Agent",
                    "description": "An agent for debugging",
                    "triggers": ["debug", "investigate", "trace"],
                    "capabilities": ["debugging", "analysis"],
                    "definition_path": "debug-agent.yaml",
                },
                "polymorphic-agent": {
                    "title": "Polymorphic Agent",
                    "description": "Multi-purpose agent",
                    "triggers": ["help", "analyze", "general"],
                    "capabilities": ["general"],
                    "definition_path": "polymorphic-agent.yaml",
                },
            },
        }
        registry_path = tmp_path / "agent-registry.yaml"
        with open(registry_path, "w") as f:
            yaml.dump(registry_data, f)

        # Create agent definition files
        for agent_name in registry_data["agents"]:
            agent_file = tmp_path / f"{agent_name}.yaml"
            with open(agent_file, "w") as f:
                yaml.dump({"name": agent_name}, f)

        return AgentRouter(str(registry_path))

    def test_route_basic(self, router: AgentRouter):
        """Test basic routing."""
        recommendations = router.route("run the tests")

        # Router may return empty if no triggers match - that's ok for this test
        # What matters is that it returns a list without crashing
        assert isinstance(recommendations, list)
        assert all(isinstance(r, AgentRecommendation) for r in recommendations)

    def test_route_returns_sorted_by_confidence(self, router: AgentRouter):
        """Test that results are sorted by confidence (highest first)."""
        recommendations = router.route("test this code")

        if len(recommendations) > 1:
            for i in range(len(recommendations) - 1):
                assert (
                    recommendations[i].confidence.total
                    >= recommendations[i + 1].confidence.total
                )

    def test_route_max_recommendations(self, router: AgentRouter):
        """Test max_recommendations limit."""
        recommendations = router.route("general task", max_recommendations=1)

        assert len(recommendations) <= 1

    def test_route_empty_request(self, router: AgentRouter):
        """Test routing with empty request."""
        recommendations = router.route("")

        # Should handle gracefully
        assert isinstance(recommendations, list)

    def test_route_updates_stats(self, router: AgentRouter):
        """Test that routing updates statistics."""
        initial_total = router.routing_stats["total_routes"]

        router.route("test request")

        assert router.routing_stats["total_routes"] == initial_total + 1


class TestExplicitAgentRequests:
    """Tests for explicit agent request parsing."""

    @pytest.fixture
    def router(self, tmp_path: Path) -> AgentRouter:
        """Create a router with test registry."""
        registry_data = {
            "version": "1.0",
            "agents": {
                "agent-researcher": {
                    "title": "Researcher Agent",
                    "description": "Research agent",
                    "triggers": ["research"],
                    "capabilities": ["research"],
                    "definition_path": "agent-researcher.yaml",
                },
                "polymorphic-agent": {
                    "title": "Polymorphic Agent",
                    "description": "Multi-purpose agent",
                    "triggers": ["help"],
                    "capabilities": ["general"],
                    "definition_path": "polymorphic-agent.yaml",
                },
            },
        }
        registry_path = tmp_path / "agent-registry.yaml"
        with open(registry_path, "w") as f:
            yaml.dump(registry_data, f)

        for agent_name in registry_data["agents"]:
            agent_file = tmp_path / f"{agent_name}.yaml"
            with open(agent_file, "w") as f:
                yaml.dump({"name": agent_name}, f)

        return AgentRouter(str(registry_path))

    def test_use_agent_pattern(self, router: AgentRouter):
        """Test 'use agent-X' pattern."""
        result = router._extract_explicit_agent("use agent-researcher to help")
        assert result == "agent-researcher"

    def test_at_agent_pattern(self, router: AgentRouter):
        """Test '@agent-X' pattern."""
        result = router._extract_explicit_agent("@agent-researcher analyze this")
        assert result == "agent-researcher"

    def test_agent_at_start_pattern(self, router: AgentRouter):
        """Test 'agent-X' at start pattern."""
        result = router._extract_explicit_agent("agent-researcher do something")
        assert result == "agent-researcher"

    def test_generic_use_agent_pattern(self, router: AgentRouter):
        """Test generic 'use an agent' defaults to polymorphic-agent."""
        result = router._extract_explicit_agent("use an agent to help me")
        assert result == "polymorphic-agent"

    def test_generic_spawn_pattern(self, router: AgentRouter):
        """Test generic 'spawn an agent' pattern."""
        result = router._extract_explicit_agent("spawn an agent for this task")
        assert result == "polymorphic-agent"

    def test_no_explicit_agent(self, router: AgentRouter):
        """Test request without explicit agent."""
        result = router._extract_explicit_agent("help me with this task")
        assert result is None

    def test_nonexistent_agent(self, router: AgentRouter):
        """Test request for non-existent agent."""
        result = router._extract_explicit_agent("use agent-nonexistent")
        assert result is None


class TestCacheBehavior:
    """Tests for routing cache behavior."""

    @pytest.fixture
    def router(self, tmp_path: Path) -> AgentRouter:
        """Create a router with test registry."""
        registry_data = {
            "version": "1.0",
            "agents": {
                "test-agent": {
                    "title": "Test Agent",
                    "description": "Test",
                    "triggers": ["test"],
                    "capabilities": ["testing"],
                    "definition_path": "test-agent.yaml",
                },
            },
        }
        registry_path = tmp_path / "agent-registry.yaml"
        with open(registry_path, "w") as f:
            yaml.dump(registry_data, f)

        agent_file = tmp_path / "test-agent.yaml"
        with open(agent_file, "w") as f:
            yaml.dump({"name": "test-agent"}, f)

        return AgentRouter(str(registry_path))

    def test_cache_hit_on_same_request(self, router: AgentRouter):
        """Test cache hit on repeated request."""
        # First request - cache miss
        router.route("test request")
        assert router.routing_stats["cache_misses"] == 1

        # Second request - cache hit
        router.route("test request")
        assert router.routing_stats["cache_hits"] == 1

    def test_cache_miss_on_different_request(self, router: AgentRouter):
        """Test cache miss on different request."""
        router.route("test request 1")
        router.route("test request 2")

        assert router.routing_stats["cache_misses"] == 2

    def test_invalidate_cache(self, router: AgentRouter):
        """Test cache invalidation."""
        router.route("test request")
        router.invalidate_cache()
        router.route("test request")

        # Should have 2 misses after invalidation
        assert router.routing_stats["cache_misses"] == 2

    def test_cache_with_context(self, router: AgentRouter):
        """Test that context affects caching."""
        router.route("test request", context={"domain": "test"})
        router.route("test request", context={"domain": "production"})

        # Different contexts = different cache entries
        assert router.routing_stats["cache_misses"] == 2


class TestRoutingTiming:
    """Tests for routing timing data."""

    @pytest.fixture
    def router(self, tmp_path: Path) -> AgentRouter:
        """Create a router with test registry."""
        registry_data = {
            "version": "1.0",
            "agents": {
                "test-agent": {
                    "title": "Test Agent",
                    "description": "Test",
                    "triggers": ["test"],
                    "capabilities": ["testing"],
                    "definition_path": "test-agent.yaml",
                },
            },
        }
        registry_path = tmp_path / "agent-registry.yaml"
        with open(registry_path, "w") as f:
            yaml.dump(registry_data, f)

        agent_file = tmp_path / "test-agent.yaml"
        with open(agent_file, "w") as f:
            yaml.dump({"name": "test-agent"}, f)

        return AgentRouter(str(registry_path))

    def test_timing_captured_on_route(self, router: AgentRouter):
        """Test that timing is captured after routing."""
        router.route("test request")

        assert router.last_routing_timing is not None
        assert isinstance(router.last_routing_timing, RoutingTiming)

    def test_timing_has_all_fields(self, router: AgentRouter):
        """Test that timing has all required fields."""
        router.route("test request")

        timing = router.last_routing_timing
        assert timing.total_routing_time_us >= 0
        assert timing.cache_lookup_us >= 0
        assert timing.trigger_matching_us >= 0
        assert timing.confidence_scoring_us >= 0
        assert isinstance(timing.cache_hit, bool)

    def test_cache_hit_timing(self, router: AgentRouter):
        """Test timing for cache hit."""
        router.route("test request")  # Cache miss
        router.route("test request")  # Cache hit

        timing = router.last_routing_timing
        assert timing.cache_hit is True
        assert timing.trigger_matching_us == 0  # Skipped on cache hit


class TestStatistics:
    """Tests for routing statistics."""

    @pytest.fixture
    def router(self, tmp_path: Path) -> AgentRouter:
        """Create a router with test registry."""
        registry_data = {
            "version": "1.0",
            "agents": {
                "test-agent": {
                    "title": "Test Agent",
                    "description": "Test",
                    "triggers": ["test"],
                    "capabilities": ["testing"],
                    "definition_path": "test-agent.yaml",
                },
            },
        }
        registry_path = tmp_path / "agent-registry.yaml"
        with open(registry_path, "w") as f:
            yaml.dump(registry_data, f)

        agent_file = tmp_path / "test-agent.yaml"
        with open(agent_file, "w") as f:
            yaml.dump({"name": "test-agent"}, f)

        return AgentRouter(str(registry_path))

    def test_get_routing_stats(self, router: AgentRouter):
        """Test get_routing_stats method."""
        router.route("request 1")
        router.route("request 1")  # Cache hit
        router.route("request 2")

        stats = router.get_routing_stats()

        assert stats["total_routes"] == 3
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 2
        assert "cache_hit_rate" in stats

    def test_get_cache_stats(self, router: AgentRouter):
        """Test get_cache_stats method."""
        router.route("request 1")

        stats = router.get_cache_stats()

        assert isinstance(stats, dict)
        assert "cache_hit_rate" in stats


class TestReloadRegistry:
    """Tests for registry reloading."""

    def test_reload_registry(self, tmp_path: Path):
        """Test registry reload."""
        # Create initial registry
        registry_data = {
            "version": "1.0",
            "agents": {
                "agent-1": {
                    "title": "Agent 1",
                    "description": "First agent",
                    "triggers": ["one"],
                    "capabilities": ["test"],
                    "definition_path": "agent-1.yaml",
                },
            },
        }
        registry_path = tmp_path / "agent-registry.yaml"
        with open(registry_path, "w") as f:
            yaml.dump(registry_data, f)

        agent_file = tmp_path / "agent-1.yaml"
        with open(agent_file, "w") as f:
            yaml.dump({"name": "agent-1"}, f)

        router = AgentRouter(str(registry_path))
        assert len(router.registry["agents"]) == 1

        # Update registry
        registry_data["agents"]["agent-2"] = {
            "title": "Agent 2",
            "description": "Second agent",
            "triggers": ["two"],
            "capabilities": ["test"],
            "definition_path": "agent-2.yaml",
        }
        with open(registry_path, "w") as f:
            yaml.dump(registry_data, f)

        agent_file2 = tmp_path / "agent-2.yaml"
        with open(agent_file2, "w") as f:
            yaml.dump({"name": "agent-2"}, f)

        # Reload - must pass the path explicitly to avoid loading real registry
        router.reload_registry(str(registry_path))
        assert len(router.registry["agents"]) == 2


class TestAgentRecommendation:
    """Tests for AgentRecommendation dataclass."""

    def test_recommendation_fields(self):
        """Test AgentRecommendation has required fields."""
        from claude.lib.core.confidence_scorer import ConfidenceScore

        rec = AgentRecommendation(
            agent_name="test-agent",
            agent_title="Test Agent",
            confidence=ConfidenceScore(
                total=0.85,
                trigger_score=0.9,
                context_score=0.8,
                capability_score=0.85,
                historical_score=0.85,
                explanation="High match",
            ),
            reason="Matched triggers",
            definition_path="/path/to/agent.yaml",
        )

        assert rec.agent_name == "test-agent"
        assert rec.agent_title == "Test Agent"
        assert rec.confidence.total == 0.85
        assert rec.reason == "Matched triggers"


class TestErrorHandling:
    """Tests for error handling in routing."""

    @pytest.fixture
    def router(self, tmp_path: Path) -> AgentRouter:
        """Create a router with test registry."""
        registry_data = {
            "version": "1.0",
            "agents": {
                "test-agent": {
                    "title": "Test Agent",
                    "description": "Test",
                    "triggers": ["test"],
                    "capabilities": ["testing"],
                    "definition_path": "test-agent.yaml",
                },
            },
        }
        registry_path = tmp_path / "agent-registry.yaml"
        with open(registry_path, "w") as f:
            yaml.dump(registry_data, f)

        agent_file = tmp_path / "test-agent.yaml"
        with open(agent_file, "w") as f:
            yaml.dump({"name": "test-agent"}, f)

        return AgentRouter(str(registry_path))

    def test_graceful_degradation_on_error(self, router: AgentRouter):
        """Test that routing returns empty list on error."""
        # Force an error by breaking internal state
        router.trigger_matcher = None  # type: ignore

        # Should return empty list, not raise
        result = router.route("test request")
        assert result == []
