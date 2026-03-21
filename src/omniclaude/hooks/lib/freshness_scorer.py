# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Freshness scorer for code entity context injection.

Computes freshness scores at query time based on entity age and type.
Uses exponential decay: score = exp(-lambda * age_days) where
lambda = ln(2) / half_life_days.

No numpy — uses math.exp for pure Python computation.

Ported from Archive/omniarchon FreshnessScorer. Adapted to work on
code entities with configurable half-life and entity type adjustments.

Reference: OMN-5681
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any


class FreshnessScorer:
    """Computes freshness scores for code entities at query time.

    All thresholds and adjustments are read from config (contract YAML).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize from contract config.

        Args:
            config: The ``config.code_context.freshness`` dict.
        """
        self._half_life_days: float = config.get("time_decay_half_life_days", 30)
        self._lambda: float = (
            math.log(2) / self._half_life_days if self._half_life_days > 0 else 0.0
        )
        self._entity_adjustments: dict[str, float] = config.get(
            "entity_type_adjustments", {}
        )
        self._thresholds: dict[str, float] = config.get(
            "freshness_thresholds",
            {
                "fresh": 0.8,
                "stale": 0.6,
                "outdated": 0.3,
                "critical": 0.0,
            },
        )
        self._ranking_weight: float = config.get("ranking_weight", 0.15)
        self._enabled: bool = config.get("enabled", True)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def ranking_weight(self) -> float:
        return self._ranking_weight

    def score(
        self,
        updated_at: datetime,
        entity_type: str = "function",
        now: datetime | None = None,
    ) -> float:
        """Compute freshness score for an entity.

        Args:
            updated_at: When the entity was last updated.
            entity_type: Type of entity (class, function, protocol, etc.)
            now: Current time (defaults to utcnow, injectable for testing).

        Returns:
            Freshness score between 0.0 and 1.0.
        """
        if not self._enabled:
            return 1.0

        if now is None:
            now = datetime.now(UTC)

        # Ensure both are timezone-aware
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        age_days = max(0.0, (now - updated_at).total_seconds() / 86400.0)

        # Exponential decay
        raw_score = math.exp(-self._lambda * age_days)

        # Entity type adjustment (multiplicative)
        type_adj = self._entity_adjustments.get(entity_type, 0.5)
        # type_adj is a "stability factor" — higher means slower decay
        # Adjust by blending: final = raw_score ^ (1 / type_adj) for type_adj > 0
        # Simpler: multiply raw by adjustment factor, clamp to [0, 1]
        adjusted = raw_score * (1.0 + (type_adj - 0.5))
        return max(0.0, min(1.0, adjusted))

    def classify(self, freshness_score: float) -> str:
        """Classify freshness level from score.

        Returns one of: "fresh", "stale", "outdated", "critical".
        """
        if freshness_score >= self._thresholds.get("fresh", 0.8):
            return "fresh"
        if freshness_score >= self._thresholds.get("stale", 0.6):
            return "stale"
        if freshness_score >= self._thresholds.get("outdated", 0.3):
            return "outdated"
        return "critical"

    def apply_to_results(
        self,
        results: list[dict[str, Any]],
        *,
        score_key: str = "similarity_score",
        updated_at_key: str = "updated_at",
        entity_type_key: str = "entity_type",
        max_entities: int = 10,
    ) -> list[dict[str, Any]]:
        """Apply freshness adjustment to a list of search results.

        Multiplies each result's score by its freshness score, weighted
        by ranking_weight. Preserves structural match priority.

        Args:
            results: List of result dicts with score and updated_at.
            score_key: Key for the similarity score.
            updated_at_key: Key for the updated_at datetime.
            entity_type_key: Key for the entity type.
            max_entities: Maximum results to return.

        Returns:
            Re-ranked results with freshness_score added.
        """
        if not self._enabled:
            return results[:max_entities]

        now = datetime.now(UTC)
        for r in results:
            updated_at = r.get(updated_at_key)
            if updated_at is None:
                r["freshness_score"] = 1.0
                continue

            if isinstance(updated_at, str):
                updated_at = datetime.fromisoformat(updated_at)

            entity_type = r.get(entity_type_key, "function")
            freshness = self.score(updated_at, entity_type, now=now)
            r["freshness_score"] = freshness

            # Adjust similarity score: blend original with freshness
            original = r.get(score_key, 0.0)
            r[score_key] = (
                original * (1.0 - self._ranking_weight)
                + freshness * self._ranking_weight
            )

        results.sort(key=lambda r: r.get(score_key, 0.0), reverse=True)
        return results[:max_entities]


__all__ = ["FreshnessScorer"]
