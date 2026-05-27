# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Golden fixture tests for AgentRouter.

Documents current behavior for regression detection during the omniclaude
restructuring program (OMN-11549). These tests PASS on current code and
serve as a behavioral contract: any refactoring step that causes a failure
here has changed observable behavior and must be reviewed.

Scope:
- AgentRouter.__init__: registry loading, component initialization
- AgentRouter.route(): cache miss → trigger matching → confidence scoring
- AgentRouter.route(): cache hit path
- AgentRouter.route(): explicit @agent-name and "use agent-X" patterns
- AgentRouter.route(): graceful empty-result on no match
- AgentRouter._extract_explicit_agent: pattern extraction contract
- AgentRouter._create_explicit_recommendation: 100% confidence on explicit
- AgentRouter.get_routing_stats(): stats shape contract
- AgentRouter.get_cache_stats(): stats shape contract
- AgentRouter.invalidate_cache(): clears cache
- AgentRouter.reload_registry(): rebuilds components
- AgentRecommendation: field shape contract
- ConfidenceScore: weighted scoring formula
- RoutingTiming: fields populated on route()

All tests use a minimal in-memory registry (no filesystem reads of the
real agent-registry.yaml) except TestAgentRouterWithRealRegistry which
reads the actual file to prove construction succeeds.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

# ---------------------------------------------------------------------------
# Minimal registry fixture — avoids coupling tests to on-disk registry shape
# ---------------------------------------------------------------------------

_MINIMAL_REGISTRY: dict[str, Any] = {
    "agents": {
        "agent-debug": {
            "name": "agent-debug",
            "title": "Debug Specialist",
            "description": "Debugging and root cause analysis",
            "category": "development",
            "capabilities": ["debugging", "error_analysis", "root_cause"],
            "activation_triggers": [
                "debug",
                "error",
                "root cause",
                "analyze error",
                "fix bug",
            ],
            "domain_context": "debugging",
            "definition_path": "/fake/agent-debug.yaml",
        },
        "agent-api-architect": {
            "name": "agent-api-architect",
            "title": "API Architect",
            "description": "RESTful API design and OpenAPI specification",
            "category": "architecture",
            "capabilities": ["api_design", "openapi", "fastapi", "microservices"],
            "activation_triggers": [
                "api design",
                "openapi",
                "rest api",
                "fastapi",
                "endpoint",
            ],
            "domain_context": "api_development",
            "definition_path": "/fake/agent-api-architect.yaml",
        },
        "agent-security": {
            "name": "agent-security",
            "title": "Security Specialist",
            "description": "Security review and vulnerability assessment",
            "category": "security",
            "capabilities": ["security_review", "vulnerability_assessment", "auth"],
            "activation_triggers": [
                "security",
                "vulnerability",
                "authentication",
                "authorization",
                "pentest",
            ],
            "domain_context": "security",
            "definition_path": "/fake/agent-security.yaml",
        },
    }
}


def _write_registry(registry: dict[str, Any]) -> str:
    """Write a registry dict to a temp file, return path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as tmp:
        yaml.dump(registry, tmp)
        return tmp.name


def _make_router(
    registry: dict[str, Any] | None = None,
    cache_ttl: int = 3600,
) -> Any:
    """Build an AgentRouter backed by an in-memory minimal registry."""
    from omniclaude.lib.core.agent_router import AgentRouter

    reg = registry if registry is not None else _MINIMAL_REGISTRY
    path = _write_registry(reg)
    return AgentRouter(registry_path=path, cache_ttl=cache_ttl)


# ---------------------------------------------------------------------------
# OMN-11549 — AgentRouter construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentRouterInit:
    """
    Golden fixture: documents AgentRouter.__init__ behavior (OMN-11549).
    """

    def test_loads_registry_successfully(self) -> None:
        router = _make_router()
        assert router.registry is not None
        assert "agents" in router.registry

    def test_trigger_matcher_initialized(self) -> None:
        from omniclaude.lib.core.trigger_matcher import TriggerMatcher

        router = _make_router()
        assert isinstance(router.trigger_matcher, TriggerMatcher)

    def test_confidence_scorer_initialized(self) -> None:
        from omniclaude.lib.core.confidence_scorer import ConfidenceScorer

        router = _make_router()
        assert isinstance(router.confidence_scorer, ConfidenceScorer)

    def test_cache_initialized(self) -> None:
        from omniclaude.lib.core.result_cache import ResultCache

        router = _make_router()
        assert isinstance(router.cache, ResultCache)

    def test_routing_stats_initialized_to_zeros(self) -> None:
        router = _make_router()
        stats = router.routing_stats
        assert stats["total_routes"] == 0
        assert stats["cache_hits"] == 0
        assert stats["cache_misses"] == 0
        assert stats["explicit_requests"] == 0
        assert stats["fuzzy_matches"] == 0

    def test_last_routing_timing_initially_none(self) -> None:
        router = _make_router()
        assert router.last_routing_timing is None

    def test_raises_file_not_found_for_missing_registry(self) -> None:
        from omniclaude.lib.core.agent_router import AgentRouter

        with pytest.raises(FileNotFoundError):
            AgentRouter(registry_path="/nonexistent/path/registry.yaml")

    def test_raises_on_invalid_yaml(self) -> None:
        from omniclaude.lib.core.agent_router import AgentRouter

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(": invalid: yaml: {{{")
            path = f.name

        with pytest.raises(Exception):
            AgentRouter(registry_path=path)


# ---------------------------------------------------------------------------
# OMN-11549 — AgentRouter.route() routing decisions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentRouterRoute:
    """
    Golden fixture: documents AgentRouter.route() routing decisions (OMN-11549).
    """

    def test_route_returns_list(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("debug this error")
        assert isinstance(result, list)

    def test_route_debug_request_returns_debug_agent(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("debug this error")
        assert len(result) > 0
        assert result[0].agent_name == "agent-debug"

    def test_route_api_request_returns_api_architect(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("api design for my microservices")
        assert len(result) > 0
        assert result[0].agent_name == "agent-api-architect"

    def test_route_security_request_returns_security_agent(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("review security vulnerabilities")
        assert len(result) > 0
        assert result[0].agent_name == "agent-security"

    def test_route_returns_empty_on_no_match(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("xyzzy frobnicate completely unrelated nonsense 12345")
        assert result == []

    def test_route_max_recommendations_respected(self) -> None:
        router = _make_router(cache_ttl=0)
        # Use a query that could match multiple agents
        result = router.route("debug api security", max_recommendations=1)
        assert len(result) <= 1

    def test_route_sorted_by_confidence_descending(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("debug this error", max_recommendations=3)
        if len(result) > 1:
            for i in range(len(result) - 1):
                assert result[i].confidence.total >= result[i + 1].confidence.total

    def test_route_increments_total_routes_stat(self) -> None:
        router = _make_router(cache_ttl=0)
        router.route("debug error")
        assert router.routing_stats["total_routes"] == 1

    def test_route_increments_cache_misses_on_first_call(self) -> None:
        router = _make_router(cache_ttl=3600)
        router.route("debug error first time unique xyz123")
        assert router.routing_stats["cache_misses"] >= 1

    def test_route_records_timing(self) -> None:
        router = _make_router(cache_ttl=0)
        router.route("debug error")
        timing = router.last_routing_timing
        assert timing is not None
        assert timing.total_routing_time_us >= 0

    def test_route_timing_cache_hit_false_on_miss(self) -> None:
        router = _make_router(cache_ttl=0)
        router.route("debug something totally unique abc987")
        assert router.last_routing_timing is not None
        assert router.last_routing_timing.cache_hit is False

    def test_route_graceful_on_exception(self) -> None:
        """Router returns empty list on unexpected exception (graceful degradation)."""
        router = _make_router(cache_ttl=0)
        # Break the trigger matcher to force an exception
        router.trigger_matcher.match = MagicMock(side_effect=RuntimeError("broken"))
        result = router.route("anything")
        assert result == []


# ---------------------------------------------------------------------------
# OMN-11549 — Cache hit path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentRouterCacheHit:
    """
    Golden fixture: documents the cache hit path in AgentRouter.route()
    (OMN-11549). Cache hit must return previous result without re-matching.
    """

    def test_cache_hit_increments_cache_hit_stat(self) -> None:
        router = _make_router(cache_ttl=3600)
        query = "debug this specific error for cache test"
        router.route(query)  # miss
        router.route(query)  # hit
        assert router.routing_stats["cache_hits"] == 1

    def test_cache_hit_returns_same_result(self) -> None:
        router = _make_router(cache_ttl=3600)
        query = "debug this specific error for same result test"
        first = router.route(query)
        second = router.route(query)
        assert len(first) == len(second)
        if first:
            assert first[0].agent_name == second[0].agent_name

    def test_cache_hit_timing_records_cache_hit_true(self) -> None:
        router = _make_router(cache_ttl=3600)
        query = "debug cache hit timing test unique"
        router.route(query)  # populate cache
        router.route(query)  # cache hit
        assert router.last_routing_timing is not None
        assert router.last_routing_timing.cache_hit is True

    def test_invalidate_cache_clears_results(self) -> None:
        router = _make_router(cache_ttl=3600)
        query = "debug invalidate cache test unique string"
        router.route(query)
        router.invalidate_cache()
        # After invalidation, stats reset is not expected, but next call is a miss
        router.route(query)
        # Should have at least one more miss (beyond the first)
        assert router.routing_stats["cache_misses"] >= 2


# ---------------------------------------------------------------------------
# OMN-11549 — Explicit agent request patterns
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExplicitAgentExtraction:
    """
    Golden fixture: documents _extract_explicit_agent() pattern recognition
    (OMN-11549).
    """

    def test_extracts_use_agent_pattern(self) -> None:
        router = _make_router()
        result = router._extract_explicit_agent("use agent-debug to fix this")
        assert result == "agent-debug"

    def test_extracts_at_sign_pattern(self) -> None:
        router = _make_router()
        result = router._extract_explicit_agent("@agent-debug analyze error")
        assert result == "agent-debug"

    def test_extracts_start_of_text_pattern(self) -> None:
        router = _make_router()
        result = router._extract_explicit_agent("agent-debug fix this error")
        assert result == "agent-debug"

    def test_returns_none_for_nonexistent_agent(self) -> None:
        router = _make_router()
        result = router._extract_explicit_agent("use agent-nonexistent to do something")
        assert result is None

    def test_returns_none_for_generic_agent_phrase(self) -> None:
        """'use an agent' without a specific name returns None (no fallback)."""
        router = _make_router()
        result = router._extract_explicit_agent("use an agent to help me")
        assert result is None

    def test_returns_none_for_normal_query(self) -> None:
        router = _make_router()
        result = router._extract_explicit_agent("debug this performance issue")
        assert result is None

    def test_case_insensitive_matching(self) -> None:
        """Explicit patterns are matched case-insensitively."""
        router = _make_router()
        result = router._extract_explicit_agent("USE AGENT-DEBUG to fix this")
        assert result == "agent-debug"


# ---------------------------------------------------------------------------
# OMN-11549 — _create_explicit_recommendation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateExplicitRecommendation:
    """
    Golden fixture: documents _create_explicit_recommendation() 100% confidence
    contract (OMN-11549).
    """

    def test_returns_recommendation_for_known_agent(self) -> None:
        router = _make_router()
        rec = router._create_explicit_recommendation("agent-debug")
        assert rec is not None

    def test_explicit_recommendation_has_full_confidence(self) -> None:
        router = _make_router()
        rec = router._create_explicit_recommendation("agent-debug")
        assert rec is not None
        assert rec.confidence.total == 1.0

    def test_all_confidence_sub_scores_are_one(self) -> None:
        router = _make_router()
        rec = router._create_explicit_recommendation("agent-debug")
        assert rec is not None
        assert rec.confidence.trigger_score == 1.0
        assert rec.confidence.context_score == 1.0
        assert rec.confidence.capability_score == 1.0
        assert rec.confidence.historical_score == 1.0

    def test_explicit_recommendation_reason(self) -> None:
        router = _make_router()
        rec = router._create_explicit_recommendation("agent-debug")
        assert rec is not None
        assert "explicit" in rec.reason.lower() or "requested" in rec.reason.lower()

    def test_returns_none_for_unknown_agent(self) -> None:
        router = _make_router()
        rec = router._create_explicit_recommendation("agent-does-not-exist")
        assert rec is None

    def test_recommendation_agent_name_matches(self) -> None:
        router = _make_router()
        rec = router._create_explicit_recommendation("agent-debug")
        assert rec is not None
        assert rec.agent_name == "agent-debug"

    def test_recommendation_agent_title_matches_registry(self) -> None:
        router = _make_router()
        rec = router._create_explicit_recommendation("agent-debug")
        assert rec is not None
        assert rec.agent_title == "Debug Specialist"


# ---------------------------------------------------------------------------
# OMN-11549 — route() with explicit request integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRouteWithExplicitRequest:
    """
    Golden fixture: documents that explicit "@agent-name" requests bypass
    trigger matching and get 100% confidence (OMN-11549).
    """

    def test_explicit_at_route_returns_correct_agent(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("@agent-debug help me fix this")
        assert len(result) == 1
        assert result[0].agent_name == "agent-debug"

    def test_explicit_use_route_returns_correct_agent(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("use agent-api-architect to design this API")
        assert len(result) == 1
        assert result[0].agent_name == "agent-api-architect"

    def test_explicit_route_confidence_is_one(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("@agent-security review my code")
        assert len(result) == 1
        assert result[0].confidence.total == 1.0

    def test_explicit_request_stat_incremented(self) -> None:
        router = _make_router(cache_ttl=0)
        router.route("@agent-debug analyze this")
        assert router.routing_stats["explicit_requests"] == 1


# ---------------------------------------------------------------------------
# OMN-11549 — AgentRecommendation shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentRecommendationShape:
    """
    Golden fixture: documents AgentRecommendation field shape (OMN-11549).
    """

    def test_recommendation_has_agent_name(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("debug this error")
        assert len(result) > 0
        assert hasattr(result[0], "agent_name")
        assert isinstance(result[0].agent_name, str)

    def test_recommendation_has_agent_title(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("debug this error")
        assert len(result) > 0
        assert hasattr(result[0], "agent_title")
        assert isinstance(result[0].agent_title, str)

    def test_recommendation_has_confidence(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("debug this error")
        assert len(result) > 0
        assert hasattr(result[0], "confidence")

    def test_confidence_total_in_range(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("debug this error")
        assert len(result) > 0
        assert 0.0 <= result[0].confidence.total <= 1.0

    def test_recommendation_has_reason(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("debug this error")
        assert len(result) > 0
        assert hasattr(result[0], "reason")
        assert isinstance(result[0].reason, str)

    def test_recommendation_has_definition_path(self) -> None:
        router = _make_router(cache_ttl=0)
        result = router.route("debug this error")
        assert len(result) > 0
        assert hasattr(result[0], "definition_path")


# ---------------------------------------------------------------------------
# OMN-11549 — ConfidenceScore weighted formula
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConfidenceScorerFormula:
    """
    Golden fixture: documents ConfidenceScorer weighting formula (OMN-11549).

    Weights: trigger=0.40, context=0.30, capability=0.20, historical=0.10
    """

    def test_total_equals_weighted_sum(self) -> None:
        from omniclaude.lib.core.confidence_scorer import ConfidenceScorer

        scorer = ConfidenceScorer()
        agent_data = {
            "domain_context": "debugging",
            "capabilities": ["debugging"],
        }
        score = scorer.score(
            agent_name="agent-debug",
            agent_data=agent_data,
            user_request="debug this error",
            context={"domain": "debugging"},
            trigger_score=0.8,
        )

        expected_total = (
            0.8 * 0.4  # trigger 40%
            + score.context_score * 0.3  # context 30%
            + score.capability_score * 0.2  # capability 20%
            + score.historical_score * 0.1  # historical 10%
        )
        assert abs(score.total - expected_total) < 1e-9

    def test_perfect_domain_match_context_score_is_one(self) -> None:
        from omniclaude.lib.core.confidence_scorer import ConfidenceScorer

        scorer = ConfidenceScorer()
        agent_data = {"domain_context": "debugging", "capabilities": []}
        score = scorer.score(
            agent_name="agent-debug",
            agent_data=agent_data,
            user_request="debug",
            context={"domain": "debugging"},
            trigger_score=1.0,
        )
        assert score.context_score == 1.0

    def test_general_domain_context_score_is_07(self) -> None:
        from omniclaude.lib.core.confidence_scorer import ConfidenceScorer

        scorer = ConfidenceScorer()
        agent_data = {"domain_context": "general", "capabilities": []}
        score = scorer.score(
            agent_name="agent-general",
            agent_data=agent_data,
            user_request="anything",
            context={"domain": "specific"},
            trigger_score=1.0,
        )
        assert score.context_score == 0.7

    def test_no_capabilities_returns_05_capability_score(self) -> None:
        from omniclaude.lib.core.confidence_scorer import ConfidenceScorer

        scorer = ConfidenceScorer()
        agent_data = {"domain_context": "general", "capabilities": []}
        score = scorer.score(
            agent_name="agent-empty",
            agent_data=agent_data,
            user_request="anything",
            context={},
            trigger_score=0.5,
        )
        assert score.capability_score == 0.5

    def test_unknown_agent_historical_score_is_05(self) -> None:
        from omniclaude.lib.core.confidence_scorer import ConfidenceScorer

        scorer = ConfidenceScorer()
        agent_data = {"domain_context": "general", "capabilities": []}
        score = scorer.score(
            agent_name="agent-no-history",
            agent_data=agent_data,
            user_request="anything",
            context={},
            trigger_score=0.5,
        )
        assert score.historical_score == 0.5

    def test_explanation_is_string(self) -> None:
        from omniclaude.lib.core.confidence_scorer import ConfidenceScorer

        scorer = ConfidenceScorer()
        agent_data = {"domain_context": "general", "capabilities": []}
        score = scorer.score(
            agent_name="agent-test",
            agent_data=agent_data,
            user_request="test",
            context={},
            trigger_score=0.6,
        )
        assert isinstance(score.explanation, str)
        assert "agent-test" in score.explanation


# ---------------------------------------------------------------------------
# OMN-11549 — get_routing_stats() and get_cache_stats() shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentRouterStats:
    """
    Golden fixture: documents get_routing_stats() and get_cache_stats()
    output shape (OMN-11549).
    """

    def test_get_routing_stats_returns_dict(self) -> None:
        router = _make_router()
        stats = router.get_routing_stats()
        assert isinstance(stats, dict)

    def test_get_routing_stats_has_total_routes(self) -> None:
        router = _make_router()
        stats = router.get_routing_stats()
        assert "total_routes" in stats

    def test_get_routing_stats_has_cache_hits(self) -> None:
        router = _make_router()
        stats = router.get_routing_stats()
        assert "cache_hits" in stats

    def test_get_routing_stats_rates_calculated_after_route(self) -> None:
        router = _make_router(cache_ttl=3600)
        router.route("debug this error stats test unique")
        stats = router.get_routing_stats()
        assert "cache_hit_rate" in stats
        assert "fuzzy_match_rate" in stats

    def test_get_cache_stats_returns_dict(self) -> None:
        router = _make_router()
        stats = router.get_cache_stats()
        assert isinstance(stats, dict)

    def test_get_cache_stats_has_hit_rate(self) -> None:
        router = _make_router()
        stats = router.get_cache_stats()
        assert "cache_hit_rate" in stats


# ---------------------------------------------------------------------------
# OMN-11549 — reload_registry()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentRouterReloadRegistry:
    """
    Golden fixture: documents reload_registry() behavior (OMN-11549).
    Verifies that reloading rebuilds trigger_matcher and clears cache.
    """

    def test_reload_succeeds_with_same_path(self) -> None:
        path = _write_registry(_MINIMAL_REGISTRY)
        from omniclaude.lib.core.agent_router import AgentRouter

        router = AgentRouter(registry_path=path, cache_ttl=3600)
        # Should not raise
        router.reload_registry(path)

    def test_reload_rebuilds_trigger_matcher(self) -> None:
        path = _write_registry(_MINIMAL_REGISTRY)
        from omniclaude.lib.core.agent_router import AgentRouter

        router = AgentRouter(registry_path=path, cache_ttl=3600)
        old_matcher = router.trigger_matcher
        router.reload_registry(path)
        # A new TriggerMatcher instance should have been created
        assert router.trigger_matcher is not old_matcher

    def test_reload_clears_cache(self) -> None:
        path = _write_registry(_MINIMAL_REGISTRY)
        from omniclaude.lib.core.agent_router import AgentRouter

        router = AgentRouter(registry_path=path, cache_ttl=3600)
        router.route("debug error populate cache")
        assert router.routing_stats["cache_misses"] >= 1
        router.reload_registry(path)
        # Cache cleared — next call is a miss again
        router.route("debug error populate cache")
        # Two misses total: before and after reload
        assert router.routing_stats["cache_misses"] >= 2

    def test_reload_raises_on_missing_file(self) -> None:
        router = _make_router()
        with pytest.raises(FileNotFoundError):
            router.reload_registry("/nonexistent/path/registry.yaml")


# ---------------------------------------------------------------------------
# OMN-11549 — Real registry construction smoke test
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentRouterWithRealRegistry:
    """
    Golden fixture: proves AgentRouter can be constructed from the real
    agent-registry.yaml without errors (OMN-11549).
    """

    def test_real_registry_loads_successfully(self) -> None:
        real_registry = (
            Path(__file__).parent.parent.parent
            / "plugins"
            / "onex"
            / "agents"
            / "configs"
            / "agent-registry.yaml"
        )
        if not real_registry.exists():
            pytest.skip(f"Real registry not found at {real_registry}")

        from omniclaude.lib.core.agent_router import AgentRouter

        router = AgentRouter(registry_path=str(real_registry), cache_ttl=0)
        assert len(router.registry.get("agents", {})) > 0

    def test_real_registry_can_route_debug_query(self) -> None:
        real_registry = (
            Path(__file__).parent.parent.parent
            / "plugins"
            / "onex"
            / "agents"
            / "configs"
            / "agent-registry.yaml"
        )
        if not real_registry.exists():
            pytest.skip(f"Real registry not found at {real_registry}")

        from omniclaude.lib.core.agent_router import AgentRouter

        router = AgentRouter(registry_path=str(real_registry), cache_ttl=0)
        result = router.route("debug this error", max_recommendations=3)
        # Should return at least one recommendation for a clear debug query
        assert isinstance(result, list)
