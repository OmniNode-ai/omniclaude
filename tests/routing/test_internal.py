# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Direct unit tests for _internal/ modules (TriggerMatcher, ConfidenceScorer).

These complement the handler-level integration tests in test_handlers.py by
exercising edge cases in the ported pure-Python logic directly.
"""

from __future__ import annotations

import pytest

from omniclaude.nodes.node_agent_routing_compute._internal import (
    ConfidenceScorer,
    TriggerMatcher,
)
from omniclaude.nodes.node_agent_routing_compute._internal.trigger_matching import (
    HARD_FLOOR,
)

# ── TriggerMatcher ────────────────────────────────────────────────────


def _registry(*agents: tuple[str, list[str]]) -> dict:
    """Build a minimal registry dict for TriggerMatcher."""
    return {
        "agents": {
            name: {"activation_triggers": triggers, "capabilities": []}
            for name, triggers in agents
        }
    }


class TestTriggerMatcherValidation:
    """Registry validation edge cases."""

    def test_missing_agents_key_raises(self) -> None:
        with pytest.raises(ValueError, match="must contain 'agents' key"):
            TriggerMatcher({})

    def test_agents_not_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a dictionary"):
            TriggerMatcher({"agents": ["not", "a", "dict"]})

    def test_non_dict_registry_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a dictionary"):
            TriggerMatcher("not a dict")  # type: ignore[arg-type]

    def test_empty_agents_is_valid(self) -> None:
        matcher = TriggerMatcher({"agents": {}})
        assert matcher.match("anything") == []


class TestTriggerMatcherMatching:
    """Core matching behavior."""

    def test_exact_match_returns_1_0(self) -> None:
        reg = _registry(("agent-debugger", ["debug"]))
        matcher = TriggerMatcher(reg)
        matches = matcher.match("I need to debug this")
        assert len(matches) == 1
        assert matches[0][0] == "agent-debugger"
        assert matches[0][1] == 1.0  # Exact match score

    def test_hard_floor_filters_noise(self) -> None:
        reg = _registry(("agent-xyz", ["xylophone"]))
        matcher = TriggerMatcher(reg)
        matches = matcher.match("xyz")
        # "xyz" vs "xylophone" fuzzy ratio is well below HARD_FLOOR
        assert all(score >= HARD_FLOOR for _, score, _ in matches)

    def test_deterministic_order_for_identical_scores(self) -> None:
        reg = _registry(
            ("agent-zzz", ["testing"]),
            ("agent-aaa", ["testing"]),
        )
        matcher = TriggerMatcher(reg)
        results = [matcher.match("testing")[0][0] for _ in range(5)]
        assert len(set(results)) == 1  # All same agent

    def test_word_boundary_prevents_partial_match(self) -> None:
        reg = _registry(("agent-poly", ["poly"]))
        matcher = TriggerMatcher(reg)
        # "polymorphic architecture" should NOT match "poly" as exact
        # because _is_context_appropriate filters it
        matches = matcher.match("polymorphic architecture is interesting")
        # If it matches, it should be via fuzzy with lower score, not exact
        for _, score, reason in matches:
            assert "Exact match: 'poly'" not in reason

    def test_multi_word_trigger_specificity_bonus(self) -> None:
        reg = _registry(
            ("agent-single", ["debug"]),
            ("agent-multi", ["debug performance"]),
        )
        matcher = TriggerMatcher(reg)
        matches = matcher.match("debug performance issues")
        # Multi-word trigger should get specificity bonus
        agent_scores = {name: score for name, score, _ in matches}
        if "agent-multi" in agent_scores and "agent-single" in agent_scores:
            assert agent_scores["agent-multi"] >= agent_scores["agent-single"]


class TestTriggerMatcherKeywords:
    """Keyword extraction edge cases."""

    def test_stopwords_filtered(self) -> None:
        reg = _registry(("agent-test", ["the"]))
        matcher = TriggerMatcher(reg)
        keywords = matcher._extract_keywords("the quick brown fox")
        assert "the" not in keywords

    def test_technical_tokens_preserved(self) -> None:
        reg = _registry(("agent-test", []))
        matcher = TriggerMatcher(reg)
        keywords = matcher._extract_keywords("deploy to s3 and k8 cluster")
        assert "s3" in keywords
        assert "k8" in keywords


class TestTriggerMatcherFuzzyThresholds:
    """Tiered fuzzy threshold behavior."""

    def test_short_trigger_needs_high_similarity(self) -> None:
        assert TriggerMatcher._fuzzy_threshold("react") == 0.85  # 5 chars

    def test_medium_trigger_moderate_threshold(self) -> None:
        assert TriggerMatcher._fuzzy_threshold("debugging") == 0.78  # 9 chars

    def test_long_trigger_lower_threshold(self) -> None:
        assert TriggerMatcher._fuzzy_threshold("infrastructure") == 0.72  # 14 chars


# ── ConfidenceScorer ──────────────────────────────────────────────────


class TestConfidenceScorer:
    """Direct scorer tests."""

    @pytest.fixture
    def scorer(self) -> ConfidenceScorer:
        return ConfidenceScorer()

    def test_score_returns_all_dimensions(self, scorer: ConfidenceScorer) -> None:
        result = scorer.score(
            agent_name="agent-test",
            agent_data={"capabilities": ["testing"], "domain_context": "general"},
            user_request="run tests",
            context={},
            trigger_score=0.8,
        )
        assert 0.0 <= result.total <= 1.0
        assert result.trigger_score == 0.8
        assert 0.0 <= result.context_score <= 1.0
        assert 0.0 <= result.capability_score <= 1.0
        assert 0.0 <= result.historical_score <= 1.0
        assert result.explanation

    def test_no_capabilities_gives_neutral_score(
        self, scorer: ConfidenceScorer
    ) -> None:
        result = scorer.score(
            agent_name="agent-test",
            agent_data={"capabilities": [], "domain_context": "general"},
            user_request="anything",
            context={},
            trigger_score=0.5,
        )
        assert result.capability_score == 0.5

    def test_matching_capabilities_increase_score(
        self, scorer: ConfidenceScorer
    ) -> None:
        result = scorer.score(
            agent_name="agent-test",
            agent_data={
                "capabilities": ["testing", "debugging"],
                "domain_context": "general",
            },
            user_request="I need testing and debugging help",
            context={},
            trigger_score=0.8,
        )
        assert result.capability_score > 0.5

    def test_domain_match_gives_perfect_context_score(
        self, scorer: ConfidenceScorer
    ) -> None:
        result = scorer.score(
            agent_name="agent-test",
            agent_data={"capabilities": [], "domain_context": "debugging"},
            user_request="anything",
            context={"domain": "debugging"},
            trigger_score=0.5,
        )
        assert result.context_score == 1.0

    def test_domain_mismatch_gives_low_context_score(
        self, scorer: ConfidenceScorer
    ) -> None:
        result = scorer.score(
            agent_name="agent-test",
            agent_data={"capabilities": [], "domain_context": "security"},
            user_request="anything",
            context={"domain": "frontend"},
            trigger_score=0.5,
        )
        assert result.context_score == 0.4

    def test_default_historical_score(self, scorer: ConfidenceScorer) -> None:
        result = scorer.score(
            agent_name="agent-unknown",
            agent_data={"capabilities": [], "domain_context": "general"},
            user_request="anything",
            context={},
            trigger_score=0.5,
        )
        assert result.historical_score == 0.5

    def test_weights_sum_to_one(self) -> None:
        total = (
            ConfidenceScorer.WEIGHT_TRIGGER
            + ConfidenceScorer.WEIGHT_CONTEXT
            + ConfidenceScorer.WEIGHT_CAPABILITY
            + ConfidenceScorer.WEIGHT_HISTORICAL
        )
        assert abs(total - 1.0) < 1e-9
