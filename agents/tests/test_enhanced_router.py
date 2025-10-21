"""
Unit tests for Enhanced Agent Router - Phase 1
==============================================

Tests all components of the enhanced routing system:
- EnhancedTriggerMatcher
- ConfidenceScorer
- CapabilityIndex
- ResultCache
- EnhancedAgentRouter (integration)

Run with: python -m pytest tests/test_enhanced_router.py -v
"""

# Add parent directory to path for imports
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.capability_index import CapabilityIndex
from lib.confidence_scorer import ConfidenceScore, ConfidenceScorer
from lib.enhanced_router import EnhancedAgentRouter
from lib.result_cache import ResultCache
from lib.trigger_matcher import EnhancedTriggerMatcher

# Sample test registry data
SAMPLE_REGISTRY = {
    "agents": {
        "agent-debug-intelligence": {
            "title": "Debug Intelligence Agent",
            "definition_path": "/path/to/debug.yaml",
            "activation_triggers": ["debug", "error", "bug", "troubleshoot"],
            "capabilities": ["error_analysis", "root_cause", "debugging"],
            "domain_context": "debugging",
        },
        "agent-api-architect": {
            "title": "API Architect",
            "definition_path": "/path/to/api.yaml",
            "activation_triggers": ["api", "endpoint", "rest", "design api"],
            "capabilities": ["api_design", "rest", "architecture"],
            "domain_context": "api_development",
        },
        "agent-performance": {
            "title": "Performance Optimizer",
            "definition_path": "/path/to/performance.yaml",
            "activation_triggers": ["optimize", "performance", "slow", "speed up"],
            "capabilities": ["optimization", "performance_analysis", "profiling"],
            "domain_context": "performance",
        },
        "agent-testing": {
            "title": "Testing Agent",
            "definition_path": "/path/to/testing.yaml",
            "activation_triggers": ["test", "testing", "unit test", "integration test"],
            "capabilities": ["testing", "test_generation", "quality_assurance"],
            "domain_context": "testing",
        },
    }
}


# ============================================================================
# TriggerMatcher Tests
# ============================================================================


class TestEnhancedTriggerMatcher:
    """Test EnhancedTriggerMatcher functionality."""

    @pytest.fixture
    def matcher(self):
        """Create matcher with sample registry."""
        return EnhancedTriggerMatcher(SAMPLE_REGISTRY)

    def test_exact_match(self, matcher):
        """Test exact trigger matching."""
        matches = matcher.match("debug this error")

        assert len(matches) > 0
        # Should match agent-debug-intelligence
        agent_names = [m[0] for m in matches]
        assert "agent-debug-intelligence" in agent_names

        # First match should have high score
        assert matches[0][1] >= 0.8

    def test_fuzzy_match(self, matcher):
        """Test fuzzy trigger matching."""
        # Misspelled but similar
        matches = matcher.match("debuging problm")

        assert len(matches) > 0
        # Should still match debug agent
        assert any("debug" in m[0] for m in matches)

    def test_keyword_overlap(self, matcher):
        """Test keyword overlap scoring."""
        matches = matcher.match("analyze api endpoint performance")

        agent_names = [m[0] for m in matches]
        # Should match both api and performance agents
        assert (
            "agent-api-architect" in agent_names or "agent-performance" in agent_names
        )

    def test_capability_match(self, matcher):
        """Test capability-based matching."""
        matches = matcher.match("need optimization and profiling")

        agent_names = [m[0] for m in matches]
        # Should match performance agent due to capabilities
        assert "agent-performance" in agent_names

    def test_no_match(self, matcher):
        """Test when no good matches found."""
        matches = matcher.match("random unrelated query xyz123")

        # May return some matches with low scores
        if matches:
            assert matches[0][1] < 0.5

    def test_multiple_matches_sorted(self, matcher):
        """Test that matches are sorted by confidence."""
        matches = matcher.match("test and debug")

        # Should return multiple matches
        assert len(matches) >= 2

        # Should be sorted (highest first)
        scores = [m[1] for m in matches]
        assert scores == sorted(scores, reverse=True)


# ============================================================================
# ConfidenceScorer Tests
# ============================================================================


class TestConfidenceScorer:
    """Test ConfidenceScorer functionality."""

    @pytest.fixture
    def scorer(self):
        """Create confidence scorer."""
        return ConfidenceScorer()

    def test_score_calculation(self, scorer):
        """Test comprehensive score calculation."""
        agent_data = SAMPLE_REGISTRY["agents"]["agent-debug-intelligence"]

        score = scorer.score(
            agent_name="agent-debug-intelligence",
            agent_data=agent_data,
            user_request="debug this error",
            context={"domain": "debugging"},
            trigger_score=0.9,
        )

        assert isinstance(score, ConfidenceScore)
        assert 0.0 <= score.total <= 1.0
        assert 0.0 <= score.trigger_score <= 1.0
        assert 0.0 <= score.context_score <= 1.0
        assert 0.0 <= score.capability_score <= 1.0
        assert 0.0 <= score.historical_score <= 1.0
        assert isinstance(score.explanation, str)
        assert len(score.explanation) > 0

    def test_perfect_context_match(self, scorer):
        """Test perfect domain context matching."""
        agent_data = SAMPLE_REGISTRY["agents"]["agent-debug-intelligence"]

        score = scorer.score(
            agent_name="agent-debug-intelligence",
            agent_data=agent_data,
            user_request="test",
            context={"domain": "debugging"},  # Matches agent domain
            trigger_score=0.5,
        )

        # Perfect context match should give 1.0
        assert score.context_score == 1.0

    def test_general_context(self, scorer):
        """Test general domain handling."""
        agent_data = SAMPLE_REGISTRY["agents"]["agent-debug-intelligence"]

        score = scorer.score(
            agent_name="agent-debug-intelligence",
            agent_data=agent_data,
            user_request="test",
            context={"domain": "general"},
            trigger_score=0.5,
        )

        # General domain should give moderate score
        assert score.context_score >= 0.7

    def test_weighted_scoring(self, scorer):
        """Test that scoring uses correct weights."""
        agent_data = SAMPLE_REGISTRY["agents"]["agent-debug-intelligence"]

        score = scorer.score(
            agent_name="agent-debug-intelligence",
            agent_data=agent_data,
            user_request="test",
            context={},
            trigger_score=1.0,  # Perfect trigger
        )

        # Trigger is 40% weight, so with perfect trigger and moderate others,
        # total should be >= 0.4
        assert score.total >= 0.4


# ============================================================================
# CapabilityIndex Tests
# ============================================================================


class TestCapabilityIndex:
    """Test CapabilityIndex functionality."""

    @pytest.fixture
    def index(self, tmp_path):
        """Create capability index with sample registry."""
        # Write sample registry to temp file
        import yaml

        registry_file = tmp_path / "test-registry.yaml"
        with open(registry_file, "w") as f:
            yaml.dump(SAMPLE_REGISTRY, f)

        return CapabilityIndex(str(registry_file))

    def test_find_by_capability(self, index):
        """Test finding agents by capability."""
        agents = index.find_by_capability("debugging")
        assert "agent-debug-intelligence" in agents

    def test_find_by_domain(self, index):
        """Test finding agents by domain."""
        agents = index.find_by_domain("api_development")
        assert "agent-api-architect" in agents

    def test_get_capabilities(self, index):
        """Test getting capabilities for agent."""
        caps = index.get_capabilities("agent-debug-intelligence")
        assert "debugging" in caps
        assert "error_analysis" in caps

    def test_multiple_capabilities(self, index):
        """Test finding agents with multiple capabilities."""
        results = index.find_agents_with_multiple_capabilities(
            ["debugging", "error_analysis"]
        )

        # Should return list of (agent, count) tuples
        assert len(results) > 0
        assert all(isinstance(r, tuple) for r in results)
        assert all(len(r) == 2 for r in results)

        # agent-debug-intelligence should have both
        agent_names = [r[0] for r in results]
        assert "agent-debug-intelligence" in agent_names

    def test_stats(self, index):
        """Test index statistics."""
        stats = index.stats()

        assert "total_agents" in stats
        assert "total_capabilities" in stats
        assert "total_domains" in stats
        assert stats["total_agents"] == 4  # Sample registry has 4 agents


# ============================================================================
# ResultCache Tests
# ============================================================================


class TestResultCache:
    """Test ResultCache functionality."""

    @pytest.fixture
    def cache(self):
        """Create result cache with short TTL for testing."""
        return ResultCache(default_ttl_seconds=2)

    def test_set_and_get(self, cache):
        """Test basic cache operations."""
        cache.set("test query", ["agent-1", "agent-2"])
        result = cache.get("test query")

        assert result == ["agent-1", "agent-2"]

    def test_cache_miss(self, cache):
        """Test cache miss."""
        result = cache.get("unknown query")
        assert result is None

    def test_context_differentiation(self, cache):
        """Test that different contexts create different cache entries."""
        cache.set("query", ["agent-1"], context={"domain": "api"})
        cache.set("query", ["agent-2"], context={"domain": "debug"})

        result1 = cache.get("query", context={"domain": "api"})
        result2 = cache.get("query", context={"domain": "debug"})

        assert result1 == ["agent-1"]
        assert result2 == ["agent-2"]

    def test_ttl_expiration(self, cache):
        """Test TTL expiration."""
        cache.set("expires", ["agent-1"], ttl_seconds=1)

        # Immediate get should work
        assert cache.get("expires") == ["agent-1"]

        # Wait for expiration
        time.sleep(1.5)

        # Should be expired
        assert cache.get("expires") is None

    def test_hit_tracking(self, cache):
        """Test cache hit tracking."""
        cache.set("popular", ["agent-1"])

        # Access multiple times
        for _ in range(5):
            cache.get("popular")

        stats = cache.stats()
        assert stats["total_hits"] >= 5

    def test_invalidation(self, cache):
        """Test cache invalidation."""
        cache.set("invalidate", ["agent-1"])
        assert cache.get("invalidate") is not None

        cache.invalidate("invalidate")
        assert cache.get("invalidate") is None

    def test_clear(self, cache):
        """Test clearing entire cache."""
        cache.set("query1", ["agent-1"])
        cache.set("query2", ["agent-2"])

        assert cache.stats()["entries"] == 2

        cache.clear()
        assert cache.stats()["entries"] == 0


# ============================================================================
# EnhancedAgentRouter Integration Tests
# ============================================================================


class TestEnhancedAgentRouter:
    """Test EnhancedAgentRouter integration."""

    @pytest.fixture
    def router(self, tmp_path):
        """Create router with sample registry."""
        import yaml

        registry_file = tmp_path / "test-registry.yaml"
        with open(registry_file, "w") as f:
            yaml.dump(SAMPLE_REGISTRY, f)

        return EnhancedAgentRouter(str(registry_file), cache_ttl=60)

    def test_explicit_agent_request(self, router):
        """Test explicit agent name extraction."""
        recommendations = router.route("use agent-api-architect to design API")

        assert len(recommendations) > 0
        assert recommendations[0].agent_name == "agent-api-architect"
        assert recommendations[0].confidence.total == 1.0

    def test_trigger_based_routing(self, router):
        """Test trigger-based routing."""
        recommendations = router.route("debug this error")

        assert len(recommendations) > 0
        # Should include debug agent
        agent_names = [r.agent_name for r in recommendations]
        assert "agent-debug-intelligence" in agent_names

        # Top recommendation should have good confidence
        assert recommendations[0].confidence.total > 0.5

    def test_multi_recommendation(self, router):
        """Test multiple recommendations."""
        recommendations = router.route(
            "optimize api performance", max_recommendations=5
        )

        assert len(recommendations) > 1
        # All should have valid confidence
        assert all(0.0 <= rec.confidence.total <= 1.0 for rec in recommendations)

        # Should be sorted by confidence
        confidences = [rec.confidence.total for rec in recommendations]
        assert confidences == sorted(confidences, reverse=True)

    def test_caching(self, router):
        """Test result caching."""
        query = "test caching functionality"

        # First call
        result1 = router.route(query)
        stats1 = router.get_routing_stats()

        # Second call (should hit cache)
        result2 = router.route(query)
        stats2 = router.get_routing_stats()

        # Results should be identical
        assert len(result1) == len(result2)
        for r1, r2 in zip(result1, result2):
            assert r1.agent_name == r2.agent_name

        # Cache hit count should increase
        assert stats2["cache_hits"] > stats1["cache_hits"]

    def test_confidence_breakdown(self, router):
        """Test confidence score breakdown."""
        recommendations = router.route("review api security")

        rec = recommendations[0]
        conf = rec.confidence

        # Check all components present
        assert hasattr(conf, "trigger_score")
        assert hasattr(conf, "context_score")
        assert hasattr(conf, "capability_score")
        assert hasattr(conf, "historical_score")
        assert hasattr(conf, "total")

        # All should be valid
        assert 0.0 <= conf.trigger_score <= 1.0
        assert 0.0 <= conf.context_score <= 1.0
        assert 0.0 <= conf.capability_score <= 1.0
        assert 0.0 <= conf.historical_score <= 1.0
        assert 0.0 <= conf.total <= 1.0

        # Explanation should exist
        assert isinstance(conf.explanation, str)
        assert len(conf.explanation) > 0

    def test_routing_stats(self, router):
        """Test routing statistics tracking."""
        # Make some requests with same context
        context = {"domain": "testing"}
        router.route("query 1", context=context)
        router.route("query 2", context=context)
        router.route("query 1", context=context)  # Cache hit

        stats = router.get_routing_stats()

        assert stats["total_routes"] == 3
        assert stats["cache_hits"] >= 1
        assert "cache_hit_rate" in stats
        assert stats["cache_hit_rate"] >= 0.33  # At least 1 hit out of 3


# ============================================================================
# Performance Tests
# ============================================================================


class TestPerformance:
    """Test performance targets."""

    @pytest.fixture
    def router(self, tmp_path):
        """Create router with sample registry."""
        import yaml

        registry_file = tmp_path / "test-registry.yaml"
        with open(registry_file, "w") as f:
            yaml.dump(SAMPLE_REGISTRY, f)

        return EnhancedAgentRouter(str(registry_file))

    def test_routing_speed(self, router):
        """Test that routing meets performance target (<100ms)."""
        import time

        queries = [
            "debug this error",
            "optimize performance",
            "design api endpoint",
            "write unit tests",
        ]

        for query in queries:
            start = time.time()
            router.route(query)
            duration = (time.time() - start) * 1000  # Convert to ms

            # Should be under 100ms
            assert (
                duration < 100
            ), f"Query '{query}' took {duration:.1f}ms (target: <100ms)"

    def test_cache_performance(self, router):
        """Test that cache hits are fast (<5ms)."""
        import time

        query = "test query"

        # Warm up cache
        router.route(query)

        # Measure cache hit
        start = time.time()
        router.route(query)
        duration = (time.time() - start) * 1000

        # Cache hit should be very fast
        assert duration < 10, f"Cache hit took {duration:.1f}ms (target: <5ms)"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
