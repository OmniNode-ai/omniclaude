# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for freshness scorer (OMN-5681)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from omniclaude.hooks.lib.freshness_scorer import FreshnessScorer

DEFAULT_CONFIG = {
    "enabled": True,
    "time_decay_half_life_days": 30,
    "entity_type_adjustments": {
        "class": 0.8,
        "function": 0.6,
        "protocol": 0.9,
        "model": 0.7,
        "import": 1.0,
    },
    "freshness_thresholds": {
        "fresh": 0.8,
        "stale": 0.6,
        "outdated": 0.3,
        "critical": 0.0,
    },
    "ranking_weight": 0.15,
}


@pytest.mark.unit
class TestFreshnessScorer:
    """Tests for FreshnessScorer."""

    def test_recent_entity_scores_high(self) -> None:
        """Entity updated 5 days ago should score high (~0.9)."""
        scorer = FreshnessScorer(DEFAULT_CONFIG)
        now = datetime.now(UTC)
        updated = now - timedelta(days=5)
        score = scorer.score(updated, "function", now=now)
        assert score > 0.7, f"5-day-old function should score > 0.7, got {score}"

    def test_old_entity_scores_low(self) -> None:
        """Entity updated 60 days ago should score lower."""
        scorer = FreshnessScorer(DEFAULT_CONFIG)
        now = datetime.now(UTC)
        updated = now - timedelta(days=60)
        score = scorer.score(updated, "function", now=now)
        assert score < 0.5, f"60-day-old function should score < 0.5, got {score}"

    def test_ranking_integration(self) -> None:
        """Two entities with equal similarity but different ages — fresher ranks higher."""
        scorer = FreshnessScorer(DEFAULT_CONFIG)
        now = datetime.now(UTC)

        results = [
            {
                "entity_id": "old",
                "similarity_score": 0.9,
                "updated_at": (now - timedelta(days=60)).isoformat(),
                "entity_type": "function",
            },
            {
                "entity_id": "fresh",
                "similarity_score": 0.9,
                "updated_at": (now - timedelta(days=2)).isoformat(),
                "entity_type": "function",
            },
        ]

        ranked = scorer.apply_to_results(results)
        assert ranked[0]["entity_id"] == "fresh"
        assert ranked[1]["entity_id"] == "old"
        assert ranked[0]["freshness_score"] > ranked[1]["freshness_score"]

    def test_disabled_returns_one(self) -> None:
        """Disabled scorer returns 1.0."""
        config = {**DEFAULT_CONFIG, "enabled": False}
        scorer = FreshnessScorer(config)
        now = datetime.now(UTC)
        score = scorer.score(now - timedelta(days=100), "function", now=now)
        assert score == 1.0

    def test_classify_levels(self) -> None:
        """Verify freshness level classification."""
        scorer = FreshnessScorer(DEFAULT_CONFIG)
        assert scorer.classify(0.9) == "fresh"
        assert scorer.classify(0.7) == "stale"
        assert scorer.classify(0.4) == "outdated"
        assert scorer.classify(0.1) == "critical"
